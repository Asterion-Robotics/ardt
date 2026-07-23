"""The doc task: config, doxyfile render, CLI wiring, and one real sphinx build."""

from __future__ import annotations

import contextlib
import io
from pathlib import Path

from ardt_core.config import ArdtConfig
from ardt_tasks_doc import doxygen
from ardt_tasks_doc.config import doc_config

CONF = "from ardt_tasks_doc.preset import *  # noqa: F403\n\nproject = 'demo'\n"


def run(args: list[str], cwd: Path) -> tuple[int, str, str]:
    from ardt_core.cli import main

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(["-C", str(cwd), *args])
    return code, out.getvalue(), err.getvalue()


class TestConfig:
    def test_defaults(self) -> None:
        cfg = doc_config(ArdtConfig())
        assert cfg.source_dir == "doc"
        assert cfg.doxygen == "auto"
        assert cfg.strict is True

    def test_from_yaml_section(self) -> None:
        cfg = doc_config(
            ArdtConfig.model_validate(
                {"tasks": {"doc": {"source_dir": "docs", "doxygen": False, "strict": False}}}
            )
        )
        assert cfg.source_dir == "docs"
        assert cfg.doxygen is False
        assert cfg.strict is False


class TestDoxyfile:
    def test_render_defaults_to_whole_repo(self, tmp_path: Path) -> None:
        text = doxygen.render_doxyfile(
            project="demo", root=tmp_path, inputs=[], output=tmp_path / "out"
        )
        assert f"INPUT                  = {tmp_path}" in text
        assert "GENERATE_XML           = YES" in text
        assert "GENERATE_HTML          = NO" in text

    def test_render_with_explicit_inputs(self, tmp_path: Path) -> None:
        text = doxygen.render_doxyfile(
            project="demo", root=tmp_path, inputs=["a", "b"], output=tmp_path / "out"
        )
        assert f"INPUT                  = {tmp_path / 'a'} {tmp_path / 'b'}" in text


class TestCli:
    def test_missing_doc_dir_is_a_clean_error(self, repo: Path) -> None:
        code, _, err = run(["doc", "build"], repo)
        assert code == 1
        assert "doc source directory" in err

    def test_missing_conf_is_a_clean_error(self, repo: Path) -> None:
        (repo / "doc").mkdir()
        code, _, err = run(["doc", "build"], repo)
        assert code == 1
        assert "conf.py" in err

    def test_dry_run_prints_the_plan(self, repo: Path) -> None:
        (repo / "doc").mkdir()
        (repo / "doc" / "conf.py").write_text(CONF)
        (repo / "doc" / "index.rst").write_text("Demo\n====\n")
        code, _, err = run(["doc", "build", "--dry-run"], repo)
        assert code == 0
        assert "[dry-run]" in err
        assert "-m sphinx" in err

    def test_dry_run_plans_doxygen_for_cpp_repos(self, repo: Path) -> None:
        (repo / "doc").mkdir()
        (repo / "doc" / "conf.py").write_text(CONF)
        (repo / "src").mkdir()
        (repo / "src" / "lib.hpp").write_text("struct S {};\n")
        code, _, err = run(["doc", "build", "--dry-run"], repo)
        assert code == 0
        assert "doxygen" in err


class TestRealSphinxBuild:
    """End to end against the sphinx in this venv — no doxygen needed."""

    def test_html_build_with_preset_and_interfaces(self, repo: Path) -> None:
        (repo / "msgs_pkg" / "msg").mkdir(parents=True)
        (repo / "msgs_pkg" / "msg" / "Ping.msg").write_text("# A ping.\n\nint64 stamp\n")
        doc = repo / "doc"
        doc.mkdir()
        (doc / "conf.py").write_text(CONF)
        (doc / "index.rst").write_text(
            "Demo\n====\n\n.. ros2-interfaces:: msgs_pkg\n\n.. mermaid::\n\n"
            "   graph LR\n      a --> b\n"
        )

        code, out, err = run(["doc", "build", "--json"], repo)
        assert code == 0, err
        index = repo / "build" / "doc" / "html" / "index.html"
        assert index.is_file()
        html = index.read_text(encoding="utf-8")
        assert "Ping" in html and "stamp" in html
        assert '"html_dir": "build/doc/html"' in out
