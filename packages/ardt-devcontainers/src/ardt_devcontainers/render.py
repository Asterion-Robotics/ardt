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

"""Rendering the dev environment into gitignored, machine-owned files.

Two rules shape this module:

1. **Nothing is repo content.** Every file is generated, hashed in a manifest,
   and gitignored. A hand edit is detected and refused, not silently kept — the
   fix is a template change in the profile plugin, or a knob in ``dev:``.
2. **The structured files are built from data structures**, not string templates
   (compose, ``devcontainer.json`` and ``c_cpp_properties.json`` are dumped from
   dicts). Only the Dockerfile is a text template, because that is the artifact a
   human debugs and the one ``platform/base-images`` will inherit verbatim.

:attr:`Render.files` is keyed by **repo-root-relative path**: nearly everything
lands in ``.devcontainer/``, but a file an extension can only read from
``.vscode/`` has to land there, and one manifest covers both.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

import yaml

from ardt_core import dist
from ardt_core.config import ArdtConfig
from ardt_core.plugins import Registry

from . import __version__
from .config import (
    DEVCONTAINER_DIR,
    VSCODE_DIR,
    WORKSPACE_FOLDER,
    DevConfig,
    ci_builder,
    ros_distro,
    source_folder,
)
from .host import HostFacts, HostProfile, detect
from .profiles import CXX_STANDARD, DISTRO, Profile, cxx_standard, profile

USER = "ubuntu"
"""uid 1000 in every ubuntu:24.04-derived image, ROS's included — so a Linux
host's uid 1000 maps straight through and bind-mounted files stay writable."""

MANIFEST = f"{DEVCONTAINER_DIR}/.ardt-dev.json"
"""Keeps its pre-split name on purpose: renaming it would make every repo
already synced look un-generated, and the first `ardt dev sync` after an
upgrade would refuse the whole render as hand-edited."""
COMPOSE = f"{DEVCONTAINER_DIR}/compose.yaml"
COMPOSE_HOST = f"{DEVCONTAINER_DIR}/compose.host.yaml"
DEVCONTAINER = f"{DEVCONTAINER_DIR}/devcontainer.json"
POST_CREATE = f"{DEVCONTAINER_DIR}/postCreate.sh"
HOST_CONFIG = f"{DEVCONTAINER_DIR}/host-config.sh"
REQUIREMENTS = f"{DEVCONTAINER_DIR}/ardt-requirements.txt"
DOCKERFILE = f"{DEVCONTAINER_DIR}/Dockerfile"
GITIGNORE = f"{DEVCONTAINER_DIR}/.gitignore"
"""Self-ignoring, ruff-cache style: the render stays out of git even in a repo
whose root ``.gitignore`` never got the `ardt dev sync` entries."""
CPP_PROPERTIES = f"{VSCODE_DIR}/c_cpp_properties.json"

GITIGNORE_BODY = "# Automatically created by `ardt dev sync`.\n*\n"

ARDT_SRC_MOUNT = "/opt/ardt-src"
"""Where a local ardt checkout mounts — the dev twin of the pipeline's
``--arg ardt_source=<dir>`` escape hatch."""

COLCON_VOLUME = "colcon"
"""One volume per repo for the whole colcon output tree. Compose namespaces it
under the project, so two repos never share it."""

COLCON_DIRS = ("build", "install", "log")
"""Mounted from :data:`COLCON_VOLUME` by ``subpath``, not as a volume each.

Docker refuses to mount a subpath that does not exist yet and will not create it
(moby#47842), so ``ardt dev volumes`` provisions these before the first start."""

SHARED_VOLUMES = {
    "ardt-ccache": "ccache is content-addressed: sharing it across repos raises the hit rate",
    "ardt-apt-cache": "downloaded .debs are the same Ubuntu packages in every repo",
    "ardt-claude": "one `claude login` for every repo, surviving any rebuild",
}
"""Declared ``external:`` and named without the project prefix, so every repo on
the machine uses the same three instead of three more.

``external:`` is the load-bearing part, not just the fixed name: it keeps
``ardt dev down --purge`` repo-scoped — compose does not delete what it does not
own, so purging one repo cannot wipe another's caches. The cost is that they
have to exist before ``up``; ``ardt dev volumes`` creates them."""

