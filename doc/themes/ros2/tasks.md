# ROS 2 tasks

`ardt-ros-tasks` runs wherever it is invoked — dev shell, devcontainer, CI container — and never imports Dagger.

| Command | Wraps |
|---|---|
| `ardt deps` | `vcs import` of the configured `.repos`, then `rosdep install` |
| `ardt build` | `colcon build` (`--symlink-install` by default) |
| `ardt test` | `colcon test` + a `colcon test-result` summary |

JUnit XMLs land at the fixed convention `build/**/test_results/**/*.xml`, so pipelines export them blindly.

## Configuration

```yaml
tasks:
  ros:
    distro: jazzy
    repos_file: my_robot.repos     # imported by `ardt deps` before rosdep runs
    repos_target: src/external
    rosdep_skip_keys:              # deps never installed (also: `ardt deps --skip-key KEY`)
      - rti-connext-dds
    # exclude_packages: [big_sim]  # skipped in rosdep/build/test (`--exclude-pkg`)
    # install_base: /opt/ros/app   # colcon --install-base; default ./install
    build_args:
      - --cmake-args
      - -DCMAKE_BUILD_TYPE=RelWithDebInfo
    symlink_install: true
```

:::{note}
A sourced ROS overlay puts `/opt/ros/<distro>` on `PYTHONPATH`, whose pytest plugins can break collection of ardt's own test suite. Run it with `PYTHONPATH= uv run pytest`. CI containers have no ROS, so this only bites local runs.
:::

The API lives in {py:mod}`ardt_ros_tasks.tasks`, with the config model in {py:mod}`ardt_ros_tasks.config`.
