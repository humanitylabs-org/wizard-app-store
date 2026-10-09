# AI Accounts: a small stdlib Python page that drives the unmodified official Claude Code CLI.
FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258 AS claude
ARG TARGETARCH
COPY fetch-claude-code.py /fetch-claude-code.py
RUN python3 /fetch-claude-code.py "$TARGETARCH" /claude

FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    CLAUDE_CODE_VERSION=2.1.263 DISABLE_AUTOUPDATER=1 \
    AI_ACCOUNTS_CLAUDE_DIR=/claude AI_ACCOUNTS_PORT=8795
LABEL org.opencontainers.image.source="https://github.com/humanitylabs-org/wizard-app-store" \
      org.opencontainers.image.description="AI Accounts: connect a Claude subscription once with the official Claude Code login; agent apps reuse it" \
      org.opencontainers.image.licenses="MIT"
COPY --from=claude --chmod=0755 /claude /usr/local/bin/claude
# /claude is the shared login volume. A fresh named volume copies this owner and mode, so the first
# app to start (this one or Hermes Agent) creates it as 1000:1000 0700.
RUN mkdir -p /app/static /claude && chown 1000:1000 /claude && chmod 0700 /claude
COPY --chmod=0444 server.py SKILL.md LICENSE /app/
COPY --chmod=0444 static/ /app/static/
USER 1000:1000
WORKDIR /app
EXPOSE 8795
CMD ["python3", "/app/server.py"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s CMD ["python3", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8795/health', timeout=3).read()"]
