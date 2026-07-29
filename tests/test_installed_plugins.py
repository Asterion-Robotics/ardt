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

"""First-party integration: the workspace's installed plugins, through the real CLI.

Core's own suite runs standalone (its CLI tests fake the plugin registry);
everything that asserts on the genuinely-installed first-party plugins lives
here, where the uv workspace guarantees they exist.
"""

from __future__ import annotations

from pathlib import Path

from ardt_core.plugins import discover
from ardt_core.testing import run_cli

run = run_cli


def test_installed_first_party_plugins_load_cleanly() -> None:
    registry = discover()
    names = {p.name for p in registry.plugins}
    assert "ardt-ros-tasks" in names
    assert registry.problems == []


def test_the_ros_dev_profile_matches_the_ci_recipes_module_set() -> None:
    """The parity rule, across the two planes that have to agree on it.

    `ardt-ros-dev` names the modules the dev container installs and
    `ardt-ros-pipelines` names the ones CI's build stage installs; they resolve
    from the same `ardt:` pin, so drift here is drift between the container a
    developer works in and the image CI builds. The check lives at the root
    because it crosses two distributions that must never import each other —
    the recipes module pulls dagger, which no dev-side test may pay for.
    """
    from ardt_ros_dev.profile import ROS2
    from ardt_ros_pipelines.recipes import ARDT_MODULES

    assert set(ARDT_MODULES) <= set(ROS2.ardt_modules)


def test_build_dry_run_through_the_real_cli(repo: Path) -> None:
    code, _out, err = run(["build", "--dry-run"], repo)
    assert code == 0
    assert "colcon build" in err
    assert not (repo / "build").exists()


def test_test_task_dry_run_plans_results_summary(repo: Path) -> None:
    code, _out, err = run(["test", "--dry-run"], repo)
    assert code == 0
    assert "colcon test-result" in err
