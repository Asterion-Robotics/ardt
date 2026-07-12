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

_exclude_option = click.option(
    "--exclude-pkg",
    "exclude_packages",
    multiple=True,
    metavar="PKG",
    help="Skip this package (repeatable; merges with tasks.ros.exclude_packages).",
)

_install_base_option = click.option(
    "--install-base",
    default=None,
    metavar="PATH",
    help="colcon install base (overrides tasks.ros.install_base).",
)


@click.command()
@click.option("--skip-vcs", is_flag=True, help="Do not import the .repos file.")
@click.option("--skip-rosdep", is_flag=True, help="Do not run rosdep install.")
@click.option(
    "--skip-key",
    "skip_keys",
    multiple=True,
    metavar="KEY",
    help="rosdep key to skip (repeatable; merges with tasks.ros.rosdep_skip_keys).",
)
@_exclude_option
@pass_ardt
def deps(
    ctx: Context,
    skip_vcs: bool,
    skip_rosdep: bool,
    skip_keys: tuple[str, ...],
    exclude_packages: tuple[str, ...],
) -> None:
    """Import workspace sources and install system dependencies."""
    tasks.deps(
        ctx,
        skip_vcs=skip_vcs,
        skip_rosdep=skip_rosdep,
        skip_keys=skip_keys,
        exclude_packages=exclude_packages,
    )


@click.command(context_settings={"ignore_unknown_options": True})
@_packages_option
@_exclude_option
@_install_base_option
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
    exclude_packages: tuple[str, ...],
    install_base: str | None,
    symlink: bool | None,
    colcon_args: tuple[str, ...],
) -> None:
    """Build the workspace with colcon.

    Arguments after `--` are passed through to colcon.
    """
    tasks.build(
        ctx,
        packages=packages,
        exclude_packages=exclude_packages,
        extra_args=colcon_args,
        symlink=symlink,
        install_base=install_base,
    )


@click.command(context_settings={"ignore_unknown_options": True})
@_packages_option
@_exclude_option
@_install_base_option
@click.argument("colcon_args", nargs=-1, type=click.UNPROCESSED)
@pass_ardt
def test(
    ctx: Context,
    packages: tuple[str, ...],
    exclude_packages: tuple[str, ...],
    install_base: str | None,
    colcon_args: tuple[str, ...],
) -> None:
    """Run the workspace's tests and summarize the results."""
    tasks.test(
        ctx,
        packages=packages,
        exclude_packages=exclude_packages,
        extra_args=colcon_args,
        install_base=install_base,
    )
