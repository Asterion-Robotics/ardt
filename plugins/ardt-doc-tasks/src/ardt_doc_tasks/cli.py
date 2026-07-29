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


@doc.command()
@click.option("--port", default=8000, show_default=True, help="Port to bind on 127.0.0.1.")
@click.option(
    "--site",
    is_flag=True,
    help="Serve the versioned site from public/ (docs-ci output) instead of build/doc/html.",
)
@pass_ardt
def serve(ctx: Context, port: int, site: bool) -> None:
    """Serve the built docs over local http (browsers cripple file:// sites)."""
    tasks.serve(ctx, port=port, site=site)
