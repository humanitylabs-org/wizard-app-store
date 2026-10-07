# Secret Drop relay: stdlib-only Python, no third-party runtime packages.
FROM python:3.12-alpine@sha256:1b668429b3511ab407d8e00648891631b0b1a4d7e15e3ca70f38ab5b91ad4ab4
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 SECRET_DROP_DATA_DIR=/data SECRET_DROP_BIND=0.0.0.0 SECRET_DROP_PORT=8792
LABEL org.opencontainers.image.source="https://github.com/humanitylabs-org/wizard-app-store" \
      org.opencontainers.image.description="Secret Drop: one-time end-to-end-encrypted credential handoff from a human to an agent" \
      org.opencontainers.image.licenses="MIT"
RUN mkdir -p /app/static /data && chown 1000:1000 /data
COPY --chmod=0444 server.py client.py SKILL.md LICENSE /app/
COPY --chmod=0444 static/ /app/static/
USER 1000:1000
WORKDIR /app
EXPOSE 8792
CMD ["python3", "/app/server.py"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s CMD ["python3", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8792/health', timeout=3).read()"]
