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

"""Delivery pins that must agree with each other.

The pre-commit ruff hook and `uv run ruff` are two installs of the same tool;
when their versions drift, a commit the hooks pass fails CI (or the reverse).
The config comment says they must track — this is the check that makes the
comment binding.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_precommit_ruff_rev_matches_the_locked_version() -> None:
    config = (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    match = re.search(r"ruff-pre-commit\s*\n\s*rev:\s*v?([\w.]+)", config)
    assert match, "ruff-pre-commit hook not found in .pre-commit-config.yaml"
    hook_version = match.group(1)

    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    locked = next(p["version"] for p in lock["package"] if p["name"] == "ruff")

    assert hook_version == locked, (
        f"pre-commit pins ruff {hook_version} but uv.lock resolves {locked}; "
        "bump the hook rev (or re-lock) so local hooks and CI run the same ruff"
    )
