# ROS 2 tasks

`ardt-ros-tasks` runs wherever it is invoked — dev shell, devcontainer, CI container — and never imports Dagger.

| Command | Wraps |
|---|---|
| `ardt deps` | `vcs import` of the configured `.repos`, then `rosdep install` |
| `ardt build` | `colcon build` (`--symlink-install` by default) |
| `ardt test` | `colcon test` + a `colcon test-result` summary |

JUnit XMLs land at the fixed convention `build/**/test_results/**/*.xml`, so pipelines export them blindly.

### Overlays

A repo built `FROM` an image that ships a prebuilt colcon workspace (an SDK, a vendor stack) lists it in `overlays`. Every task then sources `<source_base>/<distro>/setup.bash` first and each overlay's `local_setup.bash` after it, in the listed order: `local_setup`, not `setup`, so exactly the configured prefixes compose the environment and the prefix chain an overlay recorded at its own build is never replayed on top. An overlay that depends on another is listed after it. A listed overlay with no `local_setup.bash` is an error, never a silent build without it. The dev container sources the same overlays in the same order (see the [parity rule](../../devcontainer/parity.md)).

:::{note}
When running `ardt deps` on a dev machine with Python \>= 3.11, the CI images and devcontainer (via the bootstrap step) set `PIP_BREAK_SYSTEM_PACKAGES=1` for PEP 668 compliance; a plain dev shell does not (the behavior can be unwanted in some cases).
:::

## Configuration

```yaml
tasks:
  ros:
    distro: jazzy
    # repos_file: my_robot.repos   # imported by `ardt deps` before rosdep runs;
    #                              # default: `<project>.repos` when it exists,
    #                              # "" opts out of that auto-detection
    repos_target: src/external
    rosdep_skip_keys:              # deps never installed (also: `ardt deps --skip-key KEY`)
      - rti-connext-dds
    # exclude_packages: [big_sim]  # skipped in rosdep/build/test (`--exclude-pkg`)
    # package_scope: workspace    # opt OUT of the default `project` scope:
    #                              # build/dep-resolve everything vcs
    #                              # imported, demo packages included. The
    #                              # default builds --packages-up-to the
    #                              # repo's OWN packages only. `ardt test`
    #                              # stays own-only in BOTH scopes: imports'
    #                              # suites are not this repo's gate.
    # install_base: /opt/ros/app   # colcon --install-base; default ./install
    # overlays: [/opt/aos/sdk]     # install spaces layered on the distro (an SDK
    #                              # prebuilt in the builder image): their
    #                              # local_setup.bash, sourced in this order
    #                              # after the distro before deps/build/test
    build_args:
      - --cmake-args
      - -DCMAKE_BUILD_TYPE=RelWithDebInfo
    symlink_install: true
```

:::{note}
A sourced ROS overlay puts `/opt/ros/<distro>` on `PYTHONPATH`, whose pytest plugins can break collection of ardt's own test suite. Run it with `PYTHONPATH= uv run pytest`. CI containers have no ROS, so this only bites local runs.
:::

The API lives in {py:mod}`ardt_ros_tasks.tasks`, with the config model in {py:mod}`ardt_ros_tasks.config`.
