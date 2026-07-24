"""The single implementation of the tag policy (01 §5, 07 §5).

Both planes read this: "am I on a tag" and "what do I tag this image" resolve
identically in a task and in a pipeline because there is one function.

Policy:

===================  ==============================
State                Version
===================  ==============================
on tag ``v1.4.0``    ``1.4.0``
3 commits past it    ``1.4.0.dev3+g0a1b2c3``
no tag yet           ``0.0.0.dev12+g0a1b2c3``
dirty tree           the above ``+ .dirty``
not a git repo       ``0.0.0+unknown``
===================  ==============================

Spec note: 01 §5 words the same policy as ``dev-<sha>`` / ``local-<sha>-dirty``.
Those are not valid PEP 440 versions, and these strings become wheel versions and
image tags, so 07 §5's ``<last-tag>.devN+g<sha>`` form is what is implemented and
07 §3's "specs win" was raised rather than silently split. Deviating: the dirty
marker is a local-segment suffix (``+g0a1b2c3.dirty``) instead of a separate
scheme, because a local segment is exactly where PEP 440 puts "not from a clean
source".
"""

from __future__ import annotations

import re
from importlib import metadata

from .git import GitInfo

UNKNOWN = "0.0.0+unknown"

_TAG_PREFIX = re.compile(r"^v(?=\d)")


def strip_tag_prefix(tag: str) -> str:
    """``v1.4.0`` -> ``1.4.0``; a tag not starting with ``v<digit>`` is unchanged."""
    return _TAG_PREFIX.sub("", tag)


def compute(git: GitInfo) -> str:
    """Resolve the version of the working tree. Never guesses: see module docstring."""
    if not git.is_repo or git.sha is None:
        return UNKNOWN

    if git.tag is not None:
        base = strip_tag_prefix(git.tag)
        return f"{base}+dirty" if git.dirty else base

    short = git.short_sha or git.sha[:7]
    base = strip_tag_prefix(git.last_tag) if git.last_tag else "0.0.0"
    version = f"{base}.dev{git.commits_since_tag}+g{short}"
    return f"{version}.dirty" if git.dirty else version


def is_release(version: str) -> bool:
    """True for an exact-tag version off a clean tree — the only publishable state."""
    return "dev" not in version and "+" not in version


def installed(distribution: str) -> str:
    """The version the build stamped into ``distribution``'s installed metadata.

    Every ardt package's ``__version__`` is this call, so the version is declared
    once per distribution (in its ``pyproject.toml``) instead of being repeated
    in a module constant that drifts silently the moment someone bumps one and
    not the other. :data:`UNKNOWN` when the package is imported from a source
    tree that was never installed.
    """
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return UNKNOWN
