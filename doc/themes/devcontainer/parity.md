# The parity rule

The container a developer works in and the image CI builds must not drift. Four mechanisms enforce it, and `ardt dev doctor` fails when any of them does:

- **the base image**: the dev layer's base *is* `pipelines.ros_ci.builder`. That resolution order is why a repo with CI configured gets parity with nothing to keep in sync;
- **the ardt pin**: ardt installs from the repo's `ardt:` section via {py:mod}`ardt_core.dist`, producing the same requirement strings the `ros-ci` recipe installs into its build stage (readable afterwards in `.devcontainer/ardt-requirements.txt`);
- **the workspace tree**: the repo mounts where the recipe COPYs it (`/ws/src/<project>`), colcon runs from `/ws` in both, so CMake paths, `compile_commands.json` and stack traces read the same in both;
- **the first step**: `ardt dev bootstrap` runs the recipe's first step, `ardt deps`.

`ardt dev doctor` also warns when `ardt.version` is unpinned: a recipe is only reproducible when the ardt inside it is.
