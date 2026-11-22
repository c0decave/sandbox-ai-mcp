# The official MCP filesystem server, @modelcontextprotocol/server-filesystem 2.1.0 (modelcontextprotocol/servers,
# Apache-2.0/MIT; built by upstream CI from commit 194cc86e, npm provenance), MCP over stdio: reads, writes, edits
# (with a diff), moves and searches files in the folders mounted at /work and /ref1-/ref3. No network.
# Started through src/entry.mjs: the allowed directories are exactly the mounted folders, and MCP Roots are never
# used (a client's roots would replace them). package-lock.json pins it and its packages by integrity; see
# PROVENANCE.md for the audit.
ARG DEBIAN_IMAGE=docker.io/library/debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad
# node:24-trixie-slim (Node.js 24.22.1, from nodejs.org checked against its signed SHASUMS256) as docker-library/
# repo-info recorded it on 2026-10-28 (commit 55f75407), the image of servers/memory: build stage only; only its node
# binary goes into the image.
ARG NODE_IMAGE=docker.io/library/node:24-trixie-slim@sha256:89c5244bc22a9bc3287d89ebc7e49b9cb5bb84cd40e6175ac3421d5a9f68b95a

FROM ${NODE_IMAGE} AS build
ARG NODE_VERSION=v24.22.1
# npm ci installs exactly package-lock.json (integrity-checked) and runs no install scripts. 2.1.0 declares glob but
# imports it nowhere (2.2.0 drops it): glob and the three packages only it needs are removed, so what is left is
# what runs - the server (dist/*.js, package.json), @modelcontextprotocol/server and /core, zod, diff, minimatch,
# brace-expansion and balanced-match. The server's eight dist files and its package.json must be the reviewed ones.
COPY package.json package-lock.json /opt/filesystem/
COPY src/entry.mjs /opt/filesystem/entry.mjs
RUN test "$(node --version)" = "${NODE_VERSION}" \
 && cd /opt/filesystem \
 && npm ci --omit=dev --ignore-scripts --no-audit --no-fund --no-update-notifier \
 && rm -rf node_modules/glob node_modules/path-scurry node_modules/lru-cache node_modules/minipass \
      node_modules/.bin node_modules/.package-lock.json \
 && node -e 'const want = {"@modelcontextprotocol/server-filesystem": "2.1.0", "@modelcontextprotocol/server": "2.4.0", "@modelcontextprotocol/core": "2.4.0", "zod": "4.6.7", "diff": "8.0.4", "minimatch": "10.2.6", "brace-expansion": "5.0.12", "balanced-match": "4.0.4"}; for (const [p, v] of Object.entries(want)) { const got = require(`/opt/filesystem/node_modules/${p}/package.json`).version; if (got !== v) { console.error(`${p} ${got}, not ${v}`); process.exit(1); } }' \
 && test "$(ls node_modules | tr '\n' ' ')" = "@modelcontextprotocol balanced-match brace-expansion diff minimatch zod " \
 && test "$(ls node_modules/@modelcontextprotocol | tr '\n' ' ')" = "core server server-filesystem " \
 && test -z "$(find node_modules -mindepth 2 -type d -name node_modules)" \
 && cd node_modules/@modelcontextprotocol/server-filesystem \
 && test "$(ls dist | tr '\n' ' ')" = "index.js lib.js path-utils.js path-validation.js pinned-directory.js roots-utils.js server.js version.js " \
 && echo "fd44be644b81d088eded98d73a5521a179850e716102aa1d7a9edccf6d79fba9  dist/index.js" | sha256sum -c - \
 && echo "7acd502f656812f99e22e0352649564b5ce2707b5623a136239c0da7ab36b72c  dist/lib.js" | sha256sum -c - \
 && echo "5736001d7214f0d8eb47abeb0849f777529c17aa7b8b5c3320209e89bd963f38  dist/path-utils.js" | sha256sum -c - \
 && echo "07fbf314443ad3f4a30ab462b122a18f53bbc895f628e3a5830bca8aed59386b  dist/path-validation.js" | sha256sum -c - \
 && echo "170ab06bde78c692297ead795c279dae77db7c57f1dd37fc907a8304ce8fdd85  dist/pinned-directory.js" | sha256sum -c - \
 && echo "750172b0d92bdcccd17925e04f80b18aeb284e844b1fdd0a457fabf4a3e76ef9  dist/roots-utils.js" | sha256sum -c - \
 && echo "139c72a59734005319ea66463ea4d405bb29b456082b9a6b68074d1063dbbc34  dist/server.js" | sha256sum -c - \
 && echo "044a3819acfb25e8038eb742845502eb255fa719aaa158b4befad5a58a44854d  dist/version.js" | sha256sum -c - \
 && echo "42ddd58e3f5580d07af425bc7394d78496db410c3a522c73c174ea108a051771  package.json" | sha256sum -c - \
 && cp /usr/local/LICENSE /opt/nodejs-LICENSE

FROM ${DEBIAN_IMAGE}
LABEL org.opencontainers.image.source="https://github.com/c0decave/sandbox-ai-mcp" \
      org.opencontainers.image.title="sandbox-ai-mcp-filesystem" \
      org.opencontainers.image.description="The official MCP filesystem server (read, write, edit with diffs, move, search) confined to the mounted folders, no network, an MCP server of sandbox-ai-mcp (stdio)" \
      org.opencontainers.image.licenses="Apache-2.0 AND MIT AND BSD-3-Clause AND BlueOak-1.0.0"
COPY --from=build /usr/local/bin/node /usr/local/bin/node
COPY --from=build /opt/filesystem /opt/filesystem
COPY --from=build /opt/nodejs-LICENSE /usr/share/doc/sandbox-ai-mcp-filesystem/nodejs-LICENSE
COPY LICENSES/ /usr/share/doc/sandbox-ai-mcp-filesystem/
# /work and /ref1-/ref3: empty mount points (the Bubblewrap form binds the folders onto them). An empty one nobody
# mounted is not allowed: entry.mjs allows only the targets /proc/self/mountinfo lists as mount points.
RUN useradd --uid 10001 --user-group --no-create-home --home-dir /tmp --shell /usr/sbin/nologin mcp \
 && mkdir -m 0755 /work /ref1 /ref2 /ref3 \
 && /usr/local/bin/node --version
ENV HOME=/tmp NODE_ENV=production
# The usual mount targets exist in every image (a read-only rootfs under Bubblewrap cannot create them).
RUN mkdir -p -m 0755 /work /work_ro /work_rw /app /srv
USER 10001:10001
WORKDIR /tmp
# --disallow-code-generation-from-strings: no eval/new Function at all (zod then validates without its JIT).
# The arguments are the candidate folders; sandbox-ai and axross add none.
ENTRYPOINT ["/usr/local/bin/node", "--disallow-code-generation-from-strings", "/opt/filesystem/entry.mjs", \
            "/work", "/ref1", "/ref2", "/ref3"]
