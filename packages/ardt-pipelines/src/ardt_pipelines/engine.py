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

"""Connecting to Dagger and executing a pipeline.

All engine mechanics live here so that a ``dagger-io`` API bump lands in one file
The SDK auto-provisions the engine when it finds a Docker socket; on
CI runners the shim points ``_EXPERIMENTAL_DAGGER_RUNNER_HOST`` at the persistent
engine instead — both are transparent to this code.
"""

from __future__ import annotations

import asyncio
import sys

import dagger

from ardt_core.context import Context
from ardt_core.errors import ArdtError

from .registry import PipelineDef


def run_pipeline(ctx: Context, definition: PipelineDef, bound: dict[str, object]) -> None:
    """Execute one pipeline. Under ``--dry-run``, print the plan and stop."""
    rendered = " ".join(f"{k}={v!r}" for k, v in bound.items()) or "(no args)"
    if ctx.dry_run:
        ctx.console.info(f"[dry-run] pipe run {definition.name} {rendered}")
        ctx.console.info(f"[dry-run] publish={ctx.publish} version={ctx.version}")
        return

    ctx.console.step(f"pipeline {definition.name} ({rendered})")
    try:
        asyncio.run(_execute(ctx, definition, bound))
    except dagger.DaggerError as exc:
        raise ArdtError(
            f"pipeline `{definition.name}` failed: {_first_line(exc)}",
            hint="see the engine log above",
        ) from exc


async def _execute(ctx: Context, definition: PipelineDef, bound: dict[str, object]) -> None:
    # Engine logs go to stderr: stdout stays reserved for the --json envelope.
    config = dagger.Config(log_output=sys.stderr)
    async with dagger.connection(config):
        await definition.func(ctx, dagger.dag, **bound)


def _first_line(exc: Exception) -> str:
    text = str(exc) or exc.__class__.__name__
    return text.splitlines()[0]
