# ardt

**A**sterion **R**obotics **D**evelopment **T**ools: one CLI for the three things every robotics repo needs — a reproducible dev container, CI that runs the same commands a developer does, and versioned docs.

## Start here

For a ROS 2 repo, the whole path is:

```bash
# once per machine (uv is the only prerequisite)
curl -LsSf https://raw.githubusercontent.com/Asterion-Robotics/ardt/main/install.sh | bash

# in the repo
ardt dev open      # build + start the dev container, attach VS Code to it

# inside the container
ardt build         # colcon build
ardt test          # colcon test + summary
```

That is the everyday surface. [Getting started](getting-started.md) covers install variants, [the devcontainer quickstart](themes/devcontainer/quickstart.md) covers what `ardt dev open` sets up and how to debug it, and `ardt pipe run ros-ci` is the same build as a CI pipeline ([ROS 2 theme](themes/ros2/index.md)).

## The idea

**One small core, everything else a plugin.** The core knows nothing about ROS; ROS-ness itself is a plugin. Commands come in two kinds: **tasks** run in the environment you invoke them from (`ardt build` is colcon build, wherever you are), and **pipelines** run those same tasks *inside* containers (`ardt pipe run ros-ci`) — so a green CI run means the commands you type locally passed.

Reproducible dev containers, honest CI, versioned docs: these are common robotics problems, not ours alone. So the core and the general-purpose plugins are public and Apache-2.0, and our own public repos are built with them. Company-internal processes live in private plugins that install alongside, through the same entry points any third-party plugin uses.

```{toctree}
:maxdepth: 2
:caption: Using ardt

getting-started
concepts/index
demo
```

```{toctree}
:maxdepth: 2
:caption: Themes

themes/index
themes/devcontainer/index
themes/ros2/index
themes/doc/index
```

```{toctree}
:maxdepth: 2
:caption: Reference

api/index
```
