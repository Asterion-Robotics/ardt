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

"""Context write discipline, enforced.

Every command and plugin aliases the ONE Context instance, so a mid-run
reassignment of an identity field (``ctx.cfg = …``) is visible to everything
downstream — the classic aliasing bug, observed far from its cause.
``slots=True`` on Context already turns *invented* attributes into an
``AttributeError`` at runtime; this sweep makes the reassignment half of the
contract binding for all source in the monorepo. Commands may set ``publish``
and call ``emit()``; nothing else writes. Test code is exempt — tests inject
identity fields on instances they own.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

IDENTITY_FIELDS = {
    "project_root",
    "cfg",
    "config_source",
    "git",
    "ci",
    "console",
    "runner",
    "registry",
    "dry_run",
    "json_output",
}
CONTEXT_NAMES = {"ctx", "context"}
"""Contexts are named `ctx` by convention everywhere in this tree; `context`
is swept too, cheaply, in case one slips in."""


def _source_files() -> Iterator[Path]:
    for pattern in ("packages/*/src/**/*.py", "plugins/*/src/**/*.py"):
        yield from ROOT.glob(pattern)


def test_no_identity_field_reassignment_in_source() -> None:
    files = list(_source_files())
    assert files, "sweep found no sources — did the tree layout change?"

    offenders: list[str] = []
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            targets: list[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, ast.AugAssign | ast.AnnAssign):
                targets = [node.target]
            for target in targets:
                if (
                    isinstance(target, ast.Attribute)
                    and target.attr in IDENTITY_FIELDS
                    and isinstance(target.value, ast.Name)
                    and target.value.id in CONTEXT_NAMES
                ):
                    where = f"{path.relative_to(ROOT)}:{node.lineno}"
                    offenders.append(f"{where}: {ast.unparse(node)}")

    assert not offenders, (
        "Context identity fields are set once by Context.build() and never "
        "reassigned (see the Context docstring): " + "; ".join(offenders)
    )
