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

"""Plugin discovery via standard Python entry points — no bespoke mechanism.

A plugin provides any subset of three entry-point groups:

===================  ==========================================================
``ardt.commands``     click commands/groups mounted at the top level
``ardt.pipelines``    a module exposing ``@pipeline`` functions
``ardt.templates``    scaffold sets for ``ardt new``
===================  ==========================================================

Every plugin distribution declares ``ARDT_PLUGIN_API`` on its root package: an
incompatible or undeclared API version is **refused loudly and skipped whole**
— never half-loaded, never a traceback, and never fatal to the rest of the CLI.

A root package may also declare ``ARDT_CONFIG_SECTION`` — the ``ardt.yaml``
section it claims. Without it the section is derived from the distribution
name (first word after ``ardt-``), which is why every first-party plugin
declares it explicitly: package names group by theme (``ardt-ros-tasks``),
config sections group by plane (``tasks.ros``).
"""

from __future__ import annotations

import importlib
from collections.abc import Iterable
from dataclasses import dataclass, field
from importlib import metadata

ARDT_PLUGIN_API = 1
"""Bumped with core majors. Plugins declaring another value are refused."""

COMMANDS_GROUP = "ardt.commands"
PIPELINES_GROUP = "ardt.pipelines"
TEMPLATES_GROUP = "ardt.templates"
GROUPS = (COMMANDS_GROUP, PIPELINES_GROUP, TEMPLATES_GROUP)


def _empty() -> dict[str, object]:
    """A typed empty dict — bare ``dict`` as a default_factory infers Unknown."""
    return {}


@dataclass
class Plugin:
    """A successfully loaded plugin distribution."""

    name: str
    """The distribution name, e.g. ``ardt-ros-tasks``."""
    version: str
    api: int
    module: str
    """The root package that declared ``ARDT_PLUGIN_API``."""
    section: str = ""
    """The ``ardt.yaml`` section this plugin claims: the root package's
    ``ARDT_CONFIG_SECTION``, else derived from the distribution name."""
    commands: dict[str, object] = field(default_factory=_empty)
    pipelines: dict[str, object] = field(default_factory=_empty)
    templates: dict[str, object] = field(default_factory=_empty)


def derived_section(distribution: str) -> str:
    """The name-derived fallback section: first word after ``ardt-``."""
    return distribution.removeprefix("ardt-").split("-")[0]


@dataclass(frozen=True)
class Problem:
    """A plugin that was refused, and why. Reported, never raised."""

    name: str
    reason: str


@dataclass(frozen=True)
class Registry:
    """The result of discovery."""

    plugins: list[Plugin]
    problems: list[Problem]

    @property
    def sections(self) -> frozenset[str]:
        """Config sections claimed by installed plugins."""
        return frozenset(plugin.section for plugin in self.plugins)

    def commands(self) -> dict[str, object]:
        merged: dict[str, object] = {}
        for plugin in self.plugins:
            merged.update(plugin.commands)
        return merged


def _root_package(entry_point: metadata.EntryPoint) -> str:
    return entry_point.module.split(".")[0]


def _declared_api(root: str) -> int | None:
    module = importlib.import_module(root)
    api = getattr(module, "ARDT_PLUGIN_API", None)
    return api if isinstance(api, int) else None


def _distribution_name(entry_point: metadata.EntryPoint) -> str:
    dist = entry_point.dist
    return dist.name if dist is not None else _root_package(entry_point)


def _entry_points() -> list[metadata.EntryPoint]:
    found: list[metadata.EntryPoint] = []
    for group in GROUPS:
        found.extend(metadata.entry_points(group=group))
    return found


def discover(entry_points: Iterable[metadata.EntryPoint] | None = None) -> Registry:
    """Load every installed plugin. Failures become :class:`Problem` records, not exceptions."""
    eps = list(entry_points) if entry_points is not None else _entry_points()

    by_distribution: dict[str, list[metadata.EntryPoint]] = {}
    for entry_point in eps:
        by_distribution.setdefault(_distribution_name(entry_point), []).append(entry_point)

    plugins: list[Plugin] = []
    problems: list[Problem] = []

    for name, group_eps in sorted(by_distribution.items()):
        plugin, problem = _load_distribution(name, group_eps)
        if plugin is not None:
            plugins.append(plugin)
        if problem is not None:
            problems.append(problem)

    return Registry(plugins=plugins, problems=problems)


def _load_distribution(
    name: str, entry_points: list[metadata.EntryPoint]
) -> tuple[Plugin | None, Problem | None]:
    root = _root_package(entry_points[0])

    try:
        api = _declared_api(root)
    except Exception as exc:
        return None, Problem(name, f"import of `{root}` failed: {_brief(exc)}")

    if api is None:
        return None, Problem(
            name,
            f"`{root}` declares no ARDT_PLUGIN_API (expected {ARDT_PLUGIN_API})",
        )
    if api != ARDT_PLUGIN_API:
        return None, Problem(
            name,
            f"declares ARDT_PLUGIN_API {api}, this ardt speaks {ARDT_PLUGIN_API}",
        )

    declared = getattr(importlib.import_module(root), "ARDT_CONFIG_SECTION", None)
    section = declared if isinstance(declared, str) and declared else derived_section(name)
    plugin = Plugin(name=name, version=_version(name), api=api, module=root, section=section)

    # Load whole-or-nothing: one bad entry point disqualifies the distribution,
    # so a plugin never contributes half its commands.
    for entry_point in entry_points:
        try:
            loaded: object = entry_point.load()
        except Exception as exc:
            return None, Problem(name, f"entry point `{entry_point.name}` failed: {_brief(exc)}")
        target = {
            COMMANDS_GROUP: plugin.commands,
            PIPELINES_GROUP: plugin.pipelines,
            TEMPLATES_GROUP: plugin.templates,
        }[entry_point.group]
        target[entry_point.name] = loaded

    return plugin, None


def _version(distribution: str) -> str:
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:  # pragma: no cover - editable oddities
        return "unknown"


def _brief(exc: Exception) -> str:
    text = str(exc) or exc.__class__.__name__
    return text.splitlines()[0]
