# Concepts

ardt is a click CLI with a plugin loader and a typed context, and nothing else. `ardt-core` depends on `click`, `pydantic`, `pyyaml` and `rich` — installing it never drags in ROS or a container engine.

Everything a developer actually runs arrives as a **plugin**, discovered through Python entry points and guarded by a plugin API version. A plugin contributes one of two things, and the difference between them is the central idea of the platform.

```{mermaid}
flowchart LR
    subgraph pipelines["pipeline plane — ardt pipe run"]
      P["ardt-pipelines<br/>@pipeline registry, Dagger"]
      RP["ardt-ros-pipelines"]
      DP["ardt-doc-pipelines"]
    end
    subgraph tasks["task plane — ardt build / test / doc"]
      RT["ardt-ros-tasks"]
      DT["ardt-doc-tasks"]
      DV["ardt-dev"]
    end
    C["ardt-core<br/>cli · context · config · runner"]
    C --- tasks
    C --- pipelines
    pipelines -->|runs tasks inside containers| tasks
```

Pipelines call tasks *inside* containers; tasks never call pipelines. Core imports neither ROS nor Dagger, so the inner loop works with no engine installed.

```{toctree}
:maxdepth: 1

tasks
pipelines
configuration
versioning
extending
```
