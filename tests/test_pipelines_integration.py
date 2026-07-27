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

"""The one engine-backed test: a trivial pipeline against real Dagger.

Marked ``integration``: excluded by default, run with ``pytest -m integration``.
Needs a Docker socket; the SDK auto-provisions the engine on first use, so the
first run downloads the engine image (slow once, cached after).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ardt_core.context import Context
from ardt_core.plugins import Registry
from ardt_pipelines import pipeline
from ardt_pipelines.engine import run_pipeline

pytestmark = pytest.mark.integration


def test_trivial_pipeline_against_real_engine(repo: Path) -> None:
    @pipeline(name="trivial", doc="echo in alpine")
    async def trivial(ctx: Context, dag, message: str = "hello") -> None:
        out = await dag.container().from_("alpine:3.20").with_exec(["echo", message]).stdout()
        ctx.emit(echoed=out.strip())

    ctx = Context.build(cwd=repo, registry=Registry(plugins=[], problems=[]))
    run_pipeline(ctx, trivial, trivial.bind({"message": "ardt-engine-ok"}))
    assert ctx.emitted["echoed"] == "ardt-engine-ok"
