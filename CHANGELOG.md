# Changelog

Notable changes per release. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions are git tags (see [RELEASING.md](RELEASING.md)) and package versions derive from them via hatch-vcs.

## [Unreleased]

### Changed

- **Breaking:** `tasks.ros.package_scope`, defaulting to `project`: the three ROS tasks operate on the repo's own packages and nothing beyond what they need. `ardt build` runs `colcon build --packages-up-to <own>`, `ardt test` runs `colcon test --packages-select <own>` (imported dependencies' suites are not this repo's gate), and the rosdep pass resolves only that closure's manifests, so an imported stack's demo packages are neither dep-resolved, built, nor tested. A repo with no `.repos` imports has own == everything and keeps the old behavior exactly; only a repo that builds imported packages nothing of its own depends on breaks, and `package_scope: workspace` restores the old semantics. "Own" is discovered (`colcon list --base-paths <project root>`), never declared; an explicit `--packages-select` still overrides the scope.
- `tasks.ros.repos_file` left unset now auto-detects `<project>.repos` in the project root and skips the import when absent. An explicit value must still exist (a typo must not silently drop the import), and an explicit empty string opts out of the auto-detection.

## [0.4.0] - 2026-08-04

### Changed

- `ros-ci` builds faster, mostly felt on multi-platform runs. The recipe splits the tests out of the `build` stage into a `test` stage, and the runtime image forks from `build` (or from the new `strip` stage when `strip_dev_files` is on, which keeps the tests seeing the unstripped install), deliberately not from `test`: depending on it made every foreign-arch runtime build re-run the whole suite under QEMU. The escape hatch mirrors the split: `docker build --target test` is the CI gate, a plain `docker build` produces the shipped image without re-running tests.
- The recipe copies manifests first: only the files `ardt deps` reads (`package.xml`, `COLCON_IGNORE`, `*.repos`, `ardt.yaml`) land before the deps layer, so a source edit no longer invalidates the apt/rosdep/vcs work. The caveat the cache inherits: `vcs import` clones branch HEADs, so a cached deps layer does not see upstream drift; pin commits or tags in the `.repos` file, or touch it to force a re-import.
- Per-arch apt cache mounts in the builder and runtime stages make `apt-get update` and repeated package downloads near-free across runs on a persistent engine. A ccache mount is wired but inert until the builder image ships ccache and the repo opts in via `tasks.ros.build_args`.
- The per-platform runtime builds run concurrently instead of sequentially: the engine overlaps one arch's network-bound apt with the other's CPU-bound emulated compile.
- `ardt pipe run ros-ci --arg platforms=…` narrows one run to a subset of `pipelines.ros_ci.platforms`; the MR gate is the intended user (`platforms=linux/amd64` skips the emulated arm64 build entirely), while the tag pipeline keeps the config default and publishes the full manifest list.

### Fixed

- `install.sh` still resolved `ardt-devcontainers` to `plugins/ardt-devcontainers`, the path it had before 0.3.0 promoted the devcontainer engine to a `packages/` plane. Every default (non-CI) install failed on `has no subdirectory plugins/ardt-devcontainers`; CI installs were unaffected, since the runner bundle carries neither dev module. The installer's copy of the platform-vs-plugin split is now pinned to the checkout layout and to `ardt_core.dist` by `tests/test_install_sh.py`, for every module in the monorepo.

## [0.3.1] - 2026-07-29

Docs only: the planes diagram draws the extension slots (entry-point groups), and the CLI surface is regrouped under Tools. No code changes.

## [0.3.0] - 2026-07-29

### Changed

- **Breaking:** `ardt-dev` is split in two. The devcontainer engine becomes **`ardt-devcontainers`** under `packages/` (module `ardt_devcontainers`), a platform plane beside `ardt-core` and `ardt-pipelines`; the ROS 2 profile becomes **`ardt-ros-dev`** under `plugins/` (module `ardt_ros_dev`), a data-only theme plugin. The `ardt dev` verb, the `dev:` config section and every rendered file are unchanged.

  **To upgrade a repo:** bump its `ardt:` pin to a release containing the split, re-run `ardt dev sync`, and rebuild the dev image. The rendered `.devcontainer/ardt-requirements.txt` installs modules by monorepo subdirectory, so a host ardt that has the split would otherwise emit `packages/ardt-devcontainers` for a pinned rev where that path does not exist. This is the existing "host ardt ≈ pinned ardt" contract that `ardt dev doctor` already checks; the failure is loud, and an un-synced repo keeps working against its old pin until you re-sync. Workstations that installed via `install.sh` get both new modules from the default bundle; a repo pinning modules by hand (`ardt.modules`, `install_extras`, `install_skip`, `docs_ci.ardt_modules`) must rename `ardt-dev` to the two new names.

- The devcontainer is documented as a **plane**, not a theme: `doc/themes/devcontainer/` moved to `doc/devcontainer/`, `doc/themes/index.md` became a themes-by-planes matrix, and `plane` joined the concepts vocabulary. Only the docs move; no package, command or config key changes. Links to the old `themes/devcontainer/…` URLs break, though previously published versions of the site keep their own paths.

### Added

- `ardt.dev_profiles`, a fourth plugin entry-point group: a distribution contributes a `Profile` and `ardt dev` renders for that kind of repo without the engine importing anything of it. Third-party profiles no longer need a PR against ardt. The `Profile` contract is **provisional** until a second profile exists: it may change in a minor release, with `ARDT_PLUGIN_API` bumped when it does.
- `Registry.load_deferred(groups)` loads deferred entry points per group, so resolving a dev profile no longer imports pipeline modules (and no longer pays for Dagger on a laptop).
- `ardt plugins` reports each plugin's `dev_profiles`, and `ardt dev profiles` names the distribution each profile comes from.
- The `ros2` dev profile puts the workspace install space on `c_cpp_properties.json`'s `includePath`, ahead of the distro's, so a package built in the workspace shadows the installed copy of the same name (both colcon layouts are covered). It also ships the `mhutchie.git-graph` extension.
- `ardt pipe run <name> --load`: put the built runtime image into the local docker daemon as the moving tag `<project>:<X.Y.Z>-dev` for the release being developed (a release load also gets the pinned `<project>:<version>`) — the local counterpart of `--publish`, which stays registry-only and errors loudly without one.
- `ardt doc serve` (`--site` for the docs-ci output): local http preview of the built docs via the stdlib `http.server`, no new dependency. Needed because `file://` neither resolves directory URLs nor lets the version switcher fetch `versions.json`; `docs-ci` now ends with a pointer to it.
- Docs point to the official demo repos ([`ardt_ros2_demo`](https://github.com/Asterion-Robotics/ardt_ros2_demo) on GitHub, mirrored on GitLab): a README paragraph and a new "Demo with a ROS 2 project" page.

### Fixed

- `docs-ci`: a historical ref that fails to build no longer fails the whole site. It is reported by name, left out of the site, and listed under `skipped` in the `--json` envelope; the working-tree build still fails the run. The site builds every ref inside one builder whose module set comes from the working tree, so a ref only builds while its `conf.py` imports distributions the current tree still ships. That is what the `ardt-dev` rename broke, and an old ref cannot be repaired, so failing the run over it would cost every other version of the site. Follow-up in [#19](https://github.com/Asterion-Robotics/ardt/issues/19): list the broken version with a placeholder page and make the failure mode configurable.

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
