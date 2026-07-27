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

"""The interface parser: pure text in, structured data and RST out."""

from __future__ import annotations

from pathlib import Path

from ardt_doc_tasks import interfaces

MSG = """\
# The demo status message.

# Current counter value.
int64 count
string state "idle"  # inline description
uint8 STATE_IDLE=0
uint8 STATE_COUNTING=1  # busy
"""

SRV = """\
int64 target
---
bool success
int64 previous  # value before the call
"""

ACTION = """\
int64 target
---
int64 final_count
---
int64 current
"""


def _write(tmp_path: Path, kind: str, name: str, content: str) -> Path:
    directory = tmp_path / kind
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.{kind}"
    path.write_text(content)
    return path


class TestParse:
    def test_msg_fields_constants_and_comments(self, tmp_path: Path) -> None:
        parsed = interfaces.parse(_write(tmp_path, "msg", "DemoStatus", MSG))
        assert parsed.kind == "msg"
        assert parsed.description == "The demo status message."
        (section,) = parsed.sections
        assert [f.name for f in section.fields] == ["count", "state"]
        assert section.fields[0].comment == "Current counter value."
        assert section.fields[1].default == '"idle"'
        assert section.fields[1].comment == "inline description"
        assert [(c.name, c.value) for c in section.constants] == [
            ("STATE_IDLE", "0"),
            ("STATE_COUNTING", "1"),
        ]
        assert section.constants[1].comment == "busy"

    def test_srv_has_request_and_response(self, tmp_path: Path) -> None:
        parsed = interfaces.parse(_write(tmp_path, "srv", "SetCounter", SRV))
        assert [s.label for s in parsed.sections] == ["Request", "Response"]
        assert parsed.sections[0].fields[0].name == "target"
        assert parsed.sections[1].fields[1].comment == "value before the call"

    def test_action_has_three_sections(self, tmp_path: Path) -> None:
        parsed = interfaces.parse(_write(tmp_path, "action", "CountTo", ACTION))
        assert [s.label for s in parsed.sections] == ["Goal", "Result", "Feedback"]
        assert parsed.sections[2].fields[0].name == "current"

    def test_missing_trailing_sections_render_empty(self, tmp_path: Path) -> None:
        parsed = interfaces.parse(_write(tmp_path, "srv", "FireAndForget", "bool go\n"))
        assert parsed.sections[1].fields == []


class TestRender:
    def test_package_rst_covers_all_kinds_as_sections(self, tmp_path: Path) -> None:
        _write(tmp_path, "msg", "DemoStatus", MSG)
        _write(tmp_path, "srv", "SetCounter", SRV)
        _write(tmp_path, "action", "CountTo", ACTION)
        rst = interfaces.render_package_rst(tmp_path)
        # real sections (title + underline), so navigation trees pick them up
        assert "DemoStatus (msg)\n================" in rst
        assert "SetCounter (srv)\n================" in rst
        assert "CountTo (action)\n================" in rst
        assert "**Request**" in rst and "**Feedback**" in rst
        assert "``STATE_IDLE``" in rst
        # fields without a default render an em dash, not `None`
        assert "None" not in rst

    def test_kinds_filter_restricts_the_output(self, tmp_path: Path) -> None:
        _write(tmp_path, "msg", "DemoStatus", MSG)
        _write(tmp_path, "srv", "SetCounter", SRV)
        rst = interfaces.render_package_rst(tmp_path, kinds=("srv",))
        assert "SetCounter (srv)" in rst
        assert "DemoStatus" not in rst
