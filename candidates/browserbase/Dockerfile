# Browserbase MCP 3.0.0 (browserbase/mcp-server-browserbase, Apache-2.0), MCP over stdio: drives
# a cloud browser at Browserbase through Stagehand; no browser runs in this container.
# PREPARED, NOT YET BUILT: all pins below were looked up (Debian versions from the trixie indexes
# of 2026-11-05, pnpm's standalone binary by the SHA-256 GitHub publishes, upstream by commit),
# but the build has not been run. Re-check the Debian versions before building (podman run --rm
# BASE sh -c 'apt-get update -qq && apt-cache policy nodejs git'), then move this folder to
# servers/ and add it to the CI matrix.
ARG DEBIAN_IMAGE=docker.io/library/debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad
FROM ${DEBIAN_IMAGE} AS build
ARG NODEJS_VERSION=20.19.2+dfsg-1+deb13u3
ARG GIT_VERSION=1:2.47.3-0+deb13u1
# The pnpm version of package.json's "packageManager" (pnpm@10.12.4), as GitHub's standalone binary.
ARG PNPM_URL=https://github.com/pnpm/pnpm/releases/download/v10.12.4/pnpm-linux-x64
ARG PNPM_SHA256=ac2768434cbc6c5fec71da4abae7845802bbfe326d590aa0004cdf8bf0815b26
# The commit of the tag v3.0.0; pnpm installs exactly what pnpm-lock.yaml pins.
ARG BROWSERBASE_COMMIT=f6bd321a3790fcacabc24a7beaa505d3037e19c6
RUN test -n "${NODEJS_VERSION}" && test -n "${GIT_VERSION}" \
      || { echo "pin NODEJS_VERSION and GIT_VERSION (see the top of this file)" >&2; exit 1; }
RUN apt-get update \
 && apt-get install -y --no-install-recommends nodejs=${NODEJS_VERSION} git=${GIT_VERSION} \
      ca-certificates=20250419+deb13u1
ADD --checksum=sha256:${PNPM_SHA256} ${PNPM_URL} /usr/local/bin/pnpm
RUN chmod 0755 /usr/local/bin/pnpm
RUN git clone --quiet https://github.com/browserbase/mcp-server-browserbase /opt/browserbase-mcp \
 && git -C /opt/browserbase-mcp checkout --quiet ${BROWSERBASE_COMMIT} \
 && test "$(git -C /opt/browserbase-mcp rev-parse HEAD)" = "${BROWSERBASE_COMMIT}" \
 && cd /opt/browserbase-mcp \
 && pnpm install --frozen-lockfile --ignore-scripts \
 && pnpm run build \
 && pnpm prune --prod --ignore-scripts \
 && rm -rf .git src tests evals assets

FROM ${DEBIAN_IMAGE}
ARG NODEJS_VERSION=20.19.2+dfsg-1+deb13u3
LABEL org.opencontainers.image.source="https://github.com/c0decave/sandbox-ai-mcp" \
      org.opencontainers.image.title="sandbox-ai-mcp-browserbase" \
      org.opencontainers.image.description="Cloud browser automation with Browserbase and Stagehand, an MCP server of sandbox-ai-mcp (stdio)" \
      org.opencontainers.image.licenses="Apache-2.0"
RUN apt-get update \
 && apt-get install -y --no-install-recommends nodejs=${NODEJS_VERSION} ca-certificates=20250419+deb13u1 \
 && rm -rf /var/lib/apt/lists/* /var/cache/apt /var/log/apt /var/log/dpkg.log
COPY --from=build /opt/browserbase-mcp /opt/browserbase-mcp
COPY LICENSES/ /usr/share/doc/sandbox-ai-mcp-browserbase/
RUN useradd --uid 10001 --user-group --no-create-home --home-dir /tmp --shell /usr/sbin/nologin mcp
# BROWSERBASE_API_KEY, BROWSERBASE_PROJECT_ID and GEMINI_API_KEY (the default model) are passed
# with --env by sandbox-ai.
ENV HOME=/tmp
USER 10001:10001
WORKDIR /tmp
ENTRYPOINT ["node", "/opt/browserbase-mcp/cli.js"]
