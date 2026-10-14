# Pipelines

A **pipeline** is a Python function that *builds disposable environments and runs tasks inside them*, then handles the artifact side: image builds, multi-arch manifests, publishing, report export.

```bash
ardt pipe list             # what is registered
ardt pipe run ros-ci       # build + test as image stages, on docker buildx
ardt pipe run docs-ci      # the versioned docs site into public/
```

Because a pipeline is ordinary versioned Python, running it on a laptop is byte-for-byte what CI does. CI YAML shrinks to a shim that picks a pipeline name and decides `--publish`.

An image-producing pipeline has two artifact destinations, each an explicit flag: `--publish` pushes the multi-arch image to the registry (and errors when none is configured), `--load` puts the native-arch image into the local docker daemon as the *moving* tag `<project>:<X.Y.Z>-dev` (the release being developed) — each load overwrites it, so stale predecessors dangle for `docker image prune` instead of one tag per commit piling up (a release load additionally gets the pinned `<project>:<version>`). The exported `Dockerfile.rendered` stays the third, ardt-free route: `docker build -f pipeline-reports/Dockerfile.rendered .` reproduces the image with nothing installed.

## The one rule

**Pipelines orchestrate, tasks build.** A pipeline never re-implements build logic; it starts a container and calls `ardt build` inside it. Consequences worth stating explicitly:

- red tests are a *failed image build*, because the tasks run as build stages;
- there is exactly one definition of "how this repo builds", and it is the task;
- every `docker` invocation lives in `ardt_pipelines.buildx`, so core and tasks never see one.

## Authoring

```python
from ardt_pipelines import pipeline

@pipeline(name="module-ci", doc="Build, test, publish a module")
def module_ci(ctx, builder, platforms: list[str] = ("linux/amd64",)):
    ...
```

Parameters after `(ctx, builder)` become `--arg key=value` CLI options, coerced to the annotated type (`str`, `int`, `float`, `bool`, `list[str]`). Expose the module through an `ardt.pipelines` entry point and it appears in `ardt pipe list`.

`ardt_pipelines.std` carries the shared helpers: image and cache references, how credentials reach a build, the digest records of a split publish; `ardt_pipelines.buildx` is the executor a pipeline describes bake targets to.

## Executor

A pipeline runs on BuildKit through `docker buildx bake`: it renders its recipe and a bake file (one target per Dockerfile stage it needs, with platforms, outputs, registry cache and secrets) into `pipeline-reports/`, then bakes the targets it needs. Nothing is set up on a machine with Docker: the `ardt` builder (a `docker-container` driver, needed for multi-platform builds, registry cache and local outputs) is created on first use. Two properties follow from building this way and are the reason for it: the base layers of a published image are the registry's own blobs, byte for byte, so every image of a fleet shares one base chain on a host; and the layer cache lives in the registry (`cache-to type=registry`, written by CI runs, read by every run that can reach the registry), so it survives any daemon, runner or restart.

Native builders for other architectures are a CI layout, not a pipeline concern: one job per platform (`--arg platforms=<one>`) on a runner of that architecture pushes its image by digest and records it under `pipeline-reports/digests/`; `ardt pipe merge` creates the tag from the records once they sit together. A single run that builds every platform needs no merge, bake assembles the manifest list itself (QEMU, or a builder with native nodes appended).
