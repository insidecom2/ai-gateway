#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

docker compose \
  -f docker-compose.yml \
  -f docker-compose.ubuntu.yml \
  up -d --build

