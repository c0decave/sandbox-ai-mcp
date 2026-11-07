# REA 6.8.0 (morluto/rea, npm rea-agents, MIT), reverse-engineering MCP server over stdio, here
# without native engines (no Ghidra/Hopper/IDA, Frida, ADB, GDB or browser): its static
# JavaScript/Electron, web-bundle and binary-format analyses of files mounted at /work.
# PREPARED, NOT YET BUILT: rea needs Node.js ^22.23.4 || ^24.22.1 || >=26.12.1, which Debian
# trixie does not ship (nodejs 20.19), so Node.js comes from nodejs.org; its version and SHA-256
# could not be looked up where this was prepared (nodejs.org was not reachable). Fill
# NODE_VERSION and NODE_SHA256 (the line for node-v<VERSION>-linux-x64.tar.xz in
# https://nodejs.org/dist/v<VERSION>/SHASUMS256.txt, after checking its signature), re-check the
# Debian versions (podman run --rm BASE sh -c 'apt-get update -qq && apt-cache policy git xz-utils
# procps tini'), then move this folder to servers/ and add it to the CI matrix. Without them the
# build stops at the first RUN.
ARG DEBIAN_IMAGE=docker.io/library/debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad
FROM ${DEBIAN_IMAGE} AS build
ARG NODE_VERSION
ARG NODE_SHA256
ARG GIT_VERSION=1:2.47.3-0+deb13u1
ARG XZ_VERSION=5.8.1-1+deb13u2
# The commit of the tag rea-agents-6.8.0; npm ci installs exactly what its package-lock.json pins.
ARG REA_COMMIT=160d821ac9a0310afcb8d1fc427862dd6508add5
RUN test -n "${NODE_VERSION}" && test -n "${NODE_SHA256}" \
      || { echo "pin NODE_VERSION and NODE_SHA256 (see the top of this file)" >&2; exit 1; }
RUN apt-get update \
 && apt-get install -y --no-install-recommends git=${GIT_VERSION} xz-utils=${XZ_VERSION} \
      ca-certificates=20250419+deb13u1
ADD --checksum=sha256:${NODE_SHA256} https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz /tmp/node.tar.xz
RUN mkdir /opt/node && tar -xJf /tmp/node.tar.xz -C /opt/node --strip-components=1 --no-same-owner \
 && rm /tmp/node.tar.xz
ENV PATH=/opt/node/bin:${PATH}
# --ignore-scripts: no install scripts of dependencies (frida, an optional dependency with an
# install script, stays unbuilt, so the Frida tools report themselves unavailable).
RUN git clone --quiet https://github.com/morluto/rea /opt/rea \
 && git -C /opt/rea checkout --quiet ${REA_COMMIT} \
 && test "$(git -C /opt/rea rev-parse HEAD)" = "${REA_COMMIT}" \
 && cd /opt/rea \
 && npm ci --ignore-scripts --no-audit --no-fund \
 && npm run compile \
 && npm prune --omit=dev --ignore-scripts --no-audit --no-fund \
 && rm -rf .git tests website experiments docs/assets

FROM ${DEBIAN_IMAGE}
ARG PROCPS_VERSION=2:4.0.4-9
LABEL org.opencontainers.image.source="https://github.com/c0decave/sandbox-ai-mcp" \
      org.opencontainers.image.title="sandbox-ai-mcp-rea" \
      org.opencontainers.image.description="Static reverse engineering of mounted files with REA, an MCP server of sandbox-ai-mcp (stdio)" \
      org.opencontainers.image.licenses="MIT"
# procps: REA's process supervisor needs a procps `ps` before it starts its analysis workers.
RUN apt-get update \
 && apt-get install -y --no-install-recommends procps=${PROCPS_VERSION} tini=0.19.0-3+b8 \
 && rm -rf /var/lib/apt/lists/* /var/cache/apt /var/log/apt /var/log/dpkg.log
COPY --from=build /opt/node /opt/node
COPY --from=build /opt/rea /opt/rea
COPY LICENSES/ /usr/share/doc/sandbox-ai-mcp-rea/
RUN useradd --uid 10001 --user-group --no-create-home --home-dir /tmp --shell /usr/sbin/nologin mcp
ENV HOME=/tmp PATH=/opt/node/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
USER 10001:10001
WORKDIR /tmp
ENTRYPOINT ["/usr/bin/tini", "--", "node", "/opt/rea/scripts/rea.mjs", "mcp"]
