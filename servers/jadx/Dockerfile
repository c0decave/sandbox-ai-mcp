# jadx: an MCP server of sandbox-ai-mcp (src/server.py, with src/JadxBridge.java on jadx 1.5.6's library), MCP over
# stdio. Decompiles the APK, DEX, JAR, AAR, ... it is named from the folder mounted read-only at /work; writes only
# its own scratch folder below /tmp; no network.
ARG DEBIAN_IMAGE=docker.io/library/debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad

# --- the bridge, compiled against the release's jar ---
FROM ${DEBIAN_IMAGE} AS build
# jadx 1.5.6 (2026-07-10): the release asset and the SHA-256 GitHub publishes for it; the jar inside by its SHA-256
ARG JADX_URL=https://github.com/skylot/jadx/releases/download/v1.5.6/jadx-1.5.6.zip
ARG JADX_SHA256=545ea2be9c242511bc145755cf4bda2485ade42966e096f8b4d3da2a230e8974
ARG JADX_JAR_SHA256=fe3e12c45acf75f92369685fd02d1d7a7323385dc725680a9b98a0dac0ea554b
RUN apt-get update \
 && apt-get install -y --no-install-recommends openjdk-21-jdk-headless=21.0.13.1+2-1~deb13u1 openjdk-21-jre-headless=21.0.13.1+2-1~deb13u1 \
      unzip=6.0-29+deb13u1 \
 && rm -rf /var/lib/apt/lists/*
ADD --checksum=sha256:${JADX_SHA256} ${JADX_URL} /build/jadx-1.5.6.zip
COPY src/JadxBridge.java /build/src/JadxBridge.java
RUN cd /build \
 && unzip -q jadx-1.5.6.zip lib/jadx-1.5.6-all.jar \
 && echo "${JADX_JAR_SHA256}  lib/jadx-1.5.6-all.jar" | sha256sum --check --strict \
 && mkdir bridge \
 && javac --release 21 -Xlint:all -Werror -cp lib/jadx-1.5.6-all.jar -d bridge src/JadxBridge.java

# --- the server ---
FROM ${DEBIAN_IMAGE}
LABEL org.opencontainers.image.source="https://github.com/c0decave/sandbox-ai-mcp" \
      org.opencontainers.image.title="sandbox-ai-mcp-jadx" \
      org.opencontainers.image.description="Android and Java decompilation with jadx 1.5.6, headless: classes, Java source of classes and methods, smali, cross references, code and name search, AndroidManifest.xml and resources; read-only input, no network, an MCP server of sandbox-ai-mcp (stdio)" \
      org.opencontainers.image.licenses="MIT AND Apache-2.0"
# ca-certificates only for pip's download while the image is built (Debian's pip uses the system's certificates)
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3=3.13.5-1 python3-venv=3.13.5-1 \
      ca-certificates=20250419+deb13u1 openjdk-21-jre-headless=21.0.13.1+2-1~deb13u1 \
 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /opt/mcp/requirements.txt
# pip is removed from the venv and the venv tooling is purged: nothing installs Python packages at run time
RUN python3 -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir --disable-pip-version-check --require-hashes \
      --only-binary=:all: -r /opt/mcp/requirements.txt \
 && /opt/venv/bin/python -m pip uninstall -y -q pip \
 && apt-get purge -y -q python3-venv python3.13-venv python3-pip-whl python3-setuptools-whl \
 && rm -rf /var/cache/apt /var/log/apt /var/log/dpkg.log
COPY --from=build /build/lib/jadx-1.5.6-all.jar /opt/jadx/lib/jadx-1.5.6-all.jar
COPY --from=build /build/bridge/ /opt/mcp/bridge/
COPY src/server.py /opt/mcp/server.py
COPY LICENSES/ /usr/share/doc/sandbox-ai-mcp-jadx/
# The paths src/server.py names must be there; the bridge loads (its classes against the jar) before anything ships.
RUN /opt/venv/bin/python -m compileall -q /opt/mcp \
 && test -x /usr/lib/jvm/java-21-openjdk-amd64/bin/java \
 && echo "fe3e12c45acf75f92369685fd02d1d7a7323385dc725680a9b98a0dac0ea554b  /opt/jadx/lib/jadx-1.5.6-all.jar" \
      | sha256sum --check --strict \
 && mkdir /tmp/check && /usr/lib/jvm/java-21-openjdk-amd64/bin/java -XX:-UsePerfData -Djava.io.tmpdir=/tmp/check \
      -cp /opt/jadx/lib/jadx-1.5.6-all.jar:/opt/mcp/bridge JadxBridge /nonexistent < /dev/null \
      | grep -q '"id":0,"ok":false,"error":"jadx could not load the file' \
 && rm -rf /tmp/check \
 && useradd --uid 10001 --user-group --no-create-home --home-dir /tmp --shell /usr/sbin/nologin mcp \
 && mkdir -p /work
ENV HOME=/tmp
USER 10001:10001
WORKDIR /tmp
ENTRYPOINT ["/opt/venv/bin/python", "-I", "-u", "/opt/mcp/server.py"]
