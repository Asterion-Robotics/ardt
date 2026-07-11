"""Shipped-image recipes, owned by the pipeline plugin (ci_tools 02 §7.2/§7.3-4).

The Dockerfile for a repo *type* is common to all repos of that type, so it
lives here as package data and updates by bumping the pinned ardt version —
never by editing files across repos. **Repos contain no Dockerfile.** The one
sanctioned exception: a repo that needs local image content (kernel modules,
vendor drivers…) provides a *base extension* — a small ``base.Dockerfile``
starting ``FROM ${BASE_IMAGE}`` — which the render splices in as a stage
between the configured base and the runtime image.

The recipe runs the ardt tasks themselves as build stages (deps → build → test
→ stage artefacts → runtime image), so *building the image is the CI run*.
Rule 7.3-4 keeps the audit/escape-hatch story intact: the rendered Dockerfile
is exported on every run, so ``docker build -f <rendered> .`` works with no
ardt installed on the machine.
"""

from __future__ import annotations

import json
import re
from importlib import resources
from pathlib import Path

from ardt_core.errors import ArdtError
from ardt_pipelines_ros import __version__

RENDERED_NAME = "Dockerfile.rendered"
"""The rendered recipe's filename, inside the build context and in the export."""

BUILD_TARGET = "build"
RUNTIME_TARGET = "runtime"
RESULTS_DIR = "/results"
"""Where the build stage places JUnit XMLs (fixed contract with the pipeline)."""

BASE_EXT_STAGE = "base-ext"
"""Stage name given to a repo's base extension in the rendered recipe."""

LOCAL_ARDT_DIR = ".ardt-src"
"""Context subdirectory the pipeline injects a local ardt checkout into."""

_GIT_INSTALL = """\
RUN python3 -m pip install --break-system-packages \\
      "ardt-core @ {source}#subdirectory=packages/ardt-core" \\
      "ardt-tasks-ros @ {source}#subdirectory=packages/ardt-tasks-ros\""""

_LOCAL_INSTALL = f"""\
# dev mode: ardt injected from a local checkout instead of the git default
COPY {LOCAL_ARDT_DIR} /opt/ardt-src
RUN python3 -m pip install --break-system-packages \\
      /opt/ardt-src/packages/ardt-core /opt/ardt-src/packages/ardt-tasks-ros"""

_BASE_FROM = re.compile(r"^FROM\s+\$\{?BASE_IMAGE\}?\s*$")


def _template(name: str) -> str:
    return (resources.files("ardt_pipelines_ros.recipes") / name).read_text(encoding="utf-8")


def _parse_base_extension(path: Path) -> str:
    """Validate a repo's base extension and return its body (everything after FROM).

    The contract is deliberately tiny: one stage, starting ``FROM ${BASE_IMAGE}``.
    The render owns the stage name and where it slots in.
    """
    lines = path.read_text(encoding="utf-8").splitlines()

    body_start: int | None = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.upper().startswith("ARG BASE_IMAGE"):
            continue  # tolerated for standalone `docker build -f base.Dockerfile`
        if _BASE_FROM.match(stripped):
            body_start = index + 1
            break
        raise ArdtError(
            f"{path.name} must start with `FROM ${{BASE_IMAGE}}`",
            hint="the base extension extends the configured base image; it cannot pick its own",
        )
    if body_start is None:
        raise ArdtError(f"{path.name} has no FROM line")

    body = lines[body_start:]
    for line in body:
        if line.strip().upper().startswith("FROM "):
            raise ArdtError(
                f"{path.name} must define a single stage",
                hint="extra stages belong in the ardt-owned recipe, not in repos",
            )
    return "\n".join(body).strip()


def render_ros2(
    *,
    builder: str,
    base_image: str,
    project_root: Path,
    base_dockerfile: str,
    cmd: list[str] | None,
    ardt_source: str,
    local_ardt: bool,
) -> str:
    """Render the ROS 2 workspace recipe for one repo."""
    base_ext = ""
    runtime_from = "${BASE_IMAGE}"
    base_path = project_root / base_dockerfile
    if base_path.is_file():
        body = _parse_base_extension(base_path)
        base_ext = (
            f"\n# ---- repo-provided base extension ({base_dockerfile}) ----\n"
            f"FROM ${{BASE_IMAGE}} AS {BASE_EXT_STAGE}\n{body}\n"
        )
        runtime_from = BASE_EXT_STAGE

    install = _LOCAL_INSTALL if local_ardt else _GIT_INSTALL.format(source=ardt_source)
    rendered_cmd = f"CMD {json.dumps(cmd)}\n" if cmd else ""

    return (
        _template("ros2.Dockerfile.tmpl")
        .replace("@VERSION@", __version__)
        .replace("@BUILDER@", builder)
        .replace("@BASE_IMAGE@", base_image)
        .replace("@BASE_FILE@", base_dockerfile)
        .replace("@ARDT_INSTALL@", install)
        .replace("@BASE_EXT@", base_ext)
        .replace("@RUNTIME_FROM@", runtime_from)
        .replace("@CMD@", rendered_cmd)
    )
