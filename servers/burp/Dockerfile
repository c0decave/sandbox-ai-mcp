# burp: Burp Suite as an MCP server through PortSwigger's MCP extension (PortSwigger/mcp-server, GPL-3.0), built here
# from the reviewed commit with our patch (patches/: the container settings behind -Dsandbox.ai.burp.mcp=container, a
# reproducible manifest) and without the prebuilt stdio proxy jar upstream embeds. The image holds the extension jar
# (/opt/burp-mcp/burp-mcp-all.jar: what `sandbox-ai mcp burp extension` hands you for your own Burp, host mode), a
# JRE and src/server.py, which runs YOUR Burp jar (mounted read-only at /burp; never part of this image) headless with
# the extension for each MCP connection (container mode). See PROVENANCE.md for the audit.
ARG DEBIAN_IMAGE=docker.io/library/debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad

# --- the extension, from source ---
FROM ${DEBIAN_IMAGE} AS build
# main of PortSwigger/mcp-server, 2026-11-05 ("Update BappManifest.bmf"; the extension's version 1.4.0): no tags or
# releases upstream; 20 days old on 2026-11-25.
ARG BURP_MCP_COMMIT=291034081160bc944b6df3eccd60c6fc99b477e1
# Gradle 9.2.0 (2025-10-29), the version upstream's wrapper names; the SHA-256 GitHub publishes for the asset of
# gradle/gradle-distributions. The wrapper jar of the repository is not used (deleted below).
ARG GRADLE_URL=https://github.com/gradle/gradle-distributions/releases/download/v9.2.0/gradle-9.2.0-bin.zip
ARG GRADLE_SHA256=df67a32e86e3276d011735facb1535f64d0d88df84fa87521e90becc2d735444
RUN apt-get update \
 && apt-get install -y --no-install-recommends openjdk-21-jdk-headless=21.0.13.1+2-1~deb13u1 \
      openjdk-21-jre-headless=21.0.13.1+2-1~deb13u1 git=1:2.47.3-0+deb13u1 ca-certificates=20250419+deb13u1 \
      unzip=6.0-29+deb13u1 python3=3.13.5-1 \
 && rm -rf /var/lib/apt/lists/*
ADD --checksum=sha256:${GRADLE_SHA256} ${GRADLE_URL} /build/gradle-9.2.0-bin.zip
COPY burp-mcp-files.sha256 runtime-deps.init.gradle check_dependencies.py /build/
COPY patches/ /build/patches/
# The commit, its reviewed files (burp-mcp-files.sha256: every file the build reads, and nothing else under
# src/main), then our patch. Removed before anything runs: the prebuilt proxy jar (libs/mcp-proxy-all.jar, 15 MB,
# not reviewable; the extension's "Install to Claude Desktop" and "Extract server proxy jar" buttons then say it is
# not there), the Gradle wrapper, the tests (one of them runs the proxy jar) and upstream's Codex plugin files.
RUN git init --quiet /src \
 && git -C /src fetch --quiet --depth 1 https://github.com/PortSwigger/mcp-server.git ${BURP_MCP_COMMIT} \
 && git -C /src checkout --quiet FETCH_HEAD \
 && test "$(git -C /src rev-parse HEAD)" = "${BURP_MCP_COMMIT}" \
 && cd /src \
 && sha256sum --check --strict --quiet /build/burp-mcp-files.sha256 \
 && find src/main -type f | sort > /tmp/found \
 && awk '{print $2}' /build/burp-mcp-files.sha256 | grep '^src/main/' | sort > /tmp/reviewed \
 && diff -u /tmp/reviewed /tmp/found \
 && git apply --whitespace=nowarn /build/patches/0001-sandbox-ai-mcp.patch \
 && rm -rf .git libs gradle/wrapper gradlew gradlew.bat src/test plugins .agents .github \
 && cd /build && unzip -q gradle-9.2.0-bin.zip && rm gradle-9.2.0-bin.zip
# The shadow jar only (no embedProxyJar). The JDK 21 above is the toolchain: no JDK is downloaded (foojay off).
# No daemon, no build cache, no configuration cache: one clean build.
ENV GRADLE_USER_HOME=/build/gradle-home
RUN cd /src \
 && /build/gradle-9.2.0/bin/gradle --no-daemon --no-build-cache --no-configuration-cache --console=plain \
      -Porg.gradle.java.installations.auto-download=false -Porg.gradle.java.installations.auto-detect=true \
      --init-script /build/runtime-deps.init.gradle shadowJar sandboxAiRuntimeDeps \
 && ls build/libs/*.jar | tee /tmp/jars \
 && test "$(wc -l < /tmp/jars)" = 1 \
 && cp "$(cat /tmp/jars)" /build/burp-mcp-all.jar \
 && python3 -I /build/check_dependencies.py build/runtime-deps.txt /build/runtime-dependencies.json \
 && unzip -l /build/burp-mcp-all.jar > /tmp/listing \
 && grep -q ' net/portswigger/mcp/ExtensionBase.class$' /tmp/listing \
 && ! grep -q 'mcp-proxy-all.jar' /tmp/listing \
 && sha256sum /build/burp-mcp-all.jar | tee /build/burp-mcp-all.jar.sha256

# --- the server ---
FROM ${DEBIAN_IMAGE}
LABEL org.opencontainers.image.source="https://github.com/c0decave/sandbox-ai-mcp" \
      org.opencontainers.image.title="sandbox-ai-mcp-burp" \
      org.opencontainers.image.description="Burp Suite as an MCP server: PortSwigger's MCP extension 1.4.0 built from source (for your own Burp, or run here with your Burp jar, headless), an MCP server of sandbox-ai-mcp (stdio)" \
      org.opencontainers.image.licenses="GPL-3.0-only AND MIT"
RUN apt-get update \
 && apt-get install -y --no-install-recommends tini=0.19.0-3+b8 python3=3.13.5-1 \
      openjdk-21-jre-headless=21.0.13.1+2-1~deb13u1 \
 && rm -rf /var/lib/apt/lists/* /var/cache/apt /var/log/apt /var/log/dpkg.log
COPY --from=build /build/burp-mcp-all.jar /build/burp-mcp-all.jar.sha256 /build/runtime-dependencies.json /opt/burp-mcp/
COPY --from=build /build/patches/0001-sandbox-ai-mcp.patch /opt/burp-mcp/
COPY src/server.py /opt/burp-mcp/server.py
COPY LICENSES/ /usr/share/doc/sandbox-ai-mcp-burp/
# The jar's checksum file names it where it is now; the server starts and lists the extension's tools.
RUN sed -i 's#/build/burp-mcp-all.jar#/opt/burp-mcp/burp-mcp-all.jar#' /opt/burp-mcp/burp-mcp-all.jar.sha256 \
 && sha256sum --check --strict /opt/burp-mcp/burp-mcp-all.jar.sha256 \
 && test -x /usr/lib/jvm/java-21-openjdk-amd64/bin/java \
 && python3 -I -m py_compile /opt/burp-mcp/server.py && rm -rf /opt/burp-mcp/__pycache__ \
 && printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | python3 -I /opt/burp-mcp/server.py \
      | grep -q '"send_http1_request"' \
 && useradd --uid 10001 --user-group --no-create-home --home-dir /tmp --shell /usr/sbin/nologin mcp
ENV HOME=/tmp
# /etc/hosts of its own (a COPY: a build mounts its own over the image's; Podman and Docker mount theirs at run
# time): the Bubblewrap form has the file sandbox-ai binds an allowlist server's pinned hosts onto, and resolvers
# that read it find it there.
COPY hosts /etc/hosts
# /burp (your Burp jar, read-only) and /data (Burp's user folder: licence, accepted terms, project) are mounted by
# sandbox-ai; the usual mount targets exist in every image (a read-only rootfs under Bubblewrap cannot create them).
RUN mkdir -p -m 0755 /burp /data /work /work_ro /work_rw /app /srv
USER 10001:10001
WORKDIR /tmp
# tini is PID 1 where nothing else is (Podman without the host's catatonit: sandbox-ai then starts the image
# without --init) and reaps what the server leaves (Burp's JVM and what it starts); -s: also where it is not PID 1
# (Podman's --init, Bubblewrap). The program by its absolute path: sandbox-ai's Bubblewrap form takes no PATH lookup.
ENTRYPOINT ["/usr/bin/tini", "-s", "--", "/usr/bin/python3", "-I", "-u", "/opt/burp-mcp/server.py"]
