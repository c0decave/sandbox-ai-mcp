# osint-mcp 0.3.0 (robyroro/osint-mcp, MIT): domain and website investigations from public sources (RDAP,
# DNS, certificate transparency, Wayback, RIPEstat, Shodan InternetDB, HTTP headers, TLS), MCP over stdio.
# Installed from its hash-pinned PyPI wheel (osint-mcp-server, identical to the tag v0.3.0, commit 815276a9) and
# started by src/server.py, which tightens its address check (NAT64, 6to4). See PROVENANCE.md for the review.
ARG DEBIAN_IMAGE=docker.io/library/debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad
FROM ${DEBIAN_IMAGE}
LABEL org.opencontainers.image.source="https://github.com/c0decave/sandbox-ai-mcp" \
      org.opencontainers.image.title="sandbox-ai-mcp-osint-mcp" \
      org.opencontainers.image.description="Domain and website OSINT from public sources (osint-mcp), an MCP server of sandbox-ai-mcp (stdio)" \
      org.opencontainers.image.licenses="MIT"
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3=3.13.5-1 python3-venv=3.13.5-1 \
      ca-certificates=20250419+deb13u1 \
 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /opt/mcp/requirements.txt
# Every package by hash, wheels only; pip is removed from the venv and the venv tooling is purged: nothing
# installs Python packages at run time. charset-normalizer (imported by requests, which tldextract imports)
# ships mypyc-compiled copies of its md.py and cd.py: they are removed, so the reviewed Python source runs.
RUN python3 -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir --disable-pip-version-check --require-hashes \
      --only-binary=:all: -r /opt/mcp/requirements.txt \
 && /opt/venv/bin/python -m pip uninstall -y -q pip \
 && cn=/opt/venv/lib/python3.13/site-packages/charset_normalizer \
 && test -f "$cn/md.py" && test -f "$cn/cd.py" \
 && rm -f "$cn"/md.cpython-313-*.so "$cn"/cd.cpython-313-*.so \
 && test -z "$(find "$cn" -name '*.so')" \
 && /opt/venv/bin/python -I -c 'import charset_normalizer.md as m; assert m.__file__.endswith(".py"), m.__file__' \
 && apt-get purge -y -q python3-venv python3.13-venv python3-pip-whl python3-setuptools-whl \
 && rm -rf /var/cache/apt /var/log/apt /var/log/dpkg.log
COPY src/server.py /opt/mcp/server.py
COPY LICENSES/ /usr/share/doc/sandbox-ai-mcp-osint-mcp/
RUN /opt/venv/bin/python -m compileall -q /opt/mcp /opt/venv/lib/python3.13/site-packages/charset_normalizer \
 && useradd --uid 10001 --user-group --no-create-home --home-dir /tmp --shell /usr/sbin/nologin mcp
# The response cache (RDAP, crt.sh, Wayback, RIPEstat, InternetDB answers; upstream's default is a file under
# ~/.cache) lives in memory: one container per connection, nothing written to disk.
ENV HOME=/tmp \
    OSINT_MCP_CACHE_PATH=:memory:
USER 10001:10001
WORKDIR /tmp
ENTRYPOINT ["/opt/venv/bin/python", "-I", "-u", "/opt/mcp/server.py"]
