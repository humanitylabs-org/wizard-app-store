FROM node:22-alpine@sha256:0a7108bf6c7bf5de370ffb1a3ed6be93d405b43ff159f681a8d18c0e2bc2e402 AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts --no-audit --no-fund && npm cache clean --force

FROM deps AS test
COPY server.mjs ./
COPY tests/*.unit.mjs ./tests/
USER 1000:1000
CMD ["node", "--test", "tests/server.unit.mjs"]

FROM node:22-alpine@sha256:0a7108bf6c7bf5de370ffb1a3ed6be93d405b43ff159f681a8d18c0e2bc2e402 AS runtime
LABEL org.opencontainers.image.source="https://github.com/humanitylabs-org/wizard-app-store" \
      org.opencontainers.image.description="Per-agent attesting EHBP client; provider keys stay in the relay"
ENV NODE_ENV=production LISTEN_PORT=3301 RELAY_TOKEN_FILE=/run/wizard/relay-token
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY package.json server.mjs ./
USER 1000:1000
EXPOSE 3301
HEALTHCHECK --interval=30s --timeout=5s CMD ["node", "-e", "fetch('http://'+(process.env.LISTEN_HOST||'127.0.0.1')+':'+process.env.LISTEN_PORT+'/healthz').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"]
CMD ["node", "server.mjs"]
