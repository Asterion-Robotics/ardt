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

"""ardt-doc-pipelines — the docs pipeline plane: ``ardt pipe run docs-ci``.

Builds the documentation site in containers (parity: the same ``ardt doc
build`` task a dev runs, inside a pinned builder), one build per version —
the working tree plus configured branches/tag globs from git history — and
assembles them under ``public/`` with a ``versions.json`` and a root
redirect, ready for GitLab/GitHub Pages.
"""

from __future__ import annotations

from ardt_core.version import installed

ARDT_PLUGIN_API = 1
ARDT_CONFIG_SECTION = "pipelines"
"""Explicit config-section claim: package names group by theme, sections by plane."""

__version__ = installed("ardt-doc-pipelines")
