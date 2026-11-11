# Playwright MCP 0.0.83 (microsoft/playwright-mcp, Apache-2.0) with Debian's Chromium, MCP over stdio.
# The tools themselves live in playwright-core (microsoft/playwright, Apache-2.0), which the release's
# package-lock.json pins by integrity hash. See PROVENANCE.md for the audit and the pins.
ARG DEBIAN_IMAGE=docker.io/library/debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad
FROM ${DEBIAN_IMAGE} AS build
# Debian versions from the trixie / trixie-security indexes of 2026-11-05 (docs/CANDIDATES.md).
ARG NODEJS_VERSION=20.19.2+dfsg-1+deb13u3
ARG NPM_VERSION=9.2.0~ds1-3
ARG GIT_VERSION=1:2.47.3-0+deb13u1
# (npm 9 leaves the scope folders of the dev dependencies it omits, empty: removed before the check below.)
# The commit of the tag v0.0.83 (2026-09-28). npm ci installs exactly what its package-lock.json pins:
# playwright and playwright-core 1.64.0-alpha-1790635538000 (microsoft/playwright e8149b82), by integrity.
ARG PLAYWRIGHT_MCP_COMMIT=f183dad4a52965583e3cc1d59b88cdc279e2e57d
ARG PLAYWRIGHT_VERSION=1.64.0-alpha-1790635538000
RUN apt-get update \
 && apt-get install -y --no-install-recommends nodejs=${NODEJS_VERSION} npm=${NPM_VERSION} git=${GIT_VERSION} \
      ca-certificates=20250419+deb13u1
RUN git init --quiet /opt/playwright-mcp \
 && git -C /opt/playwright-mcp fetch --quiet --depth 1 https://github.com/microsoft/playwright-mcp ${PLAYWRIGHT_MCP_COMMIT} \
 && git -C /opt/playwright-mcp checkout --quiet FETCH_HEAD \
 && test "$(git -C /opt/playwright-mcp rev-parse HEAD)" = "${PLAYWRIGHT_MCP_COMMIT}"
# No install scripts (no browser download); only what runs is kept: cli.js, package.json, the licence
# and the two runtime packages (the MCP SDK, zod and the rest are bundled into playwright-core).
RUN cd /opt/playwright-mcp \
 && PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm ci --omit=dev --ignore-scripts --no-audit --no-fund --no-update-notifier \
 && node -e 'for (const p of ["playwright", "playwright-core"]) { const v = require(`/opt/playwright-mcp/node_modules/${p}/package.json`).version; if (v !== process.argv[1]) { console.error(`${p} ${v}`); process.exit(1); } }' "${PLAYWRIGHT_VERSION}" \
 && find node_modules -mindepth 1 -maxdepth 1 -type d -empty -delete \
 && test "$(ls node_modules | sort | tr '\n' ' ')" = "playwright playwright-core " \
 && find . -mindepth 1 -maxdepth 1 ! -name cli.js ! -name package.json ! -name LICENSE ! -name node_modules \
      -exec rm -rf {} +

FROM ${DEBIAN_IMAGE}
ARG NODEJS_VERSION=20.19.2+dfsg-1+deb13u3
ARG CHROMIUM_VERSION=156.0.8078.79-1~deb13u1
LABEL org.opencontainers.image.source="https://github.com/c0decave/sandbox-ai-mcp" \
      org.opencontainers.image.title="sandbox-ai-mcp-playwright" \
      org.opencontainers.image.description="Browser automation with Playwright MCP and Chromium, an MCP server of sandbox-ai-mcp (stdio)" \
      org.opencontainers.image.licenses="Apache-2.0"
RUN apt-get update \
 && apt-get install -y --no-install-recommends nodejs=${NODEJS_VERSION} chromium=${CHROMIUM_VERSION} \
      ca-certificates=20250419+deb13u1 fonts-liberation=1:2.1.5-3 tini=0.19.0-3+b8 \
 && rm -rf /var/lib/apt/lists/* /var/cache/apt /var/log/apt /var/log/dpkg.log
COPY --from=build /opt/playwright-mcp /opt/playwright-mcp
COPY LICENSES/ /usr/share/doc/sandbox-ai-mcp-playwright/
RUN useradd --uid 10001 --user-group --no-create-home --home-dir /tmp --shell /usr/sbin/nologin mcp
ENV HOME=/tmp
USER 10001:10001
WORKDIR /tmp
# Chromium's own sandbox needs user namespaces the container does not grant: the container is the
# sandbox (no capabilities, read-only root, no new privileges). --isolated: the profile is a temporary
# directory under /tmp, gone with the container. --no-webmcp: a page cannot add tools of its own to
# the server's tool list. --executable-path takes Debian's Chromium (Playwright downloads nothing).
# tini -s reaps Chromium's orphans also where it is not PID 1 (podman's --init, Bubblewrap).
ENTRYPOINT ["/usr/bin/tini", "-s", "--", "/usr/bin/node", "/opt/playwright-mcp/cli.js", "--headless", "--isolated", \
            "--no-sandbox", "--browser", "chromium", "--executable-path", "/usr/bin/chromium", \
            "--output-dir", "/tmp/playwright-output", "--no-webmcp"]
