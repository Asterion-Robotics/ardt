# ardt-pipelines

The Dagger plane of [ardt](../../README.md): the `ardt pipe` command group, the
`@pipeline` registry, and the shared helpers plugin pipelines build on.

## The mental model

A **task** (`ardt build`, `ardt test`) runs *in whatever environment you invoke
it from* — your shell, a devcontainer, a CI container. It wraps colcon/rosdep and
knows nothing about containers.

A **pipeline** (`ardt pipe run ros-ci`) is a Python function that *builds
disposable environments and runs tasks inside them*, then handles the artifact
side: image builds, multi-arch manifests, publishing, report export. It is what
a CI job executes — and because it's ordinary versioned Python, running it on
your laptop is byte-for-byte what CI does. CI YAML shrinks to a shim that picks
the pipeline name and decides `--publish`.

The one rule that keeps this sane (ci_tools 02): **pipelines orchestrate, tasks
build**. A pipeline never re-implements build logic; it starts a container and
calls `ardt build` in it. And all Dagger imports live in this package — tasks
and core never see it, so the inner loop works without any engine.

## What `ros-ci` actually does

**Repos own no Dockerfile.** The image recipe for the "ROS 2 workspace" repo
type lives in this package (`recipes/ros2.Dockerfile.tmpl`) and updates by
bumping the pinned ardt version — never by editing files across repos. The
recipe runs the ardt tasks as build stages, so *building the image is the CI
run*:

```
ardt pipe run ros-ci
│
├─ render the recipe from config (base_image, cmd, base.Dockerfile…)
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
| `base.Dockerfile` (file) | the only local Docker file a repo may carry: a single-stage base extension (`FROM ${BASE_IMAGE}` + layers below the app — drivers, kernel modules); spliced into the rendered recipe |

Updating the recipe for every repo of the type = one change here + a version
bump; repos update by bumping their pinned ardt, never by editing Dockerfiles.

## Authoring a pipeline

```python
from ardt_pipelines import pipeline

@pipeline(name="module-ci", doc="Build, test, publish a module")
async def module_ci(ctx, dag, platforms: list[str] = ("linux/amd64",)):
    ...
```

Parameters after `(ctx, dag)` become `--arg key=value` CLI options, coerced to
the annotated type (`str`, `int`, `float`, `bool`, `list[str]`). Expose the
module via an `ardt.pipelines` entry point and it appears in `ardt pipe list`.

## Engine

Auto-provisioned from the Docker socket locally (nothing to set up); on CI
runners the shim points `_EXPERIMENTAL_DAGGER_RUNNER_HOST` at a persistent
engine. `dagger-io` is pinned **exactly**; bumps are deliberate MRs run against
the pipeline test suite.
