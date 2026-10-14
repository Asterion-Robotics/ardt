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

"""The ``docs-ci`` pipeline: a versioned documentation site under ``public/``.

One build per version, each running the same ``ardt doc build`` task a dev
runs locally (two-plane rule), inside the configured builder image:

* the **working tree** — the ref that triggered the run, named after its
  tag/branch;
* every configured **historical version** (``versions.branches`` + the
  ``versions.tags`` glob), each built from git history *with its own docs and
  config* — the site rebuilds whole every run, so Pages publishing stays a
  dumb artifact upload.

The export is the Pages contract: ``public/<version>/`` per version, a
``versions.json`` describing them (the future theme flyout reads it), and a
root ``index.html`` redirecting to the default version. On GitLab the CI shim
just declares ``public/`` as the pages artifact; a GitHub pages/gh-pages
publish step can consume the same directory.

The build is one rendered Dockerfile (exported as
``pipeline-reports/Dockerfile.docs`` with its bake file): a ``builder`` stage
with the toolchain and ardt installed, a ``tree`` stage building the working
tree, one stage per historical ref cloning the repository's ``.git`` (a named
build context) and building that ref, and a ``site`` stage of nothing but the
built html, exported locally. A historical ref that fails to build leaves a
marker instead of html and is left out of the site: refs are immutable, so a
build that breaks on one can never be repaired, and failing the whole run
over it would cost every other version. The working tree fails hard.

PDF and the pinned doc-builder image are future additions; until then the
builder is assembled on the fly (apt + pip install of ardt-doc-tasks).
"""

from __future__ import annotations

import json
import shlex
import shutil
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from ardt_core import dist
from ardt_core import git as git_module
from ardt_core.context import Context
from ardt_pipelines import pipeline, std
from ardt_pipelines.buildx import Buildx, Target, render_bake

ARDT_MODULES = ("ardt-core", "ardt-doc-tasks")
"""The ardt modules the docs builder needs (it runs ``ardt doc build``). Where
they install from is the repo's ``ardt:`` section (:mod:`ardt_core.dist`). A
repo whose docs autodoc more of the toolchain adds them via
``pipelines.docs_ci.ardt_modules``."""

SITE_DIR = "public"
"""Export directory — GitLab Pages' artifact convention."""

EXPORT_DIR = "pipeline-reports"
"""Where the rendered recipe and its bake file land, beside ros-ci's."""

RENDERED_NAME = "Dockerfile.docs"
BAKE_NAME = "bake.docs.json"
SITE_TARGET = "site"
GIT_CONTEXT = "gitdir"
"""Named build context pointing at the repository's ``.git``: historical refs
clone from it inside the build, while the main context excludes ``.git``."""
LOCAL_ARDT_CONTEXT = "ardt-src"
FAILED_MARKER = ".ardt-build-failed"
"""Left in a version's directory by a historical build that failed; the
pipeline drops the version and reports it."""

STYLE_ENV = "ARDT_DOC_STYLE"
"""The contract with the doc *task* plane, carried as a name rather than an
import: this package deliberately does not depend on ``ardt-doc-tasks`` (it
installs it into the builder, it never runs it). ``ardt_doc_tasks.config``
declares the same constant, and its preset reads it."""


class VersionsConfig(BaseModel):
    """``pipelines.docs_ci.versions:`` — which historical refs join the site."""

    model_config = ConfigDict(extra="forbid")

    branches: list[str] = Field(default_factory=list)
    """Branches built from git history (e.g. ``[main]``). Empty by default:
    only the working tree builds until a repo opts into history."""
    tags: str | None = None
    """A tag glob (e.g. ``v*``); every matching tag becomes a site version."""


