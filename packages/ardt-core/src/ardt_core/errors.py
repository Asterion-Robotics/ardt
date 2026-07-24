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


class PluginError(ArdtError):
    """A plugin could not be loaded, or declares an incompatible API version."""


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
