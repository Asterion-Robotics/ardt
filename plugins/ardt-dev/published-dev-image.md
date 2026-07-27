# Open decision — publishing the dev image instead of building it per developer

> **Status: open, not decided** (raised 2026-07-24). Nothing here is implemented. Today every developer builds the rendered `Dockerfile` locally; `dev.image:` already exists and switches compose to a published image, so the *mechanism* is in place and this document is only about whether and how to use it.
>
> References the internal specs by name (ADR-015 base images, ADR-016 GitLab organization, ci_tools 09 dev environment); they are not in this repo.

## Why it comes up

Measured on jazzy/amd64 for `ardt_ros2_demo`: the dev image is **3.14 GB on disk, 744 MB to pull**, of which ~1.8 GB unpacked is the dev layer this plugin renders. Every developer pays ~10 minutes and that disk to produce a byte-identical result. A shared, digest-pinned `ros2-dev` image in the base-images repo replaces that with one pull.

Per ADR-015 D4 a dev image is an image **name** (`ros2-dev`), never a tag variant suffix, and it descends from the *builder* line, so D2's "root on `ros-core`, not `ros-base`" rule does not apply to it: that rule keeps compilers out of the runtime base that ships to a robot, and a dev image wants exactly that toolchain.

## What would not change

The render itself, the host overlay, the lifecycle hooks, the cache volumes, `devcontainer.json`, and every `ardt dev` command. `compose()` already emits `image:` in place of `build:` when `dev.image` is set (see `test_published_dev_image_replaces_the_local_build`), so adopting this is a config change in a repo's `ardt.yaml`, not a new code path. The local build stays as the offline fallback.

## What would change

| Area | Today | With a published `ros2-dev` |
|---|---|---|
| Image provenance | built locally, per developer | pulled, digest-pinned |
| Registry access for developers | none needed | `docker login` on every dev machine, laptops and Macs included |
| Package list owner | this plugin's `ros2` profile (`apt_groups`) | contested — decision 1 |
| Parity check | `dev base == pipelines.ros_ci.builder`, a string compare | dev image is *derived from* the builder, not equal — decision 2 |
| Per-repo extras | `dev.apt_packages` baked into the rendered layer | cannot bake into someone else's image — decision 3 |
| Tool version bumps | rebuild when ardt-dev changes | Renovate bumps `dev.image` digest per repo |
| arm64 | untested local build | mandatory (Apple Silicon), paid for in base-images CI |
| Image obligations | none | inherits ADR-015 D1 snapshot pinning, D3 SBOM/provenance, D5 promote-by-digest, D7 cleanup |

## Decision 1 — who owns the dev tooling package list

`images.yaml` is the single source of truth for base images (ADR-015 D2), but "what a developer needs installed" is dev-environment knowledge and already lives here as profile data.

**A. Move the list into `images.yaml`; drop the rendered Dockerfile.**

- Pros: D2's single-source rule holds unqualified; bake builds it like any other node; no cross-repo dependency.
- Cons: no offline fallback at all, so a developer without registry access has nothing; the profile still owns the runtime half (modules, bootstrap steps), so dev knowledge splits across two repos in two languages.

**B. Keep the recipe here; base-images renders it at build time** (`ardt dev render-recipe --profile ros2 > recipes/ros2-dev.Dockerfile`).

- Pros: one list, and the fallback is the same artifact as the published image so it cannot drift; ardt dogfoods itself; **the only option that scales to the second dev image** (see below).
- Cons: base-images gains a build-time dependency on ardt, which D2 deliberately avoided by choosing bake over Dagger; the generator step needs its own pin (which ardt-dev rendered this?) — the rendered header already stamps it.

**C. Both, with a drift check** — list in `images.yaml`, `ardt dev doctor` compares the pinned image's package manifest against the profile.

- Pros: keeps D2 clean and catches divergence.
- Cons: two lists maintained forever; the check needs the image pulled. Most work, least payoff.

