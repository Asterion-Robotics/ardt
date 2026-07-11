"""Git fact collection against real repositories."""

from __future__ import annotations

from pathlib import Path

from ardt_core import git as git_module
from ardt_core.testing import git


def test_outside_a_repo_everything_degrades(tmp_path: Path) -> None:
    info = git_module.collect(tmp_path)
    assert info.is_repo is False
    assert info.sha is None
    assert info.is_tag is False


def test_fresh_repo(repo: Path) -> None:
    info = git_module.collect(repo)
    assert info.is_repo is True
    assert info.root == repo.resolve()
    assert info.branch == "main"
    assert info.sha is not None
    assert info.short_sha == info.sha[:7]
    assert info.tag is None
    assert info.last_tag is None
    assert info.commits_since_tag == 1
    assert info.dirty is False


def test_tagged_head(repo: Path) -> None:
    git("tag", "v1.4.0", cwd=repo)
    info = git_module.collect(repo)
    assert info.tag == "v1.4.0"
    assert info.last_tag == "v1.4.0"
    assert info.is_tag is True
    assert info.commits_since_tag == 0


def test_commits_past_a_tag(repo: Path) -> None:
    git("tag", "v1.4.0", cwd=repo)
    (repo / "a.txt").write_text("a\n")
    git("add", "a.txt", cwd=repo)
    git("commit", "-qm", "second", cwd=repo)
    info = git_module.collect(repo)
    assert info.tag is None
    assert info.last_tag == "v1.4.0"
    assert info.commits_since_tag == 1


def test_dirty_tree_ignores_untracked_files(repo: Path) -> None:
    (repo / "untracked.txt").write_text("scratch\n")
    assert git_module.collect(repo).dirty is False

    (repo / "README.md").write_text("changed\n")
    assert git_module.collect(repo).dirty is True


def test_detached_head_has_no_branch(repo: Path) -> None:
    git("checkout", "-q", "--detach", "HEAD", cwd=repo)
    assert git_module.collect(repo).branch is None


def test_repo_with_no_commits(tmp_path: Path) -> None:
    root = tmp_path / "empty"
    root.mkdir()
    git("init", "-q", cwd=root)
    info = git_module.collect(root)
    assert info.is_repo is True
    assert info.sha is None


def test_missing_git_binary_is_not_fatal(monkeypatch, tmp_path: Path) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("git not found")

    monkeypatch.setattr(git_module.subprocess, "run", boom)
    assert git_module.collect(tmp_path).is_repo is False
