"""The doc task as a library function. The CLI in :mod:`.cli` is a thin front.

``build`` runs Doxygen (when the repo has C/C++ and it is not switched off)
and then sphinx — one version, from the working tree, into the fixed
``build/doc`` convention. Sphinx runs as ``sys.executable -m sphinx`` so it
executes in the venv that holds this plugin: the preset, breathe and the
ros-interfaces extension are importable by ``conf.py`` by construction.
"""

from __future__ import annotations

import sys
from pathlib import Path

from ardt_core.context import Context
from ardt_core.errors import ArdtError

from . import doxygen as doxygen_module
from .config import DOC_OUTPUT, DocConfig, doc_config

_CPP_SUFFIXES = frozenset({".h", ".hpp", ".hh", ".c", ".cc", ".cpp", ".cxx"})
_SKIP_DIRS = frozenset({"build", "install", "log", ".git", ".venv", "__pycache__"})


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
            hint="a 3-line conf.py suffices: `from ardt_tasks_doc.preset import *` "
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
        ctx.runner.run(command)

    ctx.emit(
        html_dir=f"{DOC_OUTPUT}/html",
        doxygen_xml=f"{DOC_OUTPUT}/doxygen/xml" if with_doxygen else None,
    )
    if not ctx.dry_run:
        ctx.console.success(f"docs at {html / 'index.html'}")


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
