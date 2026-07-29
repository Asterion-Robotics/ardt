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

"""The devcontainer engine: host detection, render resolution, machine ownership.

All `unit`: no docker, no container. What matters here is that the *render* is
right — the parity rule (base image, ardt requirements, workspace path), the
three host shapes, and the refusal to clobber a file ardt did not write.

The engine is profile-agnostic, but a render needs *a* profile, so this suite
resolves the installed `ros2` one through the real `ardt.dev_profiles` entry
point (the uv workspace guarantees `ardt-ros-dev` is there, exactly as the root
`tests/` rely on the first-party plugins being installed). What that profile
*decides* — the apt sets, the C++ standard table — is asserted in its own suite;
what is asserted here is the engine's handling of whatever a profile says.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from ardt_core.config import ArdtConfig
from ardt_core.errors import ArdtError, ConfigError
from ardt_core.plugins import Plugin, Registry, discover
from ardt_core.testing import build_context
from ardt_devcontainers import host as host_module
from ardt_devcontainers import manifest as manifest_module
from ardt_devcontainers import render as render_module
from ardt_devcontainers.config import ci_builder, dev_config, ros_distro
from ardt_devcontainers.host import HostFacts
from ardt_devcontainers.profiles import profile, profiles

context = build_context

INSTALLED = discover()
"""Discovery as production does it — the engine's worked-example profile."""

ROS2 = profiles(INSTALLED)["ros2"]


def registry_of(**named: object) -> Registry:
    """A registry contributing exactly these ``ardt.dev_profiles`` entries.

    Nothing is deferred in it, so ``load_deferred`` is a no-op and the engine
    sees the objects as if a plugin's entry points had just loaded them.
    """
    plugin = Plugin(
        name="ardt-fake-dev",
        version="0",
        api=1,
        module="fake_dev",
        section="dev",
        dev_profiles=dict(named),
    )
    return Registry(plugins=[plugin], problems=[])


def plan(
    cfg: ArdtConfig,
    *,
    facts: HostFacts | None = None,
    ardt_source: str | None = None,
    registry: Registry | None = None,
) -> render_module.Render:
    return render_module.build(
        "demo",
        cfg,
        dev_config(cfg),
        registry=registry or INSTALLED,
        facts=facts or HostFacts(system="Linux"),
        ardt_source=ardt_source,
    )


LINUX = HostFacts(system="Linux", display=":1", dri=True, x11_socket=True)
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


def test_linux_mounts_the_x11_socket_when_present() -> None:
    host = host_module.detect(LINUX)
    assert host.kind == host_module.LINUX
    assert host.environment["DISPLAY"] == ":1"
    assert "/tmp/.X11-unix:/tmp/.X11-unix" in host.volumes
    assert "/dev/dri" in host.devices


def test_linux_without_an_x_socket_notes_it_instead_of_wiring_a_dead_display() -> None:
    """Regression: detect() used to probe the real /tmp/.X11-unix, so this
    branch was untestable and the test above failed on headless machines."""
    host = host_module.detect(HostFacts(system="Linux", display=":1"))
    assert not host.gui
    assert any("Wayland-only" in note for note in host.notes)


def test_macos_has_no_display_and_no_host_networking() -> None:
    host = host_module.detect(MAC)
    assert host.kind == host_module.MACOS
    assert not host.gui
    assert host.service == {}
    assert host.environment["ROS_AUTOMATIC_DISCOVERY_RANGE"] == "LOCALHOST"
    assert any("desktop-lite" in note for note in host.notes)


def test_gui_off_wires_no_display() -> None:
    assert not host_module.detect(WSL, gui=False).gui


def test_wsl2_repos_are_addressed_by_unc_path_because_vscode_runs_on_windows() -> None:
    facts = HostFacts(system="Linux", wsl_kernel=True, wsl_distro="Ubuntu")
    path = host_module.editor_host_path(Path("/home/me/dev/repo"), facts)
    assert path == r"\\wsl.localhost\Ubuntu\home\me\dev\repo"


def test_native_hosts_address_a_repo_the_way_the_shell_does() -> None:
    for facts in (LINUX, MAC):
        assert host_module.editor_host_path(Path("/home/me/repo"), facts) == "/home/me/repo"


