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

"""install.sh module-set and ref resolution, exercised with a stubbed uv.

The stub records the argv of the one `uv tool install` call; the module set is
read back from the requirement strings. The environment is built from scratch
so the host's CI/ARDT_* variables cannot leak into the scenarios.
"""

from __future__ import annotations

import stat
import subprocess
from pathlib import Path

INSTALL_SH = Path(__file__).resolve().parents[1] / "install.sh"

UV_STUB = '#!/bin/sh\nprintf \'%s\\n\' "$@" > "$STUB_LOG"\n'
# Satisfies the trailing `command -v ardt` / `ardt --version` checks.
ARDT_STUB = '#!/bin/sh\necho "ardt, version 0.0.0-stub"\n'


def run_install(
    tmp_path: Path,
    *,
    ci: bool,
    ardt_yaml: str | None = None,
    env_modules: str | None = None,
) -> list[str]:
    """Run install.sh in a scratch dir; return the installed module names."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    log = tmp_path / "uv-args.txt"
    for name, body in (("uv", UV_STUB), ("ardt", ARDT_STUB)):
        exe = bin_dir / name
        exe.write_text(body)
        exe.chmod(exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    if ardt_yaml is not None:
        (tmp_path / "ardt.yaml").write_text(ardt_yaml)
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path), "STUB_LOG": str(log)}
    if ci:
        env["CI"] = "true"
    if env_modules is not None:
        env["ARDT_MODULES"] = env_modules
    subprocess.run(
        ["bash", str(INSTALL_SH)], cwd=tmp_path, env=env, check=True, capture_output=True
    )
    return [line.split(" @ ")[0] for line in log.read_text().splitlines() if " @ " in line]


BUNDLE = ["ardt-core", "ardt-pipelines", "ardt-ros-tasks", "ardt-ros-pipelines"]


def test_workstation_bundle_adds_dev(tmp_path: Path) -> None:
    assert run_install(tmp_path, ci=False) == [*BUNDLE, "ardt-dev"]


def test_ci_bundle_has_no_dev(tmp_path: Path) -> None:
    assert run_install(tmp_path, ci=True) == BUNDLE


def test_extras_flow_style(tmp_path: Path) -> None:
    yaml = "ardt:\n  version: v0.1.3\n  install_extras: [ardt-doc-tasks, ardt-doc-pipelines]\n"
    assert run_install(tmp_path, ci=True, ardt_yaml=yaml) == [
        *BUNDLE,
        "ardt-doc-tasks",
        "ardt-doc-pipelines",
    ]


def test_skip_block_style(tmp_path: Path) -> None:
    yaml = "ardt:\n  install_skip:\n    - ardt-ros-pipelines\n    - ardt-ros-tasks\n"
    assert run_install(tmp_path, ci=True, ardt_yaml=yaml) == ["ardt-core", "ardt-pipelines"]


def test_extras_and_skip_compose(tmp_path: Path) -> None:
    yaml = (
        "ardt:\n"
        "  version: v0.1.3\n"
        "  install_extras: [ardt-acme]  # trailing comment\n"
        "  install_skip: [ardt-dev]\n"
    )
    # Workstation context: the skip prunes ardt-dev from the bundle.
    assert run_install(tmp_path, ci=False, ardt_yaml=yaml) == [*BUNDLE, "ardt-acme"]


def test_extra_already_in_bundle_is_not_duplicated(tmp_path: Path) -> None:
    yaml = "ardt:\n  install_extras: [ardt-core]\n"
    assert run_install(tmp_path, ci=True, ardt_yaml=yaml) == BUNDLE


def test_env_overrides_config_and_bundle(tmp_path: Path) -> None:
    yaml = "ardt:\n  install_extras: [ardt-doc-tasks]\n  install_skip: [ardt-core]\n"
    assert run_install(tmp_path, ci=True, ardt_yaml=yaml, env_modules="ardt-core") == ["ardt-core"]
