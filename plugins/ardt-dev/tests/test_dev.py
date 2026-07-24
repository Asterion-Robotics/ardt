"""ardt-dev: host detection, render resolution, and the machine-owned guarantees.

All `unit`: no docker, no container. What matters here is that the *render* is
right — the parity rule (base image, ardt requirements, workspace path), the
three host shapes, and the refusal to clobber a file ardt did not write.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
import yaml

from ardt_core.config import ArdtConfig
from ardt_core.context import Context
from ardt_core.errors import ArdtError
from ardt_core.plugins import Registry
from ardt_dev import host as host_module
from ardt_dev import render as render_module
from ardt_dev.config import DEVCONTAINER_DIR, ci_builder, dev_config, ros_distro
from ardt_dev.host import HostFacts
from ardt_dev.profiles import ROS2, profile


def context(root: Path, **kwargs: object) -> Context:
    ctx = Context.build(cwd=root, registry=Registry(plugins=[], problems=[]), **kwargs)  # type: ignore[arg-type]
    ctx.console._stream = io.StringIO()  # capture; keep it plain
    ctx.console._plain = True
    return ctx


def plan(
    cfg: ArdtConfig,
    *,
    facts: HostFacts | None = None,
    ardt_source: str | None = None,
) -> render_module.Render:
    return render_module.build(
        "demo",
        cfg,
        dev_config(cfg),
        facts=facts or HostFacts(system="Linux"),
        ardt_source=ardt_source,
    )


LINUX = HostFacts(system="Linux", display=":1", dri=True)
WSL = HostFacts(system="Linux", wsl_kernel=True, wslg=True, dxg=True, display=":0")
MAC = HostFacts(system="Darwin")


# --- host detection ---------------------------------------------------------


def test_wsl2_wires_wslg_sockets_and_gpu() -> None:
    host = host_module.detect(WSL)
    assert host.kind == host_module.WSL2
    assert host.environment["WAYLAND_DISPLAY"] == "wayland-0"
    assert "/mnt/wslg/.X11-unix:/tmp/.X11-unix" in host.volumes
    assert host.devices == ["/dev/dxg"]
    assert host.service == {"network_mode": "host", "ipc": "host"}
    assert host.gui


def test_wsl2_without_wslg_says_so_instead_of_mounting_nothing() -> None:
    host = host_module.detect(HostFacts(system="Linux", wsl_kernel=True))
    assert not host.gui
    assert any("wsl --update" in note for note in host.notes)


def test_linux_mounts_the_x11_socket_when_present(tmp_path: Path) -> None:
    host = host_module.detect(LINUX)
    assert host.kind == host_module.LINUX
    assert host.environment["DISPLAY"] == ":1"
    assert "/dev/dri" in host.devices


def test_macos_has_no_display_and_no_host_networking() -> None:
    host = host_module.detect(MAC)
    assert host.kind == host_module.MACOS
    assert not host.gui
    assert host.service == {}
    assert host.environment["ROS_AUTOMATIC_DISCOVERY_RANGE"] == "LOCALHOST"
    assert any("desktop-lite" in note for note in host.notes)


def test_gui_off_wires_no_display() -> None:
    assert not host_module.detect(WSL, gui=False).gui


def test_unknown_host_is_reported_not_guessed() -> None:
    host = host_module.detect(HostFacts(system="Windows"))
    assert host.kind == host_module.UNKNOWN
    assert host.notes


# --- the parity rule --------------------------------------------------------


def test_base_image_follows_the_ci_builder() -> None:
    cfg = ArdtConfig.model_validate({"pipelines": {"ros_ci": {"builder": "ros:kilted-ros-base"}}})
    assert ci_builder(cfg) == "ros:kilted-ros-base"
    assert plan(cfg).base_image == "ros:kilted-ros-base"


def test_base_image_falls_back_to_the_profile_default_at_the_repo_distro() -> None:
    cfg = ArdtConfig.model_validate({"tasks": {"ros": {"distro": "kilted"}}})
    assert ros_distro(cfg) == "kilted"
    assert plan(cfg).base_image == "ros:kilted-ros-base"


def test_dev_base_image_overrides_everything() -> None:
    cfg = ArdtConfig.model_validate(
        {
            "dev": {"base_image": "internal/ros2-dev:2026-07"},
            "pipelines": {"ros_ci": {"builder": "ros:jazzy-ros-base"}},
        }
    )
    assert plan(cfg).base_image == "internal/ros2-dev:2026-07"


def test_malformed_ci_section_is_ignored_not_validated_here() -> None:
    cfg = ArdtConfig.model_validate({"pipelines": {"ros_ci": "nonsense"}})
    assert ci_builder(cfg) is None


def test_requirements_come_from_the_ardt_pin() -> None:
    cfg = ArdtConfig.model_validate({"ardt": {"version": "v0.3.0"}})
    reqs = plan(cfg).requirements
    assert reqs[0] == (
        "ardt-core @ git+https://github.com/Asterion-Robotics/ardt.git"
        "@v0.3.0#subdirectory=packages/ardt-core"
    )
    names = [r.split(" @ ")[0] for r in reqs]
    # ardt-dev itself: postCreate hands over to `ardt dev bootstrap` in there.
    assert names[:2] == ["ardt-core", "ardt-dev"]
    # And what the CI recipe's build stage installs, from the same pin.
    assert {"ardt-core", "ardt-ros-tasks"} <= set(names)
    assert all("@v0.3.0#" in r for r in reqs)


def test_local_checkout_replaces_the_pin_with_container_paths() -> None:
    reqs = plan(ArdtConfig(), ardt_source="../../ardt").requirements
    assert reqs[0] == "/opt/ardt-src/packages/ardt-core"
    assert "/opt/ardt-src/plugins/ardt-ros-tasks" in reqs


def test_extra_modules_are_appended() -> None:
    cfg = ArdtConfig.model_validate({"dev": {"ardt_modules": ["ardt-aos"]}})
    assert plan(cfg).requirements[-1].startswith("ardt-aos @ ")


# --- the rendered files -----------------------------------------------------


def test_dockerfile_pins_the_base_and_keeps_apt_usable() -> None:
    content = plan(ArdtConfig()).files["Dockerfile"]
    assert "ARG BASE_IMAGE=ros:jazzy-ros-base" in content
    assert "ros-jazzy-rviz2" in content  # the distro token is resolved
    assert "@DISTRO@" not in content
    assert "Keep-Downloaded-Packages" in content
    assert "ARDT_DEV_CONTAINER=1" in content


def test_extra_apt_packages_are_labelled_in_the_recipe() -> None:
    cfg = ArdtConfig.model_validate({"dev": {"apt_packages": ["libeigen3-dev"]}})
    content = cfg and plan(cfg).files["Dockerfile"]
    assert "`# from dev.apt_packages in ardt.yaml`" in content
    assert "libeigen3-dev" in content


def test_claude_code_can_be_left_out() -> None:
    cfg = ArdtConfig.model_validate({"dev": {"claude_code": False}})
    content = plan(cfg).files["Dockerfile"]
    assert "claude.ai/install.sh" not in content
    assert "CLAUDE_CONFIG_DIR" not in content
    assert "claude:/home/ubuntu/.claude" not in plan(cfg).files["compose.yaml"]


def test_compose_isolates_the_colcon_output_dirs() -> None:
    compose = yaml.safe_load(plan(ArdtConfig()).files["compose.yaml"])
    volumes = compose["services"]["dev"]["volumes"]
    assert "..:/ws/src:cached" in volumes
    assert "colcon-build:/ws/src/build" in volumes
    assert set(compose["volumes"]) >= {"colcon-build", "ccache", "apt-cache"}


def test_compose_can_keep_the_build_dirs_in_the_bind_mount() -> None:
    cfg = ArdtConfig.model_validate({"dev": {"isolate_build_dirs": False}})
    compose = yaml.safe_load(plan(cfg).files["compose.yaml"])
    assert not any("colcon-" in entry for entry in compose["services"]["dev"]["volumes"])


def test_published_dev_image_replaces_the_local_build() -> None:
    cfg = ArdtConfig.model_validate({"dev": {"image": "registry/ros2-dev@sha256:abc"}})
    service = yaml.safe_load(plan(cfg).files["compose.yaml"])["services"]["dev"]
    assert service["image"] == "registry/ros2-dev@sha256:abc"
    assert "build" not in service


def test_host_overlay_is_a_separate_file_and_never_empty() -> None:
    overlay = yaml.safe_load(plan(ArdtConfig(), facts=MAC).files["compose.host.yaml"])
    assert overlay["services"]["dev"]["environment"]["ROS_AUTOMATIC_DISCOVERY_RANGE"] == "LOCALHOST"


def test_devcontainer_json_carries_the_editor_config_so_repos_need_no_vscode_dir() -> None:
    text = plan(ArdtConfig()).files["devcontainer.json"]
    data = json.loads("\n".join(line for line in text.splitlines() if not line.startswith("//")))
    assert data["workspaceFolder"] == "/ws/src"
    assert data["dockerComposeFile"] == ["compose.yaml", "compose.host.yaml"]
    assert data["initializeCommand"] == "bash .devcontainer/host-config.sh"
    assert "llvm-vs-code-extensions.vscode-clangd" in data["customizations"]["vscode"]["extensions"]


def test_workspace_folder_reaches_every_file_that_needs_it() -> None:
    cfg = ArdtConfig.model_validate({"dev": {"workspace_folder": "/opt/ws"}})
    files = plan(cfg).files
    assert "/opt/ws/install/setup.bash" in files["Dockerfile"]
    assert "..:/opt/ws:cached" in files["compose.yaml"]
    assert '"workspaceFolder": "/opt/ws"' in files["devcontainer.json"]


def test_requirements_file_lists_each_module_once() -> None:
    text = plan(ArdtConfig()).files["ardt-requirements.txt"]
    lines = [line for line in text.splitlines() if not line.startswith("#")]
    # The profile names ardt-core too; a module is never installed twice.
    assert len(lines) == len({*render_module.BASE_MODULES, *ROS2.ardt_modules})


def test_unknown_profile_names_the_ones_that_exist() -> None:
    with pytest.raises(ArdtError, match="unknown dev profile"):
        profile("ros1")


# --- machine ownership ------------------------------------------------------


def test_sync_writes_the_render_and_gitignores_it(repo: Path) -> None:
    ctx = context(repo)
    result = render_module.write(repo, plan(ctx.cfg))
    assert render_module.ensure_gitignored(repo) is True
    assert (repo / DEVCONTAINER_DIR / "Dockerfile").is_file()
    assert ".devcontainer/" in (repo / ".gitignore").read_text()
    assert set(result.written) >= {"Dockerfile", "compose.yaml", "devcontainer.json"}
    assert (repo / DEVCONTAINER_DIR / "postCreate.sh").stat().st_mode & 0o111


def test_gitignore_entry_is_added_once(repo: Path) -> None:
    assert render_module.ensure_gitignored(repo) is True
    assert render_module.ensure_gitignored(repo) is False
    assert render_module.is_gitignored(repo)


def test_a_second_sync_is_a_no_op(repo: Path) -> None:
    ctx = context(repo)
    render_module.write(repo, plan(ctx.cfg))
    again = render_module.write(repo, plan(ctx.cfg))
    assert again.written == []
    assert "Dockerfile" in again.unchanged


def test_a_hand_edit_is_refused_not_silently_kept(repo: Path) -> None:
    ctx = context(repo)
    render_module.write(repo, plan(ctx.cfg))
    (repo / DEVCONTAINER_DIR / "Dockerfile").write_text("FROM scratch\n")
    with pytest.raises(ArdtError, match="did not generate"):
        render_module.write(repo, plan(ctx.cfg))
    assert render_module.audit(repo, plan(ctx.cfg)).conflicts == ["Dockerfile"]


def test_force_overwrites_a_hand_edit(repo: Path) -> None:
    ctx = context(repo)
    render_module.write(repo, plan(ctx.cfg))
    (repo / DEVCONTAINER_DIR / "Dockerfile").write_text("FROM scratch\n")
    result = render_module.write(repo, plan(ctx.cfg), force=True)
    assert result.conflicts == []
    assert "FROM scratch" not in (repo / DEVCONTAINER_DIR / "Dockerfile").read_text()


def test_a_stale_render_of_ours_refreshes_without_force(repo: Path) -> None:
    ctx = context(repo)
    render_module.write(repo, plan(ctx.cfg))
    # Same content ardt wrote, but from an older tool: still ours to replace.
    stale = plan(ctx.cfg, facts=MAC)
    result = render_module.write(repo, stale)
    assert "compose.host.yaml" in result.written


def test_host_config_rewrites_only_the_overlay(repo: Path) -> None:
    ctx = context(repo)
    linux_plan = plan(ctx.cfg, facts=LINUX)
    render_module.write(repo, linux_plan)
    mac_plan = plan(ctx.cfg, facts=MAC)
    result = render_module.write(repo, mac_plan, force=True, only=mac_plan.host_files)
    assert result.written == ["compose.host.yaml"]
    overlay = (repo / DEVCONTAINER_DIR / "compose.host.yaml").read_text()
    assert "LOCALHOST" in overlay
    # The portable half is untouched by a host switch.
    assert "network_mode" not in (repo / DEVCONTAINER_DIR / "compose.yaml").read_text()


def test_manifest_records_what_the_render_was_resolved_from(repo: Path) -> None:
    ctx = context(repo)
    render_module.write(repo, plan(ctx.cfg, facts=WSL, ardt_source="../../ardt"))
    data = json.loads((repo / DEVCONTAINER_DIR / render_module.MANIFEST).read_text())
    assert data["profile"] == "ros2"
    assert data["host"] == "wsl2"
    assert data["ardt_source"] == "../../ardt"
    assert data["generated"]["Dockerfile"].startswith("sha256:")
