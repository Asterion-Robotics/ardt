"""ros-ci: config parsing and its discovery through the real CLI.

These exercise the boundary this package cares about: its pipeline registers
via the standard entry point and its config section parses — without an engine.
The full containerized run is the workspace-level integration/demo territory.
"""

from __future__ import annotations

import json
from pathlib import Path

from ardt_core.config import ArdtConfig


def run(args: list[str], cwd: Path) -> tuple[int, str, str]:
    import contextlib
    import io

    from ardt_core.cli import main

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(["-C", str(cwd), *args])
    return code, out.getvalue(), err.getvalue()


class TestConfig:
    def test_defaults(self) -> None:
        from ardt_pipelines_ros.ros_ci import PipelinesSection

        cfg = ArdtConfig().section_as("pipelines", PipelinesSection).ros_ci
        assert cfg.builder == "ros:jazzy-ros-base"
        assert cfg.base_image == "ros:jazzy-ros-base"
        assert cfg.base_dockerfile == "base.Dockerfile"
        assert cfg.platforms == ["linux/amd64"]

    def test_from_yaml(self, repo: Path) -> None:
        from ardt_core import config as config_module
        from ardt_pipelines_ros.ros_ci import PipelinesSection

        (repo / "ardt.yaml").write_text(
            "pipelines:\n  ros_ci:\n    builder: custom:1\n    base_image: base:2\n"
            "    platforms: [linux/arm64]\n"
        )
        cfg, _ = config_module.load(repo)
        parsed = cfg.section_as("pipelines", PipelinesSection).ros_ci
        assert parsed.builder == "custom:1"
        assert parsed.base_image == "base:2"
        assert parsed.platforms == ["linux/arm64"]


class TestCliDiscovery:
    """ros-ci is reachable through `ardt pipe` purely via the entry point."""

    def test_pipe_list_shows_ros_ci(self, repo: Path) -> None:
        code, _, err = run(["pipe", "list"], repo)
        assert code == 0
        assert "ros-ci" in err

    def test_pipe_list_json(self, repo: Path) -> None:
        code, out, _ = run(["pipe", "list", "--json"], repo)
        assert code == 0
        names = {p["name"] for p in json.loads(out)["data"]["pipelines"]}
        assert "ros-ci" in names

    def test_dry_run_needs_no_engine(self, repo: Path) -> None:
        code, _, err = run(["pipe", "run", "ros-ci", "--dry-run"], repo)
        assert code == 0
        assert "[dry-run] pipe run ros-ci" in err

    def test_malformed_arg_is_clean(self, repo: Path) -> None:
        code, _, err = run(["pipe", "run", "ros-ci", "--arg", "novalue"], repo)
        assert code == 1
        assert "KEY=VALUE" in err
