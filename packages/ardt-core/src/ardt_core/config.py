"""Configuration: one file per repo.

``ardt.yaml`` at the project root, or a ``[tool.ardt]`` table in ``pyproject.toml``
— same model, the file wins.

Sections are namespaced per plugin (``tasks:``, ``pipelines:``, ``aos:``). Core
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

RESERVED_SECTIONS = frozenset({"tasks", "pipelines", "aos", "doc", "dev", "templates"})
"""Section names owned by first-party plugins.

Present here so that a repo configuring ``aos:`` on a machine without ``ardt-aos``
installed gets a warning, while ``aoss:`` still gets an error. Growing this set is
a core release; a third-party plugin's section is recognized only when installed.
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


def find_project_root(start: Path) -> Path:
    """Walk up from ``start`` to the first directory holding a config file or ``.git``."""
    start = start.resolve()
    for directory in (start, *start.parents):
        for filename in CONFIG_FILENAMES:
            if (directory / filename).is_file():
                return directory
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
