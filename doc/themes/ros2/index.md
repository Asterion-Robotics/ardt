# ROS 2

The ROS 2 theme covers workspace repos: a `src/` tree of packages built with colcon, its dependencies declared in `.repos` files and `package.xml`.

| Plane | Package | Provides |
|---|---|---|
| tasks | `ardt-ros-tasks` | `ardt deps`, `ardt build`, `ardt test` |
| pipelines | `ardt-ros-pipelines` | the `ros-ci` pipeline and the `ros2` image recipe |

Note what is *not* here: nothing in `ardt-core` knows about ROS. The distro, the `.repos` file, rosdep skip-keys and colcon flags are all configuration of this plugin, and a repo that installs neither package gets a CLI with no `build` command at all.

```{toctree}
:maxdepth: 1

tasks
pipelines
```
