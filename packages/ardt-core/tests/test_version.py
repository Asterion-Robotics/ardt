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


# --- the build-time / runtime contract -------------------------------------


def test_a_release_version_is_exactly_the_tag_which_is_what_the_wheel_carries() -> None:
    """The one string hatch-vcs and `compute` must agree on.

    Wheels are versioned by hatch-vcs (setuptools-scm) and `ctx.version` by
    `compute`; both read the same tag but their *dev* formats differ
    (setuptools-scm emits `1.4.0.post1.dev3`, this emits `1.4.0.dev3`). That
    divergence is cosmetic and only ever appears off-tag. On a clean tag — the
    only publishable state — both must produce the bare tag, or a published
    wheel would not be findable at the version it was released as.
    """
    computed = version.compute(info(tag="v1.4.0", last_tag="v1.4.0"))
    assert computed == "1.4.0"
    assert version.is_release(computed)


def test_installed_falls_back_instead_of_raising_for_an_uninstalled_package() -> None:
    assert version.installed("ardt-not-a-real-distribution") == version.UNKNOWN


def test_installed_reads_real_metadata() -> None:
    assert version.installed("ardt-core") not in ("", None)
