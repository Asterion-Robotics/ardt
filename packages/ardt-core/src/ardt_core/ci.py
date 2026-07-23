"""CI platform detection and the one normalization table.

Pipelines are parameterized by config + context, *not* by CI env vars (02 §1 rule 2).
That rule only holds if there is exactly one place where the platforms' wildly
different variable names collapse into the same handful of fields. This is it.

Everything a pipeline needs about "where am I running and what may I push to"
arrives as :class:`CIInfo`. Secrets are carried as plain strings here and handed
to Dagger's secret store at the publish step; they are never interpolated into a
build container (02 §6).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import cast

import yaml

from . import env
from .errors import ConfigError


class Platform(StrEnum):
    """Where ardt is running."""

    LOCAL = "local"
    GITLAB = "gitlab"
    GITHUB = "github"


@dataclass(frozen=True)
class CIInfo:
    """Normalized CI facts. The only supported way to reach the environment."""

    platform: Platform
    is_ci: bool
    registry: str | None = None
    registry_user: str | None = None
    registry_password: str | None = field(default=None, repr=False)
    job_token: str | None = field(default=None, repr=False)
    ref: str | None = None
    """The branch or tag name the job is running against."""
    is_tag: bool = False
    is_default_branch: bool = False
    project_path: str | None = None
    """``group/subgroup/project`` on GitLab, ``owner/repo`` on GitHub."""
    ssh_auth_sock: str | None = None
    """The local SSH agent socket, when one is running (local platform only).
    Pipelines forward it into builds that must clone private repos — the
    environment stays reachable only through this normalization."""

    def redacted(self) -> dict[str, object]:
        """Serializable view with secrets replaced by a presence marker."""
        return {
            "platform": self.platform.value,
            "is_ci": self.is_ci,
            "registry": self.registry,
            "registry_user": self.registry_user,
            "registry_password": "<set>" if self.registry_password else None,
            "job_token": "<set>" if self.job_token else None,
            "ref": self.ref,
            "is_tag": self.is_tag,
            "is_default_branch": self.is_default_branch,
            "project_path": self.project_path,
            "ssh_auth_sock": self.ssh_auth_sock,
        }


def credentials_path() -> Path | None:
    """``~/.config/ardt/credentials.yaml`` — local dev's stand-in for CI secrets."""
    home = env.home()
    if home is None:
        return None
    return Path(home) / ".config" / "ardt" / "credentials.yaml"


def _load_credentials() -> dict[str, str]:
    path = credentials_path()
    if path is None or not path.is_file():
        return {}
    try:
        raw: object = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(
            f"cannot read {path}: {exc}",
            hint="fix the YAML, or delete the file to fall back to anonymous access",
        ) from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} must contain a YAML mapping")
    mapping = cast("dict[object, object]", raw)
    return {str(k): str(v) for k, v in mapping.items() if v is not None}


def detect() -> CIInfo:
    """Build :class:`CIInfo` from the environment. Called once, by the Context."""
    if env.flag("GITLAB_CI"):
        return _gitlab()
    if env.flag("GITHUB_ACTIONS"):
        return _github()
    return _local()


def _gitlab() -> CIInfo:
    tag = env.get("CI_COMMIT_TAG")
    branch = env.get("CI_COMMIT_BRANCH")
    default_branch = env.get("CI_DEFAULT_BRANCH")
    return CIInfo(
        platform=Platform.GITLAB,
        is_ci=True,
        registry=env.get("CI_REGISTRY"),
        registry_user=env.get("CI_REGISTRY_USER"),
        registry_password=env.get("CI_REGISTRY_PASSWORD"),
        job_token=env.get("CI_JOB_TOKEN"),
        ref=tag or branch,
        is_tag=tag is not None,
        is_default_branch=branch is not None and branch == default_branch,
        project_path=env.get("CI_PROJECT_PATH"),
    )


def _github() -> CIInfo:
    ref_type = env.get("GITHUB_REF_TYPE")
    ref_name = env.get("GITHUB_REF_NAME")
    default_branch = env.get("GITHUB_BASE_REF") or "main"
    return CIInfo(
        platform=Platform.GITHUB,
        is_ci=True,
        registry="ghcr.io",
        registry_user=env.get("GITHUB_ACTOR"),
        registry_password=env.get("GITHUB_TOKEN"),
        job_token=env.get("GITHUB_TOKEN"),
        ref=ref_name,
        is_tag=ref_type == "tag",
        is_default_branch=ref_type == "branch" and ref_name == default_branch,
        project_path=env.get("GITHUB_REPOSITORY"),
    )


def _local() -> CIInfo:
    creds = _load_credentials()
    return CIInfo(
        platform=Platform.LOCAL,
        is_ci=False,
        registry=creds.get("registry"),
        registry_user=creds.get("registry_user"),
        registry_password=creds.get("registry_password"),
        job_token=creds.get("job_token"),
        project_path=creds.get("project_path"),
        ssh_auth_sock=env.get("SSH_AUTH_SOCK"),
    )
