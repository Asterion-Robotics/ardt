"""Dev profiles — the per-repo-type knowledge, expressed as data.

A profile answers: which base image, which extra apt packages, which ardt
modules the container needs, what to run once the container exists, and which
editor extensions make the language work. It is deliberately *data*: ardt-dev
imports no ROS package and no pipeline plugin, so a laptop install stays tiny.

Adding a profile is adding an entry to :data:`PROFILES` (plus a Dockerfile
template). When a domain plugin needs its own (``aos-module``: SDK builder base,
plugin export layout), the same table is what an ``ardt.dev_profiles`` entry
point would populate — that indirection is not worth building for one profile.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ardt_core.errors import ArdtError

DISTRO = "@DISTRO@"
"""Token replaced with the repo's ROS distro at render time."""


@dataclass(frozen=True)
class Profile:
    """Everything that differs between one kind of repo and another."""

    name: str
    summary: str
    dockerfile: str
    """Template file name in :mod:`ardt_dev.templates`."""
    default_base_image: str
    """Used when the repo pins no ``pipelines.ros_ci.builder`` and no
    ``dev.base_image``. May contain the :data:`DISTRO` token."""
    ardt_modules: tuple[str, ...]
    """ardt distributions installed in the container. The first two of the ROS
    profile are exactly ``ardt_ros_pipelines.recipes.ARDT_MODULES`` — the same
    modules CI's build stage installs, from the same ``ardt:`` pin."""
    apt_groups: tuple[tuple[str, tuple[str, ...]], ...]
    """``(label, packages)`` — labels become comments in the rendered recipe, so
    a human debugging the image can see why each group is there."""
    bootstrap: tuple[tuple[str, ...], ...]
    """Commands ``ardt dev bootstrap`` runs inside the container, in order."""
    extensions: tuple[str, ...]
    settings: dict[str, object] = field(default_factory=dict)
    container_env: dict[str, str] = field(default_factory=dict)


ROS2 = Profile(
    name="ros2",
    summary="ROS 2 workspace: colcon toolchain, rviz2/rqt, clangd, gdb",
    dockerfile="ros2.Dockerfile.tmpl",
    default_base_image=f"ros:{DISTRO}-ros-base",
    ardt_modules=("ardt-core", "ardt-ros-tasks", "ardt-doc-tasks"),
    apt_groups=(
        # What CI's build stage installs (recipes/ros2.Dockerfile.tmpl), so the
        # dev layer is strictly additive over it.
        ("as in the CI build stage", ("build-essential", "git", "python3-pip", "openssh-client")),
        ("toolchain", ("cmake", "ninja-build", "ccache", "pkg-config")),
        ("ROS dev tooling (colcon extensions, mixins, rosdep, vcstool)", ("ros-dev-tools",)),
        ("debuggers and analysers", ("gdb", "valgrind", "cppcheck")),
        # IDE-side only: `ardt check` remains the CI truth for format/lint.
        ("language servers and formatters", ("clangd", "clang-format", "clang-tidy")),
        (
            "GUI tools — the reason a dev image exists at all",
            (
                f"ros-{DISTRO}-rviz2",
                f"ros-{DISTRO}-rqt-common-plugins",
                "x11-utils",
                "mesa-utils",
                "libgl1-mesa-dri",
            ),
        ),
        ("docs toolchain (ardt doc build)", ("doxygen", "graphviz")),
        ("shell", ("bash-completion", "sudo", "curl", "wget", "jq", "less", "nano", "unzip")),
    ),
    bootstrap=(
        ("sudo", "apt-get", "update", "-qq"),
        ("rosdep", "update", "--rosdistro", DISTRO),
        # Identical to the CI recipe's step 1 — the whole point of the exercise.
        ("ardt", "deps"),
    ),
    extensions=(
        "llvm-vs-code-extensions.vscode-clangd",
        "ms-vscode.cpptools",
        "ms-vscode.cmake-tools",
        "ms-python.python",
        "charliermarsh.ruff",
        "redhat.vscode-yaml",
        "ms-iot.vscode-ros",
        "anthropic.claude-code",
    ),
    settings={
        "clangd.arguments": ["--background-index", "--clang-tidy"],
        # clangd owns C++ IntelliSense; cpptools is kept for its debug adapter.
        "C_Cpp.intelliSenseEngine": "disabled",
        "python.defaultInterpreterPath": "/usr/bin/python3",
        "cmake.configureOnOpen": False,
        "files.watcherExclude": {"**/build/**": True, "**/install/**": True, "**/log/**": True},
    },
    container_env={
        # CMake >= 3.17 honors this as an env var, so clangd gets a
        # compile_commands.json without touching the repo's build_args.
        "CMAKE_EXPORT_COMPILE_COMMANDS": "ON",
    },
)

PROFILES: dict[str, Profile] = {ROS2.name: ROS2}


def profile(name: str) -> Profile:
    """Look up a profile, or fail with the list of the ones that exist."""
    found = PROFILES.get(name)
    if found is None:
        known = ", ".join(sorted(PROFILES))
        raise ArdtError(
            f"unknown dev profile `{name}`",
            hint=f"set `dev.profile:` to one of: {known}",
        )
    return found
