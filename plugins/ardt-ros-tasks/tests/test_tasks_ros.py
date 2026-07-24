"""ardt-ros-tasks: config parsing and the deps/build/test command shapes.

These stay `unit`: no real colcon/rosdep runs here. `--dry-run` lets us assert the
*plan* (which commands, which flags) without an ROS install; the real green-on-
aos_edge run is the integration acceptance criterion, not a unit test.
"""

from __future__ import annotations

import io
from pathlib import Path

from ardt_core.context import Context
from ardt_core.plugins import Registry
from ardt_ros_tasks import tasks
from ardt_ros_tasks.config import JUNIT_GLOB, ros_config


def context(root: Path, **kwargs: object) -> Context:
    ctx = Context.build(cwd=root, registry=Registry(plugins=[], problems=[]), **kwargs)  # type: ignore[arg-type]
    ctx.console._stream = io.StringIO()  # capture; keep it plain
    ctx.console._plain = True
    return ctx


def output(ctx: Context) -> str:
    return ctx.console._stream.getvalue()  # type: ignore[attr-defined]


def test_ros_config_defaults() -> None:
    from ardt_core.config import ArdtConfig

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
    assert "rosdep install --from-paths $(colcon list --paths-only) --ignore-src -r -y" in text
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
    (repo / "ardt.yaml").write_text("tasks:\n  ros:\n    install_base: /opt/ros/aos\n")
    ctx = context(repo, dry_run=True)
    tasks.build(ctx)
    assert "--install-base /opt/ros/aos" in output(ctx)
    assert ctx.emitted["install_base"] == "/opt/ros/aos"


def test_build_install_base_cli_overrides_config(repo: Path) -> None:
    (repo / "ardt.yaml").write_text("tasks:\n  ros:\n    install_base: /opt/ros/aos\n")
    ctx = context(repo, dry_run=True)
    tasks.build(ctx, install_base="/elsewhere")
    assert "--install-base /elsewhere" in output(ctx)


def test_test_uses_same_install_base(repo: Path) -> None:
    (repo / "ardt.yaml").write_text("tasks:\n  ros:\n    install_base: /opt/ros/aos\n")
    ctx = context(repo, dry_run=True)
    tasks.test(ctx)
    assert "colcon test --install-base /opt/ros/aos" in output(ctx)


def test_exclude_packages_skips_build_and_test(repo: Path) -> None:
    (repo / "ardt.yaml").write_text("tasks:\n  ros:\n    exclude_packages: [big_sim]\n")
    ctx = context(repo, dry_run=True)
    tasks.build(ctx, exclude_packages=("flaky_pkg",))
    assert "--packages-skip big_sim flaky_pkg" in output(ctx)

    ctx = context(repo, dry_run=True)
    tasks.test(ctx)
    assert "--packages-skip big_sim" in output(ctx)


def test_deps_excluded_packages_narrow_rosdep_paths(repo: Path) -> None:
    (repo / "ardt.yaml").write_text("tasks:\n  ros:\n    exclude_packages: [big_sim]\n")
    ctx = context(repo, dry_run=True)
    tasks.deps(ctx, exclude_packages=("other",))
    text = output(ctx)
    assert "colcon list --paths-only --packages-skip big_sim other" in text
    assert "rosdep install --from-paths $(" in text


def test_deps_skip_keys_merge_config_and_cli(repo: Path) -> None:
    (repo / "ardt.yaml").write_text("tasks:\n  ros:\n    rosdep_skip_keys: [gazebo]\n")
    ctx = context(repo, dry_run=True)
    tasks.deps(ctx, skip_keys=("rti-connext-dds",))
    text = output(ctx)
    assert "--skip-keys" in text
    assert "gazebo rti-connext-dds" in text
