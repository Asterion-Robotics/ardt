# ardt

> The company-wide developer/CI CLI platform: **one small core, everything else a plugin.**
> Robotics or not — the core knows nothing about ROS; ROS-ness itself is a plugin.

The uv workspace, a fully-typed `ardt-core`, the task plugins, and an interim
Dagger pipeline plane. The domain plugin (`ardt-aos`) and the pinned base images
come later — see [Status](#status).

> **Name note.** The chosen name is **ardt** — *Asterion Robotics Development
> Tools*. A greenfield project, first tagged **v0.0.1**. Reserve the PyPI name
> before the first publish.

## Versioning

**The git tag is the only version that exists.** No file in this repo states one:
every `pyproject.toml` is `dynamic = ["version"]` via `hatch-vcs`, and every
package's `__version__` reads its installed metadata. So a release is one command
and there is nothing to keep in sync:

```bash
git tag v0.1.0 && git push --tags
```

Reading it back:

| Where | Command | Source |
|---|---|---|
| the working tree | `ardt info` | `ctx.version` → `git describe` |
| the installed CLI | `ardt --version` | metadata stamped at build time |
| the tag itself | `git describe --tags --dirty` | git |

Two formats meet here and agree **on a clean tag** — the only publishable state,
which is what `is_release()` gates on. Off-tag they differ cosmetically:
`hatch-vcs` emits `0.1.0.post1.dev3+g0a1b2c3`, `ctx.version` emits
`0.1.0.dev3+g0a1b2c3`. Both are PEP 440 and both name the same commit.

A checkout without `.git` (GitHub's "Download ZIP") builds as `0.0.0` via
`fallback-version` rather than failing. `pip install git+…` is unaffected: pip
clones, so the tags are there.

## The two-plane model

| Plane | What it is | Where it runs | Package |
|---|---|---|---|
| **tasks** | `ardt build` / `test` / `deps` … | wherever invoked — dev shell, devcontainer, CI container | `ardt-<theme>-tasks` |
| **pipelines** | `ardt pipe run <name>` | orchestrate containers/registries/services via Dagger | `ardt-pipelines` + `ardt-<theme>-pipelines` |

Pipelines call tasks *inside* containers; tasks never call pipelines. Core imports
neither ROS nor Dagger, so installing it never drags in an engine.

## Layout

```
ardt/
├── packages/                # the platform (each package owns its unit tests, <pkg>/tests/)
│   ├── ardt-core/           # cli, plugin loader, context, config, runner, console, version policy
│   └── ardt-pipelines/      # the generic Dagger plane: `ardt pipe`, @pipeline registry, std helpers
├── plugins/                 # first-party theme plugins (ardt-<theme>-tasks / -pipelines)
│   ├── ardt-ros-tasks/      # deps / build / test (colcon, rosdep, vcs) — in-env tasks
│   ├── ardt-ros-pipelines/  # ROS 2 pipeline plugin: ros-ci + the ros2 image recipe
│   ├── ardt-doc-tasks/      # doc build (sphinx preset + doxygen/breathe + ros2-interfaces)
│   ├── ardt-dev/            # `ardt dev`: renders + drives the repo's devcontainer (gitignored)
│   └── ardt-doc-pipelines/  # docs-ci: versioned site (working tree + tags) -> public/
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
    --with-editable ./plugins/ardt-ros-tasks \
    --with-editable ./plugins/ardt-dev \
    --with-editable ./packages/ardt-pipelines \
    --with-editable ./plugins/ardt-ros-pipelines

# From git (users, until PyPI publication):
uv tool install "ardt-core @ git+https://github.com/Asterion-Robotics/ardt.git#subdirectory=packages/ardt-core" \
    --with "ardt-ros-tasks @ git+https://github.com/Asterion-Robotics/ardt.git#subdirectory=plugins/ardt-ros-tasks" \
    --with "ardt-dev @ git+https://github.com/Asterion-Robotics/ardt.git#subdirectory=plugins/ardt-dev" \
    --with "ardt-pipelines @ git+https://github.com/Asterion-Robotics/ardt.git#subdirectory=packages/ardt-pipelines" \
    --with "ardt-ros-pipelines @ git+https://github.com/Asterion-Robotics/ardt.git#subdirectory=plugins/ardt-ros-pipelines"

ardt --help    # from anywhere
```

> **Why not `uvx`?** `uvx ardt` is *run-without-install*: it resolves the package
> from PyPI into a temporary environment on every invocation. That's the right
> tool for one-off runs of published CLIs (and `uvx ardt@1.2` will be great for
> pinned CI shims once ardt is on PyPI), but wrong for a daily driver: it can't
> see an unpublished workspace, it re-resolves per call, and plugins you
> `--with`-ed don't persist. `uv tool install` is the "install once, use
> everywhere" path, which is how ardt is meant to be distributed.

## Quick start

```bash
ardt info                  # dump the resolved context
ardt plugins               # what's loaded, from where, at which API version
ardt build --dry-run       # print the plan; run nothing
ardt pipe list             # registered pipelines
ardt pipe run ros-ci       # containerized build+test via Dagger (needs docker)
ardt dev sync              # render the repo's devcontainer (gitignored) — then `ardt dev up`
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

## Status

- ✅ **Workspace, bootstrap CI, quality gate**
- ✅ **`ardt-core`** — cli, plugin loader + `ARDT_PLUGIN_API` guard, context,
  config, runner, console, `ctx.version` tag policy. Coverage ≥ 90 %
- ✅ **`ardt-ros-tasks`** `deps`/`build`/`test` — verified on the
  [ardt_ros2_demo](https://github.com/Asterion-Robotics/ardt_ros2_demo) repo, host
  and jazzy container. A green run on `aos_edge` is still to be done
- ✅ **`ardt-dev`** — renders and drives the repo's devcontainer
- 🚧 **`ardt-pipelines`** — `@pipeline` registry, `ardt pipe list/run`, exact
  `dagger-io` pin, std helpers, and an interim `ros-ci` (runs the ardt tasks
  inside the builder, exports JUnit, publishes on tag), verified against a real
  engine. Missing: the persistent-engine runner setup, and dogfooding ardt's own
  CI through it
- ⏳ **`aos-ros-base` + the baked tool image**, and the `ardt-aos` domain plugin
  — not started

## License

Apache-2.0. See [LICENSE](LICENSE).
