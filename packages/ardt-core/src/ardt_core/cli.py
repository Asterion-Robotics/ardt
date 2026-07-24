"""The ``ardt`` command line.

Core owns four things here and nothing else:

* the top-level group, into which plugins mount their command groups;
* the two conventions every command honors — ``--dry-run`` and ``--json`` — which
  are *injected* into each command rather than trusted to each author;
* the ``--json`` result envelope, so CI and future tooling can consume any command
  uniformly (stdout is the envelope, diagnostics are on stderr);
* error UX: an expected failure is a one-line diagnosis and a non-zero exit,
  never a traceback.
"""

from __future__ import annotations

import functools
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, TypeVar

import click

from .context import Context
from .errors import ArdtError
from .plugins import Registry, discover
from .version import installed

__version__ = installed("ardt-core")
"""Re-exported for `ardt --version` and the `ardt info` envelope; the value is
the one `ardt_core.__version__` carries, resolved from installed metadata."""

F = TypeVar("F", bound=Callable[..., Any])


@lru_cache(maxsize=1)
def _registry() -> Registry:
    """Discover plugins once per process."""
    return discover()


@dataclass
class State:
    """Global flags, and the lazily-built Context.

    Lazy on purpose: ``ardt --help`` must not shell out to git or read a config file.
    """

    dry_run: bool = False
    json_output: bool = False
    verbose: int = 0
    directory: Path | None = None
    command: str = "ardt"
    _context: Context | None = field(default=None, repr=False)

    def context(self) -> Context:
        if self._context is None:
            self._context = Context.build(
                cwd=self.directory,
                dry_run=self.dry_run,
                json_output=self.json_output,
                verbose=self.verbose,
                registry=_registry(),
            )
        return self._context

    @property
    def built_context(self) -> Context | None:
        """The context if one was built this run, else None (before failures)."""
        return self._context


def _state() -> State:
    return click.get_current_context().ensure_object(State)


