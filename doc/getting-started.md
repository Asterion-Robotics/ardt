# Getting started

## Install

`ardt` is a CLI you call from any repo, so install it **once as a uv tool**: a persistent, isolated venv with `ardt` on your `PATH`. No `uv run` prefix, no project venv.

The one-liner does that for you, and needs [uv](https://docs.astral.sh/uv/) already installed:

```bash
curl -LsSf https://raw.githubusercontent.com/Asterion-Robotics/ardt/main/install.sh | bash
```

`ARDT_REF=v0.1.0` pins a release rather than tracking the default branch, and `ARDT_MODULES="…"` picks the plugin set. The script is short and worth reading before piping it anywhere.

### From the index

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

## Two conventions every command honors

`--dry-run`
: Print the plan, execute nothing. Core-injected into every command, plugin commands included.

`--json`
: A machine-readable result envelope on **stdout**; human output and diagnostics stay on **stderr**, so `ardt <cmd> --json | jq` always works.

## Configure a repo

One file per repo, `ardt.yaml` (or a `[tool.ardt]` table in `pyproject.toml`; the file wins), with one namespaced section per plugin. Nothing in it is required. See [Configuration](concepts/configuration.md).
