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

import re
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
        "project": "demo",
        "project_root": tmp_path,
        "base_dockerfile": "base.Dockerfile",
        "cmd": None,
        "ardt_requirements": REQUIREMENTS,
        "local_ardt": False,
    }
    kwargs.update(overrides)
    return recipes.render_ros2(**kwargs)


def test_the_workspace_is_canonical_and_the_workdir_is_the_repo(tmp_path: Path) -> None:
    """Repo at /ws/src/<project>, tasks anchored there, results staged from /ws/build."""
    rendered = render(tmp_path, project="my_repo")
    assert "COPY . /ws/src/my_repo" in rendered
    assert "WORKDIR /ws/src/my_repo" in rendered
    assert "cd /ws/build" in rendered


def test_staging_matches_both_junit_layouts(tmp_path: Path) -> None:
    """ament_cmake writes test_results/<pkg>/*.xml, colcon's pytest step writes
    <pkg>/pytest.xml with no test_results component — the staging find must
    match both, or ament_python results silently vanish from the reports."""
    rendered = render(tmp_path)
    assert "-path '*test_results*' -name '*.xml' -o -name 'pytest.xml'" in rendered


def test_no_placeholders_survive(tmp_path: Path) -> None:
    """Legit `@`s exist (pip's `pkg @ url`, the entrypoint's `"$@"`) — only the
    render's own @UPPER_CASE@ tokens must be gone."""
    assert not re.findall(r"@[A-Z_]+@", render(tmp_path))


def test_bases_and_stages(tmp_path: Path) -> None:
    rendered = render(tmp_path, builder="bld:2", base_image="base:1")
    assert "ARG BUILDER_IMAGE=bld:2" in rendered
    assert "ARG BASE_IMAGE=base:1" in rendered
    assert f"AS {recipes.BUILD_TARGET}" in rendered
    assert f"AS {recipes.TEST_TARGET}" in rendered
    assert f"AS {recipes.RUNTIME_TARGET}" in rendered


class TestTestStageSplit:
    """The runtime image must not depend on the test stage.

    Regression: `runtime` copied from a stage that ended with `ardt test`, so
    every foreign-arch runtime build re-ran the whole suite under QEMU — the
    single most expensive span of the pipeline, paid twice.
    """

    def test_test_forks_from_build(self, tmp_path: Path) -> None:
        rendered = render(tmp_path)
        assert f"FROM {recipes.BUILD_TARGET} AS {recipes.TEST_TARGET}" in rendered

    def test_runtime_copies_from_build_not_test(self, tmp_path: Path) -> None:
        rendered = render(tmp_path)
        assert "COPY --from=build /opt/ros/app" in rendered
        assert f"--from={recipes.TEST_TARGET}" not in rendered
        assert f"FROM {recipes.TEST_TARGET}" not in rendered.replace(
            f"FROM {recipes.BUILD_TARGET} AS {recipes.TEST_TARGET}", ""
        )

    def test_tests_and_staging_live_in_the_test_stage(self, tmp_path: Path) -> None:
        rendered = render(tmp_path)
        test_stage_start = rendered.index(f"AS {recipes.TEST_TARGET}")
        assert rendered.index("ardt test") > test_stage_start
        assert rendered.index(recipes.RESULTS_DIR) > test_stage_start

    def test_escape_hatch_names_the_test_target(self, tmp_path: Path) -> None:
        """The header must tell a human that a plain build skips the tests."""
        rendered = render(tmp_path)
        assert f"--target {recipes.TEST_TARGET}" in rendered


def test_tasks_run_as_stages(tmp_path: Path) -> None:
    rendered = render(tmp_path)
    deps = rendered.index("ardt deps")
    build = rendered.index("ardt build --no-symlink-install")
    test = rendered.index("ardt test")
    results = rendered.index(recipes.RESULTS_DIR)
    assert deps < build < test < results


