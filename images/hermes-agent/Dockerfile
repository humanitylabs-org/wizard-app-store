# Hermes Agent (Wizard build): the official image, unchanged, plus two official add-ons so Hermes can use
# the owner's Claude subscription signed in once in the AI Accounts app:
#   - Claude Code (Anthropic's official native CLI), pinned and integrity-checked, auto-update off;
#   - NousResearch's Claude Subscription DirectSDK (Experimental) provider plugin, pinned (MIT).
# The plugin sits in Hermes' bundled model-provider folder, which Hermes discovers on its own: no config
# edit, nothing written to /opt/data, and the selected provider/model stay exactly as the owner set them.
FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258 AS addons
ARG TARGETARCH
COPY fetch-claude-code.py fetch-directsdk-plugin.py /
RUN python3 /fetch-claude-code.py "$TARGETARCH" /out/claude \
 && python3 /fetch-directsdk-plugin.py /out/claude-subscription-directsdk-experimental

FROM nousresearch/hermes-agent:v2026.9.24@sha256:fca358f12efd65bfaaca05884166f15c0e2788375ca30d77061ac1ebc96452b7
COPY --from=addons --chmod=0755 /out/claude /usr/local/bin/claude
COPY --from=addons --chmod=0644 /out/claude-subscription-directsdk-experimental/ /opt/hermes/plugins/model-providers/claude-subscription-directsdk-experimental/
# /claude is the login volume shared with AI Accounts (uid/gid 1000, as HERMES_UID/HERMES_GID).
# Only the plugin is pointed at it. CLAUDE_CONFIG_DIR stays unset on purpose: Hermes core would otherwise
# adopt that OAuth login for its own direct Anthropic client, and the login must only ever be used by
# the official Claude Code binary.
RUN mkdir -p /claude && chown 1000:1000 /claude && chmod 0700 /claude \
 && chmod 0755 /opt/hermes/plugins/model-providers/claude-subscription-directsdk-experimental
ENV CLAUDE_CODE_VERSION=2.1.263 \
    DISABLE_AUTOUPDATER=1 \
    CLAUDE_SUBSCRIPTION_DIRECTSDK_COMMAND=/usr/local/bin/claude \
    CLAUDE_SUBSCRIPTION_DIRECTSDK_CONFIG_DIR=/claude
LABEL org.opencontainers.image.source="https://github.com/humanitylabs-org/wizard-app-store" \
      org.opencontainers.image.description="Official Hermes Agent v2026.9.24 plus pinned Claude Code and the official Claude Subscription DirectSDK plugin" \
      org.opencontainers.image.base.name="docker.io/nousresearch/hermes-agent:v2026.9.24"
