# Chrome DevTools MCP 1.12.0 (ChromeDevTools/chrome-devtools-mcp, Apache-2.0) with Debian's Chromium, MCP over stdio:
# a headless Chromium of its own, driven through Puppeteer over a pipe (no debugging port), with DevTools' analysis
# (snapshots, console, network, performance traces, Lighthouse, heap snapshots). The npm package bundles all of its
# code (no runtime dependencies), so package-lock.json pins all of it by one integrity hash. See PROVENANCE.md.
ARG DEBIAN_IMAGE=docker.io/library/debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad
# node:24-trixie-slim (Node.js 24.22.1, from nodejs.org checked against its signed SHASUMS256) as docker-library/
# repo-info recorded it on 2026-10-28 (commit 55f75407), the image of servers/memory: build stage only; only its node
# binary goes into the image.
ARG NODE_IMAGE=docker.io/library/node:24-trixie-slim@sha256:89c5244bc22a9bc3287d89ebc7e49b9cb5bb84cd40e6175ac3421d5a9f68b95a

FROM ${NODE_IMAGE} AS build
ARG NODE_VERSION=v24.22.1
# npm ci installs exactly package-lock.json (the release tarball by its integrity) and runs no install scripts. Removed
# afterwards, so that they cannot run: the usage-statistics sender (telemetry/watchdog: Clearcut logging to
# play.googleapis.com), the npm update check (bin/check-latest-version.js), the separate CLI with its daemon, and the
# agent skills (Markdown). Every file left must be the reviewed one (chrome-devtools-files.sha256), and none other.
COPY package.json package-lock.json chrome-devtools-files.sha256 /opt/chrome-devtools/
RUN test "$(node --version)" = "${NODE_VERSION}" \
 && cd /opt/chrome-devtools \
 && npm ci --omit=dev --ignore-scripts --no-audit --no-fund --no-update-notifier \
 && test "$(ls node_modules)" = "chrome-devtools-mcp" \
 && cd node_modules/chrome-devtools-mcp \
 && rm -r skills build/src/telemetry/watchdog build/src/daemon/client.js build/src/daemon/daemon.js \
      build/src/daemon/types.js build/src/bin/check-latest-version.js build/src/bin/chrome-devtools.js \
      build/src/config/cli-commands.js build/src/config/cli-options.js build/src/telemetry/metricsRegistry.js \
 && sha256sum --check --strict --quiet /opt/chrome-devtools/chrome-devtools-files.sha256 \
 && test "$(find . -type f | wc -l)" = "$(wc -l < /opt/chrome-devtools/chrome-devtools-files.sha256)" \
 && rm -rf /opt/chrome-devtools/node_modules/.bin /opt/chrome-devtools/node_modules/.package-lock.json \
      /opt/chrome-devtools/chrome-devtools-files.sha256 \
 && cp /usr/local/LICENSE /opt/nodejs-LICENSE

FROM ${DEBIAN_IMAGE}
# Debian versions from the trixie / trixie-security indexes of 2026-11-05, the same as servers/playwright.
ARG CHROMIUM_VERSION=156.0.8078.79-1~deb13u1
LABEL org.opencontainers.image.source="https://github.com/c0decave/sandbox-ai-mcp" \
      org.opencontainers.image.title="sandbox-ai-mcp-chrome-devtools" \
      org.opencontainers.image.description="Browser debugging and automation with Chrome DevTools MCP and a headless Chromium, an MCP server of sandbox-ai-mcp (stdio)" \
      org.opencontainers.image.licenses="Apache-2.0"
RUN apt-get update \
 && apt-get install -y --no-install-recommends chromium=${CHROMIUM_VERSION} \
      ca-certificates=20250419+deb13u1 fonts-liberation=1:2.1.5-3 tini=0.19.0-3+b8 \
 && rm -rf /var/lib/apt/lists/* /var/cache/apt /var/log/apt /var/log/dpkg.log
COPY --from=build /usr/local/bin/node /usr/local/bin/node
COPY --from=build /opt/chrome-devtools /opt/chrome-devtools
COPY --from=build /opt/nodejs-LICENSE /usr/share/doc/sandbox-ai-mcp-chrome-devtools/nodejs-LICENSE
COPY LICENSES/ /usr/share/doc/sandbox-ai-mcp-chrome-devtools/
RUN useradd --uid 10001 --user-group --no-create-home --home-dir /tmp --shell /usr/sbin/nologin mcp \
 && /usr/local/bin/node --version
# No usage statistics (also --no-usage-statistics below), no npm update check, no configuration file looked up in
# $HOME/.config/cd4a (every option is on the command line below).
ENV HOME=/tmp NODE_ENV=production CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS=1 CHROME_DEVTOOLS_MCP_NO_UPDATE_CHECKS=1 \
    CHROME_DEVTOOLS_MCP_NO_CONFIG_DISCOVERY=1
# /etc/hosts of its own (a COPY: a build mounts its own over the image's; Podman and Docker mount theirs at run
# time): the Bubblewrap form has the file sandbox-ai binds an allowlist server's pinned hosts onto, and resolvers
# that read it (Ruby's) find it there.
COPY hosts /etc/hosts
# The usual mount targets exist in every image (a read-only rootfs under Bubblewrap cannot create them).
RUN mkdir -p -m 0755 /work /work_ro /work_rw /app /srv
USER 10001:10001
WORKDIR /tmp
# Chromium's own sandbox needs user namespaces the container does not grant: the container is the sandbox (no
# capabilities, read-only root, no new privileges), as for servers/playwright. --isolated: a temporary profile under
# /tmp, removed when the browser closes. --no-performance-crux: performance traces send no URLs to Google's CrUX API.
# --no-file-navigations: no file: URL is opened. The categories that are off by default are switched off explicitly,
# so that no variable turns them on (CHROME_DEVTOOLS_MCP_CATEGORY_EXPERIMENTAL_THIRD_PARTY would): no tools a web page
# offers (third-party, WebMCP), no extensions, no installed web apps. Puppeteer talks to Chromium over a pipe: no
# debugging port. tini -s reaps Chromium's orphans also where it is not PID 1 (podman's --init, Bubblewrap).
ENTRYPOINT ["/usr/bin/tini", "-s", "--", "/usr/local/bin/node", \
            "/opt/chrome-devtools/node_modules/chrome-devtools-mcp/build/src/bin/chrome-devtools-mcp.js", \
            "--headless", "--isolated", "--executable-path", "/usr/bin/chromium", "--chrome-arg=--no-sandbox", \
            "--no-usage-statistics", "--no-performance-crux", "--no-file-navigations", \
            "--no-category-experimental-third-party", "--no-category-experimental-webmcp", "--no-category-extensions", \
            "--no-category-pwa"]
