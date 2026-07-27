/* Copyright 2026 Asterion Robotics
 * SPDX-License-Identifier: Apache-2.0
 *
 * The version flyout: an RTD-style corner box listing every version of the site,
 * fed by the `versions.json` the docs-ci pipeline writes at the site root.
 *
 * Deliberately a plain script and nothing else -- no `layout.html` override, no
 * `html_context`, no theme blocks:
 *
 *   - Theme-agnostic. Template names and block structure differ between
 *     sphinx-rtd-theme and pydata-sphinx-theme; a fixed-position element
 *     appended to <body> works in both, and in whatever comes next.
 *   - Build-time data is impossible anyway. docs-ci builds each version in its
 *     own container from its own git ref, so a build of v1.0 cannot know v2.0
 *     exists. Only the browser, on the assembled site, can see the whole set.
 *
 * Sphinx serves this from `<site>/<version>/_static/`, so our own URL yields
 * both the site root and the current version's name with no configuration.
 */
(function () {
  "use strict";

  var self = document.currentScript;
  if (!self || !window.fetch) return;

  var manifest = new URL("../../versions.json", self.src);
  var segments = new URL("..", self.src).pathname.split("/").filter(Boolean);
  var current = decodeURIComponent(segments[segments.length - 1] || "");

  var CSS = [
    ".ardt-vf{position:fixed;bottom:0;left:0;z-index:800;margin:0;",
    "font:normal 90%/1.4 system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;",
    "background:#1f2937;color:#e5e7eb;border-top-right-radius:.35rem;",
    "max-width:16rem;box-shadow:0 -1px 6px rgba(0,0,0,.35)}",
    ".ardt-vf>summary{cursor:pointer;padding:.45rem .8rem;list-style:none;",
    "white-space:nowrap;user-select:none}",
    ".ardt-vf>summary::-webkit-details-marker{display:none}",
    ".ardt-vf>summary::after{content:' \\25B4';opacity:.7}",
    ".ardt-vf[open]>summary::after{content:' \\25BE'}",
    ".ardt-vf>ul{margin:0;padding:.25rem 0 .5rem;list-style:none;",
    "max-height:60vh;overflow-y:auto;border-top:1px solid rgba(255,255,255,.15)}",
    ".ardt-vf>ul>li{margin:0;padding:0}",
    ".ardt-vf>ul>li>a{display:block;padding:.3rem .8rem;color:#cbd5e1;",
    "text-decoration:none;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
    ".ardt-vf>ul>li>a:hover{background:rgba(255,255,255,.1);color:#fff}",
    ".ardt-vf>ul>li>a[aria-current]{color:#fff;font-weight:600}",
    "@media print{.ardt-vf{display:none}}",
  ].join("");

  function render(versions) {
    var style = document.createElement("style");
    style.textContent = CSS;
    document.head.appendChild(style);

    var box = document.createElement("details");
    box.className = "ardt-vf";
    box.setAttribute("aria-label", "Documentation versions");

    var summary = document.createElement("summary");
    summary.textContent = "Version: " + (current || "unknown");
    box.appendChild(summary);

    var list = document.createElement("ul");
    versions.forEach(function (entry) {
      var name = entry && (entry.name || entry.version);
      if (!name) return;
      var item = document.createElement("li");
      var link = document.createElement("a");
      // Resolved against the manifest, so the site can live under any path
      // prefix -- `/` on GitLab Pages, `/<repo>/` on a GitHub project site.
      link.href = new URL(entry.url || name + "/", manifest).href;
      link.textContent = name;
      if (name === current) link.setAttribute("aria-current", "page");
      item.appendChild(link);
      list.appendChild(item);
    });
    box.appendChild(list);
    document.body.appendChild(box);
  }

  fetch(manifest.href, { credentials: "same-origin" })
    .then(function (response) {
      return response.ok ? response.json() : null;
    })
    .then(function (versions) {
      if (Array.isArray(versions) && versions.length) render(versions);
    })
    .catch(function () {
      /* A plain `ardt doc build` has no manifest. Render nothing, say nothing. */
    });
})();
