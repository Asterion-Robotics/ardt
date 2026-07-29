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

"""Shared pytest fixtures for ardt packages and third-party plugins.

Import into a ``conftest.py``::

    from ardt_core.testing import console, isolate_environment, repo  # noqa: F401

``isolate_environment`` is autouse once imported: it strips every CI variable
the :mod:`ardt_core.ci` table reads, so a suite that passes on a laptop cannot
start failing the moment it runs inside GitLab/GitHub.
"""

from __future__ import annotations

import contextlib
import io
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from ardt_core.ci import CIInfo, Platform
from ardt_core.console import Console
from ardt_core.context import Context
from ardt_core.plugins import Registry

__all__ = [
    "build_context",
    "console",
    "console_output",
    "git",
    "isolate_environment",
    "repo",
    "run_cli",
]

_CI_VARIABLES = (
    "GITLAB_CI",
    "GITHUB_ACTIONS",
    "CI_COMMIT_TAG",
    "CI_COMMIT_BRANCH",
    "CI_DEFAULT_BRANCH",
    "CI_REGISTRY",
    "CI_REGISTRY_USER",
    "CI_REGISTRY_PASSWORD",
    "CI_JOB_TOKEN",
    "CI_PROJECT_PATH",
    "GITHUB_REF_TYPE",
    "GITHUB_REF_NAME",
    "GITHUB_BASE_REF",
    "GITHUB_ACTOR",
    "GITHUB_TOKEN",
    "GITHUB_REPOSITORY",
    "SSH_AUTH_SOCK",  # not a CI variable, but ctx.ci reads it locally
)


@pytest.fixture(autouse=True)
def isolate_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Never let the developer's (or CI's) real environment leak into a test."""
    for name in _CI_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    # Point HOME at a scratch dir so `~/.config/ardt/credentials.yaml` is absent.
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("USERPROFILE", raising=False)


@pytest.fixture
def console() -> Console:
    """A local, non-CI console writing to a plain stream."""
    return Console(CIInfo(platform=Platform.LOCAL, is_ci=False))


def build_context(root: Path, **kwargs: object) -> Context:
    """A test Context: empty plugin registry, console captured in memory.

    The console writes plainly to a ``StringIO`` (a non-TTY stream is plain by
    construction); read it back with :func:`console_output`. Keyword arguments
    pass through to :meth:`Context.build` (``dry_run=True`` is the usual one).
    """
    captured = Console(
        CIInfo(platform=Platform.LOCAL, is_ci=False),
        stream=io.StringIO(),
    )
    return Context.build(
        cwd=root,
        registry=Registry(plugins=[], problems=[]),
        console=captured,
        **kwargs,  # type: ignore[arg-type]
    )


def console_output(ctx: Context) -> str:
    """Everything the context's console wrote (a :func:`build_context` context)."""
    stream = ctx.console.stream
    assert isinstance(stream, io.StringIO), "console_output needs a build_context() context"
    return stream.getvalue()


def run_cli(args: Sequence[str], cwd: Path) -> tuple[int, str, str]:
    """Invoke the real CLI in-process: ``(exit_code, stdout, stderr)``.

    Goes through :func:`ardt_core.cli.main`, so plugin discovery, option
    injection and the JSON envelope all behave exactly as in production.
    """
    from ardt_core.cli import main  # deferred: importing testing must stay light

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(["-C", str(cwd), *args])
    return code, out.getvalue(), err.getvalue()


def git(*args: str, cwd: Path) -> None:
    """Run a git command in a test repository."""
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A git repo with one commit, on branch ``main``."""
    root = tmp_path / "proj"
    root.mkdir()
    git("init", "-q", "-b", "main", cwd=root)
    git("config", "user.email", "t@example.com", cwd=root)
    git("config", "user.name", "T", cwd=root)
    git("config", "commit.gpgsign", "false", cwd=root)
    (root / "README.md").write_text("hello\n")
    git("add", "README.md", cwd=root)
    git("commit", "-qm", "initial", cwd=root)
    return root
