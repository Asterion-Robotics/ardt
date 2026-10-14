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

"""Shared pipeline helpers.

Plugin pipelines build on these instead of hand-writing bake entries, so the
conventions (image names, cache references, how credentials reach a build,
the digest records a split publish leaves) live in one place.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from ardt_core.context import Context
from ardt_core.errors import ArdtError

SOURCE_EXCLUDES = (
    ".git",
    "build",
    "install",
    "log",
    ".venv",
    "__pycache__",
    "pipeline-reports",
    "public",
)
"""Never ship the workspace's derived state into a build context."""

DIGESTS_DIR = "pipeline-reports/digests"
"""Where a per-platform publish records what it pushed, one JSON file per
platform, for ``ardt pipe merge``."""


def _path_from_remote(url: str) -> str | None:
    """``group/subgroup/project`` from a git remote URL, or ``None``.

    Handles ``https://host/g/p.git``, ``ssh://git@host:5022/g/p.git`` and the
    scp-like ``git@host:g/p.git``. A path-only remote (no host) yields None.
    """
    if "://" in url:
        path = urlsplit(url).path
    else:
        _, colon, path = url.partition(":")
        if not colon:
            return None
    path = path.strip("/").removesuffix(".git")
    return path or None


def project_path(ctx: Context) -> str | None:
    """The registry namespace of this project: CI's project path, else the git remote's."""
    if ctx.ci.project_path is not None:
        return ctx.ci.project_path
    if ctx.git.remote_url is not None:
        return _path_from_remote(ctx.git.remote_url)
    return None


def image_repository(ctx: Context, name: str | None = None) -> str:
    """``<registry>/<group>/<project>[/<name>]`` — the image name without its tag.

    The name is identical wherever it is computed (the parity rule): the
    project path comes from CI (``$CI_PROJECT_PATH`` / ``GITHUB_REPOSITORY``),
    else ``project_path:`` in ``~/.config/ardt/credentials.yaml``, else the git
    ``origin`` remote. GitLab's registry accepts nothing outside that
    namespace, so there is deliberately no flat fallback; ``name`` appends a
    sub-image. Under ``--dry-run`` an unresolvable path becomes a placeholder
    so the plan still renders.
    """
    if ctx.ci.registry is None:
        raise ArdtError(
            "no registry configured",
            hint="CI provides one; locally set `registry:` in ~/.config/ardt/credentials.yaml",
        )
    path = project_path(ctx)
    if path is None:
        if ctx.dry_run:
            path = "<project-path>"
        else:
            raise ArdtError(
                "cannot determine the registry project path",
                hint="CI provides it; locally set `project_path:` in "
                "~/.config/ardt/credentials.yaml, or add a git `origin` remote",
            )
    repository = f"{path}/{name}" if name else path
    # Registry repository paths must be lowercase (GitLab lowercases
    # CI_REGISTRY_IMAGE; ghcr rejects uppercase).
    return f"{ctx.ci.registry}/{repository.lower()}"


def image_ref(ctx: Context, name: str | None = None) -> str:
    """``<registry>/<group>/<project>[/<name>]:<version>`` — the one image name."""
    return f"{image_repository(ctx, name)}:{image_tag(ctx.version)}"


def cache_ref(ctx: Context, name: str | None, target: str) -> str | None:
    """The registry reference of a target's layer cache, or None when the
    project has no registry to speak of (a local run with no credentials).

    One ``cache`` sub-image per project, one tag per target: the cache of a
    stage is shared by every branch and every runner, and survives any daemon.
    """
    try:
        repository = image_repository(ctx, "cache")
    except ArdtError:
        return None
    if "<project-path>" in repository:
        return None
    suffix = name or ""
    tag = _slug(f"{suffix}-{target}" if suffix else target)
    return f"{repository}:{tag}"


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", text).strip("-")


def platform_slug(platform: str) -> str:
    """``linux/arm64`` -> ``linux-arm64``: a platform as a tag or file name."""
    return _slug(platform)


def load_names(ctx: Context) -> list[str]:
    """The local tags of a ``--load`` image.

    ``<project>:<X.Y.Z>-dev`` for the release being developed — a *moving*
    tag, unlike the registry's immutable ones: each load overwrites it, so the
    daemon holds one dev image per release line whose stale predecessors
    dangle for ``docker image prune``, instead of one tag per commit piling
    up. A release load (exact tag, clean tree) additionally gets the pinned
    ``<project>:<version>``.
    """
    project = ctx.project.lower()
    names = [f"{project}:{dev_tag(ctx.version)}"]
    if ctx.is_release:
        names.append(f"{project}:{image_tag(ctx.version)}")
    return names