def test_wsl2_without_a_distro_name_refuses_to_guess() -> None:
    facts = HostFacts(system="Linux", wsl_kernel=True)
    assert host_module.editor_host_path(Path("/home/me/repo"), facts) is None


def test_folder_uri_hex_encodes_the_host_path_and_keeps_the_container_path_plain() -> None:
    uri = host_module.folder_uri("/home/me/repo", "/ws/src")
    authority, _, container_path = uri.partition("/ws/src")
    assert container_path == ""
    encoded = authority.removeprefix("vscode-remote://dev-container+")
    assert bytes.fromhex(encoded).decode() == "/home/me/repo"
    assert uri.endswith("/ws/src")


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
    # The engine itself (postCreate hands over to `ardt dev bootstrap` in
    # there), then the profile's own distribution — without that one the
    # container could not resolve the profile it was rendered from.
    assert names[:3] == ["ardt-core", "ardt-devcontainers", "ardt-ros-dev"]
    # And what the CI recipe's build stage installs, from the same pin.
    assert {"ardt-core", "ardt-ros-tasks"} <= set(names)
    assert all("@v0.3.0#" in r for r in reqs)
    # The engine is a platform plane, the profile a theme plugin — and these
    # URLs are what a pinned repo pip-installs, so the paths have to be real.
    assert "#subdirectory=packages/ardt-devcontainers" in reqs[1]
    assert "#subdirectory=plugins/ardt-ros-dev" in reqs[2]


def test_local_checkout_replaces_the_pin_with_container_paths() -> None:
    reqs = plan(ArdtConfig(), ardt_source="../../ardt").requirements
    assert reqs[0] == "/opt/ardt-src/packages/ardt-core"
    assert "/opt/ardt-src/plugins/ardt-ros-tasks" in reqs


def test_extra_modules_are_appended() -> None:
    cfg = ArdtConfig.model_validate({"dev": {"ardt_modules": ["ardt-acme"]}})
    assert plan(cfg).requirements[-1].startswith("ardt-acme @ ")


# --- the rendered files -----------------------------------------------------


def test_dockerfile_pins_the_base_and_keeps_apt_usable() -> None:
    content = plan(ArdtConfig()).files[render_module.DOCKERFILE]
    assert "ARG BASE_IMAGE=ros:jazzy-ros-base" in content
    assert "ros-jazzy-rviz2" in content  # the distro token is resolved
    assert "@DISTRO@" not in content
    assert "ARDT_DEV_CONTAINER=1" in content


def test_the_apt_cache_is_enabled_after_the_installs_not_before() -> None:
    """Order is load-bearing: docker-clean must survive the build layers.

    Removed before them, every .deb the dev layer downloads (~1 GB) is baked
    into the image; left in place forever, the apt cache volume never fills.
    """
    content = plan(ArdtConfig()).files[render_module.DOCKERFILE]
    assert "docker-clean" in content and "Keep-Downloaded-Packages" in content
    assert content.index("apt-get install") < content.index("docker-clean")


def test_the_expensive_rqt_metapackage_is_not_pulled_in() -> None:
    content = plan(ArdtConfig()).files[render_module.DOCKERFILE]
    assert "rqt-common-plugins" not in content  # 398 packages, 1.45 GB
    assert "ros-jazzy-rqt-graph" in content


def test_extra_apt_packages_are_labelled_in_the_recipe() -> None:
    cfg = ArdtConfig.model_validate({"dev": {"apt_packages": ["libeigen3-dev"]}})
    content = cfg and plan(cfg).files[render_module.DOCKERFILE]
    assert "`# from dev.apt_packages in ardt.yaml`" in content
    assert "libeigen3-dev" in content


def test_claude_code_can_be_left_out() -> None:
    cfg = ArdtConfig.model_validate({"dev": {"claude_code": False}})
    content = plan(cfg).files[render_module.DOCKERFILE]
    assert "claude.ai/install.sh" not in content
    assert "CLAUDE_CONFIG_DIR" not in content
    assert "claude:/home/ubuntu/.claude" not in plan(cfg).files[render_module.COMPOSE]


