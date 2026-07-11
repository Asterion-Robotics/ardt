# ardt-pipelines

The Dagger plane of [ardt](../../README.md): the `ardt pipe` command group, the
`@pipeline` registry, and the shared helpers plugin pipelines build on.

- **The two-plane rule (ci_tools 02):** all Dagger imports live here and in plugin
  `pipelines` modules — tasks and core never import it. `dagger-io` is pinned
  **exactly**; bumps are deliberate MRs run against the pipeline test suite.
- **Authoring:** a pipeline is a plain async function, registered by decorator;
  parameters come from `--arg k=v`, coerced to the annotated types:

  ```python
  from ardt_pipelines import pipeline

  @pipeline(name="module-ci", doc="Build, test, publish a module")
  async def module_ci(ctx, dag, platforms: list[str] = ("linux/amd64",)):
      ...
  ```

  Expose the module via an `ardt.pipelines` entry point and it shows up in
  `ardt pipe list`.
- **Built-ins:** `ros-ci` — the interim generic pipeline (build + test a ROS 2
  workspace in a pinned builder image, JUnit XMLs exported to
  `pipeline-reports/`, image publish on `--publish`).
- **Engine:** auto-provisioned from the Docker socket locally; on CI runners the
  shim points `_EXPERIMENTAL_DAGGER_RUNNER_HOST` at a persistent engine.
