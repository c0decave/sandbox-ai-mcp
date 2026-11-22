# frida: an MCP server of sandbox-ai-mcp (src/server.py) driving Frida 17.25.2 against the Android (or Linux) device
# the human configured - a frida-server at FRIDA_DEVICE, or the USB devices of an adb server at FRIDA_ADB_SERVER.
# MCP over stdio. Reads scripts from the folder mounted read-only at /work, writes only the folder mounted writable
# at /out and its own scratch folder below /tmp. It reaches nothing but those two configured endpoints; frida's local
# device (this container's own processes) is never offered.
ARG DEBIAN_IMAGE=docker.io/library/debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad
FROM ${DEBIAN_IMAGE}
LABEL org.opencontainers.image.source="https://github.com/c0decave/sandbox-ai-mcp" \
      org.opencontainers.image.title="sandbox-ai-mcp-frida" \
      org.opencontainers.image.description="Frida 17.25.2 against a device you configured: devices, processes and apps, scripts in a running process with the messages they post, modules and exports, spawn/resume/kill behind FRIDA_WRITE=1, and the frida-server/frida-gadget binaries for every Android ABI; an MCP server of sandbox-ai-mcp (stdio)" \
      org.opencontainers.image.licenses="MIT AND wxWindows-exception-3.1"
# ca-certificates only for pip's download while the image is built (Debian's pip uses the system's certificates).
# adb is Debian's Android platform tool: it is run only against the adb server the human configured (-H/-P).
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3=3.13.5-1 python3-venv=3.13.5-1 \
      ca-certificates=20250419+deb13u1 adb=1:34.0.5-12 \
 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /opt/mcp/requirements.txt
# pip is removed from the venv and the venv tooling is purged: nothing installs Python packages at run time
RUN python3 -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir --disable-pip-version-check --require-hashes \
      --only-binary=:all: -r /opt/mcp/requirements.txt \
 && /opt/venv/bin/python -m pip uninstall -y -q pip \
 && apt-get purge -y -q python3-venv python3.13-venv python3-pip-whl python3-setuptools-whl \
 && rm -rf /var/cache/apt /var/log/apt /var/log/dpkg.log