def test_compose_isolates_the_colcon_output_dirs_in_one_volume() -> None:
    compose = yaml.safe_load(plan(ArdtConfig()).files[render_module.COMPOSE])
    volumes = compose["services"]["dev"]["volumes"]
    # The repo is one entry under the workspace's src/, and the colcon dirs
    # are the workspace root's — the canonical /ws tree, same as CI's.
    assert "..:/ws/src/demo:cached" in volumes
    mounts = [v for v in volumes if isinstance(v, dict) and v["source"] == "colcon"]
    assert [m["target"] for m in mounts] == ["/ws/build", "/ws/install", "/ws/log"]
    # The whole point: one volume, three subpaths — and they must stay distinct.
    # A Compose that silently drops `subpath` would alias all three (moby#47687).
    assert [m["volume"]["subpath"] for m in mounts] == ["build", "install", "log"]
    assert len({m["volume"]["subpath"] for m in mounts}) == 3
    assert set(compose["volumes"]) == {"colcon", "ardt-ccache", "ardt-apt-cache", "ardt-claude"}


def test_the_caches_are_shared_across_repos_and_not_compose_owned() -> None:
    """Fixed names (no project prefix) plus `external:` — 3 per machine, not 3 per repo."""
    compose = yaml.safe_load(plan(ArdtConfig()).files[render_module.COMPOSE])
    for name in ("ardt-ccache", "ardt-apt-cache", "ardt-claude"):
        # external: compose never removes them, so `down --purge` stays repo-scoped.
        assert compose["volumes"][name] == {"external": True}
    # The repo-scoped one is NOT external: compose creates and purges it.
    assert compose["volumes"]["colcon"] is None


def test_the_repo_volume_is_named_as_docker_will_name_it() -> None:
    """`ardt dev volumes` provisions subpaths by name, so the prefix must match."""
    built = plan(ArdtConfig())
    assert built.colcon_volume == "demo-dev_colcon"
    assert yaml.safe_load(built.files[render_module.COMPOSE])["name"] == "demo-dev"


def test_no_colcon_volume_to_provision_when_build_dirs_are_shared() -> None:
    cfg = ArdtConfig.model_validate({"dev": {"isolate_build_dirs": False}})
    assert plan(cfg).colcon_volume is None


def test_claude_volume_is_dropped_with_claude_code() -> None:
    cfg = ArdtConfig.model_validate({"dev": {"claude_code": False}})
    built = plan(cfg)
    assert "ardt-claude" not in built.shared_volumes
    assert "ardt-claude" not in yaml.safe_load(built.files[render_module.COMPOSE])["volumes"]
    assert built.shared_volumes == ("ardt-ccache", "ardt-apt-cache")


def test_compose_can_keep_the_build_dirs_in_the_bind_mount() -> None:
    cfg = ArdtConfig.model_validate({"dev": {"isolate_build_dirs": False}})
    compose = yaml.safe_load(plan(cfg).files[render_module.COMPOSE])
    assert not any("colcon-" in entry for entry in compose["services"]["dev"]["volumes"])


def test_published_dev_image_replaces_the_local_build() -> None:
    cfg = ArdtConfig.model_validate({"dev": {"image": "registry/ros2-dev@sha256:abc"}})
    service = yaml.safe_load(plan(cfg).files[render_module.COMPOSE])["services"]["dev"]
    assert service["image"] == "registry/ros2-dev@sha256:abc"
    assert "build" not in service


def test_host_overlay_is_a_separate_file_and_never_empty() -> None:
    overlay = yaml.safe_load(plan(ArdtConfig(), facts=MAC).files[render_module.COMPOSE_HOST])
    assert overlay["services"]["dev"]["environment"]["ROS_AUTOMATIC_DISCOVERY_RANGE"] == "LOCALHOST"


def test_devcontainer_json_carries_the_editor_config_so_repos_need_no_vscode_dir() -> None:
    text = plan(ArdtConfig()).files[render_module.DEVCONTAINER]
    data = json.loads("\n".join(line for line in text.splitlines() if not line.startswith("//")))
    # VS Code opens the workspace root; the repo sits at src/<project> in it.
    assert data["workspaceFolder"] == "/ws"
    # Compose files resolve next to devcontainer.json. initializeCommand runs
    # on the HOST from the repo checkout; postCreateCommand runs in the
    # container from workspaceFolder, so only the latter needs the src/ prefix.
    assert data["dockerComposeFile"] == ["compose.yaml", "compose.host.yaml"]
    assert data["initializeCommand"] == "bash .devcontainer/host-config.sh"
    assert data["postCreateCommand"] == "bash src/demo/.devcontainer/postCreate.sh"
    assert "llvm-vs-code-extensions.vscode-clangd" in data["customizations"]["vscode"]["extensions"]
    # The repo's .git is two levels below the opened folder — past VS Code's
    # default repository scan depth of 1.
    assert data["customizations"]["vscode"]["settings"]["git.repositoryScanMaxDepth"] == 2


