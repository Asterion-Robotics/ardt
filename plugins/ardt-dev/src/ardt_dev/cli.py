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

from . import render as render_module
from .config import DEVCONTAINER_DIR, ci_builder, dev_config, ros_distro
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
    manifest_path = ctx.project_root / DEVCONTAINER_DIR / render_module.MANIFEST
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
    """Render `.devcontainer/` (gitignored) from the profile and this repo's config."""
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
            ctx.console.info(f"  {DEVCONTAINER_DIR}/{name}")
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
        console.info(f"  wrote     {DEVCONTAINER_DIR}/{name}")
    if result.unchanged:
        console.info(f"  unchanged {len(result.unchanged)} file(s)")
    if ignored:
        console.info("  wrote     .gitignore entry")
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
        ctx.console.info(f"host {plan.host.kind}: {DEVCONTAINER_DIR}/{COMPOSE_HOST} up to date")
        for note in plan.host.notes:
            ctx.console.warn(note)


def _compose_argv(ctx: Context) -> list[str]:
    directory = ctx.project_root / DEVCONTAINER_DIR
    for name in (COMPOSE, COMPOSE_HOST):
        if not (directory / name).is_file():
            raise ArdtError(
                f"{DEVCONTAINER_DIR}/{name} is missing",
                hint="run `ardt dev sync` first",
            )
    ctx.runner.require(
        "docker",
        hint="install Docker Engine, or enable Docker Desktop's WSL integration",
    )
    return [
        "docker",
        "compose",
        "-f",
        str(directory / COMPOSE),
        "-f",
        str(directory / COMPOSE_HOST),
    ]


@dev.command()
@click.option("--build", is_flag=True, help="Rebuild the dev image before starting.")
@click.option("--no-bootstrap", is_flag=True, help="Start without running postCreate.")
@pass_ardt
def up(ctx: Context, build: bool, no_bootstrap: bool) -> None:
    """Start the dev container and run its create-time bootstrap."""
    compose = _compose_argv(ctx)
    workspace = dev_config(ctx.cfg).workspace_folder
    if build:
        ctx.runner.run([*compose, "build"])
    with ctx.console.section("compose up"):
        ctx.runner.run([*compose, "up", "-d"])
    if no_bootstrap:
        return
    with ctx.console.section("postCreate"):
        ctx.runner.run(
            [
                *compose,
                "exec",
                "-u",
                USER,
                "-w",
                workspace,
                "dev",
                "bash",
                f"{DEVCONTAINER_DIR}/{POST_CREATE}",
            ]
        )


@dev.command()
@pass_ardt
def shell(ctx: Context) -> None:
    """Open a login shell in the running dev container."""
    argv = [
        *_compose_argv(ctx),
        "exec",
        "-u",
        USER,
        "-w",
        dev_config(ctx.cfg).workspace_folder,
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
@click.option("--purge", is_flag=True, help="Also delete the cache volumes (build, ccache, apt).")
@pass_ardt
def down(ctx: Context, purge: bool) -> None:
    """Stop the dev container. Volumes survive unless --purge."""
    argv = [*_compose_argv(ctx), "down"]
    if purge:
        argv.append("--volumes")
    ctx.runner.run(argv)


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

    Only the colcon output dirs: the seeded volumes (ccache, Claude state, the
    apt cache) keep their image ownership on purpose — apt downloads as ``_apt``
    and warns loudly if its archive dir belongs to someone else.
    """
    targets = [
        path
        for path in (ctx.project_root / name for name in ("build", "install", "log"))
        if path.is_dir() and not os.access(path, os.W_OK)
    ]
    if not targets:
        return
    ctx.runner.run(["sudo", "chown", f"{os.getuid()}:{os.getgid()}", *[str(p) for p in targets]])


@dev.command(name="compile-commands")
@pass_ardt
def compile_commands(ctx: Context) -> None:
    """Merge colcon's per-package compile_commands.json into one for clangd."""
    build_dir = ctx.project_root / "build"
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

    ignored = render_module.is_gitignored(ctx.project_root)
    check(
        "ok" if ignored else "fail",
        "gitignore",
        f"{DEVCONTAINER_DIR}/ {'ignored' if ignored else 'is NOT ignored'}",
    )

    check("ok", "host", f"{plan.host.kind}, gui {'on' if plan.host.gui else 'off'}")
    for note in plan.host.notes:
        check("warn", "host", note)

    if not _in_container() and ctx.runner.which("docker") is None:
        check("fail", "docker", "not on PATH")

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
