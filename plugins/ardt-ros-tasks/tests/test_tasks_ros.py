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

"""ardt-ros-tasks: config parsing and the deps/build/test command shapes.

These stay `unit`: no real colcon/rosdep runs here. `--dry-run` lets us assert the
*plan* (which commands, which flags) without an ROS install; a green run on a
real downstream repo is the integration acceptance criterion, not a unit test.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ardt_core.config import ArdtConfig
from ardt_core.testing import build_context, console_output
from ardt_ros_tasks import tasks
from ardt_ros_tasks.config import JUNIT_GLOB, repos_target_path, ros_config, workspace_root

context = build_context
output = console_output


def test_cli_rejects_a_mistyped_option(repo: Path) -> None:
    """Regression: `ignore_unknown_options` forwarded any typo'd ardt flag
    straight into a real colcon run; unknown options must be usage errors."""
    from ardt_core.cli import main

    assert main(["-C", str(repo), "build", "--dry-run", "--packages-selct", "pkg"]) == 2


def test_cli_passes_arguments_after_the_separator_to_colcon(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from ardt_core.cli import main

    argv = ["-C", str(repo), "build", "--dry-run", "--", "--event-handlers", "console_direct+"]
    assert main(argv) == 0
    assert "--event-handlers console_direct+" in capsys.readouterr().err


def test_ros_config_defaults() -> None:
    cfg = ros_config(ArdtConfig())
    assert cfg.distro == "jazzy"
    assert cfg.symlink_install is True


def test_ros_config_from_yaml(repo: Path) -> None:
    (repo / "ardt.yaml").write_text(
        "tasks:\n  ros:\n    distro: kilted\n    build_args: ['--cmake-args', '-DX=1']\n"
    )
    ctx = context(repo)
    cfg = ros_config(ctx.cfg)
    assert cfg.distro == "kilted"
    assert cfg.build_args == ["--cmake-args", "-DX=1"]


def test_build_plan_includes_symlink_install(repo: Path) -> None:
    ctx = context(repo, dry_run=True)
    tasks.build(ctx)
    assert "colcon build --symlink-install" in output(ctx)


def test_build_passes_packages_select(repo: Path) -> None:
    ctx = context(repo, dry_run=True)
    tasks.build(ctx, packages=("pkg_a", "pkg_b"))
    assert "--packages-select pkg_a pkg_b" in output(ctx)


def test_build_merge_install_flag(repo: Path) -> None:
    (repo / "ardt.yaml").write_text("tasks:\n  ros:\n    merge_install: true\n")
    ctx = context(repo, dry_run=True)
    tasks.build(ctx)
    assert "--merge-install" in output(ctx)


def test_test_plan_runs_colcon_test_then_results(repo: Path) -> None:
    ctx = context(repo, dry_run=True)
    tasks.test(ctx)
    text = output(ctx)
    assert "colcon test" in text
    assert "colcon test-result --all --verbose" in text
    assert ctx.emitted["junit_glob"] == JUNIT_GLOB


def test_deps_without_repos_file_only_plans_rosdep(repo: Path) -> None:
    ctx = context(repo, dry_run=True)
    tasks.deps(ctx)
    text = output(ctx)
    # the paths listing carries the default project scope (--packages-up-to)
    assert "rosdep install --from-paths $(colcon list --paths-only --packages-up-to" in text
    assert "--ignore-src -r -y" in text
    assert "vcs import" not in text


def test_deps_with_repos_file_plans_vcs_import(repo: Path) -> None:
    (repo / "sources.repos").write_text("repositories: {}\n")
    (repo / "ardt.yaml").write_text("tasks:\n  ros:\n    repos_file: sources.repos\n")
    ctx = context(repo, dry_run=True)
    tasks.deps(ctx)
    assert "vcs import" in output(ctx)


def test_deps_missing_repos_file_is_a_clean_error(repo: Path) -> None:
    from ardt_core.errors import ArdtError

    (repo / "ardt.yaml").write_text("tasks:\n  ros:\n    repos_file: nope.repos\n")
    ctx = context(repo, dry_run=True)
    try:
        tasks.deps(ctx)
    except ArdtError as exc:
        assert "does not exist" in exc.message
    else:  # pragma: no cover
        raise AssertionError("expected ArdtError")


def test_deps_defaults_to_project_named_repos_file(repo: Path) -> None:
    # the fixture repo's directory (and so its default project name) is `proj`
    (repo / "proj.repos").write_text("repositories: {}\n")
    ctx = context(repo, dry_run=True)
    tasks.deps(ctx)
    assert "vcs import" in output(ctx)
    assert ctx.emitted["repos_file"] == "proj.repos"


def test_deps_project_name_config_drives_the_default_repos_file(repo: Path) -> None:
    (repo / "my_robot.repos").write_text("repositories: {}\n")
    (repo / "ardt.yaml").write_text("project:\n  name: my_robot\n")
    ctx = context(repo, dry_run=True)
    tasks.deps(ctx)
    assert "vcs import" in output(ctx)
    assert ctx.emitted["repos_file"] == "my_robot.repos"


def test_deps_empty_repos_file_opts_out_of_the_default(repo: Path) -> None:
    (repo / "proj.repos").write_text("repositories: {}\n")
    (repo / "ardt.yaml").write_text("tasks:\n  ros:\n    repos_file: ''\n")
    ctx = context(repo, dry_run=True)
    tasks.deps(ctx)
    assert "vcs import" not in output(ctx)
    assert ctx.emitted["repos_file"] is None


def test_deps_skip_flags(repo: Path) -> None:
    (repo / "sources.repos").write_text("repositories: {}\n")
    (repo / "ardt.yaml").write_text("tasks:\n  ros:\n    repos_file: sources.repos\n")
    ctx = context(repo, dry_run=True)
    tasks.deps(ctx, skip_vcs=True, skip_rosdep=True)
    text = output(ctx)
    assert "vcs import" not in text
    assert "rosdep" not in text


def test_rosdep_skip_keys_forwarded(repo: Path) -> None:
    (repo / "ardt.yaml").write_text(
        "tasks:\n  ros:\n    rosdep_skip_keys: ['rti-connext-dds', 'foo']\n"
    )
    ctx = context(repo, dry_run=True)
    tasks.deps(ctx)
    text = output(ctx)
    assert "--skip-keys" in text
    assert "rti-connext-dds foo" in text


def test_build_install_base_from_config(repo: Path) -> None:
    (repo / "ardt.yaml").write_text("tasks:\n  ros:\n    install_base: /opt/ros/app\n")
    ctx = context(repo, dry_run=True)
    tasks.build(ctx)
    assert "--install-base /opt/ros/app" in output(ctx)
    assert ctx.emitted["install_base"] == "/opt/ros/app"


def test_build_install_base_cli_overrides_config(repo: Path) -> None:
    (repo / "ardt.yaml").write_text("tasks:\n  ros:\n    install_base: /opt/ros/app\n")
    ctx = context(repo, dry_run=True)
    tasks.build(ctx, install_base="/elsewhere")
    assert "--install-base /elsewhere" in output(ctx)


def test_test_uses_same_install_base(repo: Path) -> None:
    (repo / "ardt.yaml").write_text("tasks:\n  ros:\n    install_base: /opt/ros/app\n")
    ctx = context(repo, dry_run=True)
    tasks.test(ctx)
    assert "colcon test --install-base /opt/ros/app" in output(ctx)


def test_exclude_packages_skips_build_and_test(repo: Path) -> None:
    (repo / "ardt.yaml").write_text("tasks:\n  ros:\n    exclude_packages: [big_sim]\n")
    ctx = context(repo, dry_run=True)
    tasks.build(ctx, exclude_packages=("flaky_pkg",))
    assert "--packages-skip big_sim flaky_pkg" in output(ctx)

    ctx = context(repo, dry_run=True)
    tasks.test(ctx)
    assert "--packages-skip big_sim" in output(ctx)


class TestPackageScope:
    """`package_scope: project` operates on the repo's own closure only.

    The point: a `.repos` import brings whole stacks (demos included); the
    workspace scope builds and dep-resolves all of it, the project scope only
    what this repo's packages actually need. TESTS are own-only in BOTH
    scopes: an import's suites belong to its own repo's gate.
    """

    YAML = "tasks:\n  ros:\n    package_scope: project\n"

    def test_project_is_the_default(self, repo: Path) -> None:
        """No config at all scopes to the project: safe because a repo with no
        imports has own == everything, so this degenerates to the old
        behavior exactly."""
        ctx = context(repo, dry_run=True)
        tasks.build(ctx)
        assert "--packages-up-to $own" in output(ctx)

    def test_workspace_opt_out_is_unscoped(self, repo: Path) -> None:
        (repo / "ardt.yaml").write_text("tasks:\n  ros:\n    package_scope: workspace\n")
        ctx = context(repo, dry_run=True)
        tasks.build(ctx)
        assert "--packages-up-to" not in output(ctx)

    def test_build_up_to_own_packages(self, repo: Path) -> None:
        (repo / "ardt.yaml").write_text(self.YAML)
        ctx = context(repo, dry_run=True)
        tasks.build(ctx)
        text = output(ctx)
        assert "--packages-up-to $own" in text
        assert "colcon list --names-only --base-paths" in text
        # the guard names the scoping, so an empty repo fails with a diagnosis
        assert "own-package scoping: colcon finds no packages" in text

    def test_test_selects_own_packages_only(self, repo: Path) -> None:
        """--packages-select, not --packages-up-to: dependency test suites
        belong to their own repos' gates."""
        (repo / "ardt.yaml").write_text(self.YAML)
        ctx = context(repo, dry_run=True)
        tasks.test(ctx)
        text = output(ctx)
        assert "--packages-select $own" in text
        assert "--packages-up-to" not in text

    def test_workspace_scope_still_tests_own_only(self, repo: Path) -> None:
        """Regression: workspace scope once ran imported suites in the gate.
        The scope widens what builds and ships, never what gates."""
        (repo / "ardt.yaml").write_text("tasks:\n  ros:\n    package_scope: workspace\n")
        ctx = context(repo, dry_run=True)
        tasks.test(ctx)
        assert "--packages-select $own" in output(ctx)

    def test_explicit_packages_still_override_test_scoping(self, repo: Path) -> None:
        (repo / "ardt.yaml").write_text("tasks:\n  ros:\n    package_scope: workspace\n")
        ctx = context(repo, dry_run=True)
        tasks.test(ctx, packages=("pkg_a",))
        text = output(ctx)
        assert "--packages-select pkg_a" in text
        assert "$own" not in text

    def test_deps_narrow_to_the_closure(self, repo: Path) -> None:
        (repo / "ardt.yaml").write_text(self.YAML)
        ctx = context(repo, dry_run=True)
        tasks.deps(ctx)
        assert "--packages-up-to $(colcon list --names-only --base-paths" in output(ctx)

    def test_explicit_packages_override_the_scope(self, repo: Path) -> None:
        (repo / "ardt.yaml").write_text(self.YAML)
        ctx = context(repo, dry_run=True)
        tasks.build(ctx, packages=("pkg_a",))
        text = output(ctx)
        assert "--packages-select pkg_a" in text
        assert "--packages-up-to" not in text

    def test_scope_composes_with_excludes(self, repo: Path) -> None:
        (repo / "ardt.yaml").write_text(
            "tasks:\n  ros:\n    package_scope: project\n    exclude_packages: [big_sim]\n"
        )
        ctx = context(repo, dry_run=True)
        tasks.build(ctx)
        text = output(ctx)
        assert "--packages-skip big_sim" in text
        assert "--packages-up-to $own" in text


