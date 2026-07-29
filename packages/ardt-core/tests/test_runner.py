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

"""The subprocess wrapper: streaming, tail capture, dry-run, error UX."""

from __future__ import annotations

from pathlib import Path

import pytest

from ardt_core.console import Console
from ardt_core.errors import RunnerError, ToolNotFoundError
from ardt_core.runner import Runner


def test_successful_command(console: Console) -> None:
    runner = Runner(console)
    result = runner.run(["python3", "-c", "print('hi')"])
    assert result.ok
    assert "hi" in result.tail


def test_non_utf8_output_is_replaced_not_fatal(console: Console) -> None:
    """Regression: strict decoding tracebacked on the first locale-mangled
    byte of compiler output; bad bytes must degrade to replacement chars."""
    runner = Runner(console)
    result = runner.run(
        ["python3", "-c", "import sys; sys.stdout.buffer.write(b'ok \\xff bad\\n')"]
    )
    assert result.ok
    assert "ok" in result.tail
    assert "�" in result.tail


def test_nonzero_exit_raises_with_command_and_code(console: Console) -> None:
    runner = Runner(console)
    with pytest.raises(RunnerError) as excinfo:
        runner.run(["python3", "-c", "import sys; sys.exit(3)"])
    assert excinfo.value.returncode == 3


def test_check_false_returns_instead_of_raising(console: Console) -> None:
    runner = Runner(console)
    result = runner.run(["python3", "-c", "import sys; sys.exit(4)"], check=False)
    assert result.ok is False
    assert result.returncode == 4


def test_tail_is_bounded(console: Console) -> None:
    runner = Runner(console)
    result = runner.run(["python3", "-c", "for i in range(200): print(i)"])
    assert len(result.tail.splitlines()) == 40
    assert result.tail.splitlines()[-1] == "199"


def test_dry_run_executes_nothing(console: Console, tmp_path: Path) -> None:
    marker = tmp_path / "made"
    runner = Runner(console, dry_run=True)
    result = runner.run(["touch", str(marker)])
    assert result.skipped is True
    assert result.ok
    assert not marker.exists()


def test_missing_tool_raises_tool_not_found(console: Console) -> None:
    runner = Runner(console)
    with pytest.raises(ToolNotFoundError):
        runner.run(["definitely-not-a-real-binary-xyz"])


def test_require_missing_tool(console: Console) -> None:
    runner = Runner(console)
    with pytest.raises(ToolNotFoundError):
        runner.require("definitely-not-a-real-binary-xyz")


def test_require_under_dry_run_tolerates_absence(console: Console) -> None:
    runner = Runner(console, dry_run=True)
    assert runner.require("definitely-not-a-real-binary-xyz") == "definitely-not-a-real-binary-xyz"


def test_require_finds_real_tool(console: Console) -> None:
    runner = Runner(console)
    assert runner.require("python3").endswith("python3")


def test_extra_env_reaches_the_child(console: Console) -> None:
    runner = Runner(console)
    result = runner.run(
        ["python3", "-c", "import os; print(os.environ['RDT_MARKER'])"],
        extra_env={"RDT_MARKER": "present"},
    )
    assert "present" in result.tail
