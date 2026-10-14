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

"""The bake plan of a ros-ci run: which targets, with which outputs, cache and
credentials, for the gate, the publish, the split publish and the load."""

from __future__ import annotations

from pathlib import Path

import pytest

from ardt_core.ci import CIInfo, Platform
from ardt_core.context import Context
from ardt_pipelines import std
from ardt_ros_pipelines import recipes, ros_ci

REGISTRY = "registry.example.com"


def _context(repo: Path, *, ci: bool = True, publish: bool = False, load: bool = False) -> Context:
    ctx = Context.build(cwd=repo)
    ctx.ci = CIInfo(
        platform=Platform.GITLAB if ci else Platform.LOCAL,
        is_ci=ci,
        registry=REGISTRY,
        project_path="example-group/my_robot" if ci else None,
    )
    ctx.publish = publish
    ctx.load = load
    return ctx


def _by_name(targets: list[object]) -> dict[str, object]:
    return {t.name: t for t in targets}  # type: ignore[attr-defined]


class TestGate:
    def test_reports_target_exports_the_results_and_reads_the_build_cache(self, repo: Path) -> None:
        ctx = _context(repo)
        cfg = ros_ci.RosCiConfig()
        targets = _by_name(
            ros_ci.plan(ctx, cfg, platforms=["linux/amd64"], credentials=std.Credentials())
        )
        reports = targets[recipes.REPORTS_TARGET]
        assert reports.target == recipes.REPORTS_TARGET
        assert reports.dockerfile == f"{ros_ci.JUNIT_EXPORT_DIR}/{recipes.RENDERED_NAME}"
        assert reports.output == [f"type=local,dest={ros_ci.JUNIT_EXPORT_DIR}"]
        assert recipes.TEST_RUN_ARG in reports.args, "a fresh value per run reruns the tests"
        cache = f"{REGISTRY}/example-group/my_robot/cache:{recipes.BUILD_TARGET}"
        assert reports.cache_from == [f"type=registry,ref={cache}"]
        assert reports.cache_to == [f"type=registry,ref={cache},mode=max"], "CI writes the cache"

    def test_a_laptop_reads_the_cache_and_never_writes_it(self, repo: Path) -> None:
        from ardt_core.testing import git

        git("remote", "add", "origin", f"https://{REGISTRY}/example-group/my_robot.git", cwd=repo)
        ctx = _context(repo, ci=False)
        targets = _by_name(
            ros_ci.plan(
                ctx, ros_ci.RosCiConfig(), platforms=["linux/amd64"], credentials=std.Credentials()
            )
        )
        reports = targets[recipes.REPORTS_TARGET]
        assert reports.cache_from, "the fleet's cache is read"
        assert reports.cache_to == []

    def test_runtime_is_built_but_not_pushed_without_publish(self, repo: Path) -> None:
        targets = _by_name(
            ros_ci.plan(
                _context(repo),
                ros_ci.RosCiConfig(),
                platforms=["linux/amd64"],
                credentials=std.Credentials(),
            )
        )
        runtime = targets[recipes.RUNTIME_TARGET]
        assert runtime.output == ["type=cacheonly"]
        assert runtime.tags == []
        assert runtime.platforms == ["linux/amd64"]

    def test_credentials_reach_both_targets(self, repo: Path) -> None:
        credentials = std.Credentials(
            secret=["id=git_token,env=ARDT_GIT_TOKEN"], ssh=["default=/s"]
        )
        targets = ros_ci.plan(
            _context(repo), ros_ci.RosCiConfig(), platforms=["linux/amd64"], credentials=credentials
        )
        assert all(t.secret == credentials.secret and t.ssh == credentials.ssh for t in targets)


class TestPublish:
    def test_every_platform_in_one_run_pushes_the_tag(self, repo: Path) -> None:
        ctx = _context(repo, publish=True)
        cfg = ros_ci.RosCiConfig(platforms=["linux/amd64", "linux/arm64"])
        runtime = _by_name(
            ros_ci.plan(ctx, cfg, platforms=list(cfg.platforms), credentials=std.Credentials())
        )[recipes.RUNTIME_TARGET]
        assert runtime.tags == [f"{REGISTRY}/example-group/my_robot:{std.image_tag(ctx.version)}"]
        assert runtime.output == [
            "type=image,push=true,compression=gzip,oci-mediatypes=true,force-compression=true"
        ]

    def test_a_subset_pushes_by_digest_without_a_tag(self, repo: Path) -> None:
        """The one-job-per-platform layout: each job records a digest, `ardt pipe merge` tags."""
        ctx = _context(repo, publish=True)
        cfg = ros_ci.RosCiConfig(platforms=["linux/amd64", "linux/arm64"])
        runtime = _by_name(
            ros_ci.plan(ctx, cfg, platforms=["linux/arm64"], credentials=std.Credentials())
        )[recipes.RUNTIME_TARGET]
        assert runtime.tags == []
        [output] = runtime.output
        assert output.startswith("type=image,push=true,push-by-digest=true,name-canonical=true,")
        assert f"name={REGISTRY}/example-group/my_robot" in output

    def test_zstd_is_a_config_knob(self, repo: Path) -> None:
        ctx = _context(repo, publish=True)
        cfg = ros_ci.RosCiConfig(compression="zstd")
        runtime = _by_name(
            ros_ci.plan(ctx, cfg, platforms=["linux/amd64"], credentials=std.Credentials())
        )[recipes.RUNTIME_TARGET]
        assert "compression=zstd" in runtime.output[0]


class TestLoad:
    def test_load_adds_a_native_docker_output(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(ros_ci.platform, "machine", lambda: "x86_64")
        ctx = _context(repo, load=True)
        cfg = ros_ci.RosCiConfig(platforms=["linux/amd64", "linux/arm64"])
        targets = _by_name(
            ros_ci.plan(ctx, cfg, platforms=list(cfg.platforms), credentials=std.Credentials())
        )
        load = targets[f"{recipes.RUNTIME_TARGET}-load"]
        assert load.platforms == ["linux/amd64"]
        assert load.output == ["type=docker"]
        assert load.tags == std.load_names(ctx)

    def test_load_without_a_native_platform_is_skipped_with_a_warning(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(ros_ci.platform, "machine", lambda: "x86_64")
        ctx = _context(repo, load=True)
        cfg = ros_ci.RosCiConfig(platforms=["linux/arm64", "linux/arm/v7"])
        targets = _by_name(
            ros_ci.plan(ctx, cfg, platforms=list(cfg.platforms), credentials=std.Credentials())
        )
        assert f"{recipes.RUNTIME_TARGET}-load" not in targets


class TestExportDir:
    def test_the_wipe_keeps_the_digest_records(self, repo: Path) -> None:
        """One platform per run writes a record; the next run's wipe must not eat it."""
        ctx = _context(repo)
        std.write_digest(ctx, repository="r/x", platform="linux/arm64", digest="sha256:a")
        stale = repo / ros_ci.JUNIT_EXPORT_DIR / "old.xml"
        stale.write_text("x")
        ros_ci._prepare_export(ctx, "FROM scratch\n")
        assert not stale.exists()
        assert (repo / std.DIGESTS_DIR / "linux-arm64.json").exists()
