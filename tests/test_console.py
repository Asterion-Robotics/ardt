"""Console: stderr discipline, plain-text fallback, CI section markers."""

from __future__ import annotations

import io

from ardt_core.ci import CIInfo, Platform
from ardt_core.console import Console, _section_key


def make(platform: Platform) -> tuple[Console, io.StringIO]:
    stream = io.StringIO()
    console = Console(
        CIInfo(platform=platform, is_ci=platform is not Platform.LOCAL), stream=stream
    )
    return console, stream


def test_plain_when_not_a_tty() -> None:
    console, _ = make(Platform.LOCAL)
    assert console.plain is True


def test_levels_render_without_markup_when_plain() -> None:
    console, stream = make(Platform.LOCAL)
    console.info("hi")
    console.success("done")
    console.warn("careful")
    console.error("broke", hint="try this")
    text = stream.getvalue()
    assert "hi" in text
    assert "ok done" in text
    assert "warning: careful" in text
    assert "error: broke" in text
    assert "try this" in text
    assert "[bold" not in text  # no rich markup leaked


def test_detail_hidden_without_verbose() -> None:
    console, stream = make(Platform.LOCAL)
    console.detail("noise")
    assert stream.getvalue() == ""


def test_detail_shown_with_verbose() -> None:
    stream = io.StringIO()
    console = Console(CIInfo(platform=Platform.LOCAL, is_ci=False), verbose=1, stream=stream)
    console.detail("shown")
    assert "shown" in stream.getvalue()


def test_quiet_suppresses_output() -> None:
    stream = io.StringIO()
    console = Console(CIInfo(platform=Platform.LOCAL, is_ci=False), quiet=True, stream=stream)
    console.info("silent")
    console.passthrough("also silent")
    assert stream.getvalue() == ""


def test_gitlab_section_markers() -> None:
    console, stream = make(Platform.GITLAB)
    with console.section("Build step"):
        console.info("working")
    text = stream.getvalue()
    assert "section_start" in text
    assert "section_end" in text
    assert "working" in text


def test_github_section_markers() -> None:
    console, stream = make(Platform.GITHUB)
    with console.section("Build step"):
        pass
    text = stream.getvalue()
    assert "::group::Build step" in text
    assert "::endgroup::" in text


def test_local_section_is_a_step() -> None:
    console, stream = make(Platform.LOCAL)
    with console.section("Build step"):
        pass
    assert "Build step" in stream.getvalue()


def test_section_key_sanitizes() -> None:
    assert _section_key("Build Step: 1/2") == "build_step__1_2"
