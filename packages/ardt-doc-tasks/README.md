# ardt-tasks-doc

The documentation task plugin: `ardt doc build` — Doxygen (C++ API via
breathe) then Sphinx, one version from the working tree, into `build/doc/`.

The whole toolchain is preset-driven: a repo's `conf.py` is three lines
(`from ardt_tasks_doc.preset import *` + `project = ...`). The preset pins the
theme (pydata) and the extension set (myst markdown, mermaid, mathjax,
autodoc/napoleon, breathe, and the ardt `ros2-interfaces` directive that
renders `.msg`/`.srv`/`.action` files without a built workspace).

Version aggregation, PDF and Pages publishing belong to the docs *pipeline*
(two-plane rule), which runs this task per ref. See the workspace README.
