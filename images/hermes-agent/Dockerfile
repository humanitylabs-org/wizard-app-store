# Hermes Agent (Wizard build): the official image, unchanged, plus two official add-ons so Hermes can use
# the owner's Claude subscription signed in once in the AI Accounts app:
#   - Claude Code (Anthropic's official native CLI), pinned and integrity-checked, auto-update off;
#   - NousResearch's Claude Subscription DirectSDK (Experimental) provider plugin, pinned (MIT).
# and, on Hermes v0.22+ bases, the holographic memory provider that left Hermes core, pinned at the commit
# Hermes' own catalog names, so agents never download it at first start (wizard-app-manager#856).
# The plugin sits in Hermes' bundled model-provider folder, which Hermes discovers on its own: no config
# edit, nothing written to /opt/data, and the selected provider/model stay exactly as the owner set them.
# BASE_IMAGE is the official Hermes image this build extends (pinned by digest). The default is the
# legacy store's engine; ai-accounts.yml also builds the App Manager boxes' engine (v2026.9.24) from it.
ARG BASE_IMAGE=nousresearch/hermes-agent:v0.23.3@sha256:3e9fe4c6ef36490f43aa0d0d80f9df64e9c92a576eee3042f1a97c8813c05355
FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258 AS addons
ARG TARGETARCH
COPY fetch-claude-code.py fetch-directsdk-plugin.py fetch-holographic-plugin.py /
RUN python3 /fetch-claude-code.py "$TARGETARCH" /out/claude \
 && python3 /fetch-directsdk-plugin.py /out/claude-subscription-directsdk-experimental \
 && python3 /fetch-holographic-plugin.py /out/holographic

FROM ${BASE_IMAGE}
ARG BASE_IMAGE
COPY --from=addons --chmod=0755 /out/claude /usr/local/bin/claude
COPY --from=addons --chmod=0644 /out/claude-subscription-directsdk-experimental/ /opt/hermes/plugins/model-providers/claude-subscription-directsdk-experimental/
# /claude is the login volume shared with AI Accounts (uid/gid 1000, as HERMES_UID/HERMES_GID).
# Only the plugin is pointed at it. CLAUDE_CONFIG_DIR stays unset on purpose: Hermes core would otherwise
# adopt that OAuth login for its own direct Anthropic client, and the login must only ever be used by
# the official Claude Code binary.
# The install stamp tells Hermes its own version; it must stay world-readable for the unprivileged
# gateway user whatever umask built the base layer (root:0600 made it report "vunknown"); older bases
# (v2026.9.24) have no stamp.
# Holographic memory goes where it lived in core (same provider name, config and memory_store.db), so Hermes
# finds it bundled and its left-core migration never fetches the plugin from GitHub. Bases that still ship it
# in core (v2026.9.24) keep their own copy untouched.
RUN --mount=type=bind,from=addons,source=/out/holographic,target=/mnt/holographic \
    mkdir -p /claude && chown 1000:1000 /claude && chmod 0700 /claude \
 && chmod 0755 /opt/hermes/plugins/model-providers/claude-subscription-directsdk-experimental \
 && if [ -e /opt/hermes/install-stamp.json ]; then chmod 0644 /opt/hermes/install-stamp.json; fi \
 && if [ ! -e /opt/hermes/plugins/memory/holographic ]; then \
      cp -R /mnt/holographic /opt/hermes/plugins/memory/holographic \
      && chown -R 0:0 /opt/hermes/plugins/memory/holographic \
      && find /opt/hermes/plugins/memory/holographic -type d -exec chmod 0755 {} + \
      && find /opt/hermes/plugins/memory/holographic -type f -exec chmod 0644 {} + ; \
    fi
ENV CLAUDE_CODE_VERSION=2.1.296 \
    DISABLE_AUTOUPDATER=1 \
    CLAUDE_SUBSCRIPTION_DIRECTSDK_COMMAND=/usr/local/bin/claude \
    CLAUDE_SUBSCRIPTION_DIRECTSDK_CONFIG_DIR=/claude
LABEL org.opencontainers.image.source="https://github.com/humanitylabs-org/wizard-app-store" \
      org.opencontainers.image.description="Official Hermes Agent (${BASE_IMAGE}) plus pinned Claude Code, the official Claude Subscription DirectSDK plugin 0.4.1, with holographic memory built in" \
      org.opencontainers.image.base.name="docker.io/${BASE_IMAGE}"
