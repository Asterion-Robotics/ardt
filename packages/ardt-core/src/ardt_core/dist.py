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
        ardt-aos:         # out-of-monorepo module: its own address + pin
          git: git+https://code.example.com/ardt-aos.git
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


def subdirectory(module: str) -> str:
    """A first-party module's path inside the monorepo (platform vs plugin)."""
    root = "packages" if module in _PACKAGES else "plugins"
    return f"{root}/{module}"


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

    def requirement(self, module: str) -> str:
        """The PEP 508 requirement string installing ``module`` in an image."""
        pin = self.modules.get(module, ModulePin())
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
