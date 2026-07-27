# From clone to open container

The everyday path is two commands. The rest of the command table exists for the days something needs inspecting.

**Before you start:** Docker (Docker Engine on Linux/WSL2, or Docker Desktop with WSL integration enabled), `ardt` installed with the `ardt-dev` plugin, and VS Code with the Dev Containers extension if you want step 3 to open an editor.

## 1. Clone

```bash
git clone <repo> && cd <repo>
```

Nothing is committed for you to configure: the repo carries no `.devcontainer/`.

## 2. Render it

```bash
ardt dev sync
```

Writes `.devcontainer/` and `.vscode/c_cpp_properties.json` from the profile and this repo's config, and adds them to `.gitignore`. It prints the profile, the host it detected, and the base image it resolved — that base image is `pipelines.ros_ci.builder`, which is what makes the container match CI.

Re-run it after changing the `dev:` section or bumping the ardt pin. It refuses to clobber a file a human edited (`--force` overrides).

## 3. Open it

```bash
ardt dev open          # add --build to rebuild the image first
```

Creates the volumes, starts the container, and attaches VS Code to `/ws/src`. The **first** run builds the dev image (minutes) and VS Code runs `postCreate` on first attach, which is `ardt dev bootstrap`: claim the volume directories, then the profile's create steps (`ardt deps`).

No editor, or a headless machine? Use the terminal path instead:

```bash
ardt dev up            # start + run postCreate here rather than in VS Code
ardt dev shell         # a login shell in the running container
```

:::{note}
There is no separate `ardt dev volumes` step: `up` and `open` both call it, and so does the devcontainer's `initializeCommand`. Run it by hand only when debugging a mount.
:::

## 4. Work in it

Inside the container the ordinary tasks apply, against the same config CI uses:

```bash
ardt build
ardt test
ardt dev compile-commands   # merge colcon's per-package files for clangd
```

## 5. Stop it

```bash
ardt dev down               # volumes survive; --purge drops this repo's build tree
```

## When something looks wrong

```bash
ardt dev doctor             # CI parity, ardt pin, render freshness, host wiring
```

`doctor` is the first thing to run after a confusing failure: it is what catches the dev container and the CI image having drifted apart, and it warns when `ardt.version` is unpinned.

## Hacking on ardt itself

```bash
ardt dev sync --ardt-source /path/to/ardt   # mount a checkout, install from it
ardt dev sync --from-pin                    # go back to the repo's ardt: pin
```

The choice is remembered across `sync` runs, so `--ardt-source` is given once, not every time.
