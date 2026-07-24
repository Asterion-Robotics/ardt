# ardt-dev

Dev environments for [ardt](../../README.md): `ardt dev` renders the container a
repo is developed in, then drives it. In-environment and engine-free — it writes
files and shells out to `docker compose`, and never imports Dagger or a ROS
package.

**Repos own no devcontainer.** The recipe and the editor wiring live here as
package data and update by bumping the pinned ardt version, exactly as the CI
image recipe does in [ardt-ros-pipelines](../ardt-ros-pipelines/README.md).
`ardt dev sync` writes them into a **gitignored** `.devcontainer/`, hashes them in
a manifest, and refuses to clobber anything a human edited.

One exception to "everything under `.devcontainer/`": cpptools reads its C/C++
configuration only from `.vscode/c_cpp_properties.json`, so the ros2 profile
renders that file too. It is gitignored **by path**, not by directory, so a repo
keeping its own `.vscode/launch.json` is unaffected. Unlike the other rendered
files it carries no comment header: cpptools only gained a JSONC parser in 1.0.0
([#5885](https://github.com/microsoft/vscode-cpptools/issues/5885)) and VS Code
still flags comments there
([#6132](https://github.com/microsoft/vscode-cpptools/issues/6132)).

| Command | Runs | Does |
|---|---|---|
| `ardt dev sync` | host | render `.devcontainer/` + `.vscode/` and add them to `.gitignore` |
| `ardt dev up` / `shell` / `down` | host | `docker compose` up + postCreate / login shell / stop |
| `ardt dev doctor` | either | check CI parity, ardt pin, render freshness, host wiring |
| `ardt dev host-config` | host | re-derive only the host overlay (the `initializeCommand`) |
| `ardt dev bootstrap` | container | claim the volume dirs, then the profile's create steps |
| `ardt dev compile-commands` | container | merge colcon's per-package files for clangd |
| `ardt dev profiles` | either | list the profiles this ardt knows |

## The parity rule

The container a developer works in and the image CI builds must not drift:

- the dev layer's base **is** `pipelines.ros_ci.builder` (that resolution order
  is why a repo with CI configured gets parity with nothing to keep in sync);
- ardt is installed from the repo's `ardt:` pin via `ardt_core.dist`, producing
  the same requirement strings the `ros-ci` recipe installs into its build stage
  (readable afterwards in `.devcontainer/ardt-requirements.txt`);
- the workspace mounts at the recipe's own path (`/ws/src`), so CMake paths,
  `compile_commands.json` and stack traces read the same in both;
- `ardt dev bootstrap` runs the recipe's first step, `ardt deps`.

`ardt dev doctor` fails when any of that drifts, and warns when `ardt.version` is
unpinned (a recipe is only reproducible when the ardt inside it is).

## Hosts

One clone works on WSL2, Linux and macOS: `devcontainer.json` has no
conditionals, so everything host-shaped goes into `compose.host.yaml`, re-derived
by `initializeCommand` on every start.

| | WSL2 | Linux | macOS |
|---|---|---|---|
| GUI (rviz2, rqt) | WSLg sockets + `/dev/dxg` | X11 socket + `/dev/dri` | not wired yet (noVNC is the intended answer) |
| DDS across host and container | `network_mode: host`, `ipc: host` | same | unavailable, falls back to localhost-scoped discovery |

## Configure

Nothing is required: a ROS 2 repo with no `dev:` section gets the standard
environment. The knobs exist for exceptions — see
[ardt.example.yaml](../../ardt.example.yaml).

```yaml
dev:
  profile: ros2
  apt_packages: [libeigen3-dev] # extra dev-layer packages
  gui: false # headless repo
  image: registry/…/ros2-dev@sha256:… # a published dev image; skips the local build
```

## Where this is going

The rendered `Dockerfile` is the interim form of the `ros2-dev` node in
`platform/base-images` (per ADR-015 a dev image is a child image, so it takes an
image *name*, never a tag variant suffix). Once that publishes, repos set
`dev.image:` and the local build disappears — the rest of the render does not
change.

Whether to make that move, and the three decisions it forces (who owns the
package list, how the parity check survives, what happens to `dev.apt_packages`),
are written up in [docs/published-dev-image.md](docs/published-dev-image.md).
**Open, not decided.**
