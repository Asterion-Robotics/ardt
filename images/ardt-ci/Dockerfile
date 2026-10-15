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

# ardt-ci: the image a CI job runs ardt in. Published by this repository's
# release workflow as ghcr.io/asterion-robotics/ardt-ci:<tag>, one image per
# ardt release, so a CI job pins ardt by pinning this image and pays for no
# installer, no uv download and no CPython download at run time.
#
# The docker client is the base because the pipeline plane drives
# `docker buildx bake` against the daemon the job provides; the docker:cli
# image ships the buildx plugin. `docker login` writes ~/.docker/config.json,
# which is how registry credentials reach pulls, the cache and the push.
FROM docker:27-cli

# uv from a versioned image rather than an install script; the musl build,
# which this alpine base needs.
COPY --from=ghcr.io/astral-sh/uv:0.12.0 /uv /uvx /usr/local/bin/

# bash: install.sh is bash. git: the modules install from a git repository.
RUN apk add --no-cache bash curl git

# Before the install step: install.sh ends with its own `command -v ardt`
# check and fails if the tool is not reachable yet.
ENV PATH="/root/.local/bin:${PATH}"

# The CPython uv would otherwise download on first use, a musl build here.
ARG PYTHON_VERSION=3.12
ENV UV_PYTHON=${PYTHON_VERSION}
RUN uv python install ${PYTHON_VERSION}

# The module set is stated, not left to install.sh's contextual default (which
# reads CI and any ardt.yaml in the working directory): the image must not
# depend on where it is built. The CI bundle (no devcontainer modules, a runner
# never opens one) plus the doc modules.
ENV ARDT_MODULES="ardt-core ardt-pipelines ardt-ros-tasks ardt-ros-pipelines ardt-doc-tasks ardt-doc-pipelines"

# The ardt to install: a tag on release, a commit on a pull request. It must
# exist on GitHub, since install.sh and the modules are fetched from it, which
# is also what proves the published installer works.
ARG ARDT_REF
RUN test -n "${ARDT_REF}" || { echo "ARDT_REF is required (a tag or a commit)"; exit 1; } \
 && curl -fLsS "https://raw.githubusercontent.com/Asterion-Robotics/ardt/${ARDT_REF}/install.sh" -o /tmp/install.sh \
 && CI=true ARDT_REF="${ARDT_REF}" bash /tmp/install.sh \
 && rm -f /tmp/install.sh

# Fail the build rather than ship an image whose tooling is missing.
RUN ardt --version && docker --version && docker buildx version && uv --version
