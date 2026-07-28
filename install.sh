#!/usr/bin/env bash
# Copyright 2026 Asterion Robotics
# SPDX-License-Identifier: Apache-2.0
#
# Install ardt as a uv tool:
#
#     curl -LsSf https://raw.githubusercontent.com/Asterion-Robotics/ardt/main/install.sh | bash
#
# Everything is in main(), called on the very last line, on purpose: a `curl |
# bash` whose connection drops mid-transfer executes whatever arrived. Wrapped
# this way, a truncated download defines a function and exits having done
# nothing, instead of running half an install.
#
# Knobs, all optional:
#     ARDT_REF=v0.1.0     git ref to install (default: the `ardt.version` pin
#                         from ./ardt.yaml when present, else the repo's
#                         default branch)
#     ARDT_MODULES="…"    space-separated distribution names (default: the
#                         context-aware bundle below, adjusted by the
#                         `ardt.install_extras` / `ardt.install_skip` lists
#                         of ./ardt.yaml when present)
#     ARDT_REPO=…         a fork or a mirror
set -euo pipefail

ARDT_REPO="${ARDT_REPO:-https://github.com/Asterion-Robotics/ardt.git}"
ARDT_REF="${ARDT_REF:-}"
ARDT_MODULES="${ARDT_MODULES:-}"

say() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

# The repo's own pin: the `ardt.version:` entry of an ardt.yaml in the working
# directory -- the same pin the pipelines install inside the containers they
# build, so one file versions both planes and CI needs no parsing of its own.
# sed instead of a YAML parser on purpose: this runs from a bare `curl | bash`
# with no dependencies, and the pin is one scalar under one top-level key.
# Quotes and trailing comments are stripped; per-module `ardt.modules:` pins
# are a pipeline concern, not a bootstrap one.
pinned_ref() {
    [ -f ardt.yaml ] || return 0
    sed -n '/^ardt:/,/^[^[:space:]]/{s/^[[:space:]]*version:[[:space:]]*//p}' ardt.yaml \
        | head -n 1 \
        | sed "s/[[:space:]]*#.*\$//; s/^[\"']//; s/[\"']\$//"
}

# The default module set is contextual, because "no ardt-dev on a runner" is a
# property of where the install runs, not of any one repo: GitHub Actions and
# GitLab CI both export CI=true, so runners get the task+pipeline planes and
# workstations add ardt-dev on top. The doc plugins are in neither bundle --
# `ardt doc build` pulls sphinx and breathe, which most users of a ROS repo
# never invoke; a repo whose CI builds docs lists them in `install_extras`.
default_bundle() {
    printf '%s' 'ardt-core ardt-pipelines ardt-ros-tasks ardt-ros-pipelines'
    [ -z "${CI:-}" ] && printf ' %s' 'ardt-dev'
    printf '\n'
}

# A list-valued key of the `ardt:` section of ./ardt.yaml, one item per line.
# Accepts the two YAML spellings a bootstrap parser should ever grow -- flow
# (`key: [a, b]`) and block (`- a` lines); quotes and trailing comments are
# stripped. awk, not a YAML parser: same rationale as pinned_ref above.
config_list() {
    [ -f ardt.yaml ] || return 0
    awk -v key="$1" '
        /^ardt:/ { section = 1; next }
        section && /^[^ \t]/ { section = 0 }
        !section { next }
        !in_list && $0 ~ "^[ \t]+" key ":" {
            sub("^[ \t]+" key ":[ \t]*", ""); sub(/[ \t]*#.*$/, "")
            if ($0 ~ /^\[/) {                       # flow style: [a, b]
                gsub(/[][,]/, " "); gsub(/["'\'']/, "")
                for (i = 1; i <= NF; i++) print $i
                exit
            }
            in_list = 1; next
        }
        in_list {
            if ($0 !~ /^[ \t]*-/) exit              # block list ended
            sub(/^[ \t]*-[ \t]*/, ""); sub(/[ \t]*#.*$/, ""); gsub(/["'\'']/, "")
            if ($0 != "") print
        }
    ' ardt.yaml
}

# (bundle - install_skip) + install_extras, order preserved, extras deduped.
# Skip only prunes the bundle: an extra is an explicit request and wins.
resolve_modules() {
    local skip modules="" module
    skip=" $(config_list install_skip | tr '\n' ' ')"
    for module in $(default_bundle); do
        case "$skip " in *" $module "*) continue ;; esac
        modules="$modules$module "
    done
    for module in $(config_list install_extras); do
        case " $modules" in *" $module "*) continue ;; esac
        modules="$modules$module "
    done
    printf '%s\n' "${modules% }"
}

# packages/ for the platform, plugins/ for everything else -- the same split
# `ardt_core.dist.subdirectory` makes.
subdirectory() {
    case "$1" in
        ardt-core | ardt-pipelines) printf 'packages/%s' "$1" ;;
        *) printf 'plugins/%s' "$1" ;;
    esac
}

requirement() {
    local module="$1" at=""
    [ -n "$ARDT_REF" ] && at="@${ARDT_REF}"
    printf '%s @ git+%s%s#subdirectory=%s' \
        "$module" "$ARDT_REPO" "$at" "$(subdirectory "$module")"
}

main() {
    if [ -z "$ARDT_REF" ]; then
        ARDT_REF="$(pinned_ref)"
        [ -n "$ARDT_REF" ] && say "using the ardt.version pin from ./ardt.yaml: ${ARDT_REF}"
    fi
    if [ -z "$ARDT_MODULES" ]; then
        ARDT_MODULES="$(resolve_modules)"
    fi

    command -v uv >/dev/null 2>&1 || die "uv is required.
  Install it, then re-run this script:
    curl -LsSf https://astral.sh/uv/install.sh | sh
  (deliberately not done for you: chaining installers hides what you are trusting)"

    set -- # rebuild the argument list as uv's flags
    local first=""
    for module in $ARDT_MODULES; do
        if [ -z "$first" ]; then
            first="$module"
            set -- "$(requirement "$module")"
        else
            set -- "$@" --with "$(requirement "$module")"
        fi
    done
    [ -n "$first" ] || die "ARDT_MODULES is empty"

    say "installing ${ARDT_MODULES}${ARDT_REF:+ at $ARDT_REF}"
    uv tool install --force "$@"

    command -v ardt >/dev/null 2>&1 || die "installed, but 'ardt' is not on PATH.
  uv keeps tools in ~/.local/bin; add it to PATH, or run: uv tool update-shell"

    say "$(ardt --version)"
    say "try: ardt --help"
}

main "$@"
