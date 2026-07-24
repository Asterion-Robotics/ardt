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
from collections.abc import Mapping


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


def snapshot() -> Mapping[str, str]:
    """Read-only view of the environment (diagnostics only)."""
    return dict(os.environ)
