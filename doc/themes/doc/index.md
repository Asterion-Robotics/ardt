# Documentation

The documentation theme builds a repo's docs the same way everywhere, from a `conf.py` that is three lines long.

| Plane | Package | Provides |
|---|---|---|
| tasks | `ardt-doc-tasks` | `ardt doc build` — doxygen then sphinx, one version from the working tree |
| pipelines | `ardt-doc-pipelines` | `docs-ci` — the versioned site under `public/`, Pages-ready |

The split follows the two-plane rule exactly: version aggregation and publishing belong to the pipeline, which runs the *same* `ardt doc build` task once per ref. These pages are themselves built by it.

```{toctree}
:maxdepth: 1

tasks
pipelines
```
