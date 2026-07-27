# Overview

A **theme** is one concern ardt knows how to handle, packaged as up to two plugins: `ardt-<theme>-tasks` (in-environment commands) and `ardt-<theme>-pipelines` (containerized orchestration). Install the themes a repo needs and nothing else — the CLI's feature set is exactly the set of plugins present.

| Theme | Packages | Adds |
|---|---|---|
| [Devcontainer](devcontainer/index.md) | `ardt-dev` | `ardt dev` — renders and drives the container the repo is developed in |
| [ROS 2](ros2/index.md) | `ardt-ros-tasks`, `ardt-ros-pipelines` | `ardt deps` / `build` / `test`, the `ros-ci` pipeline and the ROS 2 image recipe |
| [Documentation](doc/index.md) | `ardt-doc-tasks`, `ardt-doc-pipelines` | `ardt doc build`, the `docs-ci` versioned-site pipeline |

The recurring pattern across all of them: **repos own no build files.** The devcontainer recipe, the CI Dockerfile and the sphinx configuration live in the plugin as package data and update by bumping the pinned ardt version, never by editing files across N repos.
