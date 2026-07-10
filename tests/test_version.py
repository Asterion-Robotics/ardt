"""The tag policy. One implementation, so tasks and pipelines cannot disagree."""

from __future__ import annotations

import pytest

from ardt_core import version
from ardt_core.git import GitInfo


def info(**kwargs: object) -> GitInfo:
    base: dict[str, object] = {"is_repo": True, "sha": "0a1b2c3d4e5f", "short_sha": "0a1b2c3"}
    return GitInfo(**{**base, **kwargs})  # type: ignore[arg-type]


def test_not_a_repo_is_explicitly_unknown() -> None:
    assert version.compute(GitInfo(is_repo=False)) == version.UNKNOWN


def test_repo_without_commits_is_unknown() -> None:
    assert version.compute(GitInfo(is_repo=True, sha=None)) == version.UNKNOWN


def test_exact_tag_is_the_version() -> None:
    assert version.compute(info(tag="v1.4.0", last_tag="v1.4.0")) == "1.4.0"


def test_tag_without_v_prefix_is_untouched() -> None:
    assert version.compute(info(tag="1.4.0", last_tag="1.4.0")) == "1.4.0"


def test_v_prefix_only_stripped_before_a_digit() -> None:
    assert version.strip_tag_prefix("valve-2") == "valve-2"
    assert version.strip_tag_prefix("v2") == "2"


def test_dirty_tag_is_marked() -> None:
    assert version.compute(info(tag="v1.4.0", dirty=True)) == "1.4.0+dirty"


def test_commits_past_a_tag_are_a_dev_release() -> None:
    got = version.compute(info(last_tag="v1.4.0", commits_since_tag=3))
    assert got == "1.4.0.dev3+g0a1b2c3"


def test_no_tag_yet_counts_from_zero() -> None:
    got = version.compute(info(last_tag=None, commits_since_tag=12))
    assert got == "0.0.0.dev12+g0a1b2c3"


def test_dirty_branch_appends_to_the_local_segment() -> None:
    got = version.compute(info(last_tag="v1.4.0", commits_since_tag=3, dirty=True))
    assert got == "1.4.0.dev3+g0a1b2c3.dirty"


def test_short_sha_is_derived_when_absent() -> None:
    got = version.compute(GitInfo(is_repo=True, sha="0a1b2c3d4e5f", commits_since_tag=1))
    assert got == "0.0.0.dev1+g0a1b2c3"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1.4.0", True),
        ("1.4.0+dirty", False),
        ("1.4.0.dev3+g0a1b2c3", False),
        ("0.0.0+unknown", False),
    ],
)
def test_only_a_clean_exact_tag_is_publishable(value: str, expected: bool) -> None:
    assert version.is_release(value) is expected
