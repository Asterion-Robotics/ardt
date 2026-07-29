# From clone to open container

One command. Everything it needs (rendering, volumes, the image build) happens on the way.

```bash
git clone <repo> && cd <repo>
ardt dev open            # VS Code attached to the dev container
```

No editor, or a headless machine? Same thing in the terminal:

```bash
ardt dev up              # start the container + run its bootstrap
ardt dev shell           # a login shell inside it
```

The **first** run is slow: it builds the dev image (minutes) and runs `postCreate` (rosdep + `ardt deps`, more minutes). Every run after that takes seconds. Progress is printed step by step; if something stalls, start with `ardt dev doctor`.

## What you get

The container is a canonical colcon workspace at `/ws`. Your repo is one entry under `src/`; `.repos` dependencies land beside it; colcon output lands beside `src/`, **never inside your checkout**:

```text
/ws                      <- VS Code opens here; terminals start here
├── src/
│   ├── <your repo>/     <- your checkout, bind-mounted
│   └── external/        <- `.repos` imports (ardt deps)
├── build/               \
├── install/              > container-local volumes, invisible on your host
└── log/                 /
```

CI builds in the *same tree* (see [parity](parity.md)), so every path in a stack trace or `compile_commands.json` reads the same in both.

Inside, the ordinary commands apply, from anywhere in the workspace:

```bash
ardt build                  # colcon build, bases at /ws
ardt test                   # colcon test + summary
ardt dev compile-commands   # merge per-package compile_commands.json for clangd
```

## Stopping, cleaning

```bash
ardt dev down               # stop; volumes survive
ardt dev down --purge       # also drop this repo's build/install/log volume
```

## When something looks wrong

```bash
ardt dev doctor
```

One pass checks: docker present *and its daemon reachable* (the usual WSL2 trap: Docker Desktop stopped, or its WSL integration off for this distro), CI parity, the ardt pin, render freshness, and the host wiring.

## Prerequisites

- **Docker** — Docker Engine on Linux/WSL2, or Docker Desktop with WSL integration enabled for your distro.
- **ardt** with the `ardt-devcontainers` engine and a profile — `ardt-ros-dev` for a ROS 2 repo ([getting started](../../getting-started.md)). The workstation bundle installs both.
- **VS Code + the Dev Containers extension**, only if you want `ardt dev open` to attach an editor.

## Details, for the days you need them

`ardt dev up` and `open` run the pre-steps themselves: render `.devcontainer/` when missing or stale (`ardt dev sync`), create the shared cache volumes and the colcon volume (`ardt dev volumes`), then start the container. Each step is idempotent, and each can be run by hand when debugging — see the [command table](index.md).

Everything rendered is **gitignored and machine-owned**: the repo carries no `.devcontainer/`. Change the `dev:` section of `ardt.yaml` and re-run, never the rendered files; hand edits are detected and refused.

## Hacking on ardt itself

```bash
ardt dev sync --ardt-source /path/to/ardt   # mount a checkout, install from it
ardt dev sync --from-pin                    # go back to the repo's ardt: pin
```

The choice is remembered across runs, so `--ardt-source` is given once, not every time.
