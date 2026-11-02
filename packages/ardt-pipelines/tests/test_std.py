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

import re
from importlib import resources
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
        assert (
            std.image_ref(ctx) == f"{REGISTRY}/example-group/my_robot:{std.image_tag(ctx.version)}"
        )

    def test_name_appends_a_sub_image(self, repo: Path) -> None:
        ctx = _context(repo, _ci("example-group/my_robot"))
        assert (
            std.image_ref(ctx, "slim")
            == f"{REGISTRY}/example-group/my_robot/slim:{std.image_tag(ctx.version)}"
        )

    def test_repository_path_is_lowercased(self, repo: Path) -> None:
        """Registries reject uppercase repository paths; GitLab lowercases its own."""
        ctx = _context(repo, _ci("Example-Group/My_Robot"))
        assert std.image_ref(ctx).startswith(f"{REGISTRY}/example-group/my_robot:")

    def test_dev_version_yields_a_pushable_tag(self, repo: Path) -> None:
        """Off-tag versions carry a PEP 440 `+local` part; registries reject it in tags."""
        ctx = _context(repo, _ci("example-group/my_robot"))
        assert "+" in ctx.version  # the fixture repo has no tag: a local version
        tag = std.image_ref(ctx).rsplit(":", 1)[1]
        assert re.fullmatch(r"[a-zA-Z0-9_][a-zA-Z0-9._-]{0,127}", tag), tag

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
        assert (
            std.image_ref(ctx) == f"{REGISTRY}/example-group/my_robot:{std.image_tag(ctx.version)}"
        )

    def test_ci_project_path_wins_over_the_remote(self, repo: Path) -> None:
        git("remote", "add", "origin", "https://code.example.com/other/place.git", cwd=repo)
        ctx = _context(repo, _ci("example-group/my_robot"))
        assert (
            std.image_ref(ctx) == f"{REGISTRY}/example-group/my_robot:{std.image_tag(ctx.version)}"
        )

    def test_unresolvable_path_is_a_clean_error(self, repo: Path) -> None:
        """No flat fallback: a ref outside the project namespace could never push."""
        ctx = _context(repo, _ci())
        with pytest.raises(ArdtError, match="project path") as excinfo:
            std.image_ref(ctx)
        assert "credentials.yaml" in (excinfo.value.hint or "")

    def test_dry_run_renders_a_placeholder_instead(self, repo: Path) -> None:
        ctx = _context(repo, _ci(), dry_run=True)
        assert std.image_ref(ctx) == f"{REGISTRY}/<project-path>:{std.image_tag(ctx.version)}"

    def test_no_registry_is_a_clean_error(self, repo: Path) -> None:
        ctx = _context(repo, _ci(registry=None))
        with pytest.raises(ArdtError, match="no registry configured"):
            std.image_ref(ctx)


class TestDevTag:
    def test_dev_version_maps_to_its_release_line(self) -> None:
        assert std.dev_tag("0.1.1.dev3+g0a1b2c3") == "0.1.1-dev"

    def test_dirty_tag_build_is_still_dev(self) -> None:
        assert std.dev_tag("0.1.0+dirty") == "0.1.0-dev"

    def test_clean_release_maps_to_its_own_line(self) -> None:
        assert std.dev_tag("1.2.3") == "1.2.3-dev"


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
            std.git_credentials(ctx, host="code.example.com")

    def test_job_token_becomes_the_named_secret_from_the_environment(self, repo: Path) -> None:
        """The token reaches the build as a BuildKit secret read from the bake
        command's environment: never a file, never an argument."""
        ctx = _context(
            repo,
            CIInfo(platform=Platform.GITLAB, is_ci=True, registry=REGISTRY, job_token="tok"),
        )
        credentials = std.git_credentials(ctx, host="code.example.com")
        assert credentials.secret == [f"id={std.GIT_TOKEN_SECRET},env={std.GIT_TOKEN_ENV}"]
        assert credentials.env == {std.GIT_TOKEN_ENV: "tok"}
        assert credentials.ssh == []

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
            std.git_credentials(ctx, host="code.example.com")


