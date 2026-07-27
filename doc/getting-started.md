# Getting started

## Install

`ardt` is a CLI you call from any repo, so install it **once as a uv tool**: a persistent, isolated venv with `ardt` on your `PATH`. No `uv run` prefix, no project venv.

```bash
# From a checkout (developers): editable, so source edits apply immediately
uv tool install --editable ./packages/ardt-core \
    --with-editable ./plugins/ardt-ros-tasks \
    --with-editable ./plugins/ardt-doc-tasks \
    --with-editable ./plugins/ardt-dev \
    --with-editable ./packages/ardt-pipelines \
    --with-editable ./plugins/ardt-ros-pipelines \
    --with-editable ./plugins/ardt-doc-pipelines

ardt --help    # from anywhere
```

The set of `--with` packages *is* the feature set: every command past `ardt info` / `ardt plugins` comes from a plugin. See [Themes](themes/index.md) for what each one adds.

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
