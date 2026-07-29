# Extending ardt

A plugin is an ordinary Python distribution. It declares `ARDT_PLUGIN_API` on its root package and registers through one of three entry-point groups.

| Group | Contributes | Loaded into |
|---|---|---|
| `ardt.commands` | click commands or groups | the `ardt` CLI |
| `ardt.pipelines` | modules holding `@pipeline` functions | `ardt pipe list/run` |
| `ardt.dev_profiles` | one `Profile` each | `ardt dev` |

```toml
# pyproject.toml
[project.entry-points."ardt.commands"]
doc = "ardt_doc_tasks.cli:doc"

[project.entry-points."ardt.pipelines"]
ros = "ardt_ros_pipelines.ros_ci"

[project.entry-points."ardt.dev_profiles"]
ros2 = "ardt_ros_dev.profile:ROS2"
```

Only `ardt.commands` loads at startup; the rest load on demand, and per group — resolving a dev profile never imports a pipeline module, so `ardt dev sync` never pays for Dagger.

```python
# src/ardt_<theme>_tasks/__init__.py
ARDT_PLUGIN_API = 1
```

The loader refuses an incompatible plugin **loudly and whole**: never half-loaded, never fatal to the rest of the CLI. `ardt plugins` prints what loaded, from where, and at which API version.

## Your first plugin, end to end

Everything a plugin needs, in four small files. The layout mirrors the first-party plugins, so any of them is a larger worked example:

```
ardt-acme/
├── pyproject.toml
├── src/ardt_acme/
│   ├── __init__.py          # the API declaration and the config-section claim
│   ├── config.py            # the `acme:` section, as a pydantic model
│   └── cli.py               # one command
└── tests/
    ├── conftest.py
    └── test_greet.py
```

```toml
# pyproject.toml
[project]
name = "ardt-acme"
version = "0.1.0"
dependencies = ["ardt-core"]

[project.entry-points."ardt.commands"]
greet = "ardt_acme.cli:greet"
```

```python
# src/ardt_acme/__init__.py
ARDT_PLUGIN_API = 1
ARDT_CONFIG_SECTION = "acme"  # the ardt.yaml section this plugin claims
```

```python
# src/ardt_acme/config.py
from pydantic import BaseModel, ConfigDict

from ardt_core.config import ArdtConfig


class AcmeConfig(BaseModel):
    """The `acme:` section. `extra="forbid"` is what makes typos errors."""

    model_config = ConfigDict(extra="forbid")

    greeting: str = "hello"


def acme_config(cfg: ArdtConfig) -> AcmeConfig:
    return cfg.section_as("acme", AcmeConfig)
```

```python
# src/ardt_acme/cli.py
import click

from ardt_core.cli import pass_ardt
from ardt_core.context import Context

from .config import acme_config


@click.command()
@pass_ardt
def greet(ctx: Context) -> None:
    """Greet the project (a demo task)."""
    cfg = acme_config(ctx.cfg)
    ctx.runner.run(["echo", f"{cfg.greeting}, {ctx.project}"])
    ctx.emit(greeting=cfg.greeting)
```

Note what is *absent*: no `--dry-run` or `--json` handling (core injects both into every mounted command; going through `ctx.runner` is what keeps them honest), no environment reads, no `print` (the console owns stderr, the envelope owns stdout).

Install it into the ardt tool environment — append `--with-editable /path/to/ardt-acme` to the by-hand install from [Getting started](../getting-started.md) — then verify:

```bash
ardt plugins            # ardt-acme 0.1.0 (api 1)  commands: greet
ardt greet --dry-run    # [dry-run] echo hello, <project>
```

The test rides on {py:mod}`ardt_core.testing` (the plugin must be installed in the test venv, editable is fine):

```python
# tests/conftest.py
from ardt_core.testing import console, isolate_environment, repo  # noqa: F401

# tests/test_greet.py
from pathlib import Path

import pytest

from ardt_core.cli import main


def test_greet_dry_run(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["-C", str(repo), "greet", "--dry-run"]) == 0
    assert "echo hello" in capsys.readouterr().err
```

