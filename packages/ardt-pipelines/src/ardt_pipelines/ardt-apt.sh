#!/bin/sh
# Copyright 2026 Asterion Robotics
# SPDX-License-Identifier: Apache-2.0

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Author: Thibault Poignonec <t.poignonec@asterion-robotics.com>

# ardt-apt: run one build step, read from stdin, with its apt fetches going
# through the apt cache the `apt_proxy` build secret names, and run it again
# straight from the image's own sources when the cache does not answer, a
# fetch through it fails, or the step fails through it.
#
#   RUN --mount=type=secret,id=apt_proxy,required=false \
#       --mount=type=bind,from=ardt-apt,source=/ardt-apt,target=/run/ardt/ardt-apt \
#       /run/ardt/ardt-apt <<'STEP'
#   apt-get update && apt-get install -y ...
#   STEP
#
# The cache is read in URL-prefix form: a source `http(s)://<host>/<path>` is
# read as `http://<cache>/<host>/<path>`, and the cache fetches it from the
# source, over HTTPS where the source needs it (a caching nginx with one
# location per source, or apt-cacher-ng with a Remap- rule). The lists it
# serves are still checked against the image's keys. The rewritten sources and the apt configuration naming them live in
# a temporary directory handed to apt through APT_CONFIG, so nothing under
# /etc changes and nothing of it reaches a layer. Without the secret (a plain
# `docker build`, no proxy configured) the step runs as written.
#
# The secret holds `key=value` lines: `url` (http://host[:port]) and
# `probe_timeout` (seconds the cache has to answer a HEAD request).
# ARDT_APT_SPEC and ARDT_APT_ETC move the secret and /etc/apt, for tests.
set -u

spec=${ARDT_APT_SPEC:-/run/secrets/apt_proxy}
etc=${ARDT_APT_ETC:-/etc/apt}
work=$(mktemp -d /tmp/ardt-apt.XXXXXX) || exit 1
trap 'rm -rf "$work"' EXIT
cat > "$work/step.sh"

direct() {
  (unset APT_CONFIG; sh "$work/step.sh")
}

url=""
probe_timeout=2
if [ -r "$spec" ]; then
  while IFS='=' read -r key value || [ -n "$key" ]; do
    case "$key" in
      url) url=$value ;;
      probe_timeout) probe_timeout=$value ;;
    esac
  done < "$spec"
fi
url=${url%/}

if [ -z "$url" ]; then
  direct
  exit
fi

case "$url" in
  http://*) ;;
  *)
    echo "ardt-apt: the apt cache must be an http:// URL, not $url; fetching from the image's sources" >&2
    direct
    exit
    ;;
esac
hostport=${url#http://}
hostport=${hostport%%/*}
host=${hostport%:*}
port=${hostport##*:}
[ "$host" = "$hostport" ] && port=80

# A HEAD request answered within the timeout, not only an open port: a cache
# that accepts connections and then hangs counts as absent.
answers() {
  command -v timeout >/dev/null 2>&1 && command -v bash >/dev/null 2>&1 || return 1
  # shellcheck disable=SC2016 # expanded by the inner bash, from its arguments
  timeout "$probe_timeout" bash -c \
    'exec 3<>"/dev/tcp/$0/$1" && printf "HEAD / HTTP/1.0\r\n\r\n" >&3 && head -c 5 <&3' \
    "$host" "$port" 2>/dev/null | grep -q '^HTTP/'
}

if ! answers; then
  echo "ardt-apt: the apt cache at $url does not answer within ${probe_timeout}s; fetching from the image's sources"
  direct
  exit
fi

# Only URI fields are rewritten: one-line `deb`/`deb-src` entries and deb822
# `URIs:` lines. Options such as signed-by= stay as they are, so every list the
# cache serves is still checked against the image's keys.
rewrite() {
  sed -E "/^[[:space:]]*(URIs:|deb(-src)?[[:space:]])/ s#https?://#$url/#g" "$1" > "$2"
}
mkdir -p "$work/sources.list.d" "$work/apt.conf.d"
if [ -f "$etc/sources.list" ]; then
  rewrite "$etc/sources.list" "$work/sources.list"
else
  : > "$work/sources.list"
fi
for file in "$etc"/sources.list.d/*.list "$etc"/sources.list.d/*.sources; do
  [ -f "$file" ] && rewrite "$file" "$work/sources.list.d/${file##*/}"
done
# apt reads APT_CONFIG before apt.conf.d, so a timeout set here alone would be
# overridden by the image's own (60 s, 5 retries on the AOS images). The parts
# directory is a copy of the image's with one file last, which wins.
if [ -d "$etc/apt.conf.d" ]; then
  cp -p "$etc"/apt.conf.d/* "$work/apt.conf.d/" 2>/dev/null || true
fi
cat > "$work/apt.conf.d/zz-ardt-apt" <<EOF
// A cache that stops answering mid-step fails the step fast; the step is then
// run again from the image's sources.
Acquire::http::Timeout "30";
Acquire::Retries "2";
EOF
cat > "$work/apt.conf" <<EOF
Dir::Etc::sourcelist "$work/sources.list";
Dir::Etc::sourceparts "$work/sources.list.d";
Dir::Etc::parts "$work/apt.conf.d";
EOF

# apt-get and apt reach the step through a shim. Once a fetch through the cache
# has failed (apt's `Failed to fetch <cache>/...`, such as a 503 passed on from
# the source for a package the cache does not hold yet), every later call in the step fails at once instead of
# fetching again: a step that calls apt-get once per package, as rosdep does,
# would otherwise spend each package's retries on the same failing cache before
# the step is run again from the image's sources.
mkdir -p "$work/bin"
cat > "$work/shim.sh" <<'EOF'
work=$1 url=$2 real=$3
shift 3
if [ -e "$work/cache-failed" ]; then
  echo "ardt-apt: not running ${real##*/} $*: a fetch through the apt cache at $url failed earlier in this step" >&2
  exit 100
fi
log=$(mktemp "$work/stderr.XXXXXX") || exit 1
status=$(mktemp "$work/status.XXXXXX") || exit 1
# stderr copied aside to be read once the command ends, stdout left alone
{ { "$real" "$@" 2>&1 1>&3 3>&-; echo $? > "$status"; } | tee "$log" >&2; } 3>&1
rc=$(cat "$status")
if grep -qF "Failed to fetch $url/" "$log"; then
  : > "$work/cache-failed"
fi
rm -f "$log" "$status"
exit "${rc:-1}"
EOF
for tool in apt-get apt; do
  real=$(command -v "$tool") || continue
  printf '#!/bin/sh\nexec sh "%s/shim.sh" "%s" "%s" "%s" "$@"\n' "$work" "$work" "$url" "$real" > "$work/bin/$tool"
  chmod +x "$work/bin/$tool"
done

echo "ardt-apt: fetching through the apt cache at $url"
if APT_CONFIG="$work/apt.conf" PATH="$work/bin:$PATH" sh "$work/step.sh" && [ ! -e "$work/cache-failed" ]; then
  exit 0
fi
if [ -e "$work/cache-failed" ]; then
  echo "ardt-apt: a fetch through the apt cache at $url failed; running the step again from the image's sources"
else
  echo "ardt-apt: the step failed through the apt cache at $url; running it again from the image's sources"
fi
direct
