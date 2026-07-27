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

"""The ardt sphinx preset: the whole ``conf.py`` except what is truly yours.

A repo's ``conf.py`` is three lines::

    from ardt_doc_tasks.preset import *  # noqa: F403

    project = "my_project"

Everything set here is a *default* — ``conf.py`` executes top to bottom, so
anything assigned after the import wins (swap ``html_theme``, extend
``extensions`` / ``autodoc_mock_imports``, …). Updating a theme or an
extension for every repo is one MR in this package.

Conventions relied on:

* the project root is found by walking up from the sphinx working directory
  to the first ``ardt.yaml``/``.git`` (core's own root discovery — sphinx
  executes ``conf.py`` from the conf directory, so cwd alone is unreliable);
* ament_python packages live in ``<root>/<pkg>/setup.py`` — their directories
  join ``sys.path`` so autodoc imports them without a colcon build (ROS
  runtime imports are mocked via ``autodoc_mock_imports``).
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

from ardt_core.config import find_project_root as _find_project_root
from ardt_doc_tasks.config import DOC_OUTPUT as _DOC_OUTPUT

_ROOT = _find_project_root(_Path.cwd())

# ament_python packages become importable for autodoc, uninstalled.
for _setup in sorted(_ROOT.glob("*/setup.py")):
    _sys.path.insert(0, str(_setup.parent))

project = _ROOT.name
"""Default project name; repos override it after the import."""

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
    "sphinx.ext.mathjax",
    "sphinxcontrib.mermaid",
    "breathe",
    "ardt_doc_tasks.sphinx_ext",
]

source_suffix = {".rst": "restructuredtext", ".md": "markdown"}
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

myst_enable_extensions = ["colon_fence", "dollarmath"]

# ROS runtime never needs to be importable to build docs.
autodoc_mock_imports = ["rclpy", "rclcpp"]
autodoc_member_order = "bysource"
autodoc_typehints = "description"

# The C++ API arrives as doxygen XML at the fixed task convention; missing XML
# only fails pages that actually use a doxygen directive.
breathe_projects = {"ardt": str(_ROOT / _DOC_OUTPUT / "doxygen" / "xml")}
breathe_default_project = "ardt"

intersphinx_mapping: dict[str, tuple[str, None]] = {}

# RTD-style navigation: the left sidebar is the full toctree, in-page section
# titles included — each interface/class lands in the tree. pydata-sphinx-theme
# stays installed for repos that prefer it (`html_theme = "pydata_sphinx_theme"`
# after the import); the future docs pipeline's version switcher feeds either
# (pydata natively, rtd via a small flyout template reading the same JSON).
html_theme = "sphinx_rtd_theme"
html_theme_options: dict[str, object] = {
    "navigation_depth": 4,
    "collapse_navigation": False,
}
