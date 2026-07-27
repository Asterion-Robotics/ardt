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

"""Subprocess wrapper used by every task.

Streams the child's output line by line (so a 40-minute colcon build is not a
40-minute silence), keeps the last N lines so a failure can be diagnosed in one
line instead of a traceback, and honors ``--dry-run`` by printing the command it
would have run.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from . import env
from .console import Console
from .errors import RunnerError, ToolNotFoundError

TAIL_LINES = 40


@dataclass(frozen=True)
class Result:
    """Outcome of a command."""

    command: list[str]
    returncode: int
    tail: str
    """The last :data:`TAIL_LINES` lines of combined output."""
    skipped: bool = False
    """True when ``--dry-run`` meant the command never ran."""

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class Runner:
    """Runs commands. One instance per invocation, carried on the Context."""

    def __init__(
        self,
        console: Console,
        *,
        dry_run: bool = False,
        cwd: Path | None = None,
    ) -> None:
        self.console = console
        self.dry_run = dry_run
        self.cwd = cwd or Path.cwd()

    def which(self, tool: str) -> str | None:
        """Locate an external tool on PATH."""
        return shutil.which(tool)

    def require(self, tool: str, *, hint: str | None = None) -> str:
        """Locate a tool, or fail with a one-line diagnosis.

        Under ``--dry-run`` the tool need not exist: printing the plan must work on
        a machine that could not possibly execute it.
        """
        found = self.which(tool)
        if found is None:
            if self.dry_run:
                return tool
            raise ToolNotFoundError(f"{tool} is not on PATH", hint=hint)
        return found

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path | None = None,
        check: bool = True,
        extra_env: Mapping[str, str] | None = None,
        quiet: bool = False,
    ) -> Result:
        """Run ``command``, streaming its output.

        Raises :class:`RunnerError` on a non-zero exit unless ``check`` is False.
        Under ``--dry-run`` nothing runs and a successful, skipped result comes back.
        """
        argv = list(command)
        workdir = cwd or self.cwd
        pretty = shlex.join(argv)

        if self.dry_run:
            self.console.info(f"[dry-run] {pretty}")
            return Result(command=argv, returncode=0, tail="", skipped=True)

        self.console.detail(f"$ {pretty}")

        child_env = env.base_environ()
        if extra_env:
            child_env.update(extra_env)

        try:
            proc = subprocess.Popen(
                argv,
                cwd=workdir,
                env=child_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError as exc:
            raise ToolNotFoundError(f"{argv[0]} is not on PATH") from exc
        except OSError as exc:
            raise RunnerError(f"cannot run {argv[0]}: {exc}", command=argv, returncode=1) from exc

        tail: deque[str] = deque(maxlen=TAIL_LINES)
        assert proc.stdout is not None
        with proc.stdout as stream:
            for raw in stream:
                line = raw.rstrip("\n")
                tail.append(line)
                if not quiet:
                    self.console.passthrough(line)
        returncode = proc.wait()

        result = Result(command=argv, returncode=returncode, tail="\n".join(tail))
        if check and not result.ok:
            raise RunnerError(
                f"`{pretty}` exited {returncode}",
                command=argv,
                returncode=returncode,
                tail=result.tail,
                hint="see the output above" if not quiet else None,
            )
        return result
