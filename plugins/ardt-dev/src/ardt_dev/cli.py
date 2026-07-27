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

"""The ``ardt dev`` command group.

Three kinds of command: one that *renders* the environment (``sync``, plus the
``host-config`` re-render the container's own lifecycle calls), ones that *drive*
it from the host (``up``, ``shell``, ``down``), and ones that run *inside* it
(``bootstrap``, ``compile-commands``).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import click

from ardt_core import env as env_module
from ardt_core.cli import pass_ardt
from ardt_core.context import Context
from ardt_core.errors import ArdtError

from . import host as host_module
from . import render as render_module
from .config import DEVCONTAINER_DIR, ci_builder, dev_config, ros_distro
from .host import HostFacts
from .profiles import DISTRO, PROFILES, profile
from .render import (
    COMPOSE,
    COMPOSE_HOST,
    POST_CREATE,
    USER,
    Render,
)

IN_CONTAINER_ENV = "ARDT_DEV_CONTAINER"
"""Set by the rendered image, so a command that only makes sense inside the
container can say so instead of half-running on someone's laptop."""


def _workspace_root(root: Path) -> Path:
    """The colcon workspace root for a project root — the ``src/<repo>`` rule.

    Derived from where the repo actually sits, not from ``dev.workspace_folder``,
    so the same rule holds inside the container (``/ws/src/<repo>`` -> ``/ws``)
    and for a host checkout (its own root)."""
    if root.parent.name == "src":
        return root.parent.parent
    if root.name == "src":
        return root.parent
    return root


def _require_docker(ctx: Context) -> None:
    """Fail with a diagnosis, not a stack trace, when docker cannot run.

    Two distinct failures, two distinct hints: no client on PATH at all, and a
    client with no daemon behind it — the everyday WSL2 trap, where Docker
    Desktop is stopped or its WSL integration is off for this very distro and
    every `docker` call dies with a socket error the user has seen ten times
    without ever reading.
    """
    ctx.runner.require(
        "docker", hint="install Docker Engine, or enable Docker Desktop's WSL integration"
    )
    if ctx.dry_run:
        return
    probe = ctx.runner.run(
        ["docker", "info", "--format", "{{.ServerVersion}}"], check=False, quiet=True
    )
    if probe.ok:
        return
    if HostFacts.probe().wsl_kernel:
        hint = (
            "WSL2: start Docker Desktop on Windows and check Settings > Resources > "
            "WSL integration is enabled for THIS distro — or install Docker Engine "
            "inside the distro"
        )
    else:
        hint = (
            "start the daemon (`sudo systemctl start docker`) and check your user "
            "is in the `docker` group"
        )
    raise ArdtError("docker is installed but its daemon is not reachable", hint=hint)


@click.group()
def dev() -> None:
    """Render and drive the dev container this repo builds in."""


def _plan(ctx: Context, *, ardt_source: str | None) -> Render:
    return render_module.build(
        ctx.project,
        ctx.cfg,
        dev_config(ctx.cfg),
        ardt_source=ardt_source,
    )


def _relative_source(root: Path, source: Path) -> str:
    """A local checkout as a path relative to ``.devcontainer/`` when possible.

    Relative keeps the render machine-independent for the common layout (the
    ardt checkout next to the repo), which is what lets the same rendered
    compose file work on a colleague's machine.
    """
    base = (root / DEVCONTAINER_DIR).resolve()
    return os.path.relpath(source.resolve(), base)


def _remembered_source(ctx: Context) -> str | None:
    manifest_path = ctx.project_root / render_module.MANIFEST
    if not manifest_path.is_file():
        return None
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    source = data.get("ardt_source") if isinstance(data, dict) else None
    return source if isinstance(source, str) else None