class TestManifestsFirst:
    """The deps layer must survive a source-only edit.

    Regression: `COPY .` preceded the deps layer, so any code change re-ran
    apt + rosdep + vcs import — under QEMU on the arm64 leg, the single most
    expensive re-run in the pipeline.
    """

    def test_manifest_copy_precedes_deps_full_copy_follows(self, tmp_path: Path) -> None:
        rendered = render(tmp_path, project="demo")
        manifests = rendered.index("COPY --parents")
        # "&& ardt deps" is the invocation; a bare "ardt deps" would match the
        # comment explaining the manifests-first ordering, above the COPY.
        deps = rendered.index("&& ardt deps")
        full = rendered.index("COPY . /ws/src/demo")
        build = rendered.index("ardt build --no-symlink-install")
        assert manifests < deps < full < build

    def test_manifest_patterns(self, tmp_path: Path) -> None:
        """package.xml (colcon discovery), COLCON_IGNORE (pruning), *.repos
        (vcs import), ardt.yaml (the config `ardt deps` runs against)."""
        rendered = render(tmp_path)
        line = next(ln for ln in rendered.splitlines() if ln.startswith("COPY --parents"))
        for pattern in ("./**/package.xml", "./**/COLCON_IGNORE", "./*.repos", "./ardt.yaml"):
            assert pattern in line
        assert line.endswith("/ws/src/demo/")

    def test_staleness_caveat_is_documented(self, tmp_path: Path) -> None:
        """vcs clones branch HEADs; a cached deps layer will not see drift.
        The rendered file must carry the warning, since it is the artifact a
        human debugs from."""
        assert "vcs import` clones branch HEADs" in render(tmp_path)


class TestRuntimeExecDeps:
    """The shipped image installs its own exec dependencies.

    Regression 1: the runtime stage was `base + COPY install/` alone, so every
    rosdep-installed exec dependency existed only in the builder and the image
    failed at `ros2 run` time unless the base happened to carry it.
    Regression 2: the pass then scanned the install space directly — whose
    root carries colcon's COLCON_IGNORE marker, which rosdep's crawler honors —
    so it found zero packages and silently installed nothing. The pass must
    scan the manifests restaged by the build stage, never the install space.
    """

    def _runtime_stage(self, rendered: str) -> str:
        return rendered.split("AS runtime", 1)[1]

    def test_runtime_stage_resolves_exec_deps_from_staged_manifests(self, tmp_path: Path) -> None:
        stage = self._runtime_stage(render(tmp_path))
        assert "COPY --from=build /opt/runtime-manifests /tmp/runtime-manifests" in stage
        assert "rosdep install --from-paths /tmp/runtime-manifests --ignore-src" in stage
        assert "--dependency-types exec" in stage
        assert "rosdep install --from-paths /opt/ros/app" not in stage

    def test_build_stage_stages_manifests_and_fails_on_an_empty_set(self, tmp_path: Path) -> None:
        build_stage = render(tmp_path).split("AS runtime", 1)[0]
        assert "cp --parents -t /opt/runtime-manifests" in build_stage
        assert "find /opt/runtime-manifests -name package.xml | grep -q ." in build_stage

    def test_manifests_precede_the_install_space_copy(self, tmp_path: Path) -> None:
        """Same split as the build stage: a rebuilt binary must not invalidate
        the apt layer, and the emulated-arch leg feels it most."""
        stage = self._runtime_stage(render(tmp_path))
        assert stage.index("/tmp/runtime-manifests") < stage.index("COPY --from=build /opt/ros/app")

    def test_skip_keys_reach_the_runtime_rosdep_pass(self, tmp_path: Path) -> None:
        stage = self._runtime_stage(
            render(tmp_path, rosdep_skip_keys=("rti-connext-dds", "gazebo"))
        )
        assert '--skip-keys "rti-connext-dds gazebo"' in stage

    def test_no_skip_flag_without_keys(self, tmp_path: Path) -> None:
        assert "--skip-keys" not in render(tmp_path)

    def test_custom_install_base_manifests_are_staged(self, tmp_path: Path) -> None:
        rendered = render(tmp_path, install_base="/opt/app")
        assert "cd /opt/app" in rendered.split("AS runtime", 1)[0]


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


def test_no_cmd_defaults_to_bash(tmp_path: Path) -> None:
    """The entrypoint resets any base-image CMD, so the render must supply one."""
    assert 'CMD ["bash"]' in render(tmp_path)


