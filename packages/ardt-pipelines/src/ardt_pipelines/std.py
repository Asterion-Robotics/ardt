"""Shared pipeline helpers (02 §1/§3/§6).

Plugin pipelines build on these instead of raw Dagger calls where possible, so
most SDK churn lands here and in :mod:`.engine` rather than in every plugin.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from urllib.parse import urlsplit

import dagger

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
"""Never ship the workspace's derived state into a build container."""


def source_dir(dag: dagger.Client, ctx: Context) -> dagger.Directory:
    """The project's source tree, minus derived state."""
    return dag.host().directory(str(ctx.project_root), exclude=list(SOURCE_EXCLUDES))


def cache_volume(dag: dagger.Client, ctx: Context, purpose: str) -> dagger.CacheVolume:
    """Deterministic cache-volume naming: ``<purpose>-<project>`` (02 §1 rule 3)."""
    return dag.cache_volume(f"{purpose}-{ctx.project}")


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


def image_ref(ctx: Context, name: str | None = None) -> str:
    """``<registry>/<group>/<project>[/<name>]:<version>`` — the one image name.

    The reference is identical wherever it is computed (the parity rule): the
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
    # CI_REGISTRY_IMAGE; ghcr rejects uppercase). The tag is left untouched.
    return f"{ctx.ci.registry}/{repository.lower()}:{ctx.version}"


GIT_TOKEN_SECRET = "git_token"
"""BuildKit secret id for the git token, the contract between
:func:`git_credentials` and any recipe cloning private repos. The escape hatch
passes the same id the existing repo CI already uses:
``docker build --secret id=git_token,env=CI_JOB_TOKEN``."""


def git_credentials(
    dag: dagger.Client, ctx: Context, *, host: str
) -> tuple[list[dagger.Secret], dagger.Socket | None]:
    """Credentials for a build that clones private repos from ``host``.

    Domain-agnostic, natively forwarded by Dagger: the job token travels as a
    secret named :data:`GIT_TOKEN_SECRET` (scrubbed, never a layer), a local
    ssh agent as a forwarded socket; the recipe's runtime branching picks
    whichever arrived. Raises when neither exists — failing fast beats a
    mid-build clone error.
    """
    secrets: list[dagger.Secret] = []
    socket: dagger.Socket | None = None
    if ctx.ci.job_token is not None:
        secrets.append(dag.set_secret(GIT_TOKEN_SECRET, ctx.ci.job_token))
    if ctx.ci.ssh_auth_sock is not None and Path(ctx.ci.ssh_auth_sock).is_socket():
        socket = dag.host().unix_socket(ctx.ci.ssh_auth_sock)
    if not secrets and socket is None:
        raise ArdtError(
            f"no git credentials available for `{host}`",
            hint="CI provides the job token; locally run an ssh agent or set "
            "`job_token:` (a PAT) in ~/.config/ardt/credentials.yaml",
        )
    return secrets, socket


def registry_secret(dag: dagger.Client, ctx: Context) -> dagger.Secret:
    """The registry password as a Dagger secret (scrubbed from logs, 02 §6)."""
    if ctx.ci.registry_password is None:
        raise ArdtError(
            "no registry credentials available",
            hint="CI provides them; locally fill ~/.config/ardt/credentials.yaml",
        )
    return dag.set_secret("registry-password", ctx.ci.registry_password)


def build_variants(
    dag: dagger.Client,
    src: dagger.Directory,
    *,
    dockerfile: str = "Dockerfile",
    platforms: Sequence[str] = ("linux/amd64",),
    build_args: dict[str, str] | None = None,
) -> list[dagger.Container]:
    """One container per platform, built from the repo's Dockerfile.

    The Dockerfile defines the artifact; this only fans out the build (02 §7:
    shipped layers are never assembled in pipeline code).
    """
    args = [dagger.BuildArg(k, v) for k, v in (build_args or {}).items()]
    return [
        src.docker_build(dockerfile=dockerfile, platform=dagger.Platform(p), build_args=args)
        for p in platforms
    ]


async def publish_multiarch(
    dag: dagger.Client,
    ctx: Context,
    ref: str,
    variants: Sequence[dagger.Container],
) -> str:
    """Push the platform variants as one manifest; returns and emits the digest.

    Credentials enter here and only here — build containers never see them.
    """
    secret = registry_secret(dag, ctx)
    user = ctx.ci.registry_user or ""
    registry_host = ref.split("/", 1)[0]
    target = dag.container().with_registry_auth(registry_host, user, secret)
    digest = await target.publish(ref, platform_variants=list(variants))
    ctx.emit(image=ref, image_digest=digest)
    return digest
