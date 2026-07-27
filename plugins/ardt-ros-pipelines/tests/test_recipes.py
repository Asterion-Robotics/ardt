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

"""Recipe rendering: the pipeline-owned Dockerfile, engine-free."""

from __future__ import annotations

from pathlib import Path

import pytest

from ardt_core import dist
from ardt_core.errors import ArdtError
from ardt_ros_pipelines import recipes

REQUIREMENTS = (
    "ardt-core @ git+https://example.com/ardt.git#subdirectory=packages/ardt-core",
    "ardt-ros-tasks @ git+https://example.com/ardt.git#subdirectory=plugins/ardt-ros-tasks",
)


def render(tmp_path: Path, **overrides: object) -> str:
    kwargs: dict = {
        "builder": "ros:jazzy-ros-base",
        "base_image": "base:1",
        "project_root": tmp_path,
        "base_dockerfile": "base.Dockerfile",
        "cmd": None,
        "ardt_requirements": REQUIREMENTS,
        "local_ardt": False,
    }
    kwargs.update(overrides)
    return recipes.render_ros2(**kwargs)


def test_no_placeholders_survive(tmp_path: Path) -> None:
    rendered = render(tmp_path)
    assert "@" not in rendered.replace("ardt-core @", "").replace("ardt-ros-tasks @", "")


def test_bases_and_stages(tmp_path: Path) -> None:
    rendered = render(tmp_path, builder="bld:2", base_image="base:1")
    assert "ARG BUILDER_IMAGE=bld:2" in rendered
    assert "ARG BASE_IMAGE=base:1" in rendered
    assert f"AS {recipes.BUILD_TARGET}" in rendered
    assert f"AS {recipes.RUNTIME_TARGET}" in rendered


def test_tasks_run_as_stages(tmp_path: Path) -> None:
    rendered = render(tmp_path)
    deps = rendered.index("ardt deps")
    build = rendered.index("ardt build --no-symlink-install")
    test = rendered.index("ardt test")
    results = rendered.index(recipes.RESULTS_DIR)
    assert deps < build < test < results


def test_git_install_by_default(tmp_path: Path) -> None:
    rendered = render(tmp_path)
    for requirement in REQUIREMENTS:
        assert f'"{requirement}"' in rendered
    assert recipes.LOCAL_ARDT_DIR not in rendered


def test_pinned_requirements_render_verbatim(tmp_path: Path) -> None:
    pinned = (
        "ardt-core @ git+https://example.com/ardt.git@v1.2.0#subdirectory=packages/ardt-core",
    )
    assert "@v1.2.0#subdirectory" in render(tmp_path, ardt_requirements=pinned)


def test_local_install_copies_checkout(tmp_path: Path) -> None:
    rendered = render(tmp_path, local_ardt=True)
    assert f"COPY {recipes.LOCAL_ARDT_DIR} /opt/ardt-src" in rendered
    for module in recipes.ARDT_MODULES:
        assert f"/opt/ardt-src/{dist.subdirectory(module)}" in rendered
    assert "git+" not in rendered


def test_cmd_rendered_as_json(tmp_path: Path) -> None:
    rendered = render(tmp_path, cmd=["bash", "-lc", "run me"])
    assert 'CMD ["bash", "-lc", "run me"]' in rendered


def test_no_cmd_no_cmd_line(tmp_path: Path) -> None:
    assert "\nCMD " not in render(tmp_path)