def test_deps_excluded_packages_narrow_rosdep_paths(repo: Path) -> None:
    (repo / "ardt.yaml").write_text("tasks:\n  ros:\n    exclude_packages: [big_sim]\n")
    ctx = context(repo, dry_run=True)
    tasks.deps(ctx, exclude_packages=("other",))
    text = output(ctx)
    # excludes compose after the default project scope's --packages-up-to
    assert "--packages-skip big_sim other" in text
    assert "rosdep install --from-paths $(colcon list --paths-only" in text


def test_deps_skip_keys_merge_config_and_cli(repo: Path) -> None:
    (repo / "ardt.yaml").write_text("tasks:\n  ros:\n    rosdep_skip_keys: [gazebo]\n")
    ctx = context(repo, dry_run=True)
    tasks.deps(ctx, skip_keys=("rti-connext-dds",))
    text = output(ctx)
    assert "--skip-keys" in text
    assert "gazebo rti-connext-dds" in text


# --- the /ws workspace convention ---------------------------------------------


def test_workspace_root_of_a_plain_checkout_is_the_repo(tmp_path: Path) -> None:
    assert workspace_root(tmp_path / "repo") == tmp_path / "repo"


def test_workspace_root_of_a_ws_layout_is_the_grandparent(tmp_path: Path) -> None:
    assert workspace_root(tmp_path / "ws" / "src" / "repo") == tmp_path / "ws"
    # A repo checked out AS src/ gets the parent for the same reason.
    assert workspace_root(tmp_path / "ws" / "src") == tmp_path / "ws"