CLAUDE_VOLUME = "ardt-claude"

EXECUTABLE = frozenset({POST_CREATE, HOST_CONFIG})

BASE_MODULES = ("ardt-core", "ardt-devcontainers")
"""Installed in the container whatever the profile is: ``postCreate.sh`` hands
over to ``ardt dev bootstrap``, so the engine has to be in there with the core.
The profile's own distribution joins them in :func:`requirements` — without it
the container could not resolve the profile it was rendered from."""


def _unique(*names: str) -> tuple[str, ...]:
    """Order-preserving dedup — a profile may name a base module too."""
    return tuple(dict.fromkeys(names))


_HOST_CONFIG_BODY = """\
#!/usr/bin/env bash
# Rendered by `ardt dev sync` (ardt-devcontainers @VERSION@) — machine-owned, gitignored.
#
# initializeCommand: re-derive the host overlay, so one clone works on WSL2,
# Linux and macOS without a per-machine edit, then create the volumes compose
# will not create for itself. Both must happen before VS Code runs its own
# `compose up`, which is why they hang off initializeCommand and not postCreate.
# A host without ardt installed is not fatal: the overlay `ardt dev sync` already
# wrote stays in place.
set -eu
if command -v ardt >/dev/null 2>&1; then
  ardt dev host-config
  ardt dev volumes
else
  echo "ardt not on PATH: keeping the existing .devcontainer/compose.host.yaml" >&2
fi
"""


@dataclass(frozen=True)
class Render:
    """The full plan: every file, plus what it was resolved from."""

    files: dict[str, str]
    """Repo-root-relative path -> content."""
    profile: Profile
    base_image: str
    host: HostProfile
    host_facts: HostFacts
    """The raw probe. ``host`` is what compose needs; this is what anything else
    host-shaped needs — `ardt dev open` asks it for the editor's view of a path."""
    distro: str
    ardt_source: str | None
    requirements: tuple[str, ...]
    image: str | None = None
    """``dev.image`` when the repo pins a published one, else None."""
    shared_volumes: tuple[str, ...] = ()
    """The machine-wide caches. ``external:``, so they must exist before compose
    starts and compose never removes them."""
    colcon_volume: str | None = None
    """The repo's colcon volume, already project-prefixed as Docker names it.
    None when ``isolate_build_dirs`` is off and there is nothing to provision."""
    executable: frozenset[str] = EXECUTABLE

    @property
    def host_files(self) -> dict[str, str]:
        """The subset ``ardt dev host-config`` may rewrite on its own."""
        return {COMPOSE_HOST: self.files[COMPOSE_HOST]}

    @property
    def provision_image(self) -> str:
        """An image guaranteed to be pulled anyway, used to mkdir the subpaths."""
        return self.image or self.base_image


def _template(package: str, name: str) -> str:
    return (resources.files(package) / name).read_text(encoding="utf-8")


ENGINE_TEMPLATES = "ardt_devcontainers.templates"
"""Anchor for the templates the engine owns. The Dockerfile is the profile's
(:attr:`~.profiles.Profile.templates_package`); ``postCreate.sh`` is not — it
only hands over to ``ardt dev bootstrap``, which is where a profile's own
create steps run."""


def digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def resolve_base_image(cfg: ArdtConfig, dev: DevConfig, prof: Profile, distro: str) -> str:
    """The dev layer's base, in priority order.

    ``pipelines.ros_ci.builder`` beats the profile default on purpose: the repo
    that has already chosen a CI builder gets parity for free, with nothing to
    keep in sync.
    """
    chosen = dev.base_image or ci_builder(cfg) or prof.default_base_image
    return chosen.replace(DISTRO, distro)