class TestAptProxy:
    """The apt cache reaches a build as a secret read from the bake command's
    environment, from ardt.yaml or the ARDT_APT_PROXY override."""

    @staticmethod
    def _configure(repo: Path, body: str) -> None:
        (repo / "ardt.yaml").write_text(f"project:\n  name: demo\npipelines:\n{body}")

    def test_nothing_configured_means_no_secret(self, repo: Path) -> None:
        assert std.apt_proxy(_context(repo, _ci())) == std.Credentials()

    def test_configured_cache_becomes_the_named_secret(self, repo: Path) -> None:
        self._configure(repo, "  apt_proxy:\n    url: http://cache.example:3142/\n")
        credentials = std.apt_proxy(_context(repo, _ci()))
        assert credentials.secret == [f"id={std.APT_PROXY_SECRET},env={std.APT_PROXY_ENV}"]
        assert credentials.env == {
            std.APT_PROXY_ENV: "url=http://cache.example:3142\nprobe_timeout=2\n"
        }
        assert credentials.ssh == []

    def test_probe_timeout_is_configurable(self, repo: Path) -> None:
        self._configure(
            repo, "  apt_proxy:\n    url: http://cache.example:3142\n    probe_timeout: 0.5\n"
        )
        env = std.apt_proxy(_context(repo, _ci())).env[std.APT_PROXY_ENV]
        assert "probe_timeout=0.5\n" in env

    def test_the_environment_names_the_cache(self, repo: Path) -> None:
        """The normal case: nothing in ardt.yaml, the CI sets ARDT_APT_PROXY."""
        ci = CIInfo(platform=Platform.GITLAB, is_ci=True, apt_proxy="http://ci.example:3142")
        env = std.apt_proxy(_context(repo, ci)).env[std.APT_PROXY_ENV]
        assert env == "url=http://ci.example:3142\nprobe_timeout=2\n"

    def test_the_repository_overrides_the_environment(self, repo: Path) -> None:
        self._configure(repo, "  apt_proxy:\n    url: http://test.example:3142\n")
        ci = CIInfo(platform=Platform.GITLAB, is_ci=True, apt_proxy="http://ci.example:3142")
        env = std.apt_proxy(_context(repo, ci)).env[std.APT_PROXY_ENV]
        assert env.startswith("url=http://test.example:3142\n")

    def test_the_repository_can_switch_the_cache_off(self, repo: Path) -> None:
        self._configure(repo, '  apt_proxy:\n    url: ""\n')
        ci = CIInfo(platform=Platform.GITLAB, is_ci=True, apt_proxy="http://ci.example:3142")
        assert std.apt_proxy(_context(repo, ci)) == std.Credentials()

    def test_probe_timeout_applies_to_the_environment_cache(self, repo: Path) -> None:
        self._configure(repo, "  apt_proxy:\n    probe_timeout: 0.5\n")
        ci = CIInfo(platform=Platform.GITLAB, is_ci=True, apt_proxy="http://ci.example:3142")
        env = std.apt_proxy(_context(repo, ci)).env[std.APT_PROXY_ENV]
        assert env == "url=http://ci.example:3142\nprobe_timeout=0.5\n"

    def test_https_cache_is_a_clean_error(self, repo: Path) -> None:
        self._configure(repo, "  apt_proxy:\n    url: https://cache.example\n")
        with pytest.raises(ArdtError, match="not an http:// URL"):
            std.apt_proxy(_context(repo, _ci()))

    def test_the_stage_embeds_the_packaged_wrapper(self) -> None:
        script = (resources.files("ardt_pipelines") / "ardt-apt.sh").read_text(encoding="utf-8")
        stage = std.apt_stage()
        assert stage.startswith(f"FROM scratch AS {std.APT_STAGE}\n")
        assert f"/ardt-apt\n{script.rstrip()}\nARDT_APT\n" in stage

    def test_a_step_reads_its_body_from_a_heredoc_through_both_mounts(self) -> None:
        step = std.apt_step("apt-get update \\\n && apt-get install -y git\n")
        assert step.startswith("RUN --mount=type=secret,id=apt_proxy,required=false")
        assert f"from={std.APT_STAGE},source=/ardt-apt,target={std.APT_WRAPPER}" in step
        assert step.endswith(
            f"{std.APT_WRAPPER} <<'STEP'\napt-get update \\\n && apt-get install -y git\nSTEP"
        )

    def test_combine_keeps_every_entry_in_order(self) -> None:
        git = std.Credentials(secret=["id=a,env=A"], ssh=["default=/s"], env={"A": "1"})
        apt = std.Credentials(secret=["id=b,env=B"], env={"B": "2"})
        combined = std.combine(git, apt)
        assert combined.secret == ["id=a,env=A", "id=b,env=B"]
        assert combined.ssh == ["default=/s"]
        assert combined.env == {"A": "1", "B": "2"}


class TestCacheRef:
    """One cache sub-image per project, one tag per target, shared by every
    branch and runner."""

    def test_ci_project_gets_a_cache_ref_per_target(self, repo: Path) -> None:
        ctx = _context(repo, _ci("example-group/my_robot"))
        assert std.cache_ref(ctx, None, "build") == f"{REGISTRY}/example-group/my_robot/cache:build"
        assert (
            std.cache_ref(ctx, "slim", "runtime")
            == f"{REGISTRY}/example-group/my_robot/cache:slim-runtime"
        )

    def test_no_registry_means_no_cache(self, repo: Path) -> None:
        assert std.cache_ref(_context(repo, _ci(registry=None)), None, "build") is None

    def test_unresolvable_path_means_no_cache(self, repo: Path) -> None:
        assert std.cache_ref(_context(repo, _ci()), None, "build") is None


class TestDigestRecords:
    """What a per-platform publish leaves for `ardt pipe merge`."""

    def test_round_trip(self, repo: Path) -> None:
        ctx = _context(repo, _ci("example-group/my_robot"))
        std.write_digest(ctx, repository="r/x", platform="linux/arm64", digest="sha256:a")
        std.write_digest(ctx, repository="r/x", platform="linux/amd64", digest="sha256:b")
        records = std.read_digests(ctx)
        assert [r["platform"] for r in records] == ["linux/amd64", "linux/arm64"]
        assert {r["digest"] for r in records} == {"sha256:a", "sha256:b"}

    def test_no_records_is_a_clean_error(self, repo: Path) -> None:
        with pytest.raises(ArdtError, match="no digest records"):
            std.read_digests(_context(repo, _ci()))
