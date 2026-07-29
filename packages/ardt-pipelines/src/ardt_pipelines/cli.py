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

"""The ``ardt pipe`` command group."""

from __future__ import annotations

import click

from ardt_core.cli import pass_ardt
from ardt_core.context import Context
from ardt_core.errors import ArdtError

from .registry import PipelineDef, collect


def _pipelines(ctx: Context) -> dict[str, PipelineDef]:
    ctx.registry.load_deferred()  # pipeline modules (and dagger) import here, not at startup
    modules: dict[str, object] = {}
    for plugin in ctx.registry.plugins:
        for entry_name, module in plugin.pipelines.items():
            modules[f"{plugin.name}:{entry_name}"] = module
    return collect(modules)


@click.group()
def pipe() -> None:
    """Run and inspect pipelines (the Dagger plane)."""


@pipe.command(name="list")
@pass_ardt
def list_command(ctx: Context) -> None:
    """List registered pipelines and their parameters."""
    pipelines = _pipelines(ctx)
    ctx.emit(
        pipelines=[
            {
                "name": d.name,
                "doc": d.doc,
                "params": [
                    {
                        "name": p.name,
                        "type": p.annotation,
                        "default": p.default,
                        "required": p.required,
                    }
                    for p in d.params
                ],
            }
            for d in pipelines.values()
        ]
    )
    if ctx.json_output:
        return
    if not pipelines:
        ctx.console.info("no pipelines registered")
        return
    for definition in sorted(pipelines.values(), key=lambda d: d.name):
        summary = definition.doc.splitlines()[0] if definition.doc else ""
        ctx.console.info(definition.name)
        if summary:
            ctx.console.info(f"    {summary}")
        for param in definition.params:
            spec = "(required)" if param.required else f"(default: {param.default!r})"
            ctx.console.info(f"    --arg {param.name}=<{param.annotation}> {spec}")


@pipe.command(name="run")
@click.argument("name")
@click.option(
    "--arg",
    "args",
    multiple=True,
    metavar="KEY=VALUE",
    help="Set a pipeline parameter (repeatable).",
)
@click.option("--publish", is_flag=True, help="Allow the pipeline to push artifacts.")
@pass_ardt
def run_command(ctx: Context, name: str, args: tuple[str, ...], publish: bool) -> None:
    """Run a pipeline by name."""
    pipelines = _pipelines(ctx)
    definition = pipelines.get(name)
    if definition is None:
        known = ", ".join(sorted(pipelines)) or "(none)"
        raise ArdtError(f"no pipeline named `{name}`", hint=f"registered: {known}")

    parsed: dict[str, str] = {}
    for item in args:
        key, separator, value = item.partition("=")
        if not separator or not key:
            raise ArdtError(f"--arg must be KEY=VALUE, got {item!r}")
        parsed[key] = value

    ctx.publish = publish
    bound = definition.bind(parsed)
    if ctx.dry_run:
        _print_plan(ctx, definition, bound)
        return
    # Imported here, not at module top: the engine imports the Dagger SDK, and
    # this `pipe` group is an eagerly-loaded command — a top-level import would
    # put dagger back on every invocation's startup path.
    from . import engine

    engine.run_pipeline(ctx, definition, bound)


def _print_plan(ctx: Context, definition: PipelineDef, bound: dict[str, object]) -> None:
    """The ``--dry-run`` plan: everything resolvable without the engine.

    Handled here, before the engine module is even imported, so a dry-run
    needs neither the Dagger SDK nor a docker daemon.
    """
    rendered = " ".join(f"{k}={v!r}" for k, v in bound.items()) or "(no args)"
    ctx.console.info(f"[dry-run] pipe run {definition.name} {rendered}")
    if definition.doc:
        ctx.console.info(f"[dry-run]   {definition.doc.splitlines()[0]}")
    for param in definition.params:
        if param.name in bound:
            value, source = bound[param.name], "--arg"
        else:
            value, source = param.default, "default"
        ctx.console.info(f"[dry-run]   {param.name}={value!r} ({source})")
    ctx.console.info(
        f"[dry-run] publish={ctx.publish} version={ctx.version} release={ctx.is_release}"
    )
