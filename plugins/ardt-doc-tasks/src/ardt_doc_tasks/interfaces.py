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

"""ROS 2 interface files (``.msg``/``.srv``/``.action``) → structured data → RST.

Pure text parsing — no built workspace, no rosidl import: fields, defaults,
constants and the comments that document them are all in the files themselves.
Nothing here may depend on sphinx; the directive front lives in
:mod:`ardt_doc_tasks.sphinx_ext`.

Comment conventions honored (the ROS ones): a comment block immediately above
a field documents that field; an inline ``#`` documents its line; a comment
block at the very top of the file, separated from the first field by a blank
line, describes the interface itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

KIND_SECTIONS: dict[str, tuple[str, ...]] = {
    "msg": ("",),
    "srv": ("Request", "Response"),
    "action": ("Goal", "Result", "Feedback"),
}
"""Section labels per interface kind, in ``---``-separator order."""


@dataclass(frozen=True)
class Field_:
    """One field line: ``type name [default]``."""

    type: str
    name: str
    default: str | None
    comment: str


@dataclass(frozen=True)
class Constant:
    """One constant line: ``type NAME=value``."""

    type: str
    name: str
    value: str
    comment: str


@dataclass
class Section:
    """One ``---``-separated part of an interface."""

    label: str
    fields: list[Field_] = field(default_factory=list)
    constants: list[Constant] = field(default_factory=list)


@dataclass
class Interface:
    """A parsed interface file."""

    name: str
    kind: str
    description: str
    sections: list[Section]


def parse(path: Path) -> Interface:
    """Parse one interface file. The kind comes from the suffix."""
    kind = path.suffix.lstrip(".")
    labels = KIND_SECTIONS[kind]
    raw = path.read_text(encoding="utf-8")
    parts = _split_sections(raw)

    description = ""
    sections: list[Section] = []
    for index, label in enumerate(labels):
        lines = parts[index] if index < len(parts) else []
        section, leading = _parse_section(label, lines)
        if index == 0:
            description = leading
        sections.append(section)
    return Interface(name=path.stem, kind=kind, description=description, sections=sections)


def _split_sections(raw: str) -> list[list[str]]:
    parts: list[list[str]] = [[]]
    for line in raw.splitlines():
        if line.strip() == "---":
            parts.append([])
        else:
            parts[-1].append(line)
    return parts


def _parse_section(label: str, lines: list[str]) -> tuple[Section, str]:
    """Parse one section; returns it plus the file-description comment block."""
    section = Section(label=label)
    description = ""
    pending: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            # A blank line detaches the pending comments; before any content
            # they were the interface description.
            if pending and not section.fields and not section.constants and not description:
                description = " ".join(pending)
            pending = []
            continue
        if stripped.startswith("#"):
            pending.append(stripped.lstrip("#").strip())
            continue

        content, _, inline = stripped.partition("#")
        comment = " ".join((*pending, inline.strip())).strip()
        pending = []
        parsed = _parse_line(content.strip(), comment)
        if isinstance(parsed, Constant):
            section.constants.append(parsed)
        elif parsed is not None:
            section.fields.append(parsed)

    return section, description


def _parse_line(content: str, comment: str) -> Field_ | Constant | None:
    parts = content.split(maxsplit=1)
    if len(parts) < 2:
        return None
    type_, rest = parts

    name_candidate, equals, value = rest.partition("=")
    name_candidate = name_candidate.strip()
    # Constants are `TYPE NAME=VALUE` with an UPPER_CASE name (the rosidl rule);
    # anything else with an `=` is a field default edge case, kept as a field.
    if equals and name_candidate.isidentifier() and name_candidate.isupper():
        return Constant(type=type_, name=name_candidate, value=value.strip(), comment=comment)

    tokens = rest.split(maxsplit=1)
    name = tokens[0]
    default = tokens[1].strip() if len(tokens) > 1 else None
    return Field_(type=type_, name=name, default=default, comment=comment)


def find_interfaces(package_dir: Path, kinds: tuple[str, ...] | None = None) -> list[Path]:
    """Interface files of a package, in kind-then-name order, optionally filtered."""
    found: list[Path] = []
    for kind in kinds if kinds is not None else tuple(KIND_SECTIONS):
        found.extend(sorted((package_dir / kind).glob(f"*.{kind}")))
    return found


def render_package_rst(package_dir: Path, kinds: tuple[str, ...] | None = None) -> str:
    """The RST for a package's interfaces, ready for nested parsing.

    Every interface renders as a real RST *section*, so it lands in the page
    toc and in RTD-style sidebar navigation — one entry per interface.
    """
    lines: list[str] = []
    for path in find_interfaces(package_dir, kinds):
        lines.extend(_render_interface(parse(path)))
    return "\n".join(lines)


def _render_interface(interface: Interface) -> list[str]:
    title = f"{interface.name} ({interface.kind})"
    lines = [title, "=" * len(title), ""]
    if interface.description:
        lines += [interface.description, ""]
    for section in interface.sections:
        if section.label:
            lines += [f"**{section.label}**", ""]
        if section.constants:
            lines += _table(
                ("Constant", "Type", "Value", "Description"),
                [
                    (f"``{c.name}``", f"``{c.type}``", f"``{c.value}``", c.comment)
                    for c in section.constants
                ],
            )
        if section.fields:
            lines += _table(
                ("Field", "Type", "Default", "Description"),
                [
                    (
                        f"``{f.name}``",
                        f"``{f.type}``",
                        f"``{f.default}``" if f.default is not None else "—",
                        f.comment,
                    )
                    for f in section.fields
                ],
            )
        if not section.fields and not section.constants:
            lines += ["*(empty)*", ""]
    return lines


def _table(header: tuple[str, ...], rows: list[tuple[str, ...]]) -> list[str]:
    lines = [
        ".. list-table::",
        "   :header-rows: 1",
        "   :widths: 22 22 16 40",
        "",
        f"   * - {header[0]}",
        *(f"     - {h}" for h in header[1:]),
    ]
    for row in rows:
        lines.append(f"   * - {row[0]}")
        lines.extend(f"     - {cell}" for cell in row[1:])
    lines.append("")
    return lines
