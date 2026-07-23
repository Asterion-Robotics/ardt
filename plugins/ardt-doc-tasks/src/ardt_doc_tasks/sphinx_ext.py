"""The ``ros2-interfaces`` sphinx directive — the thin front over :mod:`.interfaces`.

Usage, from any page of a repo's docs::

    .. ros2-interfaces:: my_msgs_package

The argument is the interface package's directory relative to the project
root, found by walking up from the sphinx conf directory to the first
``ardt.yaml``/``.git`` — the same discovery the preset uses.

Each interface renders as a real section, so themes list them in the page toc
and (RTD-style) in the sidebar tree. The ``:kinds:`` option restricts a page
to a subset — the per-kind-page pattern::

    .. ros2-interfaces:: my_msgs_package
       :kinds: srv action
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from docutils import nodes
from sphinx.application import Sphinx
from sphinx.util.docutils import SphinxDirective

from ardt_core.config import find_project_root

from . import __version__, interfaces


def _kinds_option(argument: str) -> tuple[str, ...]:
    kinds = tuple(argument.replace(",", " ").split())
    unknown = [k for k in kinds if k not in interfaces.KIND_SECTIONS]
    if unknown:
        known = ", ".join(interfaces.KIND_SECTIONS)
        raise ValueError(f"unknown interface kind(s) {unknown}; choose from: {known}")
    return kinds


class Ros2InterfacesDirective(SphinxDirective):
    """Render a package's interfaces (optionally one kind) as sections of tables."""

    required_arguments = 1
    option_spec = {"kinds": _kinds_option}  # noqa: RUF012 - docutils API shape

    def run(self) -> list[nodes.Node]:
        root = find_project_root(Path(self.env.app.confdir))
        package_dir = root / self.arguments[0]
        kinds: tuple[str, ...] | None = self.options.get("kinds")
        if not package_dir.is_dir():
            raise self.error(
                f"ros2-interfaces: `{self.arguments[0]}` is not a directory "
                "(the path is relative to the project root)"
            )
        found = interfaces.find_interfaces(package_dir, kinds)
        if not found:
            wanted = "/".join(kinds) if kinds else "msg/srv/action"
            raise self.error(f"ros2-interfaces: no {wanted} files under `{self.arguments[0]}`")
        for path in found:  # edits to the interface files trigger a rebuild
            self.env.note_dependency(str(path))
        for kind in kinds if kinds else tuple(interfaces.KIND_SECTIONS):
            if (package_dir / kind).is_dir():  # added/removed files change the dir mtime
                self.env.note_dependency(str(package_dir / kind))
        return self.parse_text_to_nodes(
            interfaces.render_package_rst(package_dir, kinds), allow_section_headings=True
        )


def setup(app: Sphinx) -> dict[str, Any]:
    app.add_directive("ros2-interfaces", Ros2InterfacesDirective)
    return {"version": __version__, "parallel_read_safe": True, "parallel_write_safe": True}
