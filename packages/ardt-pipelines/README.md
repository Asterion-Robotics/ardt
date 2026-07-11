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

## What this package contains — and deliberately does not

This is the **generic machinery only**: the `@pipeline` registry and parameter
binding, the `ardt pipe list/run` CLI, the engine connection (the single place
the exact `dagger-io` pin is exercised), and `std` helpers (source dirs, cache
volumes, image refs, registry secrets, multi-arch publish).

It knows nothing about ROS or any repo type. Domain pipelines live in their own
plugins that depend on this package and register via the `ardt.pipelines`
entry point — e.g. [ardt-pipelines-ros](../ardt-pipelines-ros) provides
`ros-ci` and the ROS 2 image recipe.

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