class DocsCiConfig(BaseModel):
    """The ``pipelines.docs_ci:`` section."""

    model_config = ConfigDict(extra="forbid")

    builder: str = "python:3.12-slim"
    """Image the docs build in (process — never ships)."""
    apt_packages: list[str] = Field(default_factory=lambda: ["git", "doxygen", "graphviz"])
    """Installed into the builder; empty for a prebuilt builder image."""
    ardt_modules: list[str] = Field(default_factory=list)
    """ardt modules the documentation needs importable, on top of
    :data:`ARDT_MODULES` — typically a plugin repo autodoccing itself. Sphinx
    documents the *installed* packages, and where each one installs from is the
    repo's ``ardt:`` section (:mod:`ardt_core.dist`), out-of-monorepo pins
    included."""
    pip_packages: list[str] = Field(default_factory=list)
    """Requirements the docs need that no ardt distribution can declare — a
    sphinx style package, first of all. PEP 508 strings, so an index release
    (``x==1.2``) and a direct reference
    (``x @ git+https://…@v1.2``) both work, and publishing is optional.

    Not a place to paper over a missing dependency: if an *ardt* module fails to
    import, declare it there (an extra, if it is optional) rather than patching
    the builder."""
    default: str | None = None
    """Version the root redirect targets; None means the working-tree version."""
    versions: VersionsConfig = Field(default_factory=VersionsConfig)


class DocTaskConfig(BaseModel):
    """The sliver of ``tasks.doc:`` this pipeline forwards. ``extra="allow"``
    because the section belongs to ``ardt-doc-tasks``, which owns its shape."""

    model_config = ConfigDict(extra="allow")

    style: list[str] = Field(default_factory=list)
    source_dir: str = "doc"
    """Where each ref's sphinx project lives — the preflight looks for its conf.py."""


class TasksSection(BaseModel):
    """``tasks:`` — read, never claimed; the task plugins own it."""

    model_config = ConfigDict(extra="allow")

    doc: DocTaskConfig = Field(default_factory=DocTaskConfig)


class PipelinesSection(BaseModel):
    """The ``pipelines:`` config section (shared with the other pipeline plugins)."""

    model_config = ConfigDict(extra="allow")

    docs_ci: DocsCiConfig = Field(default_factory=DocsCiConfig)


def _config(ctx: Context) -> DocsCiConfig:
    return ctx.cfg.section_as("pipelines", PipelinesSection).docs_ci


def site_name(ref: str) -> str:
    """A ref as a site path segment (``feature/x`` -> ``feature-x``)."""
    return ref.replace("/", "-")


def working_tree_name(ctx: Context) -> str:
    """The working tree's version name: its tag, else its branch, else ``dev``."""
    return site_name(ctx.git.tag or ctx.git.branch or "dev")


def historical_refs(ctx: Context, cfg: DocsCiConfig) -> list[str]:
    """The configured refs that exist and carry doc config, minus the working tree's name."""
    if (cfg.versions.branches or cfg.versions.tags) and git_module.is_shallow(ctx.project_root):
        ctx.console.warn(
            "docs-ci: shallow clone — historical versions may be silently missing "
            "(fetch the full history: `fetch-depth: 0` on GitHub, `GIT_DEPTH: 0` on GitLab)"
        )
    refs: list[str] = []
    for branch in cfg.versions.branches:
        if git_module.ref_exists(ctx.project_root, branch):
            refs.append(branch)
        else:
            ctx.console.warn(f"docs-ci: configured branch `{branch}` does not exist; skipped")
    if cfg.versions.tags:
        refs.extend(git_module.list_tags(ctx.project_root, cfg.versions.tags))

    # Preflight each ref for doc config: a ref without it would abort the whole
    # site with an opaque engine error mid-build. Warn-and-skip, like the
    # missing-branch path above — one bad old tag must not kill every version.
    conf = f"{ctx.cfg.section_as('tasks', TasksSection).doc.source_dir}/conf.py"

    current = working_tree_name(ctx)
    unique: list[str] = []
    owners: dict[str, str] = {}
    for ref in refs:
        name = site_name(ref)
        if name == current:
            continue
        if name in owners:
            if owners[name] != ref:
                ctx.console.warn(
                    f"docs-ci: `{ref}` and `{owners[name]}` both map to site path `{name}`; "
                    f"keeping `{owners[name]}`"
                )
            continue
        if not git_module.path_exists_at(ctx.project_root, ref, conf):
            ctx.console.warn(f"docs-ci: `{ref}` has no {conf}; skipped")
            continue
        owners[name] = ref
        unique.append(ref)
    return unique


