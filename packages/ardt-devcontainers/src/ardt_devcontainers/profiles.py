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

"""Dev profiles — the per-repo-type knowledge, expressed as data.

A profile answers: which base image, which extra apt packages, which ardt
modules the container needs, what to run once the container exists, and which
editor extensions make the language work. It is deliberately *data*: the engine
imports no ROS package and no pipeline plugin, so a laptop install stays tiny.

**This module is the contract profile plugins build against.** A profile
distribution depends on ``ardt-devcontainers``, builds one :class:`Profile`, and
registers it under ``ardt.dev_profiles``:

.. code-block:: toml

    [project.entry-points."ardt.dev_profiles"]
    ros2 = "ardt_ros_dev.profile:ROS2"

The entry-point name is the profile name — what a repo writes in ``dev.profile``
— and two plugins claiming the same one is an error, not a silent last-wins.
Loading happens on demand (:func:`profiles`), narrowed to this one group, so
``ardt dev sync`` never imports a pipeline module.

:::{admonition} Provisional API
:class: warning

The :class:`Profile` fields were extracted from a single profile. Until a second
one exists to argue with, this contract may change in a **minor** release; the
``ARDT_PLUGIN_API`` version is what will be bumped when it does. Out-of-tree
profiles should pin ``ardt-devcontainers`` accordingly.
:::
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ardt_core.errors import ArdtError
from ardt_core.plugins import DEV_PROFILES_GROUP, Registry

DISTRO = "@DISTRO@"
"""Token replaced with the repo's ROS distro at render time."""

CXX_STANDARD = "@CXX_STANDARD@"
"""Token replaced with :func:`cxx_standard` for the repo's ROS distro."""

CXX_STANDARDS: dict[str, str] = {
    "humble": "c++17",
    "jazzy": "c++17",
    "kilted": "c++17",
    "lyrical": "c++20",
    "rolling": "c++20",
}
"""What each distro targets, per its own "Code style and language versions" page
(``docs.ros.org/en/<distro>/The-ROS2-Project/Contributing/Code-Style-Language-Versions``):
c++20 from lyrical and rolling on, c++17 before. Note REP 2000's "minimum
language requirements" tables still say C++17 for rolling — that page is the
one that tracks the switch, so it is the one quoted here. A line per distro."""

CXX_STANDARD_DEFAULT = "c++20"
"""For a distro not in the table. The newest entry's value, not the oldest: an
unknown distro is far likelier to be a future one than a forgotten past one."""


def cxx_standard(distro: str) -> str:
    """The C++ standard editor tooling should assume for ``distro``."""
    return CXX_STANDARDS.get(distro, CXX_STANDARD_DEFAULT)


@dataclass(frozen=True)
class Profile:
    """Everything that differs between one kind of repo and another."""

    name: str
    summary: str
    distribution: str
    """The profile plugin's own distribution name (``ardt-ros-dev``).

    Installed in the container alongside the engine, because the in-container
    commands (``ardt dev bootstrap``, ``ardt dev profiles``) have to resolve
    this very profile — the container renders from the same ``ardt:`` pin the
    host does, so the profile has to be *in* the pin."""
    dockerfile: str
    """Template file name, resolved from :attr:`templates_package`."""
    templates_package: str
    """Importable package holding :attr:`dockerfile`, e.g.
    ``ardt_ros_dev.templates``. An anchor, not a path: the template ships as
    package data and is read through ``importlib.resources``, so it works from
    a wheel, a zip, or an editable checkout alike."""
    default_base_image: str
    """Used when the repo pins no ``pipelines.ros_ci.builder`` and no
    ``dev.base_image``. May contain the :data:`DISTRO` token."""
    ardt_modules: tuple[str, ...]
    """Further ardt distributions installed in the container, on top of the
    engine and :attr:`distribution`. The ROS profile names exactly
    ``ardt_ros_pipelines.recipes.ARDT_MODULES`` — the same modules CI's build
    stage installs, from the same ``ardt:`` pin."""
    apt_groups: tuple[tuple[str, tuple[str, ...]], ...]
    """``(label, packages)`` — labels become comments in the rendered recipe, so
    a human debugging the image can see why each group is there."""
    bootstrap: tuple[tuple[str, ...], ...]
    """Commands ``ardt dev bootstrap`` runs inside the container, in order."""
    extensions: tuple[str, ...]
    settings: dict[str, object] = field(default_factory=dict)
    container_env: dict[str, str] = field(default_factory=dict)
    cpp_properties: dict[str, object] | None = None
    """The single ``configurations[]`` entry of ``.vscode/c_cpp_properties.json``,
    or None for a profile with no C/C++ in it. Strings may carry :data:`DISTRO`.

    Unlike :attr:`settings`, this cannot ride along in ``devcontainer.json``:
    cpptools only reads its configuration from that path in the workspace."""


def profiles(registry: Registry) -> dict[str, Profile]:
    """Every profile installed plugins contribute, keyed by name.

    The deferred load is narrowed to ``ardt.dev_profiles``: rendering a
    devcontainer must not import a pipeline module, which would pull dagger onto
    a laptop for a command that never touches it.

    An entry point aimed at something that is not a :class:`Profile` is refused
    loudly rather than skipped, and a name two plugins both claim is an error —
    ``dev.profile: ros2`` must never be ambiguous. Same contract, and the same
    reasons, as ``ardt_pipelines.collect``.
    """
    registry.load_deferred([DEV_PROFILES_GROUP])
    found: dict[str, Profile] = {}
    owners: dict[str, str] = {}
    for plugin in registry.plugins:
        for name, loaded in plugin.dev_profiles.items():
            if not isinstance(loaded, Profile):
                raise ArdtError(
                    f"ardt.dev_profiles entry point `{name}` (from `{plugin.name}`) must "
                    f"point at a Profile, got {type(loaded).__name__}",
                    hint="a profile plugin exports one ardt_devcontainers.profiles.Profile",
                )
            if name in found:
                raise ArdtError(
                    f"dev profile `{name}` is provided by both `{owners[name]}` "
                    f"and `{plugin.name}`",
                    hint="uninstall one of them, or ask its author to rename the profile",
                )
            found[name] = loaded
            owners[name] = plugin.name
    return found


def profile(name: str, registry: Registry) -> Profile:
    """Look up a profile, or fail with the list of the ones that exist."""
    installed = profiles(registry)
    found = installed.get(name)
    if found is None:
        known = ", ".join(sorted(installed)) or "none installed"
        raise ArdtError(
            f"unknown dev profile `{name}`",
            hint=(
                f"set `dev.profile:` to one of: {known}"
                if installed
                else "no profile plugin is installed — `pip install ardt-ros-dev` for ROS 2 repos"
            ),
        )
    return found
