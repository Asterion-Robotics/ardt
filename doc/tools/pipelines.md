# Pipelines

`ardt pipe` is the CI-facing half of ardt: it stands a container up with Dagger and runs tasks inside it. [Pipelines](../concepts/pipelines.md) is the model and the authoring guide; this page is the command surface.

| Command | Does |
|---|---|
| `ardt pipe list` | every registered pipeline, with its `--arg` parameters, types and defaults |
| `ardt pipe run <name>` | run one |
| `ardt pipe run <name> --dry-run` | bind the arguments and print the plan, without Dagger or a docker daemon |

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

The Dagger SDK is imported only when a run actually begins. `ardt pipe list`, `--help` and `--dry-run` never touch it, so they stay fast and work on a machine with no daemon running. That is also what makes `--dry-run` a usable check in a pre-commit hook or a CI lint job.

## Artifacts

Reports and exported files land under `pipeline-reports/` at the project root, a fixed convention so nothing needs per-repo wiring. `pipeline-reports/Dockerfile.rendered` is the ardt-free escape hatch: `docker build -f pipeline-reports/Dockerfile.rendered .` reproduces the image on a machine with nothing installed.

## Engine

Locally the Dagger engine is auto-provisioned from the Docker socket, with nothing to set up. On a CI runner, point `_EXPERIMENTAL_DAGGER_RUNNER_HOST` at a persistent engine so successive jobs share its cache. `dagger-io` is pinned exactly; bumps are deliberate and run against the pipeline test suite.
