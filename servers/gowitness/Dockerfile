# Web screenshots: gowitness 3.2.2 (sensepost/gowitness, GPL-3.0) with Debian's Chromium behind an MCP server of
# sandbox-ai-mcp (src/server.py), MCP over stdio. gowitness is built from the pinned commit with only what the server
# runs: `scan single` with the chromedp driver and the JSON-lines writer (its report server and web UI, database, the
# go-rod driver with its browser download and prebuilt helper binaries are removed, gowitness-chromedp-only.patch).
# See PROVENANCE.md for the audit and the pins.
ARG DEBIAN_IMAGE=docker.io/library/debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad
# golang:1.26-trixie (Go 1.26.10) as docker-library/repo-info recorded it on 2026-10-28 (commit 39f1d151): build stage
# only, nothing of it is in the final image (the same image servers/engram and servers/whatsapp build with).
ARG GOLANG_IMAGE=docker.io/library/golang:1.26-trixie@sha256:a050dcceee6eb9bf110151662dfac7662f3bec40927c7dee48731e3d92083d42

FROM ${GOLANG_IMAGE} AS build
# The commit of the tag 3.2.2 (release of 2026-10-11, 32 days old on 2026-11-12).
ARG GOWITNESS_COMMIT=601c84367aaf26eae7d1b5181b70633cb662cf66
ARG GOWITNESS_VERSION=3.2.2
RUN git init --quiet /src \
 && git -C /src fetch --quiet --depth 1 https://github.com/sensepost/gowitness ${GOWITNESS_COMMIT} \
 && git -C /src checkout --quiet FETCH_HEAD \
 && test "$(git -C /src rev-parse HEAD)" = "${GOWITNESS_COMMIT}"
COPY gowitness-chromedp-only.patch /tmp/gowitness-chromedp-only.patch
WORKDIR /src
ENV GOFLAGS=-mod=readonly GOTOOLCHAIN=local CGO_ENABLED=0
# Removed: the report commands (web server, prebuilt web UI, database readers), the database writer, the go-rod
# driver (browser download, leakless helper binaries) and Chromium's restricted-ports override; the patch drops their
# two uses in cmd/scan.go and pkg/runner/drivers/chromedp.go and registers the PNG and JPEG decoders the perception
# hash needs (upstream gets them through go-rod). Every module is the one go.sum pins (proxy.golang.org, checked
# against sum.golang.org); go list proves that nothing removed is linked.
RUN rm cmd/report.go cmd/report_convert.go cmd/report_generate.go cmd/report_list.go cmd/report_merge.go \
      cmd/report_migrate.go cmd/report_server.go pkg/writers/db.go pkg/runner/drivers/go-rod.go \
      pkg/runner/drivers/restricted_ports.go \
 && git apply --check /tmp/gowitness-chromedp-only.patch \
 && git apply /tmp/gowitness-chromedp-only.patch \
 && rm -rf .git \
 && go mod download && go mod verify \
 && go list -deps . > /tmp/linked \
 && if grep -E '^(github\.com/(go-rod|ysmood|glebarez|jackc|go-sql-driver|go-chi|swaggo)/|gorm\.io/|modernc\.org/|github\.com/sensepost/gowitness/(web|pkg/database|pkg/models/oldv2)(/|$))' /tmp/linked; \
    then echo "linked although removed"; exit 1; fi \
 && grep -qx 'image/png' /tmp/linked && grep -qx 'image/jpeg' /tmp/linked \
 && go test -count=1 ./internal/islazy ./pkg/runner/drivers \
 && go build -trimpath -ldflags "-s -w -X github.com/sensepost/gowitness/internal/version.GitHash=${GOWITNESS_COMMIT}" \
      -o /out/gowitness . \
 && /out/gowitness version | grep -q "gowitness: ${GOWITNESS_VERSION}" \
 && mkdir -p /out/licenses/gowitness \
 && cp LICENSE /out/licenses/gowitness/LICENSE \
 && for module in $(go list -deps -f '{{with .Module}}{{if not .Main}}{{.Path}}@{{.Version}}={{.Dir}}{{end}}{{end}}' . \
                      | sort -u); do \
      mkdir -p "/out/licenses/${module%%=*}" \
      && find "${module#*=}" -maxdepth 1 -type f \( -name 'LICENSE*' -o -name 'COPYING*' -o -name 'NOTICE*' \) \
           -exec cp {} "/out/licenses/${module%%=*}/" \; \
      && test -n "$(ls "/out/licenses/${module%%=*}")" || { echo "${module%%=*}: no licence file"; exit 1; }; \
    done

FROM ${DEBIAN_IMAGE}
# Debian versions from the trixie / trixie-security indexes of 2026-11-12 (Chromium as servers/playwright pins it).
ARG CHROMIUM_VERSION=156.0.8078.79-1~deb13u1
LABEL org.opencontainers.image.source="https://github.com/c0decave/sandbox-ai-mcp" \
      org.opencontainers.image.title="sandbox-ai-mcp-gowitness" \
      org.opencontainers.image.description="Web screenshots with gowitness and Chromium, public addresses only, an MCP server of sandbox-ai-mcp (stdio)" \
      org.opencontainers.image.licenses="MIT AND GPL-3.0-only"
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3=3.13.5-1 python3-venv=3.13.5-1 \
      chromium=${CHROMIUM_VERSION} ca-certificates=20250419+deb13u1 fonts-liberation=1:2.1.5-3 tini=0.19.0-3+b8 \
 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /opt/mcp/requirements.txt
# pip is removed from the venv and the venv tooling is purged: nothing installs Python packages at run time
RUN python3 -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir --disable-pip-version-check --require-hashes \
      --only-binary=:all: -r /opt/mcp/requirements.txt \
 && /opt/venv/bin/python -m pip uninstall -y -q pip \
 && apt-get purge -y -q python3-venv python3.13-venv python3-pip-whl python3-setuptools-whl \
 && rm -rf /var/cache/apt /var/log/apt /var/log/dpkg.log \
 && test -x /usr/bin/chromium
COPY --from=build /out/gowitness /usr/local/bin/gowitness
COPY --from=build /out/licenses/ /usr/share/doc/sandbox-ai-mcp-gowitness/modules/
COPY src/server.py /opt/mcp/server.py
COPY LICENSES/ /usr/share/doc/sandbox-ai-mcp-gowitness/
RUN /opt/venv/bin/python -m compileall -q /opt/mcp \
 && useradd --uid 10001 --user-group --no-create-home --home-dir /tmp --shell /usr/sbin/nologin mcp \
 && /usr/local/bin/gowitness version >/dev/null
ENV HOME=/tmp
USER 10001:10001
WORKDIR /tmp
# Chromium's own sandbox needs user namespaces the container does not grant: gowitness starts it with --no-sandbox and
# the container is the sandbox (no capabilities, read-only root, no new privileges). tini -s reaps Chromium's orphans
# also where it is not PID 1 (podman's --init, Bubblewrap).
ENTRYPOINT ["/usr/bin/tini", "-s", "--", "/opt/venv/bin/python", "-I", "-u", "/opt/mcp/server.py"]