@dev.command()
@click.option(
    "--ardt-source",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Mount a local ardt checkout and install from it (dev twin of `--arg ardt_source=`).",
)
@click.option(
    "--from-pin",
    is_flag=True,
    help="Install ardt from the repo's `ardt:` pin, dropping a remembered local checkout.",
)
@click.option("--force", is_flag=True, help="Overwrite files ardt did not generate.")
@pass_ardt
def sync(ctx: Context, ardt_source: Path | None, from_pin: bool, force: bool) -> None:
    """Render `.devcontainer/` + `.vscode/` (gitignored) from the profile and this repo's config."""
    if ardt_source is not None and from_pin:
        raise ArdtError("--ardt-source and --from-pin are mutually exclusive")

    source: str | None = None
    if ardt_source is not None:
        source = _relative_source(ctx.project_root, ardt_source)
    elif not from_pin:
        source = _remembered_source(ctx)

    plan = _plan(ctx, ardt_source=source)
    if ctx.dry_run:
        ctx.console.info(f"[dry-run] would render {len(plan.files)} files:")
        for name in sorted(plan.files):
            ctx.console.info(f"  {name}")
        return

    result = render_module.write(ctx.project_root, plan, force=force)
    ignored = render_module.ensure_gitignored(ctx.project_root)

    ctx.emit(
        profile=plan.profile.name,
        base_image=plan.base_image,
        host=plan.host.kind,
        ardt_source=plan.ardt_source,
        requirements=list(plan.requirements),
        written=result.written,
        unchanged=result.unchanged,
    )
    if ctx.json_output:
        return

    console = ctx.console
    console.step(f"profile {plan.profile.name} · host {plan.host.kind} · {plan.distro}")
    console.info(f"base image   {plan.base_image}")
    console.info(f"ardt         {plan.ardt_source or 'from the ardt: pin'}")
    for name in sorted(result.written):
        console.info(f"  wrote     {name}")
    if result.unchanged:
        console.info(f"  unchanged {len(result.unchanged)} file(s)")
    for entry in ignored:
        console.info(f"  ignored   {entry}")
    for note in plan.host.notes:
        console.warn(note)
    console.success("run `ardt dev up` (or VS Code: Reopen in Container)")


@dev.command(name="host-config")
@pass_ardt
def host_config(ctx: Context) -> None:
    """Re-derive only the host overlay. Runs as the devcontainer's initializeCommand."""
    plan = _plan(ctx, ardt_source=_remembered_source(ctx))
    result = render_module.write(ctx.project_root, plan, force=True, only=plan.host_files)
    ctx.emit(host=plan.host.kind, written=result.written)
    if not ctx.json_output:
        ctx.console.info(f"host {plan.host.kind}: {COMPOSE_HOST} up to date")
        for note in plan.host.notes:
            ctx.console.warn(note)


def _ensure_volumes(ctx: Context, plan: Render) -> list[str]:
    """Create what compose will not create itself, and return what was touched.

    Two gaps, both by design elsewhere: an ``external:`` volume is compose's cue
    that something else owns it (which is exactly what keeps `--purge`
    repo-scoped), and Docker refuses to mount a subpath that does not exist
    rather than creating it (moby#47842). Both are fixed with a `docker volume
    create` and one throwaway `mkdir` container, all idempotent.
    """
    touched: list[str] = []
    for name in plan.shared_volumes:
        ctx.runner.run(["docker", "volume", "create", name], quiet=True)
        touched.append(name)
    if plan.colcon_volume:
        ctx.runner.run(["docker", "volume", "create", plan.colcon_volume], quiet=True)
        # The provisioning image is the one this repo pulls anyway, so this
        # costs no extra download.
        ctx.runner.run(
            [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{plan.colcon_volume}:/volume",
                plan.provision_image,
                "mkdir",
                "-p",
                *[f"/volume/{name}" for name in render_module.COLCON_DIRS],
            ],
            quiet=True,
        )
        touched.append(plan.colcon_volume)
    return touched


@dev.command(name="volumes")
@pass_ardt
def volumes(ctx: Context) -> None:
    """Create the shared caches and the colcon volume's subpaths. Idempotent."""
    _require_docker(ctx)
    plan = _plan(ctx, ardt_source=_remembered_source(ctx))
    touched = _ensure_volumes(ctx, plan)
    ctx.emit(volumes=touched, shared=list(plan.shared_volumes))
    if ctx.json_output:
        return
    for name in touched:
        scope = "shared" if name in plan.shared_volumes else "this repo"
        ctx.console.info(f"  {name:32} ({scope})")


def _compose_argv(ctx: Context) -> list[str]:
    for name in (COMPOSE, COMPOSE_HOST):
        if not (ctx.project_root / name).is_file():
            raise ArdtError(f"{name} is missing", hint="run `ardt dev sync` first")
    _require_docker(ctx)
    return [
        "docker",
        "compose",
        "-f",
        str(ctx.project_root / COMPOSE),
        "-f",
        str(ctx.project_root / COMPOSE_HOST),
    ]


