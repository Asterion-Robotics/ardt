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

"""The ``ros2`` dev profile: what a ROS 2 workspace needs in its devcontainer.

Everything ROS-shaped about ``ardt dev``, and nothing else. The engine
(``ardt-devcontainers``) renders and drives; this distribution answers *what to
render for a ROS 2 repo* — the base image, the apt sets, the colcon-aware
bootstrap steps, the C/C++ editor wiring — as one
:class:`~ardt_devcontainers.profiles.Profile` registered under
``ardt.dev_profiles``.

It ships no command and no code path of its own: the profile is data, read by
the engine on the host and again inside the container (which is why the
container installs this distribution too, from the repo's own ``ardt:`` pin).
"""

from __future__ import annotations

from ardt_core.version import installed

ARDT_PLUGIN_API = 1
ARDT_CONFIG_SECTION = "dev"
"""The ``dev:`` plane, shared with the engine — sections group by plane, and
this plugin has no configuration surface of its own. Without the claim the
fallback would derive ``ros:`` from the distribution name, a section nothing
reads."""

__version__ = installed("ardt-ros-dev")
