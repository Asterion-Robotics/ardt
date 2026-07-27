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

"""Dev environments: ``ardt dev`` — the inner loop's half of the two planes.

A repo's devcontainer is a *rendered artifact*, never repo content: the recipe
and the editor wiring live here as package data and update with the pinned ardt
version, exactly as the CI image recipe does in ``ardt-ros-pipelines``
``ardt dev sync`` writes them into a gitignored
``.devcontainer/`` (plus the one editor file VS Code only reads from
``.vscode/``), so no repo carries — or reviews, or drifts on — a devcontainer
file.

The invariant that gives the whole thing its point: the container a developer
works in and the image CI builds share a base image, an ardt install resolved
from the same ``ardt:`` pin, and a workspace path. ``ardt dev doctor`` fails
when they drift apart.
"""

from __future__ import annotations

from ardt_core.version import installed

ARDT_PLUGIN_API = 1
ARDT_CONFIG_SECTION = "dev"
"""Explicit config-section claim: package names group by theme, sections by plane."""

__version__ = installed("ardt-dev")
