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

"""Built-in pipelines.

``ros-ci`` is the interim generic pipeline, built around one
idea: **building the image is the CI run**. The image recipe (owned by
:mod:`.recipes`, versioned with ardt) runs the ardt tasks as build stages —

1. ``ardt deps``   — rosdep install          (stage ``build``)
2. ``ardt build``  — colcon build            (stage ``build``)
3. ``ardt test``   — no network, exit code staged   (stage ``test``, forked from ``build``)
4. stage the JUnit XMLs and logs at a fixed path (stage ``test``, exported through ``reports``)
5. the shipped runtime image (``FROM base_image`` + repo's extra layers,
   forked from ``build`` — deliberately NOT from ``test``)

— and the pipeline only orchestrates: render the recipe and a bake file,
build the ``reports`` target natively (which *is* deps/build/test — the CI
gate, exported with the rendered recipe into ``pipeline-reports/``), then
build the ``runtime`` target for the selected platforms. ``runtime`` not
depending on ``test`` is the point of the split: when it did, every
foreign-arch runtime build re-ran the whole suite under QEMU. The escape
hatch mirrors it: ``docker buildx bake -f pipeline-reports/bake.json reports``
proves a change, ``... runtime`` produces the shipped image without re-running
tests. **Repos own no Dockerfile**; they set the knobs in ``pipelines.ros_ci:``,
and a repo that truly needs local image content extends the configured base
with a small ``base.Dockerfile`` (``FROM ${BASE_IMAGE}`` + its layers), spliced
into the rendered recipe as a stage:

.. code-block:: yaml

    pipelines:
      ros_ci:
        base_image: ros:jazzy-ros-base
        cmd: ["ros2", "run", "my_pkg", "node"]  # entrypoint sources the overlay
        platforms: [linux/amd64, linux/arm64]
        git_host: code.asterion-robotics.com   # private `.repos` deps need auth
        git_ssh_port: 5022

Publishing: with every configured platform in one run, bake pushes one
manifest list under the image name. A run narrowed to a subset (``--arg
platforms=linux/arm64``, the one-job-per-platform CI layout) pushes its image
by digest and records it under ``pipeline-reports/digests/``; ``ardt pipe
merge`` turns the records into the tag once they sit together.

The ardt installed inside the image comes from the repo's ``ardt:`` config
section (:mod:`ardt_core.dist`): ``ardt.version`` when set, else the release of
the ardt running this pipeline. ``--arg ardt_source=`` overrides it for one run:
a directory becomes a named build context the recipe installs from; a
``git+…`` URL swaps the monorepo address.
"""

from __future__ import annotations

import platform
import shutil
import uuid
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from ardt_core.context import Context
from ardt_core.dist import DistConfig
from ardt_core.errors import ArdtError
from ardt_pipelines import pipeline, std
from ardt_pipelines.buildx import BAKE_FILE, Buildx, Target, render_bake

from . import recipes

JUNIT_EXPORT_DIR = "pipeline-reports"


class RosCiConfig(BaseModel):
    """The ``pipelines.ros_ci:`` section."""

    model_config = ConfigDict(extra="forbid")

    builder: str = "ros:jazzy-ros-base"
    """Base of the build+test stage (process — never ships)."""
    base_image: str = "ros:jazzy-ros-base"
    """Base (``FROM``) of the SHIPPED runtime image. It need not carry the
    workspace's runtime closure: the runtime stage installs the built
    packages' exec dependencies itself, via its own rosdep pass."""
    base_dockerfile: str = "base.Dockerfile"
    """Optional in-repo base extension: a single-stage Dockerfile starting
    ``FROM ${BASE_IMAGE}`` (kernel modules, vendor drivers…). When present it is
    spliced into the rendered recipe and the runtime image builds on it."""
    install_base: str = "/opt/ros/app"
    """Where the workspace installs inside the image (build, test and the
    runtime copy all use it)."""
    strip_dev_files: bool = False
    """IP protection: remove headers (``include/``), static libs (``*.a``) and
    CMake/pkg-config exports from the install base before the runtime copy, so
    the shipped image cannot be developed against."""
    cmd: list[str] | None = None
    """Container CMD of the shipped image; ``["bash"]`` when unset. It runs
    under an entrypoint that sources the workspace overlay first, so commands
    need not source anything themselves."""
    platforms: list[str] = Field(default_factory=lambda: ["linux/amd64"])
    image: str | None = None
    """Sub-image appended under the registry project path
    (``<registry>/<project-path>/<image>``); None publishes at the path itself."""
    git_host: str | None = None
    """Private git host the ``.repos`` file clones from (``vcs import`` inside
    the deps layer needs credentials for it). When set, the pipeline forwards
    the CI job token (or a local ssh agent) into the build, and the rendered
    recipe branches between them; when None the deps layer stays credential-free."""
    git_ssh_port: int = 22
    """SSH port of ``git_host`` for the ssh-agent path."""
    git_token_user: str = "gitlab-ci-token"
    """Username the token authenticates as (GitLab job tokens require this
    literal; PATs accept any username, so the default serves both)."""
    compression: str = "gzip"
    """Layer compression of the published image: ``gzip`` (every consumer
    reads it) or ``zstd`` (smaller and faster to unpack, needs a consumer on
    containerd 1.6 or Docker 23 and later)."""


