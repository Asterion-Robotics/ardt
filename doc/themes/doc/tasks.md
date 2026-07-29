# Doc tasks

```bash
ardt doc build     # doxygen (C++ repos) then sphinx html into build/doc/
ardt doc serve     # the built docs at http://127.0.0.1:8000/
```

Output follows the fixed convention: HTML at `build/doc/html`, Doxygen XML at `build/doc/doxygen/xml`. Sphinx runs as `sys.executable -m sphinx`, so it executes in the venv holding the plugin — the preset, breathe and the `ros2-interfaces` extension are importable from `conf.py` by construction.

(doc-local-preview)=
## Local preview

`ardt doc serve` serves `build/doc/html` over local http (`--port` to move it off 8000); `ardt doc serve --site` serves the `public/` site that [`docs-ci`](pipelines.md) exports instead. Serving matters more than it looks: opening the files directly over `file://` breaks the versioned site, because mapping a directory URL to its `index.html` is a web-server convention and the version switcher fetches `versions.json`, which browsers block on file origins. The server is the stdlib `http.server` from the plugin's venv, so the command adds no dependency.

## The preset

The whole toolchain is preset-driven. A repo's `conf.py`:

```python
from ardt_doc_tasks.preset import *  # noqa: F403

project = "my_project"
```

{py:mod}`ardt_doc_tasks.preset` pins the theme and the extension set: myst markdown, mermaid, mathjax, autodoc + napoleon + viewcode + intersphinx, breathe, and the ardt `ros2-interfaces` directive. Everything it sets is a *default* — `conf.py` executes top to bottom, so anything assigned after the import wins (swap `html_theme`, extend `extensions` or `autodoc_mock_imports`, …). Updating an extension for every repo is one MR in this package.

Two conventions it relies on: the project root is found by walking up to the first `ardt.yaml` / `.git`, and `ament_python` packages (`<root>/<pkg>/setup.py`) join `sys.path` so autodoc imports them without a colcon build — ROS runtime imports (`rclpy`, `rclcpp`) are mocked.

## Configuration

```yaml
tasks:
  doc:
    source_dir: doc        # the sphinx project directory (holds conf.py)
    doxygen: auto          # true / false / auto (on when the repo has C or C++)
    doxygen_input: []      # dirs doxygen scans; empty means the whole repo
    strict: true           # sphinx -W --keep-going: warnings are errors
```

`strict` is the doc equivalent of a red test, and it is on by default.

## ROS 2 interfaces

`.msg` / `.srv` / `.action` files render as real sections — themes list them in the page toc and in the sidebar tree — with **no built workspace and no rosidl import**, by parsing the files directly ({py:mod}`ardt_doc_tasks.interfaces`). The ROS comment conventions are honored: a block above a field documents that field, an inline `#` documents its line, and a top-of-file block describes the interface.

````markdown
```{ros2-interfaces} my_msgs_package
:kinds: srv action
```
````

The argument is the package directory relative to the project root; `:kinds:` restricts a page to a subset, which is what the per-kind-page pattern uses.

## C++ API

Doxygen runs first when the repo contains C/C++ sources (`doxygen: auto`), writing XML that breathe reads. The Doxyfile is generated per run into `build/doc/doxygen/` — repos carry none. Missing XML only fails pages that actually use a doxygen directive.

## Python API

`sphinx.ext.autodoc` and `napoleon` are in the preset, so `automodule` works out of the box for anything importable in the build environment:

````markdown
```{automodule} my_package.module
:members:
```
````

There is deliberately no autosummary or autoapi in the preset: API pages are written, not generated, so the sidebar stays curated. What autodoc can *see* is the build environment's `sys.path` — for `ament_python` packages the preset handles it; for anything else, install it in the environment `ardt doc build` runs from.
