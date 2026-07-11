"""Recipe rendering: the pipeline-owned Dockerfile, engine-free."""

from __future__ import annotations

from pathlib import Path

import pytest

from ardt_core.errors import ArdtError
from ardt_pipelines_ros import recipes


def render(tmp_path: Path, **overrides: object) -> str:
    kwargs: dict = {
        "builder": "ros:jazzy-ros-base",
        "base_image": "base:1",
        "project_root": tmp_path,
        "base_dockerfile": "base.Dockerfile",
        "cmd": None,
        "ardt_source": "git+https://example.com/ardt.git",
        "local_ardt": False,
    }
    kwargs.update(overrides)
    return recipes.render_ros2(**kwargs)


def test_no_placeholders_survive(tmp_path: Path) -> None:
    rendered = render(tmp_path)
    assert "@" not in rendered.replace("ardt-core @", "").replace("ardt-tasks-ros @", "")


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
    rendered = render(tmp_path, ardt_source="git+https://example.com/ardt.git")
    assert "git+https://example.com/ardt.git#subdirectory=packages/ardt-core" in rendered
    assert recipes.LOCAL_ARDT_DIR not in rendered


def test_local_install_copies_checkout(tmp_path: Path) -> None:
    rendered = render(tmp_path, ardt_source="/somewhere/ardt", local_ardt=True)
    assert f"COPY {recipes.LOCAL_ARDT_DIR} /opt/ardt-src" in rendered
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
