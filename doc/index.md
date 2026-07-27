# ardt

**A**sterion **R**obotics **D**evelopment **T**ools: the company-wide developer/CI CLI platform, built on one rule — **one small core, everything else a plugin**. Robotics or not; the core knows nothing about ROS, and ROS-ness itself is a plugin.

```bash
ardt info          # the resolved context: git facts, CI facts, config, version
ardt plugins       # what is loaded, from where, at which plugin API version
ardt build         # a task, in the environment you invoked it from
ardt pipe run ros-ci   # a pipeline: containers, images, publishing
```

```{toctree}
:maxdepth: 2
:caption: Using ardt

getting-started
concepts/index
```

```{toctree}
:maxdepth: 2
:caption: Themes

themes/index
themes/devcontainer/index
themes/ros2/index
themes/doc/index
```

```{toctree}
:maxdepth: 2
:caption: Reference

api/index
```
