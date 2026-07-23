"""The ``ardt doc`` command group. Thin fronts over :mod:`.tasks`."""

from __future__ import annotations

import click

from ardt_core.cli import pass_ardt
from ardt_core.context import Context

from . import tasks


@click.group()
def doc() -> None:
    """Build the project documentation."""


@doc.command()
@pass_ardt
def build(ctx: Context) -> None:
    """Build the docs: doxygen (C++ repos) then sphinx html into build/doc."""
    tasks.build(ctx)
