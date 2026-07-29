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

"""Dry-run CLI coverage for the `ardt dev` group.

These stay `unit`: ``--dry-run`` plans everything and runs nothing, which is
itself the property under test — every command must be plannable on a fresh
clone, on a machine with no docker and nothing rendered. ``open`` is exercised
elsewhere: its editor probing depends on the real host.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ardt_core.cli import main

DEVCONTAINER = ".devcontainer"


def run(repo: Path, *args: str) -> int:
    return main(["-C", str(repo), *args])


def test_sync_dry_run_plans_the_render_and_writes_nothing(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(repo, "dev", "sync", "--dry-run") == 0
    assert "would render" in capsys.readouterr().err
    assert not (repo / DEVCONTAINER).exists()


def test_up_dry_run_on_a_fresh_clone_plans_without_writing(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Regression: `up --dry-run` used to refuse because the compose files the
    implicit sync would render did not exist yet."""
    assert run(repo, "dev", "up", "--dry-run") == 0
    err = capsys.readouterr().err
    assert "[dry-run]" in err
    assert "docker compose" in err
    assert not (repo / DEVCONTAINER).exists()


def test_down_dry_run_plans_the_compose_down(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(repo, "dev", "down", "--dry-run") == 0
    assert "down" in capsys.readouterr().err


def test_shell_dry_run_prints_the_exec_at_the_workspace_root(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(repo, "dev", "shell", "--dry-run") == 0
    assert "-w /ws" in capsys.readouterr().err


def test_volumes_dry_run_plans_the_provisioning(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(repo, "dev", "volumes", "--dry-run") == 0
    assert "docker volume create" in capsys.readouterr().err


def test_doctor_on_a_fresh_clone_names_the_gitignore_gap(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Nothing rendered, nothing ignored: doctor must fail and say which check."""
    assert run(repo, "dev", "doctor", "--dry-run") == 1
    err = capsys.readouterr().err
    assert "gitignore" in err
    assert "check(s) failed" in err


def test_sync_source_flags_are_mutually_exclusive(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = run(repo, "dev", "sync", "--dry-run", "--ardt-source", str(repo), "--from-pin")
    assert code == 1
    assert "mutually exclusive" in capsys.readouterr().err


def _seed_compile_commands(repo: Path, name: str, payload: str) -> Path:
    part = repo / "build" / name / "compile_commands.json"
    part.parent.mkdir(parents=True)
    part.write_text(payload, encoding="utf-8")
    return part


def test_compile_commands_dry_run_plans_the_merge_without_writing(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed_compile_commands(repo, "pkg_a", '[{"file": "a.cpp"}]')
    assert run(repo, "dev", "compile-commands", "--dry-run") == 0
    assert "would merge" in capsys.readouterr().err
    assert not (repo / "build" / "compile_commands.json").exists()


def test_compile_commands_merges_the_per_package_files(repo: Path) -> None:
    _seed_compile_commands(repo, "pkg_a", '[{"file": "a.cpp"}]')
    _seed_compile_commands(repo, "pkg_b", '[{"file": "b.cpp"}, {"file": "c.cpp"}]')
    assert run(repo, "dev", "compile-commands") == 0
    merged = json.loads((repo / "build" / "compile_commands.json").read_text(encoding="utf-8"))
    assert {entry["file"] for entry in merged} == {"a.cpp", "b.cpp", "c.cpp"}


def test_compile_commands_diagnoses_a_corrupt_fragment(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Regression: a corrupt per-package file used to escape as a traceback."""
    broken = _seed_compile_commands(repo, "pkg_a", "{not json")
    assert run(repo, "dev", "compile-commands") == 1
    err = capsys.readouterr().err
    assert str(broken) in err
    assert "not valid JSON" in err


def test_compile_commands_without_a_build_is_a_clean_error(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(repo, "dev", "compile-commands") == 1
    assert "ardt build" in capsys.readouterr().err
