# DeFleur Video API with James DeFleur's original workflow helpers bundled (see NOTICE).
FROM ghcr.io/astral-sh/uv:0.11.16@sha256:440fd6477af86a2f1b38080c539f1672cd22acb1b1a47e321dba5158ab08864d AS uv

# Node runtime + exact-pinned puppeteer-core and GSAP (package-lock.json) for James' capture.cjs. No browser here:
# capture connects to the shared Browser app.
FROM node:22-bookworm-slim@sha256:c3de60bf2f9dd0ac6370e6117950ff62d6e339527e7472301c9c78a017978392 AS capture
WORKDIR /opt/capture
COPY capture/package.json capture/package-lock.json /opt/capture/
RUN npm ci --omit=dev --ignore-scripts --no-audit --no-fund && rm -rf /root/.npm \
    && node -e "require('puppeteer-core'); require('fs').statSync('node_modules/gsap/dist/gsap.min.js')"

FROM ubuntu:24.04@sha256:534baea6a22c03a63003dbc8dbe78fe34bc0d7e595d9a9dc9834884ff530eb55 AS venv
ENV DEBIAN_FRONTEND=noninteractive UV_NO_CACHE=1 UV_PYTHON_DOWNLOADS=never
RUN apt-get update && apt-get install -y --no-install-recommends python3 ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=uv /uv /usr/local/bin/uv
COPY requirements.lock /tmp/requirements.lock
# Hash-locked CPU-only torch/stable-ts/numpy/matplotlib (uv pip compile --generate-hashes). No faster-whisper.
RUN uv venv --python /usr/bin/python3 /opt/venv \
    && uv pip install --python /opt/venv/bin/python --require-hashes --no-deps \
       --index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple \
       --index-strategy unsafe-best-match -r /tmp/requirements.lock \
    && rm -rf /opt/venv/lib/python3.12/site-packages/torch/include /opt/venv/lib/python3.12/site-packages/torch/test \
    && find /opt/venv -name '__pycache__' -prune -exec rm -rf {} + \
    && /opt/venv/bin/python -c "import torch, stable_whisper, numpy, matplotlib, PIL, onnxruntime, uvicorn, cv2; assert cv2.FaceDetectorYN; import mcp.server.mcpserver; print(torch.__version__)"

FROM ubuntu:24.04@sha256:534baea6a22c03a63003dbc8dbe78fe34bc0d7e595d9a9dc9834884ff530eb55
ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 VIDEO_BIND=0.0.0.0 VIDEO_DATA_DIR=/data \
    DEFLEUR_ROOT=/opt/defleur VIDEO_HELPER_PYTHON=/opt/venv/bin/python VIDEO_MODELS_DIR=/data/models
RUN apt-get update && apt-get install -y --no-install-recommends python3 ffmpeg util-linux tini ca-certificates fontconfig fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir /app /data && chown 1000:1000 /data
RUN test -f /usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf && fc-match -f '%{file}' 'sans-serif:style=Bold' | grep -q '^/usr/share/fonts/truetype/dejavu/'
COPY --from=venv /opt/venv /opt/venv
COPY --from=capture /usr/local/bin/node /usr/bin/node
COPY --from=capture /opt/capture /opt/capture
COPY capture/capture-remote.cjs capture/capture-remote.diff /opt/capture/
RUN /usr/bin/node --version
# YuNet face detector (opencv_zoo commit f12e127, MIT, Shiqi Yu); hash = upstream git-lfs oid.
ADD --checksum=sha256:8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4 \
    https://media.githubusercontent.com/media/opencv/opencv_zoo/f12e12798e8314f7c074a6656816c048dcc95b7a/models/face_detection_yunet/face_detection_yunet_2023mar.onnx \
    /opt/models/yunet.onnx
RUN chmod 0644 /opt/models/yunet.onnx
LABEL org.opencontainers.image.source="https://github.com/humanitylabs-org/wizard-app-store" org.opencontainers.image.description="DeFleur Video testing API + MCP endpoint (audio/edit, face crop, motion capture via the Browser app, captions, final encode)"
# James' plugin files, byte-for-byte (upstream commit 30768288eb1308b18216a5df5eb4648fbce3e55b, MIT per plugin.json).
COPY defleur/ /opt/defleur/
COPY NOTICE /opt/defleur/NOTICE
WORKDIR /app
COPY service.py editing.py client.py workflow.py transcriber.py scan_windows.py face_audit.py final_render.py mcp_server.py motion.py motion_frames.py /app/
RUN /opt/venv/bin/python -I /opt/defleur/skills/defleur-audio/scripts/test_audio_gate.py
USER 1000:1000
EXPOSE 8787
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/usr/bin/python3", "/app/service.py"]
HEALTHCHECK --interval=30s --timeout=5s CMD ["/usr/bin/python3", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/healthz', timeout=3).read()"]
