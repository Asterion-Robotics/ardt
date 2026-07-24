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
