"""The ``tasks:`` config section, ``ros:`` subsection."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from ardt_core.config import ArdtConfig

JUNIT_GLOB = "build/**/test_results/**/*.xml"
"""Fixed path convention, so pipelines can export JUnit XMLs blindly (07 §5)."""


class RosConfig(BaseModel):
    """``tasks.ros:`` — everything the three tasks need from the repo."""

    model_config = ConfigDict(extra="forbid")

    distro: str = "jazzy"
    source_base: str = "/opt/ros"
    """The install prefix to source before invoking colcon; ``{distro}`` is appended."""

    repos_file: str | None = None
    """A ``.repos`` file imported by ``ardt deps`` before rosdep runs."""
    repos_target: str = "src"

    rosdep_skip_keys: list[str] = Field(default_factory=list)
    """rosdep keys never installed (vendored, proprietary, or known-broken deps)."""
    exclude_packages: list[str] = Field(default_factory=list)
    """Packages skipped everywhere: rosdep resolution, colcon build, colcon test.
    The space-ros pattern — import a broad ``.repos``, build only what you need."""

    install_base: str | None = None
    """colcon ``--install-base``; None keeps colcon's default ``install/``."""

    build_args: list[str] = Field(default_factory=list)
    """Extra arguments appended to ``colcon build``."""
    test_args: list[str] = Field(default_factory=list)
    symlink_install: bool = True
    merge_install: bool = False


class TasksConfig(BaseModel):
    """``tasks:`` — the section this plugin claims."""

    model_config = ConfigDict(extra="allow")

    ros: RosConfig = Field(default_factory=RosConfig)


def ros_config(cfg: ArdtConfig) -> RosConfig:
    """Extract ``tasks.ros:`` from the repo config, with defaults."""
    return cfg.section_as("tasks", TasksConfig).ros