# --- the .vscode/ half ------------------------------------------------------


def test_cpp_properties_is_rendered_at_the_repo_distro() -> None:
    cfg = ArdtConfig.model_validate({"tasks": {"ros": {"distro": "kilted"}}})
    text = plan(cfg).files[render_module.CPP_PROPERTIES]
    # Plain JSON, no comment header: cpptools flags comments here (#5885, #6132).
    entry = json.loads(text)["configurations"][0]
    assert entry["name"] == "ROS-kilted"
    assert entry["includePath"][0] == "/opt/ros/kilted/include/**"
    assert entry["compileCommands"] == "${workspaceFolder}/build/compile_commands.json"
    assert "@DISTRO@" not in text and "@CXX_STANDARD@" not in text


@pytest.mark.parametrize(
    ("distro", "standard"),
    [
        # Each distro's own "Code style and language versions" page.
        ("humble", "c++17"),
        ("jazzy", "c++17"),
        ("kilted", "c++17"),
        ("lyrical", "c++20"),
        ("rolling", "c++20"),
        # Not in the table: assume a future distro, not a forgotten past one.
        ("mystery", "c++20"),
    ],
)
def test_cpp_standard_follows_the_distro(distro: str, standard: str) -> None:
    cfg = ArdtConfig.model_validate({"tasks": {"ros": {"distro": distro}}})
    entry = json.loads(plan(cfg).files[render_module.CPP_PROPERTIES])["configurations"][0]
    assert entry["cppStandard"] == standard


def test_cpp_properties_points_at_what_compile_commands_writes() -> None:
    """`ardt dev compile-commands` merges into <root>/build; the two must agree."""
    entry = json.loads(plan(ArdtConfig()).files[render_module.CPP_PROPERTIES])["configurations"][0]
    assert entry["compileCommands"].endswith("/build/compile_commands.json")


def test_a_profile_without_cpp_renders_no_vscode_file() -> None:
    bare = replace(ROS2, name="bare", cpp_properties=None)
    cfg = ArdtConfig.model_validate({"dev": {"profile": "bare"}})
    assert render_module.CPP_PROPERTIES not in plan(cfg, registry=registry_of(bare=bare)).files
    assert render_module.CPP_PROPERTIES in plan(ArdtConfig()).files


def test_the_fixed_workspace_root_reaches_every_file_that_needs_it() -> None:
    files = plan(ArdtConfig()).files
    assert "/ws/install/setup.bash" in files[render_module.DOCKERFILE]
    assert "..:/ws/src/demo:cached" in files[render_module.COMPOSE]
    assert '"workspaceFolder": "/ws"' in files[render_module.DEVCONTAINER]


def test_workspace_folder_is_not_a_knob() -> None:
    """The workspace root is a fixed convention: the CI recipe hard-codes /ws,
    and a configurable dev-side path silently broke the parity rule."""
    cfg = ArdtConfig.model_validate({"dev": {"workspace_folder": "/opt/ws"}})
    with pytest.raises(ConfigError, match="workspace_folder"):
        dev_config(cfg)


def test_compose_build_paths_resolve_from_the_devcontainer_dir() -> None:
    """Regression: compose resolves `context` against its own directory and
    `dockerfile` against the context — `.devcontainer/Dockerfile` here composed
    to `.devcontainer/.devcontainer/Dockerfile` and broke every first build."""
    service = yaml.safe_load(plan(ArdtConfig()).files[render_module.COMPOSE])["services"]["dev"]
    assert service["build"] == {"context": ".", "dockerfile": "Dockerfile"}


def test_the_image_bakes_the_workspace_skeleton_user_owned() -> None:
    """dockerd creates missing mount parents as root; /ws and /ws/src must not be."""
    content = plan(ArdtConfig()).files[render_module.DOCKERFILE]
    assert "mkdir -p /ws/src" in content
    # The .vscode bridge: VS Code opens /ws, the repo's editor config lives in
    # src/<project>/.vscode — a relative symlink connects the two.
    assert "ln -sfn src/demo/.vscode /ws/.vscode" in content


