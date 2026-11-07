# Context7 MCP 4.5.0 (upstash/context7, packages/mcp, MIT), MCP over stdio: a client of the
# Context7 documentation API (context7.com).
# PREPARED, NOT YET BUILT: all pins below were looked up (Debian versions from the trixie indexes
# of 2026-11-05, pnpm's standalone binary by the SHA-256 GitHub publishes, upstream by commit),
# but the build has not been run. Re-check the Debian versions before building (podman run --rm
# BASE sh -c 'apt-get update -qq && apt-cache policy nodejs git'), then move this folder to
# servers/ and add it to the CI matrix.
ARG DEBIAN_IMAGE=docker.io/library/debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad
FROM ${DEBIAN_IMAGE} AS build
ARG NODEJS_VERSION=20.19.2+dfsg-1+deb13u3
ARG GIT_VERSION=1:2.47.3-0+deb13u1
# Upstream builds with pnpm 10 (.github/workflows/release.yml); this is the latest 10.x release.
ARG PNPM_URL=https://github.com/pnpm/pnpm/releases/download/v10.34.9/pnpm-linux-x64
ARG PNPM_SHA256=3ec79240658f0ee4e8977f21ee2c598c7a8b8d06b86dc564f2ec6cb099fd8ac2
# The commit of the tag @upstash/context7-mcp@4.5.0; pnpm installs exactly what pnpm-lock.yaml pins.
ARG CONTEXT7_COMMIT=a138857cc23f0abaf214b72b15d974e61598369b
RUN test -n "${NODEJS_VERSION}" && test -n "${GIT_VERSION}" \
      || { echo "pin NODEJS_VERSION and GIT_VERSION (see the top of this file)" >&2; exit 1; }
RUN apt-get update \
 && apt-get install -y --no-install-recommends nodejs=${NODEJS_VERSION} git=${GIT_VERSION} \
      ca-certificates=20250419+deb13u1
ADD --checksum=sha256:${PNPM_SHA256} ${PNPM_URL} /usr/local/bin/pnpm
RUN chmod 0755 /usr/local/bin/pnpm
RUN git clone --quiet https://github.com/upstash/context7 /src \
 && git -C /src checkout --quiet ${CONTEXT7_COMMIT} \
 && test "$(git -C /src rev-parse HEAD)" = "${CONTEXT7_COMMIT}" \
 && cd /src \
 && pnpm install --frozen-lockfile --ignore-scripts --filter @upstash/context7-mcp... \
 && pnpm --filter @upstash/context7-mcp run build \
 && pnpm --filter @upstash/context7-mcp deploy --legacy --prod --ignore-scripts /opt/context7-mcp \
 && test -f /opt/context7-mcp/dist/index.js

FROM ${DEBIAN_IMAGE}
ARG NODEJS_VERSION=20.19.2+dfsg-1+deb13u3
LABEL org.opencontainers.image.source="https://github.com/c0decave/sandbox-ai-mcp" \
      org.opencontainers.image.title="sandbox-ai-mcp-context7" \
      org.opencontainers.image.description="Current library documentation from Context7, an MCP server of sandbox-ai-mcp (stdio)" \
      org.opencontainers.image.licenses="MIT"
RUN apt-get update \
 && apt-get install -y --no-install-recommends nodejs=${NODEJS_VERSION} ca-certificates=20250419+deb13u1 \
 && rm -rf /var/lib/apt/lists/* /var/cache/apt /var/log/apt /var/log/dpkg.log
COPY --from=build /opt/context7-mcp /opt/context7-mcp
COPY LICENSES/ /usr/share/doc/sandbox-ai-mcp-context7/
RUN useradd --uid 10001 --user-group --no-create-home --home-dir /tmp --shell /usr/sbin/nologin mcp
# OTEL_SDK_DISABLED: no OpenTelemetry metrics (the embedded Prometheus exporter) in the container.
# CONTEXT7_API_KEY (optional, higher limits) is passed with --env by sandbox-ai.
ENV HOME=/tmp OTEL_SDK_DISABLED=true
USER 10001:10001
WORKDIR /tmp
ENTRYPOINT ["node", "/opt/context7-mcp/dist/index.js", "--transport", "stdio"]
