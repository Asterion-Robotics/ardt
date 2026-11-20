## Why

A repository built `FROM` an image that ships a prebuilt install space (an SDK, a vendor stack) lists it in `tasks.ros.overlays`. `ardt deps` sources it before rosdep in the build stage, so rosdep skips the overlay's packages on its own (every package registered in the overlay's ament index) and `rosdep_skip_keys` can be empty. The runtime stage's rosdep pass ran raw rosdep without the overlays, so a repository with no skip keys failed there with `Cannot locate rosdep definition for [<overlay package>]`.

## What

- The runtime stage's rosdep pass sources each configured overlay's `local_setup.sh` (POSIX, the step runs under `sh`), in the configured order, before `rosdep install`. Under `--ignore-src` rosdep treats every package in the ament index of `AMENT_PREFIX_PATH` as workspace-built, so an overlay's packages resolve without a skip key. An overlay the runtime base image does not carry fails that step.
- `rosdep_skip_keys` still applies on top, unchanged.
- The build stage's deps layer needs nothing: it runs `ardt deps`, which already sources the overlays.
- `ros_ci._tasks_ros_list` replaces `_rosdep_skip_keys`: one raw reader for both `tasks.ros` lists.
- Tests at the rendered-Dockerfile level (`test_recipes.py`) and for the raw read (`test_ros_ci.py`); docs and changelog updated.

## Follow-ups once released

- Repositories that listed their overlay's packages in `rosdep_skip_keys` can drop those entries.
- Team guidance saying that every package an overlay provides must be in `rosdep_skip_keys` no longer holds.
