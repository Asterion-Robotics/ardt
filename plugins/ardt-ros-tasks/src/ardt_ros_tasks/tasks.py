"""The three tasks, as library functions. The CLI in :mod:`ardt_ros_tasks.cli` is a thin front.

``deps`` (vcs import + rosdep install), ``build`` (colcon build), ``test``
(colcon test + a test-result summary). They wrap the standard ROS 2 tooling and
never reimplement it.

Exclusions follow the space-ros pattern: import a broad ``.repos``, then skip
chosen packages everywhere (rosdep resolution via ``colcon list
--packages-skip``, build and test via ``--packages-skip``) and chosen rosdep
keys (``--skip-keys``). Config (``tasks.ros.exclude_packages`` /
``rosdep_skip_keys``) and CLI flags merge.
"""

from __future__ import annotations

import shlex
from pathlib import Path

from ardt_core.context import Context
from ardt_core.errors import ArdtError
from ardt_core.runner import Result

from .config import RosConfig, ros_config


def _ros_setup(cfg: RosConfig) -> Path:
    return Path(cfg.source_base) / cfg.distro / "setup.bash"


def _sourced(ctx: Context, cfg: RosConfig, script: str) -> list[str]:
    """Run a shell script with the ROS distro sourced, when one is present.

    On a host without ``/opt/ros/<distro>`` (a laptop using a devcontainer, say)
    the script runs bare and colcon fails with its own clear message — better
    than ardt guessing at an underlay.
    """
    setup = _ros_setup(cfg)
    if not setup.is_file():
        ctx.console.detail(f"{setup} not found; running without sourcing a ROS underlay")
        return ["bash", "-c", f"set -e; {script}"]
    return ["bash", "-c", f"set -e; . {shlex.quote(str(setup))}; {script}"]


def _in_ros_env(ctx: Context, cfg: RosConfig, command: list[str]) -> list[str]:
    return _sourced(ctx, cfg, f"exec {shlex.join(command)}")


def deps(
    ctx: Context,
    *,
    skip_vcs: bool = False,
    skip_rosdep: bool = False,
    skip_keys: tuple[str, ...] = (),
    exclude_packages: tuple[str, ...] = (),
) -> None:
    """Import ``.repos`` sources, then install system dependencies with rosdep."""
    cfg = ros_config(ctx.cfg)

    if not skip_vcs and cfg.repos_file:
        repos = ctx.project_root / cfg.repos_file
        if not repos.is_file():
            raise ArdtError(
                f"repos file {cfg.repos_file} does not exist",
                hint="fix `tasks.ros.repos_file` in ardt.yaml, or pass --skip-vcs",
            )
        target = ctx.project_root / cfg.repos_target
        with ctx.console.section(f"vcs import {cfg.repos_file}"):
            ctx.runner.require("vcs", hint="pip install vcstool")
            if not ctx.dry_run:
                target.mkdir(parents=True, exist_ok=True)
            ctx.runner.run(
                ["bash", "-c", f"vcs import {shlex.quote(str(target))} < {shlex.quote(str(repos))}"]
            )

    if skip_rosdep:
        return

    excluded = (*cfg.exclude_packages, *exclude_packages)
    keys = (*cfg.rosdep_skip_keys, *skip_keys)

    with ctx.console.section("rosdep install"):
        ctx.runner.require("rosdep", hint="apt install python3-rosdep")
        ctx.runner.require("colcon", hint="apt install python3-colcon-common-extensions")
        # Paths come from colcon, not a raw directory scan: colcon honors the
        # COLCON_IGNORE markers in build/install trees (rosdep does not), and
        # --packages-skip is the space-ros pattern — resolve deps only for the
        # packages that will actually build.
        listing = "colcon list --paths-only"
        if excluded:
            listing += f" --packages-skip {shlex.join(excluded)}"
        script = f"rosdep install --from-paths $({listing}) --ignore-src -r -y"
        if keys:
            script += f" --skip-keys {shlex.quote(' '.join(keys))}"
        ctx.runner.run(_sourced(ctx, cfg, script))


def build(
    ctx: Context,
    *,
    packages: tuple[str, ...] = (),
    exclude_packages: tuple[str, ...] = (),
    extra_args: tuple[str, ...] = (),
    symlink: bool | None = None,
    install_base: str | None = None,
) -> None:
    """``colcon build`` in the project root.

    ``symlink`` and ``install_base`` override their ``tasks.ros`` config values
    when given — image builds need real files in a fixed install base, dev
    checkouts want symlinks in ``install/``.
    """
    cfg = ros_config(ctx.cfg)
    command = ["colcon", "build"]
    if symlink if symlink is not None else cfg.symlink_install:
        command.append("--symlink-install")
    if cfg.merge_install:
        command.append("--merge-install")
    base = install_base or cfg.install_base
    if base:
        command += ["--install-base", base]
    if packages:
        command += ["--packages-select", *packages]
    excluded = (*cfg.exclude_packages, *exclude_packages)
    if excluded:
        command += ["--packages-skip", *excluded]
    command += cfg.build_args
    command += extra_args

    with ctx.console.section("colcon build"):
        ctx.runner.require("colcon", hint="apt install python3-colcon-common-extensions")
        ctx.runner.run(_in_ros_env(ctx, cfg, command))
    ctx.emit(build_ok=True, install_base=base or "install")


def test(
    ctx: Context,
    *,
    packages: tuple[str, ...] = (),
    exclude_packages: tuple[str, ...] = (),
    extra_args: tuple[str, ...] = (),
    install_base: str | None = None,
) -> None:
    """``colcon test`` followed by a ``colcon test-result`` summary.

    JUnit XMLs land at the fixed convention ``build/**/test_results/**/*.xml`` so
    pipelines can export them without knowing anything about the repo.
    """
    cfg = ros_config(ctx.cfg)
    command = ["colcon", "test"]
    base = install_base or cfg.install_base
    if base:
        command += ["--install-base", base]
    if packages:
        command += ["--packages-select", *packages]
    excluded = (*cfg.exclude_packages, *exclude_packages)
    if excluded:
        command += ["--packages-skip", *excluded]
    command += cfg.test_args
    command += extra_args

    with ctx.console.section("colcon test"):
        ctx.runner.require("colcon", hint="apt install python3-colcon-common-extensions")
        # Let the summary below produce the diagnosis, rather than a bare exit code.
        test_run: Result = ctx.runner.run(_in_ros_env(ctx, cfg, command), check=False)

    with ctx.console.section("test results"):
        summary = ctx.runner.run(
            _in_ros_env(ctx, cfg, ["colcon", "test-result", "--all", "--verbose"]),
            check=False,
        )

    ctx.emit(junit_glob="build/**/test_results/**/*.xml", tests_ok=summary.ok and test_run.ok)

    if ctx.dry_run:
        return
    if not summary.ok:
        raise ArdtError(
            "tests failed",
            hint="see the `colcon test-result` summary above for the failing packages",
        )
    if not test_run.ok:
        raise ArdtError(
            f"`colcon test` exited {test_run.returncode} but reported no failing test",
            hint="usually a package that failed to configure; check the output above",
        )
