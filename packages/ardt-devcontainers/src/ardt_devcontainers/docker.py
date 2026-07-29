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

"""The host-side docker plumbing every `ardt dev` driver command shares.

One daemon probe (so `doctor` and the drive commands cannot print diverging
diagnoses), the volume provisioning compose will not do itself, and the
compose argv against the rendered files.
"""

from __future__ import annotations

from pathlib import Path

from ardt_core import env as env_module
from ardt_core.context import Context
from ardt_core.errors import ArdtError

from . import render as render_module
from .host import HostFacts
from .render import COMPOSE, COMPOSE_HOST, IN_CONTAINER_ENV, Render


def daemon_status(ctx: Context) -> tuple[bool, str]:
    """Probe the docker daemon: ``(reachable, detail)``.

    The one probe both :func:`require_docker` and ``doctor`` use, so their
    diagnoses cannot drift. The unreachable detail is the everyday WSL2 trap:
    Docker Desktop stopped, or its WSL integration off for this very distro,
    and every `docker` call dies with a socket error the user has seen ten
    times without ever reading.
    """
    probe = ctx.runner.run(
        ["docker", "info", "--format", "{{.ServerVersion}}"], check=False, quiet=True
    )
    if probe.ok:
        return True, f"daemon up (server {probe.tail.strip()})"
    if HostFacts.probe().wsl_kernel:
        return False, (
            "WSL2: start Docker Desktop on Windows and check Settings > Resources > "
            "WSL integration is enabled for THIS distro — or install Docker Engine "
            "inside the distro"
        )
    return False, (
        "start the daemon (`sudo systemctl start docker`) and check your user "
        "is in the `docker` group"
    )


def require_docker(ctx: Context) -> None:
    """Fail with a diagnosis, not a stack trace, when docker cannot run."""
    ctx.runner.require(
        "docker", hint="install Docker Engine, or enable Docker Desktop's WSL integration"
    )
    if ctx.dry_run:
        return
    ok, detail = daemon_status(ctx)
    if not ok:
        raise ArdtError("docker is installed but its daemon is not reachable", hint=detail)


def ensure_volumes(ctx: Context, plan: Render) -> list[str]:
    """Create what compose will not create itself, and return what was touched.

    Two gaps, both by design elsewhere: an ``external:`` volume is compose's cue
    that something else owns it (which is exactly what keeps `--purge`
    repo-scoped), and Docker refuses to mount a subpath that does not exist
    rather than creating it (moby#47842). Both are fixed with a `docker volume
    create` and one throwaway `mkdir` container, all idempotent.
    """
    touched: list[str] = []
    for name in plan.shared_volumes:
        ctx.runner.run(["docker", "volume", "create", name], quiet=True)
        touched.append(name)
    if plan.colcon_volume:
        ctx.runner.run(["docker", "volume", "create", plan.colcon_volume], quiet=True)
        # The provisioning image is the one this repo pulls anyway, so this
        # costs no extra download.
        ctx.runner.run(
            [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{plan.colcon_volume}:/volume",
                plan.provision_image,
                "mkdir",
                "-p",
                *[f"/volume/{name}" for name in render_module.COLCON_DIRS],
            ],
            quiet=True,
        )
        touched.append(plan.colcon_volume)
    return touched


def compose_argv(ctx: Context) -> list[str]:
    for name in (COMPOSE, COMPOSE_HOST):
        if not (ctx.project_root / name).is_file():
            # Under --dry-run the file may legitimately not exist yet: the
            # implicit sync plans it but must not write. The plan still prints.
            if ctx.dry_run:
                continue
            raise ArdtError(f"{name} is missing", hint="run `ardt dev sync` first")
    require_docker(ctx)
    return [
        "docker",
        "compose",
        "-f",
        str(ctx.project_root / COMPOSE),
        "-f",
        str(ctx.project_root / COMPOSE_HOST),
    ]


def in_container() -> bool:
    """The image sets the marker; /.dockerenv covers a container ardt was pip-installed into."""
    return env_module.flag(IN_CONTAINER_ENV) or Path("/.dockerenv").exists()
