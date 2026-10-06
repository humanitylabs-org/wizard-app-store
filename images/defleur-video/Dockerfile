# Original standalone service only; upstream workflow/vendor files are excluded.
FROM ubuntu:24.04@sha256:534baea6a22c03a63003dbc8dbe78fe34bc0d7e595d9a9dc9834884ff530eb55
ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 VIDEO_BIND=0.0.0.0 VIDEO_DATA_DIR=/data
RUN apt-get update && apt-get install -y --no-install-recommends python3 ffmpeg util-linux tini ca-certificates && rm -rf /var/lib/apt/lists/* \
    && mkdir /app /data && chown 1000:1000 /data
# Caption font is a required dependency, even if ffmpeg stops pulling it in.
RUN test -f /usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf || \
    (apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core && rm -rf /var/lib/apt/lists/*)
LABEL org.opencontainers.image.source="https://github.com/humanitylabs-org/wizard-app-store" org.opencontainers.image.description="DeFleur Video testing API"
WORKDIR /app
COPY service.py editing.py client.py workflow.py /app/
USER 1000:1000
EXPOSE 8787
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/usr/bin/python3", "/app/service.py"]
HEALTHCHECK --interval=30s --timeout=5s CMD ["/usr/bin/python3", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/healthz', timeout=3).read()"]
