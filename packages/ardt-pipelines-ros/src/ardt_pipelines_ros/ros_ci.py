"""Built-in pipelines.

``ros-ci`` is the interim generic pipeline of 07 §7, restructured around one
idea: **building the image is the CI run**. The image recipe (owned by
:mod:`.recipes`, versioned with ardt) runs the ardt tasks as build stages —

1. ``ardt deps``   — rosdep install
2. ``ardt build``  — colcon build into the install base
3. ``ardt test``   — red tests fail the image build
4. stage the JUnit XMLs at a fixed path
5. the shipped runtime image (``FROM base_image`` + repo's extra layers)

— and the pipeline only orchestrates: render the recipe, build the ``build``
target (which *is* deps/build/test), export the reports and the rendered
Dockerfile, then build/publish the ``runtime`` target. **Repos own no
Dockerfile**; they set the knobs in ``pipelines.ros_ci:``, and a repo that
truly needs local image content extends the configured base with a small
``base.Dockerfile`` (``FROM ${BASE_IMAGE}`` + its layers), spliced into the
rendered recipe as a stage:

.. code-block:: yaml

    pipelines:
      ros_ci:
        base_image: ros:jazzy-ros-base
        cmd: ["bash", "-lc", ". /opt/app/setup.bash && ros2 run my_pkg node"]
        platforms: [linux/amd64, linux/arm64]

Until ardt is published, ``--arg ardt_source=/path/to/checkout`` injects a local
ardt into the build instead of pip-installing from git.
"""

from __future__ import annotations

from pathlib import Path

import dagger
from pydantic import BaseModel, ConfigDict, Field

from ardt_core.context import Context
from ardt_pipelines import pipeline, std

from . import recipes

JUNIT_EXPORT_DIR = "pipeline-reports"
ARDT_GIT = "git+https://github.com/Asterion-Robotics/ardt.git"


class RosCiConfig(BaseModel):
    """The ``pipelines.ros_ci:`` section."""

    model_config = ConfigDict(extra="forbid")

    builder: str = "ros:jazzy-ros-base"
    """Base of the build+test stage (process — never ships)."""
    base_image: str = "ros:jazzy-ros-base"
    """Base (``FROM``) of the SHIPPED runtime image."""
    base_dockerfile: str = "base.Dockerfile"
    """Optional in-repo base extension: a single-stage Dockerfile starting
    ``FROM ${BASE_IMAGE}`` (kernel modules, vendor drivers…). When present it is
    spliced into the rendered recipe and the runtime image builds on it."""
    cmd: list[str] | None = None
    """Container CMD of the shipped image."""
    platforms: list[str] = Field(default_factory=lambda: ["linux/amd64"])
    image: str | None = None
    """Published image name; defaults to the project name."""


class PipelinesSection(BaseModel):
    """The ``pipelines:`` config section this plugin claims."""

    model_config = ConfigDict(extra="allow")

    ros_ci: RosCiConfig = Field(default_factory=RosCiConfig)


def _config(ctx: Context) -> RosCiConfig:
    return ctx.cfg.section_as("pipelines", PipelinesSection).ros_ci


def _build_context(
    ctx: Context, dag: dagger.Client, cfg: RosCiConfig, ardt_source: str
) -> tuple[dagger.Directory, str]:
    """The build context (source + rendered recipe) and the rendered text."""
    src = std.source_dir(dag, ctx)

    local_ardt = Path(ardt_source).is_dir()
    rendered = recipes.render_ros2(
        builder=cfg.builder,
        base_image=cfg.base_image,
        project_root=ctx.project_root,
        base_dockerfile=cfg.base_dockerfile,
        cmd=cfg.cmd,
        ardt_source=ardt_source,
        local_ardt=local_ardt,
    )
    context = src.with_new_file(recipes.RENDERED_NAME, rendered)
    if local_ardt:
        checkout = dag.host().directory(ardt_source, exclude=[".git", ".venv", "__pycache__"])
        context = context.with_directory(recipes.LOCAL_ARDT_DIR, checkout)
    return context, rendered


@pipeline(name="ros-ci", doc="deps/build/test as image stages; publish the result on --publish")
async def ros_ci(ctx: Context, dag: dagger.Client, ardt_source: str = ARDT_GIT) -> None:
    cfg = _config(ctx)
    context, rendered = _build_context(ctx, dag, cfg, ardt_source)

    # Steps 1-4: the `build` target runs ardt deps/build/test as layers.
    # A red test is a failed image build — there is no separate test phase.
    build_stage = context.docker_build(
        dockerfile=recipes.RENDERED_NAME, target=recipes.BUILD_TARGET
    )
    await build_stage.sync()

    # Export the JUnit XMLs (CI renders them) and the rendered Dockerfile
    # (02 §7.3-4: the audit/`docker build` escape hatch ships with every run).
    export_dir = ctx.project_root / JUNIT_EXPORT_DIR
    await build_stage.directory(recipes.RESULTS_DIR).export(str(export_dir))
    rendered_path = export_dir / recipes.RENDERED_NAME
    rendered_path.parent.mkdir(parents=True, exist_ok=True)
    rendered_path.write_text(rendered, encoding="utf-8")
    ctx.emit(
        junit_dir=JUNIT_EXPORT_DIR,
        tests_ok=True,
        rendered_dockerfile=f"{JUNIT_EXPORT_DIR}/{recipes.RENDERED_NAME}",
    )

    # Step 5: the runtime target — built even without --publish so a broken
    # runtime stage fails the MR run, published only on --publish.
    variants = [
        context.docker_build(
            dockerfile=recipes.RENDERED_NAME,
            platform=dagger.Platform(p),
            target=recipes.RUNTIME_TARGET,
        )
        for p in cfg.platforms
    ]
    for variant in variants:
        await variant.sync()

    if not ctx.publish:
        ctx.console.info("runtime image built; skipping push (no --publish)")
        return

    ref = std.image_ref(ctx, cfg.image)
    digest = await std.publish_multiarch(dag, ctx, ref, variants)
    ctx.console.success(f"published {ref} @ {digest}")
