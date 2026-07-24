"""ardt pipelines for ROS 2 repos.

The domain plugin for the "ROS 2 workspace" repo type: the ``ros-ci`` pipeline
and the ``ros2`` image recipe it renders. Builds on :mod:`ardt_pipelines` (the
generic Dagger plane) and registers through the standard ``ardt.pipelines``
entry point — nothing here is special-cased by the machinery.
"""

from __future__ import annotations

from ardt_core.version import installed

ARDT_PLUGIN_API = 1
ARDT_CONFIG_SECTION = "pipelines"
"""Explicit config-section claim: package names group by theme, sections by plane."""

__version__ = installed("ardt-ros-pipelines")
