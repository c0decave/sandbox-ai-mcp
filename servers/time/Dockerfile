# time: the official MCP reference server mcp-server-time 2026.10.28 (modelcontextprotocol/servers src/time, MIT),
# MCP over stdio. Installed from its hash-pinned PyPI wheel (identical to commit 74af74c8 of modelcontextprotocol/
# servers) on the MCP Python SDK 2.3.0 lock of servers/osint-mcp, with tzdata 2026.6 (IANA 2026f) and tzlocal 5.4.5;
# started by src/server.py (zone arguments checked, answers bounded, tools only). No network. See PROVENANCE.md.
ARG DEBIAN_IMAGE=docker.io/library/debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad
FROM ${DEBIAN_IMAGE}
LABEL org.opencontainers.image.source="https://github.com/c0decave/sandbox-ai-mcp" \
      org.opencontainers.image.title="sandbox-ai-mcp-time" \
      org.opencontainers.image.description="Current time and time zone conversion (the official MCP time server), an MCP server of sandbox-ai-mcp (stdio)" \
      org.opencontainers.image.licenses="MIT"
RUN apt-get update \
 && apt-get install -y --no-install-recommends tini=0.19.0-3+b8 python3=3.13.5-1 python3-venv=3.13.5-1 \
 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /opt/mcp/requirements.txt
# Every package by hash, wheels only; pip is removed from the venv and the venv tooling is purged: nothing installs
# Python packages at run time.
RUN python3 -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir --disable-pip-version-check --require-hashes \
      --only-binary=:all: -r /opt/mcp/requirements.txt \
 && /opt/venv/bin/python -m pip uninstall -y -q pip \
 && apt-get purge -y -q python3-venv python3.13-venv python3-pip-whl python3-setuptools-whl \
 && rm -rf /var/cache/apt /var/log/apt /var/log/dpkg.log
COPY src/server.py /opt/mcp/server.py
COPY LICENSES/ /usr/share/doc/sandbox-ai-mcp-time/
RUN /opt/venv/bin/python -m compileall -q /opt/mcp \
 && useradd --uid 10001 --user-group --no-create-home --home-dir /tmp --shell /usr/sbin/nologin mcp
# Zones: Python's zoneinfo reads /usr/share/zoneinfo if the base image has one, else the pinned tzdata wheel.
# The local zone named in the tool descriptions: LOCAL_TIMEZONE (sandbox-ai can pass the host's), else UTC.
ENV HOME=/tmp
# The usual mount targets exist in every image (a read-only rootfs under Bubblewrap cannot create them).
RUN mkdir -p -m 0755 /work /work_ro /work_rw /app /srv
USER 10001:10001
WORKDIR /tmp
# tini is PID 1 where nothing else is (Podman without the host's catatonit: sandbox-ai then starts the image
# without --init) and reaps what the server leaves; -s: also where it is not PID 1 (Podman's --init, Bubblewrap).
ENTRYPOINT ["/usr/bin/tini", "-s", "--", "/opt/venv/bin/python", "-I", "-u", "/opt/mcp/server.py"]
