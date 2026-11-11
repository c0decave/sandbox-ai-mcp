# The official MCP Knowledge Graph memory server, @modelcontextprotocol/server-memory 2.0.1 (modelcontextprotocol/
# servers, Apache-2.0/MIT; built by upstream CI from commit 194cc86e, npm provenance), MCP over stdio. Entities,
# relations and observations in one JSONL file, /data/memory.jsonl, in the folder mounted at /data. No network.
# package-lock.json pins it and its three runtime packages by integrity; see PROVENANCE.md for the audit.
ARG DEBIAN_IMAGE=docker.io/library/debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad
# node:24-trixie-slim (Node.js 24.22.1, from nodejs.org checked against its signed SHASUMS256) as docker-library/
# repo-info recorded it on 2026-10-28 (commit 55f75407): build stage only; only its node binary goes into the image.
ARG NODE_IMAGE=docker.io/library/node:24-trixie-slim@sha256:89c5244bc22a9bc3287d89ebc7e49b9cb5bb84cd40e6175ac3421d5a9f68b95a

FROM ${NODE_IMAGE} AS build
ARG NODE_VERSION=v24.22.1
# npm ci installs exactly package-lock.json (integrity-checked), runs no install scripts and keeps only what runs:
# the server (dist/index.js, dist/version.js, package.json) and @modelcontextprotocol/server, /core and zod.
COPY package.json package-lock.json /opt/memory/
RUN test "$(node --version)" = "${NODE_VERSION}" \
 && cd /opt/memory \
 && npm ci --omit=dev --ignore-scripts --no-audit --no-fund --no-update-notifier \
 && node -e 'const want = {"@modelcontextprotocol/server-memory": "2.0.1", "@modelcontextprotocol/server": "2.4.0", "@modelcontextprotocol/core": "2.4.0", "zod": "4.6.7"}; for (const [p, v] of Object.entries(want)) { const got = require(`/opt/memory/node_modules/${p}/package.json`).version; if (got !== v) { console.error(`${p} ${got}, not ${v}`); process.exit(1); } }' \
 && test "$(ls node_modules | tr '\n' ' ')" = "@modelcontextprotocol zod " \
 && test "$(ls node_modules/@modelcontextprotocol | tr '\n' ' ')" = "core server server-memory " \
 && test -z "$(find node_modules -mindepth 2 -type d -name node_modules)" \
 && echo "779ae2294db562c14dfc347555f6ff5fa0bce87e00377c401ccb2df642928450  node_modules/@modelcontextprotocol/server-memory/dist/index.js" | sha256sum -c - \
 && echo "a65814e1815264d0a88c697ec9fd678e43168329cd722d8093e53172eae6e73f  node_modules/@modelcontextprotocol/server-memory/dist/version.js" | sha256sum -c - \
 && rm -rf node_modules/.bin \
 && cp /usr/local/LICENSE /opt/nodejs-LICENSE

FROM ${DEBIAN_IMAGE}
LABEL org.opencontainers.image.source="https://github.com/c0decave/sandbox-ai-mcp" \
      org.opencontainers.image.title="sandbox-ai-mcp-memory" \
      org.opencontainers.image.description="The official MCP Knowledge Graph memory server (entities, relations, observations in /data/memory.jsonl), no network, an MCP server of sandbox-ai-mcp (stdio)" \
      org.opencontainers.image.licenses="Apache-2.0 AND MIT"
COPY --from=build /usr/local/bin/node /usr/local/bin/node
COPY --from=build /opt/memory /opt/memory
COPY --from=build /opt/nodejs-LICENSE /usr/share/doc/sandbox-ai-mcp-memory/nodejs-LICENSE
COPY LICENSES/ /usr/share/doc/sandbox-ai-mcp-memory/
# /data: the graph's folder, mounted writable (memory.jsonl, its .lock while a write runs, the temporary file a
# write renames over it). Without a mount it is part of the read-only root: the server starts, every write fails.
RUN useradd --uid 10001 --user-group --no-create-home --home-dir /tmp --shell /usr/sbin/nologin mcp \
 && mkdir -m 0755 /data \
 && /usr/local/bin/node --version
# MEMORY_FILE_PATH is fixed here and not offered as a variable: the graph is always /data/memory.jsonl.
ENV HOME=/tmp NODE_ENV=production MEMORY_FILE_PATH=/data/memory.jsonl
USER 10001:10001
WORKDIR /tmp
# --disallow-code-generation-from-strings: no eval/new Function at all (zod then validates without its JIT).
ENTRYPOINT ["/usr/local/bin/node", "--disallow-code-generation-from-strings", \
            "/opt/memory/node_modules/@modelcontextprotocol/server-memory/dist/index.js"]