class PipelinesSection(BaseModel):
    """The ``pipelines:`` config section this plugin claims."""

    model_config = ConfigDict(extra="allow")

    ros_ci: RosCiConfig = Field(default_factory=RosCiConfig)


def _config(ctx: Context) -> RosCiConfig:
    return ctx.cfg.section_as("pipelines", PipelinesSection).ros_ci


def _git_credentials(ctx: Context, cfg: RosCiConfig) -> std.Credentials:
    """The std credential plumbing, switched by the ``git_host`` knob."""
    if cfg.git_host is None:
        return std.Credentials()
    return std.git_credentials(ctx, host=cfg.git_host)


def _rosdep_skip_keys(ctx: Context) -> tuple[str, ...]:
    """``tasks.ros.rosdep_skip_keys``, read raw.

    The runtime stage runs its own rosdep pass and must skip the same keys the
    build stage's ``ardt deps`` skips. The section belongs to ``ardt-ros-tasks``
    (which this plugin must not import), so it is read as plain data and treated
    as absent when malformed — the task plugin owns validation.
    """
    keys = ctx.cfg.raw("tasks.ros.rosdep_skip_keys")
    if not isinstance(keys, list):
        return ()
    return tuple(key for key in keys if isinstance(key, str))  # pyright: ignore[reportUnknownVariableType]


_NATIVE_PLATFORM = {"x86_64": "linux/amd64", "aarch64": "linux/arm64", "arm64": "linux/arm64"}


def _native_platform(platforms: list[str]) -> str | None:
    """The platform this machine can actually run, for ``--load``.

    A single-platform build is taken at face value; a multi-platform one picks
    the platform matching the local architecture, or none.
    """
    if len(platforms) == 1:
        return platforms[0]
    native = _NATIVE_PLATFORM.get(platform.machine())
    return native if native in platforms else None


def _selected_platforms(cfg: RosCiConfig, override: Sequence[str]) -> list[str]:
    """``--arg platforms=…`` narrows ONE run; empty keeps the config.

    The MR gate is the intended user: ``--arg platforms=linux/amd64`` skips
    the emulated arm64 build entirely, while the tag pipeline runs the config
    default and publishes the full manifest list, or one job per platform
    pushes by digest for ``ardt pipe merge``.
    """
    return list(override) if override else list(cfg.platforms)


def _ardt_dist(ctx: Context, ardt_source: str) -> DistConfig:
    """The repo's ``ardt:`` section, with a ``--arg ardt_source=git+…`` swap."""
    section = ctx.cfg.ardt
    if ardt_source:
        section = section.model_copy(update={"git": ardt_source})
    return section


def _render(ctx: Context, cfg: RosCiConfig, ardt_source: str) -> str:
    local_ardt = bool(ardt_source) and Path(ardt_source).is_dir()
    return recipes.render_ros2(
        builder=cfg.builder,
        base_image=cfg.base_image,
        project=ctx.project,
        project_root=ctx.project_root,
        base_dockerfile=cfg.base_dockerfile,
        cmd=cfg.cmd,
        ardt_requirements=_ardt_dist(ctx, ardt_source).requirements(recipes.ARDT_MODULES),
        local_ardt=local_ardt,
        install_base=cfg.install_base,
        strip_dev_files=cfg.strip_dev_files,
        git_host=cfg.git_host,
        git_ssh_port=cfg.git_ssh_port,
        git_token_user=cfg.git_token_user,
        rosdep_skip_keys=_rosdep_skip_keys(ctx),
    )


