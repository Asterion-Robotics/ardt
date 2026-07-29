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
``ardt.commands``     must load to a :class:`click.Command` (command or group),
                      mounted at the top level; anything else refuses the plugin
``ardt.pipelines``    must load to a *module* exposing ``@pipeline`` functions
                      (checked by ``ardt_pipelines.collect``)
``ardt.templates``    scaffold sets for ``ardt new`` (contract not yet enforced)
===================  ==========================================================

Every plugin distribution declares ``ARDT_PLUGIN_API`` on its root package: an
incompatible or undeclared API version is **refused loudly and skipped whole**
— never half-loaded, never a traceback, and never fatal to the rest of the CLI.

Loading is two-speed. Commands load at discovery (almost every invocation,
``--help`` included, needs them) with the whole-or-nothing rule above. Pipeline
and template entry points defer until :meth:`Registry.load_deferred` — pipeline
modules import the Dagger SDK, which no ``ardt build`` should pay for. A
deferred load failure is reported as a :class:`Problem` and the group stays
empty; the plugin's already-mounted commands remain (the one place a plugin can
be observed part-loaded, and only when its own pipeline module is broken).

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

import click

ARDT_PLUGIN_API = 1
"""Bumped with core majors. Plugins declaring another value are refused."""

COMMANDS_GROUP = "ardt.commands"
PIPELINES_GROUP = "ardt.pipelines"
TEMPLATES_GROUP = "ardt.templates"
GROUPS = (COMMANDS_GROUP, PIPELINES_GROUP, TEMPLATES_GROUP)


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
    commands: dict[str, object] = field(default_factory=dict[str, object])
    pipelines: dict[str, object] = field(default_factory=dict[str, object])
    """Empty until :meth:`Registry.load_deferred` runs."""
    templates: dict[str, object] = field(default_factory=dict[str, object])
    """Empty until :meth:`Registry.load_deferred` runs."""
    deferred: list[metadata.EntryPoint] = field(
        default_factory=list[metadata.EntryPoint], repr=False
    )
    """Pipeline/template entry points not yet loaded; drained by
    :meth:`Registry.load_deferred`."""


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

    def load_deferred(self) -> None:
        """Load the pipeline/template entry points. Idempotent.

        Called by the consumers that need those groups (``ardt pipe``,
        ``ardt plugins``); everything else never imports a pipeline module.
        A failure empties the plugin's deferred groups and becomes a
        :class:`Problem` — the CLI stays alive, ``ardt plugins`` explains.
        """
        for plugin in self.plugins:
            entry_points, plugin.deferred = plugin.deferred, []
            for entry_point in entry_points:
                try:
                    loaded: object = entry_point.load()
                except Exception as exc:
                    plugin.pipelines.clear()
                    plugin.templates.clear()
                    self.problems.append(
                        Problem(
                            plugin.name,
                            f"entry point `{entry_point.name}` failed: {_brief(exc)}",
                        )
                    )
                    break
                target = (
                    plugin.pipelines if entry_point.group == PIPELINES_GROUP else plugin.templates
                )
                target[entry_point.name] = loaded


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

    # Cross-plugin command collisions: :meth:`Registry.commands` merges in this
    # same order, so the later plugin wins — silently, unless reported here.
    owners: dict[str, str] = {}
    for plugin in plugins:
        for command in plugin.commands:
            if command in owners:
                problems.append(
                    Problem(
                        plugin.name,
                        f"command `{command}` is also provided by `{owners[command]}`; "
                        f"`{plugin.name}`'s wins",
                    )
                )
            owners[command] = plugin.name

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

    # Commands load whole-or-nothing: one bad entry point disqualifies the
    # distribution, so a plugin never contributes half its commands. Pipeline
    # and template entry points defer (Registry.load_deferred): pipeline
    # modules import the Dagger SDK, which most invocations never need.
    for entry_point in entry_points:
        if entry_point.group != COMMANDS_GROUP:
            plugin.deferred.append(entry_point)
            continue
        try:
            loaded: object = entry_point.load()
        except Exception as exc:
            return None, Problem(name, f"entry point `{entry_point.name}` failed: {_brief(exc)}")
        # An entry point aimed at the wrong attribute used to vanish silently
        # (the CLI filtered non-click objects); wrong type is a refusal like
        # any other, so the author hears about it instead of missing a command.
        if not isinstance(loaded, click.Command):
            return None, Problem(
                name,
                f"entry point `{entry_point.name}` must load to a click.Command, "
                f"got {type(loaded).__name__}",
            )
        plugin.commands[entry_point.name] = loaded

    return plugin, None


def _version(distribution: str) -> str:
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:  # pragma: no cover - editable oddities
        return "unknown"


def _brief(exc: Exception) -> str:
    text = str(exc) or exc.__class__.__name__
    return text.splitlines()[0]
