# Getting started

## The five-minute path

```bash
# 1. install ardt (uv is the only prerequisite — see below)
curl -LsSf https://raw.githubusercontent.com/Asterion-Robotics/ardt/main/install.sh | bash

# 2. in a ROS 2 repo that has an ardt.yaml
ardt dev open        # dev container built, started, VS Code attached

# 3. inside the container
ardt build
ardt test
```

The first `ardt dev open` takes minutes (image build + rosdep); after that, seconds. If anything fails, `ardt dev doctor` names the culprit — including the classic WSL2 one, Docker Desktop's WSL integration being off for your distro. The rest of this page is install variants; the [devcontainer quickstart](themes/devcontainer/quickstart.md) explains what `dev open` set up.

## Install

`ardt` is a CLI you call from any repo, so install it **once as a uv tool**: a persistent, isolated venv with `ardt` on your `PATH`. No `uv run` prefix, no project venv.

The one-liner does that for you. [uv](https://docs.astral.sh/uv/) is the only prerequisite:

```bash
curl -LsSf https://raw.githubusercontent.com/Asterion-Robotics/ardt/main/install.sh | bash
```

ardt's installer deliberately will not install uv for you: chaining installers hides what you are trusting. Run from a repo checkout, it honors the repo's `ardt.yaml`: `ardt.version` pins the ref, and `install_extras` / `install_skip` adjust the default module bundle. That bundle is contextual — core + pipelines + the ROS 2 plugins everywhere, plus `ardt-dev` on workstations only (runners are detected via `CI=true`, which GitHub Actions and GitLab CI both set); the doc plugins are opt-in. The env vars override both: `ARDT_REF=v0.1.0` pins a release, `ARDT_MODULES="…"` replaces the module set outright. The script is short and worth reading before piping it anywhere — the bundle policy is documented in it.

:::{admonition} To install uv
:class: note

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```
:::

### From the index

:::{admonition} Not yet available
:class: warning
Nothing is published to a package index yet, and the `ardt-cli` metapackage does not exist as a distribution today. Until it does, use the one-liner above or the by-hand forms below.
:::

Once the distributions are published, `ardt-cli` bundles them. It is a metapackage with no code of its own, and each theme is an extra, so nothing installs a toolchain your repos do not use:

```bash
uv tool install ardt-cli                  # the CLI and the pipeline plane
uv tool install "ardt-cli[ros]"           # + the ROS 2 theme
uv tool install "ardt-cli[doc]"           # + the documentation theme
uv tool install "ardt-cli[devcontainer]"  # + `ardt dev`
uv tool install "ardt-cli[all]"           # everything
```

### By hand

The long form, which the one-liner runs for you. Useful for a fork, an unmerged branch, or a subset:

```bash
uv tool install "ardt-core @ git+https://github.com/Asterion-Robotics/ardt.git#subdirectory=packages/ardt-core" \
    --with "ardt-pipelines @ git+https://github.com/Asterion-Robotics/ardt.git#subdirectory=packages/ardt-pipelines" \
    --with "ardt-ros-tasks @ git+https://github.com/Asterion-Robotics/ardt.git#subdirectory=plugins/ardt-ros-tasks"
```

### From a checkout

Editable, so source edits apply immediately — the developer path:

```bash
uv tool install --editable ./packages/ardt-core \
    --with-editable ./packages/ardt-pipelines \
    --with-editable ./plugins/ardt-ros-tasks \
    --with-editable ./plugins/ardt-doc-tasks \
    --with-editable ./plugins/ardt-dev \
    --with-editable ./plugins/ardt-ros-pipelines \
    --with-editable ./plugins/ardt-doc-pipelines

ardt --help    # from anywhere
```

The set of installed packages *is* the feature set: every command past `ardt info` / `ardt plugins` comes from a plugin. See [Themes](themes/index.md) for what each one adds.

:::{note}
`uvx ardt` is *run-without-install*: it re-resolves the package into a temporary environment on every invocation, cannot see an unpublished workspace, and forgets the plugins you `--with`-ed. Right for one-off runs of a published CLI, wrong for a daily driver.
:::

### Upgrade and uninstall

Upgrading *is* re-running the installer: `uv tool install --force` replaces the previous install, honoring whatever `ardt.version` pin the current directory's `ardt.yaml` carries. Uninstalling removes the uv tool, which is named after the package owning the `ardt` entry point, not the command:

```bash
uv tool uninstall ardt-core
```

## Two conventions every command honors

`--dry-run`
: Print the plan, execute nothing. Core-injected into every command, plugin commands included.

`--json`
: A machine-readable result envelope on **stdout**; human output and diagnostics stay on **stderr**, so `ardt <cmd> --json | jq` always works.

## Configure a repo

One file per repo, `ardt.yaml` (or a `[tool.ardt]` table in `pyproject.toml`; the file wins), with one namespaced section per plugin. Nothing in it is required. See [Configuration](concepts/configuration.md).
