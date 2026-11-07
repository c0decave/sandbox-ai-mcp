# Telegram user account: an MCP server of sandbox-ai-mcp (src/server.py), MCP over stdio, MTProto
# through Telethon. src/login.py (the one-time login a human runs) is in the image too.
ARG DEBIAN_IMAGE=docker.io/library/debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad
FROM ${DEBIAN_IMAGE}
LABEL org.opencontainers.image.source="https://github.com/c0decave/sandbox-ai-mcp" \
      org.opencontainers.image.title="sandbox-ai-mcp-telegram-user" \
      org.opencontainers.image.description="A Telegram user account through MTProto (Telethon), read-only unless enabled, an MCP server of sandbox-ai-mcp (stdio)" \
      org.opencontainers.image.licenses="MIT"
# No ca-certificates: MTProto is not TLS, and nothing here speaks HTTPS.
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3=3.13.5-1 python3-venv=3.13.5-1 \
 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt requirements-build.txt /opt/mcp/
# Every package by hash, wheels only, except pyaes (Telethon's pure-Python AES fallback, published
# as an sdist only): it is built here from its hash-pinned sdist with the hash-pinned setuptools of
# requirements-build.txt and no build isolation (which would fetch unpinned build tools).
# setuptools and pip are removed from the venv and the venv tooling is purged afterwards.
RUN python3 -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir --disable-pip-version-check --require-hashes \
      --only-binary=:all: -r /opt/mcp/requirements-build.txt \
 && /opt/venv/bin/pip install --no-cache-dir --disable-pip-version-check --require-hashes \
      --only-binary=:all: --no-binary=pyaes --no-build-isolation --use-pep517 -r /opt/mcp/requirements.txt \
 && /opt/venv/bin/python -m pip uninstall -y -q setuptools \
 && /opt/venv/bin/python -m pip uninstall -y -q pip \
 && apt-get purge -y -q python3-venv python3.13-venv python3-pip-whl python3-setuptools-whl \
 && rm -rf /var/cache/apt /var/log/apt /var/log/dpkg.log
COPY src/server.py src/login.py /opt/mcp/
COPY LICENSES/ /usr/share/doc/sandbox-ai-mcp-telegram-user/
RUN /opt/venv/bin/python -m compileall -q /opt/mcp \
 && useradd --uid 10001 --user-group --no-create-home --home-dir /tmp --shell /usr/sbin/nologin mcp
ENV HOME=/tmp
USER 10001:10001
WORKDIR /tmp
ENTRYPOINT ["/opt/venv/bin/python", "-I", "-u", "/opt/mcp/server.py"]
