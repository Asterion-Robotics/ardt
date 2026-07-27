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

"""ardt-doc-tasks — documentation as an in-env task: ``ardt doc build``.

Sphinx drives everything; Doxygen (via breathe) supplies the C++ API, an
ardt-shipped extension renders ROS 2 interface files, and the whole extension
set + theme live in :mod:`ardt_doc_tasks.preset` so a repo's ``conf.py`` is
three lines. The task builds ONE version from the working tree — version
aggregation, PDF and Pages publishing are the docs pipeline's job (two-plane
rule), which runs this same task per ref.
"""

from __future__ import annotations

from ardt_core.version import installed

ARDT_PLUGIN_API = 1
ARDT_CONFIG_SECTION = "tasks"
"""Explicit config-section claim: package names group by theme, sections by plane."""

__version__ = installed("ardt-doc-tasks")
