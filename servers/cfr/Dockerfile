# cfr: an MCP server of sandbox-ai-mcp (src/server.py) running the CFR 0.152 decompiler, MCP over stdio. Decompiles
# the JAR, WAR, ZIP or .class file it is named from the folder mounted read-only at /work; writes only its own scratch
# folder below /tmp; no network.
ARG DEBIAN_IMAGE=docker.io/library/debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad
FROM ${DEBIAN_IMAGE}
# CFR 0.152 (2021-12-11, the latest release): the release asset by its SHA-256 (GitHub publishes no digest for it)
ARG CFR_URL=https://github.com/leibnitz27/cfr/releases/download/0.152/cfr-0.152.jar
ARG CFR_SHA256=f686e8f3ded377d7bc87d216a90e9e9512df4156e75b06c655a16648ae8765b2
LABEL org.opencontainers.image.source="https://github.com/c0decave/sandbox-ai-mcp" \
      org.opencontainers.image.title="sandbox-ai-mcp-cfr" \
      org.opencontainers.image.description="Java decompilation with CFR 0.152: classes of a JAR/WAR, class outlines, the Java source of a class or one method, string constant search; read-only input, no network, an MCP server of sandbox-ai-mcp (stdio)" \
      org.opencontainers.image.licenses="MIT"
# ca-certificates only for pip's download while the image is built (Debian's pip uses the system's certificates)
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3=3.13.5-1 python3-venv=3.13.5-1 \
      ca-certificates=20250419+deb13u1 openjdk-21-jre-headless=21.0.13+9-1~deb13u2 \
 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /opt/mcp/requirements.txt
# pip is removed from the venv and the venv tooling is purged: nothing installs Python packages at run time
RUN python3 -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir --disable-pip-version-check --require-hashes \
      --only-binary=:all: -r /opt/mcp/requirements.txt \
 && /opt/venv/bin/python -m pip uninstall -y -q pip \
 && apt-get purge -y -q python3-venv python3.13-venv python3-pip-whl python3-setuptools-whl \
 && rm -rf /var/cache/apt /var/log/apt /var/log/dpkg.log
ADD --checksum=sha256:${CFR_SHA256} ${CFR_URL} /opt/cfr/cfr-0.152.jar
COPY src/server.py /opt/mcp/server.py
COPY LICENSES/ /usr/share/doc/sandbox-ai-mcp-cfr/
# The paths src/server.py names must be there, and CFR must run before anything ships.
RUN /opt/venv/bin/python -m compileall -q /opt/mcp \
 && chmod 0644 /opt/cfr/cfr-0.152.jar \
 && test -x /usr/lib/jvm/java-21-openjdk-amd64/bin/java \
 && /usr/lib/jvm/java-21-openjdk-amd64/bin/java -XX:-UsePerfData -jar /opt/cfr/cfr-0.152.jar --version 2>&1 \
      | grep -q "CFR 0.152" \
 && useradd --uid 10001 --user-group --no-create-home --home-dir /tmp --shell /usr/sbin/nologin mcp \
 && mkdir -p /work
ENV HOME=/tmp
USER 10001:10001
WORKDIR /tmp
ENTRYPOINT ["/opt/venv/bin/python", "-I", "-u", "/opt/mcp/server.py"]
