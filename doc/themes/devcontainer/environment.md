# Volumes and hosts

## Volumes

Four per repo, and three of the four are shared machine-wide:

| Volume | Scope | Holds | Removed by |
|---|---|---|---|
| `<project>-dev_colcon` | this repo | `build/`, `install/`, `log/` as three `subpath` mounts of one volume | `ardt dev down --purge` |
| `ardt-ccache` | **every repo** | compiler cache — sharing it raises the hit rate | `ardt dev down --purge-shared` |
| `ardt-apt-cache` | **every repo** | downloaded `.deb`s, the same packages everywhere | `--purge-shared` |
| `ardt-claude` | **every repo** | Claude Code state, so `claude login` happens once | `--purge-shared` |

The shared three are declared `external:`. That is what keeps `--purge` repo-scoped: compose does not delete what it does not own, so cleaning one repo can never wipe another's caches. The cost is that they must exist before `up` — `ardt dev volumes` creates them, and both `ardt dev up` and the devcontainer's `initializeCommand` call it.

That command also `mkdir`s the three subpaths inside the colcon volume, because Docker refuses to mount a subpath that does not exist rather than creating one ([moby#47842](https://github.com/moby/moby/issues/47842)). It is idempotent and uses the image the repo pulls anyway, so it costs no extra download.

## Hosts

One clone works on WSL2, Linux and macOS: `devcontainer.json` has no conditionals, so everything host-shaped goes into `compose.host.yaml`, re-derived by `initializeCommand` on every start.

| | WSL2 | Linux | macOS |
|---|---|---|---|
| GUI (rviz2, rqt) | WSLg sockets + `/dev/dxg` | X11 socket + `/dev/dri` | not wired yet (noVNC is the intended answer) |
| DDS across host and container | `network_mode: host`, `ipc: host` | same | unavailable, falls back to localhost-scoped discovery |

## Opening the editor

`ardt dev open` starts the container and attaches VS Code to it in one step. Two launch paths, best first:

1. `devcontainer open`, if the Dev Containers CLI is installed. This is the supported entry point, but it exists only when the CLI came *from VS Code* ("Dev Containers: Install devcontainer CLI") — the npm `@devcontainers/cli` dropped it to stay editor-agnostic;
2. `code --folder-uri vscode-remote://dev-container+<hex>/<workspace>`, built by hand. The hex is the **host** path; the URI path is the folder inside the container. Not a documented VS Code scheme, hence the ordering.

The host path is not always the path you typed. Under WSL2 the editor is a Windows process driving a Linux workspace, so it knows the repo only as `\\wsl.localhost\<distro>\…`; `editor_host_path` converts it using `WSL_DISTRO_NAME`, and stops rather than guess when that variable is unset on a WSL2 kernel.
