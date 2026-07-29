# ardt-ros-dev

The `ros2` dev profile for [ardt](../../README.md): what a ROS 2 workspace needs inside the container [`ardt dev`](../../packages/ardt-devcontainers/README.md) renders and drives.

Data, not code. One [`Profile`](src/ardt_ros_dev/profile.py) and one Dockerfile template, registered under the `ardt.dev_profiles` entry-point group; the engine reads them and does the rendering. Nothing here imports Dagger, and nothing here imports a ROS package either — a profile only *describes* a ROS environment, and it is resolved on hosts that have none.

```yaml
dev:
  profile: ros2 # the default; nothing to write for a ROS 2 repo
```

## What the profile decides

| | |
|---|---|
| Base image | `ros:<distro>-ros-base`, unless `pipelines.ros_ci.builder` or `dev.base_image` says otherwise |
| ardt in the container | `ardt-ros-tasks`, `ardt-doc-tasks` (on top of `ardt-core` + `ardt-devcontainers` + this plugin) |
| Bootstrap | `apt-get update`, `rosdep update --rosdistro <distro>`, then `ardt deps` |
| Editor | clangd for C++ IntelliSense, cpptools kept for its debug adapter, `ms-iot.vscode-ros`, ruff |
| `.vscode/c_cpp_properties.json` | include paths at the repo's distro, and the C++ standard that distro targets |

`@DISTRO@` in any of those is substituted with `tasks.ros.distro` at render time.

## The apt sets, and what is deliberately not in them

The dev layer is **strictly additive** over what the CI build stage installs — the first group repeats `recipes/ros2.Dockerfile.tmpl`'s packages verbatim so the two cannot drift. On top of it: the toolchain (cmake, ninja, ccache), `ros-dev-tools`, debuggers, language servers, the docs toolchain, and the GUI tools that are the reason a dev image exists at all.

Sizes, measured on jazzy with dependencies included: rviz2 358 MB, the rqt subset ~500 MB (mostly Qt, shared with rviz2), mesa 192 MB.

`rqt-common-plugins` is **not** in the list, and that is the single biggest size decision here: the metapackage pulls 398 packages and 1.45 GB, because `rqt_image_view` drags in OpenCV's dev packages and `rqt_plot` drags in scipy, matplotlib and VTK. A repo that wants them adds them to `dev.apt_packages`.

The C++ standard per distro follows each distro's own "Code style and language versions" page (`docs.ros.org/en/<distro>/The-ROS2-Project/Contributing/Code-Style-Language-Versions`): c++17 through kilted, c++20 from lyrical on. Note that REP 2000's "minimum language requirements" tables still say C++17 for rolling; the per-distro page is the one that tracks the switch, so it is the one quoted. An unknown distro gets c++20 — far likelier to be a future distro than a forgotten past one.

## The parity rule, ROS-side

The engine enforces the mechanism (base image, ardt pin, workspace path); this profile is what makes the ROS half of it true:

- `pipelines.ros_ci.builder` beats the profile's `default_base_image`, so a repo with CI configured gets a matching dev base with nothing to keep in sync — `ardt dev doctor` fails when they differ;
- the profile's `ardt_modules` are exactly `ardt_ros_pipelines.recipes.ARDT_MODULES`, resolved from the same `ardt:` pin, so the same ardt runs in both;
- the last bootstrap step is `ardt deps`, which is the CI recipe's first step.

## Adding another profile

Copy this distribution's shape: a `pyproject.toml` with an `ardt.dev_profiles` entry point whose **name is the profile name**, an `__init__.py` declaring `ARDT_PLUGIN_API` and `ARDT_CONFIG_SECTION = "dev"`, a module exporting one `Profile`, and a Dockerfile template shipped as package data. The engine README lists the internals that are still colcon-shaped and would need generalizing first.