def _prepare_export(ctx: Context, rendered: str) -> Path:
    """``pipeline-reports/``: wiped, then the rendered recipe and its context
    excludes written into it; the bake outputs land beside them.

    wipe: stale JUnit XMLs from a previous run must not survive into this
    run's reports.
    """
    export_dir = ctx.project_root / JUNIT_EXPORT_DIR
    # the digest records survive the wipe: one platform per run, merged after the last
    for stale in export_dir.iterdir() if export_dir.is_dir() else []:
        if stale.name != Path(std.DIGESTS_DIR).name:
            shutil.rmtree(stale, ignore_errors=True) if stale.is_dir() else stale.unlink()
    export_dir.mkdir(parents=True, exist_ok=True)
    (export_dir / recipes.RENDERED_NAME).write_text(rendered, encoding="utf-8")
    # The pipeline's bake and the escape hatch read the same excludes.
    (export_dir / recipes.DOCKERIGNORE_NAME).write_text(
        recipes.render_dockerignore(std.SOURCE_EXCLUDES), encoding="utf-8"
    )
    # Self-ignoring, ruff-cache style: the reports dir stays out of git without
    # a root .gitignore entry.
    (export_dir / ".gitignore").write_text(
        "# Automatically created by ardt.\n*\n", encoding="utf-8"
    )
    return export_dir


def _cache(ctx: Context, cfg: RosCiConfig, target: str) -> tuple[list[str], list[str]]:
    """``cache-from`` always when the project has a registry; ``cache-to`` on
    CI only, so a laptop reads the fleet's cache and never writes it."""
    ref = std.cache_ref(ctx, cfg.image, target)
    if ref is None:
        return [], []
    cache_from = [f"type=registry,ref={ref}"]
    # ignore-error: a run whose token cannot write the cache (a fork's MR) is
    # not a failed build, it is a build that left no cache behind
    cache_to = [f"type=registry,ref={ref},mode=max,ignore-error=true"] if ctx.ci.is_ci else []
    return cache_from, cache_to


def _runtime_output(
    ctx: Context, cfg: RosCiConfig, platforms: list[str], *, split: bool
) -> tuple[list[str], list[str]]:
    """The runtime target's ``output`` and ``tags``.

    No ``--publish``: the image is built and kept in the cache only (a broken
    runtime stage fails the MR run). ``--publish`` with every configured
    platform: one pushed manifest list under the image name. ``--publish`` on
    a subset (``split``): pushed by digest, no tag, for ``ardt pipe merge``.
    """
    if not ctx.publish:
        return ["type=cacheonly"], []
    compression = f",compression={cfg.compression},oci-mediatypes=true,force-compression=true"
    if split:
        repository = std.image_repository(ctx, cfg.image)
        return [
            f"type=image,push=true,push-by-digest=true,name-canonical=true,name={repository}"
            + compression
        ], []
    return [f"type=image,push=true{compression}"], [std.image_ref(ctx, cfg.image)]


def plan(
    ctx: Context, cfg: RosCiConfig, *, platforms: list[str], credentials: std.Credentials
) -> list[Target]:
    """The bake targets of one run: ``reports`` (the gate), ``runtime`` (the
    shipped image for the selected platforms) and, with ``--load``, a
    ``runtime-load`` of the native platform into the local daemon."""
    dockerfile = f"{JUNIT_EXPORT_DIR}/{recipes.RENDERED_NAME}"
    reports_from, reports_to = _cache(ctx, cfg, recipes.BUILD_TARGET)
    targets = [
        Target(
            name=recipes.REPORTS_TARGET,
            dockerfile=dockerfile,
            target=recipes.REPORTS_TARGET,
            # A fresh value per run: the test layer succeeds whatever the tests
            # say, so a cached one would replay a red result on retry.
            args={recipes.TEST_RUN_ARG: uuid.uuid4().hex},
            output=[f"type=local,dest={JUNIT_EXPORT_DIR}"],
            cache_from=reports_from,
            cache_to=reports_to,
            secret=credentials.secret,
            ssh=credentials.ssh,
        )
    ]
    split = sorted(platforms) != sorted(cfg.platforms)
    output, tags = _runtime_output(ctx, cfg, platforms, split=split)
    runtime_from, runtime_to = _cache(ctx, cfg, recipes.RUNTIME_TARGET)
    targets.append(
        Target(
            name=recipes.RUNTIME_TARGET,
            dockerfile=dockerfile,
            target=recipes.RUNTIME_TARGET,
            platforms=platforms,
            output=output,
            tags=tags,
            # The build stage's cache serves the runtime's deps and build layers
            # on every platform; the runtime's own layers get their own ref.
            cache_from=reports_from + runtime_from,
            cache_to=runtime_to,
            secret=credentials.secret,
            ssh=credentials.ssh,
        )
    )
    if ctx.load:
        native = _native_platform(platforms)
        if native is None:
            ctx.console.warn(
                f"--load skipped: none of {platforms} matches this machine "
                "(the daemon can hold a foreign-arch image but cannot run it)"
            )
        else:
            targets.append(
                Target(
                    name=f"{recipes.RUNTIME_TARGET}-load",
                    dockerfile=dockerfile,
                    target=recipes.RUNTIME_TARGET,
                    platforms=[native],
                    output=["type=docker"],
                    tags=std.load_names(ctx),
                    cache_from=reports_from + runtime_from,
                    secret=credentials.secret,
                    ssh=credentials.ssh,
                )
            )
    return targets


