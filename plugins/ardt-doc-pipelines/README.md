# ardt-doc-pipelines

The docs pipeline plane: `ardt pipe run docs-ci` builds a **versioned
documentation site** into `public/`, ready for GitLab/GitHub Pages.

Each version is one containerized run of the same `ardt doc build` task a dev
uses locally (two-plane rule): the working tree, plus every configured branch
and tag-glob match built from git history with its own docs and config. The
site ships with a `versions.json` (theme flyout data) and a root redirect to
the default version.

```yaml
pipelines:
  docs_ci:
    builder: python:3.12-slim     # docs toolchain container (never ships)
    versions:
      branches: [main]
      tags: "v*"
```

Deferred, by design: PDF output and the pinned doc-builder image (base-images
family); until then the builder is assembled on the fly (apt + pip).
