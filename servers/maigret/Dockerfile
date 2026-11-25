# maigret: an MCP server of sandbox-ai-mcp (src/server.py: our own username checker on maigret 0.6.6's site database,
# taken as data), MCP over stdio. No code of maigret ships or runs: only its resources/data.json and its licence.
ARG DEBIAN_IMAGE=docker.io/library/debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad

# --- maigret's site database out of its wheel ---
FROM ${DEBIAN_IMAGE} AS data
# maigret 0.6.6 (soxoj/maigret, MIT; PyPI, uploaded 2026-09-18): the wheel by the SHA-256 PyPI publishes, and the one
# file taken from it by its own SHA-256
ARG MAIGRET_URL=https://files.pythonhosted.org/packages/dd/66/7fd8461f2ef0805fb2009fdfa0652643a42e75f9a86550065dab0cda43b8/maigret-0.6.6-py3-none-any.whl
ARG MAIGRET_SHA256=f382e7174d202a8002b2ac3ce3cde7c11900c506399dd6110f57b9256c4181c7
ARG DATA_SHA256=ef6ca66efa174209c10205ff86f7e975b591128681710639fdc786ff05e662da
RUN apt-get update \
 && apt-get install -y --no-install-recommends unzip=6.0-29+deb13u1 \
 && rm -rf /var/lib/apt/lists/*
ADD --checksum=sha256:${MAIGRET_SHA256} ${MAIGRET_URL} /build/maigret.whl
RUN cd /build \
 && unzip -q maigret.whl maigret/resources/data.json \
 && echo "${DATA_SHA256}  maigret/resources/data.json" | sha256sum --check --strict

# --- the server ---
FROM ${DEBIAN_IMAGE}
LABEL org.opencontainers.image.source="https://github.com/c0decave/sandbox-ai-mcp" \
      org.opencontainers.image.title="sandbox-ai-mcp-maigret" \
      org.opencontainers.image.description="Username search over thousands of sites with maigret 0.6.6's site database (our own checker, no maigret code, no database updates), an MCP server of sandbox-ai-mcp (stdio)" \
      org.opencontainers.image.licenses="MIT"
# tini: the image's init (its ENTRYPOINT); ca-certificates: the sites' TLS certificates (and pip's download)
RUN apt-get update \
 && apt-get install -y --no-install-recommends tini=0.19.0-3+b8 python3=3.13.5-1 python3-venv=3.13.5-1 \
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
COPY --from=data /build/maigret/resources/data.json /opt/maigret/data.json
COPY src/server.py /opt/mcp/server.py
COPY LICENSES/ /usr/share/doc/sandbox-ai-mcp-maigret/
# The database loads (every entry, engines applied) before anything ships.
RUN /opt/venv/bin/python -m compileall -q /opt/mcp \
 && echo "ef6ca66efa174209c10205ff86f7e975b591128681710639fdc786ff05e662da  /opt/maigret/data.json" \
      | sha256sum --check --strict \
 && chmod 0444 /opt/maigret/data.json \
 && /opt/venv/bin/python -I -c 'import sys; sys.path.insert(0, "/opt/mcp"); import server; \
      db = server.database(); assert len(db.sites) == 5897 and len(db.checkable([])) > 4000' \
 && useradd --uid 10001 --user-group --no-create-home --home-dir /tmp --shell /usr/sbin/nologin mcp
ENV HOME=/tmp
# /etc/hosts of its own (a COPY: a build mounts its own over the image's; Podman and Docker mount theirs at run
# time): the Bubblewrap form has the file, and resolvers that read it find it there.
COPY hosts /etc/hosts
# The usual mount targets exist in every image (a read-only rootfs under Bubblewrap cannot create them).
RUN mkdir -p -m 0755 /work /work_ro /work_rw /app /srv
USER 10001:10001
WORKDIR /tmp
# tini is PID 1 where nothing else is (Podman without the host's catatonit: sandbox-ai then starts the image
# without --init) and reaps what the server leaves; -s: also where it is not PID 1 (Podman's --init, Bubblewrap).
ENTRYPOINT ["/usr/bin/tini", "-s", "--", "/opt/venv/bin/python", "-I", "-u", "/opt/mcp/server.py"]
