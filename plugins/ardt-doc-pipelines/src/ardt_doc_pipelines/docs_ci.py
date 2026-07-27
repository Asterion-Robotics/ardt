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

PDF and the pinned doc-builder image are future additions; until then the
builder is assembled on the fly (apt + pip install of ardt-doc-tasks).
"""

from __future__ import annotations

import json
from pathlib import Path

import dagger
from pydantic import BaseModel, ConfigDict, Field

from ardt_core import dist
from ardt_core import git as git_module
from ardt_core.context import Context
from ardt_pipelines import pipeline, std

ARDT_MODULES = ("ardt-core", "ardt-doc-tasks")
"""The ardt modules the docs builder needs (it runs ``ardt doc build``). Where
they install from is the repo's ``ardt:`` section (:mod:`ardt_core.dist`). A
repo whose docs autodoc more of the toolchain adds them via
``pipelines.docs_ci.ardt_modules``."""

SITE_DIR = "public"
"""Export directory — GitLab Pages' artifact convention."""

REPO_EXCLUDES = tuple(e for e in std.SOURCE_EXCLUDES if e != ".git")
"""Historical builds need the git history the normal source context excludes."""


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
    default: str | None = None
    """Version the root redirect targets; None means the working-tree version."""
    versions: VersionsConfig = Field(default_factory=VersionsConfig)


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
    """The configured refs that exist, minus the working tree's own name."""
    refs: list[str] = []
    for branch in cfg.versions.branches:
        if git_module.ref_exists(ctx.project_root, branch):
            refs.append(branch)
        else:
            ctx.console.warn(f"docs-ci: configured branch `{branch}` does not exist; skipped")
    if cfg.versions.tags:
        refs.extend(git_module.list_tags(ctx.project_root, cfg.versions.tags))
    current = working_tree_name(ctx)
    unique: list[str] = []
    for ref in refs:
        if site_name(ref) != current and ref not in unique:
            unique.append(ref)
    return unique


def versions_json(names: list[str], default: str) -> str:
    """The switcher data: one entry per built version, default first."""
    ordered = [default, *[n for n in names if n != default]]
    entries = [{"name": n, "version": n, "url": f"/{n}/"} for n in ordered]
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


def _builder(
    ctx: Context, dag: dagger.Client, cfg: DocsCiConfig, ardt_source: str
) -> dagger.Container:
    """The container the docs build in: toolchain + ardt-doc-tasks installed."""
    modules = builder_modules(cfg)
    container = dag.container().from_(cfg.builder)
    if cfg.apt_packages:
        packages = " ".join(cfg.apt_packages)
        container = container.with_exec(
            [
                "bash",
                "-lc",
                f"apt-get update && apt-get install -y --no-install-recommends {packages}"
                " && rm -rf /var/lib/apt/lists/*",
            ]
        )
    if ardt_source and Path(ardt_source).is_dir():
        checkout = dag.host().directory(ardt_source, exclude=[".git", ".venv", "__pycache__"])
        container = container.with_directory("/opt/ardt-src", checkout).with_exec(
            [
                "pip",
                "install",
                "--no-cache-dir",
                *(dist.local_requirement(m, "/opt/ardt-src") for m in modules),
            ]
        )
    else:
        section = ctx.cfg.ardt
        if ardt_source:
            section = section.model_copy(update={"git": ardt_source})
        container = container.with_exec(
            ["pip", "install", "--no-cache-dir", *section.requirements(modules)]
        )
    # Mounted/cloned repos belong to a different uid inside the container.
    return container.with_exec(
        [
            "bash",
            "-lc",
            "command -v git >/dev/null && git config --global --add safe.directory '*' || true",
        ]
    )


def _build_docs(container: dagger.Container) -> dagger.Directory:
    """Run the doc task in ``/ws`` and return the built html."""
    return (
        container.with_workdir("/ws")
        .with_exec(["ardt", "doc", "build"])
        .directory("/ws/build/doc/html")
    )


@pipeline(name="docs-ci", doc="Build the versioned docs site into public/ (Pages-ready)")
async def docs_ci(ctx: Context, dag: dagger.Client, ardt_source: str = "") -> None:
    cfg = _config(ctx)
    base = _builder(ctx, dag, cfg, ardt_source)

    current = working_tree_name(ctx)
    ctx.console.step(f"docs: building working tree as `{current}`")
    entries: list[tuple[str, dagger.Directory]] = [
        (current, _build_docs(base.with_directory("/ws", std.source_dir(dag, ctx))))
    ]

    repo_with_history: dagger.Directory | None = None
    for ref in historical_refs(ctx, cfg):
        if repo_with_history is None:
            repo_with_history = dag.host().directory(
                str(ctx.project_root), exclude=list(REPO_EXCLUDES)
            )
        ctx.console.step(f"docs: building `{ref}` from git history")
        checkout = (
            base.with_directory("/repo", repo_with_history)
            # --no-hardlinks: a local clone hardlinks the object store by default,
            # which fails across the container's overlay mount ("hardlink
            # different from source"). Copying costs a repo-sized read, once.
            .with_exec(["git", "clone", "-q", "--no-hardlinks", "/repo", "/ws"])
            .with_exec(["git", "-C", "/ws", "checkout", "-q", ref])
        )
        entries.append((site_name(ref), _build_docs(checkout)))

    names = [name for name, _ in entries]
    default = cfg.default or current
    if default not in names:
        ctx.console.warn(f"docs-ci: default `{default}` was not built; the redirect uses it anyway")

    site = dag.directory()
    for name, html in entries:
        site = site.with_directory(name, html)
    site = site.with_new_file("versions.json", versions_json(names, default))
    site = site.with_new_file("index.html", redirect_html(default))

    await site.export(str(ctx.project_root / SITE_DIR))
    ctx.emit(site_dir=SITE_DIR, versions=names, default=default)
    ctx.console.success(f"site at {SITE_DIR}/ ({', '.join(names)}; default -> {default})")
