"""The ``dev:`` config section, and the one cross-section read that matters.

Almost nothing belongs here: a repo that wants the standard dev environment
writes no ``dev:`` section at all. The knobs exist for the exceptions (a repo
needing an extra apt package, a published dev image, no GUI).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from ardt_core.config import ArdtConfig

DEVCONTAINER_DIR = ".devcontainer"
"""Where the render lands. Fixed by VS Code, not by us."""


class DevConfig(BaseModel):
    """``dev:`` — how this repo's dev container differs from the profile default."""

    model_config = ConfigDict(extra="forbid")

    profile: str = "ros2"
    """Which dev profile to render (:mod:`.profiles`)."""

    image: str | None = None
    """A published dev image (``…/ros2-dev@sha256:…``) to use *instead of*
    building the rendered recipe. The end state once ``platform/base-images``
    publishes dev nodes; until then the recipe is built locally."""
    base_image: str | None = None
    """Base of the rendered dev layer. None resolves to
    ``pipelines.ros_ci.builder`` when the repo sets one (that is the parity
    rule), else the profile's default."""

    apt_packages: list[str] = Field(default_factory=list)
    """Extra apt packages in the dev layer, on top of the profile's set."""
    ardt_modules: list[str] = Field(default_factory=list)
    """Extra ardt modules installed in the container, on top of the profile's."""

    workspace_folder: str = "/ws/src"
    """Where the repo mounts. Matches the CI recipe's build stage, so CMake
    paths, ``compile_commands.json`` and stack traces read the same in both."""

    gui: bool = True
    """Wire the host's display through (rviz2/rqt). Off for headless repos."""
    claude_code: bool = True
    isolate_build_dirs: bool = True
    """Keep ``build/``/``install/``/``log/`` in container-local volumes so a host
    checkout's own build tree and the container's cannot collide in each other's
    ``CMakeCache.txt``."""

    extensions: list[str] = Field(default_factory=list)
    """Extra VS Code extension ids, on top of the profile's."""
    mounts: list[str] = Field(default_factory=list)
    """Extra compose volume entries, verbatim (``/host/path:/container/path``)."""


def dev_config(cfg: ArdtConfig) -> DevConfig:
    """Extract ``dev:`` from the repo config, with defaults."""
    return cfg.section_as("dev", DevConfig)


def ros_distro(cfg: ArdtConfig, default: str = "jazzy") -> str:
    """``tasks.ros.distro``, read raw — see :func:`ci_builder` for why raw."""
    ros = cfg.section("tasks").get("ros")
    if not isinstance(ros, dict):
        return default
    distro = ros.get("distro")  # type: ignore[union-attr]
    return distro if isinstance(distro, str) else default


def ci_builder(cfg: ArdtConfig) -> str | None:
    """``pipelines.ros_ci.builder``, read raw.

    The parity rule needs the CI builder image, but ardt-dev must not import a
    pipeline plugin to get it (it would drag ``dagger-io`` onto a laptop). The
    section is read as plain data and treated as absent when malformed — this is
    a comparison, not a validation: ``ros-ci`` owns that.
    """
    pipelines = cfg.section("pipelines")
    ros_ci = pipelines.get("ros_ci")
    if not isinstance(ros_ci, dict):
        return None
    builder = ros_ci.get("builder")  # type: ignore[union-attr]
    return builder if isinstance(builder, str) else None
