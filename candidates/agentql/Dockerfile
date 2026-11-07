# AgentQL MCP 1.0.1 (tinyfish-io/agentql-mcp, npm agentql-mcp, MIT), MCP over stdio: a client of
# the AgentQL data extraction API (api.agentql.com); the page is fetched by AgentQL, not here.
# PREPARED, NOT YET BUILT: all pins below were looked up (Debian versions from the trixie indexes
# of 2026-11-05, the npm tarball by the SHA-512 integrity of the registry and its SHA-256,
# upstream's lockfile by commit), but the build has not been run. Re-check the Debian versions
# before building (podman run --rm BASE sh -c 'apt-get update -qq && apt-cache policy nodejs npm
# git'), then move this folder to servers/ and add it to the CI matrix.
ARG DEBIAN_IMAGE=docker.io/library/debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad
FROM ${DEBIAN_IMAGE} AS build
ARG NODEJS_VERSION=20.19.2+dfsg-1+deb13u3
ARG NPM_VERSION=9.2.0~ds1-3
ARG GIT_VERSION=1:2.47.3-0+deb13u1
# The published package (prebuilt dist/index.js; npm provenance: built by upstream's publish.yml
# from main at the commit below). SHA-256 for ADD, SHA-512 = the registry's "integrity".
ARG AGENTQL_TGZ_URL=https://registry.npmjs.org/agentql-mcp/-/agentql-mcp-1.0.1.tgz
ARG AGENTQL_TGZ_SHA256=367fd8df95f7e4b6eaa0ff541e39a4ea2295923d8a4b8b5f063720520a169ca4
ARG AGENTQL_INTEGRITY=sha512-K2CsCfLysqSQ2iQTgLN2UGx/lrEdkpNKVsUa/+8fNseBHztn3W+jQ58ma/Vn2iCTZVcJ6PDAX+BFNcMI/IrciA==
# The commit 1.0.1 was published from (no git tag v1.0.1 exists): its package-lock.json pins the
# dependencies (lockfileVersion 3, an integrity hash for every package); its package.json is
# byte-identical to the tarball's.
ARG AGENTQL_COMMIT=affb3a5c5eb817beac6a1aaa86e0ecd8a012f937
RUN test -n "${NODEJS_VERSION}" && test -n "${NPM_VERSION}" && test -n "${GIT_VERSION}" \
      && test -n "${AGENTQL_TGZ_SHA256}" && test -n "${AGENTQL_INTEGRITY}" && test -n "${AGENTQL_COMMIT}" \
      || { echo "pin NODEJS_VERSION, NPM_VERSION, GIT_VERSION, AGENTQL_TGZ_SHA256, AGENTQL_INTEGRITY and AGENTQL_COMMIT (see the top of this file)" >&2; exit 1; }
RUN apt-get update \
 && apt-get install -y --no-install-recommends nodejs=${NODEJS_VERSION} npm=${NPM_VERSION} \
      git=${GIT_VERSION} ca-certificates=20250419+deb13u1
ADD --checksum=sha256:${AGENTQL_TGZ_SHA256} ${AGENTQL_TGZ_URL} /tmp/agentql-mcp.tgz
ENV NPM_CONFIG_UPDATE_NOTIFIER=false NPM_CONFIG_FUND=false NPM_CONFIG_AUDIT=false
RUN node -e 'const c=require("crypto"),f=require("fs"); const h="sha512-"+c.createHash("sha512").update(f.readFileSync(process.argv[1])).digest("base64"); if (h!==process.argv[2]) { console.error("integrity mismatch: "+h); process.exit(1); }' \
      /tmp/agentql-mcp.tgz "${AGENTQL_INTEGRITY}" \
 && mkdir /opt/agentql-mcp \
 && tar -xzf /tmp/agentql-mcp.tgz -C /opt/agentql-mcp --strip-components=1 --no-same-owner \
 && git clone --quiet https://github.com/tinyfish-io/agentql-mcp /src \
 && git -C /src checkout --quiet ${AGENTQL_COMMIT} \
 && test "$(git -C /src rev-parse HEAD)" = "${AGENTQL_COMMIT}" \
 && cmp /src/package.json /opt/agentql-mcp/package.json \
 && cp /src/package-lock.json /opt/agentql-mcp/ \
 && cd /opt/agentql-mcp \
 && npm ci --omit=dev --ignore-scripts \
 && test -f dist/index.js && test -d node_modules/@modelcontextprotocol/sdk && test -d node_modules/node-fetch

FROM ${DEBIAN_IMAGE}
ARG NODEJS_VERSION=20.19.2+dfsg-1+deb13u3
LABEL org.opencontainers.image.source="https://github.com/c0decave/sandbox-ai-mcp" \
      org.opencontainers.image.title="sandbox-ai-mcp-agentql" \
      org.opencontainers.image.description="Structured data from web pages with AgentQL, an MCP server of sandbox-ai-mcp (stdio)" \
      org.opencontainers.image.licenses="MIT"
RUN apt-get update \
 && apt-get install -y --no-install-recommends nodejs=${NODEJS_VERSION} ca-certificates=20250419+deb13u1 \
 && rm -rf /var/lib/apt/lists/* /var/cache/apt /var/log/apt /var/log/dpkg.log
COPY --from=build /opt/agentql-mcp /opt/agentql-mcp
COPY LICENSES/ /usr/share/doc/sandbox-ai-mcp-agentql/
RUN useradd --uid 10001 --user-group --no-create-home --home-dir /tmp --shell /usr/sbin/nologin mcp
# No telemetry to switch off (none found in the server or its two direct dependencies).
# AGENTQL_API_KEY (required: without it the server exits at start) is passed with --env by
# sandbox-ai.
ENV HOME=/tmp
USER 10001:10001
WORKDIR /tmp
ENTRYPOINT ["node", "/opt/agentql-mcp/dist/index.js"]
