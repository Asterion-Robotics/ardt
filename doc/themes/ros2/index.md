# ROS 2

The ROS 2 theme covers workspace repos: a `src/` tree of packages built with colcon, its dependencies declared in `.repos` files and `package.xml`.

| Plane | Package | Provides |
|---|---|---|
| tasks | `ardt-ros-tasks` | `ardt deps`, `ardt build`, `ardt test` |
| pipelines | `ardt-ros-pipelines` | the `ros-ci` pipeline and the `ros2` image recipe |
| [devcontainer](../../devcontainer/index.md) | `ardt-ros-dev` | the `ros2` dev profile: base image, apt sets, bootstrap steps, C/C++ editor wiring |

Note what is *not* here: nothing in `ardt-core` knows about ROS, and neither does any of the three planes. The distro, the `.repos` file, rosdep skip-keys, colcon flags and everything the dev container installs are configuration or data of these plugins, and a repo that installs none of them gets a CLI with no `build` command at all.

```{toctree}
:maxdepth: 1

tasks
pipelines
```
