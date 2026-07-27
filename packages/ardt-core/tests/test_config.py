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

"""Config loading: precedence and namespaced plugin sections."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from ardt_core import config
from ardt_core.errors import ConfigError


def write(root: Path, name: str, text: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_defaults_when_nothing_present(tmp_path: Path) -> None:
    cfg, source = config.load(tmp_path)
    assert source.kind == "defaults"
    assert cfg.project.name is None


def test_ardt_yaml_is_loaded(tmp_path: Path) -> None:
    write(tmp_path, "ardt.yaml", "project:\n  name: widget\n")
    cfg, source = config.load(tmp_path)
    assert source.kind == "ardt.yaml"
    assert cfg.project.name == "widget"


def test_ardt_yaml_wins_over_pyproject(tmp_path: Path) -> None:
    write(tmp_path, "ardt.yaml", "project:\n  name: fromyaml\n")
    write(tmp_path, "pyproject.toml", '[tool.ardt]\nproject = { name = "frompyproject" }\n')
    cfg, source = config.load(tmp_path)
    assert source.kind == "ardt.yaml"
    assert cfg.project.name == "fromyaml"


def test_pyproject_tool_table(tmp_path: Path) -> None:
    write(tmp_path, "pyproject.toml", '[tool.ardt]\nproject = { name = "frompyproject" }\n')
    cfg, source = config.load(tmp_path)
    assert source.kind == "pyproject.toml"
    assert cfg.project.name == "frompyproject"


def test_pyproject_without_tool_ardt_is_defaults(tmp_path: Path) -> None:
    write(tmp_path, "pyproject.toml", "[project]\nname = 'x'\n")
    _, source = config.load(tmp_path)
    assert source.kind == "defaults"


def test_malformed_yaml_is_a_clean_error(tmp_path: Path) -> None:
    write(tmp_path, "ardt.yaml", "project: [unclosed\n")
    with pytest.raises(ConfigError):
        config.load(tmp_path)


def test_top_level_list_rejected(tmp_path: Path) -> None:
    write(tmp_path, "ardt.yaml", "- a\n- b\n")
    with pytest.raises(ConfigError):
        config.load(tmp_path)


def test_unknown_field_in_known_section_rejected(tmp_path: Path) -> None:
    write(tmp_path, "ardt.yaml", "project:\n  nope: 1\n")
    with pytest.raises(ConfigError):
        config.load(tmp_path)


def test_plugin_section_survives_as_raw_data(tmp_path: Path) -> None:
    write(tmp_path, "ardt.yaml", "tasks:\n  ros:\n    distro: kilted\n")
    cfg, _ = config.load(tmp_path)
    assert cfg.section("tasks") == {"ros": {"distro": "kilted"}}


class _Demo(BaseModel):
    distro: str = "jazzy"


def test_section_as_parses_into_a_model(tmp_path: Path) -> None:
    write(tmp_path, "ardt.yaml", "demo:\n  distro: kilted\n")
    cfg, _ = config.load(tmp_path)
    assert cfg.section_as("demo", _Demo).distro == "kilted"


def test_absent_section_is_empty() -> None:
    assert config.ArdtConfig().section("nope") == {}


def test_non_mapping_section_rejected(tmp_path: Path) -> None:
    write(tmp_path, "ardt.yaml", "tasks: 5\n")
    cfg, _ = config.load(tmp_path)
    with pytest.raises(ConfigError):
        cfg.section("tasks")


def test_unknown_sections_split_by_reserved(tmp_path: Path) -> None:
    write(tmp_path, "ardt.yaml", "doc:\n  x: 1\nwibble:\n  y: 2\n")
    cfg, _ = config.load(tmp_path)
    fatal, dormant = cfg.unknown_sections(installed=frozenset())
    assert fatal == ["wibble"]
    assert dormant == ["doc"]


def test_installed_plugin_section_is_neither(tmp_path: Path) -> None:
    write(tmp_path, "ardt.yaml", "tasks:\n  ros: {}\n")
    cfg, _ = config.load(tmp_path)
    fatal, dormant = cfg.unknown_sections(installed=frozenset({"tasks"}))
    assert fatal == []
    assert dormant == []


def test_find_project_root_by_config(tmp_path: Path) -> None:
    write(tmp_path, "ardt.yaml", "{}\n")
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    assert config.find_project_root(nested) == tmp_path.resolve()


def test_find_project_root_by_git(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    nested = tmp_path / "a"
    nested.mkdir()
    assert config.find_project_root(nested) == tmp_path.resolve()


def test_find_project_root_falls_back_to_start(tmp_path: Path) -> None:
    assert config.find_project_root(tmp_path) == tmp_path.resolve()


def test_find_project_root_resolves_a_colcon_workspace(tmp_path: Path) -> None:
    """/ws layout: the project is src/<repo>, findable from the workspace root."""
    write(tmp_path, "src/my_repo/ardt.yaml", "{}\n")
    (tmp_path / "build").mkdir()
    repo = (tmp_path / "src" / "my_repo").resolve()
    assert config.find_project_root(tmp_path) == repo
    assert config.find_project_root(tmp_path / "src") == repo
    assert config.find_project_root(tmp_path / "build") == repo
    # From inside the project the plain walk-up wins before the convention.
    nested = tmp_path / "src" / "my_repo" / "pkg"
    nested.mkdir()
    assert config.find_project_root(nested) == repo


def test_find_project_root_accepts_a_repo_checked_out_as_src(tmp_path: Path) -> None:
    write(tmp_path, "src/ardt.yaml", "{}\n")
    assert config.find_project_root(tmp_path) == (tmp_path / "src").resolve()


def test_find_project_root_refuses_to_guess_between_projects(tmp_path: Path) -> None:
    """Two configs under src/ (an imported dep can carry one) is ambiguous from outside."""
    write(tmp_path, "src/a/ardt.yaml", "{}\n")
    write(tmp_path, "src/b/ardt.yaml", "{}\n")
    with pytest.raises(ConfigError, match="several projects"):
        config.find_project_root(tmp_path)
    # Inside one of them there is nothing to guess.
    assert config.find_project_root(tmp_path / "src" / "a") == (tmp_path / "src" / "a").resolve()


def test_find_project_root_ignores_external_deps_one_level_down(tmp_path: Path) -> None:
    """`ardt deps` imports into src/external/<name>; those never join the lookup."""
    write(tmp_path, "src/my_repo/ardt.yaml", "{}\n")
    write(tmp_path, "src/external/dep/ardt.yaml", "{}\n")
    assert config.find_project_root(tmp_path) == (tmp_path / "src" / "my_repo").resolve()
