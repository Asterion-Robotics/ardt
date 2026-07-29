# Pipelines

A **pipeline** is a Python function that *builds disposable environments and runs tasks inside them*, then handles the artifact side: image builds, multi-arch manifests, publishing, report export.

```bash
ardt pipe list             # what is registered
ardt pipe run ros-ci       # build + test in a container, via Dagger
ardt pipe run docs-ci      # the versioned docs site into public/
```

Because a pipeline is ordinary versioned Python, running it on a laptop is byte-for-byte what CI does. CI YAML shrinks to a shim that picks a pipeline name and decides `--publish`.

An image-producing pipeline has two artifact destinations, each an explicit flag: `--publish` pushes the multi-arch image to the registry (and errors loudly when none is configured — it never silently goes elsewhere), `--load` puts the native-arch image into the local docker daemon as `<project>:<version>` for `docker run`-level poking. The exported `Dockerfile.rendered` stays the third, ardt-free route: `docker build -f pipeline-reports/Dockerfile.rendered .` reproduces the image with nothing installed.

## The one rule

**Pipelines orchestrate, tasks build.** A pipeline never re-implements build logic; it starts a container and calls `ardt build` inside it. Consequences worth stating explicitly:

- red tests are a *failed image build*, because the tasks run as build stages;
- there is exactly one definition of "how this repo builds", and it is the task;
- all Dagger imports live in `ardt-pipelines`, so core and tasks never see it.

## Authoring

```python
from ardt_pipelines import pipeline

@pipeline(name="module-ci", doc="Build, test, publish a module")
async def module_ci(ctx, dag, platforms: list[str] = ("linux/amd64",)):
    ...
```

Parameters after `(ctx, dag)` become `--arg key=value` CLI options, coerced to the annotated type (`str`, `int`, `float`, `bool`, `list[str]`). Expose the module through an `ardt.pipelines` entry point and it appears in `ardt pipe list`.

`ardt_pipelines.std` carries the shared helpers: source directories, cache volumes, image refs, registry secrets, multi-arch publish.

## Engine

The Dagger engine is auto-provisioned from the Docker socket locally, with nothing to set up. On CI runners the shim points `_EXPERIMENTAL_DAGGER_RUNNER_HOST` at a persistent engine. `dagger-io` is pinned **exactly**; bumps are deliberate MRs run against the pipeline test suite.