def test_requirements_file_lists_each_module_once() -> None:
    text = plan(ArdtConfig()).files[render_module.REQUIREMENTS]
    lines = [line for line in text.splitlines() if not line.startswith("#")]
    # The profile names ardt-core too; a module is never installed twice.
    expected = {*render_module.BASE_MODULES, ROS2.distribution, *ROS2.ardt_modules}
    assert len(lines) == len(expected)


# --- the ardt.dev_profiles extension point ----------------------------------


def test_the_installed_profile_arrives_through_the_real_entry_point() -> None:
    """No import of any profile plugin anywhere in the engine: `ros2` is here
    because a distribution registered it, which is the whole point of the split."""
    assert "ardt_ros_dev" not in str(render_module.ENGINE_TEMPLATES)
    assert ROS2.name == "ros2"
    assert ROS2.distribution == "ardt-ros-dev"
    assert ROS2.templates_package == "ardt_ros_dev.templates"


def test_unknown_profile_names_the_ones_that_exist() -> None:
    with pytest.raises(ArdtError, match="unknown dev profile") as excinfo:
        profile("ros1", INSTALLED)
    assert "ros2" in str(excinfo.value.hint)


def test_no_profile_installed_says_what_to_install() -> None:
    """A laptop with the engine but no profile plugin must get a pointer, not
    an empty list — the two are separately installable now."""
    with pytest.raises(ArdtError, match="unknown dev profile") as excinfo:
        profile("ros2", Registry(plugins=[], problems=[]))
    assert "ardt-ros-dev" in str(excinfo.value.hint)


def test_an_entry_point_aimed_at_the_wrong_object_is_refused_loudly() -> None:
    """Core cannot type-check this (it must not depend on the engine), so the
    engine does it on consumption — and says which plugin to blame."""
    with pytest.raises(ArdtError, match="must point at a Profile"):
        profiles(registry_of(ros2="not a profile"))


def test_two_plugins_claiming_one_profile_name_is_an_error() -> None:
    """`dev.profile: ros2` must never be ambiguous — same rule as pipelines."""
    other = Plugin(name="ardt-other-dev", version="0", api=1, module="other", section="dev")
    other.dev_profiles["ros2"] = replace(ROS2, summary="a different ros2")
    clashing = registry_of(ros2=ROS2)
    clashing.plugins.append(other)
    with pytest.raises(ArdtError, match="provided by both"):
        profiles(clashing)


def test_a_profile_brings_its_own_dockerfile_template() -> None:
    """The engine resolves the recipe from the profile's package, not its own:
    a second profile ships its template without touching this distribution."""
    bare = replace(ROS2, name="bare", templates_package="ardt_devcontainers.templates")
    cfg = ArdtConfig.model_validate({"dev": {"profile": "bare"}})
    # postCreate.sh.tmpl is not a Dockerfile, but it is a template only the
    # engine ships: rendering it proves the anchor, not the content, is what moved.
    rendered = plan(
        cfg, registry=registry_of(bare=replace(bare, dockerfile="postCreate.sh.tmpl"))
    ).files[render_module.DOCKERFILE]
    assert "ardt dev bootstrap" in rendered


# --- machine ownership ------------------------------------------------------


def test_sync_writes_the_render_and_gitignores_it(repo: Path) -> None:
    ctx = context(repo)
    result = manifest_module.write(repo, plan(ctx.cfg))
    assert manifest_module.ensure_gitignored(repo) == list(manifest_module.GITIGNORE_ENTRIES)
    assert (repo / render_module.DOCKERFILE).is_file()
    # The .vscode/ half lands outside .devcontainer/, and is ignored on its own.
    assert (repo / render_module.CPP_PROPERTIES).is_file()
    ignored = (repo / ".gitignore").read_text()
    assert ".devcontainer/" in ignored and ".vscode/c_cpp_properties.json" in ignored
    assert set(result.written) >= {
        render_module.DOCKERFILE,
        render_module.COMPOSE,
        render_module.DEVCONTAINER,
        render_module.CPP_PROPERTIES,
    }
    assert (repo / render_module.POST_CREATE).stat().st_mode & 0o111


