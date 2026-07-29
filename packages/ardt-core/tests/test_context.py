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

"""The Context: assembly, version wiring, section validation, the info dump."""

from __future__ import annotations

from pathlib import Path

import pytest

from ardt_core.context import Context
from ardt_core.errors import ConfigError
from ardt_core.plugins import Registry
from ardt_core.testing import git


def build(root: Path, **kwargs: object) -> Context:
    return Context.build(cwd=root, registry=Registry(plugins=[], problems=[]), **kwargs)  # type: ignore[arg-type]


def test_build_in_a_repo(repo: Path) -> None:
    ctx = build(repo)
    assert ctx.project_root == repo.resolve()
    assert ctx.project == "proj"
    assert ctx.git.branch == "main"
    assert ctx.version.startswith("0.0.0.dev1+g")
    assert ctx.is_release is False


def test_inventing_attributes_is_an_error(repo: Path) -> None:
    """slots=True: `ctx.pubish = True` must fail loudly, not silently create a
    side channel while `publish` stays False."""
    ctx = build(repo)
    with pytest.raises(AttributeError):
        ctx.pubish = True  # type: ignore[attr-defined]


def test_version_is_computed_once(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The manual `_version` cache must behave like the cached_property it replaced."""
    from ardt_core import context as context_module

    ctx = build(repo)
    calls: list[int] = []

    def fake_compute(git_info: object) -> str:
        calls.append(1)
        return "1.2.3"

    monkeypatch.setattr(context_module.version_module, "compute", fake_compute)
    assert ctx.version == "1.2.3"
    assert ctx.version == "1.2.3"
    assert calls == [1]


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
    (repo / "ardt.yaml").write_text("doc:\n  source_dir: doc\n")
    ctx = build(repo)  # doc plugin not installed -> warning, not error
    assert ctx.cfg.section("doc") == {"source_dir": "doc"}


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
