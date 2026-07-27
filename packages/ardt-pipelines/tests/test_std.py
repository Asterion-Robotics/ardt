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

"""std helpers that need no engine: image_ref must yield one pushable reference.

The parity rule under test: the reference is identical wherever it is computed
— CI's project path, the credentials file, or the git remote all resolve to the
same ``<registry>/<group>/<project>[/<name>]:<version>``, and there is no flat
fallback (GitLab's registry would reject it anyway).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ardt_core.ci import CIInfo, Platform
from ardt_core.context import Context
from ardt_core.errors import ArdtError
from ardt_core.testing import git
from ardt_pipelines import std

REGISTRY = "registry.example.com"


def _context(repo: Path, ci: CIInfo, *, dry_run: bool = False) -> Context:
    ctx = Context.build(cwd=repo, dry_run=dry_run)
    ctx.ci = ci
    return ctx


def _ci(project_path: str | None = None, registry: str | None = REGISTRY) -> CIInfo:
    return CIInfo(
        platform=Platform.GITLAB if project_path else Platform.LOCAL,
        is_ci=project_path is not None,
        registry=registry,
        project_path=project_path,
    )


class TestImageRef:
    def test_ci_ref_is_namespaced_by_the_project_path(self, repo: Path) -> None:
        """GitLab only accepts pushes under $CI_REGISTRY_IMAGE = registry/<group>/<project>."""
        ctx = _context(repo, _ci("example-group/my_robot"))
        assert std.image_ref(ctx) == f"{REGISTRY}/example-group/my_robot:{ctx.version}"

    def test_name_appends_a_sub_image(self, repo: Path) -> None:
        ctx = _context(repo, _ci("example-group/my_robot"))
        assert std.image_ref(ctx, "slim") == f"{REGISTRY}/example-group/my_robot/slim:{ctx.version}"

    def test_repository_path_is_lowercased(self, repo: Path) -> None:
        """Registries reject uppercase repository paths; GitLab lowercases its own."""
        ctx = _context(repo, _ci("Example-Group/My_Robot"))
        assert std.image_ref(ctx).startswith(f"{REGISTRY}/example-group/my_robot:")

    @pytest.mark.parametrize(
        "remote",
        [
            "https://code.example.com/example-group/my_robot.git",
            "ssh://git@code.example.com:5022/example-group/my_robot.git",
            "git@code.example.com:example-group/my_robot.git",
        ],
    )
    def test_local_ref_derives_from_the_git_remote(self, repo: Path, remote: str) -> None:
        """The same full name locally as on CI — the parity rule."""
        git("remote", "add", "origin", remote, cwd=repo)
        ctx = _context(repo, _ci())
        assert std.image_ref(ctx) == f"{REGISTRY}/example-group/my_robot:{ctx.version}"

    def test_ci_project_path_wins_over_the_remote(self, repo: Path) -> None:
        git("remote", "add", "origin", "https://code.example.com/other/place.git", cwd=repo)
        ctx = _context(repo, _ci("example-group/my_robot"))
        assert std.image_ref(ctx) == f"{REGISTRY}/example-group/my_robot:{ctx.version}"

    def test_unresolvable_path_is_a_clean_error(self, repo: Path) -> None:
        """No flat fallback: a ref outside the project namespace could never push."""
        ctx = _context(repo, _ci())
        with pytest.raises(ArdtError, match="project path") as excinfo:
            std.image_ref(ctx)
        assert "credentials.yaml" in (excinfo.value.hint or "")

    def test_dry_run_renders_a_placeholder_instead(self, repo: Path) -> None:
        ctx = _context(repo, _ci(), dry_run=True)
        assert std.image_ref(ctx) == f"{REGISTRY}/<project-path>:{ctx.version}"

    def test_no_registry_is_a_clean_error(self, repo: Path) -> None:
        ctx = _context(repo, _ci(registry=None))
        with pytest.raises(ArdtError, match="no registry configured"):
            std.image_ref(ctx)


class TestPathFromRemote:
    def test_path_only_remote_yields_none(self, repo: Path) -> None:
        git("remote", "add", "origin", "/srv/git/mirror", cwd=repo)
        ctx = _context(repo, _ci())
        assert std.project_path(ctx) is None


class TestGitCredentials:
    """Domain-agnostic credential plumbing any private-clone recipe reuses."""

    def test_no_credentials_is_a_clean_error(self, repo: Path) -> None:
        ctx = _context(repo, _ci())
        with pytest.raises(ArdtError, match="no git credentials"):
            # The (stub) dagger client is never touched on the failure path.
            std.git_credentials(object(), ctx, host="code.example.com")

    def test_job_token_becomes_the_named_secret(self, repo: Path) -> None:
        class FakeDag:
            def __init__(self) -> None:
                self.named: list[str] = []

            def set_secret(self, name: str, value: str) -> str:
                self.named.append(name)
                assert value == "tok"
                return "secret-handle"

        ctx = _context(
            repo,
            CIInfo(platform=Platform.GITLAB, is_ci=True, registry=REGISTRY, job_token="tok"),
        )
        dag = FakeDag()
        secrets, sock = std.git_credentials(dag, ctx, host="code.example.com")
        assert dag.named == [std.GIT_TOKEN_SECRET]
        assert secrets == ["secret-handle"]
        assert sock is None

    def test_stale_agent_path_is_ignored(self, repo: Path, tmp_path: Path) -> None:
        """SSH_AUTH_SOCK pointing at nothing must not count as a credential."""
        ctx = _context(
            repo,
            CIInfo(
                platform=Platform.LOCAL,
                is_ci=False,
                registry=REGISTRY,
                ssh_auth_sock=str(tmp_path / "gone.sock"),
            ),
        )
        with pytest.raises(ArdtError, match="no git credentials"):
            std.git_credentials(object(), ctx, host="code.example.com")
