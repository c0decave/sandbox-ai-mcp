# Gitea (gitea.com/gitea/gitea-mcp, MIT, Gitea's own MCP server): issues, pull requests, files, Actions, releases,
# wiki ... of one Gitea instance, MCP over stdio. Only its tools: our entry point src/main.go is built inside its
# module and links gitea-mcp's operation and internal packages, not its cmd package (no HTTP transport, OAuth,
# health-check file, Unix socket, mTLS or -insecure). Read-only unless GITEA_WRITE=1. See PROVENANCE.md.
ARG DEBIAN_IMAGE=docker.io/library/debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad
# golang:1.27-trixie (Go 1.27.4) as docker-library/repo-info recorded it on 2026-11-10 (commit 2d1d058f, its layers
# of 2026-11-05 and 2026-11-10): build stage only, nothing of it is in the final image. gitea-mcp v1.13.0 needs Go 1.27.
ARG GOLANG_IMAGE=docker.io/library/golang:1.27-trixie@sha256:c47c3fda018d13d43a6bf5ebac3e5bba8a23a35782aa4faf531afaf47c64c39f

FROM ${GOLANG_IMAGE} AS build
# Tag v1.13.0 (published 2026-11-06 05:39 UTC, tag 2026-11-05), the newest release 14 days old on 2026-11-25.
ARG GITEA_MCP_COMMIT=34ba56e9a95d3a59113a293f1263685c3986f37c
ARG GITEA_MCP_VERSION=v1.13.0
RUN git init --quiet /src \
 && git -C /src fetch --quiet --depth 1 https://gitea.com/gitea/gitea-mcp ${GITEA_MCP_COMMIT} \
 && git -C /src checkout --quiet FETCH_HEAD \
 && test "$(git -C /src rev-parse HEAD)" = "${GITEA_MCP_COMMIT}" \
 && rm -rf /src/.git
COPY gitea-mcp-files.sha256 /tmp/gitea-mcp-files.sha256
COPY src/main.go src/main_test.go /src/cmd/sandbox-ai-mcp/
WORKDIR /src
ENV GOFLAGS=-mod=readonly GOTOOLCHAIN=local CGO_ENABLED=0
# Every Go file of gitea-mcp that is linked is the reviewed one (gitea-mcp-files.sha256: the operation and internal
# packages, go.mod, go.sum, LICENSE), checked before anything is downloaded; every module is the one go.sum pins
# (proxy.golang.org, checked against sum.golang.org). go list proves that nothing else of gitea-mcp is linked (its
# cmd package is not); go test runs src/main_test.go against a fake Gitea. Go's telemetry: off (its default "local"
# mode never uploads; off keeps even the local counters out of the build).
RUN go telemetry off \
 && sha256sum --check --strict --quiet /tmp/gitea-mcp-files.sha256 \
 && go mod download && go mod verify \
 && go list -deps ./cmd/sandbox-ai-mcp | grep '^gitea.com/gitea/gitea-mcp/' | sort > /tmp/linked \
 && printf '%s\n' cmd/sandbox-ai-mcp internal/annotation internal/attachment internal/context internal/flag \
      internal/gitea internal/log internal/oauth internal/params internal/slim internal/to internal/tool operation \
      operation/actions operation/issue operation/label operation/milestone operation/notification \
      operation/packages operation/project operation/pull operation/repo operation/search operation/timetracking \
      operation/user operation/version operation/wiki \
    | sed 's|^|gitea.com/gitea/gitea-mcp/|' | sort > /tmp/reviewed \
 && diff -u /tmp/reviewed /tmp/linked \
 && for package in $(cat /tmp/linked); do \
      dir=${package#gitea.com/gitea/gitea-mcp/}; \
      for file in $(go list -f '{{range .GoFiles}}{{.}} {{end}}{{range .EmbedFiles}}{{.}} {{end}}' "$package"); do \
        test "$dir" = cmd/sandbox-ai-mcp || grep -q "  $dir/$file\$" /tmp/gitea-mcp-files.sha256 \
          || { echo "$dir/$file is linked but not reviewed"; exit 1; }; \
      done; \
    done \
 && go vet ./cmd/sandbox-ai-mcp \
 && go test -count=1 ./cmd/sandbox-ai-mcp \
 && go build -trimpath -ldflags "-s -w -X main.version=${GITEA_MCP_VERSION}" -o /out/gitea-mcp ./cmd/sandbox-ai-mcp \
 && /out/gitea-mcp --version \
 && mkdir -p /out/licenses/gitea-mcp \
 && cp LICENSE /out/licenses/gitea-mcp/LICENSE \
 && for module in $(go list -deps -f '{{with .Module}}{{if not .Main}}{{.Path}}@{{.Version}}={{.Dir}}{{end}}{{end}}' \
                      ./cmd/sandbox-ai-mcp | sort -u); do \
      mkdir -p "/out/licenses/${module%%=*}" \
      && find "${module#*=}" -maxdepth 1 -type f \( -name 'LICENSE*' -o -name 'COPYING*' -o -name 'NOTICE*' \) \
           -exec cp {} "/out/licenses/${module%%=*}/" \; \
      && test -n "$(ls "/out/licenses/${module%%=*}")" || { echo "${module%%=*}: no licence file"; exit 1; }; \
    done

FROM ${DEBIAN_IMAGE}
LABEL org.opencontainers.image.source="https://github.com/c0decave/sandbox-ai-mcp" \
      org.opencontainers.image.title="sandbox-ai-mcp-gitea" \
      org.opencontainers.image.description="Gitea's own MCP server (gitea-mcp) for one Gitea instance, read-only by default, an MCP server of sandbox-ai-mcp (stdio)" \
      org.opencontainers.image.licenses="MIT AND Apache-2.0 AND BSD-3-Clause"
# tini (Debian's), the init of the ENTRYPOINT; ca-certificates for an https:// Gitea
RUN apt-get update \
 && apt-get install -y --no-install-recommends tini=0.19.0-3+b8 \
      ca-certificates=20250419+deb13u1 \
 && rm -rf /var/lib/apt/lists/* /var/cache/apt /var/log/apt /var/log/dpkg.log
COPY --from=build /out/gitea-mcp /usr/local/bin/gitea-mcp
COPY --from=build /out/licenses/ /usr/share/doc/sandbox-ai-mcp-gitea/modules/
COPY LICENSES/ /usr/share/doc/sandbox-ai-mcp-gitea/
RUN useradd --uid 10001 --user-group --no-create-home --home-dir /tmp --shell /usr/sbin/nologin mcp \
 && /usr/local/bin/gitea-mcp --version
ENV HOME=/tmp PATH=/usr/local/bin:/usr/bin:/bin GOMAXPROCS=2
# /etc/hosts of its own (a COPY: a build mounts its own over the image's; Podman and Docker mount theirs at run
# time): the Bubblewrap form has the file sandbox-ai binds an allowlist server's pinned hosts onto, and resolvers
# that read it find it there.
COPY hosts /etc/hosts
# The usual mount targets exist in every image (a read-only rootfs under Bubblewrap cannot create them).
RUN mkdir -p -m 0755 /work /work_ro /work_rw /app /srv
USER 10001:10001
WORKDIR /tmp
# tini is PID 1 where nothing else is (Podman without the host's catatonit: sandbox-ai then starts the image
# without --init) and reaps what the server leaves; -s: also where it is not PID 1 (Podman's --init, Bubblewrap).
ENTRYPOINT ["/usr/bin/tini", "-s", "--", "/usr/local/bin/gitea-mcp"]
