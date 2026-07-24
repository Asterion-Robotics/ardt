"""The plugin loader: entry-point discovery, the API guard, report-and-skip."""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass

import pytest

from ardt_core import plugins
from ardt_core.plugins import discover


@dataclass
class FakeDist:
    name: str


class FakeEntryPoint:
    """Enough of importlib.metadata.EntryPoint for the loader."""

    def __init__(
        self,
        name: str,
        group: str,
        module: str,
        value: object,
        dist: str | None = None,
    ) -> None:
        self.name = name
        self.group = group
        self.module = module
        self._value = value
        self.dist = FakeDist(dist) if dist else None

    def load(self) -> object:
        if isinstance(self._value, Exception):
            raise self._value
        return self._value


@pytest.fixture
def fake_package(monkeypatch: pytest.MonkeyPatch):
    """Register a throwaway root package with a chosen (or missing) API version."""

    created: list[str] = []

    def make(root: str, api: object | None, section: str | None = None) -> None:
        module = types.ModuleType(root)
        if api is not None:
            module.ARDT_PLUGIN_API = api  # type: ignore[attr-defined]
        if section is not None:
            module.ARDT_CONFIG_SECTION = section  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, root, module)
        created.append(root)

    yield make


def _version_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(plugins, "_version", lambda _name: "9.9.9")


def test_compatible_plugin_loads(monkeypatch: pytest.MonkeyPatch, fake_package) -> None:
    fake_package("acme_plugin", plugins.ARDT_PLUGIN_API)
    _version_ok(monkeypatch)
    marker = object()
    eps = [
        FakeEntryPoint("hello", plugins.COMMANDS_GROUP, "acme_plugin.cli", marker, dist="acme-plug")
    ]

    registry = discover(eps)
    assert registry.problems == []
    assert len(registry.plugins) == 1
    plugin = registry.plugins[0]
    assert plugin.name == "acme-plug"
    assert plugin.commands == {"hello": marker}
    assert plugin.section == "acme"  # name-derived fallback


def test_declared_config_section_wins_over_derivation(
    monkeypatch: pytest.MonkeyPatch, fake_package
) -> None:
    """`ardt-ros-tasks` claims `tasks:`, not `ros:` — names group by theme,
    sections by plane, so the claim is an explicit declaration."""
    fake_package("acme_plugin", plugins.ARDT_PLUGIN_API, section="tasks")
    _version_ok(monkeypatch)
    eps = [
        FakeEntryPoint("hi", plugins.COMMANDS_GROUP, "acme_plugin.cli", object(), dist="acme-ros")
    ]

    plugin = discover(eps).plugins[0]
    assert plugin.section == "tasks"


def test_wrong_api_version_is_refused(monkeypatch: pytest.MonkeyPatch, fake_package) -> None:
    fake_package("acme_plugin", plugins.ARDT_PLUGIN_API + 1)
    _version_ok(monkeypatch)
    eps = [FakeEntryPoint("hi", plugins.COMMANDS_GROUP, "acme_plugin.cli", object(), dist="acme")]

    registry = discover(eps)
    assert registry.plugins == []
    assert len(registry.problems) == 1
    assert "ARDT_PLUGIN_API" in registry.problems[0].reason


def test_missing_api_declaration_is_refused(monkeypatch: pytest.MonkeyPatch, fake_package) -> None:
    fake_package("acme_plugin", None)
    _version_ok(monkeypatch)
    eps = [FakeEntryPoint("hi", plugins.COMMANDS_GROUP, "acme_plugin.cli", object(), dist="acme")]

    registry = discover(eps)
    assert registry.plugins == []
    assert "declares no ARDT_PLUGIN_API" in registry.problems[0].reason


def test_import_failure_is_reported_not_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    # No such module registered -> importlib raises ModuleNotFoundError inside the loader.
    _version_ok(monkeypatch)
    eps = [FakeEntryPoint("hi", plugins.COMMANDS_GROUP, "ghost_pkg.cli", object(), dist="ghost")]

    registry = discover(eps)
    assert registry.plugins == []
    assert "import of `ghost_pkg` failed" in registry.problems[0].reason


def test_entry_point_load_failure_disqualifies_whole_plugin(
    monkeypatch: pytest.MonkeyPatch, fake_package
) -> None:
    fake_package("acme_plugin", plugins.ARDT_PLUGIN_API)
    _version_ok(monkeypatch)
    eps = [
        FakeEntryPoint("good", plugins.COMMANDS_GROUP, "acme_plugin.cli", object(), dist="acme"),
        FakeEntryPoint(
            "bad",
            plugins.COMMANDS_GROUP,
            "acme_plugin.cli",
            RuntimeError("boom"),
            dist="acme",
        ),
    ]

    registry = discover(eps)
    assert registry.plugins == []  # whole-or-nothing: the good command is dropped too
    assert "entry point `bad` failed" in registry.problems[0].reason


def test_all_three_groups_are_collected(monkeypatch: pytest.MonkeyPatch, fake_package) -> None:
    fake_package("acme_plugin", plugins.ARDT_PLUGIN_API)
    _version_ok(monkeypatch)
    eps = [
        FakeEntryPoint("cmd", plugins.COMMANDS_GROUP, "acme_plugin.cli", object(), dist="acme"),
        FakeEntryPoint("pipe", plugins.PIPELINES_GROUP, "acme_plugin.pipe", object(), dist="acme"),
        FakeEntryPoint("tset", plugins.TEMPLATES_GROUP, "acme_plugin.tpl", object(), dist="acme"),
    ]

    plugin = discover(eps).plugins[0]
    assert set(plugin.commands) == {"cmd"}
    assert set(plugin.pipelines) == {"pipe"}
    assert set(plugin.templates) == {"tset"}


def test_registry_helpers(monkeypatch: pytest.MonkeyPatch, fake_package) -> None:
    fake_package("acme_plugin", plugins.ARDT_PLUGIN_API)
    _version_ok(monkeypatch)
    eps = [FakeEntryPoint("cmd", plugins.COMMANDS_GROUP, "acme_plugin.cli", 1, dist="ardt-tasks")]

    registry = discover(eps)
    assert registry.sections == frozenset({"tasks"})
    assert registry.commands() == {"cmd": 1}


def test_real_installed_plugin_is_discovered() -> None:
    """The genuinely-installed ardt-ros-tasks must load with no problems."""
    registry = discover()
    names = {p.name for p in registry.plugins}
    assert "ardt-ros-tasks" in names
    assert registry.problems == []
