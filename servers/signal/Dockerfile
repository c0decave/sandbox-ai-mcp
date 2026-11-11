# Signal: a Signal account of yours (a linked device), an MCP server of sandbox-ai-mcp (src/server.py) over
# the client and message history of signal-mcp 1.43.3 (googlarz/signal-mcp, MIT; only the six reviewed
# modules of signal-mcp-files.sha256, not its MCP server, CLI, Signal Desktop import or webhook), with
# signal-cli 0.14.9 (AsamK/signal-cli, GPL-3.0) on Eclipse Temurin 25.0.5 (GPL-2.0 with Classpath
# Exception). MCP over stdio. See PROVENANCE.md.
ARG DEBIAN_IMAGE=docker.io/library/debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad

FROM ${DEBIAN_IMAGE} AS source
# Tag v1.43.3 (2026-10-21) = PyPI signal-mcp 1.43.3, whose wheel has these modules byte for byte
ARG SIGNAL_MCP_COMMIT=d3b1945c972340b72f8086da33f96f71b82f792c
# The JVM release of signal-cli v0.14.9 (2026-10-07; signed by AsamK, FA10826A74907F9EC6BBB7FC2BA2CD21B5B09570)
ARG SIGNAL_CLI_URL=https://github.com/AsamK/signal-cli/releases/download/v0.14.9/signal-cli-0.14.9.tar.gz
ARG SIGNAL_CLI_SHA256=c32b87f587198cbd277c9d71228716ee6047ee2b63e8e88728e8280d9407d65a
# Eclipse Temurin JRE 25.0.5+8 for Linux x64 (2026-10-22), the SHA-256 GitHub and its .sha256.txt publish
ARG TEMURIN_URL=https://github.com/adoptium/temurin25-binaries/releases/download/jdk-25.0.5%2B8/OpenJDK25U-jre_x64_linux_hotspot_25.0.5_8.tar.gz
ARG TEMURIN_SHA256=6fac98f0c8202efc3135a9e9e42aa61963ec42d1c5cbb40caf231e7b14a24ef6
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates=20250419+deb13u1 git=1:2.47.3-0+deb13u1 \
      python3=3.13.5-1 \
 && rm -rf /var/lib/apt/lists/*
COPY signal-mcp-files.sha256 prepare.py /tmp/
RUN printf '%s\n' '#!/bin/sh' 'set -eu' 'git init -q "$2"' 'cd "$2"' \
      'git remote add origin "$1"' 'git fetch -q --depth 1 origin "$3"' 'git checkout -q FETCH_HEAD' \
      'test "$(git rev-parse HEAD)" = "$3"' 'rm -rf .git' > /usr/local/bin/fetch-commit \
 && chmod 0755 /usr/local/bin/fetch-commit \
 && fetch-commit https://github.com/googlarz/signal-mcp.git /src/signal-mcp "$SIGNAL_MCP_COMMIT" \
 && cd /src/signal-mcp \
 && sha256sum --check --strict --quiet /tmp/signal-mcp-files.sha256 \
 && mkdir -p /opt/signal-mcp \
 && awk '{print $2}' /tmp/signal-mcp-files.sha256 | xargs cp --parents -t /opt/signal-mcp
# The release files, checked by SHA-256; the native libraries of libsignal and SQLite moved out of
# their jars into /opt/signal-cli/native (prepare.py), so nothing is ever unpacked into /tmp.
RUN python3 -I /tmp/prepare.py fetch "$SIGNAL_CLI_URL" "$SIGNAL_CLI_SHA256" /tmp/signal-cli.tar.gz \
 && python3 -I /tmp/prepare.py fetch "$TEMURIN_URL" "$TEMURIN_SHA256" /tmp/jre.tar.gz \
 && mkdir -p /opt/java /tmp/signal-cli \
 && tar -xzf /tmp/jre.tar.gz -C /opt/java --strip-components=1 --no-same-owner \
 && tar -xzf /tmp/signal-cli.tar.gz -C /tmp/signal-cli --strip-components=1 --no-same-owner \
 && python3 -I /tmp/prepare.py signal-cli /tmp/signal-cli /opt/signal-cli \
 && mkdir -p /opt/signal-cli/doc \
 && cp /tmp/signal-cli/man/man1/signal-cli.1.gz /tmp/signal-cli/man/man5/signal-cli-jsonrpc.5.gz /opt/signal-cli/doc/

FROM ${DEBIAN_IMAGE}
LABEL org.opencontainers.image.source="https://github.com/c0decave/sandbox-ai-mcp" \
      org.opencontainers.image.title="sandbox-ai-mcp-signal" \
      org.opencontainers.image.description="A Signal account of yours as a linked device (signal-cli 0.14.9, signal-mcp 1.43.3's message history), read-only unless enabled, an MCP server of sandbox-ai-mcp (stdio)" \
      org.opencontainers.image.licenses="MIT AND GPL-3.0-only AND AGPL-3.0-only AND GPL-2.0-only WITH Classpath-exception-2.0"
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3=3.13.5-1 python3-venv=3.13.5-1 \
 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /opt/mcp/requirements.txt
# pip is removed from the venv and the venv tooling is purged: nothing installs Python packages at run time
RUN python3 -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir --disable-pip-version-check --require-hashes \
      --only-binary=:all: -r /opt/mcp/requirements.txt \
 && /opt/venv/bin/python -m pip uninstall -y -q pip \
 && apt-get purge -y -q python3-venv python3.13-venv python3-pip-whl python3-setuptools-whl \
 && rm -rf /var/cache/apt /var/log/apt /var/log/dpkg.log
COPY --from=source /opt/java /opt/java
COPY --from=source /opt/signal-cli /opt/signal-cli
COPY --from=source /opt/signal-mcp/src/signal_mcp /opt/venv/lib/python3.13/site-packages/signal_mcp
COPY src/server.py /opt/mcp/server.py
COPY LICENSES/ /usr/share/doc/sandbox-ai-mcp-signal/
# /data: the account's folder, mounted writable (signal-cli's data and the message history live there).
RUN /opt/venv/bin/python -m compileall -q /opt/mcp /opt/venv/lib/python3.13/site-packages/signal_mcp \
 && useradd --uid 10001 --user-group --no-create-home --home-dir /tmp --shell /usr/sbin/nologin mcp \
 && mkdir -m 0755 /data
ENV HOME=/data
USER 10001:10001
WORKDIR /tmp
ENTRYPOINT ["/opt/venv/bin/python", "-I", "-u", "/opt/mcp/server.py"]