A pipeline plugin is the same skeleton with an `ardt.pipelines` entry point naming a module of `@pipeline` functions — see [Pipelines](pipelines.md) for that contract.

## A dev profile plugin

A profile is the smallest kind of plugin: no command, no config section of its own, no code path. It declares what a kind of repo needs in its devcontainer, and {py:mod}`ardt_devcontainers` does the rendering.

```
ardt-acme-dev/
├── pyproject.toml               # dependencies = ["ardt-core", "ardt-devcontainers"]
└── src/ardt_acme_dev/
    ├── __init__.py              # ARDT_PLUGIN_API = 1, ARDT_CONFIG_SECTION = "dev"
    ├── profile.py               # one Profile instance
    └── templates/acme.Dockerfile.tmpl
```

```python
# src/ardt_acme_dev/profile.py
from ardt_devcontainers.profiles import DISTRO, Profile

ACME = Profile(
    name="acme",
    summary="Acme SDK workspace",
    distribution="ardt-acme-dev",              # installed in the container too
    dockerfile="acme.Dockerfile.tmpl",
    templates_package="ardt_acme_dev.templates",
    default_base_image="ubuntu:24.04",
    ardt_modules=("ardt-core",),
    apt_groups=(("toolchain", ("cmake", "ninja-build")),),
    bootstrap=(("ardt", "deps"),),
    extensions=("ms-python.python",),
)
```

The entry-point name **is** the profile name — what a repo writes in `dev.profile` — and two plugins claiming the same one is an error, not a silent last-wins. `distribution` names the plugin itself, because `ardt dev bootstrap` runs *inside* the container and has to resolve the same profile the host rendered from; it is installed there from the repo's own `ardt:` pin. `templates_package` is an import anchor, not a path, so the template is read through `importlib.resources` and works from a wheel as well as an editable checkout.

:::{warning}
The `Profile` contract is **provisional**. Its fields were extracted from a single profile, so it may change in a minor release until a second one exists to argue with; `ARDT_PLUGIN_API` is what gets bumped when it does. Pin `ardt-devcontainers` accordingly, and check the engine's README for the internals that are still colcon-shaped (the volume layout, `ardt dev compile-commands`, the `ros_ci.builder` parity check, the `@DISTRO@` token) — a non-ROS profile meets those edges first.
:::

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

## Working on ardt itself

The monorepo is a uv workspace. Every distribution owns its unit tests; `tests/` at the root holds only what crosses package boundaries:

```
ardt/
├── packages/                # the platform planes
│   ├── ardt-core/           # cli, plugin loader, context, config, runner, console, version policy
│   ├── ardt-pipelines/      # the generic Dagger plane: `ardt pipe`, @pipeline registry, std helpers
│   └── ardt-devcontainers/  # the devcontainer plane: `ardt dev` renders and drives, profile-agnostic
├── plugins/                 # first-party theme plugins (ardt-<theme>-<plane>)
│   ├── ardt-ros-tasks/      # deps / build / test (colcon, rosdep, vcs) — in-env tasks
│   ├── ardt-ros-pipelines/  # ros-ci + the ros2 image recipe
│   ├── ardt-ros-dev/        # the ros2 dev profile — data for the devcontainer plane
│   ├── ardt-doc-tasks/      # doc build (sphinx preset + doxygen/breathe + ros2-interfaces)
│   └── ardt-doc-pipelines/  # docs-ci: versioned site (working tree + tags) -> public/
├── tests/                   # cross-package only: policy sweeps + docker-marked integration
└── .github/workflows/       # lint, tests, the versioned docs site, PyPI publication
```

:::{warning}
On a machine with ROS sourced, `/opt/ros/<distro>` is on `PYTHONPATH`, and its pytest plugins can break collection. Run the suite as `PYTHONPATH= uv run pytest`. CI containers have no ROS, so this only bites locally.
:::
