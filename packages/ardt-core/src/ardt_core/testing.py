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

import subprocess
from pathlib import Path

import pytest

from ardt_core.ci import CIInfo, Platform
from ardt_core.console import Console

__all__ = ["console", "git", "isolate_environment", "repo"]

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
