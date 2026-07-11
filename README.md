# ardt

> The company-wide developer/CI CLI platform: **one small core, everything else a plugin.**
> Robotics or not — the core knows nothing about ROS; ROS-ness itself is a plugin.

This repo implements milestones **B0–B1** of the [CI-tools spec](https://…/docs/ci_tools)
(the `aos_poc/docs/ci_tools` design set): the uv workspace, a fully-typed
`ardt-core`, and the first task plugin, `ardt-tasks-ros`. The Dagger pipeline plane
(`ardt-pipelines`), the domain plugin (`ardt-aos`), and the pinned base images come
in later milestones (B3–B4, T3).

> **Name note.** The design docs use the working name *turret*; the chosen name is
> **ardt** — *Asterion Robotics Development Tools*. A greenfield project, starting
> at **0.0.0**. Reserve the PyPI name (spec T0.1) before the first publish.

## The two-plane model

| Plane | What it is | Where it runs | Package |
|---|---|---|---|
| **tasks** | `ardt build` / `test` / `deps` … | wherever invoked — dev shell, devcontainer, CI container | `ardt-tasks-*` |
| **pipelines** | `ardt pipe run <name>` | orchestrate containers/registries/services via Dagger | `ardt-pipelines` *(later)* |

Pipelines call tasks *inside* containers; tasks never call pipelines. Core imports
neither ROS nor Dagger, so installing it never drags in an engine.

## Layout

```
ardt/
├── packages/                # each package owns its unit tests (<pkg>/tests/)
│   ├── ardt-core/           # cli, plugin loader, context, config, runner, console, version policy
│   ├── ardt-tasks-ros/      # deps / build / test (colcon, rosdep, vcs) — in-env tasks
│   ├── ardt-pipelines/      # the generic Dagger plane: `ardt pipe`, @pipeline registry, std helpers
│   └── ardt-pipelines-ros/  # ROS 2 pipeline plugin: ros-ci + the ros2 image recipe
├── tests/                # cross-package only: policy sweeps + docker-marked integration
└── .github/workflows/    # bootstrap CI (lint + format + pyright strict + coverage gate)
```

Shared test fixtures (`repo`, `console`, CI-env isolation) ship as
`ardt_core.testing` — third-party plugins get them the same way our own
packages do.

## Installation

`ardt` is a CLI you call from any repo, so install it **once as a uv tool** — a
persistent, isolated venv with `ardt` on your PATH; no `uv run` prefix, no
project venv needed:

```bash
# From a checkout (developers): editable, so source edits apply immediately
uv tool install --editable ./packages/ardt-core \
    --with-editable ./packages/ardt-tasks-ros \
    --with-editable ./packages/ardt-pipelines \
    --with-editable ./packages/ardt-pipelines-ros

# From git (users, until PyPI publication):
uv tool install "ardt-core @ git+https://github.com/Asterion-Robotics/ardt.git#subdirectory=packages/ardt-core" \
    --with "ardt-tasks-ros @ git+https://github.com/Asterion-Robotics/ardt.git#subdirectory=packages/ardt-tasks-ros" \
    --with "ardt-pipelines @ git+https://github.com/Asterion-Robotics/ardt.git#subdirectory=packages/ardt-pipelines" \
    --with "ardt-pipelines-ros @ git+https://github.com/Asterion-Robotics/ardt.git#subdirectory=packages/ardt-pipelines-ros"

ardt --help    # from anywhere
```

> **Why not `uvx`?** `uvx ardt` is *run-without-install*: it resolves the package
> from PyPI into a temporary environment on every invocation. That's the right
> tool for one-off runs of published CLIs (and `uvx ardt@1.2` will be great for
> pinned CI shims once ardt is on PyPI), but wrong for a daily driver: it can't
> see an unpublished workspace, it re-resolves per call, and plugins you
> `--with`-ed don't persist. `uv tool install` is the "install once, use
> everywhere" path — the spec's own distribution model (01 §6).

## Quick start

```bash
ardt info                  # dump the resolved context
ardt plugins               # what's loaded, from where, at which API version
ardt build --dry-run       # print the plan; run nothing
ardt pipe list             # registered pipelines
ardt pipe run ros-ci       # containerized build+test via Dagger (needs docker)
ardt info --json           # machine-readable envelope on stdout (diagnostics on stderr)
```

> **Local dev on a machine with ROS sourced:** a sourced ROS overlay puts
> `/opt/ros/<distro>` on `PYTHONPATH`, whose pytest plugins can break collection.
> Run the test suite with `PYTHONPATH= uv run pytest`. CI containers have no ROS,
> so this only bites local runs.

## Two conventions every command honors

- `--dry-run` — print the plan, execute nothing. Core-injected into every command,
  including plugin-provided ones.
- `--json` — a machine-readable result envelope on **stdout**; all human output and
  diagnostics stay on **stderr**, so `ardt <cmd> --json | jq` always works.

## Configuration

One file per repo — `ardt.yaml` (or a `[tool.ardt]` table in `pyproject.toml`; the
file wins). Sections are namespaced per plugin. See [ardt.example.yaml](ardt.example.yaml).

## Quality bar

Python ≥ 3.11, uv for everything, ruff (lint + format), **pyright strict on
`ardt-core`**, pytest with a **≥ 90 % coverage gate on core**. All enforced in CI:

```bash
PYTHONPATH= uv run ruff check . && uv run ruff format --check .
PYTHONPATH= uv run pyright packages/ardt-core/src
PYTHONPATH= uv run pytest --cov=ardt_core --cov-report=term-missing
```

## Status vs. the spec

- ✅ B0 workspace, bootstrap CI, quality gate
- ✅ B1 `ardt-core` (cli, plugin loader + `ARDT_PLUGIN_API` guard, context, config,
  runner, console, `ctx.version` tag policy) — core coverage ≥ 90 %
- ✅ B2 (partial) `ardt-tasks-ros` `deps`/`build`/`test` — verified on the
  [ardt_ros2_demo](https://github.com/Asterion-Robotics/ardt_ros2_demo) repo, host
  + jazzy container; a green run on `aos_edge` still to be done
- ✅ B3 (partial) `ardt-pipelines`: `@pipeline` registry, `ardt pipe list/run`,
  exact `dagger-io` pin, std helpers, interim `ros-ci` (runs the ardt tasks
  inside the builder, exports JUnit, publishes on tag) — verified against a real
  engine. Missing: the persistent-engine runner setup (T2.3), dogfood (T2.4)
- ⏳ B4 `aos-ros-base` + tool image + dogfood, T3 `ardt-aos` — not yet.

## License

Apache-2.0. See [LICENSE](LICENSE).
