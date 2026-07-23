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
        ctx = _context(repo, _ci("aos-edge-poc/aos_edge"))
        assert std.image_ref(ctx) == f"{REGISTRY}/aos-edge-poc/aos_edge:{ctx.version}"

    def test_name_appends_a_sub_image(self, repo: Path) -> None:
        ctx = _context(repo, _ci("aos-edge-poc/aos_edge"))
        assert std.image_ref(ctx, "slim") == f"{REGISTRY}/aos-edge-poc/aos_edge/slim:{ctx.version}"

    def test_repository_path_is_lowercased(self, repo: Path) -> None:
        """Registries reject uppercase repository paths; GitLab lowercases its own."""
        ctx = _context(repo, _ci("AOS-Edge-POC/AOS_Edge"))
        assert std.image_ref(ctx).startswith(f"{REGISTRY}/aos-edge-poc/aos_edge:")

    @pytest.mark.parametrize(
        "remote",
        [
            "https://code.example.com/aos-edge-poc/aos_edge.git",
            "ssh://git@code.example.com:5022/aos-edge-poc/aos_edge.git",
            "git@code.example.com:aos-edge-poc/aos_edge.git",
        ],
    )
    def test_local_ref_derives_from_the_git_remote(self, repo: Path, remote: str) -> None:
        """The same full name locally as on CI — the parity rule."""
        git("remote", "add", "origin", remote, cwd=repo)
        ctx = _context(repo, _ci())
        assert std.image_ref(ctx) == f"{REGISTRY}/aos-edge-poc/aos_edge:{ctx.version}"

    def test_ci_project_path_wins_over_the_remote(self, repo: Path) -> None:
        git("remote", "add", "origin", "https://code.example.com/other/place.git", cwd=repo)
        ctx = _context(repo, _ci("aos-edge-poc/aos_edge"))
        assert std.image_ref(ctx) == f"{REGISTRY}/aos-edge-poc/aos_edge:{ctx.version}"

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
