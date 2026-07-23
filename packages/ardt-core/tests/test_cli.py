"""CLI behavior: the JSON envelope, dry-run/json injection, error UX."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from ardt_core import cli as cli_module
from ardt_core.cli import cli, main


def run(args: list[str], cwd: Path) -> tuple[int, str, str]:
    """Invoke `main` in-process, capturing stdout/stderr separately."""
    import contextlib
    import io

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main([*("-C", str(cwd)), *args])
    return code, out.getvalue(), err.getvalue()


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


def test_plugins_lists_the_real_plugin(repo: Path) -> None:
    code, out, _ = run(["plugins", "--json"], repo)
    assert code == 0
    names = {p["name"] for p in json.loads(out)["data"]["plugins"]}
    assert "ardt-ros-tasks" in names


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


def test_global_options_injected_into_plugin_commands(repo: Path) -> None:
    result = CliRunner().invoke(cli, ["build", "--help"])
    assert result.exit_code == 0
    assert "--dry-run" in result.output
    assert "--json" in result.output


def test_dry_run_build_prints_plan_and_runs_nothing(repo: Path) -> None:
    (repo / "ardt.yaml").write_text("project:\n  name: proj\n")
    code, _out, err = run(["build", "--dry-run"], repo)
    assert code == 0
    assert "colcon build" in err
    assert not (repo / "build").exists()


def test_dry_run_before_subcommand_also_works(repo: Path) -> None:
    code, _, err = run(["--dry-run", "build"], repo)
    assert code == 0
    assert "colcon build" in err


def test_plugins_human_output_names_the_plugin(repo: Path) -> None:
    code, _out, err = run(["plugins"], repo)
    assert code == 0
    assert "ardt-ros-tasks" in err
    assert "commands:" in err


def test_test_task_dry_run_plans_results_summary(repo: Path) -> None:
    code, _, err = run(["test", "--dry-run"], repo)
    assert code == 0
    assert "colcon test-result" in err


def test_keyboard_interrupt_exits_130(repo: Path, monkeypatch) -> None:
    def boom(**_kwargs: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli_module.cli, "main", boom)
    assert cli_module.main(["info"]) == 130
