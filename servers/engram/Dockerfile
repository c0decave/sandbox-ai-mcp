# Engram (Gentleman-Programming/engram, MIT): persistent memory for coding agents in SQLite with FTS5, MCP over
# stdio. Only its MCP server: our entry point src/main.go is built inside Engram's module and links nothing of
# Engram but internal/mcp and internal/store (no CLI, HTTP API, TUI, Engram Cloud, autosync or update check).
# The memory lives in the folder mounted at /data. No network. See PROVENANCE.md for the audit.
ARG DEBIAN_IMAGE=docker.io/library/debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad
# golang:1.26-trixie (Go 1.26.10) as docker-library/repo-info recorded it on 2026-10-28 (commit 39f1d151):
# build stage only, nothing of it is in the final image (the same image servers/whatsapp builds with).
ARG GOLANG_IMAGE=docker.io/library/golang:1.26-trixie@sha256:a050dcceee6eb9bf110151662dfac7662f3bec40927c7dee48731e3d92083d42

FROM ${GOLANG_IMAGE} AS build
# Tag v3.6.0 (2026-10-24), the newest release 14 days old on 2026-11-11.
ARG ENGRAM_COMMIT=98912f811c90428e83a6aac99fa439bedb4b268f
ARG ENGRAM_VERSION=v3.6.0
RUN git init --quiet /src \
 && git -C /src fetch --quiet --depth 1 https://github.com/Gentleman-Programming/engram ${ENGRAM_COMMIT} \
 && git -C /src checkout --quiet FETCH_HEAD \
 && test "$(git -C /src rev-parse HEAD)" = "${ENGRAM_COMMIT}" \
 && rm -rf /src/.git
COPY engram-files.sha256 /tmp/engram-files.sha256
COPY src/main.go src/main_test.go /src/cmd/sandbox-ai-mcp/
WORKDIR /src
ENV GOFLAGS=-mod=readonly GOTOOLCHAIN=local CGO_ENABLED=0
# Every Go file of Engram that is linked is the reviewed one (engram-files.sha256: internal/mcp, internal/store and
# the packages they import); every module is the one go.sum pins (proxy.golang.org, checked against sum.golang.org).
# go list proves that nothing else of Engram is linked; go test runs src/main_test.go.
RUN sha256sum --check --strict --quiet /tmp/engram-files.sha256 \
 && go mod download && go mod verify \
 && go list -deps ./cmd/sandbox-ai-mcp | grep '^github.com/Gentleman-Programming/engram/v3/' | sort > /tmp/linked \
 && printf '%s\n' cmd/sandbox-ai-mcp internal/agentops internal/cloud/constants internal/command internal/diagnostic \
      internal/hostbind internal/identityfile internal/mcp internal/project internal/store internal/timeutil \
    | sed 's|^|github.com/Gentleman-Programming/engram/v3/|' | sort > /tmp/reviewed \
 && diff -u /tmp/reviewed /tmp/linked \
 && for package in $(cat /tmp/linked); do \
      dir=${package#github.com/Gentleman-Programming/engram/v3/}; \
      for file in $(go list -f '{{range .GoFiles}}{{.}} {{end}}' "$package"); do \
        test "$dir" = cmd/sandbox-ai-mcp || grep -q "  $dir/$file\$" /tmp/engram-files.sha256 \
          || { echo "$dir/$file is linked but not reviewed"; exit 1; }; \
      done; \
    done \
 && go vet ./cmd/sandbox-ai-mcp \
 && go test -count=1 ./cmd/sandbox-ai-mcp \
 && go build -trimpath -ldflags "-s -w -X main.version=${ENGRAM_VERSION}" -o /out/engram-mcp ./cmd/sandbox-ai-mcp \
 && /out/engram-mcp --version \
 && mkdir -p /out/licenses/engram \
 && cp LICENSE /out/licenses/engram/LICENSE \
 && for module in $(go list -deps -f '{{with .Module}}{{if not .Main}}{{.Path}}@{{.Version}}={{.Dir}}{{end}}{{end}}' \
                      ./cmd/sandbox-ai-mcp | sort -u); do \
      mkdir -p "/out/licenses/${module%%=*}" \
      && find "${module#*=}" -maxdepth 1 -type f \( -name 'LICENSE*' -o -name 'COPYING*' -o -name 'NOTICE*' \) \
           -exec cp {} "/out/licenses/${module%%=*}/" \; \
      && test -n "$(ls "/out/licenses/${module%%=*}")" || { echo "${module%%=*}: no licence file"; exit 1; }; \
    done

FROM ${DEBIAN_IMAGE}
LABEL org.opencontainers.image.source="https://github.com/c0decave/sandbox-ai-mcp" \
      org.opencontainers.image.title="sandbox-ai-mcp-engram" \
      org.opencontainers.image.description="Engram's persistent agent memory (SQLite, FTS5) in /data, only its MCP server, no network, an MCP server of sandbox-ai-mcp (stdio)" \
      org.opencontainers.image.licenses="MIT AND BSD-3-Clause AND Apache-2.0"
COPY --from=build /out/engram-mcp /usr/local/bin/engram-mcp
COPY --from=build /out/licenses/ /usr/share/doc/sandbox-ai-mcp-engram/modules/
COPY LICENSES/ /usr/share/doc/sandbox-ai-mcp-engram/
# /data: the memory's folder, mounted writable (engram.db with its WAL, .instance-id, two lock files). Without a mount
# it is part of the read-only root: the server starts and every call says the folder is missing.
RUN useradd --uid 10001 --user-group --no-create-home --home-dir /tmp --shell /usr/sbin/nologin mcp \
 && mkdir -m 0755 /data \
 && /usr/local/bin/engram-mcp --version
# No git in the image and PATH without a writable folder: Engram's project detection finds no git to run.
# SQLITE_TMPDIR: SQLite's temporary files in the tmpfs, never in the working directory.
ENV HOME=/tmp PATH=/usr/local/bin:/usr/bin:/bin GOMAXPROCS=2 SQLITE_TMPDIR=/tmp
USER 10001:10001
WORKDIR /tmp
ENTRYPOINT ["/usr/local/bin/engram-mcp"]
