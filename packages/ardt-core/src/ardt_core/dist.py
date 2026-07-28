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

"""Where ardt distributions install from — the ``ardt:`` config section.

Pipelines install ardt *inside* the images they build (the two-plane rule: the
same tasks run in the container as on a dev machine). Every pipeline used to
carry its own copy of the git address and module→subdirectory knowledge; this
module is the single shared implementation.

The section pins the whole toolchain per repo:

.. code-block:: yaml

    ardt:
      git: git+https://github.com/Asterion-Robotics/ardt.git  # the default
      version: v0.3.0     # git rev every monorepo module installs at
      modules:
        ardt-acme:        # out-of-monorepo module: its own address + pin
          git: git+https://code.example.com/ardt-acme.git
          version: v1.2.0

Each pipeline declares *which* modules its images need (``ardt-core`` +
``ardt-ros-tasks`` for ros-ci, …); this section answers *where from* and *at
what version*. Without a ``version`` the install tracks HEAD — fine for
development, but CI repos should pin: the rendered recipe is only reproducible
when the ardt inside it is.
"""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict, Field

ARDT_GIT = "git+https://github.com/Asterion-Robotics/ardt.git"
"""The ardt monorepo — the default source of every first-party module."""

_PACKAGES = frozenset({"ardt-core", "ardt-pipelines"})
"""Monorepo modules living under ``packages/``; everything else is a plugin."""


def base_name(module: str) -> str:
    """A requirement's distribution name, extras stripped (``a[b]`` -> ``a``)."""
    return module.partition("[")[0]


def extras(module: str) -> str:
    """A requirement's bracketed extras, or ``""`` (``a[b]`` -> ``[b]``)."""
    _, bracket, rest = module.partition("[")
    return f"{bracket}{rest}" if bracket else ""


def subdirectory(module: str) -> str:
    """A first-party module's path inside the monorepo (platform vs plugin)."""
    name = base_name(module)
    root = "packages" if name in _PACKAGES else "plugins"
    return f"{root}/{name}"


def local_requirement(module: str, root: str) -> str:
    """The pip argument installing ``module`` from a monorepo checkout at ``root``.

    The counterpart of :meth:`DistConfig.requirement` for images that mount the
    source instead of cloning it. Extras stay on the path, where pip wants them
    (``/src/packages/ardt-core[testing]``); the *directory* never carries them.
    """
    return f"{root}/{subdirectory(module)}{extras(module)}"


class ModulePin(BaseModel):
    """One module's override: its own source, rev, or in-repo location."""

    model_config = ConfigDict(extra="forbid")

    git: str | None = None
    """The module's own git address (pip VCS form, ``git+https://…``). None
    means the monorepo ``ardt.git``."""
    version: str | None = None
    """Git rev (tag, branch, sha) to install at. For a monorepo module, None
    falls back to the section-wide ``version``; for an external ``git``, the
    section-wide pin does not apply (it pins a different repository)."""
    subdirectory: str | None = None
    """Path of the package inside its repository. None derives the monorepo
    layout for first-party modules, or the repository root for external ones."""


class DistConfig(BaseModel):
    """The ``ardt:`` section — which ardt this repo's pipelines install."""

    model_config = ConfigDict(extra="forbid")

    git: str = ARDT_GIT
    """Git address of the ardt monorepo (pip VCS form)."""
    version: str | None = None
    """Git rev every monorepo module installs at. None tracks HEAD."""
    modules: dict[str, ModulePin] = Field(default_factory=dict)
    """Per-module overrides, keyed by distribution name."""
    install_extras: list[str] = Field(default_factory=list)
    """Modules install.sh adds to its default bundle. A bootstrap knob only:
    pipelines and dev profiles declare their own module sets and ignore it."""
    install_skip: list[str] = Field(default_factory=list)
    """Modules install.sh removes from its default bundle (before extras
    apply). Same scope as ``install_extras``: the bootstrap installer only."""

    def requirement(self, module: str) -> str:
        """The PEP 508 requirement string installing ``module`` in an image.

        ``module`` may carry extras; they ride along in the name field, which is
        exactly where PEP 508 puts them, and the pin is looked up without them.
        """
        pin = self.modules.get(base_name(module), ModulePin())
        if pin.git is None:
            source = self.git
            version = pin.version or self.version
            sub = pin.subdirectory or subdirectory(module)
        else:
            source = pin.git
            version = pin.version
            sub = pin.subdirectory

        url = source
        if version:
            url += f"@{version}"
        if sub:
            url += f"#subdirectory={sub}"
        return f"{module} @ {url}"

    def requirements(self, modules: Iterable[str]) -> tuple[str, ...]:
        """Requirement strings for the modules a pipeline's image needs."""
        return tuple(self.requirement(module) for module in modules)
