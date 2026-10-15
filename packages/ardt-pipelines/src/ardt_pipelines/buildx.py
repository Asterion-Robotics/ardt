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

"""The executor: BuildKit through ``docker buildx``.

A pipeline describes its build as a bake file (one target per Dockerfile
stage it needs, with that target's platforms, outputs, cache and secrets) and
hands it here; this module owns every ``docker`` invocation of the pipeline
plane, so a buildx or BuildKit change lands in one file. The bake file is also
exported with the run, so ``docker buildx bake -f <it>`` reproduces the run
with no ardt installed.

Why BuildKit directly and not an engine of its own: the base layers of an
image built here are the registry's own blobs, byte for byte, so every image
of a fleet shares one base chain on a host; and the layer cache lives in the
registry (``cache-to type=registry``), so it survives any daemon, runner or
restart instead of dying with an engine's garbage collection.
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from ardt_core.context import Context
from ardt_core.errors import ArdtError

BUILDER = "ardt"
"""The builder every ardt run uses: a ``docker-container`` driver, which is
what multi-platform builds, registry cache export and local outputs need (the
daemon's default builder has none of them). Created on first use; a CI job
class may pre-create it, with native nodes appended for other architectures."""

BAKE_FILE = "bake.json"
"""The bake file's name inside the export directory."""

BUILDKIT_IMAGE = "moby/buildkit:v0.33.1"
"""The BuildKit the builder runs: pinned, so every builder of a fleet (laptops
and runners) resolves, caches and exports the same way whatever buildx the
host carries. Bumped on purpose, with the pipeline tests."""

BUILDKITD_CONFIG = """\
# Written by ardt when it created this builder; change it with
#   docker buildx rm --keep-state ardt && docker buildx create --name ardt \\
#     --driver docker-container --buildkitd-config <your file>
# (the cache survives the recreation).
[worker.oci]
  gc = true
  # the garbage collector keeps the layer cache and the cache mounts (apt,
  # ccache) under this ceiling, oldest and least used first
  maxUsedSpace = "40GB"
  minFreeSpace = "10%"
"""
"""The builder's default daemon configuration: a bounded cache instead of
BuildKit's disk-relative default, so a laptop never finds its disk eaten."""


@dataclass
class Target:
    """One bake target: a Dockerfile stage built with these settings.

    Field names follow the bake file's own vocabulary so the rendered JSON
    reads like the documentation."""

    name: str
    dockerfile: str
    target: str
    context: str = "."
    platforms: list[str] = field(default_factory=list[str])
    args: dict[str, str] = field(default_factory=dict[str, str])
    output: list[str] = field(default_factory=list[str])
    tags: list[str] = field(default_factory=list[str])
    cache_from: list[str] = field(default_factory=list[str])
    cache_to: list[str] = field(default_factory=list[str])
    secret: list[str] = field(default_factory=list[str])
    ssh: list[str] = field(default_factory=list[str])
    contexts: dict[str, str] = field(default_factory=dict[str, str])

    def render(self) -> dict[str, object]:
        body: dict[str, object] = {
            "context": self.context,
            "dockerfile": self.dockerfile,
            "target": self.target,
        }
        optional: dict[str, object] = {
            "platforms": self.platforms,
            "args": self.args,
            "output": self.output,
            "tags": self.tags,
            "cache-from": self.cache_from,
            "cache-to": self.cache_to,
            "secret": self.secret,
            "ssh": self.ssh,
            "contexts": self.contexts,
        }
        body.update({key: value for key, value in optional.items() if value})
        return body


def render_bake(targets: Sequence[Target]) -> str:
    """The bake file: every target, and a default group naming them all."""
    document = {
        "group": {"default": {"targets": [t.name for t in targets]}},
        "target": {t.name: t.render() for t in targets},
    }
    return json.dumps(document, indent=2) + "\n"


def _entitlements(bake_file: Path) -> list[str]:
    """``--allow=fs.read=<path>`` for every named context of the bake file.

    bake refuses to read a directory outside the working tree unless the
    caller grants it: a named context pointing at a local ardt checkout is
    exactly that, and granting the paths the file itself names is the whole
    permission the run needs."""
    try:
        document = json.loads(bake_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    paths: list[str] = []
    for target in document.get("target", {}).values():
        contexts: dict[str, object] = target.get("contexts") or {}
        for path in contexts.values():
            if isinstance(path, str) and Path(path).is_absolute() and path not in paths:
                paths.append(path)
    return [f"--allow=fs.read={path}" for path in paths]


class Buildx:
    """``docker buildx`` as the pipeline plane sees it."""

    def __init__(self, ctx: Context, *, builder: str = BUILDER) -> None:
        self.ctx = ctx
        self.builder = builder
        self._ready = False
        self._env: dict[str, str] = {}

    def with_env(self, values: Mapping[str, str]) -> None:
        """Environment handed to every later docker command: how a secret
        reaches a ``secret = ["id=...,env=NAME"]`` bake entry without a file."""
        self._env.update(values)

    def ensure_builder(self) -> None:
        """The named builder, created on first use; a no-op when it exists."""
        if self._ready:
            return
        runner = self.ctx.runner
        runner.require("docker", hint="the pipeline plane runs on docker buildx")
        probe = runner.run(["docker", "buildx", "inspect", self.builder], check=False, quiet=True)
        if not probe.ok and not probe.skipped:
            self.ctx.console.step(
                f"creating buildx builder `{self.builder}` (docker-container, {BUILDKIT_IMAGE})"
            )
            with tempfile.TemporaryDirectory(prefix="ardt-builder-") as tmp:
                config = Path(tmp) / "buildkitd.toml"
                config.write_text(BUILDKITD_CONFIG, encoding="utf-8")
                runner.run(
                    [
                        "docker",
                        "buildx",
                        "create",
                        "--name",
                        self.builder,
                        "--driver",
                        "docker-container",
                        "--driver-opt",
                        f"image={BUILDKIT_IMAGE}",
                        "--buildkitd-config",
                        str(config),
                        "--bootstrap",
                    ],
                    quiet=True,
                )
        self._ready = True

    def login(self, *, required: bool = False) -> None:
        """Log the daemon in to the registry with the credentials at hand, when
        there are any; the password travels on stdin, never on the command.

        A failed login is fatal only when ``required`` (a publish needs it);
        otherwise it is a warning: a gate run reads the registry cache if it
        can and builds without it if it cannot."""
        ci = self.ctx.ci
        if ci.registry is None or ci.registry_password is None:
            return
        result = self.ctx.runner.run(
            ["docker", "login", ci.registry, "-u", ci.registry_user or "", "--password-stdin"],
            stdin=ci.registry_password,
            quiet=True,
            check=required,
        )
        if not result.ok and not result.skipped:
            self.ctx.console.warn(
                f"registry login to {ci.registry} failed; building without its cache "
                f"({result.tail.strip().splitlines()[-1] if result.tail.strip() else 'no detail'})"
            )

    def bake(
        self, bake_file: Path, targets: Sequence[str], *, cwd: Path
    ) -> dict[str, dict[str, object]]:
        """Build the named targets of ``bake_file``; returns buildx's metadata
        per target (``containerimage.digest``, ``image.name``, ...)."""
        self.ensure_builder()
        with tempfile.TemporaryDirectory(prefix="ardt-bake-") as tmp:
            metadata = Path(tmp) / "metadata.json"
            self.ctx.runner.run(
                [
                    "docker",
                    "buildx",
                    "bake",
                    "--builder",
                    self.builder,
                    "--file",
                    str(bake_file),
                    "--metadata-file",
                    str(metadata),
                    "--progress=plain",
                    *_entitlements(bake_file),
                    *targets,
                ],
                cwd=cwd,
                extra_env=self._env,
            )
            if self.ctx.dry_run or not metadata.is_file():
                return {}
            loaded = json.loads(metadata.read_text(encoding="utf-8"))
        return {name: value for name, value in loaded.items() if isinstance(value, dict)}

    def imagetools_create(self, ref: str, sources: Sequence[str]) -> str:
        """One manifest list ``ref`` from per-platform images pushed by digest;
        returns the list's digest."""
        if not sources:
            raise ArdtError("nothing to merge: no per-platform digests were given")
        self.ctx.runner.run(
            ["docker", "buildx", "imagetools", "create", "--tag", ref, *sources], quiet=True
        )
        return self.digest_of(ref)

    def digest_of(self, ref: str) -> str:
        result = self.ctx.runner.run(
            [
                "docker",
                "buildx",
                "imagetools",
                "inspect",
                ref,
                "--format",
                "{{json .Manifest.Digest}}",
            ],
            quiet=True,
        )
        if result.skipped:
            return "<digest>"
        return json.loads(result.tail.strip().splitlines()[-1])
