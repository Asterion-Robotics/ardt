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

"""ROS 2 workspace tasks: ``ardt deps`` / ``ardt build`` / ``ardt test``.

In-environment and engine-free by design: these run wherever they are invoked —
a dev shell, a devcontainer, or a CI container started by a pipeline. That is the
property that keeps the inner loop working without Dagger installed.
"""

from __future__ import annotations

from ardt_core.version import installed

ARDT_PLUGIN_API = 1
ARDT_CONFIG_SECTION = "tasks"
"""Explicit config-section claim: package names group by theme, sections by plane."""

__version__ = installed("ardt-ros-tasks")
