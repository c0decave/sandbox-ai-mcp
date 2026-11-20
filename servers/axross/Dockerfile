# axross: axross-headless-mcp 0.15.180 (c0decave/axross-headless-mcp, Apache-2.0) - axross's file tools on the folder
# mounted at /work and on the SFTP connections saved as axross profiles - MCP over stdio, started by src/server.py
# (the root, the groups, the reviewed modules, the keyring and the folders fixed; see PROVENANCE.md).
# Installed from its hash-pinned PyPI wheel (byte for byte the tag v0.15.180, commit 07976963) with its dependencies
# (requirements.txt); then every file of the package that was not reviewed for this image is deleted
# (reviewed.sha256: the 65 kept, each checked by its SHA-256), and so are invoke, SecretStorage and jeepney, which
# paramiko and keyring import only for what this server never does (an SSH config's "Match exec", the desktop's
# Secret Service). No network unless the human gives it one for a connection.
ARG DEBIAN_IMAGE=docker.io/library/debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad
FROM ${DEBIAN_IMAGE}
LABEL org.opencontainers.image.source="https://github.com/c0decave/sandbox-ai-mcp" \
      org.opencontainers.image.title="sandbox-ai-mcp-axross" \
      org.opencontainers.image.description="axross's file tools on a mounted folder and on saved SFTP connections (axross-headless-mcp, reviewed modules only), an MCP server of sandbox-ai-mcp (stdio)" \
      org.opencontainers.image.licenses="Apache-2.0 AND MIT AND LGPL-2.1-only"
# ca-certificates only for pip's download while the image is built (Debian's pip uses the system's certificates)
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3=3.13.5-1 python3-venv=3.13.5-1 \
      ca-certificates=20250419+deb13u1 \
 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt reviewed.sha256 /opt/mcp/
# Every package by hash, wheels only; pip is removed from the venv and the venv tooling is purged: nothing installs
# Python packages at run time.
RUN python3 -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir --disable-pip-version-check --require-hashes \
      --only-binary=:all: -r /opt/mcp/requirements.txt \
 && /opt/venv/bin/python -m pip uninstall -y -q invoke secretstorage jeepney \
 && /opt/venv/bin/python -m pip uninstall -y -q pip \
 && cd /opt/venv/lib/python3.13/site-packages \
 && sha256sum --check --quiet --strict /opt/mcp/reviewed.sha256 \
 && awk '{print $2}' /opt/mcp/reviewed.sha256 | sort > /tmp/keep \
 && find axross_headless_mcp -type f | sort > /tmp/all \
 && comm -23 /tmp/all /tmp/keep | tr '\n' '\0' | xargs -0 -r rm -f -- \
 && find axross_headless_mcp -depth -type d -empty -delete \
 && find axross_headless_mcp -type f | sort | cmp -s - /tmp/keep \
 && rm -f /tmp/keep /tmp/all \
 && test ! -e invoke && test ! -e secretstorage && test ! -e jeepney \
 && /opt/venv/bin/python -I -c 'import paramiko, keyring, jsonschema; import paramiko.config as c; assert c.invoke is None' \
 && apt-get purge -y -q python3-venv python3.13-venv python3-pip-whl python3-setuptools-whl \
 && rm -rf /var/cache/apt /var/log/apt /var/log/dpkg.log
COPY src/server.py /opt/mcp/server.py
COPY LICENSES/ /usr/share/doc/sandbox-ai-mcp-axross/
# /work, /axross and /ssh are where the human's folders are mounted; empty (and read-only) when none is.
RUN /opt/venv/bin/python -m compileall -q /opt/mcp /opt/venv/lib/python3.13/site-packages/axross_headless_mcp \
 && mkdir -m 0755 /work /axross /ssh \
 && useradd --uid 10001 --user-group --no-create-home --home-dir /tmp --shell /usr/sbin/nologin mcp
ENV HOME=/tmp
USER 10001:10001
WORKDIR /tmp
ENTRYPOINT ["/opt/venv/bin/python", "-I", "-u", "/opt/mcp/server.py"]
