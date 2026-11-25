# yt-dlp: an MCP server of sandbox-ai-mcp (src/server.py: metadata and subtitles through yt-dlp 2026.10.26 as a
# library, one worker process per call), MCP over stdio. Nothing is downloaded or written.
ARG DEBIAN_IMAGE=docker.io/library/debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad
FROM ${DEBIAN_IMAGE}
LABEL org.opencontainers.image.source="https://github.com/c0decave/sandbox-ai-mcp" \
      org.opencontainers.image.title="sandbox-ai-mcp-yt-dlp" \
      org.opencontainers.image.description="Metadata, subtitles and YouTube search with yt-dlp 2026.10.26 (no downloads, no plugins, no JavaScript runtime, public addresses only), an MCP server of sandbox-ai-mcp (stdio)" \
      org.opencontainers.image.licenses="MIT AND Unlicense"
# tini: the image's init (its ENTRYPOINT); ca-certificates: the system CA store yt-dlp verifies the sites with (its
# compat option no-certifi) and pip's download
RUN apt-get update \
 && apt-get install -y --no-install-recommends tini=0.19.0-3+b8 python3=3.13.5-1 python3-venv=3.13.5-1 \
      ca-certificates=20250419+deb13u1 \
 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /opt/mcp/requirements.txt
# The shared MCP SDK lock plus yt-dlp's wheel (pure Python, without extras: no dependency), by hash; pip is removed
# from the venv and the venv tooling is purged: nothing installs Python packages at run time. yt-dlp's command line
# entry point (its self-update lives there) is removed; the server imports the library in its worker only.
RUN python3 -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir --disable-pip-version-check --require-hashes \
      --only-binary=:all: -r /opt/mcp/requirements.txt \
 && /opt/venv/bin/python -m pip uninstall -y -q pip \
 && rm -f /opt/venv/bin/yt-dlp \
 && rm -rf /opt/venv/share/doc/yt_dlp /opt/venv/share/man/man1/yt-dlp.1 /opt/venv/share/bash-completion \
      /opt/venv/share/fish /opt/venv/share/zsh \
 && apt-get purge -y -q python3-venv python3.13-venv python3-pip-whl python3-setuptools-whl \
 && rm -rf /var/cache/apt /var/log/apt /var/log/dpkg.log
COPY src/server.py /opt/mcp/server.py
COPY LICENSES/ /usr/share/doc/sandbox-ai-mcp-yt-dlp/
# The worker imports yt-dlp and answers (a refused request, before any network use) before anything ships.
RUN /opt/venv/bin/python -m compileall -q /opt/mcp \
 && echo '{"op": "nothing"}' | /opt/venv/bin/python -I /opt/mcp/server.py --worker | grep -q '"ok": false' \
 && /opt/venv/bin/python -I -c 'import yt_dlp.version as v; assert v.__version__ == "2026.10.26", v.__version__' \
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
# without --init) and reaps what the server leaves (its workers); -s: also where it is not PID 1 (Podman's --init,
# Bubblewrap).
ENTRYPOINT ["/usr/bin/tini", "-s", "--", "/opt/venv/bin/python", "-I", "-u", "/opt/mcp/server.py"]
