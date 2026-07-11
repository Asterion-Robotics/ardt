"""The one engine-backed test (07 §5 AC): a trivial pipeline against real Dagger.

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
