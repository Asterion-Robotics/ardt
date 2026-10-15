# Releasing

A release is a git tag; there is no version file to bump. hatch-vcs derives every package's version from the tag (`root = "../.."` in each `pyproject.toml`), so one tag versions all eight distributions, and consumer repos pin it via `ardt.version` in their `ardt.yaml`.

## Procedure

1. Update [CHANGELOG.md](CHANGELOG.md): retitle *Unreleased* to the new version with today's date, and start a fresh empty *Unreleased* section. Commit on `main`.
2. Tag and push. The tag trigger in `ci.yml` runs the full pipeline; once lint and tests are green, the docs site deploys and the CI image is published as `ghcr.io/asterion-robotics/ardt-ci:vX.Y.Z` (amd64 and arm64), with that release installed in it.

   ```bash
   git tag -a vX.Y.Z -m "vX.Y.Z"
   git push origin main vX.Y.Z
   ```

3. Create the GitHub release. Generated notes give the PR-level detail; the changelog stays the curated record.

   ```bash
   gh release create vX.Y.Z --generate-notes
   ```

## Versioning policy

Semver-ish while pre-1.0: breaking config or CLI changes bump the minor and are called out with **Breaking:** in the changelog; everything else bumps the patch. Bumping `ARDT_PLUGIN_API` (a plugin-contract break) is always at least a minor.
