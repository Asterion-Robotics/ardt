# Configuration

One file per repo: `ardt.yaml` at the project root, or a `[tool.ardt]` table in `pyproject.toml` — same model, the file wins. **Nothing in it is required**: a repo with no config gets defaults everywhere.

The project root is found by walking up from the working directory to the first `ardt.yaml` / `ardt.yml`, or failing that the first `.git`.

## Namespaced sections

Core owns `project:` and `ardt:`, plus the reserved `check:` section (parsed for typo-safety; nothing consumes it yet). Everything else belongs to a plugin, which claims its section and parses it into its own pydantic model — core never knows their shape.

```yaml
project:
  name: my_robot          # defaults to the project-root directory name

ardt:                     # the one ardt pin: pipelines install it inside their
                          # images, install.sh honors it on workstations and CI
  git: git+https://github.com/Asterion-Robotics/ardt.git
  version: v0.3.0         # pin it: a recipe is reproducible only when its ardt is
  install_extras: [ardt-doc-tasks, ardt-doc-pipelines]  # install.sh: add to its bundle
  install_skip: [ardt-ros-dev]                          # install.sh: drop from it

tasks:
  ros:                    # ardt-ros-tasks
    distro: jazzy
  doc:                    # ardt-doc-tasks
    strict: true

pipelines:
  ros_ci:                 # ardt-ros-pipelines
    base_image: ros:jazzy-ros-base
  docs_ci:                # ardt-doc-pipelines
    versions:
      branches: [main]

dev:                      # ardt-devcontainers
  profile: ros2
```

## Typo-safety without coupling

An unknown section is an **error** — unless it is a name reserved for a first-party plugin that simply is not installed here, in which case it is a **warning**. So `doc:` on a machine without `ardt-doc-tasks` is tolerated, while `docs:` is caught. The reserved set lives in `ardt_core.config`; growing it is a core release, and third-party sections are recognized once their plugin is installed.

See [`ardt.example.yaml`](https://github.com/Asterion-Robotics/ardt/blob/main/ardt.example.yaml) for the annotated, exhaustive version, and {py:mod}`ardt_core.config` for the API.
