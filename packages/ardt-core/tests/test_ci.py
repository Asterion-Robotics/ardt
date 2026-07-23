"""CI detection and the normalization table — the one env choke point."""

from __future__ import annotations

from pathlib import Path

import pytest

from ardt_core import ci
from ardt_core.ci import Platform
from ardt_core.errors import ConfigError


def test_no_ci_vars_means_local(monkeypatch: pytest.MonkeyPatch) -> None:
    info = ci.detect()
    assert info.platform is Platform.LOCAL
    assert info.is_ci is False


def test_gitlab_tag_build(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITLAB_CI", "true")
    monkeypatch.setenv("CI_COMMIT_TAG", "v2.0.0")
    monkeypatch.setenv("CI_REGISTRY", "registry.example.com")
    monkeypatch.setenv("CI_REGISTRY_USER", "gitlab-ci-token")
    monkeypatch.setenv("CI_REGISTRY_PASSWORD", "secret")
    monkeypatch.setenv("CI_JOB_TOKEN", "jobtoken")
    monkeypatch.setenv("CI_PROJECT_PATH", "aos/infra/ardt")

    info = ci.detect()
    assert info.platform is Platform.GITLAB
    assert info.is_ci is True
    assert info.is_tag is True
    assert info.ref == "v2.0.0"
    assert info.registry == "registry.example.com"
    assert info.registry_password == "secret"
    assert info.project_path == "aos/infra/ardt"


def test_gitlab_default_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITLAB_CI", "true")
    monkeypatch.setenv("CI_COMMIT_BRANCH", "main")
    monkeypatch.setenv("CI_DEFAULT_BRANCH", "main")
    info = ci.detect()
    assert info.is_tag is False
    assert info.is_default_branch is True
    assert info.ref == "main"


def test_github_tag_build(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_REF_TYPE", "tag")
    monkeypatch.setenv("GITHUB_REF_NAME", "v2.0.0")
    monkeypatch.setenv("GITHUB_ACTOR", "octocat")
    monkeypatch.setenv("GITHUB_TOKEN", "ghtoken")
    monkeypatch.setenv("GITHUB_REPOSITORY", "asterion/ardt")

    info = ci.detect()
    assert info.platform is Platform.GITHUB
    assert info.registry == "ghcr.io"
    assert info.is_tag is True
    assert info.job_token == "ghtoken"
    assert info.project_path == "asterion/ardt"


def test_gitlab_wins_when_both_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITLAB_CI", "true")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert ci.detect().platform is Platform.GITLAB


def test_redacted_hides_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_TOKEN", "supersecret")
    redacted = ci.detect().redacted()
    # ghcr login uses the token as the registry password, so both are set — but
    # the point of redacted() is that neither leaks the raw value.
    assert redacted["registry_password"] == "<set>"
    assert redacted["job_token"] == "<set>"
    assert "supersecret" not in str(redacted)


def test_local_reads_credentials_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".config" / "ardt").mkdir(parents=True)
    (home / ".config" / "ardt" / "credentials.yaml").write_text(
        "registry: registry.example.com\nregistry_user: me\nregistry_password: pw\n"
        "project_path: aos-edge-poc/aos_edge\n"
    )
    monkeypatch.setenv("HOME", str(home))

    info = ci.detect()
    assert info.platform is Platform.LOCAL
    assert info.registry == "registry.example.com"
    assert info.registry_password == "pw"
    assert info.project_path == "aos-edge-poc/aos_edge"


def test_malformed_credentials_file_is_a_clean_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    (home / ".config" / "ardt").mkdir(parents=True)
    (home / ".config" / "ardt" / "credentials.yaml").write_text("- not\n- a mapping\n")
    monkeypatch.setenv("HOME", str(home))

    with pytest.raises(ConfigError):
        ci.detect()
