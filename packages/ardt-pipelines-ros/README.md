# ardt-pipelines-ros

The pipeline plugin for **ROS 2 workspace repos**: the `ros-ci` pipeline and the
`ros2` image recipe it renders. Builds on [ardt-pipelines](../ardt-pipelines)
(the generic Dagger plane) and registers through the standard `ardt.pipelines`
entry point — the machinery does not special-case it.

**Repos own no Dockerfile.** The image recipe for this repo type lives here
(`recipes/ros2.Dockerfile.tmpl`) and updates by bumping the pinned ardt version
— never by editing files across repos. The recipe runs the ardt tasks as build
stages, so *building the image is the CI run*:

```
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
      5) FROM base_image (⊕ the repo's base extension, if any)
         + COPY the built install base + CMD
      → always built (a broken runtime stage fails the MR run)
      → with --publish: one multi-arch manifest pushed as
        <registry>/<project>:<ctx.version>, digest in the --json envelope
```

Per-repo knobs, all in `ardt.yaml` (`pipelines.ros_ci:`):

| Knob | Role |
|---|---|
| `builder` | base of the build+test stage (process — never ships) |
| `base_image` | `FROM` of the **shipped** runtime image |
| `cmd` | the shipped image's CMD |
| `install_base` | where the workspace installs in the image (default `/opt/ros/aos`) |
| `strip_dev_files` | IP protection: strip headers, static libs and CMake/pkg-config exports before the runtime copy |
| `base.Dockerfile` (file) | the only local Docker file a repo may carry: a single-stage base extension (`FROM ${BASE_IMAGE}` + layers below the app — drivers, kernel modules); spliced into the rendered recipe |

Until the baked `ardt-ci` tool image exists (B4), the recipe pip-installs the
ardt *task plane* (never the pipeline plane) into the build stage from
`ardt_source` — the public git repo by default, or a local checkout for
development: `ardt pipe run ros-ci --arg ardt_source=/path/to/ardt`.
