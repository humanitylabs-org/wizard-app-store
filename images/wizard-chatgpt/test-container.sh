#!/bin/sh
# Isolated packaging test: no provider network, credentials, or real login.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
TAG=${WIZARD_CHATGPT_IMAGE:-wizard-chatgpt:test}
[ -n "${SKIP_BUILD:-}" ] || docker build -t "$TAG" "$ROOT"
python3 "$ROOT/../../tests/pool-container-smoke.py" chatgpt "$TAG"
