# Doc pipelines

```bash
ardt pipe run docs-ci      # the whole versioned site into public/
```

Each version is one containerized run of the same `ardt doc build` a developer uses locally: the working tree, plus every configured branch and tag-glob match built from git history *with its own docs and config*. The site ships a `versions.json` (theme flyout data) and a root redirect to the default version. `public/` is GitLab Pages' artifact convention.

```{image} docs-ci-site.svg
:alt: Every configured ref builds once in a single builder container; the results are assembled into public/ with a versions.json and a root redirect.
:width: 100%
:align: center
```

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

`pip_packages:` covers what no ardt distribution can declare, a sphinx **style** package above all. They are PEP 508 strings, so an index release (`x>=1.2`) and a direct reference (`x @ git+https://…@v1.2.0`) both work, and an unpublished package is still reachable — the builder already installs ardt itself from a git URL by default.

## Styles

A style is a plain sphinx extension, not an ardt plugin: nothing in it imports ardt, and it works in any sphinx project. A repo names it in `tasks.doc.style` and pins the package in `pip_packages:` so the builder has it:

```yaml
tasks:
  doc:
    style: [asterion_sphinx_style]     # what to apply
pipelines:
  docs_ci:
    pip_packages: ["asterion-sphinx-style>=0.1.0"]   # where it comes from
```

Two lines because they answer different questions, and the second cannot be derived from the first: an import name is not a distribution name, and the builder has to install the package before anything can ask it what it provides.

`conf.py` stays at the three-line preset contract. The style is deliberately *not* declared there: the pipeline forwards `tasks.doc.style` into the builder as an environment variable the preset reads, so it applies to **every** version of the site, including releases whose own `conf.py` predates the style. A style declared in `conf.py` could only ever reach refs that already knew about it.

That also means a style release restyles the whole archive on the next rebuild, which is the intent (`ardt --version` docs from 2026 should not look like 2026 forever) and the reason the rules below matter.

A developer needs the same package in the environment `ardt` itself runs from, or a local `ardt doc build` renders unstyled — one more `--with asterion-sphinx-style` on the `uv tool install` line.

A lower bound rather than `==` is deliberate: a house style is meant to move with the brand, not to be bumped by hand in every repo. Each *resolved* release is still immutable, since an index forbids re-uploading a version — which a git tag does not.

Three rules make a style safe to use, because docs-ci rebuilds *every* version of a site with the *currently installed* one:

1. **Fill, never clobber.** Set `html_theme`, `html_logo`, `html_favicon` only when unset, so a repo can always override.
2. **Absolute paths for packaged assets**, appended to `html_static_path` / `templates_path` on `builder-inited` — never assigned.
3. **Never warn.** `tasks.doc.strict` is on by default, and one warning on one historical ref fails the whole site.

The preset stays theme-agnostic; a style is theme-specific by nature, since it chooses the theme and may ship templates shaped for it.

Every listed ref is built with *its own* `doc/` and `conf.py`, and `ardt doc build` fails hard on a ref that has no `doc/` at all — so a version predating the repo's documentation cannot join the site, and one failing ref fails the whole run. Grow `versions:` from the oldest ref that actually ships docs.

Deferred by design: PDF output and a pinned doc-builder image (the base-images family). Until then the builder is assembled on the fly with apt + pip.

The implementation is {py:mod}`ardt_doc_pipelines.docs_ci`.
