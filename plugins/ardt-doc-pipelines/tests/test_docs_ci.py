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

import contextlib
import io
import json
from pathlib import Path

from ardt_core.config import ArdtConfig
from ardt_core.context import Context
from ardt_core.testing import git
from ardt_doc_pipelines import docs_ci


def run(args: list[str], cwd: Path) -> tuple[int, str, str]:
    from ardt_core.cli import main

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(["-C", str(cwd), *args])
    return code, out.getvalue(), err.getvalue()


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
        cfg = docs_ci.DocsCiConfig.model_validate({"ardt_modules": ["ardt-pipelines", "ardt-dev"]})
        assert docs_ci.builder_modules(cfg) == (*docs_ci.ARDT_MODULES, "ardt-pipelines", "ardt-dev")

    def test_naming_a_base_module_does_not_duplicate_it(self) -> None:
        cfg = docs_ci.DocsCiConfig.model_validate({"ardt_modules": ["ardt-core"]})
        assert docs_ci.builder_modules(cfg) == docs_ci.ARDT_MODULES

    def test_extras_refine_a_base_module_in_place(self) -> None:
        cfg = docs_ci.DocsCiConfig.model_validate({"ardt_modules": ["ardt-core[testing]"]})
        # one ardt-core, keeping its position -- not two competing installs.
        assert docs_ci.builder_modules(cfg) == ("ardt-core[testing]", "ardt-doc-tasks")


class TestVersionSelection:
    def _ctx(self, repo: Path) -> Context:
        return Context.build(cwd=repo)

    def test_working_tree_name_prefers_tag_then_branch(self, repo: Path) -> None:
        ctx = self._ctx(repo)
        assert docs_ci.working_tree_name(ctx) == "main"
        git("tag", "v1.0.0", cwd=repo)
        assert docs_ci.working_tree_name(self._ctx(repo)) == "v1.0.0"

    def test_historical_refs_filter_missing_and_current(self, repo: Path) -> None:
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

    def test_branch_with_slash_becomes_flat_site_name(self) -> None:
        assert docs_ci.site_name("feature/x") == "feature-x"


class TestSiteScaffolding:
    def test_versions_json_puts_default_first(self) -> None:
        data = json.loads(docs_ci.versions_json(["main", "v1.0.0"], "v1.0.0"))
        assert [entry["name"] for entry in data] == ["v1.0.0", "main"]
        assert data[0]["url"] == "/v1.0.0/"

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