def _ensure_synced(ctx: Context) -> Render:
    """Render (or refresh) the environment before driving it.

    `ardt dev up` on a fresh clone must just work: nothing about `sync` needs a
    human decision, so `up` and `open` run it implicitly — render what is
    missing or stale, refuse hand-edited files with sync's own message, no-op
    when everything already matches. Kept out of --dry-run, which must not
    write.
    """
    plan = _plan(ctx, ardt_source=_remembered_source(ctx))
    if ctx.dry_run:
        return plan
    state = render_module.audit(ctx.project_root, plan)
    if state.written or state.conflicts:
        result = render_module.write(ctx.project_root, plan)  # refuses hand-edits
        render_module.ensure_gitignored(ctx.project_root)
        ctx.console.step(f"synced {len(result.written)} dev file(s) (implicit `ardt dev sync`)")
        for name in sorted(result.written):
            ctx.console.detail(f"  wrote {name}")
    return plan


@dev.command()
@click.option("--build", is_flag=True, help="Rebuild the dev image before starting.")
@click.option("--no-bootstrap", is_flag=True, help="Start without running postCreate.")
@pass_ardt
def up(ctx: Context, build: bool, no_bootstrap: bool) -> None:
    """Start the dev container, rendering and provisioning whatever is missing first."""
    plan = _ensure_synced(ctx)
    compose = _compose_argv(ctx)
    source = dev_config(ctx.cfg).source_folder(ctx.project)
    if build:
        with ctx.console.section("docker compose build"):
            ctx.runner.run([*compose, "build"])
    # Before `up`, not after: compose fails on a missing external volume, and
    # the container fails to start on a missing subpath.
    ctx.console.step("provisioning docker volumes (shared caches + this repo's colcon volume)")
    _ensure_volumes(ctx, plan)
    with ctx.console.section("compose up — the first run builds the dev image (minutes)"):
        ctx.runner.run([*compose, "up", "-d"])
    if no_bootstrap:
        return
    with ctx.console.section("postCreate — rosdep + `ardt deps` (minutes on first run)"):
        ctx.runner.run(
            [
                *compose,
                "exec",
                "-u",
                USER,
                "-w",
                source,
                "dev",
                "bash",
                POST_CREATE,
            ]
        )
    ctx.console.success("dev container ready — `ardt dev shell`, or `ardt dev open` for VS Code")


def _code_argv(ctx: Context, plan: Render, workspace: str) -> list[str]:
    """`code` opening the container directly, via a hand-built remote URI."""
    ctx.runner.require(
        "code",
        hint=(
            "install VS Code's `code` command (Shell Command: Install 'code' in PATH), "
            "or the Dev Containers CLI for `devcontainer open`"
        ),
    )
    host_path = host_module.editor_host_path(ctx.project_root, plan.host_facts)
    if host_path is None:
        raise ArdtError(
            "WSL2 without WSL_DISTRO_NAME: cannot say which distro holds this repo",
            hint="run `ardt dev open` from a WSL shell, or open the folder in VS Code by hand",
        )
    return ["code", "--folder-uri", host_module.folder_uri(host_path, workspace)]


def _open_editor(ctx: Context, plan: Render, workspace: str) -> str:
    """Open the editor on the container, best option first. Returns what ran.

    `devcontainer open` is the supported entry point, but only the CLI installed
    *from VS Code* has it — npm's `@devcontainers/cli` dropped `open` to stay
    editor-agnostic, and the two are the same binary name on PATH. So the probe
    cannot be trusted: try it, and treat a failure as "this is the other one"
    rather than as the end of the road.
    """
    if ctx.runner.which("devcontainer"):
        argv = ["devcontainer", "open", str(ctx.project_root)]
        if ctx.runner.run(argv, check=False, quiet=True).ok:
            return argv[0]
        ctx.console.detail("`devcontainer open` failed (npm CLI has no `open`) — using `code`")
    ctx.runner.run(_code_argv(ctx, plan, workspace))
    return "code"


@dev.command(name="open")
@click.option("--build", is_flag=True, help="Rebuild the dev image before opening.")
@pass_ardt
def open_command(ctx: Context, build: bool) -> None:
    """Open VS Code attached to the dev container, rendering and starting it if needed."""
    plan = _ensure_synced(ctx)
    compose = _compose_argv(ctx)
    cfg = dev_config(ctx.cfg)

    if build:
        if cfg.image:
            raise ArdtError(
                f"nothing to build: dev.image pins {cfg.image}",
                hint="drop `dev.image` from ardt.yaml to build the rendered recipe locally",
            )
        with ctx.console.section("docker compose build"):
            ctx.runner.run([*compose, "build"])
    ctx.console.step("provisioning docker volumes (shared caches + this repo's colcon volume)")
    _ensure_volumes(ctx, plan)
    # Start it ourselves so --build is deterministic. VS Code still owns
    # postCreate: it runs postCreateCommand the first time it attaches,
    # whoever created the container.
    with ctx.console.section("compose up — the first run builds the dev image (minutes)"):
        ctx.runner.run([*compose, "up", "-d"])

    editor = _open_editor(ctx, plan, cfg.workspace_folder)
    ctx.emit(editor=editor, workspace_folder=cfg.workspace_folder)
    if not ctx.json_output:
        ctx.console.success(f"opening {cfg.workspace_folder} in the dev container ({editor})")
        ctx.console.info("first attach runs postCreate in VS Code (rosdep + `ardt deps` — minutes)")


