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
3. ``ardt test``   — red tests fail the build (stage ``test``, forked from ``build``)
4. stage the JUnit XMLs at a fixed path      (stage ``test``)
5. the shipped runtime image (``FROM base_image`` + repo's extra layers,
   forked from ``build`` — deliberately NOT from ``test``)

— and the pipeline only orchestrates: render the recipe, build the ``test``
target natively (which *is* deps/build/test — the CI gate), export the
reports and the rendered Dockerfile, then build/publish the ``runtime``
target per platform. ``runtime`` not depending on ``test`` is the point of
the split: when it did, every foreign-arch runtime build re-ran the whole
suite under QEMU. The escape hatch mirrors it:
``docker build --target test`` proves a change, a plain ``docker build``
produces the shipped image without re-running tests. **Repos own no
Dockerfile**; they set the knobs in ``pipelines.ros_ci:``, and a repo that
truly needs local image content extends the configured base with a small
``base.Dockerfile`` (``FROM ${BASE_IMAGE}`` + its layers), spliced into the
rendered recipe as a stage:

.. code-block:: yaml

    pipelines:
      ros_ci:
        base_image: ros:jazzy-ros-base
        cmd: ["bash", "-lc", ". /opt/app/setup.bash && ros2 run my_pkg node"]
        platforms: [linux/amd64, linux/arm64]
        git_host: code.asterion-robotics.com   # private `.repos` deps need auth
        git_ssh_port: 5022

The ardt installed inside the image comes from the repo's ``ardt:`` config
section (:mod:`ardt_core.dist`) — pin ``ardt.version`` there for reproducible
recipes. ``--arg ardt_source=`` overrides it for one run: a directory injects
a local checkout into the build; a ``git+…`` URL swaps the monorepo address.
"""

from __future__ import annotations

import asyncio
import platform
from collections.abc import Sequence
from pathlib import Path

import dagger
from pydantic import BaseModel, ConfigDict, Field

from ardt_core.context import Context
from ardt_core.dist import DistConfig
from ardt_pipelines import pipeline, std

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
    """Container CMD of the shipped image."""
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


class PipelinesSection(BaseModel):
    """The ``pipelines:`` config section this plugin claims."""

    model_config = ConfigDict(extra="allow")

    ros_ci: RosCiConfig = Field(default_factory=RosCiConfig)


def _config(ctx: Context) -> RosCiConfig:
    return ctx.cfg.section_as("pipelines", PipelinesSection).ros_ci


def _git_credentials(
    ctx: Context, dag: dagger.Client, cfg: RosCiConfig
) -> tuple[list[dagger.Secret], dagger.Socket | None]:
    """The std credential plumbing, switched by the ``git_host`` knob."""
    if cfg.git_host is None:
        return [], None
    return std.git_credentials(dag, ctx, host=cfg.git_host)


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


def _native_variant(
    platforms: list[str], variants: list[dagger.Container]
) -> dagger.Container | None:
    """The variant this machine can actually run, for ``--load``.

    A single-platform build is taken at face value; a multi-platform one picks
    the variant matching the local architecture, or none.
    """
    if len(variants) == 1:
        return variants[0]
    native = _NATIVE_PLATFORM.get(platform.machine())
    for built_platform, variant in zip(platforms, variants, strict=True):
        if built_platform == native:
            return variant
    return None


def _selected_platforms(cfg: RosCiConfig, override: Sequence[str]) -> list[str]:
    """``--arg platforms=…`` narrows ONE run; empty keeps the config.

    The MR gate is the intended user: ``--arg platforms=linux/amd64`` skips
    the emulated arm64 build entirely, while the tag pipeline runs the config
    default and publishes the full manifest list.
    """
    return list(override) if override else list(cfg.platforms)


def _ardt_dist(ctx: Context, ardt_source: str) -> DistConfig:
    """The repo's ``ardt:`` section, with a ``--arg ardt_source=git+…`` swap."""
    section = ctx.cfg.ardt
    if ardt_source:
        section = section.model_copy(update={"git": ardt_source})
    return section


