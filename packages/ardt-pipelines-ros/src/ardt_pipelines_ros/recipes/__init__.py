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
from ardt_pipelines import std
from ardt_pipelines_ros import __version__

RENDERED_NAME = "Dockerfile.rendered"
"""The rendered recipe's filename, inside the build context and in the export."""

DOCKERIGNORE_NAME = f"{RENDERED_NAME}.dockerignore"
"""Exported next to the rendered recipe. BuildKit picks up a per-Dockerfile
``<name>.dockerignore``, so the plain ``docker build -f …`` escape hatch gets
the same context excludes the pipeline uses — without it, a host checkout's
``build/``/``install/`` trees leak into the image and break rosdep/colcon."""

BUILD_TARGET = "build"
RUNTIME_TARGET = "runtime"
RESULTS_DIR = "/results"
"""Where the build stage places JUnit XMLs (fixed contract with the pipeline)."""

BASE_EXT_STAGE = "base-ext"
"""Stage name given to a repo's base extension in the rendered recipe."""

LOCAL_ARDT_DIR = ".ardt-src"
"""Context subdirectory the pipeline injects a local ardt checkout into."""

# Re-exported so recipe consumers need not care where the contract lives.
GIT_TOKEN_SECRET = std.GIT_TOKEN_SECRET
"""BuildKit secret id the deps layer's token mount uses — the contract with
``ardt_pipelines.std.git_credentials``."""

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

_GIT_MOUNTS = f"""--mount=type=ssh \\
    --mount=type=secret,id={GIT_TOKEN_SECRET},required=false \\
    """

# The proven aos_edge auth branching, verbatim in mechanism: an SSH agent when
# BuildKit forwarded one, else the token secret via a credential helper that
# reads /run/secrets at *use* time (the token itself never lands in a layer),
# else fail with the two ways to provide credentials.
_GIT_AUTH = """ \\
 && if [ -n "$SSH_AUTH_SOCK" ] && [ -S "$SSH_AUTH_SOCK" ]; then \\
      echo "git auth for {host}: ssh agent" \\
      && mkdir -m 0700 -p ~/.ssh \\
      && ssh-keyscan -p {port} {host} >> ~/.ssh/known_hosts \\
      && git config --global url."ssh://git@{host}:{port}/".insteadOf "https://{host}/"; \\
    elif [ -f /run/secrets/{secret} ]; then \\
      echo "git auth for {host}: token" \\
      && git config --global credential."https://{host}".helper \\
           '!f() {{ echo "username={user}"; echo "password=$(cat /run/secrets/{secret})"; }}; f'; \\
    else \\
      echo "no git credentials for {host}: CI injects the job token; locally set" >&2 \\
      && echo "job_token: in ~/.config/ardt/credentials.yaml or run an ssh agent —" >&2 \\
      && echo "escape hatch: docker build --ssh default -f {rendered} ." >&2 \\
      && exit 1; \\
    fi"""

_STRIP_STEP = """\

# 4b) IP protection: development files are removed BEFORE the runtime copy, so
# the shipped image carries no headers, static libs, or CMake/pkg-config
# exports that would let a third party develop against the proprietary
# packages. Runtime data (launch files, urdf, plugins) is kept.
RUN find {base} -type d \\( -name include -o -name cmake -o -name pkgconfig \\) \\
      -prune -exec rm -rf {{}} + \\
 && find {base} -name '*.a' -delete
"""


def _template(name: str) -> str:
    return (resources.files("ardt_pipelines_ros.recipes") / name).read_text(encoding="utf-8")


def render_dockerignore(excludes: tuple[str, ...]) -> str:
    """Context excludes for the standalone ``docker build`` escape hatch.

    ``.ardt-src`` must never appear here: the dev-mode recipe COPYs it
    explicitly, and an ignored path would fail that COPY.
    """
    lines = "\n".join(excludes)
    return f"# Rendered by ardt ros-ci — keep next to {RENDERED_NAME}.\n{lines}\n"


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
    install_base: str = "/opt/ros/aos",
    strip_dev_files: bool = False,
    git_host: str | None = None,
    git_ssh_port: int = 22,
    git_token_user: str = "gitlab-ci-token",
) -> str:
    """Render the ROS 2 workspace recipe for one repo.

    ``git_host`` switches on private-host git auth for the deps layer (the
    ``vcs import`` of a private ``.repos``): SSH-agent and token mounts plus
    the runtime branching between them.
    """
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
    strip = _STRIP_STEP.format(base=install_base) if strip_dev_files else ""
    git_mounts = _GIT_MOUNTS if git_host else ""
    git_auth = (
        _GIT_AUTH.format(
            host=git_host,
            port=git_ssh_port,
            secret=GIT_TOKEN_SECRET,
            user=git_token_user,
            rendered=RENDERED_NAME,
        )
        if git_host
        else ""
    )

    return (
        _template("ros2.Dockerfile.tmpl")
        .replace("@VERSION@", __version__)
        .replace("@BUILDER@", builder)
        .replace("@BASE_IMAGE@", base_image)
        .replace("@BASE_FILE@", base_dockerfile)
        .replace("@ARDT_INSTALL@", install)
        .replace("@GIT_MOUNTS@", git_mounts)
        .replace("@GIT_AUTH@", git_auth)
        .replace("@INSTALL_BASE@", install_base)
        .replace("@STRIP@", strip)
        .replace("@BASE_EXT@", base_ext)
        .replace("@RUNTIME_FROM@", runtime_from)
        .replace("@CMD@", rendered_cmd)
    )
