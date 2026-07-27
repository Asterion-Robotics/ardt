"""Rendering the dev environment into gitignored, machine-owned files.

Two rules shape this module:

1. **Nothing is repo content.** Every file is generated, hashed in a manifest,
   and gitignored. A hand edit is detected and refused, not silently kept — the
   fix is a template change in ardt-dev or a knob in ``dev:``.
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
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

import yaml

from ardt_core import dist
from ardt_core.config import ArdtConfig
from ardt_core.errors import ArdtError

from . import __version__
from .config import DEVCONTAINER_DIR, VSCODE_DIR, DevConfig, ci_builder, ros_distro
from .host import HostFacts, HostProfile, detect
from .profiles import CXX_STANDARD, DISTRO, Profile, cxx_standard, profile

USER = "ubuntu"
"""uid 1000 in every ubuntu:24.04-derived image, ROS's included — so a Linux
host's uid 1000 maps straight through and bind-mounted files stay writable."""

MANIFEST = f"{DEVCONTAINER_DIR}/.ardt-dev.json"
COMPOSE = f"{DEVCONTAINER_DIR}/compose.yaml"
COMPOSE_HOST = f"{DEVCONTAINER_DIR}/compose.host.yaml"
DEVCONTAINER = f"{DEVCONTAINER_DIR}/devcontainer.json"
POST_CREATE = f"{DEVCONTAINER_DIR}/postCreate.sh"
HOST_CONFIG = f"{DEVCONTAINER_DIR}/host-config.sh"
REQUIREMENTS = f"{DEVCONTAINER_DIR}/ardt-requirements.txt"
DOCKERFILE = f"{DEVCONTAINER_DIR}/Dockerfile"
CPP_PROPERTIES = f"{VSCODE_DIR}/c_cpp_properties.json"

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

BASE_MODULES = ("ardt-core", "ardt-dev")
"""Installed in the container whatever the profile is: ``postCreate.sh`` hands
over to ``ardt dev bootstrap``, so ardt-dev has to be in there with the core."""


def _unique(*names: str) -> tuple[str, ...]:
    """Order-preserving dedup — a profile may name a base module too."""
    return tuple(dict.fromkeys(names))


