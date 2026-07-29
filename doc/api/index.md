# Python API

One page per distribution, one section per module. The pages autodoc the **installed** packages, so they describe exactly the ardt that built them — build from the workspace venv to document the working tree.

| Distribution | Role |
|---|---|
| [`ardt-core`](ardt_core.md) | the CLI, the plugin loader, the context, the config |
| [`ardt-pipelines`](ardt_pipelines.md) | the generic Dagger plane |
| [`ardt-devcontainers`](ardt_devcontainers.md) | the devcontainer engine |
| [`ardt-ros-tasks`](ardt_ros_tasks.md) / [`ardt-ros-pipelines`](ardt_ros_pipelines.md) / [`ardt-ros-dev`](ardt_ros_dev.md) | the ROS 2 theme |
| [`ardt-doc-tasks`](ardt_doc_tasks.md) / [`ardt-doc-pipelines`](ardt_doc_pipelines.md) | the documentation theme |

Public surface: everything documented here is importable by plugins. {py:class}`~ardt_core.context.Context`, {py:mod}`ardt_core.config` and {py:mod}`ardt_core.testing` are the three a plugin author touches first.

{py:mod}`ardt_core.testing` is the one module with a dependency the core install deliberately omits: it ships pytest fixtures, so reach for it as `ardt-core[testing]`.

```{toctree}
:maxdepth: 1

ardt_core
ardt_pipelines
ardt_devcontainers
ardt_ros_tasks
ardt_ros_pipelines
ardt_ros_dev
ardt_doc_tasks
ardt_doc_pipelines
```
