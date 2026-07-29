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

"""The doc task as a library function. The CLI in :mod:`ardt_doc_tasks.cli` is a thin front.

``build`` runs Doxygen (when the repo has C/C++ and it is not switched off)
and then sphinx — one version, from the working tree, into the fixed
``build/doc`` convention. Sphinx runs as ``sys.executable -m sphinx`` so it
executes in the venv that holds this plugin: the preset, breathe and the
ros-interfaces extension are importable by ``conf.py`` by construction.
"""

from __future__ import annotations

import contextlib
import sys
from pathlib import Path

from ardt_core import env
from ardt_core.context import Context
from ardt_core.errors import ArdtError

from . import doxygen as doxygen_module
from .config import DOC_OUTPUT, STYLE_ENV, DocConfig, doc_config

_CPP_SUFFIXES = frozenset({".h", ".hpp", ".hh", ".c", ".cc", ".cpp", ".cxx"})
_SKIP_DIRS = frozenset({"build", "install", "log", ".git", ".venv", "__pycache__"})

# The docs-ci site directory. Owned by ardt-doc-pipelines (SITE_DIR in
# docs_ci.py) and mirrored here: the task plane must not import the pipeline
# plane, and `doc serve --site` must work whether or not it is installed.
SITE_DIR = "public"


def build(ctx: Context) -> None:
    """Doxygen (if enabled) then sphinx html. Emits the output paths."""
    cfg = doc_config(ctx.cfg)
    source = ctx.project_root / cfg.source_dir
    if not source.is_dir():
        raise ArdtError(
            f"doc source directory `{cfg.source_dir}` does not exist",
            hint="create it, or point `tasks.doc.source_dir` in ardt.yaml at the sphinx project",
        )
    if not (source / "conf.py").is_file():
        raise ArdtError(
            f"`{cfg.source_dir}/conf.py` not found",
            hint="a 3-line conf.py suffices: `from ardt_doc_tasks.preset import *` "
            "plus your `project = ...`",
        )

    out = ctx.project_root / DOC_OUTPUT
    with_doxygen = _doxygen_enabled(ctx.project_root, cfg)
    if with_doxygen:
        _run_doxygen(ctx, cfg, out / "doxygen")

    html = out / "html"
    with ctx.console.section("sphinx build"):
        command = [sys.executable, "-m", "sphinx", "-b", "html"]
        if cfg.strict:
            command += ["-W", "--keep-going"]
        command += [str(source), str(html)]
        ctx.runner.run(command, extra_env=_style_env(ctx, cfg))

    ctx.emit(
        html_dir=f"{DOC_OUTPUT}/html",
        doxygen_xml=f"{DOC_OUTPUT}/doxygen/xml" if with_doxygen else None,
    )
    if not ctx.dry_run:
        ctx.console.success(f"docs at {html / 'index.html'}")
        ctx.console.detail("preview: ardt doc serve")


def serve(ctx: Context, *, port: int, site: bool) -> None:
    """Serve built docs (or the docs-ci site) over local http.

    ``file://`` cannot preview these builds faithfully: mapping a directory URL
    to its ``index.html`` is a web-server convention, not a filesystem one, and
    the version switcher fetches ``versions.json``, which browsers block on
    file origins. Static serving needs nothing beyond the stdlib, so this is
    ``python -m http.server`` from the venv that holds this plugin.
    """
    target = SITE_DIR if site else f"{DOC_OUTPUT}/html"
    root = ctx.project_root / target
    if not root.is_dir() and not ctx.dry_run:
        producer = "ardt pipe run docs-ci" if site else "ardt doc build"
        raise ArdtError(
            f"nothing to serve: `{target}/` does not exist",
            hint=f"run `{producer}` first",
        )
    ctx.console.info(f"serving {target}/ at http://127.0.0.1:{port}/ (Ctrl+C to stop)")
    command = [
        sys.executable,
        "-m",
        "http.server",
        str(port),
        "--bind",
        "127.0.0.1",
        "--directory",
        str(root),
    ]
    with contextlib.suppress(KeyboardInterrupt):
        ctx.runner.run(command)


def _style_env(ctx: Context, cfg: DocConfig) -> dict[str, str]:
    """The style handed to the preset, and why it is an environment variable.

    A caller that already set it wins: the doc pipeline sets it on the builder so
    that *every* historical ref renders with the current style, and that ref's own
    config must not override it. Empty locally means no style, not "unset".
    """
    if env.has(STYLE_ENV):
        return {}
    if cfg.style:
        # An extension list that depends on ambient state is worth stating out
        # loud rather than leaving to be discovered in a diff of the html.
        ctx.console.detail(f"style: {' '.join(cfg.style)}")
    return {STYLE_ENV: " ".join(cfg.style)}


def _doxygen_enabled(root: Path, cfg: DocConfig) -> bool:
    if cfg.doxygen != "auto":
        return cfg.doxygen
    return _has_cpp_sources(root)


def _has_cpp_sources(root: Path) -> bool:
    """True when the repo holds any C/C++ file outside derived/hidden trees."""
    stack = [root]
    while stack:
        directory = stack.pop()
        for child in directory.iterdir():
            if child.is_dir():
                if child.name not in _SKIP_DIRS and not child.name.startswith("."):
                    stack.append(child)
            elif child.suffix in _CPP_SUFFIXES:
                return True
    return False


def _run_doxygen(ctx: Context, cfg: DocConfig, out_dir: Path) -> None:
    with ctx.console.section("doxygen"):
        ctx.runner.require("doxygen", hint="apt install doxygen (or set tasks.doc.doxygen: false)")
        doxyfile = out_dir / "Doxyfile"
        if not ctx.dry_run:
            out_dir.mkdir(parents=True, exist_ok=True)
            doxyfile.write_text(
                doxygen_module.render_doxyfile(
                    project=ctx.project,
                    root=ctx.project_root,
                    inputs=cfg.doxygen_input,
                    output=out_dir,
                ),
                encoding="utf-8",
            )
        ctx.runner.run(["doxygen", str(doxyfile)])