**Leaning: B**, for a structural reason rather than taste. A future SDK-module profile wants a dev image rooted on the SDK's own builder image, which ADR-015 D4's scope boundary says **is not a base image** (SemVer'd with the SDK release chain, published by the SDK-side pipeline). So there will be two dev image lines, in two repos, on two versioning schemes. Under A that is the same tooling list written twice; under B it is one recipe with a swapped `BASE_IMAGE`, which is exactly D2's "no recipe names its own FROM" rule.

## Decision 2 — the parity check becomes a provenance check

`ardt dev doctor` currently compares two strings and **fails** on mismatch; that check is what makes the CI-parity contract enforceable rather than aspirational. A published image breaks it: `ros2-dev@sha256:…` is not textually `ros:jazzy-ros-base`.

1. **Trust the tag.** Same CalVer month on both pins implies the same snapshot. Cheap; silently passes when someone repins one and not the other.
2. **Compare the base-digest label.** buildx natively sets `org.opencontainers.image.base.digest`; `doctor` compares it against the repo's pinned builder digest. Needs the image locally, which is fine after `ardt dev up`. Costs almost nothing because the label already exists.
3. **Look it up in the release manifest.** D5 already publishes name → digest → SBOM ref. Works without pulling; needs registry access and manifest parsing in this plugin.

**Leaning: 2, degrading to 1's message when the label is absent.** It preserves the property that matters: the container a developer works in provably descends from the image CI builds on.

## Decision 3 — what happens to `dev.apt_packages`

**This exposes a defect that exists today**, independent of the decision: with `dev.image` set, the rendered Dockerfile is not built, so `dev.apt_packages` is **silently ignored**. Whatever we choose, `doctor` should fail on that combination rather than dropping config quietly. That fix is worth doing now.

**A. `postCreate` installs them** into the running container, backed by the apt cache volume.

- Pros: no per-repo image; extras stay visible in `ardt.yaml`; the cache volume (which now actually works, see the `docker-clean` note in the recipe) makes a re-create cheap.
- Cons: paid on every fresh container; a heavy extras list turns a 30-second create into minutes.

**B. Repo base-extension Dockerfile**, mirroring what `ros-ci` already accepts: a single-stage `dev.Dockerfile` starting `FROM ${BASE_IMAGE}`, spliced by the render.

- Pros: the same pattern and the same constraint the CI recipe already enforces, so it stays one concept; layers cache locally.
- Cons: reintroduces a Dockerfile into repos, which is what this plugin exists to remove, usually for two packages.

**Leaning: A as the default, B for the rare repo needing local image content** (vendor drivers, kernel headers) — the same rule as `ros_ci.base_dockerfile`. Consistency with the CI side is worth more here than optimality.

## Costs to accept deliberately

- **Registry auth on every dev machine**, including Macs and machines that never touch CI. Per ADR-016 that is a group deploy token or a personal login, and a new onboarding step. It also means the offline fallback (decision 1B) is not really optional.
- **Build cost in base-images CI**: a ~3 GB image on two native arches per snapshot bump; D7's cleanup policy should expect one large node.
- **Snapshot pinning applies**, so clangd/rviz2/gdb versions freeze per CalVer tag. That is a feature (reviewable tool bumps) but it means "I want a newer clangd" becomes an MR against `snapshots.yaml`. Someone will be surprised.
- **No mirror or signing obligation**: dev images never ship, so D1's mirror trigger and D3's signing gate do not apply. The SBOM comes free from bake and is worth keeping.
- **A smoke test that mirrors `ros2-base`'s**: where the base test asserts `gcc`/`git`/`colcon` are *absent*, the dev test asserts `rviz2`, `clangd`, `gdb` and `colcon` are *present* and `rviz2 --help` exits 0. Real GUI checks stay a developer's job; CI has no display.

## Smallest sensible first cut, if adopted

1. `ros2-dev` in `images.yaml` as a child of the builder line, generic variant, amd64 + arm64.
2. `ardt dev render-recipe` (decision 1B), with the ardt-dev version stamped in the rendered header (already the case).
3. `doctor`: base-digest label check (decision 2); fail on `dev.image` + `dev.apt_packages` (decision 3, worth doing regardless).
4. Renovate: extend the `ardt.yaml` custom manager to `dev.image`, same tag-plus-digest rule as the other pins.
5. Flip `ardt_ros2_demo` to `dev.image:` and confirm `ardt dev up` builds nothing.

## Related, already decided

- A dev image is an image name, not a tag variant suffix; amd64 + arm64; no L4T dev variant (ADR-015 D4).
- The dev layer names individual rqt plugins, never ROS metapackages: `rqt-common-plugins` costs 398 packages / 1.45 GB because `rqt_image_view` pulls OpenCV's dev packages and `rqt_plot` pulls scipy/matplotlib/VTK. That rule carries over to the published recipe unchanged.
