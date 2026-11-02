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

"""The apt step wrapper, run for real: a step goes through a cache that answers,
and straight to the image's sources when the cache is absent, down, hung, or
the step fails through it."""

from __future__ import annotations

import shutil
import socket
import subprocess
import threading
import time
from collections.abc import Iterator
from importlib import resources
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    not all(shutil.which(tool) for tool in ("sh", "bash", "timeout", "sed")),
    reason="the wrapper runs under a POSIX shell with bash and coreutils",
)

SCRIPT = str(resources.files("ardt_ros_pipelines.recipes") / "ardt-apt.sh")

DEB822 = """Types: deb
URIs: https://snapshot.ubuntu.com/ubuntu/20260925T000000Z/
Suites: resolute resolute-updates
Components: main universe
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
"""
ONE_LINE = (
    "deb [signed-by=/usr/share/keyrings/ros.asc] http://snapshots.ros.org/lyrical/2026-08-19/ubuntu"
    " resolute main\n"
)

# What every step below prints: whether apt was pointed elsewhere, and the
# sources it would read.
SHOW = """if [ -n "${APT_CONFIG:-}" ]; then
  echo "via=cache"
  cat "$(sed -n 's/^Dir::Etc::sourceparts "\\(.*\\)";$/\\1/p' "$APT_CONFIG")"/*
  cat "$(sed -n 's/^Dir::Etc::parts "\\(.*\\)";$/\\1/p' "$APT_CONFIG")"/zz-ardt-apt
else
  echo "via=direct"
fi
"""


class _Server:
    """A TCP server on localhost that answers HTTP, or accepts and never answers."""

    def __init__(self, *, hang: bool) -> None:
        self._hang = hang
        self._sock = socket.socket()
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen()
        self.port: int = self._sock.getsockname()[1]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        self._sock.settimeout(0.1)
        held: list[socket.socket] = []
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except TimeoutError:
                continue
            if self._hang:
                held.append(conn)
                continue
            conn.recv(1024)
            conn.sendall(b"HTTP/1.0 200 OK\r\nContent-Length: 0\r\n\r\n")
            conn.close()
        for conn in held:
            conn.close()

    def close(self) -> None:
        self._stop.set()
        self._thread.join()
        self._sock.close()


@pytest.fixture
def cache() -> Iterator[_Server]:
    server = _Server(hang=False)
    yield server
    server.close()


@pytest.fixture
def hung_cache() -> Iterator[_Server]:
    server = _Server(hang=True)
    yield server
    server.close()


@pytest.fixture
def etc(tmp_path: Path) -> Path:
    root = tmp_path / "etc-apt"
    (root / "sources.list.d").mkdir(parents=True)
    (root / "apt.conf.d").mkdir()
    (root / "sources.list.d" / "ubuntu.sources").write_text(DEB822)
    (root / "sources.list.d" / "ros.list").write_text(ONE_LINE)
    (root / "apt.conf.d" / "80-retries").write_text('Acquire::Retries "5";\n')
    return root


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def run(
    tmp_path: Path, etc: Path, step: str, *, spec: str | None
) -> subprocess.CompletedProcess[str]:
    spec_path = tmp_path / "apt_proxy"
    if spec is not None:
        spec_path.write_text(spec)
    return subprocess.run(
        ["sh", SCRIPT],
        input=step,
        capture_output=True,
        text=True,
        check=False,
        env={
            "PATH": "/usr/bin:/bin",
            "ARDT_APT_SPEC": str(spec_path),
            "ARDT_APT_ETC": str(etc),
            "TMPDIR": str(tmp_path),
        },
        timeout=30,
    )


def test_without_the_secret_the_step_runs_as_written(tmp_path: Path, etc: Path) -> None:
    result = run(tmp_path, etc, SHOW, spec=None)
    assert result.returncode == 0
    assert result.stdout.splitlines()[-1] == "via=direct"


def test_a_cache_that_answers_serves_every_source_in_prefix_form(
    tmp_path: Path, etc: Path, cache: _Server
) -> None:
    url = f"http://127.0.0.1:{cache.port}"
    result = run(tmp_path, etc, SHOW, spec=f"url={url}\nprobe_timeout=2\n")
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "via=cache" in out
    assert f"URIs: {url}/snapshot.ubuntu.com/ubuntu/20260925T000000Z/" in out
    assert f"] {url}/snapshots.ros.org/lyrical/2026-08-19/ubuntu resolute main" in out
    # the keys the lists are checked against stay the image's own
    assert "Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg" in out
    assert "[signed-by=/usr/share/keyrings/ros.asc]" in out
    # the wrapper's timeouts come last, after the image's own settings
    assert 'Acquire::http::Timeout "30";' in out


def test_the_image_sources_are_left_untouched(tmp_path: Path, etc: Path, cache: _Server) -> None:
    run(tmp_path, etc, SHOW, spec=f"url=http://127.0.0.1:{cache.port}\n")
    assert (etc / "sources.list.d" / "ubuntu.sources").read_text() == DEB822
    assert (etc / "sources.list.d" / "ros.list").read_text() == ONE_LINE
    assert not list(tmp_path.glob("ardt-apt.*")), "the work directory is removed"


def test_a_cache_that_is_down_means_direct(tmp_path: Path, etc: Path) -> None:
    result = run(tmp_path, etc, SHOW, spec=f"url=http://127.0.0.1:{_free_port()}\n")
    assert result.returncode == 0
    assert "does not answer" in result.stdout
    assert result.stdout.splitlines()[-1] == "via=direct"


def test_a_cache_that_hangs_means_direct_within_the_probe_timeout(
    tmp_path: Path, etc: Path, hung_cache: _Server
) -> None:
    start = time.monotonic()
    result = run(
        tmp_path, etc, SHOW, spec=f"url=http://127.0.0.1:{hung_cache.port}\nprobe_timeout=1\n"
    )
    assert time.monotonic() - start < 10
    assert result.returncode == 0
    assert result.stdout.splitlines()[-1] == "via=direct"


def test_a_step_that_fails_through_the_cache_runs_again_direct(
    tmp_path: Path, etc: Path, cache: _Server
) -> None:
    step = 'if [ -n "${APT_CONFIG:-}" ]; then echo through-cache; exit 100; fi; echo direct-ok\n'
    result = run(tmp_path, etc, step, spec=f"url=http://127.0.0.1:{cache.port}\n")
    assert result.returncode == 0
    assert result.stdout.index("through-cache") < result.stdout.index("running it again")
    assert result.stdout.splitlines()[-1] == "direct-ok"


def test_a_step_that_fails_direct_too_fails_the_build(
    tmp_path: Path, etc: Path, cache: _Server
) -> None:
    result = run(tmp_path, etc, "exit 7\n", spec=f"url=http://127.0.0.1:{cache.port}\n")
    assert result.returncode == 7


def test_a_step_that_fails_without_a_cache_keeps_its_exit_code(tmp_path: Path, etc: Path) -> None:
    assert run(tmp_path, etc, "exit 7\n", spec=None).returncode == 7


def test_an_https_cache_url_is_refused_and_the_step_runs_direct(tmp_path: Path, etc: Path) -> None:
    result = run(tmp_path, etc, SHOW, spec="url=https://cache.example\n")
    assert result.returncode == 0
    assert "must be an http:// URL" in result.stderr
    assert result.stdout.splitlines()[-1] == "via=direct"
