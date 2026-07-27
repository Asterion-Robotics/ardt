# Concepts

ardt is a click CLI with a plugin loader and a typed context, and nothing else. `ardt-core` depends on `click`, `pydantic`, `pyyaml` and `rich` — installing it never drags in ROS or a container engine.

Everything a developer actually runs arrives as a **plugin**, discovered through Python entry points and guarded by a plugin API version. A plugin contributes one of two things, and the difference between them is the central idea of the platform.

```{image} plugin-planes.svg
:alt: ardt-core beside the pipeline plane (ardt-pipelines, ardt-ros-pipelines, ardt-doc-pipelines) and the task plane (ardt-ros-tasks, ardt-doc-tasks, ardt-dev); the pipeline plane runs tasks inside containers.
:width: 100%
:align: center
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
