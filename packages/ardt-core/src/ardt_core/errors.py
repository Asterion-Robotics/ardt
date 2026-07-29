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

"""Error types.

Expected failures (bad config, missing tool, red tests) must exit non-zero with a
one-line diagnosis and never a traceback. Everything raised deliberately by ardt
derives from :class:`ArdtError`; anything else escaping to the CLI is a bug and is
allowed to print its traceback.
"""

from __future__ import annotations


class ArdtError(Exception):
    """Base class for expected, user-facing failures.

    The message is the one-line diagnosis printed to stderr. ``hint`` is an
    optional second line suggesting the fix.
    """

    exit_code = 1

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


class ConfigError(ArdtError):
    """The repo's ``ardt.yaml`` (or ``[tool.ardt]``) is missing, malformed or unknown."""


class RunnerError(ArdtError):
    """A subprocess exited non-zero."""

    def __init__(
        self,
        message: str,
        *,
        command: list[str],
        returncode: int,
        tail: str = "",
        hint: str | None = None,
    ) -> None:
        super().__init__(message, hint=hint)
        self.command = command
        self.returncode = returncode
        self.tail = tail


class ToolNotFoundError(ArdtError):
    """A required external tool (colcon, rosdep, vcs, git…) is not on PATH."""
