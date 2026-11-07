# Playwright MCP 0.0.84 (microsoft/playwright-mcp, Apache-2.0) with Debian's Chromium, MCP over stdio.
# PREPARED, NOT YET BUILT: the Debian package versions are not pinned here (this repository pins
# every package by version). Fill NODEJS_VERSION, NPM_VERSION, GIT_VERSION and CHROMIUM_VERSION
# with the versions of the pinned base (podman run --rm BASE sh -c 'apt-get update -qq &&
# apt-cache policy nodejs npm git chromium'), then move this folder to servers/ and add it to the
# CI matrix. Without them the build stops at the first RUN.
ARG DEBIAN_IMAGE=docker.io/library/debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad
FROM ${DEBIAN_IMAGE} AS build
ARG NODEJS_VERSION
ARG NPM_VERSION
ARG GIT_VERSION
# The commit of the tag v0.0.84; npm ci installs exactly what its package-lock.json pins (integrity hashes).
ARG PLAYWRIGHT_MCP_COMMIT=be26c080edfae7c761db1e757c4aff9f6453b4d7
RUN test -n "${NODEJS_VERSION}" && test -n "${NPM_VERSION}" && test -n "${GIT_VERSION}" \
      || { echo "pin NODEJS_VERSION, NPM_VERSION and GIT_VERSION (see the top of this file)" >&2; exit 1; }
RUN apt-get update \
 && apt-get install -y --no-install-recommends nodejs=${NODEJS_VERSION} npm=${NPM_VERSION} git=${GIT_VERSION} \
      ca-certificates=20250419+deb13u1
RUN git clone --quiet https://github.com/microsoft/playwright-mcp /opt/playwright-mcp \
 && git -C /opt/playwright-mcp checkout --quiet ${PLAYWRIGHT_MCP_COMMIT} \
 && test "$(git -C /opt/playwright-mcp rev-parse HEAD)" = "${PLAYWRIGHT_MCP_COMMIT}" \
 && cd /opt/playwright-mcp && PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm ci --omit=dev --ignore-scripts \
 && rm -rf .git

FROM ${DEBIAN_IMAGE}
ARG NODEJS_VERSION
ARG CHROMIUM_VERSION
LABEL org.opencontainers.image.source="https://github.com/c0decave/sandbox-ai-mcp" \
      org.opencontainers.image.title="sandbox-ai-mcp-playwright" \
      org.opencontainers.image.description="Browser automation with Playwright MCP and Chromium, an MCP server of sandbox-ai-mcp (stdio)" \
      org.opencontainers.image.licenses="Apache-2.0"
RUN test -n "${CHROMIUM_VERSION}" || { echo "pin CHROMIUM_VERSION (see the top of this file)" >&2; exit 1; }
RUN apt-get update \
 && apt-get install -y --no-install-recommends nodejs=${NODEJS_VERSION} chromium=${CHROMIUM_VERSION} \
      ca-certificates=20250419+deb13u1 fonts-liberation tini \
 && rm -rf /var/lib/apt/lists/*
COPY --from=build /opt/playwright-mcp /opt/playwright-mcp
COPY LICENSES/ /usr/share/doc/sandbox-ai-mcp-playwright/
RUN useradd --uid 10001 --user-group --no-create-home --home-dir /tmp --shell /usr/sbin/nologin mcp
ENV HOME=/tmp
USER 10001:10001
WORKDIR /tmp
# Chromium's own sandbox needs user namespaces the container does not grant: the container is the
# sandbox (no capabilities, read-only root, no new privileges). The profile stays in memory.
ENTRYPOINT ["/usr/bin/tini", "--", "node", "/opt/playwright-mcp/cli.js", "--headless", "--isolated", \
            "--no-sandbox", "--browser", "chromium", "--executable-path", "/usr/bin/chromium", \
            "--output-dir", "/tmp/playwright-output"]