def requirements(
    cfg: ArdtConfig,
    dev: DevConfig,
    prof: Profile,
    ardt_source: str | None,
) -> tuple[str, ...]:
    """The ardt install lines, resolved exactly as the CI recipe resolves them.

    Default: ``ardt_core.dist`` turns the repo's ``ardt:`` pin into PEP 508
    requirements — the same strings ``ros-ci`` pip-installs into its build
    stage. With a local checkout mounted, container-side paths replace them, the
    dev twin of ``ardt pipe run ros-ci --arg ardt_source=<dir>``.
    """
    modules = _unique(*BASE_MODULES, prof.distribution, *prof.ardt_modules, *dev.ardt_modules)
    if ardt_source is not None:
        return tuple(dist.local_requirement(module, ARDT_SRC_MOUNT) for module in modules)
    return cfg.ardt.requirements(modules)


def _apt_block(prof: Profile, extra: list[str], distro: str) -> str:
    """The package list for the rendered recipe, labelled group by group.

    Backtick-quoted shell comments (not ``#`` lines) so the block is safe inside
    a line continuation in any builder.
    """
    lines: list[str] = []
    groups = [*prof.apt_groups]
    if extra:
        groups.append(("from dev.apt_packages in ardt.yaml", tuple(extra)))
    for label, packages in groups:
        lines.append(f"      `# {label}` \\")
        rendered = " ".join(p.replace(DISTRO, distro) for p in packages)
        lines.append(f"      {rendered} \\")
    lines[-1] = lines[-1].removesuffix(" \\")
    return "\n".join(lines)


IN_CONTAINER_ENV = "ARDT_DEV_CONTAINER"
"""Set by the rendered image, so a command that only makes sense inside the
container can say so instead of half-running on someone's laptop. Owned here,
beside the render that bakes it; the CLI imports it."""


def _env_block(prof: Profile, dev: DevConfig) -> str:
    home = f"/home/{USER}"
    values = {
        "CCACHE_DIR": f"{home}/.ccache",
        "PATH": f"{home}/.local/bin:${{PATH}}",
        IN_CONTAINER_ENV: "1",
        **prof.container_env,
    }
    if dev.claude_code:
        # Relocates .claude.json next to the rest, so one volume holds all of
        # Claude Code's state and `claude login` survives a rebuild.
        values["CLAUDE_CONFIG_DIR"] = f"{home}/.claude"
    return " \\\n    ".join(f"{key}={value}" for key, value in sorted(values.items()))


CLAUDE_CODE_VERSION: str | None = None
"""The Claude Code version baked into the dev image, passed to the official
installer (``install.sh <version>``). None tracks the installer's default
channel — the one moving layer in an otherwise pinned render; set an exact
version here (bumped like any other pin) to freeze it."""

_CLAUDE_BLOCK = """
# Claude Code lives under $HOME: the launcher in ~/.local/bin, its state in
# $CLAUDE_CONFIG_DIR. That directory is a named volume at runtime, so the baked
# install is copied into it on first create and self-updates from there.
RUN curl -fsSL https://claude.ai/install.sh | bash{version_arg}
"""


def _claude_block() -> str:
    arg = f" -s -- {CLAUDE_CODE_VERSION}" if CLAUDE_CODE_VERSION else ""
    return _CLAUDE_BLOCK.format(version_arg=arg)


def dockerfile(prof: Profile, dev: DevConfig, *, project: str, base_image: str, distro: str) -> str:
    return (
        _template(prof.templates_package, prof.dockerfile)
        .replace("@VERSION@", __version__)
        .replace("@BASE_IMAGE@", base_image)
        .replace("@USER@", USER)
        .replace("@WORKSPACE@", WORKSPACE_FOLDER)
        .replace("@PROJECT@", project)
        .replace("@APT@", _apt_block(prof, dev.apt_packages, distro))
        .replace("@ENV@", _env_block(prof, dev))
        .replace("@CLAUDE@", _claude_block() if dev.claude_code else "")
    )


class _Dumper(yaml.SafeDumper):
    """Indents sequences under their key — these files get read by humans."""

    def increase_indent(self, flow: bool = False, indentless: bool = False) -> None:
        super().increase_indent(flow=flow, indentless=False)


def _yaml_document(data: dict[str, object], *, note: str = "") -> str:
    header = (
        "# Rendered by `ardt dev sync` "
        f"(ardt-devcontainers {__version__}) — machine-owned, gitignored.\n"
    )
    if note:
        header += f"# {note}\n"
    body = yaml.dump(
        data,
        Dumper=_Dumper,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        width=100,
    )
    return header + body


