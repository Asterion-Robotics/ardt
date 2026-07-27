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