def dev_tag(version: str) -> str:
    """``0.1.1.dev3+g…`` -> ``0.1.1-dev``: the release being developed, as a tag."""
    base = version.split("+")[0].partition(".dev")[0]
    return f"{base}-dev"


def image_tag(version: str) -> str:
    """The version as a pushable image tag.

    PEP 440 allows ``+`` in local versions (``1.4.0.dev3+g0a1b2c3``, the
    off-tag default) but the OCI tag grammar
    (``[a-zA-Z0-9_][a-zA-Z0-9._-]{0,127}``) does not, so every registry
    rejects the raw version. ``-`` is the conventional stand-in.
    """
    return version.replace("+", "-")


GIT_TOKEN_SECRET = "git_token"
"""BuildKit secret id for the git token, the contract between
:func:`git_credentials` and any recipe cloning private repos. The escape hatch
passes the same id the existing repo CI already uses:
``docker build --secret id=git_token,env=CI_JOB_TOKEN``."""

GIT_TOKEN_ENV = "ARDT_GIT_TOKEN"
"""The environment variable the secret is read from, set for the bake command
only (``secret = ["id=git_token,env=ARDT_GIT_TOKEN"]``): the token lands in
no file and on no command line."""


@dataclass(frozen=True)
class Credentials:
    """What a build that clones private repos gets: bake ``secret`` and
    ``ssh`` entries, and the environment the bake command needs for them."""

    secret: list[str] = field(default_factory=list[str])
    ssh: list[str] = field(default_factory=list[str])
    env: dict[str, str] = field(default_factory=dict[str, str])


def git_credentials(ctx: Context, *, host: str) -> Credentials:
    """Credentials for a build that clones private repos from ``host``.

    Domain-agnostic: the job token travels as the BuildKit secret
    :data:`GIT_TOKEN_SECRET` (read from the environment of the bake command,
    never a layer), a local ssh agent as a forwarded socket; the recipe's
    runtime branching picks whichever arrived. Raises when neither exists —
    failing fast beats a mid-build clone error.
    """
    secret: list[str] = []
    ssh: list[str] = []
    env: dict[str, str] = {}
    if ctx.ci.job_token is not None:
        secret.append(f"id={GIT_TOKEN_SECRET},env={GIT_TOKEN_ENV}")
        env[GIT_TOKEN_ENV] = ctx.ci.job_token
    if ctx.ci.ssh_auth_sock is not None and Path(ctx.ci.ssh_auth_sock).is_socket():
        ssh.append(f"default={ctx.ci.ssh_auth_sock}")
    if not secret and not ssh:
        raise ArdtError(
            f"no git credentials available for `{host}`",
            hint="CI provides the job token; locally run an ssh agent or set "
            "`job_token:` (a PAT) in ~/.config/ardt/credentials.yaml",
        )
    return Credentials(secret=secret, ssh=ssh, env=env)


def write_digest(ctx: Context, *, repository: str, platform: str, digest: str) -> Path:
    """Record what a per-platform publish pushed, for ``ardt pipe merge``."""
    directory = ctx.project_root / DIGESTS_DIR
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{platform_slug(platform)}.json"
    path.write_text(
        json.dumps({"repository": repository, "platform": platform, "digest": digest}) + "\n",
        encoding="utf-8",
    )
    return path


def read_digests(ctx: Context) -> list[dict[str, str]]:
    """Every digest record of the project, sorted by platform."""
    directory = ctx.project_root / DIGESTS_DIR
    records: list[dict[str, str]] = []
    for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        missing = {"repository", "platform", "digest"} - set(loaded)
        if missing:
            raise ArdtError(f"{path} lacks {', '.join(sorted(missing))}")
        records.append({key: str(loaded[key]) for key in ("repository", "platform", "digest")})
    if not records:
        raise ArdtError(
            f"no digest records under {DIGESTS_DIR}/",
            hint="a per-platform `ardt pipe run <pipeline> --publish --arg platforms=<one>` "
            "writes one; collect them as artifacts before merging",
        )
    return records
