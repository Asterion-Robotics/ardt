"""The Context: built once per invocation, injected everywhere.

Pipelines and tasks read the *same* object. That is what makes "what version is
this" and "am I on a tag" resolve identically in both planes — there is one
implementation, not two that drift.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

from . import ci as ci_module
from . import config as config_module
from . import git as git_module
from . import version as version_module
from .ci import CIInfo
from .config import ArdtConfig, ConfigSource
from .console import Console
from .errors import ConfigError
from .git import GitInfo
from .plugins import Registry, discover
from .runner import Runner


def _empty_dict() -> dict[str, object]:
    """A typed empty dict — bare ``dict`` as a default_factory infers Unknown."""
    return {}


@dataclass
class Context:
    """Everything a command needs to know about where and how it is running."""

    project_root: Path
    cfg: ArdtConfig
    config_source: ConfigSource
    git: GitInfo
    ci: CIInfo
    console: Console
    runner: Runner
    registry: Registry
    dry_run: bool = False
    publish: bool = False
    json_output: bool = False
    _emitted: dict[str, object] = field(default_factory=_empty_dict, repr=False)

    @classmethod
    def build(
        cls,
        cwd: Path | None = None,
        *,
        dry_run: bool = False,
        publish: bool = False,
        json_output: bool = False,
        verbose: int = 0,
        registry: Registry | None = None,
    ) -> Context:
        """Assemble the context. The only place the pieces are wired together."""
        cwd = (cwd or Path.cwd()).resolve()
        root = config_module.find_project_root(cwd)
        cfg, source = config_module.load(root)

        ci = ci_module.detect()
        console = Console(ci, verbose=verbose)
        plugin_registry = registry if registry is not None else discover()

        _report_plugin_problems(console, plugin_registry)
        _check_sections(console, cfg, plugin_registry)

        return cls(
            project_root=root,
            cfg=cfg,
            config_source=source,
            git=git_module.collect(root),
            ci=ci,
            console=console,
            runner=Runner(console, dry_run=dry_run, cwd=root),
            registry=plugin_registry,
            dry_run=dry_run,
            publish=publish,
            json_output=json_output,
        )

    @property
    def project(self) -> str:
        """The project name: ``project.name`` from config, else the root directory name."""
        return self.cfg.project.name or self.project_root.name

    @cached_property
    def version(self) -> str:
        """The version of the working tree, per the single tag policy."""
        return version_module.compute(self.git)

    @property
    def is_release(self) -> bool:
        """True on an exact tag off a clean tree — the only publishable state."""
        return version_module.is_release(self.version)

    def emit(self, **values: object) -> None:
        """Contribute to the ``--json`` result envelope (digests, report paths…)."""
        self._emitted.update(values)

    @property
    def emitted(self) -> dict[str, object]:
        return dict(self._emitted)

    def describe(self) -> dict[str, object]:
        """The full context dump behind ``ardt info``."""
        return {
            "project": self.project,
            "project_root": str(self.project_root),
            "version": self.version,
            "is_release": self.is_release,
            "config": {
                "kind": self.config_source.kind,
                "path": str(self.config_source.path) if self.config_source.path else None,
            },
            "git": {
                "is_repo": self.git.is_repo,
                "branch": self.git.branch,
                "sha": self.git.sha,
                "tag": self.git.tag,
                "last_tag": self.git.last_tag,
                "commits_since_tag": self.git.commits_since_tag,
                "dirty": self.git.dirty,
            },
            "ci": self.ci.redacted(),
            "plugins": [
                {"name": p.name, "version": p.version, "api": p.api} for p in self.registry.plugins
            ],
        }


def _report_plugin_problems(console: Console, registry: Registry) -> None:
    for problem in registry.problems:
        console.warn(f"plugin `{problem.name}` not loaded: {problem.reason}")


def _check_sections(console: Console, cfg: ArdtConfig, registry: Registry) -> None:
    """Unknown sections are errors; sections of uninstalled known plugins are warnings."""
    fatal, dormant = cfg.unknown_sections(registry.sections)
    for name in dormant:
        console.warn(f"config section `{name}:` ignored — no plugin installed that claims it")
    if fatal:
        listed = ", ".join(f"`{name}:`" for name in fatal)
        raise ConfigError(
            f"unknown config section(s): {listed}",
            hint="check the spelling, or install the plugin that owns the section",
        )
