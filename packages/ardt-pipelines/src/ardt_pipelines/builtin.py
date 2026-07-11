"""Built-in pipelines.

``ros-ci`` is the interim generic pipeline of 07 §7: build + test a ROS 2
workspace in a pinned builder image, publish a runtime image on ``--publish``.
Interim until the ``module-ci`` family (T3) replaces it. Configure via the
``pipelines.ros_ci:`` section:

.. code-block:: yaml

    pipelines:
      ros_ci:
        builder: ros:jazzy-ros-base
        platforms: [linux/amd64, linux/arm64]

The two-plane rule (02 §1 rule 1) applies: the container runs ``ardt deps`` /
``ardt build`` / ``ardt test`` — this pipeline orchestrates the environment and
never re-implements the build logic. Until the baked ``ardt-ci`` tool image
exists (B4), ardt is pip-installed into the builder from ``ardt_source``: the
public git repo by default, or a local checkout for development
(``--arg ardt_source=/path/to/ardt``).
"""

from __future__ import annotations

from pathlib import Path

import dagger
from pydantic import BaseModel, ConfigDict, Field

from ardt_core.context import Context

from . import std
from .registry import pipeline

JUNIT_EXPORT_DIR = "pipeline-reports"
ARDT_GIT = "git+https://github.com/Asterion-Robotics/ardt.git"

# Only the task plane enters the container — never ardt-pipelines (two-plane rule:
# nothing inside a build container may import dagger).
_TASK_PACKAGES = ("ardt-core", "ardt-tasks-ros")


class RosCiConfig(BaseModel):
    """The ``pipelines.ros_ci:`` section."""

    model_config = ConfigDict(extra="forbid")

    builder: str = "ros:jazzy-ros-base"
    dockerfile: str = "Dockerfile"
    platforms: list[str] = Field(default_factory=lambda: ["linux/amd64"])
    image: str | None = None
    """Published image name; defaults to the project name."""


class PipelinesSection(BaseModel):
    """The ``pipelines:`` config section this plugin claims."""

    model_config = ConfigDict(extra="allow")

    ros_ci: RosCiConfig = Field(default_factory=RosCiConfig)


def _config(ctx: Context) -> RosCiConfig:
    return ctx.cfg.section_as("pipelines", PipelinesSection).ros_ci


def _with_ardt(dag: dagger.Client, container: dagger.Container, source: str) -> dagger.Container:
    """Install the ardt task plane into the builder (stopgap until ardt-ci, B4)."""
    pip = "python3 -m pip install --break-system-packages"
    if Path(source).is_dir():
        checkout = dag.host().directory(source, exclude=[".git", ".venv", "__pycache__"])
        packages = " ".join(f"/opt/ardt-src/packages/{name}" for name in _TASK_PACKAGES)
        return container.with_directory("/opt/ardt-src", checkout).with_exec(
            ["bash", "-lc", f"{pip} {packages}"]
        )
    requirements = " ".join(
        f"'{name} @ {source}#subdirectory=packages/{name}'" for name in _TASK_PACKAGES
    )
    return container.with_exec(["bash", "-lc", f"{pip} {requirements}"])


@pipeline(name="ros-ci", doc="Build and test a ROS 2 workspace; publish its image on --publish")
async def ros_ci(ctx: Context, dag: dagger.Client, ardt_source: str = ARDT_GIT) -> None:
    cfg = _config(ctx)
    src = std.source_dir(dag, ctx)

    # The repo root lands at /ws/src (its ardt.yaml configures the tasks in
    # there exactly as it does on a dev machine).
    results = "/results"
    prepared = (
        dag.container()
        .from_(cfg.builder)
        .with_directory("/ws/src", src)
        .with_workdir("/ws/src")
        # "colcon-ws": the volume layout is /ws/src-rooted; the purpose string is
        # part of the key, so changing the layout means a new volume (CMake
        # refuses a build tree whose recorded paths moved).
        .with_mounted_cache("/ws/src/build", std.cache_volume(dag, ctx, "colcon-ws"))
        # Environment provisioning (not build logic): fresh containers have no
        # apt lists, no rosdep cache, and ros-base ships without pip.
        .with_exec(
            [
                "bash",
                "-lc",
                "apt-get update"
                " && apt-get install -y --no-install-recommends python3-pip"
                " && rosdep update --rosdistro $ROS_DISTRO",
            ]
        )
    )
    workspace = (
        _with_ardt(dag, prepared, ardt_source)
        # The tasks themselves — same commands, flags and ardt.yaml as on a host.
        .with_exec(["ardt", "deps"])
        .with_exec(["ardt", "build"])
        .with_exec(["ardt", "test"])
        # Harvest JUnit XMLs from the tasks' fixed path convention
        # (build/**/test_results/**/*.xml) into an exportable directory: execs
        # can read the cache mount, Dagger directory snapshots cannot.
        .with_exec(
            [
                "bash",
                "-lc",
                f"mkdir -p {results} && cd build"
                f" && (find . -path '*test_results*' -name '*.xml'"
                f"      -exec cp --parents -t {results} {{}} +)",
            ]
        )
    )
    await workspace.sync()  # fail fast on red tests

    # JUnit XMLs out of the container so CI can render them (02 §1 rule 4).
    export_path = str(ctx.project_root / JUNIT_EXPORT_DIR)
    await workspace.directory(results).export(export_path)
    ctx.emit(junit_dir=JUNIT_EXPORT_DIR, tests_ok=True)

    if not ctx.publish:
        ctx.console.info("skipping publish (no --publish)")
        return

    ref = std.image_ref(ctx, cfg.image)
    variants = std.build_variants(dag, src, dockerfile=cfg.dockerfile, platforms=cfg.platforms)
    digest = await std.publish_multiarch(dag, ctx, ref, variants)
    ctx.console.success(f"published {ref} @ {digest}")
