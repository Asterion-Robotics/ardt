# ardt-cli

The `ardt` CLI plus its first-party plugins, in one install.

```bash
uv tool install ardt-cli                  # the CLI and the pipeline plane
uv tool install "ardt-cli[ros]"           # + the ROS 2 theme
uv tool install "ardt-cli[doc]"           # + the documentation theme
uv tool install "ardt-cli[devcontainer]"  # + `ardt dev`
uv tool install "ardt-cli[all]"           # everything
```

No code of its own: the dependencies are the payload. Each theme is an extra, so
installing ardt never pulls in a toolchain the repo will not use.

`devcontainer` rather than `dev`, because an extra named `dev` usually means the
tooling to develop *this package*.

See the [ardt repository](https://github.com/Asterion-Robotics/ardt) for what
each plugin does.
