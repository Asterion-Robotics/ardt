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

from pydantic import BaseModel, ConfigDict, Field

from ardt_core.context import Context
from ardt_core.errors import ArdtError

from .buildx import Target

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


# ---- what every image-producing pipeline shares: the recipe knows its stages,
# this knows how a stage becomes a gate, an image, a cached layer or a record ----


class ImagesConfig(BaseModel):
    """``pipelines.images:`` — the knobs of every image-producing pipeline."""

    model_config = ConfigDict(extra="forbid")

    registry_cache: bool = True
    """Keep the layer cache of every stage in the registry, as the ``cache``
    sub-image of the project (one tag per stage): CI runs write it, every run
    that can reach the registry reads it. Off, the cache is the builder's own
    only (a registry that should hold nothing but images, or none at all)."""
    compression: str = "gzip"
    """Layer compression of a published image: ``gzip`` (every consumer reads
    it) or ``zstd`` (smaller and faster to unpack, needs a consumer on
    containerd 1.6 or Docker 23 and later)."""


class _ImagesSection(BaseModel):
    model_config = ConfigDict(extra="allow")

    images: ImagesConfig = Field(default_factory=ImagesConfig)


def images_config(ctx: Context) -> ImagesConfig:
    return ctx.cfg.section_as("pipelines", _ImagesSection).images


def cache_entries(
    ctx: Context, cfg: ImagesConfig, image: str | None, stage: str
) -> tuple[list[str], list[str]]:
    """``cache-from`` when the project has a registry, ``cache-to`` on CI only,
    nothing when the knob is off: a laptop reads the fleet's cache and never
    writes it."""
    ref = cache_ref(ctx, image, stage) if cfg.registry_cache else None
    if ref is None:
        return [], []
    # ignore-error: a run whose token cannot write the cache (a fork's MR) is
    # not a failed build, it is a build that left no cache behind
    cache_to = [f"type=registry,ref={ref},mode=max,ignore-error=true"] if ctx.ci.is_ci else []
    return [f"type=registry,ref={ref}"], cache_to


def gate_target(
    ctx: Context,
    cfg: ImagesConfig,
    *,
    name: str,
    dockerfile: str,
    stage: str,
    dest: str,
    image: str | None = None,
    args: dict[str, str] | None = None,
    credentials: Credentials | None = None,
    cache_stage: str | None = None,
) -> Target:
    """A stage exported to a local directory: test reports, a docs site.

    ``cache_stage`` names the stage whose cache the export rides on when it is
    not the exported one (a scratch stage of results caches nothing itself)."""
    credentials = credentials or Credentials()
    cache_from, cache_to = cache_entries(ctx, cfg, image, cache_stage or stage)
    return Target(
        name=name,
        dockerfile=dockerfile,
        target=stage,
        args=dict(args or {}),
        output=[f"type=local,dest={dest}"],
        cache_from=cache_from,
        cache_to=cache_to,
        secret=list(credentials.secret),
        ssh=list(credentials.ssh),
    )


def image_output(
    ctx: Context, cfg: ImagesConfig, image: str | None, *, split: bool
) -> tuple[list[str], list[str]]:
    """An image target's ``output`` and ``tags``.

    No ``--publish``: built and kept in the cache only (a broken stage still
    fails the run). ``--publish`` with every configured platform: one pushed
    manifest list under the image name. ``--publish`` on a subset (``split``):
    pushed by digest, no tag, for ``ardt pipe merge``.
    """
    if not ctx.publish:
        return ["type=cacheonly"], []
    compression = f",compression={cfg.compression},oci-mediatypes=true,force-compression=true"
    if split:
        repository = image_repository(ctx, image)
        return [
            f"type=image,push=true,push-by-digest=true,name-canonical=true,name={repository}"
            + compression
        ], []
    return [f"type=image,push=true{compression}"], [image_ref(ctx, image)]


def image_target(
    ctx: Context,
    cfg: ImagesConfig,
    *,
    name: str,
    dockerfile: str,
    stage: str,
    image: str | None,
    platforms: list[str],
    all_platforms: list[str],
    credentials: Credentials | None = None,
    extra_cache_from: list[str] | None = None,
) -> Target:
    """The shipped image for the selected platforms; ``extra_cache_from`` adds
    the caches of the stages it forks from."""
    credentials = credentials or Credentials()
    output, tags = image_output(ctx, cfg, image, split=sorted(platforms) != sorted(all_platforms))
    cache_from, cache_to = cache_entries(ctx, cfg, image, stage)
    return Target(
        name=name,
        dockerfile=dockerfile,
        target=stage,
        platforms=list(platforms),
        output=output,
        tags=tags,
        cache_from=[*(extra_cache_from or []), *cache_from],
        cache_to=cache_to,
        secret=list(credentials.secret),
        ssh=list(credentials.ssh),
    )


def load_target(
    ctx: Context,
    *,
    name: str,
    dockerfile: str,
    stage: str,
    platform: str,
    cache_from: list[str],
    credentials: Credentials | None = None,
) -> Target:
    """The native image into the local daemon (``--load``), tagged
    :func:`load_names`."""
    credentials = credentials or Credentials()
    return Target(
        name=name,
        dockerfile=dockerfile,
        target=stage,
        platforms=[platform],
        output=["type=docker"],
        tags=load_names(ctx),
        cache_from=list(cache_from),
        secret=list(credentials.secret),
        ssh=list(credentials.ssh),
    )


def finish_publish(
    ctx: Context,
    metadata: dict[str, dict[str, object]],
    *,
    target: str,
    image: str | None,
    platforms: list[str],
    all_platforms: list[str],
) -> None:
    """After a ``--publish`` bake: the digest bake reported, recorded for the
    merge when the run built a subset of the platforms, emitted as the tag
    when it built them all."""
    digest = str(metadata.get(target, {}).get("containerimage.digest", ""))
    if sorted(platforms) != sorted(all_platforms):
        repository = image_repository(ctx, image)
        built = ",".join(platforms)
        path = write_digest(ctx, repository=repository, platform=built, digest=digest)
        ctx.console.info(f"recorded {built} as {digest} in {path.relative_to(ctx.project_root)}")
        ctx.emit(image_repository=repository, image_digest=digest, platforms=platforms)
        ctx.console.success(
            f"pushed {repository}@{digest} for {built}; "
            "`ardt pipe merge` creates the tag once every platform's record is in"
        )
        return
    ref = image_ref(ctx, image)
    ctx.emit(image=ref, image_digest=digest)
    ctx.console.success(f"published {ref} @ {digest}")
