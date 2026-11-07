# syntax=docker/dockerfile:1.7
# Hermes Agent, Wizard slim build. PACKAGING ONLY: stock Hermes source at the pinned release, no code changes.
#
# Same runtime as the official image (s6-overlay, /opt/data, hermes user, entrypoint, fixed SQLite, Playwright
# headless shell for the browser tool, dashboard + TUI bundles) and the same two Wizard add-ons as
# hermes-agent:v2026.9.24-wizard2 (pinned Claude Code + NousResearch's Claude Subscription DirectSDK plugin).
# What is left out, and why:
#   - compilers and dev headers (gcc, g++, make, cmake, python3-dev, libffi-dev, libolm-dev): only needed to build
#     wheels; they stay in the build stage;
#   - docker-cli: the Docker terminal backend needs a Docker socket, which a Wizard app never gets;
#   - extras Wizard doesn't use: matrix (needs libolm + compilers), google-chat, bedrock, azure-identity, otlp;
#   - the Photon iMessage sidecar (macOS-only service; not reachable from a Linux box).
# Kept: [all] (cron, pty, mcp, uvloop, homeassistant, sms, acp, google, web, youtube), [messaging]
# (Telegram, Discord, Slack), [anthropic], ffmpeg (voice notes and TTS conversion), git, ripgrep, node, uv.
ARG HERMES_REF=v2026.9.24
ARG HERMES_COMMIT=f97608f178d1ffeca59860195ab7da295f7c8e5f

