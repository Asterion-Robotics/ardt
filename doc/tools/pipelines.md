# Pipelines

`ardt pipe` is the CI-facing half of ardt: it builds the images a recipe describes on docker buildx and runs tasks inside their stages. [Pipelines](../concepts/pipelines.md) is the model and the authoring guide; this page is the command surface.

| Command | Does |
|---|---|
| `ardt pipe list` | every registered pipeline, with its `--arg` parameters, types and defaults |
| `ardt pipe run <name>` | run one |
| `ardt pipe run <name> --dry-run` | bind the arguments and print the plan, without a docker daemon |
| `ardt pipe merge` | one manifest list from the per-platform images a split publish pushed by digest |

| Flag on `run` | Does |
|---|---|
| `--arg KEY=VALUE` | set a pipeline parameter, repeatable; coerced to the annotated type |
| `--publish` | allow the pipeline to push artifacts (errors when no registry is configured) |
| `--load` | put the native-arch image into the local docker daemon |

Pipelines come from installed plugins, through the `ardt.pipelines` entry point. **The name is the whole address**: `ros-ci` means the same pipeline everywhere, and two plugins registering one name is a hard error at collection time rather than a silent last-one-wins.

```bash
ardt pipe run ros-ci --arg platforms=linux/amd64,linux/arm64 --publish
```

An unknown name fails with the registered names as the hint, and a malformed `--arg` fails before anything starts. Both are one-line diagnoses, never a traceback ([CLI conventions](cli.md)).

## What a run costs before it runs

Docker is invoked only when a run actually begins. `ardt pipe list`, `--help` and `--dry-run` never touch it, so they stay fast and work on a machine with no daemon running. That is also what makes `--dry-run` a usable check in a pre-commit hook or a CI lint job.

## Artifacts

Reports and exported files land under `pipeline-reports/` at the project root, a fixed convention so nothing needs per-repo wiring: the JUnit XMLs and the logs staged beside them, `test-exit-code` (the exit code of the test step, on which a run fails after the export), and the rendered recipe. `pipeline-reports/Dockerfile.rendered` is the ardt-free escape hatch: `docker build -f pipeline-reports/Dockerfile.rendered .` reproduces the image on a machine with nothing installed but Docker with BuildKit (the default since Docker 23.0; the recipe's test step uses `RUN --network=none`, which the legacy builder rejects).

## Executor

`docker buildx bake` against the `ardt` builder (a `docker-container` driver), created on first use; a CI job class may pre-create it and append native nodes for other architectures. The bake file of every run is exported as `pipeline-reports/bake.json` beside the rendered recipe, so `docker buildx bake -f pipeline-reports/bake.json reports` reproduces the gate with no ardt installed. The layer cache is a `cache` sub-image of the project in the registry, one tag per stage: CI runs write it, every run reads it.

## The builder and its cache

The builder is one container, `buildx_buildkit_ardt0`, running a pinned BuildKit, with its state in the volume `buildx_buildkit_ardt0_state`. That volume is what makes the second run fast, on a laptop as on a runner that keeps the builder between jobs:

| It holds | Keyed by | Shared |
|---|---|---|
| the layer cache of every stage built on this builder | content | across the repositories built here |
| the apt cache mounts (`/var/cache/apt`, the lists) | architecture | across repositories: a deb fetched for one module serves the next |
| the ccache mount | architecture | across repositories, once the builder image ships `ccache` and the repo opts in |

ardt creates the builder with a garbage-collection policy (`maxUsedSpace = "40GB"`, `minFreeSpace = "10%"` of the disk): BuildKit keeps the cache under that ceiling by itself, oldest and least used first, so nothing has to be purged by hand. The commands when you want to look or act anyway:

```bash
docker buildx du --builder ardt                 # what the cache holds, by record
docker buildx prune --builder ardt              # drop the unused records now (the GC, forced)
docker buildx prune --builder ardt --all        # drop everything, including the layers in use
docker buildx rm --keep-state ardt              # remove the builder, keep its cache: the next run
                                                #   recreates it, with a new configuration if you pass one
docker buildx rm ardt                           # remove the builder and its cache: a full reset
```

### Sizing the cache yourself

The ceiling is a property of the builder, so it is set once per host where the builder is created, never per repository or per run. It lives in BuildKit's [`buildkitd.toml`](https://docs.docker.com/build/buildkit/toml-configuration/), section `[worker.oci]`. The simple shape, one ceiling for everything:

```toml
[worker.oci]
  gc = true
  maxUsedSpace = "40GB"    # prune until the cache is under this
  minFreeSpace = "10%"     # and until the disk keeps at least this much free
  # reservedSpace = "10GB" # never prune below this, even when the disk is tight
```

The fine shape, ordered rules where the first match wins, to keep the apt and ccache mounts longer than the layers:

```toml
[worker.oci]
  gc = true

  [[worker.oci.gcpolicy]]
    filters = ["type==exec.cachemount"]   # the cache mounts: a month, up to 10 GB
    keepDuration = "720h"
    maxUsedSpace = "10GB"

  [[worker.oci.gcpolicy]]                 # everything else: a week, up to 40 GB
    keepDuration = "168h"
    maxUsedSpace = "40GB"
    minFreeSpace = "10%"
```

Sizes take a byte count, a unit (`"512MB"`) or a percentage of the disk; `docker buildx inspect ardt` prints the rules in force as `GC Policy rule#N`, which is how to check what a builder runs.

**Locally**, recreate the builder with your file and keep its cache:

```bash
docker buildx rm --keep-state ardt
docker buildx create --name ardt --driver docker-container \
  --driver-opt image=moby/buildkit:v0.33.1 \
  --buildkitd-config ~/.config/ardt/buildkitd.toml --bootstrap
```

ardt reattaches to any builder named `ardt`, so what you created wins over its default from then on.

**On a CI runner**, the builder is host infrastructure: created once by whatever provisions the runner, as the user the jobs run as, sized for that disk, and capped so a build cannot starve the runner's other jobs. Jobs reattach to it and need nothing beyond the registry login.

```bash
docker buildx create --name ardt --driver docker-container \
  --driver-opt image=moby/buildkit:v0.33.1 \
  --driver-opt memory=12g --driver-opt cpu-quota=600000 \
  --buildkitd-config /etc/ardt/buildkitd.toml --bootstrap
```

A registry mirror or an insecure registry go into the same file. With a throwaway daemon per job there is no builder to size: the default rule applies to a cache that dies with the job, and the registry cache does the work.
