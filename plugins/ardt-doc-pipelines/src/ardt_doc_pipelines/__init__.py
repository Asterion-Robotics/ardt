"""ardt-doc-pipelines — the docs pipeline plane: ``ardt pipe run docs-ci``.

Builds the documentation site in containers (parity: the same ``ardt doc
build`` task a dev runs, inside a pinned builder), one build per version —
the working tree plus configured branches/tag globs from git history — and
assembles them under ``public/`` with a ``versions.json`` and a root
redirect, ready for GitLab/GitHub Pages.
"""

from __future__ import annotations

ARDT_PLUGIN_API = 1
ARDT_CONFIG_SECTION = "pipelines"
"""Explicit config-section claim: package names group by theme, sections by plane."""

__version__ = "0.0.0"