def pass_ardt(func: F) -> F:
    """Give a command the :class:`Context` as its first argument."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        state = _state()
        state.command = click.get_current_context().command_path
        return func(state.context(), *args, **kwargs)

    return wrapper  # type: ignore[return-value]


def _set_dry_run(_ctx: click.Context, _param: click.Parameter, value: bool) -> None:
    if value:  # never unset what the group already set
        _state().dry_run = True


def _set_json(_ctx: click.Context, _param: click.Parameter, value: bool) -> None:
    if value:
        _state().json_output = True


_GLOBAL_OPTIONS = (
    click.Option(
        ["--dry-run"],
        is_flag=True,
        expose_value=False,
        callback=_set_dry_run,
        help="Print the plan; run nothing.",
    ),
    click.Option(
        ["--json"],
        is_flag=True,
        expose_value=False,
        callback=_set_json,
        help="Emit a machine-readable result envelope on stdout.",
    ),
)


def _inject_global_options(command: click.Command) -> click.Command:
    """Add ``--dry-run``/``--json`` to a command that does not already declare them."""
    existing = {opt for param in command.params for opt in param.opts}
    for option in _GLOBAL_OPTIONS:
        if not existing.intersection(option.opts):
            command.params.append(option)
    if isinstance(command, click.Group):
        for name in command.list_commands(click.Context(command)):
            sub = command.get_command(click.Context(command), name)
            if sub is not None:
                _inject_global_options(sub)
    return command


class ArdtGroup(click.Group):
    """The top-level group: injects the global conventions, mounts plugin commands."""

    def add_command(self, cmd: click.Command, name: str | None = None) -> None:
        super().add_command(_inject_global_options(cmd), name)

    def _plugin_commands(self) -> dict[str, click.Command]:
        return {
            name: obj
            for name, obj in _registry().commands().items()
            if isinstance(obj, click.Command)
        }

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        found = super().get_command(ctx, cmd_name)
        if found is not None:
            return found
        plugin_command = self._plugin_commands().get(cmd_name)
        if plugin_command is None:
            return None
        return _inject_global_options(plugin_command)

    def list_commands(self, ctx: click.Context) -> list[str]:
        return sorted({*super().list_commands(ctx), *self._plugin_commands()})


@click.group(cls=ArdtGroup, context_settings={"help_option_names": ["-h", "--help"]})
@click.option("--dry-run", is_flag=True, help="Print the plan; run nothing.")
@click.option("--json", "json_output", is_flag=True, help="Machine-readable result envelope.")
@click.option(
    "-C",
    "--directory",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Run as if ardt was started in this directory.",
)
@click.option("-v", "--verbose", count=True, help="Show the commands being run.")
@click.version_option(__version__, "-V", "--version", prog_name="ardt")
@click.pass_context
def cli(
    ctx: click.Context,
    dry_run: bool,
    json_output: bool,
    directory: Path | None,
    verbose: int,
) -> None:
    """ardt — build, test and ship robotics software the same way everywhere."""
    state = ctx.ensure_object(State)
    state.dry_run = state.dry_run or dry_run
    state.json_output = state.json_output or json_output
    state.directory = directory
    state.verbose = verbose


@cli.command()
@pass_ardt
def info(ctx: Context) -> None:
    """Dump the resolved context: project, version, git, CI, plugins."""
    ctx.emit(**ctx.describe())
    if ctx.json_output:
        return
    # Read typed fields off the context directly (not the stringly describe() dict).
    console = ctx.console
    git = ctx.git
    branch = git.branch or "(detached)"
    dirty = " (dirty)" if git.dirty else ""
    console.info(f"project      {ctx.project}")
    console.info(f"root         {ctx.project_root}")
    console.info(f"version      {ctx.version}")
    console.info(f"config       {ctx.config_source.kind}")
    console.info(f"git          {branch} @ {(git.sha or 'none')[:7]}{dirty}")
    console.info(f"ci           {ctx.ci.platform.value}")
    console.info(f"plugins      {len(ctx.registry.plugins)} loaded")


@cli.command(name="plugins")
@pass_ardt
def plugins_command(ctx: Context) -> None:
    """List loaded plugins: what, from where, at which API version."""
    registry = ctx.registry
    ctx.emit(
        plugins=[
            {
                "name": p.name,
                "version": p.version,
                "api": p.api,
                "module": p.module,
                "section": p.section,
                "commands": sorted(p.commands),
                "pipelines": sorted(p.pipelines),
                "templates": sorted(p.templates),
            }
            for p in registry.plugins
        ],
        problems=[{"name": p.name, "reason": p.reason} for p in registry.problems],
    )
    if ctx.json_output:
        return
    if not registry.plugins:
        ctx.console.info("no plugins installed")
    for plugin in registry.plugins:
        provided = ", ".join(
            part
            for part in (
                f"commands: {', '.join(sorted(plugin.commands))}" if plugin.commands else "",
                f"pipelines: {', '.join(sorted(plugin.pipelines))}" if plugin.pipelines else "",
                f"templates: {', '.join(sorted(plugin.templates))}" if plugin.templates else "",
            )
            if part
        )
        ctx.console.info(f"{plugin.name} {plugin.version} (api {plugin.api})  {provided}")
    for problem in registry.problems:
        ctx.console.warn(f"{problem.name}: {problem.reason}")


def _envelope(state: State, *, error: ArdtError | None = None) -> dict[str, object]:
    context = state.built_context
    return {
        "ok": error is None,
        "command": state.command,
        "ardt_version": __version__,
        "project_version": context.version if context else None,
        "data": context.emitted if context else {},
        "error": None if error is None else {"message": error.message, "hint": error.hint},
    }


def _print_envelope(state: State, *, error: ArdtError | None = None) -> None:
    if state.json_output:
        json.dump(_envelope(state, error=error), sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point. Turns expected failures into one-line diagnoses."""
    state = State()
    try:
        cli.main(args=argv, obj=state, prog_name="ardt", standalone_mode=False)
    except ArdtError as exc:
        _fail(state, exc)
        return exc.exit_code
    except click.exceptions.Exit as exc:  # --help, --version
        return exc.exit_code
    except (click.exceptions.Abort, KeyboardInterrupt):
        print("aborted", file=sys.stderr)
        return 130
    except click.ClickException as exc:
        exc.show()
        return exc.exit_code
    _print_envelope(state)
    return 0


def _fail(state: State, exc: ArdtError) -> None:
    context = state.built_context
    if context is not None:
        context.console.error(exc.message, hint=exc.hint)
    else:
        print(f"error: {exc.message}", file=sys.stderr)
        if exc.hint:
            print(f"       {exc.hint}", file=sys.stderr)
    _print_envelope(state, error=exc)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