FROM debian:13.4 AS sqlite_build
ARG SQLITE_AUTOCONF_VERSION=3530400
ARG SQLITE_SHA256=0e9483900e92cd5de8fd48d16bf9200145a61f7fd5be542a5ac81d8a9516eb9c
RUN apt-get -o Acquire::Retries=3 update && \
    apt-get -o Acquire::Retries=3 install -y --no-install-recommends build-essential ca-certificates curl && \
    rm -rf /var/lib/apt/lists/* && \
    (curl -fsSL --retry 1 --retry-all-errors --connect-timeout 15 --max-time 60 -o /tmp/sqlite.tar.gz \
        "https://sqlite.org/2026/sqlite-autoconf-${SQLITE_AUTOCONF_VERSION}.tar.gz" || \
     curl -fsSL --retry 3 --retry-all-errors --connect-timeout 15 --max-time 120 -o /tmp/sqlite.tar.gz \
        "https://sources.buildroot.net/sqlite/sqlite-autoconf-${SQLITE_AUTOCONF_VERSION}.tar.gz") && \
    printf '%s  %s\n' "${SQLITE_SHA256}" /tmp/sqlite.tar.gz | sha256sum -c && \
    tar -xzf /tmp/sqlite.tar.gz -C /tmp && cd "/tmp/sqlite-autoconf-${SQLITE_AUTOCONF_VERSION}" && \
    CFLAGS="-O2 -DSQLITE_ENABLE_FTS3 -DSQLITE_ENABLE_FTS3_PARENTHESIS -DSQLITE_ENABLE_FTS4 -DSQLITE_ENABLE_FTS5 \
        -DSQLITE_ENABLE_RTREE -DSQLITE_ENABLE_GEOPOLY -DSQLITE_ENABLE_COLUMN_METADATA -DSQLITE_ENABLE_UNLOCK_NOTIFY \
        -DSQLITE_ENABLE_DBSTAT_VTAB -DSQLITE_ENABLE_DBPAGE_VTAB -DSQLITE_ENABLE_MATH_FUNCTIONS \
        -DSQLITE_ENABLE_PREUPDATE_HOOK -DSQLITE_ENABLE_SESSION -DSQLITE_SECURE_DELETE -DSQLITE_THREADSAFE=1 \
        -DSQLITE_MAX_VARIABLE_NUMBER=250000" \
        ./configure --prefix=/opt/sqlite-fixed --disable-static && make -j"$(nproc)" && make install

FROM ghcr.io/astral-sh/uv:0.11.6-python3.13-trixie@sha256:b3c543b6c4f23a5f2df22866bd7857e5d304b67a564f4feab6ac22044dde719b AS uv_source
FROM node:26-bookworm-slim@sha256:9e6f9357d371591e32ab6f2d8a26d63bdd0d17c29eee3f4f3e7e454d9634bf73 AS node_source

# Wizard add-ons, identical to v2026.9.24-wizard2.
FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258 AS addons
ARG TARGETARCH
COPY fetch-claude-code.py fetch-directsdk-plugin.py /
RUN python3 /fetch-claude-code.py "$TARGETARCH" /out/claude \
 && python3 /fetch-directsdk-plugin.py /out/claude-subscription-directsdk-experimental

# ---------- build stage: everything that needs a compiler or a package manager cache ----------
FROM debian:13.4 AS build
ARG HERMES_REF
ARG HERMES_COMMIT
# The official image runs Python 3.13 (its uv python3.13 base), not .python-version's 3.11; /opt/data lazy packages
# are built for it, so the slim image must match to share /opt/data with wizard2/official. Install it in
# a fixed path so the runtime stage can copy the interpreter together with the venv that points at it.
ENV PYTHONDONTWRITEBYTECODE=1 PLAYWRIGHT_BROWSERS_PATH=/opt/hermes/.playwright npm_config_install_links=false \
    UV_PYTHON_INSTALL_DIR=/opt/uv-python UV_PYTHON=3.13 UV_LINK_MODE=copy
RUN apt-get -o Acquire::Retries=3 update && \
    apt-get -o Acquire::Retries=3 install -y --no-install-recommends \
    ca-certificates curl git python3 python-is-python3 python3-venv python3-dev gcc g++ make libffi-dev && \
    rm -rf /var/lib/apt/lists/*
COPY --from=sqlite_build /opt/sqlite-fixed/lib/libsqlite3.so.3.53.4 /usr/local/lib/
RUN ln -sf libsqlite3.so.3.53.4 /usr/local/lib/libsqlite3.so.0 && ln -sf libsqlite3.so.3.53.4 /usr/local/lib/libsqlite3.so && \
    printf '/usr/local/lib\n' > /etc/ld.so.conf.d/000-sqlite-fixed.conf && ldconfig
COPY --chmod=0755 --from=uv_source /usr/local/bin/uv /usr/local/bin/uvx /usr/local/bin/
COPY --chmod=0755 --from=node_source /usr/local/bin/node /usr/local/bin/
COPY --from=node_source /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN ln -sf /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm && \
    ln -sf /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx
# Stock source at the pinned release, checked by commit.
RUN git clone --depth 1 --branch "$HERMES_REF" https://github.com/NousResearch/hermes-agent.git /opt/hermes && \
    test "$(git -C /opt/hermes rev-parse HEAD)" = "$HERMES_COMMIT" && \
    printf '%s\n' "$HERMES_COMMIT" > /opt/hermes/.hermes_build_sha && \
    cd /opt/hermes && rm -rf .git .github tests website contributors evals data runtime hermes-config \
       plugins/platforms/photon/sidecar ui-tui/dist ui-tui/packages/hermes-ink/dist && \
    find apps -mindepth 1 -maxdepth 1 ! -name shared -exec rm -rf {} + && \
    find . -name '*.md' ! -name 'SKILL.md' ! -path './skills/*' ! -path './optional-skills/*' ! -path './docker/*' -delete && \
    touch README.md
WORKDIR /opt/hermes
RUN npm install --prefer-offline --no-audit --fetch-retries=5 && \
    for i in 1 2 3; do npx playwright install chromium --only-shell && break || { [ "$i" = 3 ] && exit 1; sleep 10; }; done && \
    npm cache clean --force
RUN uv python install 3.13 && \
    uv sync --frozen --no-install-project --no-cache \
      --extra all --extra messaging --extra anthropic && \
    uv pip install --python .venv/bin/python --no-cache-dir --no-deps -e "." && \
    find /opt/hermes/.venv -name '__pycache__' -prune -exec rm -rf {} + && \
    find /opt/hermes/.venv -name '*.pyc' -delete && \
    readlink -f /opt/hermes/.venv/bin/python | grep -q '^/opt/uv-python/.*3\.13' && \
    /opt/hermes/.venv/bin/hermes --version
# The dashboard and TUI ship as prebuilt bundles (HERMES_WEB_DIST, HERMES_TUI_DIR, as upstream), so build-only
# packages (typescript, vite, rolldown, three, babel, esbuild, eslint, vitest, prettier) are pruned afterwards.
RUN cd web && npm run build && cd ../ui-tui && npm run build && cd .. && \
    npm prune --omit=dev --no-audit && \
    test -f hermes_cli/web_dist/index.html && test -f ui-tui/dist/entry.js && test -d node_modules/@hermes/ink && \
    rm -rf /opt/hermes/web/node_modules/.cache /root/.npm /root/.cache

# ---------- runtime ----------
FROM debian:13.4
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PLAYWRIGHT_BROWSERS_PATH=/opt/hermes/.playwright \
    npm_config_install_links=false
RUN apt-get -o Acquire::Retries=3 update && \
    apt-get -o Acquire::Retries=3 install -y --no-install-recommends \
    ca-certificates curl iputils-ping python3 python-is-python3 python3-venv ripgrep ffmpeg libatomic1 procps git \
    openssh-client xz-utils && \
    rm -rf /var/lib/apt/lists/*
COPY --from=sqlite_build /opt/sqlite-fixed/lib/libsqlite3.so.3.53.4 /usr/local/lib/
RUN ln -sf libsqlite3.so.3.53.4 /usr/local/lib/libsqlite3.so.0 && ln -sf libsqlite3.so.3.53.4 /usr/local/lib/libsqlite3.so && \
    printf '/usr/local/lib\n' > /etc/ld.so.conf.d/000-sqlite-fixed.conf && ldconfig && \
    python3 -c "import sqlite3,sys; sys.exit('old sqlite') if sqlite3.sqlite_version_info < (3,51,3) else None"

ARG TARGETARCH
ARG S6_OVERLAY_VERSION=3.2.3.0
ARG S6_OVERLAY_NOARCH_SHA256=b720f9d9340efc8bb07528b9743813c836e4b02f8693d90241f047998b4c53cf
ARG S6_OVERLAY_X86_64_SHA256=a93f02882c6ed46b21e7adb5c0add86154f01236c93cd82c7d682722e8840563
ARG S6_OVERLAY_AARCH64_SHA256=0952056ff913482163cc30e35b2e944b507ba1025d78f5becbb89367bf344581
ARG S6_OVERLAY_SYMLINKS_SHA256=a60dc5235de3ecbcf874b9c1f18d73263ab99b289b9329aa950e8729c4789f0e
RUN set -eu; case "${TARGETARCH:-amd64}" in \
        amd64) a=x86_64; s="${S6_OVERLAY_X86_64_SHA256}";; arm64) a=aarch64; s="${S6_OVERLAY_AARCH64_SHA256}";; \
        *) exit 1;; esac; \
    b="https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}"; \
    curl -fsSL --retry 3 -o /tmp/n.tar.xz "$b/s6-overlay-noarch.tar.xz"; \
    curl -fsSL --retry 3 -o /tmp/l.tar.xz "$b/s6-overlay-symlinks-noarch.tar.xz"; \
    curl -fsSL --retry 3 -o /tmp/a.tar.xz "$b/s6-overlay-$a.tar.xz"; \
    printf '%s  %s\n%s  %s\n%s  %s\n' "$S6_OVERLAY_NOARCH_SHA256" /tmp/n.tar.xz "$s" /tmp/a.tar.xz \
        "$S6_OVERLAY_SYMLINKS_SHA256" /tmp/l.tar.xz | sha256sum -c; \
    for t in n a l; do tar -C / -Jxpf /tmp/$t.tar.xz; done; rm /tmp/*.tar.xz

RUN useradd -u 10000 -m -d /opt/data hermes
COPY --chmod=0755 --from=uv_source /usr/local/bin/uv /usr/local/bin/uvx /usr/local/bin/
COPY --chmod=0755 --from=node_source /usr/local/bin/node /usr/local/bin/
COPY --from=node_source /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN ln -sf /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm && \
    ln -sf /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

COPY --link --chmod=a+rX,go-w --from=build /opt/uv-python /opt/uv-python
COPY --link --chmod=a+rX,go-w --from=build /opt/hermes /opt/hermes
WORKDIR /opt/hermes
# Shared libraries the headless shell needs (what `playwright install --with-deps` adds), runtime only.
RUN apt-get -o Acquire::Retries=3 update && npx playwright install-deps chromium && \
    rm -rf /var/lib/apt/lists/* /root/.npm /usr/share/doc/* /usr/share/man/* /usr/share/info/* && \
    find /usr/share/locale -mindepth 1 -maxdepth 1 ! -name 'en*' ! -name 'locale.alias' -exec rm -rf {} +
RUN mkdir -p /tmp/.X11-unix /tmp/hermes-runtime && chmod 1777 /tmp/.X11-unix && chmod 0700 /tmp/hermes-runtime

COPY --chmod=0755 --from=build /opt/hermes/docker/tini-shim.sh /usr/bin/tini
RUN mkdir -p /opt/hermes/bin && cp /opt/hermes/docker/hermes-exec-shim.sh /opt/hermes/bin/hermes && \
    chmod 0755 /opt/hermes /opt/hermes/bin/hermes /opt/hermes/docker/entrypoint-dispatch.sh && \
    printf 'docker\n' > /opt/hermes/.install_method && mkdir -p /etc/hermes && \
    HERMES_GIT_SHA="$(cat /opt/hermes/.hermes_build_sha)" python3 -c 'import json, os, pathlib, tomllib; p = tomllib.loads(pathlib.Path("/opt/hermes/pyproject.toml").read_text())["project"]; m = pathlib.Path("/etc/hermes/image-provenance.json"); m.write_text(json.dumps({"schema": 1, "deployment_kind": "image", "manager": "docker", "image": "nousresearch/hermes-agent", "version": p["version"], "revision": os.environ.get("HERMES_GIT_SHA") or None}, sort_keys=True, separators=(",", ":")) + "\n"); m.chmod(0o444)'
RUN cp -r /opt/hermes/docker/s6-rc.d/. /etc/s6-overlay/s6-rc.d/ && mkdir -p /etc/cont-init.d && \
    printf '#!/command/with-contenv sh\nexec /opt/hermes/docker/stage2-hook.sh\n' > /etc/cont-init.d/01-hermes-setup && \
    cp /opt/hermes/docker/cont-init.d/015-supervise-perms /opt/hermes/docker/cont-init.d/02-reconcile-profiles /etc/cont-init.d/ && \
    chmod 0755 /etc/cont-init.d/*

# Wizard add-ons (same as v2026.9.24-wizard2). /claude is the login volume shared with AI Accounts.
COPY --from=addons --chmod=0755 /out/claude /usr/local/bin/claude
COPY --from=addons --chmod=0644 /out/claude-subscription-directsdk-experimental/ /opt/hermes/plugins/model-providers/claude-subscription-directsdk-experimental/
RUN mkdir -p /claude && chown 1000:1000 /claude && chmod 0700 /claude && \
    chmod 0755 /opt/hermes/plugins/model-providers/claude-subscription-directsdk-experimental

ENV HERMES_WEB_DIST=/opt/hermes/hermes_cli/web_dist HERMES_TUI_DIR=/opt/hermes/ui-tui HERMES_HOME=/opt/data \
    HERMES_WRITE_SAFE_ROOT=/opt/data HERMES_DISABLE_LAZY_INSTALLS=1 HERMES_LAZY_INSTALL_TARGET=/opt/data/lazy-packages \
    XDG_RUNTIME_DIR=/tmp/hermes-runtime PATH="/opt/hermes/bin:/opt/hermes/.venv/bin:/opt/data/.local/bin:${PATH}" \
    CLAUDE_CODE_VERSION=2.1.296 DISABLE_AUTOUPDATER=1 CLAUDE_SUBSCRIPTION_DIRECTSDK_COMMAND=/usr/local/bin/claude \
    CLAUDE_SUBSCRIPTION_DIRECTSDK_CONFIG_DIR=/claude
RUN mkdir -p /opt/data
VOLUME [ "/opt/data" ]
LABEL org.opencontainers.image.source="https://github.com/humanitylabs-org/wizard-app-store" \
      org.opencontainers.image.description="Hermes Agent v2026.9.24 (stock source, slim packaging) plus pinned Claude Code and the Claude Subscription DirectSDK plugin" \
      org.opencontainers.image.revision="f97608f178d1ffeca59860195ab7da295f7c8e5f"
ENTRYPOINT [ "/opt/hermes/docker/entrypoint-dispatch.sh" ]
CMD [ ]
