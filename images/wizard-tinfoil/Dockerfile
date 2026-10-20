FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
LABEL org.opencontainers.image.source="https://github.com/humanitylabs-org/wizard-app-store" \
      org.opencontainers.image.licenses="GPL-3.0-only"
WORKDIR /app
COPY requirements.lock /app/requirements.lock
RUN pip install --no-cache-dir --require-hashes -r /app/requirements.lock
COPY app /app/app
COPY web /app/web
COPY openapi.json /app/openapi.json
RUN mkdir /data && chown 1000:1000 /data && chmod 700 /data
USER 1000:1000
ENV DATA_DIR=/data/private PORT=18804 HOME=/data/private XDG_CACHE_HOME=/data/private/cache XDG_DATA_HOME=/data/private/share PYTHONDONTWRITEBYTECODE=1
EXPOSE 18804
CMD ["python", "/app/app/server.py"]