def _build_context(
    ctx: Context, dag: dagger.Client, cfg: RosCiConfig, ardt_source: str
) -> tuple[dagger.Directory, str]:
    """The build context (source + rendered recipe) and the rendered text."""
    src = std.source_dir(dag, ctx)

    local_ardt = bool(ardt_source) and Path(ardt_source).is_dir()
    rendered = recipes.render_ros2(
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
    context = src.with_new_file(recipes.RENDERED_NAME, rendered)
    if local_ardt:
        checkout = dag.host().directory(ardt_source, exclude=[".git", ".venv", "__pycache__"])
        context = context.with_directory(recipes.LOCAL_ARDT_DIR, checkout)
    return context, rendered


@pipeline(name="ros-ci", doc="deps/build/test as image stages; publish the result on --publish")
async def ros_ci(
    ctx: Context,
    dag: dagger.Client,
    ardt_source: str = "",
    platforms: list[str] = (),
) -> None:
    cfg = _config(ctx)
    build_platforms = _selected_platforms(cfg, platforms)
    secrets, ssh = _git_credentials(ctx, dag, cfg)
    context, rendered = _build_context(ctx, dag, cfg, ardt_source)

    # Steps 1-4: the `test` target runs ardt deps/build/test as layers, on the
    # native platform only. A red test is a failed image build — there is no
    # separate test phase, and no other platform re-runs the suite: the
    # runtime targets below fork from `build`, upstream of the tests.
    test_stage = context.docker_build(
        dockerfile=recipes.RENDERED_NAME, target=recipes.TEST_TARGET, secrets=secrets, ssh=ssh
    )
    await test_stage.sync()

    # Export the JUnit XMLs (CI renders them) and the rendered Dockerfile
    # (the audit/`docker build` escape hatch ships with every run).
    export_dir = ctx.project_root / JUNIT_EXPORT_DIR
    # wipe: stale JUnit XMLs from a previous run must not survive into this
    # run's reports.
    await test_stage.directory(recipes.RESULTS_DIR).export(str(export_dir), wipe=True)
    rendered_path = export_dir / recipes.RENDERED_NAME
    rendered_path.parent.mkdir(parents=True, exist_ok=True)
    rendered_path.write_text(rendered, encoding="utf-8")
    # The escape hatch needs the same context excludes the pipeline used.
    (export_dir / recipes.DOCKERIGNORE_NAME).write_text(
        recipes.render_dockerignore(std.SOURCE_EXCLUDES), encoding="utf-8"
    )
    ctx.emit(
        junit_dir=JUNIT_EXPORT_DIR,
        tests_ok=True,
        rendered_dockerfile=f"{JUNIT_EXPORT_DIR}/{recipes.RENDERED_NAME}",
    )

    # Step 5: the runtime target — built even without --publish so a broken
    # runtime stage fails the MR run, published only on --publish.
    variants = [
        context.docker_build(
            dockerfile=recipes.RENDERED_NAME,
            platform=dagger.Platform(p),
            target=recipes.RUNTIME_TARGET,
            # Non-native platforms rebuild the build stage, deps layer included
            # (the deps layer is a cache hit on a warm engine unless a manifest
            # changed — see the recipe's manifests-first COPY).
            secrets=secrets,
            ssh=ssh,
        )
        for p in build_platforms
    ]
    # gather, not a sequential loop: the engine overlaps one arch's
    # network-bound apt with the other's CPU-bound (emulated) compile.
    await asyncio.gather(*(variant.sync() for variant in variants))

    if ctx.load:
        native = _native_variant(build_platforms, variants)
        if native is None:
            ctx.console.warn(
                f"--load skipped: none of {build_platforms} matches this machine "
                "(the daemon can hold a foreign-arch image but cannot run it)"
            )
        else:
            names = await std.load_local(ctx, native)
            ctx.emit(loaded=names)
            ctx.console.success(
                f"loaded {', '.join(names)} into the local docker daemon (version {ctx.version})"
            )

    if not ctx.publish:
        ctx.console.info("runtime image built; skipping push (no --publish)")
        return

    ref = std.image_ref(ctx, cfg.image)
    digest = await std.publish_multiarch(dag, ctx, ref, variants)
    ctx.console.success(f"published {ref} @ {digest}")
