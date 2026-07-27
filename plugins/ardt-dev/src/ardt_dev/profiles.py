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

"""Dev profiles — the per-repo-type knowledge, expressed as data.

A profile answers: which base image, which extra apt packages, which ardt
modules the container needs, what to run once the container exists, and which
editor extensions make the language work. It is deliberately *data*: ardt-dev
imports no ROS package and no pipeline plugin, so a laptop install stays tiny.

Adding a profile is adding an entry to :data:`PROFILES` (plus a Dockerfile
template). When a domain plugin needs its own (say, an SDK builder base and a
plugin export layout), the same table is what an ``ardt.dev_profiles`` entry
point would populate — that indirection is not worth building for one profile.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ardt_core.errors import ArdtError

DISTRO = "@DISTRO@"
"""Token replaced with the repo's ROS distro at render time."""

CXX_STANDARD = "@CXX_STANDARD@"
"""Token replaced with :func:`cxx_standard` for the repo's ROS distro."""

CXX_STANDARDS: dict[str, str] = {
    "humble": "c++17",
    "jazzy": "c++17",
    "kilted": "c++17",
    "lyrical": "c++20",
    "rolling": "c++20",
}
"""What each distro targets, per its own "Code style and language versions" page
(``docs.ros.org/en/<distro>/The-ROS2-Project/Contributing/Code-Style-Language-Versions``):
c++20 from lyrical and rolling on, c++17 before. Note REP 2000's "minimum
language requirements" tables still say C++17 for rolling — that page is the
one that tracks the switch, so it is the one quoted here. A line per distro."""

CXX_STANDARD_DEFAULT = "c++20"
"""For a distro not in the table. The newest entry's value, not the oldest: an
unknown distro is far likelier to be a future one than a forgotten past one."""


def cxx_standard(distro: str) -> str:
    """The C++ standard editor tooling should assume for ``distro``."""
    return CXX_STANDARDS.get(distro, CXX_STANDARD_DEFAULT)


@dataclass(frozen=True)
class Profile:
    """Everything that differs between one kind of repo and another."""

    name: str
    summary: str
    dockerfile: str
    """Template file name in :mod:`ardt_dev.templates`."""
    default_base_image: str
    """Used when the repo pins no ``pipelines.ros_ci.builder`` and no
    ``dev.base_image``. May contain the :data:`DISTRO` token."""
    ardt_modules: tuple[str, ...]
    """ardt distributions installed in the container. The first two of the ROS
    profile are exactly ``ardt_ros_pipelines.recipes.ARDT_MODULES`` — the same
    modules CI's build stage installs, from the same ``ardt:`` pin."""
    apt_groups: tuple[tuple[str, tuple[str, ...]], ...]
    """``(label, packages)`` — labels become comments in the rendered recipe, so
    a human debugging the image can see why each group is there."""
    bootstrap: tuple[tuple[str, ...], ...]
    """Commands ``ardt dev bootstrap`` runs inside the container, in order."""
    extensions: tuple[str, ...]
    settings: dict[str, object] = field(default_factory=dict)
    container_env: dict[str, str] = field(default_factory=dict)
    cpp_properties: dict[str, object] | None = None
    """The single ``configurations[]`` entry of ``.vscode/c_cpp_properties.json``,
    or None for a profile with no C/C++ in it. Strings may carry :data:`DISTRO`.

    Unlike :attr:`settings`, this cannot ride along in ``devcontainer.json``:
    cpptools only reads its configuration from that path in the workspace."""


