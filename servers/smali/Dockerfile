# smali: an MCP server of sandbox-ai-mcp (src/server.py) running baksmali/smali 3.0.10, apktool 3.0.3, Android's
# zipalign and apksigner, MCP over stdio. Reads the apps of the folder mounted read-only at /work, writes only the
# folder mounted writable at /out and its own scratch folder below /tmp; no network, no key of yours.
ARG DEBIAN_IMAGE=docker.io/library/debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad

# --- the pinned release files, unpacked and checked ---
FROM ${DEBIAN_IMAGE} AS tools
# smali and baksmali 3.0.10 (baksmali/smali, the release artifacts of google/smali 3.0.10, 2026-08-24): the fat jars
# by the SHA-256 GitHub publishes for them
ARG BAKSMALI_URL=https://github.com/baksmali/smali/releases/download/3.0.10/baksmali-3.0.10-fat-release.jar
ARG BAKSMALI_SHA256=37ae4a41a8886e15c20b8362fa4250f96bbdb55e1a608199ad8b5dff068b588f
ARG SMALI_URL=https://github.com/baksmali/smali/releases/download/3.0.10/smali-3.0.10-fat-release.jar
ARG SMALI_SHA256=32fa0e88a6c397b3922201adf5f3e534fbaed5a663c71d0c558c3ddce0af844a
# apktool 3.0.3 (iBotPeaches/Apktool, 2026-07-20): the release jar by the SHA-256 GitHub publishes for it, and the two
# files taken out of it - apktool's own aapt2 2.20 and its android-framework.jar - each by its SHA-256
ARG APKTOOL_URL=https://github.com/iBotPeaches/Apktool/releases/download/v3.0.3/apktool_3.0.3.jar
ARG APKTOOL_SHA256=dbf930b076c6b9be08d57c449cacefc3bdd6b71ebd59b3066fc0e1f5b14f9423
ARG APKTOOL_AAPT2_SHA256=df312db814c018019b2b79a993b041b738d7b76f4a8f28da25bc874a026368cc
ARG APKTOOL_FRAMEWORK_SHA256=5dd984016ed5a5eb0eef866e2c6e8cd352e1427828ec23adb18005cf5648f3d7
RUN apt-get update \
 && apt-get install -y --no-install-recommends unzip=6.0-29+deb13u1 \
 && rm -rf /var/lib/apt/lists/*
ADD --checksum=sha256:${BAKSMALI_SHA256} ${BAKSMALI_URL} /build/smali/baksmali-3.0.10-fat-release.jar
ADD --checksum=sha256:${SMALI_SHA256} ${SMALI_URL} /build/smali/smali-3.0.10-fat-release.jar
ADD --checksum=sha256:${APKTOOL_SHA256} ${APKTOOL_URL} /build/apktool/apktool_3.0.3.jar
# apktool starts aapt2 as a child process with paths of its own, and it installs the framework into its frame path at
# run time: both are taken out of the jar here instead, so that nothing is unpacked or written while the server runs
# (a read-only root, and a /tmp that may be noexec).
RUN cd /build/apktool \
 && unzip -q -j apktool_3.0.3.jar prebuilt/linux/aapt2 prebuilt/android-framework.jar \
 && mkdir framework \
 && mv android-framework.jar framework/1.apk \
 && echo "${APKTOOL_AAPT2_SHA256}  aapt2" | sha256sum --check --strict \
 && echo "${APKTOOL_FRAMEWORK_SHA256}  framework/1.apk" | sha256sum --check --strict \
 && chmod 0755 aapt2 && chmod 0444 framework/1.apk apktool_3.0.3.jar \
 && chmod 0444 /build/smali/baksmali-3.0.10-fat-release.jar /build/smali/smali-3.0.10-fat-release.jar

# --- the server ---
FROM ${DEBIAN_IMAGE}
LABEL org.opencontainers.image.source="https://github.com/c0decave/sandbox-ai-mcp" \
      org.opencontainers.image.title="sandbox-ai-mcp-smali" \
      org.opencontainers.image.description="Android bytecode as smali and APKs taken apart and put together again: baksmali/smali 3.0.10, apktool 3.0.3, zipalign and apksigner with a throwaway debug key; input read-only, output in a folder of its own, no network, an MCP server of sandbox-ai-mcp (stdio)" \
      org.opencontainers.image.licenses="MIT AND Apache-2.0 AND BSD-3-Clause"
# ca-certificates only for pip's download while the image is built (Debian's pip uses the system's certificates).
# zipalign and apksigner are Debian's Android build tools; libapksig-java holds the signing library. The apksigner
# package's first alternative dependency is default-jre (an X11 JRE), so its one jar is taken out of the package file
# instead - the JRE here is openjdk-21-jre-headless, as in servers/jadx and servers/cfr.
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3=3.13.5-1 python3-venv=3.13.5-1 \
      ca-certificates=20250419+deb13u1 openjdk-21-jre-headless=21.0.13.1+2-1~deb13u1 \
      zipalign=1:10.0.0+r36-1.1 libapksig-java=35.0.2-1 \
 && apt-get download -q apksigner=35.0.2-1 \
 && dpkg-deb --fsys-tarfile apksigner_35.0.2-1_all.deb \
      | tar -x -C / ./usr/share/java/apksigner-35.0.2.jar \
 && rm -f apksigner_35.0.2-1_all.deb \
 && test -f /usr/share/java/apksigner-35.0.2.jar \
 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /opt/mcp/requirements.txt
# pip is removed from the venv and the venv tooling is purged: nothing installs Python packages at run time
RUN python3 -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir --disable-pip-version-check --require-hashes \
      --only-binary=:all: -r /opt/mcp/requirements.txt \
 && /opt/venv/bin/python -m pip uninstall -y -q pip \
 && apt-get purge -y -q python3-venv python3.13-venv python3-pip-whl python3-setuptools-whl \
 && rm -rf /var/cache/apt /var/log/apt /var/log/dpkg.log
COPY --from=tools /build/smali/ /opt/smali/
COPY --from=tools /build/apktool/apktool_3.0.3.jar /opt/apktool/apktool_3.0.3.jar
COPY --from=tools /build/apktool/aapt2 /opt/apktool/aapt2
COPY --from=tools /build/apktool/framework/1.apk /opt/apktool/framework/1.apk
COPY src/server.py /opt/mcp/server.py
COPY LICENSES/ /usr/share/doc/sandbox-ai-mcp-smali/
# Every path src/server.py names must be there, and every tool must run, before anything ships (a version may
# come on stderr: CFR's does).
RUN /opt/venv/bin/python -m compileall -q /opt/mcp \
 && test -x /usr/lib/jvm/java-21-openjdk-amd64/bin/java \
 && test -x /usr/lib/jvm/java-21-openjdk-amd64/bin/keytool \
 && test -x /usr/bin/zipalign \
 && test -r /opt/apktool/framework/1.apk \
 && java=/usr/lib/jvm/java-21-openjdk-amd64/bin/java \
 && "$java" -XX:-UsePerfData -jar /opt/smali/baksmali-3.0.10-fat-release.jar --version 2>&1 | grep -q "baksmali 3.0.10" \
 && "$java" -XX:-UsePerfData -jar /opt/smali/smali-3.0.10-fat-release.jar --version 2>&1 | grep -q "smali 3.0.10" \
 && "$java" -XX:-UsePerfData -jar /opt/apktool/apktool_3.0.3.jar --version 2>&1 | grep -q "3.0.3" \
 && "$java" -XX:-UsePerfData -cp /usr/share/java/apksigner-35.0.2.jar:/usr/share/java/apksig-0.9.jar \
      com.android.apksigner.ApkSignerTool --version 2>&1 | grep -q "0.9" \
 && /opt/apktool/aapt2 version 2>&1 | grep -q "Android Asset Packaging Tool" \
 && useradd --uid 10001 --user-group --no-create-home --home-dir /tmp --shell /usr/sbin/nologin mcp \
 && mkdir -p /work /out
ENV HOME=/tmp
USER 10001:10001
WORKDIR /tmp
ENTRYPOINT ["/opt/venv/bin/python", "-I", "-u", "/opt/mcp/server.py"]
