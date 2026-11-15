# The official MCP sequential-thinking server, @modelcontextprotocol/server-sequential-thinking 2.0.0
# (modelcontextprotocol/servers, Apache-2.0/MIT; built by upstream CI from commit 51b6382a, npm provenance), MCP over
# stdio. One tool that keeps a chain of thoughts in memory for the length of one connection. No network, no files.
# package-lock.json pins it and its packages by integrity; see PROVENANCE.md for the audit.
ARG DEBIAN_IMAGE=docker.io/library/debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad
# node:24-trixie-slim (Node.js 24.22.1, from nodejs.org checked against its signed SHASUMS256) as docker-library/
# repo-info recorded it on 2026-10-28 (commit 55f75407), the image of servers/memory: build stage only; only its node
# binary goes into the image.
ARG NODE_IMAGE=docker.io/library/node:24-trixie-slim@sha256:89c5244bc22a9bc3287d89ebc7e49b9cb5bb84cd40e6175ac3421d5a9f68b95a

FROM ${NODE_IMAGE} AS build
ARG NODE_VERSION=v24.22.1
# npm ci installs exactly package-lock.json (integrity-checked) and runs no install scripts. 2.0.0 declares yargs but
# imports it nowhere: yargs and the eleven packages only it needs are removed, so what is left is what runs - the
# server (dist/index.js, dist/lib.js, dist/version.js, package.json), @modelcontextprotocol/server and /core, zod and
# chalk.
COPY package.json package-lock.json /opt/sequential-thinking/
RUN test "$(node --version)" = "${NODE_VERSION}" \
 && cd /opt/sequential-thinking \
 && npm ci --omit=dev --ignore-scripts --no-audit --no-fund --no-update-notifier \
 && rm -rf node_modules/yargs node_modules/yargs-parser node_modules/cliui node_modules/escalade \
      node_modules/get-caller-file node_modules/require-directory node_modules/y18n node_modules/string-width \
      node_modules/strip-ansi node_modules/ansi-regex node_modules/wrap-ansi node_modules/ansi-styles \
      node_modules/color-convert node_modules/color-name node_modules/emoji-regex node_modules/is-fullwidth-code-point \
      node_modules/.bin node_modules/.package-lock.json \
 && node -e 'const want = {"@modelcontextprotocol/server-sequential-thinking": "2.0.0", "@modelcontextprotocol/server": "2.4.0", "@modelcontextprotocol/core": "2.4.0", "zod": "4.6.7", "chalk": "5.6.2"}; for (const [p, v] of Object.entries(want)) { const got = require(`/opt/sequential-thinking/node_modules/${p}/package.json`).version; if (got !== v) { console.error(`${p} ${got}, not ${v}`); process.exit(1); } }' \
 && test "$(ls node_modules | tr '\n' ' ')" = "@modelcontextprotocol chalk zod " \
 && test "$(ls node_modules/@modelcontextprotocol | tr '\n' ' ')" = "core server server-sequential-thinking " \
 && test -z "$(find node_modules -mindepth 2 -type d -name node_modules)" \
 && echo "209921bc90eaaedb484ddd75471452ecc254086bcb0ffda395a99619332760b3  node_modules/@modelcontextprotocol/server-sequential-thinking/dist/index.js" | sha256sum -c - \
 && echo "dd1a882a435cd672b0da9a407a0445a4dcf53fa4374572eb5d79815b5ccd56e2  node_modules/@modelcontextprotocol/server-sequential-thinking/dist/lib.js" | sha256sum -c - \
 && echo "ae5a797a13cbc960f2303f2af3b2429135694875547e2dfb3b9700e4f8e10f19  node_modules/@modelcontextprotocol/server-sequential-thinking/dist/version.js" | sha256sum -c - \
 && cp /usr/local/LICENSE /opt/nodejs-LICENSE

FROM ${DEBIAN_IMAGE}
LABEL org.opencontainers.image.source="https://github.com/c0decave/sandbox-ai-mcp" \
      org.opencontainers.image.title="sandbox-ai-mcp-sequential-thinking" \
      org.opencontainers.image.description="The official MCP sequential-thinking server (a chain of thoughts kept for one connection), no network, an MCP server of sandbox-ai-mcp (stdio)" \
      org.opencontainers.image.licenses="Apache-2.0 AND MIT"
COPY --from=build /usr/local/bin/node /usr/local/bin/node
COPY --from=build /opt/sequential-thinking /opt/sequential-thinking
COPY --from=build /opt/nodejs-LICENSE /usr/share/doc/sandbox-ai-mcp-sequential-thinking/nodejs-LICENSE
COPY LICENSES/ /usr/share/doc/sandbox-ai-mcp-sequential-thinking/
RUN useradd --uid 10001 --user-group --no-create-home --home-dir /tmp --shell /usr/sbin/nologin mcp \
 && /usr/local/bin/node --version
# DISABLE_THOUGHT_LOGGING: otherwise every thought is drawn as a box on stderr (into sandbox-ai's logs, three times
# the thought's size in memory while it is drawn); fixed here, not offered as a variable.
ENV HOME=/tmp NODE_ENV=production DISABLE_THOUGHT_LOGGING=true
USER 10001:10001
WORKDIR /tmp
# --disallow-code-generation-from-strings: no eval/new Function at all (zod then validates without its JIT).
ENTRYPOINT ["/usr/local/bin/node", "--disallow-code-generation-from-strings", \
            "/opt/sequential-thinking/node_modules/@modelcontextprotocol/server-sequential-thinking/dist/index.js"]
