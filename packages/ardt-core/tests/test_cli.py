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

"""CLI behavior: the JSON envelope, dry-run/json injection, error UX."""

from __future__ import annotations

import json
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from ardt_core import cli as cli_module
from ardt_core.cli import cli
from ardt_core.context import Context
from ardt_core.plugins import ARDT_PLUGIN_API, Plugin, Registry
from ardt_core.testing import run_cli


@pytest.fixture
def fake_plugin(monkeypatch: pytest.MonkeyPatch) -> Plugin:
    """A minimal in-memory plugin, so core's suite needs no plugin installed."""

    @click.command()
    @cli_module.pass_ardt
    def greet(ctx: Context) -> None:
        """Say hello via the runner."""
        ctx.runner.run(["echo", "greetings"])

    plugin = Plugin(
        name="acme-plug",
        version="9.9.9",
        api=ARDT_PLUGIN_API,
        module="acme_plug",
        section="acme",
        commands={"greet": greet},
    )
    registry = Registry(plugins=[plugin], problems=[])
    monkeypatch.setattr(cli_module, "_registry", lambda: registry)
    return plugin


run = run_cli


def test_help_does_not_touch_the_repo() -> None:
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "build, test and ship" in result.output


def test_version_flag() -> None:
    result = CliRunner().invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert cli_module.__version__ in result.output


def test_info_human_output(repo: Path) -> None:
    code, out, err = run(["info"], repo)
    assert code == 0
    assert "project" in err
    assert out == ""  # nothing on stdout without --json


def test_info_json_envelope(repo: Path) -> None:
    code, out, _ = run(["info", "--json"], repo)
    assert code == 0
    envelope = json.loads(out)
    assert envelope["ok"] is True
    assert envelope["command"] == "ardt info"
    assert envelope["data"]["project"] == "proj"
    assert envelope["error"] is None


def test_json_stdout_is_pure(repo: Path) -> None:
    """stdout must be exactly one JSON document, so `| jq` works."""
    _, out, _ = run(["info", "--json"], repo)
    json.loads(out)  # raises if anything else leaked onto stdout


def test_plugins_lists_the_loaded_plugin(repo: Path, fake_plugin: Plugin) -> None:
    code, out, _ = run(["plugins", "--json"], repo)
    assert code == 0
    names = {p["name"] for p in json.loads(out)["data"]["plugins"]}
    assert names == {"acme-plug"}


def test_unknown_section_is_one_line_error_not_traceback(repo: Path) -> None:
    (repo / "ardt.yaml").write_text("wibble: {}\n")
    code, out, err = run(["info"], repo)
    assert code == 1
    assert "error:" in err
    assert "Traceback" not in err
    assert out == ""


def test_error_envelope_on_json(repo: Path) -> None:
    (repo / "ardt.yaml").write_text("wibble: {}\n")
    code, out, _ = run(["info", "--json"], repo)
    assert code == 1
    envelope = json.loads(out)
    assert envelope["ok"] is False
    assert "unknown config section" in envelope["error"]["message"]


def test_global_options_injected_into_plugin_commands(fake_plugin: Plugin) -> None:
    result = CliRunner().invoke(cli, ["greet", "--help"])
    assert result.exit_code == 0
    assert "--dry-run" in result.output
    assert "--json" in result.output


def test_dry_run_plugin_command_prints_plan_and_runs_nothing(
    repo: Path, fake_plugin: Plugin
) -> None:
    code, _out, err = run(["greet", "--dry-run"], repo)
    assert code == 0
    assert "[dry-run]" in err
    assert "echo greetings" in err


def test_dry_run_before_subcommand_also_works(repo: Path, fake_plugin: Plugin) -> None:
    code, _, err = run(["--dry-run", "greet"], repo)
    assert code == 0
    assert "echo greetings" in err


def test_plugins_human_output_names_the_plugin(repo: Path, fake_plugin: Plugin) -> None:
    code, _out, err = run(["plugins"], repo)
    assert code == 0
    assert "acme-plug" in err
    assert "commands:" in err


def test_keyboard_interrupt_exits_130(repo: Path, monkeypatch) -> None:
    def boom(**_kwargs: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli_module.cli, "main", boom)
    assert cli_module.main(["info"]) == 130
