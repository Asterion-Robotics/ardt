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

"""The ``@pipeline`` decorator and registry.

A pipeline is a plain async function taking ``(ctx, dag, *keyword params)``;
parameters come from CLI ``--arg k=v`` and are coerced to the annotated types.
Plugins expose pipelines by pointing an ``ardt.pipelines`` entry point at a module;
every :class:`PipelineDef` found in that module is registered.

No Dagger import here: the registry and parameter binding are engine-free so they
stay unit-testable anywhere.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from types import ModuleType
from typing import Any

from ardt_core.errors import ArdtError

PipelineFunc = Callable[..., Awaitable[None]]

_SUPPORTED = ("str", "int", "float", "bool", "list[str]")


@dataclass(frozen=True)
class Param:
    """One user-settable pipeline parameter."""

    name: str
    annotation: str
    """Textual annotation; one of ``str``/``int``/``float``/``bool``/``list[str]``."""
    default: object
    required: bool


@dataclass(frozen=True)
class PipelineDef:
    """A registered pipeline: the function plus its introspected signature."""

    name: str
    doc: str
    func: PipelineFunc
    params: tuple[Param, ...]

    def bind(self, args: Mapping[str, str]) -> dict[str, object]:
        """Coerce ``--arg k=v`` strings to the annotated parameter types."""
        known = {p.name: p for p in self.params}
        unknown = sorted(set(args) - set(known))
        if unknown:
            raise ArdtError(
                f"pipeline `{self.name}` has no parameter `{unknown[0]}`",
                hint=f"parameters: {', '.join(known) or '(none)'}",
            )
        bound: dict[str, object] = {}
        for param in self.params:
            if param.name in args:
                bound[param.name] = _coerce(self.name, param, args[param.name])
            elif param.required:
                raise ArdtError(
                    f"pipeline `{self.name}` requires --arg {param.name}=…",
                )
        return bound


def _annotation_name(annotation: object) -> str:
    if annotation is inspect.Parameter.empty:
        return "str"
    if isinstance(annotation, str):  # `from __future__ import annotations`
        return annotation.replace(" ", "")
    return getattr(annotation, "__name__", str(annotation))


def _coerce(pipeline_name: str, param: Param, raw: str) -> object:
    kind = param.annotation
    try:
        if kind == "int":
            return int(raw)
        if kind == "float":
            return float(raw)
        if kind == "bool":
            lowered = raw.lower()
            if lowered in {"1", "true", "yes", "on"}:
                return True
            if lowered in {"0", "false", "no", "off"}:
                return False
            raise ValueError(raw)
        if kind == "list[str]":
            return [item for item in (part.strip() for part in raw.split(",")) if item]
        return raw
    except ValueError as exc:
        raise ArdtError(
            f"pipeline `{pipeline_name}`: --arg {param.name}={raw!r} is not a valid {kind}"
        ) from exc


def pipeline(name: str, doc: str = "") -> Callable[[PipelineFunc], PipelineDef]:
    """Register an async function as a pipeline.

    The first two parameters (context and Dagger client) are injected by the
    runner; everything after is a user parameter settable via ``--arg``.
    """

    def decorate(func: PipelineFunc) -> PipelineDef:
        signature = inspect.signature(func)
        parameters = list(signature.parameters.values())
        if len(parameters) < 2:
            raise ArdtError(f"pipeline `{name}` must take (ctx, dag) as its first two parameters")
        params: list[Param] = []
        for p in parameters[2:]:
            annotation = _annotation_name(p.annotation)
            if annotation not in _SUPPORTED:
                raise ArdtError(
                    f"pipeline `{name}`: parameter `{p.name}: {annotation}` unsupported",
                    hint=f"supported: {', '.join(_SUPPORTED)}",
                )
            params.append(
                Param(
                    name=p.name,
                    annotation=annotation,
                    default=None if p.default is inspect.Parameter.empty else p.default,
                    required=p.default is inspect.Parameter.empty,
                )
            )
        return PipelineDef(
            name=name,
            doc=doc or inspect.getdoc(func) or "",
            func=func,
            params=tuple(params),
        )

    return decorate


def collect(modules: Mapping[str, Any]) -> dict[str, PipelineDef]:
    """Gather every :class:`PipelineDef` from plugin-provided pipeline modules.

    ``modules`` is the merged ``ardt.pipelines`` entry-point mapping from the
    plugin registry. A duplicate pipeline name across plugins is an error — a
    pipeline invocation must never be ambiguous.
    """
    found: dict[str, PipelineDef] = {}
    for entry_name, module in modules.items():
        if not isinstance(module, ModuleType):
            raise ArdtError(
                f"ardt.pipelines entry point `{entry_name}` must point at a module, "
                f"got {type(module).__name__}"
            )
        for attribute in vars(module).values():
            if isinstance(attribute, PipelineDef):
                if attribute.name in found:
                    raise ArdtError(
                        f"pipeline `{attribute.name}` is defined by two plugins",
                        hint=f"second definition found in `{module.__name__}`",
                    )
                found[attribute.name] = attribute
    return found
