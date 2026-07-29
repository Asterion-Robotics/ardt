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

"""Host detection — the only place WSL2/Linux/macOS differences live.

``devcontainer.json`` has no conditionals, so everything host-shaped (display
sockets, host networking, GPU device nodes) is emitted into a second compose
file that overlays the portable one. Detection is a pure function of
:class:`HostFacts` so the three host shapes are unit-testable on any machine.
"""

from __future__ import annotations

import platform
from dataclasses import dataclass, field
from pathlib import Path

from ardt_core import env

WSL2 = "wsl2"
LINUX = "linux"
MACOS = "macos"
UNKNOWN = "unknown"


@dataclass(frozen=True)
class HostFacts:
    """What the render needs to know about the machine it is running on."""

    system: str
    """``platform.system()``: Linux, Darwin, Windows."""
    wsl_kernel: bool = False
    """``microsoft`` in ``/proc/version`` — a WSL2 distro."""
    wslg: bool = False
    """``/mnt/wslg`` present: WSLg is serving X11/Wayland/PulseAudio."""
    dxg: bool = False
    """``/dev/dxg`` present: WSL GPU passthrough (D3D12-backed GL)."""
    dri: bool = False
    """``/dev/dri`` present: native GPU nodes."""
    x11_socket: bool = False
    """``/tmp/.X11-unix`` present: an X server (or XWayland) is serving."""
    display: str | None = None
    wsl_distro: str | None = None
    """``WSL_DISTRO_NAME`` — needed to name this distro from the Windows side."""

    @classmethod
    def probe(cls) -> HostFacts:
        """Read the real machine."""
        proc_version = Path("/proc/version")
        wsl_kernel = False
        if proc_version.is_file():
            wsl_kernel = "microsoft" in proc_version.read_text(errors="ignore").lower()
        return cls(
            system=platform.system(),
            wsl_kernel=wsl_kernel,
            wslg=Path("/mnt/wslg").is_dir(),
            dxg=Path("/dev/dxg").exists(),
            dri=Path("/dev/dri").exists(),
            x11_socket=Path("/tmp/.X11-unix").is_dir(),
            display=env.get("DISPLAY"),
            wsl_distro=env.get("WSL_DISTRO_NAME"),
        )


@dataclass(frozen=True)
class HostProfile:
    """The host's contribution to the compose overlay."""

    kind: str
    service: dict[str, object] = field(default_factory=dict)
    """Service-level keys (``network_mode``, ``ipc``)."""
    environment: dict[str, str] = field(default_factory=dict)
    volumes: list[str] = field(default_factory=list)
    devices: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    """Human-facing caveats, surfaced by ``ardt dev doctor``."""

    @property
    def gui(self) -> bool:
        """True when the overlay actually wires a display through."""
        return "DISPLAY" in self.environment or "WAYLAND_DISPLAY" in self.environment


def detect(facts: HostFacts, *, gui: bool = True) -> HostProfile:
    """Resolve the host into a compose overlay."""
    if facts.system == "Darwin":
        return _macos(gui=gui)
    if facts.system == "Linux" and facts.wsl_kernel:
        return _wsl2(facts, gui=gui)
    if facts.system == "Linux":
        return _linux(facts, gui=gui)
    return HostProfile(
        kind=UNKNOWN,
        notes=[
            f"unrecognized host {facts.system!r}: no display, no host networking. "
            "Run ardt from a WSL2 distro, Linux, or macOS."
        ],
    )


def editor_host_path(path: Path, facts: HostFacts) -> str | None:
    """How VS Code addresses ``path``, which is not how the shell addresses it.

    On WSL2 the editor is a Windows process driving a Linux workspace, so it
    knows the repo by its UNC path and nothing else. Everywhere else the two
    agree. None when the machine is WSL2 but will not say which distro it is —
    the caller has no safe guess to make there.
    """
    if facts.system == "Linux" and facts.wsl_kernel:
        if not facts.wsl_distro:
            return None
        return f"\\\\wsl.localhost\\{facts.wsl_distro}" + str(path).replace("/", "\\")
    return str(path)


