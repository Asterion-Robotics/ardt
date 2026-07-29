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

"""docs-ci: config, version selection and site scaffolding — engine-free."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ardt_core.config import ArdtConfig
from ardt_core.context import Context
from ardt_core.testing import build_context, console_output, git, run_cli
from ardt_doc_pipelines import docs_ci

run = run_cli


class TestConfig:
    def test_defaults(self) -> None:
        cfg = ArdtConfig().section_as("pipelines", docs_ci.PipelinesSection).docs_ci
        assert cfg.builder == "python:3.12-slim"
        assert cfg.versions.branches == []
        assert cfg.versions.tags is None
        assert cfg.default is None

    def test_from_yaml(self) -> None:
        cfg = (
            ArdtConfig.model_validate(
                {"pipelines": {"docs_ci": {"versions": {"branches": ["main"], "tags": "v*"}}}}
            )
            .section_as("pipelines", docs_ci.PipelinesSection)
            .docs_ci
        )
        assert cfg.versions.branches == ["main"]
        assert cfg.versions.tags == "v*"


class TestBuilderModules:
    def test_defaults_to_the_task_plane_only(self) -> None:
        assert docs_ci.builder_modules(docs_ci.DocsCiConfig()) == docs_ci.ARDT_MODULES

    def test_extra_modules_append_after_the_base_set(self) -> None:
        extra = ["ardt-pipelines", "ardt-devcontainers"]
        cfg = docs_ci.DocsCiConfig.model_validate({"ardt_modules": extra})
        assert docs_ci.builder_modules(cfg) == (*docs_ci.ARDT_MODULES, *extra)

    def test_naming_a_base_module_does_not_duplicate_it(self) -> None:
        cfg = docs_ci.DocsCiConfig.model_validate({"ardt_modules": ["ardt-core"]})
        assert docs_ci.builder_modules(cfg) == docs_ci.ARDT_MODULES

    def test_pip_packages_default_to_none(self) -> None:
        assert docs_ci.DocsCiConfig().pip_packages == []

    def test_pip_packages_take_pep_508_strings(self) -> None:
        cfg = docs_ci.DocsCiConfig.model_validate(
            {"pip_packages": ["asterion-sphinx-style @ git+https://example.com/s.git@v1.2.0"]}
        )
        # Not routed through `ardt:` -- these are not ardt distributions.
        assert docs_ci.builder_modules(cfg) == docs_ci.ARDT_MODULES
        assert cfg.pip_packages[0].startswith("asterion-sphinx-style @ git+")

    def test_extras_refine_a_base_module_in_place(self) -> None:
        cfg = docs_ci.DocsCiConfig.model_validate({"ardt_modules": ["ardt-core[testing]"]})
        # one ardt-core, keeping its position -- not two competing installs.
        assert docs_ci.builder_modules(cfg) == ("ardt-core[testing]", "ardt-doc-tasks")


class TestStyleForwarding:
    """The pipeline reads `tasks.doc` without depending on ardt-doc-tasks."""

    def test_no_style_configured(self) -> None:
        section = ArdtConfig().section_as("tasks", docs_ci.TasksSection)
        assert section.doc.style == []

    def test_reads_the_task_planes_section(self) -> None:
        cfg = ArdtConfig.model_validate(
            {"tasks": {"doc": {"style": ["asterion_sphinx_style"], "strict": False}}}
        )
        section = cfg.section_as("tasks", docs_ci.TasksSection)
        # `strict` belongs to ardt-doc-tasks; extra="allow" keeps it from erroring.
        assert section.doc.style == ["asterion_sphinx_style"]

    def test_the_env_name_is_the_contract_with_the_task_plane(self) -> None:
        assert docs_ci.STYLE_ENV == "ARDT_DOC_STYLE"


class TestVersionSelection:
    def _ctx(self, repo: Path) -> Context:
        return Context.build(cwd=repo)

    def test_working_tree_name_prefers_tag_then_branch(self, repo: Path) -> None:
        ctx = self._ctx(repo)
        assert docs_ci.working_tree_name(ctx) == "main"
        git("tag", "v1.0.0", cwd=repo)
        assert docs_ci.working_tree_name(self._ctx(repo)) == "v1.0.0"

    def _with_doc_config(self, repo: Path) -> None:
        (repo / "doc").mkdir()
        (repo / "doc" / "conf.py").write_text("project = 'x'\n")
        git("add", "doc", cwd=repo)
        git("commit", "-qm", "doc config", cwd=repo)

    def test_historical_refs_filter_missing_and_current(self, repo: Path) -> None:
        self._with_doc_config(repo)
        git("tag", "v0.1.0", cwd=repo)
        git("branch", "stable", cwd=repo)
        # move HEAD past the tag so the working tree is `main`, not `v0.1.0`
        (repo / "next.txt").write_text("x\n")
        git("add", "next.txt", cwd=repo)
        git("commit", "-qm", "next", cwd=repo)
        ctx = self._ctx(repo)
        cfg = docs_ci.DocsCiConfig.model_validate(
            {"versions": {"branches": ["main", "stable", "ghost"], "tags": "v*"}}
        )
        # `main` is the working tree -> dropped; `ghost` does not exist -> warned+dropped.
        assert docs_ci.historical_refs(ctx, cfg) == ["stable", "v0.1.0"]

    def test_ref_without_doc_config_is_skipped_not_fatal(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Regression: one old tag without doc/conf.py aborted the entire site
        with a raw engine error that never named the ref."""
        git("tag", "v0.0.1", cwd=repo)  # tagged BEFORE doc config existed
        self._with_doc_config(repo)
        git("tag", "v0.1.0", cwd=repo)
        (repo / "next.txt").write_text("x\n")
        git("add", "next.txt", cwd=repo)
        git("commit", "-qm", "next", cwd=repo)
        ctx = self._ctx(repo)
        cfg = docs_ci.DocsCiConfig.model_validate({"versions": {"tags": "v*"}})
        assert docs_ci.historical_refs(ctx, cfg) == ["v0.1.0"]
        assert "`v0.0.1` has no doc/conf.py" in capsys.readouterr().err

    def test_site_name_collisions_warn_and_keep_the_first(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._with_doc_config(repo)
        git("branch", "feature/x", cwd=repo)
        git("branch", "feature-x", cwd=repo)
        (repo / "next.txt").write_text("x\n")
        git("add", "next.txt", cwd=repo)
        git("commit", "-qm", "next", cwd=repo)
        ctx = self._ctx(repo)
        cfg = docs_ci.DocsCiConfig.model_validate(
            {"versions": {"branches": ["feature/x", "feature-x"]}}
        )
        assert docs_ci.historical_refs(ctx, cfg) == ["feature/x"]
        assert "both map to site path `feature-x`" in capsys.readouterr().err

    def test_branch_with_slash_becomes_flat_site_name(self) -> None:
        assert docs_ci.site_name("feature/x") == "feature-x"


class TestSiteScaffolding:
    def test_versions_json_puts_default_first(self) -> None:
        data = json.loads(docs_ci.versions_json(["main", "v1.0.0"], "v1.0.0"))
        assert [entry["name"] for entry in data] == ["v1.0.0", "main"]
        assert data[0]["url"] == "v1.0.0/"  # relative: the site may live under a path prefix

    def test_redirect_targets_the_default(self) -> None:
        html = docs_ci.redirect_html("main")
        assert 'url=./main/"' in html
        assert 'href="./main/"' in html


class TestCliDiscovery:
    def test_pipe_list_shows_docs_ci(self, repo: Path) -> None:
        code, _, err = run(["pipe", "list"], repo)
        assert code == 0
        assert "docs-ci" in err

    def test_dry_run_needs_no_engine(self, repo: Path) -> None:
        code, _, err = run(["pipe", "run", "docs-ci", "--dry-run"], repo)
        assert code == 0
        assert "[dry-run] pipe run docs-ci" in err


class TestHistoricalRefsFailSoft:
    """A broken historical ref leaves the site short one version, not empty.

    Old refs are immutable: docs-ci builds them all inside ONE builder whose
    module set comes from the working tree, so a ref whose `conf.py` imports a
    since-renamed distribution can never be repaired. Failing the whole run over
    it would cost every *other* version of the site.
    """

    class _Built:
        """Stands in for the lazy `dagger.Directory` a build returns.

        `sync()` is the only place a lazy handle can fail: without forcing it,
        the error would not surface until the final export, which is the whole
        site failing rather than one version.
        """

        def __init__(self, boom: Exception | None = None) -> None:
            self.boom = boom
            self.synced = False

        async def sync(self) -> TestHistoricalRefsFailSoft._Built:
            self.synced = True
            if self.boom is not None:
                raise self.boom
            return self

    def test_a_good_ref_is_forced_and_kept(self, repo: Path) -> None:
        import asyncio

        ctx = build_context(repo)
        built = self._Built()
        result = asyncio.run(docs_ci._build_historical(ctx, "v1.0.0", built))
        assert result is built
        assert built.synced, "the build must be forced here, not deferred to export"

    def test_a_broken_ref_is_reported_and_dropped(self, repo: Path) -> None:
        import asyncio

        import dagger

        ctx = build_context(repo)
        boom = dagger.DaggerError("No module named 'ardt_dev'\nsecond line ignored")
        assert asyncio.run(docs_ci._build_historical(ctx, "v0.2.0", self._Built(boom))) is None
        err = console_output(ctx)
        assert "v0.2.0" in err
        assert "leaving it out of the site" in err
        assert "No module named 'ardt_dev'" in err
        assert "second line ignored" not in err  # first line only, like other reports

    def test_a_non_dagger_error_still_propagates(self, repo: Path) -> None:
        """Only build failures are tolerated; a bug in the pipeline must not be."""
        import asyncio

        ctx = build_context(repo)
        with pytest.raises(RuntimeError, match="not a build failure"):
            asyncio.run(
                docs_ci._build_historical(
                    ctx, "v1.0.0", self._Built(RuntimeError("not a build failure"))
                )
            )
