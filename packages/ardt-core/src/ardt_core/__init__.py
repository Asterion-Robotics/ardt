"""ardt — one small core, everything else a plugin.

Two execution planes, never mixed (01 §1):

* **tasks** run in whatever environment invokes them (dev shell, container, CI job);
* **pipelines** orchestrate environments (containers, registries, services) via Dagger.

Pipelines call tasks inside containers; tasks never call pipelines. Core knows
about neither ROS nor Dagger — installing it never drags in an engine.
"""

from __future__ import annotations

from .ci import CIInfo, Platform
from .config import ArdtConfig
from .console import Console
from .context import Context
from .dist import ARDT_GIT, DistConfig, ModulePin
from .errors import (
    ArdtError,
    ConfigError,
    PluginError,
    RunnerError,
    ToolNotFoundError,
)
from .git import GitInfo
from .plugins import ARDT_PLUGIN_API, Plugin, Registry
from .runner import Result, Runner
from .version import installed

__version__ = installed("ardt-core")

__all__ = [
    "ARDT_GIT",
    "ARDT_PLUGIN_API",
    "ArdtConfig",
    "ArdtError",
    "CIInfo",
    "ConfigError",
    "Console",
    "Context",
    "DistConfig",
    "GitInfo",
    "ModulePin",
    "Platform",
    "Plugin",
    "PluginError",
    "Registry",
    "Result",
    "Runner",
    "RunnerError",
    "ToolNotFoundError",
    "__version__",
]
