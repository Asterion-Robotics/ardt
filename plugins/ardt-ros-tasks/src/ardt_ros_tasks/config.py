# Copyright 2026 Asterion Robotics
# SPDX-License-Identifier: Apache-2.0

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Author: Thibault Poignonec <t.poignonec@asterion-robotics.com>

"""The ``tasks:`` config section, ``ros:`` subsection."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ardt_core.config import ArdtConfig, workspace_root

__all__ = [
    "JUNIT_GLOB",
    "RosConfig",
    "TasksConfig",
    "repos_target_path",
    "ros_config",
    "workspace_root",
]

JUNIT_GLOB = "build/**/test_results/**/*.xml"
"""Fixed path convention (relative to the workspace root), so pipelines can
export JUnit XMLs blindly."""


def repos_target_path(cfg: RosConfig, project_root: Path) -> Path:
    """Where ``ardt deps`` imports the ``.repos`` entries.

    An explicit ``tasks.ros.repos_target`` is honored relative to the project
    root. The default is ``external/`` under the workspace's ``src/``, so every
    imported repo lands beside this one but visibly grouped
    (``/ws/src/external/<name>``) — for a plain checkout that degrades to
    ``<repo>/src/external``, the same shape one level in.
    """
    if cfg.repos_target is not None:
        return project_root / cfg.repos_target
    ws = workspace_root(project_root)
    src = project_root / "src" if ws == project_root else ws / "src"
    return src / "external"


class RosConfig(BaseModel):
    """``tasks.ros:`` — everything the three tasks need from the repo."""

    model_config = ConfigDict(extra="forbid")

    distro: str = "jazzy"
    source_base: str = "/opt/ros"
    """The install prefix to source before invoking colcon; ``{distro}`` is appended."""

    package_scope: Literal["workspace", "project"] = "project"
    """Which packages the ros tasks operate on.

    ``project`` (the default): the repo's own packages and nothing beyond what
    they need. ``ardt build`` becomes ``--packages-up-to <own>`` (own packages
    plus their recursive dependencies), ``ardt test`` becomes
    ``--packages-select <own>`` (imported dependencies' test suites are not
    this repo's merge gate), and the rosdep pass in ``ardt deps`` resolves
    only that closure's manifests — an imported stack's demo packages are
    neither dep-resolved, built, nor tested. "Own" is discovered, not
    declared: whatever colcon finds under the project root. For a repo with
    no ``.repos`` imports this is identical to ``workspace``, which is what
    makes it a safe default.

    ``workspace`` (the pre-v0.4.1 behavior, opt-in now): everything colcon
    discovers under the workspace root — this repo AND every package
    ``vcs import`` fetched, demo packages included. For the rare repo that
    builds imported packages nothing of its own depends on.

    An explicit ``--packages-select`` on the CLI overrides the scope either
    way."""

    repos_file: str | None = None
    """A ``.repos`` file imported by ``ardt deps`` before rosdep runs. None
    (the default) auto-detects ``<project>.repos`` in the project root and
    skips the import when absent; an explicit value must exist; an explicit
    empty string disables the import for a repo whose ``<project>.repos``
    would otherwise be picked up."""
    repos_target: str | None = None
    """Where ``vcs import`` clones, relative to the project root. None resolves
    to ``external/`` under the workspace's ``src/`` (:func:`repos_target_path`):
    in a ``/ws`` layout every imported repo lands at ``/ws/src/external/<name>``
    — in the workspace beside this repo, but grouped so what is yours and what
    is imported stays legible (and out of the ``src/*`` project lookup)."""

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