def compose(
    ctx_project: str,
    dev: DevConfig,
    *,
    ardt_source: str | None,
    image: str | None,
) -> str:
    """The portable half: everything identical on WSL2, Linux and macOS."""
    workspace = WORKSPACE_FOLDER
    home = f"/home/{USER}"

    # The repo is ONE entry under the workspace's src/ — `.repos` imports land
    # grouped in src/external/ — and the colcon output dirs are the workspace
    # root's, exactly the tree the CI recipe builds in.
    volumes: list[object] = [f"..:{source_folder(ctx_project)}:cached"]
    named: dict[str, object] = {}
    if dev.isolate_build_dirs:
        # One volume, three subpaths — long syntax, since the `src:dst` short
        # form cannot express a subpath.
        for name in COLCON_DIRS:
            volumes.append(
                {
                    "type": "volume",
                    "source": COLCON_VOLUME,
                    "target": f"{workspace}/{name}",
                    "volume": {"subpath": name},
                }
            )
        named[COLCON_VOLUME] = None
    volumes.append(f"ardt-ccache:{home}/.ccache")
    volumes.append("ardt-apt-cache:/var/cache/apt/archives")
    for shared in SHARED_VOLUMES:
        if shared == CLAUDE_VOLUME and not dev.claude_code:
            continue
        named[shared] = {"external": True}
    if dev.claude_code:
        volumes.append(f"{CLAUDE_VOLUME}:{home}/.claude")
    if ardt_source is not None:
        volumes.append(f"{ardt_source}:{ARDT_SRC_MOUNT}:ro")
    volumes += dev.mounts

    service: dict[str, object] = {}
    if image:
        service["image"] = image
    else:
        # Both paths resolve relative to the compose file's own directory
        # (.devcontainer/), and `dockerfile` relative to `context` on top of
        # that — `dockerfile: .devcontainer/Dockerfile` here would resolve to
        # `.devcontainer/.devcontainer/Dockerfile` and fail every build.
        service["build"] = {"context": ".", "dockerfile": Path(DOCKERFILE).name}
    service.update(
        {
            "init": True,
            "command": "sleep infinity",
            "environment": {"ROS_DOMAIN_ID": "${ROS_DOMAIN_ID:-0}"},
            "volumes": volumes,
        }
    )

    return _yaml_document(
        {
            "name": compose_project(ctx_project),
            "services": {"dev": service},
            "volumes": named,
        },
        note=(
            "Host-specific wiring lives in compose.host.yaml, re-derived per machine "
            "by `ardt dev host-config`."
        ),
    )


def host_overlay(host: HostProfile) -> str:
    """The host-specific half — the only file that differs between machines."""
    service: dict[str, object] = dict(host.service)
    if host.environment:
        service["environment"] = dict(host.environment)
    if host.devices:
        service["devices"] = list(host.devices)
    if host.volumes:
        service["volumes"] = list(host.volumes)
    if not service:
        # compose rejects a null service body.
        service["environment"] = {}
    return _yaml_document(
        {"services": {"dev": service}},
        note=f"host: {host.kind}. Re-derived by `ardt dev host-config` (initializeCommand).",
    )


