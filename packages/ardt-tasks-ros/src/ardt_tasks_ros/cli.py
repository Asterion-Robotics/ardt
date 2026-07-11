"""Click commands mounted at ``ardt deps`` / ``ardt build`` / ``ardt test``.

Thin fronts: every command is one call into :mod:`.tasks`. ``--dry-run`` and
``--json`` are injected by core and are deliberately absent here.
"""

from __future__ import annotations

import click

from ardt_core.cli import pass_ardt
from ardt_core.context import Context

from . import tasks

_packages_option = click.option(
    "--packages-select",
    "packages",
    multiple=True,
    metavar="PKG",
    help="Restrict to these packages (repeatable).",
)


@click.command()
@click.option("--skip-vcs", is_flag=True, help="Do not import the .repos file.")
@click.option("--skip-rosdep", is_flag=True, help="Do not run rosdep install.")
@pass_ardt
def deps(ctx: Context, skip_vcs: bool, skip_rosdep: bool) -> None:
    """Import workspace sources and install system dependencies."""
    tasks.deps(ctx, skip_vcs=skip_vcs, skip_rosdep=skip_rosdep)


@click.command(context_settings={"ignore_unknown_options": True})
@_packages_option
@click.option(
    "--symlink-install/--no-symlink-install",
    "symlink",
    default=None,
    help="Override tasks.ros.symlink_install from the config.",
)
@click.argument("colcon_args", nargs=-1, type=click.UNPROCESSED)
@pass_ardt
def build(
    ctx: Context,
    packages: tuple[str, ...],
    symlink: bool | None,
    colcon_args: tuple[str, ...],
) -> None:
    """Build the workspace with colcon.

    Arguments after `--` are passed through to colcon.
    """
    tasks.build(ctx, packages=packages, extra_args=colcon_args, symlink=symlink)


@click.command(context_settings={"ignore_unknown_options": True})
@_packages_option
@click.argument("colcon_args", nargs=-1, type=click.UNPROCESSED)
@pass_ardt
def test(ctx: Context, packages: tuple[str, ...], colcon_args: tuple[str, ...]) -> None:
    """Run the workspace's tests and summarize the results."""
    tasks.test(ctx, packages=packages, extra_args=colcon_args)
