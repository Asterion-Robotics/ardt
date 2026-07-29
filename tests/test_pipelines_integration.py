# Copyright 2026 Asterion Robotics
# SPDX-License-Identifier: Apache-2.0

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Author: Thibault Poignonec <t.poignonec@asterion-robotics.com>

"""The one engine-backed test: a trivial pipeline against real Dagger.

Marked ``integration``: excluded by default, run with ``pytest -m integration``.
Needs a Docker socket; the SDK auto-provisions the engine on first use, so the
first run downloads the engine image (slow once, cached after).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ardt_core.context import Context
from ardt_core.plugins import Registry
from ardt_pipelines import pipeline, std
from ardt_pipelines.engine import run_pipeline

pytestmark = pytest.mark.integration


ARDT_ROOT = Path(__file__).resolve().parents[1]


def test_ros_ci_end_to_end_on_a_fixture_package(repo: Path) -> None:
    """The shipping pipeline, for real: deps/build/test stages, the runtime
    stage's exec-deps rosdep pass, and the JUnit/Dockerfile exports — against a
    minimal ament_python package, with ardt installed from this working tree."""
    from ardt_core.testing import git
    from ardt_ros_pipelines.ros_ci import ros_ci

    (repo / "ardt.yaml").write_text("tasks:\n  ros:\n    distro: jazzy\n")
    (repo / "package.xml").write_text(
        '<?xml version="1.0"?>\n'
        '<package format="3">\n'
        "  <name>demo_pkg</name><version>0.0.1</version>\n"
        "  <description>ardt integration fixture</description>\n"
        '  <maintainer email="t@example.com">T</maintainer><license>Apache-2.0</license>\n'
        "  <buildtool_depend>ament_python</buildtool_depend>\n"
        "  <test_depend>python3-pytest</test_depend>\n"
        "  <export><build_type>ament_python</build_type></export>\n"
        "</package>\n"
    )
    (repo / "setup.py").write_text(
        "from setuptools import setup\n"
        # tests_require is what colcon keys on to run pytest (not unittest)
        "setup(name='demo_pkg', version='0.0.1', packages=[], tests_require=['pytest'],\n"
        "      data_files=[('share/ament_index/resource_index/packages',\n"
        "                   ['resource/demo_pkg']), ('share/demo_pkg', ['package.xml'])])\n"
    )
    (repo / "resource").mkdir()
    (repo / "resource" / "demo_pkg").write_text("")
    (repo / "test").mkdir()
    (repo / "test" / "test_ok.py").write_text("def test_ok() -> None:\n    assert True\n")
    git("add", "-A", cwd=repo)
    git("commit", "-qm", "fixture package", cwd=repo)

    ctx = Context.build(cwd=repo, registry=Registry(plugins=[], problems=[]))
    ctx.load = True  # exercise the daemon-load path end to end
    run_pipeline(ctx, ros_ci, ros_ci.bind({"ardt_source": str(ARDT_ROOT)}))

    assert ctx.emitted["tests_ok"] is True
    reports = repo / "pipeline-reports"
    assert (reports / "Dockerfile.rendered").is_file()
    assert list(reports.rglob("*.xml")), "no JUnit results were staged"

    loaded = ctx.emitted["loaded"]
    # the moving per-release-line tag; the fixture repo is never a release
    assert loaded == [f"proj:{std.dev_tag(ctx.version)}"]
    assert loaded[0].endswith("-dev")
    try:
        subprocess.run(["docker", "image", "inspect", *loaded], check=True, capture_output=True)
    finally:
        subprocess.run(["docker", "rmi", *loaded], check=False, capture_output=True)


def test_trivial_pipeline_against_real_engine(repo: Path) -> None:
    @pipeline(name="trivial", doc="echo in alpine")
    async def trivial(ctx: Context, dag, message: str = "hello") -> None:
        out = await dag.container().from_("alpine:3.20").with_exec(["echo", message]).stdout()
        ctx.emit(echoed=out.strip())

    ctx = Context.build(cwd=repo, registry=Registry(plugins=[], problems=[]))
    run_pipeline(ctx, trivial, trivial.bind({"message": "ardt-engine-ok"}))
    assert ctx.emitted["echoed"] == "ardt-engine-ok"
