# Tasks

A **task** runs *in whatever environment you invoke it from*: your shell, a devcontainer, a CI container. It wraps the tool a developer would otherwise run by hand (colcon, rosdep, sphinx, doxygen) and knows nothing about containers.

```bash
ardt deps      # vcs import + rosdep install     (ardt-ros-tasks)
ardt build     # colcon build                    (ardt-ros-tasks)
ardt test      # colcon test + result summary    (ardt-ros-tasks)
ardt doc build # doxygen + sphinx                (ardt-doc-tasks)
ardt dev up    # the repo's devcontainer         (ardt-devcontainers)
```

## What a task guarantees

**Same flags everywhere.** The task reads `ardt.yaml`, so a developer's `ardt build` and CI's `ardt build` differ in *where* they run, never in *what* they run. This is what makes "works on my machine" a testable claim instead of an excuse.

**Fixed output conventions.** Artifacts land at paths pipelines can export blindly, with no per-repo wiring:

| Artifact | Convention |
|---|---|
| JUnit XML | `build/**/test_results/**/*.xml` |
| HTML docs | `build/doc/html` |
| Doxygen XML | `build/doc/doxygen/xml` |

**No engine.** A task plugin never imports Dagger. That is a hard boundary, not a style preference: it keeps `ardt build` usable on a machine with no Docker.

## Anatomy

A task plugin is a normal Python distribution that exposes click commands through the `ardt.commands` entry point. The command function is a thin front over a library function taking the {py:class}`~ardt_core.context.Context`:

```python
@doc.command()
@pass_ardt
def build(ctx: Context) -> None:
    """Build the docs: doxygen (C++ repos) then sphinx html into build/doc."""
    tasks.build(ctx)
```

`ctx` carries git facts, normalized CI facts, the typed config, the version, the console and the subprocess runner — see [Extending ardt](extending.md).
