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

"""Configuration: one file per repo.

``ardt.yaml`` at the project root, or a ``[tool.ardt]`` table in ``pyproject.toml``
— same model, the file wins.

Sections are namespaced per plugin (``tasks:``, ``pipelines:``, ``doc:``). Core
does not know their shape; a plugin claims its section and parses it into its own
pydantic model via :meth:`ArdtConfig.section_as`. An unknown section is an error,
*unless* it belongs to a plugin that simply is not installed here — then it is a
warning. That gives typo-safety without making core depend on its plugins.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import TypeVar, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .dist import DistConfig
from .errors import ConfigError

CONFIG_FILENAMES = ("ardt.yaml", "ardt.yml")
PYPROJECT = "pyproject.toml"

RESERVED_SECTIONS = frozenset({"tasks", "pipelines", "doc", "dev", "templates"})
"""Section names owned by first-party plugins.

Present here so that a repo configuring ``doc:`` on a machine without
``ardt-doc-tasks`` installed gets a warning, while ``docs:`` still gets an
error. Growing this set is a core release; a third-party plugin's section is
recognized only when installed.
"""

ModelT = TypeVar("ModelT", bound=BaseModel)


class ProjectConfig(BaseModel):
    """The ``project:`` section."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    """Defaults to the project root's directory name."""


class CheckConfig(BaseModel):
    """The ``check:`` section — exceptions to the ardt-shipped lint configs."""

    model_config = ConfigDict(extra="forbid")

    ignore: list[str] = Field(default_factory=list)
    clang_format: str | None = None


class ArdtConfig(BaseModel):
    """The parsed repo config. Plugin sections survive as raw data."""

    model_config = ConfigDict(extra="allow")

    project: ProjectConfig = Field(default_factory=ProjectConfig)
    check: CheckConfig = Field(default_factory=CheckConfig)
    ardt: DistConfig = Field(default_factory=DistConfig)
    """Where ardt itself installs from inside pipeline-built images
    (:mod:`.dist`). Core-owned like ``project:`` and ``check:``."""

    def section(self, name: str) -> dict[str, object]:
        """The raw mapping for a plugin section, or ``{}`` when absent."""
        extra = self.__pydantic_extra__ or {}
        value = extra.get(name)
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ConfigError(f"config section `{name}:` must be a mapping")
        return cast("dict[str, object]", value)

    def section_as(self, name: str, model: type[ModelT]) -> ModelT:
        """Parse a plugin section into the plugin's own model."""
        try:
            return model.model_validate(self.section(name))
        except ValidationError as exc:
            raise ConfigError(f"invalid `{name}:` section: {_first_error(exc)}") from exc

    def unknown_sections(self, installed: frozenset[str]) -> tuple[list[str], list[str]]:
        """Split extra sections into ``(fatal, from_uninstalled_plugins)``."""
        extra = self.__pydantic_extra__ or {}
        fatal: list[str] = []
        dormant: list[str] = []
        for name in extra:
            if name in installed:
                continue
            (dormant if name in RESERVED_SECTIONS else fatal).append(name)
        return sorted(fatal), sorted(dormant)


class ConfigSource(BaseModel):
    """Where the config came from, for ``ardt info``."""

    path: Path | None = None
    kind: str = "defaults"
    """One of ``ardt.yaml``, ``ardt.yml``, ``pyproject.toml``, ``defaults``."""


def _config_file_in(directory: Path) -> bool:
    return any((directory / filename).is_file() for filename in CONFIG_FILENAMES)


def _workspace_projects(src: Path) -> list[Path]:
    """The projects living one level under a workspace's ``src/`` dir."""
    if not src.is_dir():
        return []
    return sorted(child for child in src.iterdir() if child.is_dir() and _config_file_in(child))


def find_project_root(start: Path) -> Path:
    """Walk up from ``start`` to the first directory holding a config file or ``.git``.

    One convention on top of the walk, for the colcon workspace layout
    (``/ws/src/<repo>`` is the project, ``/ws/{build,install,log}`` the colcon
    output): a directory whose ``src/`` holds a project *is* a workspace root,
    and the project root is that ``src/<repo>``. It is what lets ``ardt build``
    run from ``/ws`` in a container or ``~/ws`` on a host, without a
    ``--project-root`` flag. Only :data:`CONFIG_FILENAMES` count as project
    markers here — a bare ``src/*/pyproject.toml`` is too common to mean "ardt
    project" on its own — and the convention is checked before ``.git`` because
    a config file is the stronger signal.

    Several projects under one ``src/`` (imported ``.repos`` deps can carry
    their own ``ardt.yaml``) is ambiguous from outside them and raises; running
    from *inside* a project resolves to that project before this rule is ever
    consulted.
    """
    start = start.resolve()
    for directory in (start, *start.parents):
        if _config_file_in(directory):
            return directory
        src = directory if directory.name == "src" else directory / "src"
        if src is not directory and _config_file_in(src):
            return src  # a repo checked out as `src` itself
        projects = _workspace_projects(src)
        if len(projects) == 1:
            return projects[0]
        if len(projects) > 1:
            listed = ", ".join(p.name for p in projects)
            raise ConfigError(
                f"several projects under {src}: {listed}",
                hint="run ardt from inside the one you mean",
            )
        if (directory / ".git").exists():
            return directory
    return start


def load(root: Path) -> tuple[ArdtConfig, ConfigSource]:
    """Load the config for a project root. Missing config is not an error."""
    for filename in CONFIG_FILENAMES:
        path = root / filename
        if path.is_file():
            return _from_yaml(path), ConfigSource(path=path, kind=filename)

    pyproject = root / PYPROJECT
    if pyproject.is_file():
        data = _tool_table(pyproject)
        if data is not None:
            return _validate(data, pyproject), ConfigSource(path=pyproject, kind=PYPROJECT)

    return ArdtConfig(), ConfigSource()


def _from_yaml(path: Path) -> ArdtConfig:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {_one_line(exc)}") from exc
    if raw is None:
        return ArdtConfig()
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} must contain a YAML mapping at the top level")
    return _validate(cast("dict[str, object]", raw), path)


def _tool_table(pyproject: Path) -> dict[str, object] | None:
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"cannot read {pyproject}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{pyproject} is not valid TOML: {_one_line(exc)}") from exc
    tool = cast("dict[str, object]", data).get("tool")
    if not isinstance(tool, dict):
        return None
    table = cast("dict[str, object]", tool).get("ardt")
    if table is None:
        return None
    if not isinstance(table, dict):
        raise ConfigError(f"{pyproject}: [tool.ardt] must be a table")
    return cast("dict[str, object]", table)


def _validate(data: dict[str, object], path: Path) -> ArdtConfig:
    try:
        return ArdtConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"{path}: {_first_error(exc)}") from exc


def _first_error(exc: ValidationError) -> str:
    error = exc.errors()[0]
    location = ".".join(str(part) for part in error["loc"]) or "<root>"
    return f"{location}: {error['msg']}"


def _one_line(exc: Exception) -> str:
    return str(exc).replace("\n", " ").strip()
