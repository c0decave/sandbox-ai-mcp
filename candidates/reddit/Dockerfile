# Reddit MCP Buddy 1.1.14 (karanb192/reddit-mcp-buddy, npm reddit-mcp-buddy, MIT), MCP over stdio:
# read Reddit (browse, search, post details with comments, user analysis) through Reddit's
# official OAuth API, or its public RSS feed without credentials. Read-only: this release has no
# write tools. Published 2026-07-29 (pinning rule: a release at least 14 days old; 1.2.0 of
# 2026-11-02 was too new).
# PREPARED, NOT YET BUILT: all pins below were looked up (Debian versions from the trixie indexes
# of 2026-11-05, the npm tarball by the SHA-512 integrity of the registry and its SHA-256,
# upstream's lockfile by the commit the npm provenance names), but the build has not been run.
# Re-check the Debian versions before building (podman run --rm BASE sh -c 'apt-get update -qq &&
# apt-cache policy nodejs npm git'), then move this folder to servers/ and add it to the CI matrix.
ARG DEBIAN_IMAGE=docker.io/library/debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad
FROM ${DEBIAN_IMAGE} AS build
ARG NODEJS_VERSION=20.19.2+dfsg-1+deb13u3
ARG NPM_VERSION=9.2.0~ds1-3
ARG GIT_VERSION=1:2.47.3-0+deb13u1
# The published package (prebuilt dist/; npm provenance: built by upstream's publish-mcp.yml from
# refs/tags/v1.1.14 at the commit below). SHA-256 for ADD, SHA-512 = the registry's "integrity".
ARG REDDIT_TGZ_URL=https://registry.npmjs.org/reddit-mcp-buddy/-/reddit-mcp-buddy-1.1.14.tgz
ARG REDDIT_TGZ_SHA256=99bc1559908ea66993bd760924e678fcff964dc37b041c80f6b86690fbacd9af
ARG REDDIT_INTEGRITY=sha512-+O1+W5dcGiY5iwtHG4+dYOS9w+nhPtL2vGqT9+Qtp0Q4ymdfQZhznJc6+27O/PHt/FShBTmOjhj3+Y49cKUU7Q==
# The commit 1.1.14 was built from (npm provenance; the tag v1.1.14 was later moved to e2d3f3fa,
# which differs only in CI files and server.json): its package-lock.json pins the dependencies
# (lockfileVersion 3, an integrity hash for every package); its package.json is byte-identical
# to the tarball's.
ARG REDDIT_COMMIT=dfd3f0941a0ae18ef108a9f7788dd0f350d610b3
RUN test -n "${NODEJS_VERSION}" && test -n "${NPM_VERSION}" && test -n "${GIT_VERSION}" \
      && test -n "${REDDIT_TGZ_SHA256}" && test -n "${REDDIT_INTEGRITY}" && test -n "${REDDIT_COMMIT}" \
      || { echo "pin NODEJS_VERSION, NPM_VERSION, GIT_VERSION, REDDIT_TGZ_SHA256, REDDIT_INTEGRITY and REDDIT_COMMIT (see the top of this file)" >&2; exit 1; }
RUN apt-get update \
 && apt-get install -y --no-install-recommends nodejs=${NODEJS_VERSION} npm=${NPM_VERSION} \
      git=${GIT_VERSION} ca-certificates=20250419+deb13u1
ADD --checksum=sha256:${REDDIT_TGZ_SHA256} ${REDDIT_TGZ_URL} /tmp/reddit-mcp-buddy.tgz
ENV NPM_CONFIG_UPDATE_NOTIFIER=false NPM_CONFIG_FUND=false NPM_CONFIG_AUDIT=false
RUN node -e 'const c=require("crypto"),f=require("fs"); const h="sha512-"+c.createHash("sha512").update(f.readFileSync(process.argv[1])).digest("base64"); if (h!==process.argv[2]) { console.error("integrity mismatch: "+h); process.exit(1); }' \
      /tmp/reddit-mcp-buddy.tgz "${REDDIT_INTEGRITY}" \
 && mkdir /opt/reddit-mcp-buddy \
 && tar -xzf /tmp/reddit-mcp-buddy.tgz -C /opt/reddit-mcp-buddy --strip-components=1 --no-same-owner \
 && git clone --quiet https://github.com/karanb192/reddit-mcp-buddy /src \
 && git -C /src checkout --quiet ${REDDIT_COMMIT} \
 && test "$(git -C /src rev-parse HEAD)" = "${REDDIT_COMMIT}" \
 && cmp /src/package.json /opt/reddit-mcp-buddy/package.json \
 && cp /src/package-lock.json /opt/reddit-mcp-buddy/ \
 && cd /opt/reddit-mcp-buddy \
 && npm ci --omit=dev --ignore-scripts \
 && test -f dist/index.js && test -d node_modules/@modelcontextprotocol/sdk && test -d node_modules/zod \
      && test -d node_modules/zod-to-json-schema

FROM ${DEBIAN_IMAGE}
ARG NODEJS_VERSION=20.19.2+dfsg-1+deb13u3
LABEL org.opencontainers.image.source="https://github.com/c0decave/sandbox-ai-mcp" \
      org.opencontainers.image.title="sandbox-ai-mcp-reddit" \
      org.opencontainers.image.description="Read Reddit (browse, search, posts and comments, users) through its official API, an MCP server of sandbox-ai-mcp (stdio)" \
      org.opencontainers.image.licenses="MIT"
RUN apt-get update \
 && apt-get install -y --no-install-recommends nodejs=${NODEJS_VERSION} ca-certificates=20250419+deb13u1 \
 && rm -rf /var/lib/apt/lists/* /var/cache/apt /var/log/apt /var/log/dpkg.log
COPY --from=build /opt/reddit-mcp-buddy /opt/reddit-mcp-buddy
COPY LICENSES/ /usr/share/doc/sandbox-ai-mcp-reddit/
RUN useradd --uid 10001 --user-group --no-create-home --home-dir /tmp --shell /usr/sbin/nologin mcp
# No telemetry to switch off (none found in the server or its three direct dependencies).
# REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET and REDDIT_USER_AGENT (app-only, read) are passed with
# --env by sandbox-ai; without them only browse_subreddit (RSS) and reddit_explain work.
# REDDIT_USERNAME/REDDIT_PASSWORD (a full-scope password grant) are not passed.
ENV HOME=/tmp
USER 10001:10001
WORKDIR /tmp
# dist/index.js, not dist/cli.js: no CLI flags (--auth, --http), stdio unless
# REDDIT_BUDDY_HTTP is set.
ENTRYPOINT ["node", "/opt/reddit-mcp-buddy/dist/index.js"]
