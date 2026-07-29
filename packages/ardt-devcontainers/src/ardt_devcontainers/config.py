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

"""The ``dev:`` config section, and the one cross-section read that matters.

Almost nothing belongs here: a repo that wants the standard dev environment
writes no ``dev:`` section at all. The knobs exist for the exceptions (a repo
needing an extra apt package, a published dev image, no GUI).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from ardt_core.config import ArdtConfig

DEVCONTAINER_DIR = ".devcontainer"
"""Where most of the render lands. Fixed by VS Code, not by us."""

VSCODE_DIR = ".vscode"
"""The rest of it. Only files VS Code refuses to read from anywhere else land
here (``c_cpp_properties.json``); everything an extension *can* pick up from
``devcontainer.json`` stays in :data:`DEVCONTAINER_DIR`."""

WORKSPACE_FOLDER = "/ws"
"""The colcon workspace root inside the container: what VS Code opens, where
colcon runs, where ``build/``/``install/``/``log/`` land. The repo itself
mounts two levels down at ``<WORKSPACE_FOLDER>/src/<project>``
(:func:`source_folder`), matching the CI recipe's ``COPY . /ws/src/<repo>`` —
so CMake paths, ``compile_commands.json`` and stack traces read the same in
both, and ``.repos`` imports become the repo's siblings under ``src/``.

A constant, not a knob: the CI recipe hard-codes the same path, and the parity
promise rests on the two never drifting."""


def source_folder(project: str) -> str:
    """Where the repo mounts: one entry under the workspace's ``src/``."""
    return f"{WORKSPACE_FOLDER}/src/{project}"


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
    distro = cfg.raw("tasks.ros.distro")
    return distro if isinstance(distro, str) else default


def ci_builder(cfg: ArdtConfig) -> str | None:
    """``pipelines.ros_ci.builder``, read raw.

    The parity rule needs the CI builder image, but the engine must not import a
    pipeline plugin to get it (it would drag ``dagger-io`` onto a laptop). The
    section is read as plain data and treated as absent when malformed — this is
    a comparison, not a validation: ``ros-ci`` owns that.
    """
    builder = cfg.raw("pipelines.ros_ci.builder")
    return builder if isinstance(builder, str) else None
