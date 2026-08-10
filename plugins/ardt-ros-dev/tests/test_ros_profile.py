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

"""The ros2 profile: what it decides, and that the engine can find it.

Two jobs. First, the wiring — the profile reaches the engine through the real
`ardt.dev_profiles` entry point and renders, which is the contract a profile
plugin signs. Second, the decisions that are ROS-shaped rather than
engine-shaped: the apt sets, the C++ standard per distro, CI parity.

All `unit`: rendering is pure, so none of this needs docker or a container.
"""

from __future__ import annotations

import json

import pytest

from ardt_core.config import ArdtConfig
from ardt_core.plugins import discover
from ardt_devcontainers import render as render_module
from ardt_devcontainers.config import dev_config
from ardt_devcontainers.host import HostFacts
from ardt_devcontainers.profiles import Profile, profiles
from ardt_ros_dev.profile import ROS2

INSTALLED = discover()


def plan(cfg: ArdtConfig) -> render_module.Render:
    return render_module.build(
        "demo",
        cfg,
        dev_config(cfg),
        registry=INSTALLED,
        facts=HostFacts(system="Linux"),
    )


# --- the plugin contract ----------------------------------------------------


def test_the_profile_loads_through_the_installed_entry_point() -> None:
    """Not `import ardt_ros_dev` — the entry point, as the engine resolves it.

    This is what would break on a bad `[project.entry-points]` table, a renamed
    module, or a wheel that forgot to ship the package.
    """
    found = profiles(INSTALLED)
    assert found["ros2"] is ROS2
    assert isinstance(ROS2, Profile)


def test_the_profile_names_its_own_distribution_and_templates() -> None:
    """Both are what let the engine stay ignorant of this plugin: one puts it in
    the container's ardt install, the other locates its Dockerfile template."""
    assert ROS2.distribution == "ardt-ros-dev"
    assert ROS2.templates_package == "ardt_ros_dev.templates"


def test_the_profile_renders_a_dockerfile_through_the_engine() -> None:
    content = plan(ArdtConfig()).files[render_module.DOCKERFILE]
    assert "ARG BASE_IMAGE=ros:jazzy-ros-base" in content
    assert "@DISTRO@" not in content  # the distro token is resolved


def test_the_container_installs_the_profile_that_rendered_it() -> None:
    """`ardt dev bootstrap` runs *in* the container and has to resolve `ros2`
    there, so this plugin must be in the rendered requirements."""
    reqs = plan(ArdtConfig()).requirements
    assert any(r.startswith("ardt-ros-dev @ ") for r in reqs)


# --- what the profile decides -----------------------------------------------


def test_the_dev_layer_is_additive_over_the_ci_build_stage() -> None:
    """The parity rule's apt half: the first group repeats what CI installs."""
    content = plan(ArdtConfig()).files[render_module.DOCKERFILE]
    assert "`# as in the CI build stage`" in content
    for package in ("build-essential", "git", "python3-pip", "openssh-client"):
        assert package in content


def test_the_expensive_rqt_metapackage_is_not_pulled_in() -> None:
    content = plan(ArdtConfig()).files[render_module.DOCKERFILE]
    assert "rqt-common-plugins" not in content  # 398 packages, 1.45 GB
    assert "ros-jazzy-rqt-graph" in content
    assert "ros-jazzy-rviz2" in content


def test_the_gui_tools_follow_the_repo_distro() -> None:
    cfg = ArdtConfig.model_validate({"tasks": {"ros": {"distro": "kilted"}}})
    content = plan(cfg).files[render_module.DOCKERFILE]
    assert "ros-kilted-rviz2" in content
    assert "ros-jazzy-" not in content


def test_bootstrap_ends_on_the_ci_recipes_first_step() -> None:
    """`ardt deps` last (with PEP 668 env var), and `rosdep update` at the repo's distro before it."""
    assert ROS2.bootstrap[-1] == ("PIP_BREAK_SYSTEM_PACKAGES=1", "ardt", "deps")
    assert ("rosdep", "update", "--rosdistro", "@DISTRO@") in ROS2.bootstrap


@pytest.mark.parametrize(
    ("distro", "standard"),
    [
        # Each distro's own "Code style and language versions" page.
        ("humble", "c++17"),
        ("jazzy", "c++17"),
        ("kilted", "c++17"),
        ("lyrical", "c++20"),
        ("rolling", "c++20"),
        # Not in the table: assume a future distro, not a forgotten past one.
        ("mystery", "c++20"),
    ],
)
def test_cpp_standard_follows_the_distro(distro: str, standard: str) -> None:
    cfg = ArdtConfig.model_validate({"tasks": {"ros": {"distro": distro}}})
    entry = json.loads(plan(cfg).files[render_module.CPP_PROPERTIES])["configurations"][0]
    assert entry["cppStandard"] == standard


def test_cpp_properties_is_rendered_at_the_repo_distro() -> None:
    cfg = ArdtConfig.model_validate({"tasks": {"ros": {"distro": "kilted"}}})
    text = plan(cfg).files[render_module.CPP_PROPERTIES]
    # Plain JSON, no comment header: cpptools flags comments here (#5885, #6132).
    entry = json.loads(text)["configurations"][0]
    assert entry["name"] == "ROS-kilted"
    assert "/opt/ros/kilted/include/**" in entry["includePath"]
    # `ardt dev compile-commands` merges into <workspace>/build; the two agree.
    assert entry["compileCommands"] == "${workspaceFolder}/build/compile_commands.json"
    assert "@DISTRO@" not in text and "@CXX_STANDARD@" not in text


def test_the_workspace_install_space_shadows_the_distro() -> None:
    """Overlay before underlay, as `install/setup.bash` orders them.

    A message package built here installs its generated headers under
    `install/`; if the distro's include tree came first, a package name present
    in both would resolve to the installed copy rather than the one just built.
    """
    paths = ROS2.cpp_properties["includePath"]
    workspace = [p for p in paths if p.startswith("${workspaceFolder}")]
    distro = [p for p in paths if p.startswith("/opt/ros/")]
    assert workspace, "the workspace's own install space is not on the include path"
    assert paths.index(workspace[-1]) < paths.index(distro[0])
    # Both colcon layouts: isolated (the default) and tasks.ros.merge_install.
    assert "${workspaceFolder}/install/*/include/**" in paths
    assert "${workspaceFolder}/install/include/**" in paths


def test_the_include_path_uses_the_workspace_root_the_render_opens() -> None:
    """`${workspaceFolder}`, not a literal /ws: cpptools expands it from
    devcontainer.json, so the two cannot drift."""
    entry = json.loads(plan(ArdtConfig()).files[render_module.CPP_PROPERTIES])["configurations"][0]
    assert all("/ws/" not in path for path in entry["includePath"])


def test_clangd_owns_intellisense_and_cpptools_keeps_the_debug_adapter() -> None:
    assert ROS2.settings["C_Cpp.intelliSenseEngine"] == "disabled"
    assert "llvm-vs-code-extensions.vscode-clangd" in ROS2.extensions
    assert "ms-vscode.cpptools" in ROS2.extensions
