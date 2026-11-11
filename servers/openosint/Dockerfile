# OpenOSINT: passive OSINT lookups, an MCP server of sandbox-ai-mcp (src/server.py) over the tool code of
# OpenOSINT 2.36.1 (MIT), MCP over stdio. Only the reviewed modules go into the image (openosint-files.sha256,
# 26 files): not OpenOSINT's CLI, web UI (with its minified JavaScript), LLM agent, graph, active tools or MCP
# server. See PROVENANCE.md.
ARG DEBIAN_IMAGE=docker.io/library/debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad

FROM ${DEBIAN_IMAGE} AS source
# Tag v2.36.1 (2026-10-19) = PyPI openosint 2.36.1, whose wheel has these files byte for byte
ARG OPENOSINT_COMMIT=998497328cc69e71f11e4bd8d343428cf9d4bda5
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates git \
 && rm -rf /var/lib/apt/lists/*
COPY openosint-files.sha256 /tmp/openosint-files.sha256
RUN printf '%s\n' '#!/bin/sh' 'set -eu' 'git init -q "$2"' 'cd "$2"' \
      'git remote add origin "$1"' 'git fetch -q --depth 1 origin "$3"' 'git checkout -q FETCH_HEAD' \
      'test "$(git rev-parse HEAD)" = "$3"' 'rm -rf .git' > /usr/local/bin/fetch-commit \
 && chmod 0755 /usr/local/bin/fetch-commit \
 && fetch-commit https://github.com/OpenOSINT/OpenOSINT.git /src/openosint "$OPENOSINT_COMMIT" \
 && cd /src/openosint \
 && sha256sum --check --strict --quiet /tmp/openosint-files.sha256 \
 && mkdir -p /opt/openosint \
 && awk '{print $2}' /tmp/openosint-files.sha256 | xargs cp --parents -t /opt/openosint

FROM ${DEBIAN_IMAGE}
LABEL org.opencontainers.image.source="https://github.com/c0decave/sandbox-ai-mcp" \
      org.opencontainers.image.title="sandbox-ai-mcp-openosint" \
      org.opencontainers.image.description="Passive OSINT lookups with OpenOSINT 2.36.1's tool code (RDAP, WHOIS, DNS, IP, GitHub, pastes, GDELT news, HIBP, VirusTotal, AbuseIPDB, IP2Location, Bright Data SERP), an MCP server of sandbox-ai-mcp (stdio)" \
      org.opencontainers.image.licenses="MIT"
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3=3.13.5-1 python3-venv=3.13.5-1 \
      ca-certificates=20250419+deb13u1 \
 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /opt/mcp/requirements.txt
# pip is removed from the venv and the venv tooling is purged: nothing installs Python packages at run time
RUN python3 -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir --disable-pip-version-check --require-hashes \
      --only-binary=:all: -r /opt/mcp/requirements.txt \
 && /opt/venv/bin/python -m pip uninstall -y -q pip \
 && apt-get purge -y -q python3-venv python3.13-venv python3-pip-whl python3-setuptools-whl \
 && rm -rf /var/cache/apt /var/log/apt /var/log/dpkg.log
COPY --from=source /opt/openosint/openosint /opt/venv/lib/python3.13/site-packages/openosint
COPY src/server.py /opt/mcp/server.py
COPY LICENSES/ /usr/share/doc/sandbox-ai-mcp-openosint/
RUN /opt/venv/bin/python -m compileall -q /opt/mcp /opt/venv/lib/python3.13/site-packages/openosint \
 && useradd --uid 10001 --user-group --no-create-home --home-dir /tmp --shell /usr/sbin/nologin mcp
ENV HOME=/tmp
USER 10001:10001
WORKDIR /tmp
ENTRYPOINT ["/opt/venv/bin/python", "-I", "-u", "/opt/mcp/server.py"]
