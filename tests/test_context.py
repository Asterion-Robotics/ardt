"""The Context: assembly, version wiring, section validation, the info dump."""

from __future__ import annotations

from pathlib import Path

import pytest

from ardt_core.context import Context
from ardt_core.errors import ConfigError
from ardt_core.plugins import Registry

from .conftest import git


def build(root: Path, **kwargs: object) -> Context:
    return Context.build(cwd=root, registry=Registry(plugins=[], problems=[]), **kwargs)  # type: ignore[arg-type]


def test_build_in_a_repo(repo: Path) -> None:
    ctx = build(repo)
    assert ctx.project_root == repo.resolve()
    assert ctx.project == "proj"
    assert ctx.git.branch == "main"
    assert ctx.version.startswith("0.0.0.dev1+g")
    assert ctx.is_release is False


def test_project_name_from_config(repo: Path) -> None:
    (repo / "ardt.yaml").write_text("project:\n  name: widget\n")
    assert build(repo).project == "widget"


def test_version_on_a_tag_is_a_release(repo: Path) -> None:
    git("tag", "v2.0.0", cwd=repo)
    ctx = build(repo)
    assert ctx.version == "2.0.0"
    assert ctx.is_release is True


def test_unknown_section_is_fatal(repo: Path) -> None:
    (repo / "ardt.yaml").write_text("wibble:\n  x: 1\n")
    with pytest.raises(ConfigError):
        build(repo)


def test_dormant_known_section_only_warns(repo: Path) -> None:
    (repo / "ardt.yaml").write_text("aos:\n  sdk_line: '2.1'\n")
    ctx = build(repo)  # aos plugin not installed -> warning, not error
    assert ctx.cfg.section("aos") == {"sdk_line": "2.1"}


def test_emit_accumulates_into_the_envelope(repo: Path) -> None:
    ctx = build(repo)
    ctx.emit(a=1)
    ctx.emit(b=2)
    assert ctx.emitted == {"a": 1, "b": 2}


def test_describe_is_json_safe(repo: Path) -> None:
    import json

    ctx = build(repo)
    dumped = json.dumps(ctx.describe())
    assert "proj" in dumped
