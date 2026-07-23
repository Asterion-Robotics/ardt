"""The ardt-owned Doxyfile.

Doxygen exists here only to feed breathe: XML on, HTML/LaTeX off. The file is
rendered per run (machine-owned, like the pipeline recipes) so repos carry no
Doxyfile; a repo needing more control points ``tasks.doc.doxygen_input`` at the
right directories or turns the step off.
"""

from __future__ import annotations

from pathlib import Path

_TEMPLATE = """\
# Rendered by `ardt doc build` — machine-owned; do not edit, do not commit.
PROJECT_NAME           = "@PROJECT@"
OUTPUT_DIRECTORY       = @OUTPUT@
INPUT                  = @INPUT@
RECURSIVE              = YES
EXCLUDE_PATTERNS       = */build/* */install/* */log/* */test/* */.git/* */.venv/*
FILE_PATTERNS          = *.h *.hpp *.hh *.c *.cc *.cpp *.cxx
STRIP_FROM_PATH        = @ROOT@
EXTRACT_ALL            = YES
GENERATE_HTML          = NO
GENERATE_LATEX         = NO
GENERATE_XML           = YES
XML_PROGRAMLISTING     = NO
WARN_IF_UNDOCUMENTED   = NO
QUIET                  = YES
"""


def render_doxyfile(*, project: str, root: Path, inputs: list[str], output: Path) -> str:
    """Render the Doxyfile for one run. ``inputs`` empty means the whole repo."""
    rendered_inputs = " ".join(str(root / i) for i in inputs) if inputs else str(root)
    return (
        _TEMPLATE.replace("@PROJECT@", project)
        .replace("@OUTPUT@", str(output))
        .replace("@INPUT@", rendered_inputs)
        .replace("@ROOT@", str(root))
    )
