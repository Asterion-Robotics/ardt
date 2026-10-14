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
