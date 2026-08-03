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
# awk instead of a YAML parser on purpose: this runs from a bare `curl | bash`
# with no dependencies, and the pin is one scalar under one top-level key.
# Keys match only at the section's own child indent (the indent of its first
# entry), so a deeper `modules.<name>.version:` pin can never shadow the
# top-level one. Quotes and trailing comments are stripped.
pinned_ref() {
    [ -f ardt.yaml ] || return 0
    awk '
        /^ardt:/ { section = 1; next }
        section && /^[^ \t]/ { exit }
        !section { next }
        /^[ \t]*(#|$)/ { next }
        {
            match($0, /^[ \t]+/)
            if (!child) child = RLENGTH
            if (RLENGTH == child && sub(/^[ \t]+version:[ \t]*/, "")) {
                sub(/[ \t]*#.*$/, ""); gsub(/^["'\'']|["'\'']$/, "")
                print; exit
            }
        }
    ' ardt.yaml
}

# The default module set is contextual, because "no devcontainer tooling on a
# runner" is a property of where the install runs, not of any one repo: GitHub
# Actions and GitLab CI both export CI=true, so runners get the bundle below
# and workstations add the dev engine and its ros2 profile on top.
#
# What is IN the bundle is policy, not necessity -- documented so the choice
# can be revisited instead of rediscovered:
#   - ardt-core, ardt-pipelines: the platform; everything needs them.
#   - ardt-ros-tasks, ardt-ros-pipelines: included because ardt is a robotics
#     toolchain and nearly every consumer repo is a ROS 2 repo; the default
#     serves that majority. A non-ROS repo sheds them with `install_skip`.
#   - ardt-devcontainers, ardt-ros-dev: the devcontainer engine and the
#     profile that drives it for a ROS 2 repo. Two modules, not one, since
#     the split -- a non-ROS workstation skips the profile and keeps the
#     engine. Both are useless on a runner, which never opens a container.
#   - doc plugins: excluded because `ardt doc build` pulls sphinx and breathe,
#     which most repos never invoke. A repo whose CI builds docs opts in with
#     `install_extras` (see ardt.example.yaml).
default_bundle() {
    printf '%s' 'ardt-core ardt-pipelines ardt-ros-tasks ardt-ros-pipelines'
    [ -z "${CI:-}" ] && printf ' %s' 'ardt-devcontainers ardt-ros-dev'
    printf '\n'
}

# A list-valued key of the `ardt:` section of ./ardt.yaml, one item per line.
# Accepts the two YAML spellings a bootstrap parser should ever grow -- flow
# (`key: [a, b]`) and block (`- a` lines); quotes and trailing comments are
# stripped. awk, not a YAML parser, and the same child-indent depth rule as
# pinned_ref above: a nested key inside `modules:` must never match.
config_list() {
    [ -f ardt.yaml ] || return 0
    awk -v key="$1" '
        /^ardt:/ { section = 1; next }
        section && /^[^ \t]/ { section = 0 }
        !section { next }
        /^[ \t]*(#|$)/ { next }
        {
            match($0, /^[ \t]+/)
            if (!child) child = RLENGTH
        }
        !in_list && RLENGTH == child && $0 ~ "^[ \t]+" key ":" {
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

# packages/ for the platform planes -- the CLI, the Dagger plane, the
# devcontainer plane -- and plugins/ for theme knowledge. This list is the same
# split `ardt_core.dist._PACKAGES` makes, and it has to be duplicated here: the
# installer runs before any ardt exists to ask. The two are held together by
# tests/test_install_sh.py, which reads _PACKAGES and asserts the paths this
# emits agree with it -- the check that was missing when the devcontainer
# engine moved from plugins/ to packages/ and this arm was left behind.
subdirectory() {
    case "$1" in
        ardt-core | ardt-pipelines | ardt-devcontainers) printf 'packages/%s' "$1" ;;
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
