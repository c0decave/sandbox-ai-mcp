# smali: an MCP server of sandbox-ai-mcp (src/server.py) running Google's baksmali/smali 3.0.10, apktool 3.0.3, Android's
# zipalign and apksigner, MCP over stdio. Reads the apps of the folder mounted read-only at /work, writes only the
# folder mounted writable at /out and its own scratch folder below /tmp; no network, no key of yours.
ARG DEBIAN_IMAGE=docker.io/library/debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad

# --- the pinned release files, unpacked and checked ---
FROM ${DEBIAN_IMAGE} AS tools
# smali and baksmali 3.0.10 as Google publishes them: com.android.tools.smali:{smali,smali-baksmali,smali-dexlib2,
# smali-util}:3.0.10 in Google's Maven repository (maven.google.com; not on Maven Central), uploaded 2026-09-04,
# then exactly the runtime dependencies their POMs name, from Maven Central (each with the date Maven Central
# serves for it). Every SHA-256 was computed here and matched every checksum file the repository publishes beside
# the jar (PROVENANCE.md says which); CI checks them again before every build (maven-central.json,
# scripts/maven_central.py) and that the image holds exactly these jars.
ARG SMALI_URL=https://dl.google.com/dl/android/maven2/com/android/tools/smali/smali/3.0.10/smali-3.0.10.jar
ARG SMALI_SHA256=b54c34f7a1b769b1e637f8a26909c68f399c273f3e5cde3e308e91107c135305
ARG BAKSMALI_URL=https://dl.google.com/dl/android/maven2/com/android/tools/smali/smali-baksmali/3.0.10/smali-baksmali-3.0.10.jar
ARG BAKSMALI_SHA256=7d6578dfe5c44f1984b64268e91834432b0942d49e08186a501039dd92b58213
ARG DEXLIB2_URL=https://dl.google.com/dl/android/maven2/com/android/tools/smali/smali-dexlib2/3.0.10/smali-dexlib2-3.0.10.jar
ARG DEXLIB2_SHA256=688dee6a46962a4dd1774b64be926534b0b6504bfd5d5c9f89c0f5af284f50c1
ARG SMALI_UTIL_URL=https://dl.google.com/dl/android/maven2/com/android/tools/smali/smali-util/3.0.10/smali-util-3.0.10.jar
ARG SMALI_UTIL_SHA256=cc2ef8349765644e4b15371f2c9f77d69b5412a094a38fe5fd992a124b7322fe
# com.google.guava:guava:31.1-android (2022-02-28)
ARG GUAVA_URL=https://repo1.maven.org/maven2/com/google/guava/guava/31.1-android/guava-31.1-android.jar
ARG GUAVA_SHA256=32ac2ed709d96d278b5d2e3e5cea178fa4939939c525fb647532f013308db309
# com.google.guava:failureaccess:1.0.1 (2018-11-19)
ARG FAILUREACCESS_URL=https://repo1.maven.org/maven2/com/google/guava/failureaccess/1.0.1/failureaccess-1.0.1.jar
ARG FAILUREACCESS_SHA256=a171ee4c734dd2da837e4b16be9df4661afab72a41adaf31eb84dfdaf936ca26
# com.google.guava:listenablefuture:9999.0-empty-to-avoid-conflict-with-guava (2018-09-11)
ARG LISTENABLEFUTURE_URL=https://repo1.maven.org/maven2/com/google/guava/listenablefuture/9999.0-empty-to-avoid-conflict-with-guava/listenablefuture-9999.0-empty-to-avoid-conflict-with-guava.jar
ARG LISTENABLEFUTURE_SHA256=b372a037d4230aa57fbeffdef30fd6123f9c0c2db85d0aced00c91b974f33f99
# com.google.code.findbugs:jsr305:3.0.2 (2017-03-31)
ARG JSR305_URL=https://repo1.maven.org/maven2/com/google/code/findbugs/jsr305/3.0.2/jsr305-3.0.2.jar
ARG JSR305_SHA256=766ad2a0783f2687962c8ad74ceecc38a28b9f72a2d085ee438b7813e928d0c7
# org.checkerframework:checker-qual:3.12.0 (2021-04-01)
ARG CHECKER_QUAL_URL=https://repo1.maven.org/maven2/org/checkerframework/checker-qual/3.12.0/checker-qual-3.12.0.jar
ARG CHECKER_QUAL_SHA256=ff10785ac2a357ec5de9c293cb982a2cbb605c0309ea4cc1cb9b9bc6dbe7f3cb
# com.google.errorprone:error_prone_annotations:2.11.0 (2022-01-25)
ARG ERROR_PRONE_URL=https://repo1.maven.org/maven2/com/google/errorprone/error_prone_annotations/2.11.0/error_prone_annotations-2.11.0.jar
ARG ERROR_PRONE_SHA256=721cb91842b46fa056847d104d5225c8b8e1e8b62263b993051e1e5a0137b7ec
# com.google.j2objc:j2objc-annotations:1.3 (2017-01-18)
ARG J2OBJC_URL=https://repo1.maven.org/maven2/com/google/j2objc/j2objc-annotations/1.3/j2objc-annotations-1.3.jar
ARG J2OBJC_SHA256=21af30c92267bd6122c0e0b4d20cccb6641a37eaf956c6540ec471d584e64a7b
# org.jcommander:jcommander:1.85 (2024-08-18)
ARG JCOMMANDER_URL=https://repo1.maven.org/maven2/org/jcommander/jcommander/1.85/jcommander-1.85.jar
ARG JCOMMANDER_SHA256=fa7552d2831a2b20778d86851d093edca68fbc0a77f792b6223110e4fae67a70
# org.antlr:antlr:3.5.2 (2014-03-25)
ARG ANTLR3_URL=https://repo1.maven.org/maven2/org/antlr/antlr/3.5.2/antlr-3.5.2.jar
ARG ANTLR3_SHA256=5ac36c2acfb0a0f3d37dafe20b5b570f2643e2d000c648d44503c2738be643df
# org.antlr:antlr-runtime:3.5.2 (2014-03-25)
ARG ANTLR3_RUNTIME_URL=https://repo1.maven.org/maven2/org/antlr/antlr-runtime/3.5.2/antlr-runtime-3.5.2.jar
ARG ANTLR3_RUNTIME_SHA256=ce3fc8ecb10f39e9a3cddcbb2ce350d272d9cd3d0b1e18e6fe73c3b9389c8734
# org.antlr:ST4:4.0.8 (2014-03-25)
ARG ST4_URL=https://repo1.maven.org/maven2/org/antlr/ST4/4.0.8/ST4-4.0.8.jar
ARG ST4_SHA256=58caabc40c9f74b0b5993fd868e0f64a50c0759094e6a251aaafad98edfc7a3b
# org.antlr:stringtemplate:3.2.1 (2009-09-22)
ARG STRINGTEMPLATE_URL=https://repo1.maven.org/maven2/org/antlr/stringtemplate/3.2.1/stringtemplate-3.2.1.jar
ARG STRINGTEMPLATE_SHA256=f66ce72e965e5301cb0f020e54d2ba6ad76feb91b3cbfc30dbbf00c06a6df6d7
# antlr:antlr:2.7.7 (2007-01-13)
ARG ANTLR2_URL=https://repo1.maven.org/maven2/antlr/antlr/2.7.7/antlr-2.7.7.jar
ARG ANTLR2_SHA256=88fbda4b912596b9f56e8e12e580cc954bacfb51776ecfddd3e18fc1cf56dc4c
# apktool 3.0.3 (iBotPeaches/Apktool, 2026-07-20): the release jar by the SHA-256 GitHub publishes for it, and the two
# files taken out of it - apktool's own aapt2 2.20 and its android-framework.jar - each by its SHA-256
ARG APKTOOL_URL=https://github.com/iBotPeaches/Apktool/releases/download/v3.0.3/apktool_3.0.3.jar
ARG APKTOOL_SHA256=dbf930b076c6b9be08d57c449cacefc3bdd6b71ebd59b3066fc0e1f5b14f9423
ARG APKTOOL_AAPT2_SHA256=df312db814c018019b2b79a993b041b738d7b76f4a8f28da25bc874a026368cc
ARG APKTOOL_FRAMEWORK_SHA256=5dd984016ed5a5eb0eef866e2c6e8cd352e1427828ec23adb18005cf5648f3d7
RUN apt-get update \
 && apt-get install -y --no-install-recommends unzip=6.0-29+deb13u1 \
 && rm -rf /var/lib/apt/lists/*
ADD --checksum=sha256:${SMALI_SHA256} ${SMALI_URL} /build/smali/smali-3.0.10.jar
ADD --checksum=sha256:${BAKSMALI_SHA256} ${BAKSMALI_URL} /build/smali/smali-baksmali-3.0.10.jar
ADD --checksum=sha256:${DEXLIB2_SHA256} ${DEXLIB2_URL} /build/smali/smali-dexlib2-3.0.10.jar
ADD --checksum=sha256:${SMALI_UTIL_SHA256} ${SMALI_UTIL_URL} /build/smali/smali-util-3.0.10.jar
ADD --checksum=sha256:${GUAVA_SHA256} ${GUAVA_URL} /build/smali/guava-31.1-android.jar
ADD --checksum=sha256:${FAILUREACCESS_SHA256} ${FAILUREACCESS_URL} /build/smali/failureaccess-1.0.1.jar
ADD --checksum=sha256:${LISTENABLEFUTURE_SHA256} ${LISTENABLEFUTURE_URL} /build/smali/listenablefuture-9999.0-empty-to-avoid-conflict-with-guava.jar
ADD --checksum=sha256:${JSR305_SHA256} ${JSR305_URL} /build/smali/jsr305-3.0.2.jar
ADD --checksum=sha256:${CHECKER_QUAL_SHA256} ${CHECKER_QUAL_URL} /build/smali/checker-qual-3.12.0.jar
ADD --checksum=sha256:${ERROR_PRONE_SHA256} ${ERROR_PRONE_URL} /build/smali/error_prone_annotations-2.11.0.jar
ADD --checksum=sha256:${J2OBJC_SHA256} ${J2OBJC_URL} /build/smali/j2objc-annotations-1.3.jar
ADD --checksum=sha256:${JCOMMANDER_SHA256} ${JCOMMANDER_URL} /build/smali/jcommander-1.85.jar
ADD --checksum=sha256:${ANTLR3_SHA256} ${ANTLR3_URL} /build/smali/antlr-3.5.2.jar
ADD --checksum=sha256:${ANTLR3_RUNTIME_SHA256} ${ANTLR3_RUNTIME_URL} /build/smali/antlr-runtime-3.5.2.jar
ADD --checksum=sha256:${ST4_SHA256} ${ST4_URL} /build/smali/ST4-4.0.8.jar
ADD --checksum=sha256:${STRINGTEMPLATE_SHA256} ${STRINGTEMPLATE_URL} /build/smali/stringtemplate-3.2.1.jar
ADD --checksum=sha256:${ANTLR2_SHA256} ${ANTLR2_URL} /build/smali/antlr-2.7.7.jar
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
 && chmod 0444 /build/smali/*.jar

# --- the server ---
FROM ${DEBIAN_IMAGE}
# baksmali's and smali's class paths: the tool's jar, then its POM's runtime closure in Maven's order - the same as
# BAKSMALI_CLASSPATH and SMALI_CLASSPATH of src/server.py (their manifests name no Main-Class)
ARG BAKSMALI_CLASSPATH=/opt/smali/smali-baksmali-3.0.10.jar:/opt/smali/smali-dexlib2-3.0.10.jar:/opt/smali/smali-util-3.0.10.jar:/opt/smali/guava-31.1-android.jar:/opt/smali/jcommander-1.85.jar:/opt/smali/jsr305-3.0.2.jar:/opt/smali/failureaccess-1.0.1.jar:/opt/smali/listenablefuture-9999.0-empty-to-avoid-conflict-with-guava.jar:/opt/smali/checker-qual-3.12.0.jar:/opt/smali/error_prone_annotations-2.11.0.jar:/opt/smali/j2objc-annotations-1.3.jar
ARG SMALI_CLASSPATH=/opt/smali/smali-3.0.10.jar:/opt/smali/smali-dexlib2-3.0.10.jar:/opt/smali/antlr-3.5.2.jar:/opt/smali/smali-util-3.0.10.jar:/opt/smali/antlr-runtime-3.5.2.jar:/opt/smali/jcommander-1.85.jar:/opt/smali/stringtemplate-3.2.1.jar:/opt/smali/guava-31.1-android.jar:/opt/smali/jsr305-3.0.2.jar:/opt/smali/ST4-4.0.8.jar:/opt/smali/antlr-2.7.7.jar:/opt/smali/failureaccess-1.0.1.jar:/opt/smali/listenablefuture-9999.0-empty-to-avoid-conflict-with-guava.jar:/opt/smali/checker-qual-3.12.0.jar:/opt/smali/error_prone_annotations-2.11.0.jar:/opt/smali/j2objc-annotations-1.3.jar
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
 && for jar in $(echo "${BAKSMALI_CLASSPATH}:${SMALI_CLASSPATH}" | tr ':' ' '); do test -r "$jar" || exit 1; done \
 && "$java" -XX:-UsePerfData -cp "${BAKSMALI_CLASSPATH}" com.android.tools.smali.baksmali.Main --version 2>&1 \
      | grep -q "baksmali 3.0.10" \
 && "$java" -XX:-UsePerfData -cp "${SMALI_CLASSPATH}" com.android.tools.smali.smali.Main --version 2>&1 \
      | grep -q "smali 3.0.10" \
 && "$java" -XX:-UsePerfData -jar /opt/apktool/apktool_3.0.3.jar --version 2>&1 | grep -q "3.0.3" \
 && "$java" -XX:-UsePerfData -cp /usr/share/java/apksigner-35.0.2.jar:/usr/share/java/apksig-0.9.jar \
      com.android.apksigner.ApkSignerTool --version 2>&1 | grep -q "0.9" \
 && /opt/apktool/aapt2 version 2>&1 | grep -q "Android Asset Packaging Tool" \
 && useradd --uid 10001 --user-group --no-create-home --home-dir /tmp --shell /usr/sbin/nologin mcp \
 && mkdir -p /work /out
ENV HOME=/tmp
# The usual mount targets exist in every image (a read-only rootfs under Bubblewrap cannot create them).
RUN mkdir -p -m 0755 /work /work_ro /work_rw /app /srv
USER 10001:10001
WORKDIR /tmp
ENTRYPOINT ["/opt/venv/bin/python", "-I", "-u", "/opt/mcp/server.py"]
