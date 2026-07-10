"""Shared fixtures. Everything here is `unit`: no docker, no network, no engine."""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from ardt_core.ci import CIInfo, Platform
from ardt_core.console import Console


@pytest.fixture(autouse=True)
def _isolate_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Never let the developer's (or CI's) real environment leak into a test.

    Without this, the whole suite passes locally and fails the moment it runs on
    GitLab, because `ci.detect()` suddenly sees `GITLAB_CI`.
    """
    for name in (
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
    ):
        monkeypatch.delenv(name, raising=False)
    # Point HOME at a scratch dir so `~/.config/ardt/credentials.yaml` is absent.
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("USERPROFILE", raising=False)


@pytest.fixture
def console() -> Console:
    return Console(CIInfo(platform=Platform.LOCAL, is_ci=False))


def git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Iterator[Path]:
    """A git repo with one commit, on branch `main`."""
    root = tmp_path / "proj"
    root.mkdir()
    git("init", "-q", "-b", "main", cwd=root)
    git("config", "user.email", "t@example.com", cwd=root)
    git("config", "user.name", "T", cwd=root)
    git("config", "commit.gpgsign", "false", cwd=root)
    (root / "README.md").write_text("hello\n")
    git("add", "README.md", cwd=root)
    git("commit", "-qm", "initial", cwd=root)
    yield root
