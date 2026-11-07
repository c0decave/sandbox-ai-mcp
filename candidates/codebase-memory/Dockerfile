# codebase-memory-mcp 0.12.1 (DeusData, MIT), a static C binary, MCP over stdio.
# PREPARED, NOT YET BUILT: every pin below was looked up (base image as in the other candidates,
# release archive by the SHA-256 GitHub publishes and checksums.txt repeats, Debian git from the
# trixie index of 2026-11-05), but the image has not been built or smoke-tested yet. Before
# moving this folder to servers/: re-check GIT_VERSION (podman run --rm BASE sh -c 'apt-get
# update -qq && apt-cache policy git'), build, smoke-test, add it to the CI matrix.
ARG DEBIAN_IMAGE=docker.io/library/debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad
FROM ${DEBIAN_IMAGE}
ARG GIT_VERSION=1:2.47.3-0+deb13u1
# The fully static linux-amd64 build of the tag v0.12.1 (commit a7158ac2f48ca646b4527341b76f930f2aeff87e).
ARG CBM_URL=https://github.com/DeusData/codebase-memory-mcp/releases/download/v0.12.1/codebase-memory-mcp-linux-amd64-portable.tar.gz
ARG CBM_SHA256=8c3d0341064301e78ecc84cf7348d4e2c6562a0f57448243ea560aaa34de36c1
LABEL org.opencontainers.image.source="https://github.com/c0decave/sandbox-ai-mcp" \
      org.opencontainers.image.title="sandbox-ai-mcp-codebase-memory" \
      org.opencontainers.image.description="Code knowledge graph of a mounted repository with codebase-memory-mcp, an MCP server of sandbox-ai-mcp (stdio)" \
      org.opencontainers.image.licenses="MIT"
RUN test -n "${GIT_VERSION}" || { echo "pin GIT_VERSION (see the top of this file)" >&2; exit 1; }
# git: detect_changes, the git-history pass and the test-impact tools run `git -C <repo> ...`.
RUN apt-get update \
 && apt-get install -y --no-install-recommends git=${GIT_VERSION} \
 && rm -rf /var/lib/apt/lists/* /var/cache/apt /var/log/apt /var/log/dpkg.log
ADD --checksum=sha256:${CBM_SHA256} ${CBM_URL} /tmp/cbm.tar.gz
RUN mkdir /tmp/cbm && tar -xzf /tmp/cbm.tar.gz -C /tmp/cbm --no-same-owner \
 && install -m 0755 /tmp/cbm/codebase-memory-mcp /usr/local/bin/codebase-memory-mcp \
 && mkdir -p /usr/share/doc/sandbox-ai-mcp-codebase-memory \
 && cp /tmp/cbm/THIRD_PARTY_NOTICES.md /usr/share/doc/sandbox-ai-mcp-codebase-memory/ \
 && rm -rf /tmp/cbm /tmp/cbm.tar.gz
COPY LICENSES/ /usr/share/doc/sandbox-ai-mcp-codebase-memory/
# cbm strips GIT_CONFIG_COUNT and the other repository-local variables from its git children, so
# the mounted repository (owned by another uid than the server's) is trusted in the system config.
RUN git config --system --add safe.directory '*'
RUN useradd --uid 10001 --user-group --no-create-home --home-dir /tmp --shell /usr/sbin/nologin mcp
# Indexes (SQLite) and the daemon's logs live in /out, which must be mounted writable (the root
# is read-only and /tmp is a 64 MiB tmpfs). index_repository refuses paths outside /work
# (CBM_ALLOWED_ROOT). --ui=false: without a config file the binary turns its embedded web UI on
# (an HTTP listener on 127.0.0.1:9749); the flag is persisted in its config under $HOME.
ENV HOME=/tmp CBM_ALLOWED_ROOT=/work CBM_CACHE_DIR=/out/codebase-memory
USER 10001:10001
WORKDIR /work
ENTRYPOINT ["/usr/local/bin/codebase-memory-mcp", "--ui=false"]
