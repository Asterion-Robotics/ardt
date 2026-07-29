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

"""The only module in ardt allowed to read the process environment.

Rule: *no ``os.environ`` access outside the ``ctx.ci`` normalization module*.
The rule's intent is a single choke point, so that pipelines and tasks can never
smuggle configuration in through an env var: everything they need arrives via
``ctx.ci`` or ``ardt.yaml``. This module is that choke point; :mod:`ardt_core.ci`
consumes it, and :mod:`ardt_core.runner` uses :func:`base_environ` to seed
subprocesses. ``tests/test_no_environ_access.py`` enforces it.
"""

from __future__ import annotations

import os


def get(name: str, default: str | None = None) -> str | None:
    """Return an environment variable, or ``default`` when unset or empty."""
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value


def flag(name: str) -> bool:
    """True when the variable is set to something other than a falsy literal."""
    value = get(name)
    if value is None:
        return False
    return value.lower() not in {"0", "false", "no", "off"}


def has(name: str) -> bool:
    """True when the variable is set at all (even to an empty string)."""
    return name in os.environ


def base_environ() -> dict[str, str]:
    """A copy of the process environment, for seeding subprocesses."""
    return dict(os.environ)


def home() -> str | None:
    """The user's home directory, if the environment names one."""
    return get("HOME") or get("USERPROFILE")
