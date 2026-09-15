# The parity rule

The container a developer works in and the image CI builds must not drift. Five mechanisms enforce it, and `ardt dev doctor` fails when any of them does:

- **the base image**: the dev layer's base *is* `pipelines.ros_ci.builder`. That resolution order is why a repo with CI configured gets parity with nothing to keep in sync;
- **the ardt pin**: ardt installs from the repo's `ardt:` section via {py:mod}`ardt_core.dist`, producing the same requirement strings the `ros-ci` recipe installs into its build stage (readable afterwards in `.devcontainer/ardt-requirements.txt`);
- **the workspace tree**: the repo mounts where the recipe COPYs it (`/ws/src/<project>`), colcon runs from `/ws` in both, so CMake paths, `compile_commands.json` and stack traces read the same in both;
- **the first step**: `ardt dev bootstrap` runs the recipe's first step, `ardt deps`;
- **the environment**: the dev shell sources what the tasks source, `/opt/ros/<distro>/setup.bash` then each `tasks.ros.overlays` entry's `local_setup.bash` in order, before the workspace; `c_cpp_properties.json` lists the overlay include paths between the workspace and the distro. `ardt dev doctor` reports the overlays and, inside the container, fails when one has no `local_setup.bash`.

`ardt dev doctor` also reports the ardt pin: `ardt.version` when set, else the release of the running ardt (a released ardt installs itself inside the images it renders). It warns only when a dev build of ardt renders without a pin: that recipe tracks HEAD and is not reproducible.
