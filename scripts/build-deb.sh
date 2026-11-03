#!/usr/bin/env bash
# Build the Ubuntu package in Docker (same steps as CI). Result: dist/dailydeck_<version>_all.deb
#
#   scripts/build-deb.sh                      # Ubuntu 26.04
#   UBUNTU_IMAGE=ubuntu:25.10 scripts/build-deb.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${UBUNTU_IMAGE:-ubuntu:26.04}"
mkdir -p "$ROOT/dist"
docker run --rm \
    -v "$ROOT":/src:ro -v "$ROOT/dist":/out \
    -e HOST_UID="$(id -u)" -e HOST_GID="$(id -g)" \
    "$IMAGE" bash /src/scripts/ci/build-deb.sh /src /out
