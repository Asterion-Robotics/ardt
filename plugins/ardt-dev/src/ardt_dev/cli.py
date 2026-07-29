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

from ardt_core.cli import pass_ardt
from ardt_core.config import workspace_root
from ardt_core.context import Context
from ardt_core.errors import ArdtError

from . import checks as checks_module
from . import docker as docker_module
from . import host as host_module
from . import manifest as manifest_module
from . import render as render_module
from .config import DEVCONTAINER_DIR, WORKSPACE_FOLDER, dev_config, ros_distro
from .config import source_folder as container_source_folder
from .profiles import DISTRO, PROFILES, profile
from .render import (
    COMPOSE_HOST,
    POST_CREATE,
    USER,
    Render,
)


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
    manifest_path = ctx.project_root / manifest_module.MANIFEST
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

    result = manifest_module.write(ctx.project_root, plan, force=force)
    ignored = manifest_module.ensure_gitignored(ctx.project_root)

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
    result = manifest_module.write(ctx.project_root, plan, force=True, only=plan.host_files)
    ctx.emit(host=plan.host.kind, written=result.written)
    if not ctx.json_output:
        ctx.console.info(f"host {plan.host.kind}: {COMPOSE_HOST} up to date")
        for note in plan.host.notes:
            ctx.console.warn(note)


@dev.command(name="volumes")
@pass_ardt
def volumes(ctx: Context) -> None:
    """Create the shared caches and the colcon volume's subpaths. Idempotent."""
    docker_module.require_docker(ctx)
    plan = _plan(ctx, ardt_source=_remembered_source(ctx))
    touched = docker_module.ensure_volumes(ctx, plan)
    ctx.emit(volumes=touched, shared=list(plan.shared_volumes))
    if ctx.json_output:
        return
    for name in touched:
        scope = "shared" if name in plan.shared_volumes else "this repo"
        ctx.console.info(f"  {name:32} ({scope})")


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
    state = manifest_module.audit(ctx.project_root, plan)
    if state.written or state.conflicts:
        result = manifest_module.write(ctx.project_root, plan)  # refuses hand-edits
        manifest_module.ensure_gitignored(ctx.project_root)
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
    compose = docker_module.compose_argv(ctx)
    source = container_source_folder(ctx.project)
    if build:
        with ctx.console.section("docker compose build"):
            ctx.runner.run([*compose, "build"])
    # Before `up`, not after: compose fails on a missing external volume, and
    # the container fails to start on a missing subpath.
    ctx.console.step("provisioning docker volumes (shared caches + this repo's colcon volume)")
    docker_module.ensure_volumes(ctx, plan)
    with ctx.console.section("compose up — the first run builds the dev image (minutes)"):
        ctx.runner.run([*compose, "up", "-d"])
    if no_bootstrap:
        ctx.emit(compose_up=True, image_built=build, bootstrapped=False)
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
    ctx.emit(compose_up=True, image_built=build, bootstrapped=True)
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
    compose = docker_module.compose_argv(ctx)
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
    docker_module.ensure_volumes(ctx, plan)
    # Start it ourselves so --build is deterministic. VS Code still owns
    # postCreate: it runs postCreateCommand the first time it attaches,
    # whoever created the container.
    with ctx.console.section("compose up — the first run builds the dev image (minutes)"):
        ctx.runner.run([*compose, "up", "-d"])

    editor = _open_editor(ctx, plan, WORKSPACE_FOLDER)
    ctx.emit(editor=editor, workspace_folder=WORKSPACE_FOLDER)
    if not ctx.json_output:
        ctx.console.success(f"opening {WORKSPACE_FOLDER} in the dev container ({editor})")
        ctx.console.info("first attach runs postCreate in VS Code (rosdep + `ardt deps` — minutes)")


@dev.command()
@pass_ardt
def shell(ctx: Context) -> None:
    """Open a login shell in the running dev container, at the workspace root."""
    argv = [
        *docker_module.compose_argv(ctx),
        "exec",
        "-u",
        USER,
        "-w",
        WORKSPACE_FOLDER,  # build/ and src/ in view
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
    argv = [*docker_module.compose_argv(ctx), "down"]
    if purge:
        argv.append("--volumes")
    ctx.runner.run(argv)
    ctx.emit(down=True, purged=purge, purged_shared=purge_shared)
    if not purge_shared:
        return
    for name in plan.shared_volumes:
        ctx.runner.run(["docker", "volume", "rm", "--force", name], quiet=True)
    ctx.console.warn(f"removed the machine-wide caches: {', '.join(plan.shared_volumes)}")


@dev.command()
@pass_ardt
def bootstrap(ctx: Context) -> None:
    """Prepare the container: volume ownership, then the profile's create steps."""
    if not docker_module.in_container():
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
    ctx.emit(profile=cfg.profile, bootstrap_steps=len(prof.bootstrap))
    ctx.console.success("container ready — `ardt build`, then `ardt test`")


def _claim_volume_dirs(ctx: Context) -> None:
    """Named volumes mount root-owned; the workspace user has to own them.

    Only the colcon output dirs — at the *workspace root*, beside ``src/`` —
    the seeded volumes (ccache, Claude state, the apt cache) keep their image
    ownership on purpose: apt downloads as ``_apt`` and warns loudly if its
    archive dir belongs to someone else.
    """
    base = workspace_root(ctx.project_root)
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
    build_dir = workspace_root(ctx.project_root) / "build"
    parts = sorted(build_dir.glob("*/compile_commands.json"))
    if not parts:
        raise ArdtError(
            f"no per-package compile_commands.json under {build_dir}",
            hint="run `ardt build` first (the dev image exports them by default)",
        )
    entries: list[object] = []
    for part in parts:
        try:
            loaded = json.loads(part.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ArdtError(
                f"{part} is not valid JSON: {exc}",
                hint="rebuild the package (`ardt build`) to regenerate it",
            ) from exc
        if isinstance(loaded, list):
            entries.extend(loaded)  # type: ignore[arg-type]
    target = build_dir / "compile_commands.json"
    if ctx.dry_run:
        ctx.console.info(f"[dry-run] would merge {len(parts)} file(s) into {target}")
        return
    target.write_text(json.dumps(entries, indent=1) + "\n", encoding="utf-8")
    ctx.emit(compile_commands=str(target), packages=len(parts), entries=len(entries))
    ctx.console.success(f"{len(entries)} entries from {len(parts)} package(s) -> {target}")


@dev.command()
@pass_ardt
def doctor(ctx: Context) -> None:
    """Check the dev environment against CI: base image, ardt pin, render, host."""
    plan = _plan(ctx, ardt_source=_remembered_source(ctx))
    checks = checks_module.run_checks(ctx, plan)
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
