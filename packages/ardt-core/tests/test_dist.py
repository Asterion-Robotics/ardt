"""dist: the shared "where does ardt install from" resolution."""

from __future__ import annotations

import pytest

from ardt_core import dist
from ardt_core.config import ArdtConfig
from ardt_core.errors import ConfigError


class TestSubdirectory:
    def test_platform_packages(self) -> None:
        assert dist.subdirectory("ardt-core") == "packages/ardt-core"
        assert dist.subdirectory("ardt-pipelines") == "packages/ardt-pipelines"

    def test_everything_else_is_a_plugin(self) -> None:
        assert dist.subdirectory("ardt-ros-tasks") == "plugins/ardt-ros-tasks"
        assert dist.subdirectory("ardt-doc-tasks") == "plugins/ardt-doc-tasks"


class TestRequirement:
    def test_default_tracks_monorepo_head(self) -> None:
        assert dist.DistConfig().requirement("ardt-core") == (
            f"ardt-core @ {dist.ARDT_GIT}#subdirectory=packages/ardt-core"
        )

    def test_section_version_pins_every_monorepo_module(self) -> None:
        section = dist.DistConfig(version="v1.2.0")
        assert section.requirement("ardt-ros-tasks") == (
            f"ardt-ros-tasks @ {dist.ARDT_GIT}@v1.2.0#subdirectory=plugins/ardt-ros-tasks"
        )

    def test_module_version_overrides_section_version(self) -> None:
        section = dist.DistConfig(
            version="v1.2.0", modules={"ardt-ros-tasks": dist.ModulePin(version="v9")}
        )
        assert "@v9#" in section.requirement("ardt-ros-tasks")
        assert "@v1.2.0#" in section.requirement("ardt-core")

    def test_custom_monorepo_address(self) -> None:
        section = dist.DistConfig(git="git+https://mirror.example.com/ardt.git")
        assert section.requirement("ardt-core") == (
            "ardt-core @ git+https://mirror.example.com/ardt.git#subdirectory=packages/ardt-core"
        )

    def test_external_module_installs_from_its_repo_root(self) -> None:
        section = dist.DistConfig(
            version="v1.2.0",  # pins the monorepo — must NOT leak onto ardt-aos
            modules={"ardt-aos": dist.ModulePin(git="git+https://x.example.com/ardt-aos.git")},
        )
        assert section.requirement("ardt-aos") == (
            "ardt-aos @ git+https://x.example.com/ardt-aos.git"
        )

    def test_external_module_with_pin_and_subdirectory(self) -> None:
        pin = dist.ModulePin(
            git="git+https://x.example.com/mono.git", version="v3", subdirectory="pkgs/ardt-aos"
        )
        section = dist.DistConfig(modules={"ardt-aos": pin})
        assert section.requirement("ardt-aos") == (
            "ardt-aos @ git+https://x.example.com/mono.git@v3#subdirectory=pkgs/ardt-aos"
        )

    def test_requirements_preserve_module_order(self) -> None:
        assert [
            r.split(" @ ")[0]
            for r in dist.DistConfig().requirements(("ardt-core", "ardt-ros-tasks"))
        ] == ["ardt-core", "ardt-ros-tasks"]


class TestConfigSection:
    """The `ardt:` section is core-owned — parsed with the rest of ardt.yaml."""

    def test_defaults_when_absent(self) -> None:
        assert ArdtConfig().ardt == dist.DistConfig()

    def test_parses_from_config(self) -> None:
        cfg = ArdtConfig.model_validate(
            {"ardt": {"version": "v1.2.0", "modules": {"ardt-ros-tasks": {"version": "v9"}}}}
        )
        assert cfg.ardt.version == "v1.2.0"
        assert cfg.ardt.modules["ardt-ros-tasks"].version == "v9"

    def test_typos_are_errors(self) -> None:
        with pytest.raises(Exception) as excinfo:
            ArdtConfig.model_validate({"ardt": {"verison": "v1.2.0"}})
        assert "verison" in str(excinfo.value)

    def test_typo_through_load_is_a_config_error(self, tmp_path) -> None:
        from ardt_core import config as config_module

        (tmp_path / "ardt.yaml").write_text("ardt:\n  git: 42\n")
        with pytest.raises(ConfigError):
            config_module.load(tmp_path)
