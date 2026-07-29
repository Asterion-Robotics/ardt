# Demo with a ROS 2 project

The official demo repo, [`ardt_ros2_demo`](https://github.com/Asterion-Robotics/ardt_ros2_demo), is a minimal but complete ROS 2 workspace driven end-to-end by ardt. The same repo is mirrored on GitLab as [`tpoignonec/ardt_ros2_demo`](https://gitlab.com/tpoignonec/ardt_ros2_demo), so both hosting flavors are covered: `.github/workflows/ci.yml` for GitHub Actions + GitHub Pages, `.gitlab-ci.yml` for GitLab CI + GitLab Pages. Both CI files are deliberately thin (install ardt, run two pipelines) because the rosdep/colcon/sphinx/doxygen commands, the container recipes and the site layout all live in ardt, pinned by `ardt.version` in the repo's `ardt.yaml`.

## What it exercises

Three small packages plus an aggregator, chosen to touch every plugin:

- `ardt_ros2_demo_pkg_1` (`ament_python`): a counter node with the logic split out for tests and Sphinx autodoc.
- `ardt_ros2_demo_pkg_2` (`ament_cmake`): a C++ library with Doxygen comments and gtest.
- `ardt_demo_ros2_msgs`: msg/srv/action files written with the comment conventions the doc tooling renders into interface tables.
- `ardt_ros2_demo` (aggregator): groups the others and hosts the repo docs.

## Try it

From a checkout, the whole task plane runs without Docker:

```bash
ardt deps        # rosdep install
ardt build       # colcon build
ardt test        # colcon test + summary
ardt doc build   # doxygen + sphinx -> build/doc/html/index.html
ardt doc serve   # preview the result at http://127.0.0.1:8000/
```

The two pipelines need Docker and nothing else (no Dockerfile in the repo, no colcon on the host):

```bash
ardt pipe run ros-ci    # deps/build/test as image stages
ardt pipe run docs-ci   # the versioned site (working tree + every v* tag) -> public/
```

## What to read it for

- **The repo-side footprint.** One [`ardt.yaml`](https://github.com/Asterion-Robotics/ardt_ros2_demo/blob/main/ardt.yaml), one 5-line Sphinx `conf.py`, two short CI files. Everything else is content, which makes it a good template for what *your* repo needs to carry.
- **The CI shape.** [`ci.yml`](https://github.com/Asterion-Robotics/ardt_ros2_demo/blob/main/.github/workflows/ci.yml) and [`.gitlab-ci.yml`](https://gitlab.com/tpoignonec/ardt_ros2_demo/-/blob/main/.gitlab-ci.yml) run the exact commands you type locally, so a green run means your local build passes. The GitLab file also documents the one real platform difference: pipelines drive containers through a Docker daemon, which GitHub runners have for free and GitLab needs `docker:dind` for.
- **The doc features.** The published site shows hand-written RST (math, mermaid), Python autodoc with ROS imports mocked (no colcon build needed), C++ via Doxygen/breathe, and interface tables generated straight from the `.msg`/`.srv`/`.action` files.
