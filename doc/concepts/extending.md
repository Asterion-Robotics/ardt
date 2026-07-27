# Extending ardt

A plugin is an ordinary Python distribution. It declares `ARDT_PLUGIN_API` on its root package and registers through one of two entry-point groups.

| Group | Contributes | Loaded into |
|---|---|---|
| `ardt.commands` | click commands or groups | the `ardt` CLI |
| `ardt.pipelines` | modules holding `@pipeline` functions | `ardt pipe list/run` |

```toml
# pyproject.toml
[project.entry-points."ardt.commands"]
doc = "ardt_doc_tasks.cli:doc"

[project.entry-points."ardt.pipelines"]
ros = "ardt_ros_pipelines.ros_ci"
```

```python
# src/ardt_<theme>_tasks/__init__.py
ARDT_PLUGIN_API = 1
```

The loader refuses an incompatible plugin **loudly and whole**: never half-loaded, never fatal to the rest of the CLI. `ardt plugins` prints what loaded, from where, and at which API version.

## The context

Every command receives one {py:class}`~ardt_core.context.Context`, built once per invocation:

- **git facts** (`ardt_core.git`) and the version policy (`ardt_core.version`);
- **normalized CI facts** (`ardt_core.ci`) — the one table mapping GitLab / GitHub variables onto `registry`, `registry_user`, `is_tag`, …;
- **the typed config** (`ctx.cfg.section_as("tasks", MySection)`);
- **`ctx.runner`** — a streaming subprocess wrapper with tail capture and dry-run support. Shell out through it, never through `subprocess` directly, or `--dry-run` silently stops being honest;
- **`ctx.console`** — rich on a TTY, plain plus CI section markers otherwise, everything on **stderr**;
- **`ctx.emit(...)`** — the `--json` result envelope, on **stdout**.

`ardt_core.ci` and `ardt_core.env` are the only modules permitted to read the environment. Everything else takes its facts from the context.

## Testing a plugin

Shared fixtures (`repo`, `console`, CI-environment isolation) ship as {py:mod}`ardt_core.testing`, so a third-party plugin gets them exactly the way first-party ones do.

## Adding a theme to these docs

A theme is a page directory plus an API page:

1. `doc/themes/<theme>/index.md`, with `tasks.md` / `pipelines.md` subsections as needed, added to the `Themes` toctree in [`doc/index.md`](../index.md) and to the table in [`doc/themes/index.md`](../themes/index.md);
2. `doc/api/<package>.md`, added to the toctree in [`doc/api/index.md`](../api/index.md).

Nothing else: the preset supplies the toolchain, and `ardt doc build` picks up whatever is in the tree.
