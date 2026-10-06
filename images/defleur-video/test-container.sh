#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
docker build -t wizard-defleur-video:0.2.1-testing "$ROOT"
# 1 GiB is a scratch quota, not a preallocation. Stages reserve 512 MiB.
set --
if [ -n "${VIDEO_HELPER_ROOT:-}" ]; then
  set -- --mount "type=bind,source=$VIDEO_HELPER_ROOT,target=/opt/workflow,readonly" -e VIDEO_HELPER_ROOT=/opt/workflow
fi
docker run "$@" --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges --cpus 2 --memory 1536m --memory-swap 1536m \
  --pids-limit 64 --tmpfs /scratch:rw,noexec,nosuid,size=1024m,mode=1777 \
  -e TMPDIR=/scratch \
  --mount "type=bind,source=$ROOT/test_service.py,target=/app/test_service.py,readonly" \
  --entrypoint /usr/bin/python3 wizard-defleur-video:0.2.1-testing -c '
import unittest, pathlib, json, os
r = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover("/app", pattern="test_service.py"))
print(json.dumps({"uid": os.getuid(), **{n: pathlib.Path("/sys/fs/cgroup/" + n).read_text().strip() for n in ("memory.peak", "memory.max", "memory.swap.max", "cpu.max")}}))
raise SystemExit(not r.wasSuccessful())'
