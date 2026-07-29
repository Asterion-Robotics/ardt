# ardt

[![ci](https://github.com/Asterion-Robotics/ardt/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/Asterion-Robotics/ardt/actions/workflows/ci.yml)
[![version](https://img.shields.io/github/v/tag/Asterion-Robotics/ardt?sort=semver&label=version)](https://github.com/Asterion-Robotics/ardt/tags)
[![docs](https://img.shields.io/badge/docs-latest-blue)](https://asterion-robotics.github.io/ardt/)

> The open core of Asterion Robotics' development tooling: **one small core, everything else a plugin.** Robotics or not. For instance, the core knows nothing about ROS; ROS-ness itself is a plugin.

One CLI for the three things every robotics repo needs: a dev container, CI that runs the same commands a developer does, and versioned docs. Tasks run wherever you invoke them; pipelines run those same tasks *inside* containers, so a green CI run means the commands you type locally passed.

**[Documentation](https://asterion-robotics.github.io/ardt/)**: concepts, configuration, and what each plugin adds.

**Demo**: [`ardt_ros2_demo`](https://github.com/Asterion-Robotics/ardt_ros2_demo) ([GitLab mirror](https://gitlab.com/tpoignonec/ardt_ros2_demo)) is a minimal but complete ROS 2 workspace driven end-to-end by ardt: tasks, dev container, and a CI that is nothing but "install ardt, run two pipelines", on both GitHub Actions and GitLab CI.

## Install

```bash
# If needed, install uv beforehand
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install ARDT tools
curl -LsSf https://raw.githubusercontent.com/Asterion-Robotics/ardt/main/install.sh | bash
```

[uv](https://docs.astral.sh/uv/) is the only prerequisite, and ardt's installer will not install it for you: chaining installers hides what you are trusting. Run from a repo checkout, the installer honors the repo's `ardt.yaml`: `ardt.version` pins the ref, and `ardt.install_extras` / `ardt.install_skip` adjust the default module bundle (core + pipelines + the ROS 2 task/pipeline plugins, plus `ardt-devcontainers` and `ardt-ros-dev` outside CI; doc plugins are opt-in — the policy is spelled out in the script). `ARDT_REF=v0.1.0` and `ARDT_MODULES="…"` override both. [`install.sh`](install.sh) is short, and worth reading before you pipe it anywhere.

Other routes — a published release, a fork, an editable checkout — are under *Getting started* in the [documentation](https://asterion-robotics.github.io/ardt/).

## ROS 2

```bash
ardt deps                  # vcs import, then rosdep
ardt build                 # colcon, with the repo's build args
ardt test                  # colcon test, summarized

ardt pipe run ros-ci       # the same three, as image build stages
```

The pipeline needs Docker and nothing else: no Dockerfile in your repo, no colcon on your host.

## Documentation

```bash
ardt doc build             # sphinx, plus doxygen for C++; warnings are errors

ardt pipe run docs-ci      # every version of the site into public/
```

`docs-ci` builds the working tree plus every configured branch and tag, each from its own history, into one Pages-ready site with a version switcher.

## Dev container

```bash
ardt dev open              # everything: render, volumes, build, start, attach VS Code
```

One command does whatever is missing (`ardt dev up` is the editor-less variant; `sync`, `volumes`, `shell`, `down` exist for driving the steps by hand). Inside, the container is a canonical colcon workspace — repo at `/ws/src/<name>`, colcon output at `/ws/{build,install,log}`, never inside your checkout — and its base image *is* the CI builder, so what you debug in is what builds. `ardt dev doctor` fails if the two drift.

## License

Apache-2.0. See [LICENSE](LICENSE). The internal plugins that carry Asterion's own processes install alongside these, through the same entry points any third-party plugin uses.
