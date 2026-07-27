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
    default: null                          # version the root redirect targets;
                                           # null means the working-tree version
    versions:
      branches: [main]                     # empty by default: working tree only
      tags: "v*"
```

The builder installs the ardt **task** plane only (`ardt-core` + `ardt-doc-tasks`) from the repo's `ardt:` pin, then runs `ardt doc build` per ref. A repo whose docs autodoc a Python API must therefore make that API installable in the builder: `ardt_modules:` names the ardt modules the documentation needs, typically a plugin repo autodoccing itself, resolved through the same `ardt:` pin (out-of-monorepo modules included).

Every listed ref is built with *its own* `doc/` and `conf.py`, and `ardt doc build` fails hard on a ref that has no `doc/` at all — so a version predating the repo's documentation cannot join the site, and one failing ref fails the whole run. Grow `versions:` from the oldest ref that actually ships docs.

Deferred by design: PDF output and a pinned doc-builder image (the base-images family). Until then the builder is assembled on the fly with apt + pip.

The implementation is {py:mod}`ardt_doc_pipelines.docs_ci`.