class TestBaseExtension:
    def test_absent_means_runtime_from_base(self, tmp_path: Path) -> None:
        rendered = render(tmp_path)
        assert f"FROM ${{BASE_IMAGE}} AS {recipes.RUNTIME_TARGET}" in rendered
        assert recipes.BASE_EXT_STAGE not in rendered

    def test_spliced_as_a_stage(self, tmp_path: Path) -> None:
        (tmp_path / "base.Dockerfile").write_text(
            "# comment\nARG BASE_IMAGE=whatever\nFROM ${BASE_IMAGE}\nRUN echo kernel-module\n"
        )
        rendered = render(tmp_path)
        assert f"FROM ${{BASE_IMAGE}} AS {recipes.BASE_EXT_STAGE}" in rendered
        assert "RUN echo kernel-module" in rendered
        assert f"FROM {recipes.BASE_EXT_STAGE} AS {recipes.RUNTIME_TARGET}" in rendered
        # the extension sits between the build stage and the runtime stage
        assert rendered.index("RUN echo kernel-module") < rendered.index(
            f"AS {recipes.RUNTIME_TARGET}"
        )

    def test_unbraced_from_accepted(self, tmp_path: Path) -> None:
        (tmp_path / "base.Dockerfile").write_text("FROM $BASE_IMAGE\nRUN echo hi\n")
        assert "RUN echo hi" in render(tmp_path)

    def test_wrong_from_is_a_clean_error(self, tmp_path: Path) -> None:
        (tmp_path / "base.Dockerfile").write_text("FROM ubuntu:24.04\nRUN echo hi\n")
        with pytest.raises(ArdtError, match="must start with"):
            render(tmp_path)

    def test_multiple_stages_rejected(self, tmp_path: Path) -> None:
        (tmp_path / "base.Dockerfile").write_text("FROM ${BASE_IMAGE}\nRUN echo hi\nFROM alpine\n")
        with pytest.raises(ArdtError, match="single stage"):
            render(tmp_path)

    def test_empty_file_rejected(self, tmp_path: Path) -> None:
        (tmp_path / "base.Dockerfile").write_text("# only a comment\n")
        with pytest.raises(ArdtError, match="no FROM"):
            render(tmp_path)


class TestInstallBaseAndStrip:
    def test_default_install_base(self, tmp_path: Path) -> None:
        rendered = render(tmp_path)
        assert "--install-base /opt/ros/aos" in rendered
        assert "COPY --from=build /opt/ros/aos /opt/ros/aos" in rendered

    def test_custom_install_base(self, tmp_path: Path) -> None:
        rendered = render(tmp_path, install_base="/opt/thing")
        assert "--install-base /opt/thing" in rendered
        assert "COPY --from=build /opt/thing /opt/thing" in rendered
        assert "/opt/ros/aos" not in rendered

    def test_no_strip_by_default(self, tmp_path: Path) -> None:
        assert "IP protection" not in render(tmp_path)

    def test_strip_removes_dev_files_before_runtime_copy(self, tmp_path: Path) -> None:
        rendered = render(tmp_path, strip_dev_files=True)
        assert "-name include" in rendered
        assert "*.a" in rendered
        # the strip runs in the build stage, before the runtime stage begins
        assert rendered.index("IP protection") < rendered.index("AS runtime")


class TestGitAuth:
    def test_off_by_default(self, tmp_path: Path) -> None:
        rendered = render(tmp_path)
        assert "--mount" not in rendered
        assert "credential" not in rendered

    def test_syntax_directive_is_the_first_line(self, tmp_path: Path) -> None:
        """BuildKit mounts in the escape-hatch `docker build` need the directive."""
        assert render(tmp_path).startswith("# syntax=docker/dockerfile:1\n")

    def test_mounts_and_branching(self, tmp_path: Path) -> None:
        rendered = render(tmp_path, git_host="code.example.com", git_ssh_port=5022)
        assert "--mount=type=ssh" in rendered
        assert f"--mount=type=secret,id={recipes.GIT_TOKEN_SECRET},required=false" in rendered
        assert "ssh-keyscan -p 5022 code.example.com" in rendered
        assert (
            'url."ssh://git@code.example.com:5022/".insteadOf "https://code.example.com/"'
            in rendered
        )
        assert "username=gitlab-ci-token" in rendered
        # auth is configured in the same RUN, before the vcs import runs
        assert rendered.index("elif [ -f /run/secrets/") < rendered.index("ardt deps")

    def test_token_read_at_use_time_never_baked(self, tmp_path: Path) -> None:
        rendered = render(tmp_path, git_host="code.example.com")
        assert f"$(cat /run/secrets/{recipes.GIT_TOKEN_SECRET})" in rendered

    def test_token_user_is_configurable(self, tmp_path: Path) -> None:
        rendered = render(tmp_path, git_host="ghe.example.com", git_token_user="x-access-token")
        assert "username=x-access-token" in rendered

    def test_no_credentials_message_names_the_escape_hatch(self, tmp_path: Path) -> None:
        rendered = render(tmp_path, git_host="code.example.com")
        assert "no git credentials for code.example.com" in rendered
        assert f"docker build --ssh default -f {recipes.RENDERED_NAME} ." in rendered


def test_dockerignore_render_lists_excludes() -> None:
    text = recipes.render_dockerignore(("build", "install", ".git"))
    assert "build\ninstall\n.git" in text
    assert ".ardt-src" not in text