ROS2 = Profile(
    name="ros2",
    summary="ROS 2 workspace: colcon toolchain, rviz2/rqt, clangd, gdb",
    dockerfile="ros2.Dockerfile.tmpl",
    default_base_image=f"ros:{DISTRO}-ros-base",
    ardt_modules=("ardt-core", "ardt-ros-tasks", "ardt-doc-tasks"),
    apt_groups=(
        # What CI's build stage installs (recipes/ros2.Dockerfile.tmpl), so the
        # dev layer is strictly additive over it.
        ("as in the CI build stage", ("build-essential", "git", "python3-pip", "openssh-client")),
        ("toolchain", ("cmake", "ninja-build", "ccache", "pkg-config")),
        ("ROS dev tooling (colcon extensions, mixins, rosdep, vcstool)", ("ros-dev-tools",)),
        ("debuggers and analysers", ("gdb", "valgrind", "cppcheck")),
        # IDE-side only: `ardt check` remains the CI truth for format/lint.
        # Note that a repo whose .pre-commit-config.yaml sets a higher
        # `minimum_pre_commit_version` installs its own.
        (
            "language servers, formatters, and the local hook runner",
            ("clangd", "clang-format", "clang-tidy", "pre-commit"),
        ),
        (
            # Measured on jazzy (installed size, deps included): rviz2 358 MB,
            # this rqt set ~500 MB (mostly Qt, shared with rviz2), mesa 192 MB.
            # `rqt-common-plugins` is deliberately NOT here: that metapackage
            # pulls 398 packages / 1.45 GB, because rqt_image_view drags in
            # OpenCV's dev packages and rqt_plot drags in scipy/matplotlib/VTK.
            # A repo that wants them adds them to `dev.apt_packages`.
            "GUI tools — the reason a dev image exists at all",
            (
                # Rviz2
                f"ros-{DISTRO}-rviz2",
                # Rqt
                f"ros-{DISTRO}-rqt-gui",
                f"ros-{DISTRO}-rqt-gui-cpp",
                f"ros-{DISTRO}-rqt-graph",
                f"ros-{DISTRO}-rqt-console",
                f"ros-{DISTRO}-rqt-topic",
                f"ros-{DISTRO}-rqt-reconfigure",
                # Other GUI dependencies
                "x11-utils",
                "mesa-utils",
                "libgl1-mesa-dri",
            ),
        ),
        ("docs toolchain (ardt doc build)", ("doxygen", "graphviz")),
        (
            "shell",
            ("bash-completion", "sudo", "curl", "wget", "jq", "less", "nano", "unzip", "tree"),
        ),
    ),
    bootstrap=(
        ("sudo", "apt-get", "update", "-qq"),
        ("rosdep", "update", "--rosdistro", DISTRO),
        # Identical to the CI recipe's step 1 — the whole point of the exercise.
        ("ardt", "deps"),
    ),
    extensions=(
        "llvm-vs-code-extensions.vscode-clangd",
        "ms-vscode.cpptools",
        "ms-vscode.cmake-tools",
        "ms-python.python",
        "charliermarsh.ruff",
        "redhat.vscode-yaml",
        "ms-iot.vscode-ros",
        "anthropic.claude-code",
    ),
    settings={
        "clangd.arguments": ["--background-index", "--clang-tidy"],
        # clangd owns C++ IntelliSense; cpptools is kept for its debug adapter.
        "C_Cpp.intelliSenseEngine": "disabled",
        "python.defaultInterpreterPath": "/usr/bin/python3",
        "cmake.configureOnOpen": False,
        "files.watcherExclude": {"**/build/**": True, "**/install/**": True, "**/log/**": True},
        # VS Code opens the workspace root (/ws); the repo's .git sits two
        # levels down (src/<repo>/.git), one past the default scan depth of 1.
        "git.repositoryScanMaxDepth": 2,
    },
    container_env={
        # CMake >= 3.17 honors this as an env var, so clangd gets a
        # compile_commands.json without touching the repo's build_args.
        "CMAKE_EXPORT_COMPILE_COMMANDS": "ON",
    },
    cpp_properties={
        "name": f"ROS-{DISTRO}",
        "includePath": [f"/opt/ros/{DISTRO}/include/**", "/usr/include/**"],
        "intelliSenseMode": "gcc-x64",
        "compilerPath": "/usr/bin/gcc",
        "cStandard": "gnu11",
        "cppStandard": CXX_STANDARD,
        "defines": [],
        "configurationProvider": "ms-vscode.cmake-tools",
        # `ardt dev compile-commands` merges colcon's per-package files here.
        "compileCommands": "${workspaceFolder}/build/compile_commands.json",
    },
)

PROFILES: dict[str, Profile] = {ROS2.name: ROS2}


def profile(name: str) -> Profile:
    """Look up a profile, or fail with the list of the ones that exist."""
    found = PROFILES.get(name)
    if found is None:
        known = ", ".join(sorted(PROFILES))
        raise ArdtError(
            f"unknown dev profile `{name}`",
            hint=f"set `dev.profile:` to one of: {known}",
        )
    return found
