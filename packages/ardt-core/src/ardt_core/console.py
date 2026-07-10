"""Terminal output.

Two invariants:

1. **Everything goes to stderr.** stdout belongs to the ``--json`` envelope and to
   nothing else, so any command can be piped into ``jq`` without a ``2>/dev/null``.
2. **CI logs stay grep-able.** Rich markup and spinners are for TTYs; under CI the
   output degrades to plain lines, wrapped in the platform's collapsible-section
   markers (GitLab's ``section_start``, GitHub's ``::group::``).
"""

from __future__ import annotations

import sys
import time
from collections.abc import Generator
from contextlib import contextmanager
from typing import TextIO

from rich.console import Console as RichConsole

from .ci import CIInfo, Platform


class Console:
    """The console. Built once by the Context, passed everywhere."""

    def __init__(
        self,
        ci: CIInfo | None = None,
        *,
        verbose: int = 0,
        quiet: bool = False,
        stream: TextIO | None = None,
    ) -> None:
        self._stream = stream if stream is not None else sys.stderr
        self._ci = ci
        self.verbose = verbose
        self.quiet = quiet
        self._plain = not self._stream.isatty()
        self._rich = RichConsole(file=self._stream, stderr=True, no_color=self._plain)
        self._section_depth = 0

    @property
    def plain(self) -> bool:
        """True when output must stay free of control sequences."""
        return self._plain

    def _write(self, markup: str, plain: str) -> None:
        if self.quiet:
            return
        if self._plain:
            print(plain, file=self._stream, flush=True)
        else:
            self._rich.print(markup, highlight=False)

    def info(self, message: str) -> None:
        self._write(message, message)

    def step(self, message: str) -> None:
        """A step being taken — the verb-level narration of a task."""
        self._write(f"[bold cyan]::[/] {message}", f":: {message}")

    def detail(self, message: str) -> None:
        """Shown only with ``-v``."""
        if self.verbose > 0:
            self._write(f"[dim]{message}[/]", message)

    def success(self, message: str) -> None:
        self._write(f"[bold green]ok[/] {message}", f"ok {message}")

    def warn(self, message: str) -> None:
        self._write(f"[bold yellow]warning[/] {message}", f"warning: {message}")

    def error(self, message: str, *, hint: str | None = None) -> None:
        self._write(f"[bold red]error[/] {message}", f"error: {message}")
        if hint:
            self._write(f"       [dim]{hint}[/]", f"       {hint}")

    def passthrough(self, line: str) -> None:
        """A line of a subprocess's output, forwarded verbatim."""
        if not self.quiet:
            print(line, file=self._stream, flush=True)

    @contextmanager
    def section(self, title: str) -> Generator[None]:
        """Group output under a collapsible header where the platform supports it."""
        key = _section_key(title)
        started = time.time()
        self._open_section(key, title, started)
        self._section_depth += 1
        try:
            yield
        finally:
            self._section_depth -= 1
            self._close_section(key, started)

    def _open_section(self, key: str, title: str, started: float) -> None:
        if self.quiet:
            return
        platform = self._ci.platform if self._ci else Platform.LOCAL
        if platform is Platform.GITLAB:
            print(
                f"\033[0Ksection_start:{int(started)}:{key}\r\033[0K{title}",
                file=self._stream,
                flush=True,
            )
        elif platform is Platform.GITHUB:
            print(f"::group::{title}", file=self._stream, flush=True)
        else:
            self.step(title)

    def _close_section(self, key: str, started: float) -> None:
        if self.quiet:
            return
        platform = self._ci.platform if self._ci else Platform.LOCAL
        if platform is Platform.GITLAB:
            print(
                f"\033[0Ksection_end:{int(time.time())}:{key}\r\033[0K",
                file=self._stream,
                flush=True,
            )
        elif platform is Platform.GITHUB:
            print("::endgroup::", file=self._stream, flush=True)


def _section_key(title: str) -> str:
    """GitLab section keys accept only ``[a-zA-Z0-9_.-]``."""
    return "".join(c if c.isalnum() or c in "_.-" else "_" for c in title.lower())
