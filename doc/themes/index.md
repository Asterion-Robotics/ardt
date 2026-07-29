# Overview

Two independent axes describe every plugin. A **theme** is one concern ardt knows how to handle: ROS 2, documentation. A **plane** is *how* a command runs: in the environment you invoke it from, inside a container Dagger builds, or inside the container you develop in. A plugin is one cell of that grid, which is what its name spells out: `ardt-<theme>-<plane>`.

The planes are platform packages, documented on their own: [tasks](../concepts/tasks.md), [pipelines](../concepts/pipelines.md), [devcontainer](../devcontainer/index.md). Themes fill them in:

| Theme | task plane | pipeline plane | devcontainer plane |
|---|---|---|---|
| [ROS 2](ros2/index.md) | `ardt-ros-tasks` | `ardt-ros-pipelines` | `ardt-ros-dev` |
| [Documentation](doc/index.md) | `ardt-doc-tasks` | `ardt-doc-pipelines` | — |

Install the themes a repo needs and nothing else: the CLI's feature set is exactly the set of plugins present. A cell may be empty, as the documentation theme's devcontainer cell is — building docs needs no dev container of its own kind, it happens in whichever one you are already in.

:::{note}
**"Devcontainer" is a plane here, not a theme**, though it was listed as one until recently. That held while `ardt dev` was a single distribution that looked like a theme plugin. It is now the `ardt-devcontainers` engine plus whatever profiles are installed, and the ROS-specific half of it is `ardt-ros-dev`, a cell of the ROS 2 row above.
:::

The recurring pattern across all of them: **repos own no build files.** The devcontainer recipe, the CI Dockerfile and the sphinx configuration live in the plugin as package data and update by bumping the pinned ardt version, never by editing files across N repos.
