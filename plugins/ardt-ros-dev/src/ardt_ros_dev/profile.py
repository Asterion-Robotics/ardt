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

"""The ROS 2 dev profile, expressed as data.

Moved here verbatim from the engine when the devcontainer plane was split from
the profiles that drive it. Every rationale below is load-bearing and was paid
for in image size or debugging time, so it travels with the data.

The rule that keeps the numbers honest: this layer is strictly *additive* over
what the CI build stage installs, so the container a developer works in and the
image CI builds cannot drift.
"""

from __future__ import annotations

from ardt_devcontainers.profiles import CXX_STANDARD, DISTRO, Profile

ROS2 = Profile(
    name="ros2",
    summary="ROS 2 workspace: colcon toolchain, rviz2/rqt, clangd, gdb",
    distribution="ardt-ros-dev",
    dockerfile="ros2.Dockerfile.tmpl",
    templates_package="ardt_ros_dev.templates",
    default_base_image=f"ros:{DISTRO}-ros-base",
    ardt_modules=("ardt-core", "ardt-ros-tasks", "ardt-doc-tasks"),
    apt_groups=(
        # What CI's build stage installs (recipes/ros2.Dockerfile.tmpl), so the
        # dev layer is strictly additive over it.
        ("as in the CI build stage", ("build-essential", "git", "python3-pip", "openssh-client")),
        ("toolchain", ("cmake", "ninja-build", "ccache", "pkg-config")),
        ("ROS dev tooling (colcon extensions, mixins, rosdep, vcstool)", ("ros-dev-tools",)),
        ("debuggers and analysers", ("gdb", "valgrind", "cppcheck")),
        # IDE-side only: the repo's pre-commit config remains the CI truth
        # for format/lint.
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
        "mhutchie.git-graph",
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
        # Overlay before underlay, the order `install/setup.bash` establishes:
        # a package built in this workspace shadows the distro's copy of the
        # same name, which is the entire point of an overlay. Without the
        # workspace entries, headers generated here (message packages above
        # all) resolve to nothing, or to a stale installed version.
        #
        # Both colcon layouts are listed because both are reachable from
        # config: isolated is the default (`install/<pkg>/include`), merged is
        # `tasks.ros.merge_install: true` (`install/include`). The workspace
        # root is `${workspaceFolder}` rather than a literal `/ws` so this
        # keeps matching whatever the render opens.
        "includePath": [
            "${workspaceFolder}/install/*/include/**",
            "${workspaceFolder}/install/include/**",
            f"/opt/ros/{DISTRO}/include/**",
            "/usr/include/**",
        ],
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