def versions_json(names: list[str], default: str) -> str:
    """The switcher data: one entry per built version, default first.

    ``url`` is relative to this file, which sits at the site root. A root-absolute
    ``/<name>/`` would assume the site *is* the domain root — true for GitLab
    Pages, false for a GitHub project site served under ``/<repo>/``.
    """
    ordered = [default, *[n for n in names if n != default]]
    entries = [{"name": n, "version": n, "url": f"{n}/"} for n in ordered]
    return json.dumps(entries, indent=2) + "\n"


def redirect_html(target: str) -> str:
    """The root ``index.html``: an instant redirect to the default version."""
    return (
        "<!DOCTYPE html>\n"
        '<html><head><meta charset="utf-8">\n'
        f'<meta http-equiv="refresh" content="0; url=./{target}/">\n'
        f'<link rel="canonical" href="./{target}/">\n'
        f'</head><body><a href="./{target}/">Documentation</a></body></html>\n'
    )


def builder_modules(cfg: DocsCiConfig) -> tuple[str, ...]:
    """The modules installed in the builder.

    Deduped on distribution name with ``ardt_modules`` winning, so naming a base
    module *with extras* (``ardt-core[testing]``, which the shared pytest
    fixtures need) refines that install instead of adding a second one.
    """
    merged = {dist.base_name(m): m for m in ARDT_MODULES}
    for module in cfg.ardt_modules:
        merged[dist.base_name(module)] = module
    return tuple(merged.values())


def _stage_name(index: int) -> str:
    return f"ref-{index}"


def render(
    ctx: Context, cfg: DocsCiConfig, *, refs: list[str], local_ardt: bool, ardt_source: str
) -> str:
    """The docs recipe: builder, the working tree, one stage per ref, the site."""
    modules = builder_modules(cfg)
    lines = [
        "# syntax=docker/dockerfile:1",
        "# Rendered by `ardt pipe run docs-ci` — machine-owned, exported with every run.",
        f"FROM {cfg.builder} AS builder",
    ]
    if cfg.apt_packages:
        lines.append(
            "RUN apt-get update && apt-get install -y --no-install-recommends "
            f"{' '.join(cfg.apt_packages)} && rm -rf /var/lib/apt/lists/*"
        )
    # Ahead of the ardt install: a style package moves per release, the ardt
    # layer moves every commit, so this order keeps the cheaper layer cached.
    if cfg.pip_packages:
        lines.append(f"RUN pip install --no-cache-dir {shlex.join(cfg.pip_packages)}")
    if local_ardt:
        lines.append(f"COPY --from={LOCAL_ARDT_CONTEXT} / /opt/ardt-src")
        requirements = [dist.local_requirement(m, "/opt/ardt-src") for m in modules]
    else:
        section = ctx.cfg.ardt
        if ardt_source:
            section = section.model_copy(update={"git": ardt_source})
        requirements = list(section.requirements(modules))
    lines.append(f"RUN pip install --no-cache-dir {shlex.join(requirements)}")
    # The working tree's style, imposed on every ref this builder builds: a
    # release cut before the style existed would otherwise render unthemed
    # forever; set here, the site restyles whole on the next run.
    styles = ctx.cfg.section_as("tasks", TasksSection).doc.style
    if styles:
        lines.append(f"ENV {STYLE_ENV}={shlex.quote(' '.join(styles))}")
    # Cloned repos belong to a different uid inside the container.
    lines.append(
        "RUN command -v git >/dev/null && git config --global --add safe.directory '*' || true"
    )

    lines += [
        "",
        "# the working tree: fails hard, it is the half that can still be fixed",
        "FROM builder AS tree",
        "COPY . /ws",
        "WORKDIR /ws",
        "RUN ardt doc build",
    ]
    for index, ref in enumerate(refs):
        lines += [
            "",
            f"# {ref}, from git history: a failure leaves a marker, not a broken site",
            f"FROM builder AS {_stage_name(index)}",
            f"COPY --from={GIT_CONTEXT} / /repo.git",
            # --no-hardlinks: a local clone hardlinks the object store by default,
            # which fails across the build's overlay mount.
            "RUN git clone -q --no-hardlinks /repo.git /ws"
            f" && git -C /ws checkout -q {shlex.quote(ref)}",
            "WORKDIR /ws",
            "RUN mkdir -p build/doc/html"
            f" && (ardt doc build || touch build/doc/html/{FAILED_MARKER})",
        ]
    lines += [
        "",
        "FROM scratch AS site",
        f"COPY --from=tree /ws/build/doc/html /{working_tree_name(ctx)}",
    ]
    for index, ref in enumerate(refs):
        lines.append(f"COPY --from={_stage_name(index)} /ws/build/doc/html /{site_name(ref)}")
    return "\n".join(lines) + "\n"