@dev.command()
@pass_ardt
def shell(ctx: Context) -> None:
    """Open a login shell in the running dev container, at the workspace root."""
    argv = [
        *_compose_argv(ctx),
        "exec",
        "-u",
        USER,
        "-w",
        dev_config(ctx.cfg).workspace_folder,  # /ws — build/ and src/ in view
        "dev",
        "bash",
        "-l",
    ]
    if ctx.dry_run:
        ctx.console.info("[dry-run] " + " ".join(argv))
        return
    # The Runner pipes output, which is exactly wrong for an interactive shell:
    # hand the terminal over to docker instead of proxying it.
    os.execvp(argv[0], argv)


@dev.command()
@click.option("--purge", is_flag=True, help="Also delete this repo's colcon volume.")
@click.option(
    "--purge-shared",
    is_flag=True,
    help="Also delete the machine-wide caches — every repo's, not just this one's.",
)
@pass_ardt
def down(ctx: Context, purge: bool, purge_shared: bool) -> None:
    """Stop the dev container. Volumes survive unless --purge.

    `--purge` is repo-scoped by construction: the shared caches are `external:`,
    so compose leaves them alone however hard `down` is asked to clean. Wiping
    ccache, the apt archives and the Claude Code login for *every* repo on this
    machine takes the separate --purge-shared, because it is a separate decision.
    """
    plan = _plan(ctx, ardt_source=_remembered_source(ctx))
    argv = [*_compose_argv(ctx), "down"]
    if purge:
        argv.append("--volumes")
    ctx.runner.run(argv)
    if not purge_shared:
        return
    for name in plan.shared_volumes:
        ctx.runner.run(["docker", "volume", "rm", "--force", name], quiet=True)
    ctx.console.warn(f"removed the machine-wide caches: {', '.join(plan.shared_volumes)}")


@dev.command()
@pass_ardt
def bootstrap(ctx: Context) -> None:
    """Prepare the container: volume ownership, then the profile's create steps."""
    if not _in_container():
        raise ArdtError(
            "`ardt dev bootstrap` runs inside the dev container",
            hint="use `ardt dev up` from the host, which runs it for you",
        )
    cfg = dev_config(ctx.cfg)
    prof = profile(cfg.profile)
    distro = ros_distro(ctx.cfg)

    if cfg.isolate_build_dirs:
        _claim_volume_dirs(ctx)
    for step in prof.bootstrap:
        command = [part.replace(DISTRO, distro) for part in step]
        with ctx.console.section(" ".join(command)):
            ctx.runner.run(command)
    ctx.console.success("container ready — `ardt build`, then `ardt test`")


def _in_container() -> bool:
    """The image sets the marker; /.dockerenv covers a container ardt was pip-installed into."""
    return env_module.flag(IN_CONTAINER_ENV) or Path("/.dockerenv").exists()


def _claim_volume_dirs(ctx: Context) -> None:
    """Named volumes mount root-owned; the workspace user has to own them.

    Only the colcon output dirs — at the *workspace root*, beside ``src/`` —
    the seeded volumes (ccache, Claude state, the apt cache) keep their image
    ownership on purpose: apt downloads as ``_apt`` and warns loudly if its
    archive dir belongs to someone else.
    """
    base = _workspace_root(ctx.project_root)
    dirs = [base / name for name in ("build", "install", "log") if (base / name).is_dir()]
    owned = [path for path in dirs if not os.access(path, os.W_OK)]
    if owned:
        ctx.runner.run(["sudo", "chown", f"{os.getuid()}:{os.getgid()}", *[str(p) for p in owned]])
    if ctx.dry_run:
        return
    for path in dirs:
        # colcon writes these markers itself on first use; pre-created volume
        # dirs get them up front so `colcon list` from the workspace root never
        # rediscovers installed packages as sources.
        (path / "COLCON_IGNORE").touch(exist_ok=True)


