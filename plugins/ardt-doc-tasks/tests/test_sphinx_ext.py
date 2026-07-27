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

"""sphinx_ext: what the extension registers with sphinx — no build required."""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any, cast

from ardt_doc_tasks import sphinx_ext


class FakeApp:
    """Just enough Sphinx application to record what ``setup()`` asks for."""

    def __init__(self) -> None:
        self.config = SimpleNamespace(html_static_path=[])
        self.directives: list[str] = []
        self.handlers: dict[str, Callable[[Any], None]] = {}
        self.js_files: list[str] = []

    def add_directive(self, name: str, _cls: object) -> None:
        self.directives.append(name)

    def connect(self, event: str, handler: Callable[[Any], None]) -> None:
        self.handlers[event] = handler

    def add_js_file(self, name: str) -> None:
        self.js_files.append(name)


class TestVersionFlyout:
    def test_the_asset_ships_inside_the_package(self) -> None:
        # Installed from a wheel there is no source tree to fall back on.
        assert (sphinx_ext.STATIC_DIR / sphinx_ext.VERSION_FLYOUT).is_file()

    def test_setup_registers_the_directive_and_the_script(self) -> None:
        app = FakeApp()
        sphinx_ext.setup(cast(Any, app))
        assert app.directives == ["ros2-interfaces"]
        assert app.js_files == [sphinx_ext.VERSION_FLYOUT]

    def test_static_dir_is_appended_so_a_repo_of_its_own_wins(self) -> None:
        app = FakeApp()
        app.config.html_static_path = ["_static"]
        sphinx_ext.setup(cast(Any, app))
        app.handlers["builder-inited"](app)
        assert app.config.html_static_path == ["_static", str(sphinx_ext.STATIC_DIR)]