# --- frida-server and frida-gadget, as Frida publishes them (xz): every Android ABI, and Linux x86_64 and arm64.
# Each file is the release asset itself, pinned by the SHA-256 GitHub publishes for it, and stays packed in the image
# (197 MiB): the server unpacks one into /out (export_server) or into its scratch folder before an adb push
# (push_server), so the image carries exactly the bytes whose digest is pinned and nothing is executable here.
ARG ANDROID_ARM_GADGET_SHA256=7825e2949268f4a23d38f8aaa3690e3659fd5c730e8062d4913ea0b308b933e1
ADD --checksum=sha256:${ANDROID_ARM_GADGET_SHA256} https://github.com/frida/frida/releases/download/17.25.2/frida-gadget-17.25.2-android-arm.so.xz /opt/frida/android/arm/frida-gadget-17.25.2-android-arm.so.xz
ARG ANDROID_ARM_SERVER_SHA256=7fb906385e3dd99ff11dc3068ee2441cf58ecbb8cf13fbd457db62e0c03d3640
ADD --checksum=sha256:${ANDROID_ARM_SERVER_SHA256} https://github.com/frida/frida/releases/download/17.25.2/frida-server-17.25.2-android-arm.xz /opt/frida/android/arm/frida-server-17.25.2-android-arm.xz
ARG ANDROID_ARM64_GADGET_SHA256=8c527f7844932ef0b66d99b38cc7191380e52907ca43c82f2acb6b7801945798
ADD --checksum=sha256:${ANDROID_ARM64_GADGET_SHA256} https://github.com/frida/frida/releases/download/17.25.2/frida-gadget-17.25.2-android-arm64.so.xz /opt/frida/android/arm64/frida-gadget-17.25.2-android-arm64.so.xz
ARG ANDROID_ARM64_SERVER_SHA256=08d7b7f02256621c9089cecd6495a5eb43861bf560a7ed86ad376e75d16a1fb6
ADD --checksum=sha256:${ANDROID_ARM64_SERVER_SHA256} https://github.com/frida/frida/releases/download/17.25.2/frida-server-17.25.2-android-arm64.xz /opt/frida/android/arm64/frida-server-17.25.2-android-arm64.xz
ARG ANDROID_X86_GADGET_SHA256=bae97edf0bef867e550a1cb84775edb3461c0bf170138f587a5a668b69d5f2f6
ADD --checksum=sha256:${ANDROID_X86_GADGET_SHA256} https://github.com/frida/frida/releases/download/17.25.2/frida-gadget-17.25.2-android-x86.so.xz /opt/frida/android/x86/frida-gadget-17.25.2-android-x86.so.xz
ARG ANDROID_X86_SERVER_SHA256=9957c81b3c60fbb48774814ea17136efa47f0da0aaac518022d097db41b9e1ba
ADD --checksum=sha256:${ANDROID_X86_SERVER_SHA256} https://github.com/frida/frida/releases/download/17.25.2/frida-server-17.25.2-android-x86.xz /opt/frida/android/x86/frida-server-17.25.2-android-x86.xz
ARG ANDROID_X86_64_GADGET_SHA256=2924dd5ac38b33065223ac747712ee5c83a41d1a8a7fbbc3b292e8600e826a27
ADD --checksum=sha256:${ANDROID_X86_64_GADGET_SHA256} https://github.com/frida/frida/releases/download/17.25.2/frida-gadget-17.25.2-android-x86_64.so.xz /opt/frida/android/x86_64/frida-gadget-17.25.2-android-x86_64.so.xz
ARG ANDROID_X86_64_SERVER_SHA256=ee675076d25599dd55c3b080ccf61c02b44d00653a06db2b0e2a2149ef69dad1
ADD --checksum=sha256:${ANDROID_X86_64_SERVER_SHA256} https://github.com/frida/frida/releases/download/17.25.2/frida-server-17.25.2-android-x86_64.xz /opt/frida/android/x86_64/frida-server-17.25.2-android-x86_64.xz
ARG LINUX_ARM64_GADGET_SHA256=82e2271667f94f9da104b560b6c8d4b24763d9dc6e022548e80b30b7e35901f0
ADD --checksum=sha256:${LINUX_ARM64_GADGET_SHA256} https://github.com/frida/frida/releases/download/17.25.2/frida-gadget-17.25.2-linux-arm64.so.xz /opt/frida/linux/arm64/frida-gadget-17.25.2-linux-arm64.so.xz
ARG LINUX_ARM64_SERVER_SHA256=c0ee2aea83081fbfec4e2655d507d297d8df58df56c84dea56277d957fe64432
ADD --checksum=sha256:${LINUX_ARM64_SERVER_SHA256} https://github.com/frida/frida/releases/download/17.25.2/frida-server-17.25.2-linux-arm64.xz /opt/frida/linux/arm64/frida-server-17.25.2-linux-arm64.xz
ARG LINUX_X86_64_GADGET_SHA256=1549939529077bc99b0dbf19c7fc4a62e11b0b77499bc73b3e4a7ef83ec24ec6
ADD --checksum=sha256:${LINUX_X86_64_GADGET_SHA256} https://github.com/frida/frida/releases/download/17.25.2/frida-gadget-17.25.2-linux-x86_64.so.xz /opt/frida/linux/x86_64/frida-gadget-17.25.2-linux-x86_64.so.xz
ARG LINUX_X86_64_SERVER_SHA256=2b9356fb2aab71e87cb50b6aa4dfef06892ca5851bc7013278d88754b6642ad1
ADD --checksum=sha256:${LINUX_X86_64_SERVER_SHA256} https://github.com/frida/frida/releases/download/17.25.2/frida-server-17.25.2-linux-x86_64.xz /opt/frida/linux/x86_64/frida-server-17.25.2-linux-x86_64.xz

COPY src/server.py /opt/mcp/server.py
COPY LICENSES/ /usr/share/doc/sandbox-ai-mcp-frida/
# The paths src/server.py names must be there, the bindings must load, their version must be the binaries' version,
# and the server must start without a device before anything ships.
RUN /opt/venv/bin/python -m compileall -q /opt/mcp \
 && test -x /usr/bin/adb \
 && chmod -R a-x,a+rX /opt/frida \
 && /opt/venv/bin/python -c "import frida; assert frida.__version__ == '17.25.2', frida.__version__" \
 && for platform in android linux; do \
      for abi in $(ls /opt/frida/$platform); do \
        ls /opt/frida/$platform/$abi/frida-server-17.25.2-$platform-$abi.xz > /dev/null; \
      done; \
    done \
 && /opt/venv/bin/python -c "import lzma, glob; [lzma.open(p, 'rb').read(64) for p in glob.glob('/opt/frida/*/*/*.xz')]" \
 && useradd --uid 10001 --user-group --no-create-home --home-dir /tmp --shell /usr/sbin/nologin mcp \
 && mkdir -p /work /out
ENV HOME=/tmp
# The usual mount targets exist in every image (a read-only rootfs under Bubblewrap cannot create them).
RUN mkdir -p -m 0755 /work /work_ro /work_rw /app /srv
USER 10001:10001
# what the server's own user sees: all 12 binaries (4 Android and 2 Linux ABIs, server and gadget each); a folder
# without its x bit hid them all
RUN /opt/venv/bin/python -c "import glob; found = glob.glob('/opt/frida/*/*/*.xz'); assert len(found) == 12, found"
WORKDIR /tmp
ENTRYPOINT ["/opt/venv/bin/python", "-I", "-u", "/opt/mcp/server.py"]