def folder_uri(host_path: str, workspace_folder: str) -> str:
    """The ``vscode-remote://`` URI that opens a dev container directly.

    The authority is ``dev-container+<host path, hex-encoded>`` and the URI path
    is the folder *inside* the container. This scheme is not in VS Code's public
    docs, which is why `ardt dev open` prefers `devcontainer open` and falls back
    to building the URI only when the Dev Containers CLI is not installed.
    """
    return f"vscode-remote://dev-container+{host_path.encode('utf-8').hex()}{workspace_folder}"


def _dds_service() -> dict[str, object]:
    """Host networking + shared memory, so container nodes and host nodes talk.

    Linux-only: Docker Desktop has no equivalent, which is why macOS falls back
    to localhost-scoped discovery instead.
    """
    return {"network_mode": "host", "ipc": "host"}


def _wsl2(facts: HostFacts, *, gui: bool) -> HostProfile:
    notes: list[str] = []
    environment: dict[str, str] = {}
    volumes: list[str] = []
    devices: list[str] = []

    if gui:
        if facts.wslg:
            # Microsoft's documented WSLg-in-Docker wiring: both sockets, audio,
            # and the WSL user-space GL libraries.
            environment.update(
                {
                    "DISPLAY": facts.display or ":0",
                    "WAYLAND_DISPLAY": "wayland-0",
                    "XDG_RUNTIME_DIR": "/mnt/wslg/runtime-dir",
                    "PULSE_SERVER": "/mnt/wslg/PulseServer",
                    "LD_LIBRARY_PATH": "/usr/lib/wsl/lib",
                }
            )
            volumes += [
                "/mnt/wslg/.X11-unix:/tmp/.X11-unix",
                "/mnt/wslg:/mnt/wslg",
                "/usr/lib/wsl:/usr/lib/wsl",
            ]
            notes.append(
                "Qt prints a one-off 'wrong permissions on runtime directory' warning: "
                "/mnt/wslg/runtime-dir is 0777 on the host and cannot be changed. Harmless."
            )
            if facts.dxg:
                devices.append("/dev/dxg")
            else:
                notes.append("/dev/dxg absent: GL falls back to software (llvmpipe)")
        else:
            notes.append("no /mnt/wslg: update WSL (`wsl --update`) or set dev.gui: false")

    return HostProfile(
        kind=WSL2,
        service=_dds_service(),
        environment=environment,
        volumes=volumes,
        devices=devices,
        notes=notes,
    )


def _linux(facts: HostFacts, *, gui: bool) -> HostProfile:
    notes: list[str] = []
    environment: dict[str, str] = {}
    volumes: list[str] = []
    devices: list[str] = []

    if gui:
        if facts.x11_socket:
            environment["DISPLAY"] = facts.display or ":0"
            volumes.append("/tmp/.X11-unix:/tmp/.X11-unix")
            notes.append("run `xhost +local:docker` once per login if a GUI cannot open a display")
            if facts.dri:
                devices.append("/dev/dri")
        else:
            notes.append("no /tmp/.X11-unix: a Wayland-only session needs its own wiring")

    return HostProfile(
        kind=LINUX,
        service=_dds_service(),
        environment=environment,
        volumes=volumes,
        devices=devices,
        notes=notes,
    )


def _macos(*, gui: bool) -> HostProfile:
    notes = [
        "Docker Desktop has no host networking: DDS discovery is scoped to the container "
        "(ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST)",
    ]
    if gui:
        notes.append(
            "no X11 on macOS: rviz2/rqt are not wired yet — the intended answer is the "
            "desktop-lite (noVNC) feature, or Foxglove in a browser"
        )
    return HostProfile(
        kind=MACOS,
        environment={"ROS_AUTOMATIC_DISCOVERY_RANGE": "LOCALHOST"},
        notes=notes,
    )
