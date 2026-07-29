# ROS 2 pipelines

`ardt-ros-pipelines` provides the `ros-ci` pipeline and the image recipe it renders. It builds on `ardt-pipelines` and registers through the standard `ardt.pipelines` entry point — the machinery does not special-case it.

**Repos own no Dockerfile.** The recipe for this repo type (`recipes/ros2.Dockerfile.tmpl`) lives in the plugin and updates by bumping the pinned ardt version. Because the recipe runs the ardt tasks as build stages, *building the image is the CI run*:

```{image} ros-ci-stages.svg
:alt: The build target runs ardt deps, build and test as image stages and exports reports; the runtime target copies the install base and then installs its exec dependencies with rosdep.
:width: 100%
:align: center
```

```text
ardt pipe run ros-ci
│
├─ render the recipe from config (base_image, base.Dockerfile…)
│     → exported to pipeline-reports/Dockerfile.rendered on every run,
│       so `docker build -f … .` always works with no ardt installed
│
├─ build the `build` target        FROM pipelines.ros_ci.builder
│     1) ardt deps                 ← the same tasks, config and flags
│     2) ardt build                  as on a dev machine (two-plane rule)
│     3) ardt test                 ← red tests = failed image build
│     4) stage JUnit XMLs at /results
│     └─ exported → pipeline-reports/                 ← CI renders these
│
└─ build the `runtime` target
     5a) FROM base_image (⊕ the repo's base extension, if any)
         + COPY the built install base + CMD
     5b) rosdep install --dependency-types exec over that install base
         ← exec deps only, resolved from the share/*/package.xml files
           the copy brought along; skips tasks.ros.rosdep_skip_keys
      → always built (a broken runtime stage fails the MR run)
      → with --publish: one multi-arch manifest pushed as
        <registry>/<project>:<ctx.version>, digest in the --json envelope
```

Step 5b runs in the *runtime* stage, not the build stage, and it is raw `rosdep` rather than `ardt deps`. Both are deliberate. The runtime image starts from `base_image` alone, so everything rosdep installed into the builder is absent from it; and what it needs is the **exec** closure only, resolved from the install base it just copied, not the build and test dependencies `ardt deps` resolves from the source tree. There is no source tree and no ardt in the runtime image, and putting either there would ship a toolchain with the app. An unresolvable key fails the image build, which is the earliest moment it can be caught.

## Configuration

All knobs live under `pipelines.ros_ci:`.

| Knob | Role |
|---|---|
| `builder` | base of the build+test stage (process — never ships) |
| `base_image` | `FROM` of the **shipped** runtime image |
| `cmd` | the shipped image's CMD |
| `install_base` | where the workspace installs in the image (default `/opt/ros/app`) |
| `strip_dev_files` | IP protection: strip headers, static libs and CMake/pkg-config exports before the runtime copy |
| `platforms` | manifest platforms, e.g. `[linux/amd64, linux/arm64]` |
| `git_host` / `git_ssh_port` | auth for private `.repos` deps: CI job token, or a local ssh agent |
| `base.Dockerfile` (a file) | the only local Docker file a repo may carry: a single-stage base extension (`FROM ${BASE_IMAGE}` + layers below the app — drivers, kernel modules), spliced into the rendered recipe |

Until the baked `ardt-ci` tool image exists, the recipe pip-installs the ardt *task plane* (never the pipeline plane) into the build stage from `ardt_source`: the public git repo by default, or a local checkout for development — `ardt pipe run ros-ci --arg ardt_source=/path/to/ardt`.

The implementation is {py:mod}`ardt_ros_pipelines.ros_ci`.
