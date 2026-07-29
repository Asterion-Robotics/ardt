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

"""`ardt dev doctor`'s checks, separated from the command front.

Each check appends ``(level, label, detail)``; the CLI renders and decides the
exit code. Pure enough to assert check by check with a captured context.
"""

from __future__ import annotations

from ardt_core.context import Context

from . import docker as docker_module
from . import manifest as manifest_module
from .config import ci_builder
from .render import Render


def run_checks(ctx: Context, plan: Render) -> list[tuple[str, str, str]]:
    """Every doctor verdict, as ``(level, label, detail)`` rows."""
    checks: list[tuple[str, str, str]] = []

    def check(level: str, label: str, detail: str) -> None:
        checks.append((level, label, detail))

    builder = ci_builder(ctx.cfg)
    if builder is None:
        check(
            "warn",
            "CI parity",
            "repo sets no pipelines.ros_ci.builder — nothing to compare the dev base against",
        )
    elif builder == plan.base_image:
        check("ok", "CI parity", f"dev base == ros_ci.builder ({builder})")
    else:
        check("fail", "CI parity", f"dev base {plan.base_image} != ros_ci.builder {builder}")

    if ctx.cfg.ardt.version:
        check("ok", "ardt pin", f"{ctx.cfg.ardt.git}@{ctx.cfg.ardt.version}")
    else:
        check("warn", "ardt pin", "ardt.version unset: container and CI both track HEAD")
    if plan.ardt_source:
        check("warn", "ardt source", f"local checkout {plan.ardt_source} (not the pin)")

    state = manifest_module.audit(ctx.project_root, plan)
    if state.conflicts:
        check("fail", "render", f"hand-edited: {', '.join(sorted(state.conflicts))}")
    elif state.written:
        check("warn", "render", f"stale, run `ardt dev sync`: {', '.join(sorted(state.written))}")
    else:
        check("ok", "render", f"{len(state.unchanged)} files match this ardt-dev")

    missing = manifest_module.missing_gitignore_entries(ctx.project_root)
    check(
        "fail" if missing else "ok",
        "gitignore",
        f"NOT ignored: {', '.join(missing)}" if missing else "the whole render is ignored",
    )

    check("ok", "host", f"{plan.host.kind}, gui {'on' if plan.host.gui else 'off'}")
    for note in plan.host.notes:
        check("warn", "host", note)

    if not docker_module.in_container():
        if ctx.runner.which("docker") is None:
            check("fail", "docker", "not on PATH")
        else:
            ok, detail = docker_module.daemon_status(ctx)
            check("ok" if ok else "fail", "docker", detail)

    return checks