def collect_site(
    ctx: Context, site: Path, *, current: str, refs: list[str], default: str
) -> tuple[list[str], list[str]]:
    """Drop the versions whose build left a marker, write the switcher data and
    the root redirect; returns the versions kept and the refs skipped."""
    names: list[str] = [current]
    skipped: list[str] = []
    for ref in refs:
        name = site_name(ref)
        if (site / name / FAILED_MARKER).exists():
            shutil.rmtree(site / name, ignore_errors=True)
            ctx.console.warn(f"docs-ci: `{ref}` failed to build; leaving it out of the site")
            skipped.append(ref)
        else:
            names.append(name)
    (site / "versions.json").write_text(versions_json(names, default), encoding="utf-8")
    (site / "index.html").write_text(redirect_html(default), encoding="utf-8")
    return names, skipped


@pipeline(name="docs-ci", doc="Build the versioned docs site into public/ (Pages-ready)")
def docs_ci(ctx: Context, builder: Buildx, ardt_source: str = "") -> None:
    cfg = _config(ctx)
    current = working_tree_name(ctx)
    refs = historical_refs(ctx, cfg)
    local_ardt = bool(ardt_source) and Path(ardt_source).is_dir()
    rendered = render(ctx, cfg, refs=refs, local_ardt=local_ardt, ardt_source=ardt_source)

    export_dir = ctx.project_root / EXPORT_DIR
    export_dir.mkdir(parents=True, exist_ok=True)
    (export_dir / RENDERED_NAME).write_text(rendered, encoding="utf-8")
    (export_dir / f"{RENDERED_NAME}.dockerignore").write_text(
        "\n".join(std.SOURCE_EXCLUDES) + "\n", encoding="utf-8"
    )
    contexts = {GIT_CONTEXT: str(ctx.project_root / ".git")}
    if local_ardt:
        contexts[LOCAL_ARDT_CONTEXT] = str(Path(ardt_source).resolve())
    target = Target(
        name=SITE_TARGET,
        dockerfile=f"{EXPORT_DIR}/{RENDERED_NAME}",
        target=SITE_TARGET,
        output=[f"type=local,dest={SITE_DIR}"],
        contexts=contexts,
    )
    bake_file = export_dir / BAKE_NAME
    bake_file.write_text(render_bake([target]), encoding="utf-8")

    # wipe: a version removed from the config must also leave public/ — a stale
    # directory would otherwise ride along into the Pages artifact forever.
    site = ctx.project_root / SITE_DIR
    shutil.rmtree(site, ignore_errors=True)
    ctx.console.step(f"docs: building `{current}` and {len(refs)} historical version(s)")
    builder.bake(bake_file, [SITE_TARGET], cwd=ctx.project_root)
    if ctx.dry_run:
        return

    default = cfg.default or current
    names, skipped = collect_site(ctx, site, current=current, refs=refs, default=default)
    if default not in names:
        ctx.console.warn(f"docs-ci: default `{default}` was not built; the redirect uses it anyway")
    ctx.emit(site_dir=SITE_DIR, versions=names, default=default, skipped=skipped)
    ctx.console.success(f"site at {SITE_DIR}/ ({', '.join(names)}; default -> {default})")
    if skipped:
        ctx.console.warn(
            f"{len(skipped)} version(s) left out of the site: {', '.join(skipped)} — "
            "the site is complete apart from these"
        )
    ctx.console.info(
        f"preview: ardt doc serve --site (the {SITE_DIR}/ site needs http, not file://)"
    )