def test_gitignore_entries_are_added_once(repo: Path) -> None:
    assert manifest_module.ensure_gitignored(repo) == list(manifest_module.GITIGNORE_ENTRIES)
    assert manifest_module.ensure_gitignored(repo) == []
    assert manifest_module.is_gitignored(repo)


def test_a_partially_ignored_repo_gets_only_what_it_lacks(repo: Path) -> None:
    """The .vscode/ entry is new; a repo synced by an older ardt-dev has only the first."""
    (repo / ".gitignore").write_text(".devcontainer/\n")
    assert manifest_module.ensure_gitignored(repo) == [render_module.CPP_PROPERTIES]
    assert (repo / ".gitignore").read_text().count(".devcontainer/") == 1


def test_a_pre_vscode_manifest_is_read_not_treated_as_hand_edits(repo: Path) -> None:
    """Older ardt-dev keyed the manifest by bare file name, not by repo path."""
    ctx = context(repo)
    manifest_module.write(repo, plan(ctx.cfg))
    path = repo / manifest_module.MANIFEST
    data = json.loads(path.read_text())
    data["generated"] = {Path(k).name: v for k, v in data["generated"].items()}
    path.write_text(json.dumps(data))
    # Same files on disk, legacy keys: nothing is a conflict, nothing is stale.
    state = manifest_module.audit(repo, plan(ctx.cfg))
    assert state.conflicts == []
    assert render_module.DOCKERFILE in state.unchanged


def test_a_second_sync_is_a_no_op(repo: Path) -> None:
    ctx = context(repo)
    manifest_module.write(repo, plan(ctx.cfg))
    again = manifest_module.write(repo, plan(ctx.cfg))
    assert again.written == []
    assert render_module.DOCKERFILE in again.unchanged


def test_a_hand_edit_is_refused_not_silently_kept(repo: Path) -> None:
    ctx = context(repo)
    manifest_module.write(repo, plan(ctx.cfg))
    (repo / render_module.DOCKERFILE).write_text("FROM scratch\n")
    with pytest.raises(ArdtError, match="did not generate"):
        manifest_module.write(repo, plan(ctx.cfg))
    assert manifest_module.audit(repo, plan(ctx.cfg)).conflicts == [render_module.DOCKERFILE]


def test_force_overwrites_a_hand_edit(repo: Path) -> None:
    ctx = context(repo)
    manifest_module.write(repo, plan(ctx.cfg))
    (repo / render_module.DOCKERFILE).write_text("FROM scratch\n")
    result = manifest_module.write(repo, plan(ctx.cfg), force=True)
    assert result.conflicts == []
    assert "FROM scratch" not in (repo / render_module.DOCKERFILE).read_text()


def test_a_stale_render_of_ours_refreshes_without_force(repo: Path) -> None:
    ctx = context(repo)
    manifest_module.write(repo, plan(ctx.cfg))
    # Same content ardt wrote, but from an older tool: still ours to replace.
    stale = plan(ctx.cfg, facts=MAC)
    result = manifest_module.write(repo, stale)
    assert render_module.COMPOSE_HOST in result.written


def test_host_config_rewrites_only_the_overlay(repo: Path) -> None:
    ctx = context(repo)
    linux_plan = plan(ctx.cfg, facts=LINUX)
    manifest_module.write(repo, linux_plan)
    mac_plan = plan(ctx.cfg, facts=MAC)
    result = manifest_module.write(repo, mac_plan, force=True, only=mac_plan.host_files)
    assert result.written == [render_module.COMPOSE_HOST]
    overlay = (repo / render_module.COMPOSE_HOST).read_text()
    assert "LOCALHOST" in overlay
    # The portable half is untouched by a host switch.
    assert "network_mode" not in (repo / render_module.COMPOSE).read_text()


def test_manifest_records_what_the_render_was_resolved_from(repo: Path) -> None:
    ctx = context(repo)
    manifest_module.write(repo, plan(ctx.cfg, facts=WSL, ardt_source="../../ardt"))
    data = json.loads((repo / manifest_module.MANIFEST).read_text())
    assert data["profile"] == "ros2"
    assert data["host"] == "wsl2"
    assert data["ardt_source"] == "../../ardt"
    assert data["generated"][render_module.DOCKERFILE].startswith("sha256:")