@pipeline(name="ros-ci", doc="deps/build/test as image stages; publish the result on --publish")
def ros_ci(
    ctx: Context,
    builder: Buildx,
    ardt_source: str = "",
    platforms: list[str] = (),  # pyright: ignore[reportArgumentType]
) -> None:
    cfg = _config(ctx)
    build_platforms = _selected_platforms(cfg, platforms)
    credentials = _git_credentials(ctx, cfg)
    rendered = _render(ctx, cfg, ardt_source)
    export_dir = _prepare_export(ctx, rendered)

    targets = plan(ctx, cfg, platforms=build_platforms, credentials=credentials)
    if ardt_source and Path(ardt_source).is_dir():
        for target in targets:
            target.contexts[recipes.LOCAL_ARDT_CONTEXT] = str(Path(ardt_source).resolve())
    bake_file = export_dir / BAKE_FILE
    bake_file.write_text(render_bake(targets), encoding="utf-8")
    builder.with_env(credentials.env)
    # a no-op without credentials; with them the cache export and the push need it
    builder.login()

    # Steps 1-4: the `reports` target runs ardt deps/build/test as layers, on
    # the native platform only, and exports the results beside the recipe. A
    # red test does not fail the image build: the test layer stages its exit
    # code with the results, so the reports of a red run are exported before
    # the pipeline fails on it. No other platform re-runs the suite: the
    # runtime target forks from `build`, upstream of the tests.
    builder.bake(bake_file, [recipes.REPORTS_TARGET], cwd=ctx.project_root)
    exit_file = export_dir / recipes.TEST_EXIT_FILE
    test_exit = exit_file.read_text(encoding="utf-8").strip() if exit_file.is_file() else "unknown"
    tests_ok = test_exit == "0"
    ctx.emit(
        junit_dir=JUNIT_EXPORT_DIR,
        tests_ok=tests_ok,
        rendered_dockerfile=f"{JUNIT_EXPORT_DIR}/{recipes.RENDERED_NAME}",
        bake_file=f"{JUNIT_EXPORT_DIR}/{BAKE_FILE}",
    )
    if not tests_ok:
        raise ArdtError(
            f"tests failed: `ardt test` exited {test_exit}; the JUnit reports and the logs beside "
            f"them are in {JUNIT_EXPORT_DIR}/, nothing was built past the tests"
        )

    # Step 5: the runtime target — built even without --publish so a broken
    # runtime stage fails the MR run, pushed only on --publish; the load
    # target beside it puts the native image into the daemon.
    runtime_targets = [t.name for t in targets if t.name != recipes.REPORTS_TARGET]
    metadata = builder.bake(bake_file, runtime_targets, cwd=ctx.project_root)

    if ctx.load and f"{recipes.RUNTIME_TARGET}-load" in runtime_targets:
        names = std.load_names(ctx)
        ctx.emit(loaded=names)
        ctx.console.success(
            f"loaded {', '.join(names)} into the local docker daemon (version {ctx.version})"
        )

    if not ctx.publish:
        ctx.console.info("runtime image built; skipping push (no --publish)")
        return

    digest = str(metadata.get(recipes.RUNTIME_TARGET, {}).get("containerimage.digest", ""))
    if sorted(build_platforms) != sorted(cfg.platforms):
        repository = std.image_repository(ctx, cfg.image)
        built = ",".join(build_platforms)
        path = std.write_digest(ctx, repository=repository, platform=built, digest=digest)
        ctx.console.info(f"recorded {built} as {digest} in {path.relative_to(ctx.project_root)}")
        ctx.emit(image_repository=repository, image_digest=digest, platforms=build_platforms)
        ctx.console.success(
            f"pushed {repository}@{digest} for {', '.join(build_platforms)}; "
            "`ardt pipe merge` creates the tag once every platform's record is in"
        )
        return
    ref = std.image_ref(ctx, cfg.image)
    ctx.emit(image=ref, image_digest=digest)
    ctx.console.success(f"published {ref} @ {digest}")
