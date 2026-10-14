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

"""Executing a pipeline.

A pipeline runs on BuildKit through :class:`~ardt_pipelines.buildx.Buildx`,
which the runner hands it as its second argument. A pipeline registered with
``engine="dagger"`` keeps the previous executor (a Dagger client as its second
argument) until it is ported; that path imports the Dagger SDK only when such
a pipeline actually runs, so no other invocation pays for it.
"""

from __future__ import annotations

import asyncio
import inspect
import sys

from ardt_core.context import Context
from ardt_core.errors import ArdtError

from .buildx import Buildx
from .registry import PipelineDef


def run_pipeline(ctx: Context, definition: PipelineDef, bound: dict[str, object]) -> None:
    """Execute one pipeline. ``--dry-run`` never reaches here: the CLI prints
    the plan and returns before this module is even imported."""
    rendered = " ".join(f"{k}={v!r}" for k, v in bound.items()) or "(no args)"
    ctx.console.step(f"pipeline {definition.name} ({rendered})")
    if definition.engine == "dagger":
        _run_dagger(ctx, definition, bound)
        return
    outcome = definition.func(ctx, Buildx(ctx), **bound)
    if inspect.iscoroutine(outcome):
        asyncio.run(outcome)


def _run_dagger(ctx: Context, definition: PipelineDef, bound: dict[str, object]) -> None:
    try:
        import dagger
    except ImportError as exc:  # pragma: no cover - the plugin declares the dependency
        raise ArdtError(
            f"pipeline `{definition.name}` runs on Dagger, which is not installed",
            hint="the plugin that registers it must depend on dagger-io",
        ) from exc

    async def execute() -> None:
        # Engine logs go to stderr: stdout stays reserved for the --json envelope.
        async with dagger.connection(dagger.Config(log_output=sys.stderr)):
            outcome = definition.func(ctx, dagger.dag, **bound)
            if outcome is not None:
                await outcome

    try:
        asyncio.run(execute())
    except dagger.DaggerError as exc:
        raise ArdtError(
            f"pipeline `{definition.name}` failed: {_first_line(exc)}",
            hint="see the engine log above",
        ) from exc


def _first_line(exc: Exception) -> str:
    text = str(exc) or exc.__class__.__name__
    return text.splitlines()[0]
