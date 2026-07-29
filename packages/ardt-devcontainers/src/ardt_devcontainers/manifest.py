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

"""Disk state for the rendered environment: manifest, audit, write, gitignore.

The other half of the render story: :mod:`.render` builds the plan in memory
(pure), this module reconciles it with the working tree — the hash manifest
that distinguishes "ours and stale" from "hand-edited", the write that refuses
to clobber what ardt did not generate, and the gitignore upkeep.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ardt_core.errors import ArdtError

from . import __version__
from .config import DEVCONTAINER_DIR
from .render import CPP_PROPERTIES, MANIFEST, Render, digest


@dataclass
class WriteResult:
    """What ``write`` did, so the CLI can report instead of guessing."""

    written: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    """Files on disk that ardt did not generate, or that were edited by hand."""


def _manifest_key(name: str) -> str:
    """Read a pre-``.vscode/`` manifest, whose keys were bare file names.

    Without this every repo synced by an older engine would see its whole
    render reported as hand-edited on the next `ardt dev sync` — the keys, not
    the contents, changed.
    """
    return name if "/" in name else f"{DEVCONTAINER_DIR}/{name}"


def load_manifest(root: Path) -> dict[str, str]:
    """The hashes of the last render, or ``{}`` when there is none."""
    path = root / MANIFEST
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    generated = data.get("generated") if isinstance(data, dict) else None
    if not isinstance(generated, dict):
        return {}
    return {_manifest_key(str(k)): str(v) for k, v in generated.items()}  # type: ignore[union-attr]


def audit(root: Path, render: Render, *, only: dict[str, str] | None = None) -> WriteResult:
    """Compare a render against the working tree without touching anything."""
    manifest = load_manifest(root)
    result = WriteResult()
    for name, content in (only or render.files).items():
        path = root / name
        if not path.exists():
            result.written.append(name)
            continue
        on_disk = path.read_text(encoding="utf-8")
        if on_disk == content:
            result.unchanged.append(name)
        elif manifest.get(name) == digest(on_disk):
            result.written.append(name)  # ours, and stale — safe to refresh
        else:
            result.conflicts.append(name)
    return result


def write(
    root: Path,
    render: Render,
    *,
    force: bool = False,
    only: dict[str, str] | None = None,
) -> WriteResult:
    """Write the render, refusing to clobber anything ardt did not generate."""
    subset = only or render.files
    result = audit(root, render, only=subset)
    if result.conflicts and not force:
        listed = ", ".join(sorted(result.conflicts))
        raise ArdtError(
            f"ardt did not generate these file(s): {listed}",
            hint=(
                "`ardt dev sync --force` overwrites them; "
                "the supported customization knobs are `dev:` in ardt.yaml"
            ),
        )

    to_write = [*result.written, *(result.conflicts if force else [])]
    for name in to_write:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(subset[name], encoding="utf-8")
        if name in render.executable:
            path.chmod(0o755)

    manifest = load_manifest(root)
    manifest.update({name: digest(content) for name, content in subset.items()})
    manifest_path = root / MANIFEST
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "tool": f"ardt-devcontainers {__version__}",
                "profile": render.profile.name,
                "host": render.host.kind,
                "base_image": render.base_image,
                "ardt_source": render.ardt_source,
                "generated": manifest,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    result.written = to_write
    if force:
        result.conflicts = []
    return result


GITIGNORE_ENTRIES = (f"{DEVCONTAINER_DIR}/", CPP_PROPERTIES)
"""What the render occupies. The whole of ``.devcontainer/``, but only the one
generated file under ``.vscode/`` — a repo may keep its own launch.json there."""

_GITIGNORE_NOTE = "# generated by `ardt dev sync` — machine-owned, never committed"


def _gitignore_entries(root: Path) -> set[str]:
    path = root / ".gitignore"
    if not path.is_file():
        return set()
    return {line.strip().rstrip("/") for line in path.read_text(encoding="utf-8").splitlines()}


def missing_gitignore_entries(root: Path) -> list[str]:
    """The render paths ``.gitignore`` does not exclude yet."""
    present = _gitignore_entries(root)
    return [entry for entry in GITIGNORE_ENTRIES if entry.rstrip("/") not in present]


def is_gitignored(root: Path) -> bool:
    """True when ``.gitignore`` already excludes the whole render."""
    return not missing_gitignore_entries(root)


def ensure_gitignored(root: Path) -> list[str]:
    """Add the render's paths to the repo's ``.gitignore``. Returns what it added."""
    missing = missing_gitignore_entries(root)
    if not missing:
        return []
    path = root / ".gitignore"
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    prefix = "" if existing.endswith("\n") or not existing else "\n"
    added = "".join(f"{entry}\n" for entry in missing)
    path.write_text(f"{existing}{prefix}\n{_GITIGNORE_NOTE}\n{added}", encoding="utf-8")
    return missing
