# ardt-core

The only mandatory package of [ardt](../../README.md) — the small, dependency-light core. Installing it never drags in ROS or a container engine.

Provides:

- **`ardt` CLI** (`cli.py`) — the top-level click group; injects the `--dry-run` / `--json` conventions into every command, including plugin-provided ones.
- **Plugin loader** (`plugins.py`) — entry-point discovery guarded by `ARDT_PLUGIN_API`; an incompatible plugin is refused loudly and skipped whole, never half-loaded, never fatal to the rest of the CLI.
- **Context** (`context.py`) — built once per invocation and injected everywhere: git facts, normalized CI facts, project config, the version.
- **Config** (`config.py`) — `ardt.yaml` / `[tool.ardt]` into typed pydantic models, with namespaced plugin sections.
- **`ctx.version`** (`version.py`) — the single tag policy (tag → semver; branch → `<last-tag>.devN+g<sha>`; dirty → `+ .dirty`; no repo → `0.0.0+unknown`).
- **CI normalization** (`ci.py`) — the one table mapping GitLab / GitHub vars and the local credentials file onto `registry`, `registry_user`, `is_tag`, … This is the **only** module besides `env.py` permitted to read the environment.
- **Runner** (`runner.py`) — streaming subprocess wrapper with tail capture and dry-run.
- **Console** (`console.py`) — rich on a TTY, plain + CI section markers otherwise; everything on stderr.

Deps: `click`, `pydantic`, `pyyaml`, `rich` — nothing heavier.