def devcontainer(project: str, dev: DevConfig, prof: Profile) -> str:
    data: dict[str, object] = {
        "name": f"{project} — {prof.name} dev",
        # Resolved relative to devcontainer.json itself, unlike the commands
        # below: initializeCommand runs on the HOST from the repo checkout,
        # postCreateCommand runs in the container from workspaceFolder — the
        # workspace root, of which the repo is src/<project>.
        "dockerComposeFile": [Path(COMPOSE).name, Path(COMPOSE_HOST).name],
        "service": "dev",
        "workspaceFolder": WORKSPACE_FOLDER,
        "remoteUser": USER,
        "initializeCommand": f"bash {HOST_CONFIG}",
        "postCreateCommand": f"bash src/{project}/{POST_CREATE}",
        "customizations": {
            "vscode": {
                "extensions": [*prof.extensions, *dev.extensions],
                "settings": prof.settings,
            }
        },
    }
    header = (
        "// Rendered by `ardt dev sync` "
        f"(ardt-devcontainers {__version__}) — machine-owned, gitignored.\n"
        "// Editor config ships with the container; the repo carries no .vscode/ of\n"
        "// its own (`ardt dev sync` renders the one file that cannot live here).\n"
        "// Change the dev profile or `dev:` in ardt.yaml, never this file.\n"
    )
    return header + json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def _detokenize(value: object, distro: str) -> object:
    """Resolve the profile tokens through nested profile data."""
    if isinstance(value, str):
        return value.replace(DISTRO, distro).replace(CXX_STANDARD, cxx_standard(distro))
    if isinstance(value, list):
        return [_detokenize(item, distro) for item in value]  # type: ignore[arg-type]
    if isinstance(value, dict):
        return {key: _detokenize(item, distro) for key, item in value.items()}  # type: ignore[union-attr]
    return value


def cpp_properties(prof: Profile, distro: str) -> str:
    """``.vscode/c_cpp_properties.json`` — the one file cpptools reads from there.

    No comment header, unlike every other rendered file: cpptools only grew a
    JSONC parser in 1.0.0, and VS Code still flags comments here unless the file
    is associated as jsonc (microsoft/vscode-cpptools#5885, #6132). Provenance
    lives in the manifest instead.
    """
    entry = _detokenize(dict(prof.cpp_properties or {}), distro)
    return json.dumps({"configurations": [entry], "version": 4}, indent=4) + "\n"


def _slug(name: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")


def compose_project(project: str) -> str:
    """The compose project name — and so the prefix on every non-external volume."""
    return f"{_slug(project)}-dev"


def build(
    project: str,
    cfg: ArdtConfig,
    dev: DevConfig,
    *,
    registry: Registry,
    facts: HostFacts | None = None,
    ardt_source: str | None = None,
) -> Render:
    """Resolve everything and produce the file set. Pure: nothing is written.

    ``registry`` is where the profile comes from — ``ctx.registry`` in a command,
    a hand-built one in a test. Injected rather than discovered here, so a render
    never depends on what happens to be installed behind the caller's back.
    """
    prof = profile(dev.profile, registry)
    distro = ros_distro(cfg)
    base_image = resolve_base_image(cfg, dev, prof, distro)
    probed = facts or HostFacts.probe()
    host = detect(probed, gui=dev.gui)
    reqs = requirements(cfg, dev, prof, ardt_source)

    files = {
        GITIGNORE: GITIGNORE_BODY,
        DOCKERFILE: dockerfile(prof, dev, project=project, base_image=base_image, distro=distro),
        COMPOSE: compose(project, dev, ardt_source=ardt_source, image=dev.image),
        COMPOSE_HOST: host_overlay(host),
        DEVCONTAINER: devcontainer(project, dev, prof),
        POST_CREATE: _template(ENGINE_TEMPLATES, "postCreate.sh.tmpl").replace(
            "@VERSION@", __version__
        ),
        HOST_CONFIG: _HOST_CONFIG_BODY.replace("@VERSION@", __version__),
        REQUIREMENTS: (
            "# Rendered by `ardt dev sync` from the `ardt:` section of this repo's config.\n"
            "# The same requirement strings the ros-ci recipe installs into its build stage.\n"
            + "".join(f"{req}\n" for req in reqs)
        ),
    }
    if prof.cpp_properties:
        files[CPP_PROPERTIES] = cpp_properties(prof, distro)
    shared = tuple(v for v in SHARED_VOLUMES if dev.claude_code or v != CLAUDE_VOLUME)
    return Render(
        files=files,
        profile=prof,
        base_image=base_image,
        host=host,
        host_facts=probed,
        distro=distro,
        ardt_source=ardt_source,
        requirements=reqs,
        image=dev.image,
        shared_volumes=shared,
        colcon_volume=(
            f"{compose_project(project)}_{COLCON_VOLUME}" if dev.isolate_build_dirs else None
        ),
    )
