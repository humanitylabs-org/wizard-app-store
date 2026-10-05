#!/bin/sh
set -eu
# No UI patches: fetch and build exactly this upstream revision.
ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
REV=1af684e2d6ce05e6d1da82d67bc671e15d2d2d96
mkdir -p "${TMPDIR:-$ROOT/.build}"
WORK=$(mktemp -d "${TMPDIR:-$ROOT/.build}/wizard-ui.XXXXXX")
trap 'rm -rf "$WORK"' EXIT
curl --fail --location --retry 2 "https://github.com/przbadu/hermes-ui/archive/$REV.tar.gz" -o "$WORK/source.tar.gz"
tar -xzf "$WORK/source.tar.gz" -C "$WORK"
cd "$WORK/hermes-ui-$REV/app"
"$ROOT/node_modules/.bin/bun" install --frozen-lockfile --ignore-scripts
"$ROOT/node_modules/.bin/bun" run build
cp -R dist "$ROOT/images/hermes-frontend-3/"
cp ../LICENSE "$ROOT/images/hermes-frontend-3/LICENSE.upstream"
