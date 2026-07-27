# Versioning

**The git tag is the only version that exists.** No file in the repo states one: every `pyproject.toml` is `dynamic = ["version"]` via `hatch-vcs`, and every package's `__version__` reads its installed metadata. A release is one command, and there is nothing to keep in sync.

```bash
git tag v0.1.0 && git push --tags
```

Reading it back:

| Where | Command | Source |
|---|---|---|
| the working tree | `ardt info` | `ctx.version` → `git describe` |
| the installed CLI | `ardt --version` | metadata stamped at build time |
| the tag itself | `git describe --tags --dirty` | git |

The two formats agree **on a clean tag**, the only publishable state, which is what `is_release()` gates on. Off-tag they differ cosmetically: `hatch-vcs` emits `0.1.0.post1.dev3+g0a1b2c3`, `ctx.version` emits `0.1.0.dev3+g0a1b2c3`. Both are PEP 440 and both name the same commit.

The policy in one line, implemented in {py:mod}`ardt_core.version`: tag → semver; branch → `<last-tag>.devN+g<sha>`; dirty → `+.dirty`; no repo → `0.0.0+unknown`.

A checkout without `.git` (GitHub's "Download ZIP") builds as `0.0.0` via `fallback-version` rather than failing. `pip install git+…` is unaffected: pip clones, so the tags are there.