def test_entrypoint_sources_the_overlay(tmp_path: Path) -> None:
    """CMD/args run with the workspace overlay active, and interactive shells
    (docker exec … bash) get it from .bashrc — both keyed on install_base."""
    rendered = render(tmp_path, install_base="/opt/app")
    assert (
        'ENTRYPOINT ["/bin/bash", "-c", "source /opt/app/setup.bash && exec \\"$@\\"", "--"]'
        in rendered
    )
    assert 'echo "source /opt/ros/${ROS_DISTRO}/setup.bash" >> /root/.bashrc' in rendered
    assert 'echo "source /opt/app/setup.bash" >> /root/.bashrc' in rendered


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
        assert "--install-base /opt/ros/app" in rendered
        assert "COPY --from=build /opt/ros/app /opt/ros/app" in rendered

    def test_custom_install_base(self, tmp_path: Path) -> None:
        rendered = render(tmp_path, install_base="/opt/thing")
        assert "--install-base /opt/thing" in rendered
        assert "COPY --from=build /opt/thing /opt/thing" in rendered
        assert "/opt/ros/app" not in rendered

    def test_no_strip_by_default(self, tmp_path: Path) -> None:
        assert "IP protection" not in render(tmp_path)

    def test_strip_removes_dev_files_before_runtime_copy(self, tmp_path: Path) -> None:
        rendered = render(tmp_path, strip_dev_files=True)
        assert "-name include" in rendered
        assert "*.a" in rendered
        assert rendered.index("IP protection") < rendered.index("AS runtime")

    def test_strip_is_its_own_stage_and_runtime_copies_from_it(self, tmp_path: Path) -> None:
        """Strip forks from build, and the test stage keeps the unstripped
        install — the pre-split behavior, where strip ran after the tests."""
        rendered = render(tmp_path, strip_dev_files=True)
        assert f"FROM {recipes.BUILD_TARGET} AS {recipes.STRIP_STAGE}" in rendered
        assert f"COPY --from={recipes.STRIP_STAGE} /opt/ros/app" in rendered
        # the test stage still forks from the unstripped build stage
        assert f"FROM {recipes.BUILD_TARGET} AS {recipes.TEST_TARGET}" in rendered

    def test_no_strip_stage_without_the_knob(self, tmp_path: Path) -> None:
        assert f"AS {recipes.STRIP_STAGE}" not in render(tmp_path)


class TestCacheMounts:
    """Per-arch BuildKit cache mounts; they pay off on a persistent engine."""

    def test_targetarch_declared_in_both_mounting_stages(self, tmp_path: Path) -> None:
        """ARG scope is per stage; an undeclared TARGETARCH expands empty and
        every arch would silently share (and thrash) one cache."""
        rendered = render(tmp_path)
        build_stage = rendered.split(f"AS {recipes.TEST_TARGET}")[0]
        runtime_stage = rendered.split(f"AS {recipes.RUNTIME_TARGET}")[1]
        assert "ARG TARGETARCH" in build_stage
        assert "ARG TARGETARCH" in runtime_stage

    def test_apt_mounts_are_arch_keyed_and_locked(self, tmp_path: Path) -> None:
        rendered = render(tmp_path)
        assert "target=/var/cache/apt,sharing=locked,id=apt-cache-${TARGETARCH}" in rendered
        assert "target=/var/lib/apt/lists,sharing=locked,id=apt-lists-${TARGETARCH}" in rendered

    def test_ccache_mount_on_the_build_step(self, tmp_path: Path) -> None:
        rendered = render(tmp_path)
        line_start = rendered.index("target=/root/.ccache,id=ccache-${TARGETARCH}")
        assert line_start < rendered.index("ardt build --no-symlink-install")

    def test_apt_lists_never_removed(self, tmp_path: Path) -> None:
        """The lists live in a mount, not a layer; an rm would only empty the
        shared cache for the next run. (Matched with the trailing /*: the
        template's own comment quotes the command without it.)"""
        assert "rm -rf /var/lib/apt/lists/*" not in render(tmp_path)

    def test_docker_clean_removed_in_build_kept_in_runtime(self, tmp_path: Path) -> None:
        """Build stage keeps .debs in the cache mount; the SHIPPED image's apt
        behavior is not ours to change."""
        rendered = render(tmp_path)
        build_stage = rendered.split(f"AS {recipes.TEST_TARGET}")[0]
        runtime_stage = rendered.split(f"AS {recipes.RUNTIME_TARGET}")[1]
        assert "rm -f /etc/apt/apt.conf.d/docker-clean" in build_stage
        assert (
            "docker-clean"
            not in runtime_stage.replace(
                "# alone here (removing it would change the SHIPPED image's apt behavior), so", ""
            ).split("RUN", 1)[1]
        )

    def test_deps_layer_keeps_cache_mounts_alongside_git_mounts(self, tmp_path: Path) -> None:
        rendered = render(tmp_path, git_host="code.example.com")
        deps_run = rendered[rendered.index("# 1) deps") : rendered.index("&& ardt deps")]
        assert "--mount=type=ssh" in deps_run
        assert "id=apt-cache-${TARGETARCH}" in deps_run


class TestGitAuth:
    def test_off_by_default(self, tmp_path: Path) -> None:
        rendered = render(tmp_path)
        assert "--mount=type=ssh" not in rendered
        assert "--mount=type=secret" not in rendered
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
        # ("&& ardt deps" is the invocation, not the comment mentioning it)
        assert rendered.index("elif [ -f /run/secrets/") < rendered.index("&& ardt deps")

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
