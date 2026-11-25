# radare2 + r2mcp (the official radare2 MCP server, radareorg/radare2-mcp), MCP over stdio.
# Both are built from source at pinned commits; git checks every object against the commit ID.

ARG DEBIAN_IMAGE=docker.io/library/debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad

FROM ${DEBIAN_IMAGE} AS build
# radare2 6.2.4 and radare2-mcp 1.9.0 (the commits their release tags point at)
ARG R2_COMMIT=485e5e205b190fc297a2a95a6f982ff5d9f54039
ARG R2MCP_COMMIT=562c0cf23c42b65b3052f0b294d8778c20facbde
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates git build-essential meson ninja-build \
      pkg-config python3 patch \
 && rm -rf /var/lib/apt/lists/*
# fetch <url> <dir> <commit>: exactly that commit, or the build fails
RUN printf '%s\n' '#!/bin/sh' 'set -eu' 'git init -q "$2"' 'cd "$2"' \
      'git remote add origin "$1"' 'git fetch -q --depth 1 origin "$3"' 'git checkout -q FETCH_HEAD' \
      'test "$(git rev-parse HEAD)" = "$3"' > /usr/local/bin/fetch-commit \
 && chmod 0755 /usr/local/bin/fetch-commit
RUN fetch-commit https://github.com/radareorg/radare2.git /src/radare2 "$R2_COMMIT"
# radare2's meson subprojects (sdb, capstone, qjs, otezip, zydis) are fetched at the revisions
# pinned in its own subprojects/*.wrap files.
RUN cd /src/radare2 \
 && meson setup build --prefix=/opt/radare2 --libdir=lib --buildtype=release \
 && ninja -C build \
 && ninja -C build install
ENV PATH=/opt/radare2/bin:$PATH \
    PKG_CONFIG_PATH=/opt/radare2/lib/pkgconfig \
    LD_LIBRARY_PATH=/opt/radare2/lib
# r2mcp with this repository's patches (patches/, see PROVENANCE.md): open_file takes no URI under -s,
# and no command r2mcp builds can carry a second line (0001); tools only - no prompts capability unless prompts
# are loaded, no resources capability (0002). The patched files must be exactly the reviewed ones.
COPY patches/ /patches/
RUN fetch-commit https://github.com/radareorg/radare2-mcp.git /src/r2mcp "$R2MCP_COMMIT" \
 && cd /src/r2mcp \
 && for p in /patches/*.patch; do patch -p1 --forward --fuzz=0 --no-backup-if-mismatch < "$p" || exit 1; done \
 && echo "a96fcc518cfddd4f612587bd9fc45d1b58b2519ca9be3f6477dbca1102f0b120  src/r2api.inc.c" | sha256sum --check --strict \
 && echo "daca549e58ab09dbcc5d0048ec40846d75bda5355cf38c4567280195a84ec488  src/r2mcp.c" | sha256sum --check --strict \
 && echo "bcdcb06bc903fba620093c2e59198be410c64206947664fe0cd9af4f994bfae3  src/main.c" | sha256sum --check --strict \
 && ./configure --prefix=/opt/radare2 \
 && make -j"$(nproc)" \
 && install -m 0755 src/r2mcp /opt/radare2/bin/r2mcp \
 && r2 -v && /opt/radare2/bin/r2mcp -v

FROM ${DEBIAN_IMAGE}
LABEL org.opencontainers.image.source="https://github.com/c0decave/sandbox-ai-mcp" \
      org.opencontainers.image.title="sandbox-ai-mcp-radare2" \
      org.opencontainers.image.description="radare2 6.2.4 with the official r2mcp 1.9.0 MCP server (stdio)" \
      org.opencontainers.image.licenses="MIT AND LGPL-3.0-only"
# tini (Debian's), the init of the ENTRYPOINT
RUN apt-get update \
 && apt-get install -y --no-install-recommends tini=0.19.0-3+b8 \
 && rm -rf /var/lib/apt/lists/* /var/cache/apt /var/log/apt /var/log/dpkg.log
COPY --from=build /opt/radare2 /opt/radare2
COPY LICENSES/ /usr/share/doc/sandbox-ai-mcp-radare2/
COPY r2mcp-run /opt/radare2/bin/r2mcp-run
RUN echo /opt/radare2/lib > /etc/ld.so.conf.d/radare2.conf && ldconfig \
 && chmod 0755 /opt/radare2/bin/r2mcp-run \
 && useradd --uid 10001 --user-group --no-create-home --home-dir /tmp --shell /usr/sbin/nologin mcp \
 && mkdir -p /work \
 && /opt/radare2/bin/r2mcp -v
# tools only: the initialize answer of the entrypoint's flags announces tools and neither prompts nor resources
RUN printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"build","version":"1"}}}' \
      | timeout 30 /opt/radare2/bin/r2mcp -s /work -g none -N 2>/dev/null > /tmp/initialize.json; \
    cat /tmp/initialize.json && grep -q '"protocolVersion"' /tmp/initialize.json && grep -q '"tools"' /tmp/initialize.json \
 && ! grep -q '"resources"' /tmp/initialize.json && ! grep -q '"prompts"' /tmp/initialize.json \
 && rm /tmp/initialize.json
ENV HOME=/tmp \
    PATH=/opt/radare2/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
# The usual mount targets exist in every image (a read-only rootfs under Bubblewrap cannot create them).
RUN mkdir -p -m 0755 /work /work_ro /work_rw /app /srv
USER 10001:10001
WORKDIR /work
# r2mcp-run: r2mcp with its flags (-s /work, -g none, -N and exactly the 32 tools of tools.json; see the file).
# tini is PID 1 where nothing else is (Podman without the host's catatonit: sandbox-ai then starts the image
# without --init) and reaps what the server leaves; -s: also where it is not PID 1 (Podman's --init, Bubblewrap).
ENTRYPOINT ["/usr/bin/tini", "-s", "--", "/opt/radare2/bin/r2mcp-run"]
