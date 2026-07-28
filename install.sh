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
#     ARDT_MODULES="…"    space-separated distribution names
#     ARDT_REPO=…         a fork or a mirror
set -euo pipefail

ARDT_REPO="${ARDT_REPO:-https://github.com/Asterion-Robotics/ardt.git}"
ARDT_REF="${ARDT_REF:-}"

# The task plane plus the pipeline plane, matching the README. The doc plugins
# are omitted by default: `ardt doc build` pulls sphinx and breathe, which most
# users of a ROS repo never invoke.
ARDT_MODULES="${ARDT_MODULES:-ardt-core ardt-pipelines ardt-ros-tasks ardt-ros-pipelines ardt-dev}"

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
