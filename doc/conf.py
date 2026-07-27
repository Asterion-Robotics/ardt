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

"""Sphinx configuration for the ardt documentation — the 3-line preset contract.

Everything the toolchain decides (theme, extension set, myst options, breathe
wiring, the ``ros2-interfaces`` directive) comes from
:mod:`ardt_doc_tasks.preset`; only what is genuinely this repo's is set below.

The Python API pages autodoc the **installed** ardt distributions: ``ardt doc
build`` runs sphinx as ``sys.executable -m sphinx``, so whatever ``ardt_*``
packages live in that environment are importable here. Build from the workspace
venv (all seven packages, editable) to document the working tree.
"""

from __future__ import annotations

import importlib
import pkgutil

from ardt_doc_tasks.preset import *  # noqa: F403

project = "ardt"
author = "Asterion Robotics"

# The house style: a plain sphinx extension, pinned for the docs builder in
# `pipelines.docs_ci.pip_packages`. Rebound rather than appended — the star
# import above binds the preset's own list, so `.append()` would mutate it.
extensions = [*extensions, "asterion_sphinx_style"]  # noqa: F405

# --- autodoc/pydantic ordering hazard -------------------------------------
#
# Sphinx's autodoc merges a class's *source-level* annotations into the live
# class object, and pydantic declares `__pydantic_extra__: Dict[str, Any] | None`
# under `if TYPE_CHECKING:`. The moment autodoc documents a BaseModel subclass,
# that annotation becomes real on `pydantic.BaseModel`, and every model built
# **after** that point with `extra="allow"` dies with
# `PydanticSchemaGenerationError: the type annotation for __pydantic_extra__
# must be dict[str, ...]` — which autodoc reports as "failed to import".
#
# Models built *before* autodoc runs are unaffected, so importing every module
# we document, here, sidesteps it entirely.
ARDT_PACKAGES = (
    "ardt_core",
    "ardt_pipelines",
    "ardt_dev",
    "ardt_ros_tasks",
    "ardt_ros_pipelines",
    "ardt_doc_tasks",
    "ardt_doc_pipelines",
)

for _name in ARDT_PACKAGES:
    _package = importlib.import_module(_name)
    for _module in pkgutil.iter_modules(_package.__path__, f"{_name}."):
        importlib.import_module(_module.name)

# Autodoc renders bare type names from annotations (`type[ModelT]`) as *fuzzy*
# python cross-references. With seven packages in one inventory those collide
# with same-named attributes elsewhere (`interfaces.Field_.type`), and sphinx
# warns — fatal under `tasks.doc.strict`. Suppression is the only lever sphinx
# offers here, and it costs little: outside nitpicky mode, `ref.python` carries
# ambiguity warnings only, never unresolved-reference ones.
suppress_warnings = ["ref.python"]