_HOST_CONFIG_BODY = """\
#!/usr/bin/env bash
# Rendered by `ardt dev sync` (ardt-dev @VERSION@) — machine-owned, gitignored.
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


def _template(name: str) -> str:
    return (resources.files("ardt_dev.templates") / name).read_text(encoding="utf-8")


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
    modules = _unique(*BASE_MODULES, *prof.ardt_modules, *dev.ardt_modules)
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


def _env_block(prof: Profile, dev: DevConfig) -> str:
    home = f"/home/{USER}"
    values = {
        "CCACHE_DIR": f"{home}/.ccache",
        "PATH": f"{home}/.local/bin:${{PATH}}",
        # Lets commands that only make sense inside the container say so.
        "ARDT_DEV_CONTAINER": "1",
        **prof.container_env,
    }
    if dev.claude_code:
        # Relocates .claude.json next to the rest, so one volume holds all of
        # Claude Code's state and `claude login` survives a rebuild.
        values["CLAUDE_CONFIG_DIR"] = f"{home}/.claude"
    return " \\\n    ".join(f"{key}={value}" for key, value in sorted(values.items()))


_CLAUDE_BLOCK = """
# Claude Code lives under $HOME: the launcher in ~/.local/bin, its state in
# $CLAUDE_CONFIG_DIR. That directory is a named volume at runtime, so the baked
# install is copied into it on first create and self-updates from there.
RUN curl -fsSL https://claude.ai/install.sh | bash
"""


def dockerfile(prof: Profile, dev: DevConfig, *, base_image: str, distro: str) -> str:
    return (
        _template(prof.dockerfile)
        .replace("@VERSION@", __version__)
        .replace("@BASE_IMAGE@", base_image)
        .replace("@USER@", USER)
        .replace("@WORKSPACE@", dev.workspace_folder)
        .replace("@APT@", _apt_block(prof, dev.apt_packages, distro))
        .replace("@ENV@", _env_block(prof, dev))
        .replace("@CLAUDE@", _CLAUDE_BLOCK if dev.claude_code else "")
    )


class _Dumper(yaml.SafeDumper):
    """Indents sequences under their key — these files get read by humans."""

    def increase_indent(self, flow: bool = False, indentless: bool = False) -> None:
        super().increase_indent(flow=flow, indentless=False)


def _yaml_document(data: dict[str, object], *, note: str = "") -> str:
    header = (
        f"# Rendered by `ardt dev sync` (ardt-dev {__version__}) — machine-owned, gitignored.\n"
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
    workspace = dev.workspace_folder
    home = f"/home/{USER}"

    volumes: list[object] = [f"..:{workspace}:cached"]
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
        service["build"] = {"context": ".", "dockerfile": DOCKERFILE}
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
        # below, which VS Code runs from the workspace root.
        "dockerComposeFile": [Path(COMPOSE).name, Path(COMPOSE_HOST).name],
        "service": "dev",
        "workspaceFolder": dev.workspace_folder,
        "remoteUser": USER,
        "initializeCommand": f"bash {HOST_CONFIG}",
        "postCreateCommand": f"bash {POST_CREATE}",
        "customizations": {
            "vscode": {
                "extensions": [*prof.extensions, *dev.extensions],
                "settings": prof.settings,
            }
        },
    }
    header = (
        f"// Rendered by `ardt dev sync` (ardt-dev {__version__}) — machine-owned, gitignored.\n"
        "// Editor config ships with the container; the repo carries no .vscode/ of\n"
        "// its own (`ardt dev sync` renders the one file that cannot live here).\n"
        "// Change ardt-dev's profile or `dev:` in ardt.yaml, never this file.\n"
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
    facts: HostFacts | None = None,
    ardt_source: str | None = None,
) -> Render:
    """Resolve everything and produce the file set. Pure: nothing is written."""
    prof = profile(dev.profile)
    distro = ros_distro(cfg)
    base_image = resolve_base_image(cfg, dev, prof, distro)
    probed = facts or HostFacts.probe()
    host = detect(probed, gui=dev.gui)
    reqs = requirements(cfg, dev, prof, ardt_source)

    files = {
        DOCKERFILE: dockerfile(prof, dev, base_image=base_image, distro=distro),
        COMPOSE: compose(project, dev, ardt_source=ardt_source, image=dev.image),
        COMPOSE_HOST: host_overlay(host),
        DEVCONTAINER: devcontainer(project, dev, prof),
        POST_CREATE: _template("postCreate.sh.tmpl").replace("@VERSION@", __version__),
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


@dataclass
class WriteResult:
    """What ``write`` did, so the CLI can report instead of guessing."""

    written: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    """Files on disk that ardt did not generate, or that were edited by hand."""


def _manifest_key(name: str) -> str:
    """Read a pre-``.vscode/`` manifest, whose keys were bare file names.

    Without this every repo synced by an older ardt-dev would see its whole
    render reported as hand-edited on the next `ardt dev sync` — the keys, not
    the contents, changed.
    """
    return name if "/" in name else f"{DEVCONTAINER_DIR}/{name}"


def load_manifest(root: Path) -> dict[str, str]:
    """The hashes of the last render, or ``{}`` when there is none."""
    path = root / MANIFEST
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    generated = data.get("generated") if isinstance(data, dict) else None
    if not isinstance(generated, dict):
        return {}
    return {_manifest_key(str(k)): str(v) for k, v in generated.items()}  # type: ignore[union-attr]


def audit(root: Path, render: Render, *, only: dict[str, str] | None = None) -> WriteResult:
    """Compare a render against the working tree without touching anything."""
    manifest = load_manifest(root)
    result = WriteResult()
    for name, content in (only or render.files).items():
        path = root / name
        if not path.exists():
            result.written.append(name)
            continue
        on_disk = path.read_text(encoding="utf-8")
        if on_disk == content:
            result.unchanged.append(name)
        elif manifest.get(name) == digest(on_disk):
            result.written.append(name)  # ours, and stale — safe to refresh
        else:
            result.conflicts.append(name)
    return result


def write(
    root: Path,
    render: Render,
    *,
    force: bool = False,
    only: dict[str, str] | None = None,
) -> WriteResult:
    """Write the render, refusing to clobber anything ardt did not generate."""
    subset = only or render.files
    result = audit(root, render, only=subset)
    if result.conflicts and not force:
        listed = ", ".join(sorted(result.conflicts))
        raise ArdtError(
            f"ardt did not generate these file(s): {listed}",
            hint=(
                "`ardt dev sync --force` overwrites them; "
                "the supported customization knobs are `dev:` in ardt.yaml"
            ),
        )

    to_write = [*result.written, *(result.conflicts if force else [])]
    for name in to_write:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(subset[name], encoding="utf-8")
        if name in render.executable:
            path.chmod(0o755)

    manifest = load_manifest(root)
    manifest.update({name: digest(content) for name, content in subset.items()})
    manifest_path = root / MANIFEST
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "tool": f"ardt-dev {__version__}",
                "profile": render.profile.name,
                "host": render.host.kind,
                "base_image": render.base_image,
                "ardt_source": render.ardt_source,
                "generated": manifest,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    result.written = to_write
    if force:
        result.conflicts = []
    return result


GITIGNORE_ENTRIES = (f"{DEVCONTAINER_DIR}/", CPP_PROPERTIES)
"""What the render occupies. The whole of ``.devcontainer/``, but only the one
generated file under ``.vscode/`` — a repo may keep its own launch.json there."""

_GITIGNORE_NOTE = "# generated by `ardt dev sync` — machine-owned, never committed"


def _gitignore_entries(root: Path) -> set[str]:
    path = root / ".gitignore"
    if not path.is_file():
        return set()
    return {line.strip().rstrip("/") for line in path.read_text(encoding="utf-8").splitlines()}


def missing_gitignore_entries(root: Path) -> list[str]:
    """The render paths ``.gitignore`` does not exclude yet."""
    present = _gitignore_entries(root)
    return [entry for entry in GITIGNORE_ENTRIES if entry.rstrip("/") not in present]


def is_gitignored(root: Path) -> bool:
    """True when ``.gitignore`` already excludes the whole render."""
    return not missing_gitignore_entries(root)


def ensure_gitignored(root: Path) -> list[str]:
    """Add the render's paths to the repo's ``.gitignore``. Returns what it added."""
    missing = missing_gitignore_entries(root)
    if not missing:
        return []
    path = root / ".gitignore"
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    prefix = "" if existing.endswith("\n") or not existing else "\n"
    added = "".join(f"{entry}\n" for entry in missing)
    path.write_text(f"{existing}{prefix}\n{_GITIGNORE_NOTE}\n{added}", encoding="utf-8")
    return missing
