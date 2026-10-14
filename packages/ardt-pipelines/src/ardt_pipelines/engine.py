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

"""Executing a pipeline: the function runs with the context and a
:class:`~ardt_pipelines.buildx.Buildx` handle; an async pipeline is awaited."""

from __future__ import annotations

import asyncio
import inspect

from ardt_core.context import Context

from .buildx import Buildx
from .registry import PipelineDef


def run_pipeline(ctx: Context, definition: PipelineDef, bound: dict[str, object]) -> None:
    """Execute one pipeline. ``--dry-run`` never reaches here: the CLI prints
    the plan and returns before this module is even imported."""
    rendered = " ".join(f"{k}={v!r}" for k, v in bound.items()) or "(no args)"
    ctx.console.step(f"pipeline {definition.name} ({rendered})")
    outcome = definition.func(ctx, Buildx(ctx), **bound)
    if inspect.iscoroutine(outcome):
        asyncio.run(outcome)
