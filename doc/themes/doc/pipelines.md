# Doc pipelines

```bash
ardt pipe run docs-ci      # the whole versioned site into public/
```

Each version is one containerized run of the same `ardt doc build` a developer uses locally: the working tree, plus every configured branch and tag-glob match built from git history *with its own docs and config*. The site ships a `versions.json` (theme flyout data) and a root redirect to the default version. `public/` is GitLab Pages' artifact convention.

```yaml
pipelines:
  docs_ci:
    builder: python:3.12-slim              # docs toolchain container (never ships)
    apt_packages: [git, doxygen, graphviz] # empty for a prebuilt builder image
    ardt_modules: []                       # ardt modules the docs need importable
    pip_packages: []                       # everything else the docs need (a style)
    default: null                          # version the root redirect targets;
                                           # null means the working-tree version
    versions:
      branches: [main]                     # empty by default: working tree only
      tags: "v*"
```

The builder installs the ardt **task** plane only (`ardt-core` + `ardt-doc-tasks`) from the repo's `ardt:` pin, then runs `ardt doc build` per ref. A repo whose docs autodoc a Python API must therefore make that API installable in the builder: `ardt_modules:` names the ardt modules the documentation needs, typically a plugin repo autodoccing itself, resolved through the same `ardt:` pin (out-of-monorepo modules included).

`pip_packages:` covers what no ardt distribution can declare, a sphinx **style** package above all. They are PEP 508 strings, so an index release (`x==1.2.0`) and a direct reference (`x @ git+https://…@v1.2.0`) both work and publishing is optional — the builder already installs ardt itself from a git URL by default.

## Styles

A style is a plain sphinx extension, not an ardt plugin: nothing in it imports ardt, and it works in any sphinx project. A repo opts in from its `conf.py`, and pins the package in `pip_packages:` so the builder has it:

```python
from ardt_doc_tasks.preset import *                       # toolchain
extensions = [*extensions, "asterion_sphinx_style"]       # presentation
project = "my_project"
html_logo = "_static/my-logo.png"                         # optional; wins over the style's
```

Rebind rather than `extensions.append(...)`: the star-import binds the preset's *own* list, so appending mutates it in place.

Three rules make a style safe to use, because docs-ci rebuilds *every* version of a site with the *currently installed* one:

1. **Fill, never clobber.** Set `html_theme`, `html_logo`, `html_favicon` only when unset, so a repo can always override.
2. **Absolute paths for packaged assets**, appended to `html_static_path` / `templates_path` on `builder-inited` — never assigned.
3. **Never warn.** `tasks.doc.strict` is on by default, and one warning on one historical ref fails the whole site.

The preset stays theme-agnostic; a style is theme-specific by nature, since it chooses the theme and may ship templates shaped for it.

Every listed ref is built with *its own* `doc/` and `conf.py`, and `ardt doc build` fails hard on a ref that has no `doc/` at all — so a version predating the repo's documentation cannot join the site, and one failing ref fails the whole run. Grow `versions:` from the oldest ref that actually ships docs.

Deferred by design: PDF output and a pinned doc-builder image (the base-images family). Until then the builder is assembled on the fly with apt + pip.

The implementation is {py:mod}`ardt_doc_pipelines.docs_ci`.