def test_repos_import_lands_in_src_external_of_the_workspace(tmp_path: Path) -> None:
    cfg = ros_config(ArdtConfig())
    assert repos_target_path(cfg, tmp_path / "ws" / "src" / "repo") == (
        tmp_path / "ws" / "src" / "external"
    )
    # Plain checkout: same shape, one level in.
    assert repos_target_path(cfg, tmp_path / "repo") == tmp_path / "repo" / "src" / "external"


def test_repos_target_override_stays_project_relative(tmp_path: Path) -> None:
    cfg = ros_config(ArdtConfig.model_validate({"tasks": {"ros": {"repos_target": "deps"}}}))
    assert repos_target_path(cfg, tmp_path / "ws" / "src" / "repo") == (
        tmp_path / "ws" / "src" / "repo" / "deps"
    )


def test_colcon_runs_from_the_workspace_root(tmp_path: Path) -> None:
    """In a /ws layout the build/install/log bases must land beside src/."""
    project = tmp_path / "ws" / "src" / "repo"
    project.mkdir(parents=True)
    (project / "ardt.yaml").write_text("{}\n")
    ctx = context(project, dry_run=True)
    assert ctx.project_root == project
    tasks.build(ctx)
    # The dry-run plan prints the command; the cwd is the runner's business —
    # assert it directly on the call the task makes.
    assert tasks._ws(ctx) == tmp_path / "ws"
