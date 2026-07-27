# Devcontainer

`ardt dev` renders the container a repo is developed in, then drives it. The everyday surface is one command — `ardt dev open` (or `up` on a headless machine) does whatever is missing: render, volumes, image build, start. [From clone to open container](quickstart.md) is the walkthrough; the table below is the full surface, mostly for debugging one step at a time.

**Repos own no devcontainer.** The recipe and the editor wiring live in `ardt-dev` as package data. `ardt dev sync` writes them into a **gitignored** `.devcontainer/`, hashes them in a manifest, and refuses to clobber anything a human edited.

The container is a canonical colcon workspace: the repo at `/ws/src/<project>`, `.repos` imports at `/ws/src/external/`, colcon output at `/ws/{build,install,log}` — the same tree the CI recipe builds in ([parity](parity.md)).

| Command | Runs | Does |
|---|---|---|
| `ardt dev open` | host | everything needed, then VS Code attached to `/ws` (`--build` rebuilds first) |
| `ardt dev up` / `shell` / `down` | host | everything needed + postCreate / login shell at `/ws` / stop |
| `ardt dev sync` | host | render `.devcontainer/` + `.vscode/` (also implicit in `up`/`open`) |
| `ardt dev volumes` | host | create the shared caches and the colcon subpaths (also implicit) |
| `ardt dev doctor` | either | check docker + daemon, CI parity, ardt pin, render freshness, host wiring |
| `ardt dev host-config` | host | re-derive only the host overlay (the `initializeCommand`) |
| `ardt dev bootstrap` | container | claim the volume dirs, then the profile's create steps |
| `ardt dev compile-commands` | container | merge colcon's per-package files for clangd |
| `ardt dev profiles` | either | list the profiles this ardt knows |

Nothing is required to use it: a ROS 2 repo with no `dev:` section gets the standard environment. The knobs exist for exceptions.

```yaml
dev:
  profile: ros2
  apt_packages: [libeigen3-dev]          # extra dev-layer packages
  gui: false                             # headless repo
  image: registry/…/ros2-dev@sha256:…    # a published dev image; skips the local build
```

One exception to "everything under `.devcontainer/`": cpptools reads its C/C++ configuration only from `.vscode/c_cpp_properties.json`, so the ros2 profile renders that file too, gitignored **by path** so a repo keeping its own `.vscode/launch.json` is unaffected.

```{toctree}
:maxdepth: 1

quickstart
parity
environment
```
