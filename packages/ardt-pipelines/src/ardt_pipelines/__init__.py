"""ardt pipelines — the Dagger plane.

The one rule that contains Dagger churn (02): **all Dagger imports live in this
package and in plugin ``pipelines`` modules — tasks and core never import it.**
Pipelines orchestrate environments (containers, registries, services); the build
logic itself stays in tasks, which pipelines run *inside* containers.
"""

from __future__ import annotations

from .registry import Param, PipelineDef, collect, pipeline

ARDT_PLUGIN_API = 1

__version__ = "0.0.0"

__all__ = [
    "ARDT_PLUGIN_API",
    "Param",
    "PipelineDef",
    "__version__",
    "collect",
    "pipeline",
]
