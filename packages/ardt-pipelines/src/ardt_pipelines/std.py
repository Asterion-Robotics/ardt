"""Shared pipeline helpers (02 §1/§3/§6).

Plugin pipelines build on these instead of raw Dagger calls where possible, so
most SDK churn lands here and in :mod:`.engine` rather than in every plugin.
"""

from __future__ import annotations

from collections.abc import Sequence

import dagger

from ardt_core.context import Context
from ardt_core.errors import ArdtError

SOURCE_EXCLUDES = (".git", "build", "install", "log", ".venv", "__pycache__")
"""Never ship the workspace's derived state into a build container."""


def source_dir(dag: dagger.Client, ctx: Context) -> dagger.Directory:
    """The project's source tree, minus derived state."""
    return dag.host().directory(str(ctx.project_root), exclude=list(SOURCE_EXCLUDES))


def cache_volume(dag: dagger.Client, ctx: Context, purpose: str) -> dagger.CacheVolume:
    """Deterministic cache-volume naming: ``<purpose>-<project>`` (02 §1 rule 3)."""
    return dag.cache_volume(f"{purpose}-{ctx.project}")


def image_ref(ctx: Context, name: str | None = None) -> str:
    """``<registry>/<project>:<version>`` — the tag policy applied to images."""
    if ctx.ci.registry is None:
        raise ArdtError(
            "no registry configured",
            hint="CI provides one; locally set `registry:` in ~/.config/ardt/credentials.yaml",
        )
    return f"{ctx.ci.registry}/{name or ctx.project}:{ctx.version}"


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
        dag.container(platform=dagger.Platform(p)).build(
            context=src, dockerfile=dockerfile, build_args=args
        )
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
