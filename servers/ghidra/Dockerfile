# ghidra: an MCP server of sandbox-ai-mcp (src/server.py, with src/GhidraBridge.java on Ghidra 12.2's headless API),
# MCP over stdio. Imports and analyses the executables, libraries and firmware it is named from the folder mounted
# read-only at /work; no Ghidra project, nothing saved; writes only its own scratch folder below /tmp; no network.
ARG DEBIAN_IMAGE=docker.io/library/debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad

# --- Ghidra, pruned, and the bridge compiled against it ---
FROM ${DEBIAN_IMAGE} AS build
# Ghidra 12.2 (NSA, Apache-2.0; tag Ghidra_12.2_build, published 2026-10-22): the release asset and the SHA-256
# GitHub publishes for it
ARG GHIDRA_URL=https://github.com/NationalSecurityAgency/ghidra/releases/download/Ghidra_12.2_build/ghidra_12.2_PUBLIC_20261016.zip
ARG GHIDRA_SHA256=2c2cd776db3c1f6a097ba418922378ac3649cadd5e844a6f5f088ae628a7be67
# Eclipse Temurin JDK 25.0.5+8 for Linux x64 (2026-10-22; Ghidra 12.2 needs Java 25): javac and jar for the bridge
# only, it does not ship; the JRE of the same release runs it (below)
ARG TEMURIN_JDK_URL=https://github.com/adoptium/temurin25-binaries/releases/download/jdk-25.0.5%2B8/OpenJDK25U-jdk_x64_linux_hotspot_25.0.5_8.tar.gz
ARG TEMURIN_JDK_SHA256=68982529869257d0ee6b824ec5aa270ff8b118bb438670da0b97ebdab178d7fb
RUN apt-get update \
 && apt-get install -y --no-install-recommends unzip=6.0-29+deb13u1 \
 && rm -rf /var/lib/apt/lists/*
ADD --checksum=sha256:${GHIDRA_SHA256} ${GHIDRA_URL} /build/ghidra.zip
ADD --checksum=sha256:${TEMURIN_JDK_SHA256} ${TEMURIN_JDK_URL} /build/jdk.tar.gz
# What does not ship (PROVENANCE.md): the debugger (Ghidra/Debug: agents for gdb, lldb, WinDbg, trace RMI sockets),
# the Ghidra Server and its client side's server (Features/GhidraServer, server/), BSim (PostgreSQL and Elasticsearch
# clients), PyGhidra (the JPype bridge), GhidraGo (ghidra:// URLs), the optional extensions (Extensions/, not
# installed), the documentation, the Docker files, the Windows and macOS binaries.
RUN cd /build \
 && unzip -q ghidra.zip \
 && mv ghidra_12.2_PUBLIC /opt/ghidra \
 && rm -rf /opt/ghidra/docs /opt/ghidra/Extensions /opt/ghidra/server /opt/ghidra/docker /opt/ghidra/Ghidra/Extensions \
      /opt/ghidra/Ghidra/Debug /opt/ghidra/Ghidra/Features/GhidraServer /opt/ghidra/Ghidra/Features/BSim \
      /opt/ghidra/Ghidra/Features/BSimFeatureVisualizer /opt/ghidra/Ghidra/Features/PyGhidra \
      /opt/ghidra/Ghidra/Features/GhidraGo /opt/ghidra/GPL/DMG \
 && find /opt/ghidra -depth -type d \( -path '*/os/win_*' -o -path '*/os/mac_*' \) -exec rm -rf {} + \
 && find /opt/ghidra \( -name '*.bat' -o -name '*.exe' -o -name '*.dll' \) -delete \
 && chmod -R a+rX,go-w /opt/ghidra \
 && mkdir /build/jdk && tar -xzf jdk.tar.gz -C /build/jdk --strip-components=1 --no-same-owner
COPY src/GhidraBridge.java /build/src/GhidraBridge.java
RUN cd /build \
 && CP=$(find /opt/ghidra/Ghidra/Framework /opt/ghidra/Ghidra/Features/Base /opt/ghidra/Ghidra/Features/Decompiler \
      -name '*.jar' | sort | tr '\n' ':') \
 && mkdir bridge module module/lib \
 && /build/jdk/bin/javac --release 25 -Xlint:all,-path,-classfile -Werror -cp "$CP" -d bridge src/GhidraBridge.java \
 && /build/jdk/bin/jar --create --file module/lib/sandbox-ai-mcp-ghidra.jar -C bridge . \
 && : > module/Module.manifest

