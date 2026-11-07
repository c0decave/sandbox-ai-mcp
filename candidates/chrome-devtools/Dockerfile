# Chrome DevTools MCP 1.12.0 (ChromeDevTools/chrome-devtools-mcp, Apache-2.0) with Debian's
# Chromium, MCP over stdio.
# PREPARED, NOT YET BUILT: the npm package's integrity is not pinned here (the npm registry was not
# reachable where this was prepared). Fill CDT_INTEGRITY with the published value
# (npm view chrome-devtools-mcp@1.12.0 dist.integrity, a "sha512-..." string) and re-check the
# Debian versions (podman run --rm BASE sh -c 'apt-get update -qq && apt-cache policy nodejs
# chromium fonts-liberation tini'), then move this folder to servers/ and add it to the CI
# matrix. Without CDT_INTEGRITY the build stops at the first RUN.
#
# Why the npm package and not the git commit: the package is the release's rollup bundle with no
# runtime dependencies ("dependencies" is empty in package.json), so its integrity hash pins all
# of it; building the commit needs Node >= 22.18 for its .ts build scripts, which Debian trixie
# does not ship (nodejs 20.19).
ARG DEBIAN_IMAGE=docker.io/library/debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad
FROM ${DEBIAN_IMAGE} AS build
# Debian versions from the trixie / trixie-security indexes of 2026-11-05.
ARG NODEJS_VERSION=20.19.2+dfsg-1+deb13u3
# The tag chrome-devtools-mcp-v1.12.0 is commit af2834411a564d366f9cab63efb046d9084f4dba.
ARG CDT_URL=https://registry.npmjs.org/chrome-devtools-mcp/-/chrome-devtools-mcp-1.12.0.tgz
ARG CDT_INTEGRITY
RUN test -n "${CDT_INTEGRITY}" \
      || { echo "pin CDT_INTEGRITY (see the top of this file)" >&2; exit 1; }
RUN apt-get update \
 && apt-get install -y --no-install-recommends nodejs=${NODEJS_VERSION} ca-certificates=20250419+deb13u1
ADD ${CDT_URL} /tmp/cdt.tgz
# npm's integrity is base64(SHA-512) of the tarball; compare it before unpacking anything.
RUN node -e 'const c=require("crypto"),f=require("fs");const h="sha512-"+c.createHash("sha512").update(f.readFileSync("/tmp/cdt.tgz")).digest("base64");if(h!==process.argv[1]){console.error("integrity mismatch: "+h);process.exit(1)}' "${CDT_INTEGRITY}" \
 && mkdir /opt/chrome-devtools-mcp \
 && tar -xzf /tmp/cdt.tgz -C /opt/chrome-devtools-mcp --strip-components=1 --no-same-owner \
 && node -e 'const p=require("/opt/chrome-devtools-mcp/package.json");if(p.version!=="1.12.0"||Object.keys(p.dependencies||{}).length){console.error("unexpected package.json");process.exit(1)}'

FROM ${DEBIAN_IMAGE}
ARG NODEJS_VERSION=20.19.2+dfsg-1+deb13u3
ARG CHROMIUM_VERSION=156.0.8078.79-1~deb13u1
LABEL org.opencontainers.image.source="https://github.com/c0decave/sandbox-ai-mcp" \
      org.opencontainers.image.title="sandbox-ai-mcp-chrome-devtools" \
      org.opencontainers.image.description="Browser debugging and automation with Chrome DevTools MCP and Chromium, an MCP server of sandbox-ai-mcp (stdio)" \
      org.opencontainers.image.licenses="Apache-2.0"
RUN apt-get update \
 && apt-get install -y --no-install-recommends nodejs=${NODEJS_VERSION} chromium=${CHROMIUM_VERSION} \
      ca-certificates=20250419+deb13u1 fonts-liberation=1:2.1.5-3 tini=0.19.0-3+b8 \
 && rm -rf /var/lib/apt/lists/* /var/cache/apt /var/log/apt /var/log/dpkg.log
COPY --from=build /opt/chrome-devtools-mcp /opt/chrome-devtools-mcp
COPY LICENSES/ /usr/share/doc/sandbox-ai-mcp-chrome-devtools/
RUN useradd --uid 10001 --user-group --no-create-home --home-dir /tmp --shell /usr/sbin/nologin mcp
# No usage statistics to Google (play.googleapis.com), no update check against the npm registry.
ENV HOME=/tmp CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS=1 CHROME_DEVTOOLS_MCP_NO_UPDATE_CHECKS=1
USER 10001:10001
WORKDIR /tmp
# Chromium's own sandbox needs user namespaces the container does not grant: the container is the
# sandbox (no capabilities, read-only root, no new privileges). The profile is a temporary
# directory (--isolated). --no-performance-crux: trace URLs are not sent to the CrUX API.
ENTRYPOINT ["/usr/bin/tini", "--", "node", "/opt/chrome-devtools-mcp/build/src/bin/chrome-devtools-mcp.js", \
            "--headless", "--isolated", "--executable-path", "/usr/bin/chromium", \
            "--chrome-arg=--no-sandbox", "--no-usage-statistics", "--no-performance-crux"]
