"""Enforce the single-choke-point rule (07 §5).

No module may touch ``os.environ`` except :mod:`ardt_core.env` (the choke point
itself). Pipelines being parameterized by config+context rather than CI env vars
(02 §1 rule 2) only holds if this stays true, so it is a test, not a convention.
"""

from __future__ import annotations

import ast
from pathlib import Path

import ardt_core
import ardt_doc_pipelines
import ardt_doc_tasks
import ardt_pipelines
import ardt_ros_pipelines
import ardt_ros_tasks

ALLOWED = {"env.py"}


def _package_files(package: object) -> list[Path]:
    root = Path(package.__file__).parent  # type: ignore[arg-type]
    return sorted(root.rglob("*.py"))


def _reads_environ(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        # os.environ  /  os.getenv(...)  /  os.environ.get(...)
        if isinstance(node, ast.Attribute) and node.attr in {"environ", "getenv", "putenv"}:
            value = node.value
            if isinstance(value, ast.Name) and value.id == "os":
                return True
    return False


def test_only_env_module_reads_the_environment() -> None:
    offenders: list[str] = []
    packages = (
        ardt_core,
        ardt_ros_tasks,
        ardt_doc_tasks,
        ardt_pipelines,
        ardt_ros_pipelines,
        ardt_doc_pipelines,
    )
    for package in packages:
        for path in _package_files(package):
            if path.name in ALLOWED:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            if _reads_environ(tree):
                offenders.append(path.name)
    assert offenders == [], f"os.environ accessed outside env.py: {offenders}"
