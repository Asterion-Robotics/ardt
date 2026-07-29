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

"""ardt — one small core, everything else a plugin.

Two execution planes, never mixed:

* **tasks** run in whatever environment invokes them (dev shell, container, CI job);
* **pipelines** orchestrate environments (containers, registries, services) via Dagger.

Pipelines call tasks inside containers; tasks never call pipelines. Core knows
about neither ROS nor Dagger — installing it never drags in an engine.
"""

from __future__ import annotations

from .ci import CIInfo, Platform
from .config import ArdtConfig
from .console import Console
from .context import Context
from .dist import ARDT_GIT, DistConfig, ModulePin
from .errors import (
    ArdtError,
    ConfigError,
    RunnerError,
    ToolNotFoundError,
)
from .git import GitInfo
from .plugins import ARDT_PLUGIN_API, Plugin, Registry
from .runner import Result, Runner
from .version import installed

__version__ = installed("ardt-core")

__all__ = [
    "ARDT_GIT",
    "ARDT_PLUGIN_API",
    "ArdtConfig",
    "ArdtError",
    "CIInfo",
    "ConfigError",
    "Console",
    "Context",
    "DistConfig",
    "GitInfo",
    "ModulePin",
    "Platform",
    "Plugin",
    "Registry",
    "Result",
    "Runner",
    "RunnerError",
    "ToolNotFoundError",
    "__version__",
]
