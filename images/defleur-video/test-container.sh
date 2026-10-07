#!/bin/sh
# Build the image and run the unit suite plus James' test_audio_gate.py inside it,
# with the same hardening as the Runtipi recipe. Network is off: the Transcriber is
# faked on loopback here; the real Transcriber runs in scripts/e2e-video-audio.py.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
IMAGE=${VIDEO_IMAGE:-wizard-defleur-video:0.3.0-testing}
[ -n "${VIDEO_SKIP_BUILD:-}" ] || docker build -t "$IMAGE" "$ROOT"
docker run --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges --cpus 2 --memory 1536m --memory-swap 1536m \
  --pids-limit 64 --tmpfs /scratch:rw,noexec,nosuid,size=1024m,mode=1777 \
  -e TMPDIR=/scratch \
  --mount "type=bind,source=$ROOT/test_service.py,target=/app/test_service.py,readonly" \
  --entrypoint /usr/bin/python3 "$IMAGE" -c '
import unittest, pathlib, json, os, subprocess
gate = subprocess.run(["/opt/venv/bin/python", "-I", "/opt/defleur/skills/defleur-audio/scripts/test_audio_gate.py"])
r = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover("/app", pattern="test_service.py"))
print(json.dumps({"uid": os.getuid(), "test_audio_gate_rc": gate.returncode, **{n: pathlib.Path("/sys/fs/cgroup/" + n).read_text().strip() for n in ("memory.peak", "memory.max", "memory.swap.max", "cpu.max")}}))
raise SystemExit(gate.returncode or not r.wasSuccessful())'
