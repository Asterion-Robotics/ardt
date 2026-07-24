# ardt-ros-tasks

ROS 2 workspace tasks for [ardt](../../README.md): `ardt deps`, `ardt build`,
`ardt test`. In-environment and engine-free — they run wherever invoked (dev shell,
devcontainer, CI container) and never import Dagger.

| Command | Wraps |
|---|---|
| `ardt deps` | `vcs import` of the configured `.repos`, then `rosdep install` |
| `ardt build` | `colcon build` (`--symlink-install` by default) |
| `ardt test` | `colcon test` + a `colcon test-result` summary |

JUnit XMLs land at the fixed convention `build/**/test_results/**/*.xml` so
pipelines can export them blindly.

Configure under `tasks.ros:` in `ardt.yaml` — see the
[example](../../ardt.example.yaml).
