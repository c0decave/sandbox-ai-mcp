# Context7 MCP 4.5.0 (upstash/context7 packages/mcp, @upstash/context7-mcp, MIT), MCP over stdio: a client of the
# Context7 documentation API (context7.com) - two tools that send a library name or ID and a question there and return
# the documentation text it answers with. Network: allowlist context7.com:443; CONTEXT7_API_KEY optional.
# package-lock.json pins the release and its packages by integrity; prepare.mjs keeps only what runs on the stdio path
# with OpenTelemetry off and applies four patches; context7-files.sha256 pins every file of the server. See
# PROVENANCE.md for the audit.
ARG DEBIAN_IMAGE=docker.io/library/debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad
# node:24-trixie-slim (Node.js 24.22.1, from nodejs.org checked against its signed SHASUMS256) as docker-library/
# repo-info recorded it on 2026-10-28 (commit 55f75407), the image of servers/memory: build stage only; only its node
# binary goes into the image.
ARG NODE_IMAGE=docker.io/library/node:24-trixie-slim@sha256:89c5244bc22a9bc3287d89ebc7e49b9cb5bb84cd40e6175ac3421d5a9f68b95a

FROM ${NODE_IMAGE} AS build
ARG NODE_VERSION=v24.22.1
# npm ci installs exactly package-lock.json (integrity-checked) and runs no install scripts; prepare.mjs then removes
# the packages that never load (OpenTelemetry, require-in-the-middle, import-in-the-middle, hono, @types), checks the
# 74 that are left against their locked versions, removes the server's telemetry modules and applies the patches
# (each file checked by SHA-256 before and after). Every file of the server must then be the reviewed one.
COPY package.json package-lock.json prepare.mjs context7-files.sha256 /opt/context7/
RUN test "$(node --version)" = "${NODE_VERSION}" \
 && cd /opt/context7 \
 && npm ci --omit=dev --ignore-scripts --no-audit --no-fund --no-update-notifier \
 && node prepare.mjs node_modules \
 && cd node_modules/@upstash/context7-mcp \
 && sha256sum --check --strict --quiet /opt/context7/context7-files.sha256 \
 && cd /opt/context7 \
 && rm prepare.mjs context7-files.sha256 \
 && cp /usr/local/LICENSE /opt/nodejs-LICENSE

FROM ${DEBIAN_IMAGE}
LABEL org.opencontainers.image.source="https://github.com/c0decave/sandbox-ai-mcp" \
      org.opencontainers.image.title="sandbox-ai-mcp-context7" \
      org.opencontainers.image.description="Current library documentation from Context7 (context7.com), an MCP server of sandbox-ai-mcp (stdio)" \
      org.opencontainers.image.licenses="MIT"
COPY --from=build /usr/local/bin/node /usr/local/bin/node
COPY --from=build /opt/context7 /opt/context7
COPY --from=build /opt/nodejs-LICENSE /usr/share/doc/sandbox-ai-mcp-context7/nodejs-LICENSE
COPY LICENSES/ /usr/share/doc/sandbox-ai-mcp-context7/
RUN useradd --uid 10001 --user-group --no-create-home --home-dir /tmp --shell /usr/sbin/nologin mcp \
 && /usr/local/bin/node --version
# OTEL_SDK_DISABLED=true: the server loads no telemetry at all (its telemetry modules are not even in the image, so
# the server refuses to start without it). CONTEXT7_API_KEY (optional) comes from sandbox-ai's secret store.
ENV HOME=/tmp NODE_ENV=production OTEL_SDK_DISABLED=true
USER 10001:10001
WORKDIR /tmp
# --disallow-code-generation-from-strings: no eval/new Function at all (zod then validates without its JIT).
ENTRYPOINT ["/usr/local/bin/node", "--disallow-code-generation-from-strings", \
            "/opt/context7/node_modules/@upstash/context7-mcp/dist/index.js", "--transport", "stdio"]
