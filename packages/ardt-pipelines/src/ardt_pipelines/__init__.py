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

"""ardt pipelines — the Dagger plane.

The one rule that contains Dagger churn (02): **all Dagger imports live in this
package and in plugin ``pipelines`` modules — tasks and core never import it.**
Pipelines orchestrate environments (containers, registries, services); the build
logic itself stays in tasks, which pipelines run *inside* containers.
"""

from __future__ import annotations

from ardt_core.version import installed

from .registry import Param, PipelineDef, collect, pipeline

ARDT_PLUGIN_API = 1
ARDT_CONFIG_SECTION = "pipelines"
"""Explicit config-section claim: package names group by theme, sections by plane."""

__version__ = installed("ardt-pipelines")

__all__ = [
    "ARDT_PLUGIN_API",
    "Param",
    "PipelineDef",
    "__version__",
    "collect",
    "pipeline",
]
