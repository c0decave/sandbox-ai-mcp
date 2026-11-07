# Ghidra 12.2 headless + pyghidra-mcp 0.3.0 (clearbluejar, Apache-2.0), MCP over stdio.
# PREPARED, NOT YET BUILT: the Debian package versions are not pinned here (this repository pins
# every package by version). Fill JDK_VERSION, UNZIP_VERSION and PYTHON_VERSION with the versions
# of the pinned base (podman run --rm BASE sh -c 'apt-get update -qq && apt-cache policy
# openjdk-21-jre-headless unzip python3'), then move this folder to servers/ and add it to the CI
# matrix. Without them the build stops at the first RUN.
ARG DEBIAN_IMAGE=docker.io/library/debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad
FROM ${DEBIAN_IMAGE}
ARG JDK_VERSION
ARG UNZIP_VERSION
ARG PYTHON_VERSION
# The release asset and the SHA-256 GitHub publishes for it (Ghidra_12.2_build).
ARG GHIDRA_URL=https://github.com/NationalSecurityAgency/ghidra/releases/download/Ghidra_12.2_build/ghidra_12.2_PUBLIC_20261016.zip
ARG GHIDRA_SHA256=2c2cd776db3c1f6a097ba418922378ac3649cadd5e844a6f5f088ae628a7be67
LABEL org.opencontainers.image.source="https://github.com/c0decave/sandbox-ai-mcp" \
      org.opencontainers.image.title="sandbox-ai-mcp-ghidra" \
      org.opencontainers.image.description="Ghidra headless analysis through pyghidra-mcp, an MCP server of sandbox-ai-mcp (stdio)" \
      org.opencontainers.image.licenses="Apache-2.0"
RUN test -n "${JDK_VERSION}" && test -n "${UNZIP_VERSION}" && test -n "${PYTHON_VERSION}" \
      || { echo "pin JDK_VERSION, UNZIP_VERSION and PYTHON_VERSION (see the top of this file)" >&2; exit 1; }
RUN apt-get update \
 && apt-get install -y --no-install-recommends openjdk-21-jre-headless=${JDK_VERSION} unzip=${UNZIP_VERSION} \
      python3=${PYTHON_VERSION} python3-venv=${PYTHON_VERSION} ca-certificates=20250419+deb13u1 \
 && rm -rf /var/lib/apt/lists/*
ADD --checksum=sha256:${GHIDRA_SHA256} ${GHIDRA_URL} /tmp/ghidra.zip
RUN unzip -q /tmp/ghidra.zip -d /opt && mv /opt/ghidra_12.2_PUBLIC /opt/ghidra && rm /tmp/ghidra.zip \
 && apt-get purge -y -q unzip
COPY requirements.txt /opt/mcp/requirements.txt
RUN python3 -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir --disable-pip-version-check --require-hashes \
      --only-binary=:all: -r /opt/mcp/requirements.txt \
 && /opt/venv/bin/python -m pip uninstall -y -q pip \
 && apt-get purge -y -q python3-venv python3-pip-whl python3-setuptools-whl \
 && rm -rf /var/cache/apt /var/log/apt /var/log/dpkg.log
COPY LICENSES/ /usr/share/doc/sandbox-ai-mcp-ghidra/
RUN useradd --uid 10001 --user-group --no-create-home --home-dir /tmp --shell /usr/sbin/nologin mcp
ENV HOME=/tmp GHIDRA_INSTALL_DIR=/opt/ghidra JAVA_TOOL_OPTIONS="-Xmx2g -Djava.awt.headless=true"
USER 10001:10001
WORKDIR /tmp
# The project (analysis database) lives in /out when it is mounted writable, else in /tmp.
ENTRYPOINT ["/opt/venv/bin/pyghidra-mcp", "--transport", "stdio", "--no-gui", "--project-path", "/out/ghidra-projects"]
