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

"""The pipeline registry, engine-free: decorator, param binding, collection.

Nothing here opens a Dagger connection. The engine path is covered
by the docker-marked test in the workspace-level tests/.
"""

from __future__ import annotations

import types

import pytest

from ardt_core.errors import ArdtError
from ardt_pipelines import PipelineDef, collect, pipeline


async def _noop(ctx, dag) -> None:  # pragma: no cover - never executed
    pass


def test_decorator_returns_a_definition() -> None:
    definition = pipeline(name="demo", doc="a demo")(_noop)
    assert isinstance(definition, PipelineDef)
    assert definition.name == "demo"
    assert definition.doc == "a demo"
    assert definition.params == ()


def test_docstring_is_the_fallback_doc() -> None:
    async def documented(ctx, dag) -> None:
        """From the docstring."""

    assert pipeline(name="d")(documented).doc == "From the docstring."


def test_params_are_introspected() -> None:
    async def f(ctx, dag, count: int = 2, tags: list[str] = ()) -> None: ...  # type: ignore[assignment]

    definition = pipeline(name="p")(f)
    names = [p.name for p in definition.params]
    assert names == ["count", "tags"]
    assert definition.params[0].annotation == "int"
    assert definition.params[0].required is False


def test_fewer_than_two_parameters_is_rejected() -> None:
    async def bad(ctx) -> None: ...

    with pytest.raises(ArdtError):
        pipeline(name="bad")(bad)


def test_unsupported_annotation_is_rejected() -> None:
    async def bad(ctx, dag, weird: dict = ()) -> None: ...  # type: ignore[assignment]

    with pytest.raises(ArdtError):
        pipeline(name="bad")(bad)


class TestBinding:
    def _definition(self) -> PipelineDef:
        async def f(
            ctx,
            dag,
            count: int = 1,
            ratio: float = 0.5,
            verbose: bool = False,
            tags: list[str] = (),  # type: ignore[assignment]
            label: str = "x",
        ) -> None: ...

        return pipeline(name="bind")(f)

    def test_defaults_mean_empty_binding(self) -> None:
        assert self._definition().bind({}) == {}

    def test_coercions(self) -> None:
        bound = self._definition().bind(
            {"count": "3", "ratio": "0.25", "verbose": "true", "tags": "a, b,c", "label": "y"}
        )
        assert bound == {
            "count": 3,
            "ratio": 0.25,
            "verbose": True,
            "tags": ["a", "b", "c"],
            "label": "y",
        }

    @pytest.mark.parametrize("raw", ["0", "false", "no", "off"])
    def test_bool_falsy_forms(self, raw: str) -> None:
        assert self._definition().bind({"verbose": raw})["verbose"] is False

    def test_bad_int_is_a_clean_error(self) -> None:
        with pytest.raises(ArdtError, match="not a valid int"):
            self._definition().bind({"count": "many"})

    def test_bad_bool_is_a_clean_error(self) -> None:
        with pytest.raises(ArdtError, match="not a valid bool"):
            self._definition().bind({"verbose": "maybe"})

    def test_unknown_arg_is_a_clean_error(self) -> None:
        with pytest.raises(ArdtError, match="no parameter"):
            self._definition().bind({"nope": "1"})

    def test_missing_required_arg(self) -> None:
        async def f(ctx, dag, needed: str) -> None: ...

        definition = pipeline(name="req")(f)
        with pytest.raises(ArdtError, match="requires --arg needed"):
            definition.bind({})
        assert definition.bind({"needed": "v"}) == {"needed": "v"}


class TestCollect:
    def _module(self, name: str, *defs: PipelineDef) -> types.ModuleType:
        module = types.ModuleType(name)
        for i, d in enumerate(defs):
            setattr(module, f"p{i}", d)
        return module

    def test_collects_across_modules(self) -> None:
        a = pipeline(name="a")(_noop)
        b = pipeline(name="b")(_noop)
        found = collect({"m1": self._module("m1", a), "m2": self._module("m2", b)})
        assert set(found) == {"a", "b"}

    def test_duplicate_name_is_an_error(self) -> None:
        first = pipeline(name="dup")(_noop)
        second = pipeline(name="dup")(_noop)
        with pytest.raises(ArdtError, match="two plugins"):
            collect({"m1": self._module("m1", first), "m2": self._module("m2", second)})

    def test_non_module_entry_is_an_error(self) -> None:
        with pytest.raises(ArdtError, match="must point at a module"):
            collect({"bad": object()})


def test_run_unknown_pipeline_is_clean(repo) -> None:
    """Through the real CLI: unknown names get a one-line diagnosis."""
    import contextlib
    import io

    from ardt_core.cli import main

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(["-C", str(repo), "pipe", "run", "nope"])
    assert code == 1
    assert "no pipeline named" in err.getvalue()
    assert "Traceback" not in err.getvalue()
