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
├── packages/
│   ├── ardt-core/         # cli, plugin loader, context, config, runner, console, version policy
│   └── ardt-tasks-ros/    # deps / build / test (colcon, rosdep, vcs) — the first plugin
├── tests/                # unit suite (marked; unit runs anywhere, integration needs docker)
└── .github/workflows/    # bootstrap CI (lint + format + pyright strict + coverage gate)
```

## Quick start

```bash
uv sync
uv run ardt --help
uv run ardt info            # dump the resolved context
uv run ardt plugins         # what's loaded, from where, at which API version
uv run ardt build --dry-run # print the plan; run nothing
uv run ardt info --json     # machine-readable envelope on stdout (diagnostics go to stderr)
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
- ✅ B2 (partial) `ardt-tasks-ros` `deps`/`build`/`test` — green run on an
  `aos_edge` checkout (host + jazzy container) still to be done
- ⏳ B3 `ardt-pipelines` (Dagger plane), B4 `aos-ros-base` + dogfood, T3 `ardt-aos` — not yet.

## License

Apache-2.0. See [LICENSE](LICENSE).
