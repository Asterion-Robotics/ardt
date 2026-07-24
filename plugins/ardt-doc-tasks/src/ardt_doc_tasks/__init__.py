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