@dev.command(name="compile-commands")
@pass_ardt
def compile_commands(ctx: Context) -> None:
    """Merge colcon's per-package compile_commands.json into one for clangd."""
    build_dir = _workspace_root(ctx.project_root) / "build"
    parts = sorted(build_dir.glob("*/compile_commands.json"))
    if not parts:
        raise ArdtError(
            f"no per-package compile_commands.json under {build_dir}",
            hint="run `ardt build` first (the dev image exports them by default)",
        )
    entries: list[object] = []
    for part in parts:
        loaded = json.loads(part.read_text(encoding="utf-8"))
        if isinstance(loaded, list):
            entries.extend(loaded)  # type: ignore[arg-type]
    target = build_dir / "compile_commands.json"
    target.write_text(json.dumps(entries, indent=1) + "\n", encoding="utf-8")
    ctx.emit(compile_commands=str(target), packages=len(parts), entries=len(entries))
    ctx.console.success(f"{len(entries)} entries from {len(parts)} package(s) -> {target}")


@dev.command()
@pass_ardt
def doctor(ctx: Context) -> None:
    """Check the dev environment against CI: base image, ardt pin, render, host."""
    plan = _plan(ctx, ardt_source=_remembered_source(ctx))
    checks: list[tuple[str, str, str]] = []  # (level, label, detail)

    def check(level: str, label: str, detail: str) -> None:
        checks.append((level, label, detail))

    builder = ci_builder(ctx.cfg)
    if builder is None:
        check(
            "warn",
            "CI parity",
            "repo sets no pipelines.ros_ci.builder — nothing to compare the dev base against",
        )
    elif builder == plan.base_image:
        check("ok", "CI parity", f"dev base == ros_ci.builder ({builder})")
    else:
        check("fail", "CI parity", f"dev base {plan.base_image} != ros_ci.builder {builder}")

    if ctx.cfg.ardt.version:
        check("ok", "ardt pin", f"{ctx.cfg.ardt.git}@{ctx.cfg.ardt.version}")
    else:
        check("warn", "ardt pin", "ardt.version unset: container and CI both track HEAD")
    if plan.ardt_source:
        check("warn", "ardt source", f"local checkout {plan.ardt_source} (not the pin)")

    state = render_module.audit(ctx.project_root, plan)
    if state.conflicts:
        check("fail", "render", f"hand-edited: {', '.join(sorted(state.conflicts))}")
    elif state.written:
        check("warn", "render", f"stale, run `ardt dev sync`: {', '.join(sorted(state.written))}")
    else:
        check("ok", "render", f"{len(state.unchanged)} files match this ardt-dev")

    missing = render_module.missing_gitignore_entries(ctx.project_root)
    check(
        "fail" if missing else "ok",
        "gitignore",
        f"NOT ignored: {', '.join(missing)}" if missing else "the whole render is ignored",
    )

    check("ok", "host", f"{plan.host.kind}, gui {'on' if plan.host.gui else 'off'}")
    for note in plan.host.notes:
        check("warn", "host", note)

    if not _in_container():
        if ctx.runner.which("docker") is None:
            check("fail", "docker", "not on PATH")
        else:
            probe = ctx.runner.run(
                ["docker", "info", "--format", "{{.ServerVersion}}"], check=False, quiet=True
            )
            if probe.ok:
                check("ok", "docker", f"daemon up (server {probe.tail.strip()})")
            else:
                check(
                    "fail",
                    "docker",
                    "client on PATH but the daemon is unreachable "
                    "(WSL2: Docker Desktop running, WSL integration on for this distro?)",
                )

    ctx.emit(checks=[{"level": lvl, "check": label, "detail": d} for lvl, label, d in checks])
    if not ctx.json_output:
        for level, label, detail in checks:
            line = f"{label:12} {detail}"
            if level == "ok":
                ctx.console.success(line)
            elif level == "warn":
                ctx.console.warn(line)
            else:
                ctx.console.error(line)
    failures = [label for level, label, _ in checks if level == "fail"]
    if failures:
        raise ArdtError(
            f"{len(failures)} dev environment check(s) failed: {', '.join(sorted(set(failures)))}",
            hint="`ardt dev sync` fixes render and gitignore drift",
        )


@dev.command(name="profiles")
@pass_ardt
def profiles_command(ctx: Context) -> None:
    """List the dev profiles this ardt knows."""
    ctx.emit(profiles={name: p.summary for name, p in PROFILES.items()})
    if ctx.json_output:
        return
    active = dev_config(ctx.cfg).profile
    for name, prof in sorted(PROFILES.items()):
        marker = "*" if name == active else " "
        ctx.console.info(f"{marker} {name:10} {prof.summary}")