# --- the server ---
FROM ${DEBIAN_IMAGE}
LABEL org.opencontainers.image.source="https://github.com/c0decave/sandbox-ai-mcp" \
      org.opencontainers.image.title="sandbox-ai-mcp-ghidra" \
      org.opencontainers.image.description="Binary analysis with Ghidra 12.2, headless: import and auto-analysis, functions, C from the decompiler, disassembly, calls, cross references, imports, exports and strings; read-only input, no network, an MCP server of sandbox-ai-mcp (stdio)" \
      org.opencontainers.image.licenses="MIT AND Apache-2.0"
# Eclipse Temurin JRE 25.0.5+8 for Linux x64 (2026-10-22), the SHA-256 GitHub and its .sha256.txt publish (the JRE
# of servers/signal)
ARG TEMURIN_JRE_URL=https://github.com/adoptium/temurin25-binaries/releases/download/jdk-25.0.5%2B8/OpenJDK25U-jre_x64_linux_hotspot_25.0.5_8.tar.gz
ARG TEMURIN_JRE_SHA256=6fac98f0c8202efc3135a9e9e42aa61963ec42d1c5cbb40caf231e7b14a24ef6
# tini: the image's init (its ENTRYPOINT); python3: the server; libstdc++6: Ghidra's decompiler and demangler (native
# C++ programs of the release); ca-certificates only for pip's download while the image is built
RUN apt-get update \
 && apt-get install -y --no-install-recommends tini=0.19.0-3+b8 python3=3.13.5-1 python3-venv=3.13.5-1 \
      ca-certificates=20250419+deb13u1 libstdc++6=14.2.0-19 \
 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /opt/mcp/requirements.txt
# pip is removed from the venv and the venv tooling is purged: nothing installs Python packages at run time
RUN python3 -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir --disable-pip-version-check --require-hashes \
      --only-binary=:all: -r /opt/mcp/requirements.txt \
 && /opt/venv/bin/python -m pip uninstall -y -q pip \
 && apt-get purge -y -q python3-venv python3.13-venv python3-pip-whl python3-setuptools-whl \
 && rm -rf /var/cache/apt /var/log/apt /var/log/dpkg.log
ADD --checksum=sha256:${TEMURIN_JRE_SHA256} ${TEMURIN_JRE_URL} /tmp/jre.tar.gz
RUN mkdir -p /opt/java \
 && tar -xzf /tmp/jre.tar.gz -C /opt/java --strip-components=1 --no-same-owner \
 && rm /tmp/jre.tar.gz \
 && chmod -R a+rX,go-w /opt/java
COPY --from=build /opt/ghidra/ /opt/ghidra/
COPY --from=build /build/module/ /opt/mcp/ghidra-module/
COPY src/server.py /opt/mcp/server.py
COPY LICENSES/ /usr/share/doc/sandbox-ai-mcp-ghidra/
# The paths src/server.py names must be there; the bridge starts inside Ghidra and refuses a file that is not there
# (Ghidra's whole start - class loader, modules, the bridge found as a module - before anything ships).
RUN /opt/venv/bin/python -m compileall -q /opt/mcp \
 && test -x /opt/java/bin/java \
 && test -x /opt/ghidra/Ghidra/Features/Decompiler/os/linux_x86_64/decompile \
 && mkdir -p /tmp/check/tmp \
 && /opt/java/bin/java -XX:-UsePerfData -Xshare:off -Djava.awt.headless=true \
      -Djava.system.class.loader=ghidra.GhidraClassLoader -Dghidra.external.modules=/opt/mcp/ghidra-module \
      -Djava.io.tmpdir=/tmp/check/tmp -Duser.home=/tmp/check/tmp -Dapplication.settingsdir=/tmp/check/settings \
      -Dapplication.cachedir=/tmp/check/cache -Dapplication.tempdir=/tmp/check/tmp \
      --enable-native-access=ALL-UNNAMED --sun-misc-unsafe-memory-access=allow \
      -cp /opt/ghidra/Ghidra/Framework/Utility/lib/Utility.jar ghidra.Ghidra GhidraBridge /nonexistent x 60 \
      < /dev/null 2>/dev/null | grep -q '"id":0,"ok":false,"error":"Ghidra could not import the file' \
 && rm -rf /tmp/check \
 && useradd --uid 10001 --user-group --no-create-home --home-dir /tmp --shell /usr/sbin/nologin mcp
ENV HOME=/tmp
# The usual mount targets exist in every image (a read-only rootfs under Bubblewrap cannot create them).
RUN mkdir -p -m 0755 /work /work_ro /work_rw /app /srv
USER 10001:10001
WORKDIR /tmp
# tini is PID 1 where nothing else is (Podman without the host's catatonit: sandbox-ai then starts the image
# without --init) and reaps what the server leaves; -s: also where it is not PID 1 (Podman's --init, Bubblewrap).
ENTRYPOINT ["/usr/bin/tini", "-s", "--", "/opt/venv/bin/python", "-I", "-u", "/opt/mcp/server.py"]
