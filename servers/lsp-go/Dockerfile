# Language server for Go: gopls behind sandbox-ai-mcp's read-only LSP bridge (src/server.py, MIT, the same file in
# every lsp-* image), MCP over stdio, with the Go toolchain gopls needs to load packages (go list). The project is the
# folder mounted read-only at /work. No network: modules are never downloaded (GOPROXY=off), the standard library and
# a vendor/ folder are what is known beside the project.
ARG DEBIAN_IMAGE=docker.io/library/debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad
# golang:1.27-trixie (Go 1.27.4) as docker-library/repo-info recorded it on 2026-11-10 (commit 2d1d058f): the build of
# gopls, and its Go toolchain (/usr/local/go) is what the final image runs gopls with.
ARG GOLANG_IMAGE=docker.io/library/golang:1.27-trixie@sha256:c47c3fda018d13d43a6bf5ebac3e5bba8a23a35782aa4faf531afaf47c64c39f

FROM ${GOLANG_IMAGE} AS build
# gopls v0.24.0 (2026-10-14, the Go team's, BSD-3-Clause; golang.org/x/tools commit 1f9922d1dcc5836d5c5bcb552c8fed230f885372):
# its module checked against the h1: hash sum.golang.org has for it, its dependencies by its go.sum.
ARG GOPLS_VERSION=v0.24.0
ARG GOPLS_SUM=h1:nPO/LffYa4sP62Ueuema5PPnZPGaZjGl+vZGvbTek4g=
ENV GOFLAGS=-mod=readonly GOTOOLCHAIN=local CGO_ENABLED=0
RUN go telemetry off \
 && go mod download -json "golang.org/x/tools/gopls@${GOPLS_VERSION}" > /tmp/gopls.json \
 && grep -q "\"Sum\": \"${GOPLS_SUM}\"" /tmp/gopls.json \
 && GOBIN=/out go install -trimpath -ldflags "-s -w" "golang.org/x/tools/gopls@${GOPLS_VERSION}" \
 && /out/gopls version \
 && mkdir -p /out/config \
 && XDG_CONFIG_HOME=/out/config go telemetry off \
 && cat /out/config/go/telemetry/mode

FROM ${DEBIAN_IMAGE}
LABEL org.opencontainers.image.source="https://github.com/c0decave/sandbox-ai-mcp" \
      org.opencontainers.image.title="sandbox-ai-mcp-lsp-go" \
      org.opencontainers.image.description="Go code navigation with gopls (definition, references, hover, diagnostics, symbols) over a read-only project, an MCP server of sandbox-ai-mcp (stdio)" \
      org.opencontainers.image.licenses="MIT AND BSD-3-Clause"
# tini: the image's init (its ENTRYPOINT); python3: the bridge
RUN apt-get update \
 && apt-get install -y --no-install-recommends tini=0.19.0-3+b8 python3=3.13.5-1 python3-venv=3.13.5-1 \
 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /opt/mcp/requirements.txt
# The MCP SDK lock of servers/osv, by hash, wheels only; pip is removed from the venv and the venv tooling is purged:
# nothing installs Python packages at run time
RUN python3 -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir --disable-pip-version-check --require-hashes \
      --only-binary=:all: -r /opt/mcp/requirements.txt \
 && /opt/venv/bin/python -m pip uninstall -y -q pip \
 && apt-get purge -y -q python3-venv python3.13-venv python3-pip-whl python3-setuptools-whl \
 && rm -rf /var/cache/apt /var/log/apt /var/log/dpkg.log
COPY --from=build /usr/local/go /usr/local/go
COPY --from=build /out/gopls /usr/local/bin/gopls
# Go's telemetry setting "off" (read-only): gopls neither counts locally nor ever asks to upload
COPY --from=build /out/config /opt/lsp/config
COPY src/server.py /opt/mcp/server.py
COPY LICENSES/ /usr/share/doc/sandbox-ai-mcp-lsp-go/
RUN /opt/venv/bin/python -m compileall -q /opt/mcp \
 && useradd --uid 10001 --user-group --no-create-home --home-dir /tmp --shell /usr/sbin/nologin mcp \
 && /usr/local/bin/gopls version
# No network: GOPROXY=off (a module not in the project's vendor/ is reported, never fetched), GOTOOLCHAIN=local (a
# newer go line in go.mod is reported, no toolchain is downloaded), no cgo (no C compiler here); caches in /tmp.
ENV HOME=/tmp PATH=/usr/local/go/bin:/usr/local/bin:/usr/bin:/bin GOPROXY=off GOTOOLCHAIN=local GOFLAGS= \
    CGO_ENABLED=0 GOCACHE=/tmp/go-build GOMODCACHE=/tmp/go-mod GOPATH=/tmp/go XDG_CONFIG_HOME=/opt/lsp/config \
    GOSUMDB=off GOMAXPROCS=2
# The usual mount targets exist in every image (a read-only rootfs under Bubblewrap cannot create them).
RUN mkdir -p -m 0755 /work /work_ro /work_rw /app /srv
USER 10001:10001
WORKDIR /tmp
# tini is PID 1 where nothing else is (Podman without the host's catatonit: sandbox-ai then starts the image
# without --init) and reaps what the server leaves; -s: also where it is not PID 1 (Podman's --init, Bubblewrap).
ENTRYPOINT ["/usr/bin/tini", "-s", "--", "/opt/venv/bin/python", "-I", "-u", "/opt/mcp/server.py", "go"]
