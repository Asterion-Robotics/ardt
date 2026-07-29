# Concepts

Eight words carry all of ardt. Everything else in these pages is detail:

| Word | Meaning |
|---|---|
| **task** | a command that runs where you type it — `ardt build` is colcon build, here |
| **pipeline** | the same tasks run *inside* containers — `ardt pipe run ros-ci` is CI |
| **plugin** | a Python package adding tasks, pipelines or dev profiles; every command past `ardt info` is one |
| **module** | an installable piece of ardt (technically: a Python distribution) — the platform packages and the plugins; the name `install.sh`, `ARDT_MODULES` and the `ardt:` config section address |
| **plane** | *where* a command runs: in the environment you typed it in (task), in a container Dagger builds (pipeline), or in the container you develop in (devcontainer). A platform package owns each |
| **theme** | a family of plugins for one concern (ROS 2, docs) — up to one per plane, named `ardt-<theme>-<plane>` |
| **profile** | a dev-container flavor a repo picks (`ros2` is the only one today) |
| **render** | files ardt generates, gitignored and machine-owned — never edited, always re-derived |

ardt itself is a click CLI with a plugin loader and a typed context, and nothing else. `ardt-core` depends on `click`, `pydantic`, `pyyaml` and `rich` — installing it never drags in ROS or a container engine.

Everything a developer actually runs arrives as a **plugin**, discovered through Python entry points and guarded by a plugin API version. What a plugin contributes places it in one of three planes, and the relation between them is the central idea of the platform.

```{image} plugin-planes.svg
:alt: ardt-core beside three plugin planes. The pipeline plane (ardt-pipelines, ardt-ros-pipelines, ardt-doc-pipelines) and the devcontainer plane (ardt-devcontainers, ardt-ros-dev) each stand up a container and run the task plane (ardt-ros-tasks, ardt-doc-tasks) inside it.
:width: 100%
:align: center
```

One plane holds the **tasks**, the commands that run where you type them. The other two each stand a container up and run those same tasks inside it: the pipeline plane for CI, driven by Dagger, and the devcontainer plane for the inner loop, driven by `docker compose`. Tasks never call either one back.

That the two container planes run the *same* task plane, installed from the same `ardt:` pin, is what the parity rule is: the image CI builds and the container you work in cannot quietly diverge, and `ardt dev doctor` fails when they do. Core imports neither ROS nor Dagger, so the inner loop works with no engine installed.

```{toctree}
:maxdepth: 1

tasks
pipelines
configuration
versioning
extending
```
