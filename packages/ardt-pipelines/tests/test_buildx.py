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

"""The executor without a daemon: what it renders and what it runs.

The commands are recorded by a fake runner; docker itself is the integration
tests' business.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from ardt_core.ci import CIInfo, Platform
from ardt_core.context import Context
from ardt_core.errors import ArdtError
from ardt_core.runner import Result
from ardt_pipelines import buildx


@dataclass
class FakeRunner:
    """Records every command; answers each with a canned result."""

    answers: dict[str, Result] = field(default_factory=dict[str, Result])
    calls: list[list[str]] = field(default_factory=list[list[str]])
    stdins: list[str | None] = field(default_factory=list[str | None])
    dry_run: bool = False

    def require(self, tool: str, *, hint: str | None = None) -> str:
        return tool

    def run(self, command, *, cwd=None, check=True, extra_env=None, quiet=False, stdin=None):  # type: ignore[no-untyped-def]
        argv = list(command)
        self.calls.append(argv)
        self.stdins.append(stdin)
        key = " ".join(argv[:3])
        result = self.answers.get(key, Result(command=argv, returncode=0, tail=""))
        if check and not result.ok:
            raise AssertionError(f"unexpected failure for {key}")
        return result


def _context(repo: Path, runner: FakeRunner, **ci: object) -> Context:
    ctx = Context.build(cwd=repo)
    ctx.ci = CIInfo(platform=Platform.GITLAB, is_ci=True, **ci)  # type: ignore[arg-type]
    ctx.runner = runner  # type: ignore[assignment]
    return ctx


class TestRenderBake:
    def test_targets_and_a_default_group(self) -> None:
        targets = [
            buildx.Target(
                name="reports", dockerfile="D", target="reports", output=["type=local,dest=r"]
            ),
            buildx.Target(
                name="runtime",
                dockerfile="D",
                target="runtime",
                platforms=["linux/amd64", "linux/arm64"],
                tags=["reg/x:1"],
                cache_from=["type=registry,ref=reg/x/cache:build"],
                contexts={"ardt-src": "/src"},
            ),
        ]
        document = json.loads(buildx.render_bake(targets))
        assert document["group"]["default"]["targets"] == ["reports", "runtime"]
        assert document["target"]["reports"] == {
            "context": ".",
            "dockerfile": "D",
            "target": "reports",
            "output": ["type=local,dest=r"],
        }
        runtime = document["target"]["runtime"]
        assert runtime["platforms"] == ["linux/amd64", "linux/arm64"]
        assert runtime["cache-from"] == ["type=registry,ref=reg/x/cache:build"]
        assert runtime["contexts"] == {"ardt-src": "/src"}
        assert "secret" not in runtime, "empty settings are left out, the file reads as the docs"


class TestBuilder:
    def test_bake_creates_the_builder_once_then_bakes(self, repo: Path) -> None:
        runner = FakeRunner(
            answers={
                "docker buildx inspect": Result(command=["docker"], returncode=1, tail="no builder")
            }
        )
        ctx = _context(repo, runner)
        (repo / "bake.json").write_text(
            buildx.render_bake(
                [
                    buildx.Target(
                        name="reports",
                        dockerfile="D",
                        target="reports",
                        contexts={"ardt-src": "/src/ardt"},
                    )
                ]
            )
        )
        executor = buildx.Buildx(ctx)
        executor.with_env({"ARDT_GIT_TOKEN": "tok"})
        executor.bake(repo / "bake.json", ["reports"], cwd=repo)
        executor.bake(repo / "bake.json", ["runtime"], cwd=repo)
        kinds = [" ".join(c[:3]) for c in runner.calls]
        assert kinds == [
            "docker buildx inspect",
            "docker buildx create",
            "docker buildx bake",
            "docker buildx bake",
        ]
        create = runner.calls[1]
        assert create[create.index("--driver") + 1] == "docker-container"
        assert f"image={buildx.BUILDKIT_IMAGE}" in create, "the BuildKit version is pinned"
        assert "--buildkitd-config" in create, "the builder gets ardt's bounded GC policy"
        bake = runner.calls[2]
        assert bake[bake.index("--builder") + 1] == buildx.BUILDER
        assert bake[-1] == "reports"
        assert "--allow=fs.read=/src/ardt" in bake, "a named context outside the tree is granted"

    def test_login_sends_the_password_on_stdin_only(self, repo: Path) -> None:
        runner = FakeRunner()
        ctx = _context(
            repo, runner, registry="reg.example", registry_user="bot", registry_password="s3cret"
        )
        buildx.Buildx(ctx).login()
        [login] = runner.calls
        assert login[:3] == ["docker", "login", "reg.example"]
        assert "s3cret" not in login
        assert runner.stdins == ["s3cret"]

    def test_login_is_a_no_op_without_credentials(self, repo: Path) -> None:
        runner = FakeRunner()
        buildx.Buildx(_context(repo, runner)).login()
        assert runner.calls == []

    def test_merge_creates_the_tag_from_digests_and_reads_it_back(self, repo: Path) -> None:
        runner = FakeRunner(
            answers={
                "docker buildx imagetools": Result(
                    command=["docker"], returncode=0, tail='"sha256:list"\n'
                )
            }
        )
        executor = buildx.Buildx(_context(repo, runner))
        digest = executor.imagetools_create("reg/x:1", ["reg/x@sha256:a", "reg/x@sha256:b"])
        assert digest == "sha256:list"
        create, inspect = runner.calls
        assert create[3:] == ["create", "--tag", "reg/x:1", "reg/x@sha256:a", "reg/x@sha256:b"]
        assert inspect[3:5] == ["inspect", "reg/x:1"]

    def test_merge_of_nothing_is_a_clean_error(self, repo: Path) -> None:
        with pytest.raises(ArdtError, match="nothing to merge"):
            buildx.Buildx(_context(repo, FakeRunner())).imagetools_create("reg/x:1", [])


class TestMergeCommand:
    """`ardt pipe merge` through the real CLI, up to the point docker would be called."""

    def test_dry_run_names_the_tag_and_the_sources(self, repo: Path) -> None:
        from ardt_core.testing import run_cli

        ctx = _context(repo, FakeRunner(), registry="reg.example", project_path="g/p")
        from ardt_pipelines import std

        std.write_digest(
            ctx, repository="reg.example/g/p", platform="linux/amd64", digest="sha256:a"
        )
        std.write_digest(
            ctx, repository="reg.example/g/p", platform="linux/arm64", digest="sha256:b"
        )
        code, _, err = run_cli(["pipe", "merge", "--dry-run"], repo)
        assert code == 0, err
        assert "imagetools create reg.example/g/p:" in err
        assert "reg.example/g/p@sha256:a reg.example/g/p@sha256:b" in err

    def test_records_from_two_repositories_are_refused(self, repo: Path) -> None:
        from ardt_core.testing import run_cli

        ctx = _context(repo, FakeRunner(), registry="reg.example", project_path="g/p")
        from ardt_pipelines import std

        std.write_digest(
            ctx, repository="reg.example/g/p", platform="linux/amd64", digest="sha256:a"
        )
        std.write_digest(
            ctx, repository="reg.example/g/other", platform="linux/arm64", digest="sha256:b"
        )
        code, _, err = run_cli(["pipe", "merge", "--dry-run"], repo)
        assert code == 1
        assert "2 repositories" in err
