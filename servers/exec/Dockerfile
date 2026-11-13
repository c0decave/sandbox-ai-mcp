# exec: an MCP server of sandbox-ai-mcp (src/server.py), MCP over stdio: shell commands in the project folder mounted at
# /work, with time limits, no input, bounded output, background jobs, run_tests and lint - for agents on small local
# models. The commands run in this container with the tools installed below; it has no network.
ARG DEBIAN_IMAGE=docker.io/library/debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad
FROM ${DEBIAN_IMAGE}
LABEL org.opencontainers.image.source="https://github.com/c0decave/sandbox-ai-mcp" \
      org.opencontainers.image.title="sandbox-ai-mcp-exec" \
      org.opencontainers.image.description="Shell commands in /work for agents on small local models: time limits, no input, bounded output, background jobs, test failures only, lint; no network, an MCP server of sandbox-ai-mcp (stdio)" \
      org.opencontainers.image.licenses="MIT"
# The server's Python (python3, python3-venv for the build only) and what the commands get besides the base image's
# bash and coreutils: git, make, ps (procps), pytest, pyflakes and PyYAML for Debian's python3, shellcheck, and node
# (Debian's Node.js 20, without npm: a project's own jest, vitest or eslint in node_modules runs with it).
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3=3.13.5-1 python3-venv=3.13.5-1 \
      ca-certificates=20250419+deb13u1 \
      git=1:2.47.3-0+deb13u1 make=4.4.1-2 procps=2:4.0.4-9 \
      python3-pytest=8.3.5-2 python3-pyflakes=3.2.0-3 python3-yaml=6.0.2-1+b2 \
      shellcheck=0.10.0-1 nodejs=20.19.2+dfsg-1+deb13u3 \
 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /opt/mcp/requirements.txt
# pip is removed from the venv and the venv tooling is purged: nothing installs Python packages at run time
RUN python3 -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir --disable-pip-version-check --require-hashes \
      --only-binary=:all: -r /opt/mcp/requirements.txt \
 && /opt/venv/bin/python -m pip uninstall -y -q pip \
 && apt-get purge -y -q python3-venv python3.13-venv python3-pip-whl python3-setuptools-whl \
 && rm -rf /var/cache/apt /var/log/apt /var/log/dpkg.log
COPY src/server.py /opt/mcp/server.py
COPY LICENSES/ /usr/share/doc/sandbox-ai-mcp-exec/
# /work: the project's mount point (an empty folder of the read-only root without a mount: every tool says so).
# The mounted project belongs to another user than the server's (rootless podman maps it to root): git trusts it.
RUN /opt/venv/bin/python -m compileall -q /opt/mcp \
 && useradd --uid 10001 --user-group --no-create-home --home-dir /tmp --shell /usr/sbin/nologin mcp \
 && mkdir -m 0755 /work \
 && git config --system --add safe.directory '*' \
 && /usr/bin/python3 -I -c 'import pytest, pyflakes, yaml' && shellcheck --version >/dev/null && node --version
ENV HOME=/tmp
USER 10001:10001
WORKDIR /tmp
ENTRYPOINT ["/opt/venv/bin/python", "-I", "-u", "/opt/mcp/server.py"]
