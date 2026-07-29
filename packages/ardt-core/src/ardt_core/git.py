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

"""Git facts, collected once per invocation.

Read-only and best-effort: outside a repository (a source tarball, a container
build stage) every field degrades to ``None``/``False`` rather than raising, and
:mod:`ardt_core.version` turns that into an explicit ``0.0.0+unknown``.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GitInfo:
    """Facts about the checkout ardt was invoked in."""

    is_repo: bool
    root: Path | None = None
    branch: str | None = None
    sha: str | None = None
    short_sha: str | None = None
    tag: str | None = None
    """The tag pointing at HEAD exactly, if any."""
    last_tag: str | None = None
    """The most recent tag reachable from HEAD (equals ``tag`` when on a tag)."""
    commits_since_tag: int = 0
    dirty: bool = False
    remote_url: str | None = None
    """URL of the ``origin`` remote, if the repo has one."""

    @property
    def is_tag(self) -> bool:
        return self.tag is not None


def _run(args: list[str], cwd: Path) -> str | None:
    """Run a git command, returning stripped stdout or ``None`` on any failure."""
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def collect(cwd: Path) -> GitInfo:
    """Collect git facts for the repository containing ``cwd``."""
    root = _run(["rev-parse", "--show-toplevel"], cwd)
    if root is None:
        return GitInfo(is_repo=False)

    remote_url = _run(["remote", "get-url", "origin"], cwd)

    sha = _run(["rev-parse", "HEAD"], cwd)
    if sha is None:
        # A repo with no commits yet: a repo for all other purposes.
        return GitInfo(
            is_repo=True,
            root=Path(root),
            branch=_branch(cwd),
            dirty=_dirty(cwd),
            remote_url=remote_url,
        )

    tag = _run(["describe", "--tags", "--exact-match", "HEAD"], cwd)
    last_tag = _run(["describe", "--tags", "--abbrev=0"], cwd)

    commits_since_tag = 0
    if last_tag is not None:
        count = _run(["rev-list", "--count", f"{last_tag}..HEAD"], cwd)
        if count is not None and count.isdigit():
            commits_since_tag = int(count)
    else:
        count = _run(["rev-list", "--count", "HEAD"], cwd)
        if count is not None and count.isdigit():
            commits_since_tag = int(count)

    return GitInfo(
        is_repo=True,
        root=Path(root),
        branch=_branch(cwd),
        sha=sha,
        short_sha=sha[:7],
        tag=tag,
        last_tag=last_tag,
        commits_since_tag=commits_since_tag,
        dirty=_dirty(cwd),
        remote_url=remote_url,
    )


def list_tags(cwd: Path, pattern: str) -> list[str]:
    """Tags matching a glob ``pattern``, newest version first. Empty outside a repo."""
    out = _run(["tag", "--list", pattern, "--sort=-v:refname"], cwd)
    return out.split() if out else []


def ref_exists(cwd: Path, ref: str) -> bool:
    """True when ``ref`` resolves to a commit in the repository containing ``cwd``."""
    return _run(["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], cwd) is not None


def path_exists_at(cwd: Path, ref: str, path: str) -> bool:
    """True when ``path`` exists in the tree of ``ref``."""
    return _run(["cat-file", "-e", f"{ref}:{path}"], cwd) is not None


def is_shallow(cwd: Path) -> bool:
    """True in a shallow clone — CI depth limits hide tags and history."""
    return _run(["rev-parse", "--is-shallow-repository"], cwd) == "true"


def _branch(cwd: Path) -> str | None:
    branch = _run(["rev-parse", "--abbrev-ref", "HEAD"], cwd)
    if branch in (None, "HEAD"):  # detached
        return None
    return branch


def _dirty(cwd: Path) -> bool:
    status = _run(["status", "--porcelain", "--untracked-files=no"], cwd)
    return bool(status)
