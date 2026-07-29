# Changelog

Notable changes per release. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions are git tags (see [RELEASING.md](RELEASING.md)) and package versions derive from them via hatch-vcs.

## [Unreleased]

### Added

- `ardt pipe run <name> --load`: put the built runtime image into the local docker daemon as `<project>:<version>` — the local counterpart of `--publish` (which stays registry-only and errors loudly without one).

## [0.2.0] - 2026-07-29

### Changed

### Fixed

### Added

## [0.2.0] - 2026-07-29

### Changed

- **Breaking:** the `dev.workspace_folder` key is rejected; the container workspace root is always `/ws` (the CI recipe hard-codes the same path, and the parity rule rests on the two never drifting).
- The shipped runtime image installs its own exec dependencies via a rosdep pass over the install space, honoring `tasks.ros.rosdep_skip_keys`; the base image no longer needs to carry the workspace's runtime closure.
- `ardt build` / `ardt test` no longer forward unknown options to colcon; pass-through requires the `--` separator.
- The coverage gate spans all seven packages (combined ≥ 80%) instead of `ardt-core` alone.
- CI enforces the frozen lockfile (no silent re-resolve), runs with a read-only default token, and deploys docs only when lint and tests are green.

### Fixed

- `image_ref` sanitizes PEP 440 local versions (`+` → `-`) into registry-valid OCI tags; publishing non-release builds works.
- `install.sh` anchors `ardt.yaml` key parsing to the section's child indent, so a per-module `modules.<name>.version` pin can no longer shadow the top-level pin.
- GitHub `is_default_branch` reads `repository.default_branch` from the event payload; non-`main` default branches are recognized. GitLab merge-request pipelines keep their ref.
- Subprocess output decodes with `errors="replace"` instead of crashing on non-UTF-8 bytes.
- `find_project_root` only applies the `src/` workspace convention where a workspace is plausible; duplicate YAML keys in `ardt.yaml` are rejected.
- `@pipeline` accepts evaluated `list[str]` annotations (no `from __future__ import annotations` required in plugin modules); non-click `ardt.commands` entry points and cross-plugin command collisions are reported instead of silent.
- `ardt dev`: host detection is a pure function of `HostFacts`, `compile-commands` honors `--dry-run` and diagnoses corrupt fragments, and `dev up --dry-run` plans on a fresh clone.

### Added

- `ardt.example.yaml` documents every supported key; docs gained upgrade/uninstall instructions; shellcheck lints `install.sh`.

## [0.1.2] - 2026-07-27

- Post-user-test fixes: canonical `/ws` workspace convention, one-command dev UX (`ardt dev open`), docs entry path.

## [0.1.1] - 2026-07-27

- `install.sh`: one-line installer as a uv tool, with the context-aware module bundle.

## [0.1.0] - 2026-07-27

- Versioned docs site applies the house style to every published version, plus diagrams.

## [0.0.3] - 2026-07-27

- Theme-agnostic version flyout for the docs; `versions.json` URLs relative to the site root.

## [0.0.2] - 2026-07-27

- Pre-commit config, SPDX headers, lint in CI.

## [0.0.1] - 2026-07-27

- First tagged state: core + pipelines platform, ROS 2 task/pipeline plugins, doc plugins, versioned docs site published to GitHub Pages.
