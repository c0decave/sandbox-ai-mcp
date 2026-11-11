# WhatsApp through a linked device: edouard-claude/whatsapp-mcp (MIT), its Rust MCP server wa-mcp and its Go
# bridge wa-bridge on whatsmeow, built from the reviewed commit with this repository's patches (patches/, see
# PROVENANCE.md): read-only unless WHATSAPP_WRITE=1, files to send only from /send, no pairing or logout tools.
# MCP over stdio; the account's session and message database live only in the folder mounted at /data.
ARG DEBIAN_IMAGE=docker.io/library/debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad
# golang:1.26-trixie (Go 1.26.10) and rust:1-slim-trixie (Rust 1.99.1) as docker-library/repo-info recorded them
# on 2026-10-28 (commits 39f1d151 and d4d021c0): build stages only, nothing of them is in the final image.
ARG GOLANG_IMAGE=docker.io/library/golang:1.26-trixie@sha256:a050dcceee6eb9bf110151662dfac7662f3bec40927c7dee48731e3d92083d42
ARG RUST_IMAGE=docker.io/library/rust:1-slim-trixie@sha256:b8e062b1c3a80183df83d9ba187cadd2b5ab84bc78d453dbfeb2fccd5f982247

# The source at the reviewed commit (2026-10-20), patched. bridge/pb/bridge.pb.go is not taken from upstream: it
# is generated again below from the reviewed proto/bridge.proto.
FROM ${GOLANG_IMAGE} AS source
ARG WA_MCP_COMMIT=f3fe07f278412139e2122369c5d63ee394264f34
RUN git init --quiet /src \
 && git -C /src fetch --quiet --depth 1 https://github.com/edouard-claude/whatsapp-mcp ${WA_MCP_COMMIT} \
 && git -C /src checkout --quiet FETCH_HEAD \
 && test "$(git -C /src rev-parse HEAD)" = "${WA_MCP_COMMIT}"
COPY patches/ /patches/
RUN cd /src && for patch in /patches/*.patch; do git apply --verbose "$patch" || exit 1; done \
 && rm -rf /src/.git /src/bridge/pb/bridge.pb.go

# protoc 36.2 (protocolbuffers/protobuf release of 2026-09-17), by its SHA-256 as GitHub publishes it.
FROM ${DEBIAN_IMAGE} AS protoc
ADD --checksum=sha256:121f6c7afe1d4d0e3ea6aab9432038599250134cbf4474cb1167d2c7decd4278 \
    https://github.com/protocolbuffers/protobuf/releases/download/v36.2/protoc-36.2-linux-x86_64.zip /tmp/protoc.zip
RUN apt-get update \
 && apt-get install -y --no-install-recommends unzip=6.0-29+deb13u1 \
 && unzip -q /tmp/protoc.zip -d /opt/protoc \
 && chmod 0755 /opt/protoc/bin/protoc

# wa-bridge: every module by its go.sum hash (proxy.golang.org, checked against sum.golang.org), no cgo.
FROM ${GOLANG_IMAGE} AS bridge
COPY --from=source /src /src
COPY --from=protoc /opt/protoc /opt/protoc
WORKDIR /src/bridge
ENV GOFLAGS=-mod=readonly GOTOOLCHAIN=local CGO_ENABLED=0
RUN go mod download && go mod verify \
 && go build -trimpath -o /tmp/protoc-gen-go google.golang.org/protobuf/cmd/protoc-gen-go \
 && /opt/protoc/bin/protoc -I /src/proto --plugin=protoc-gen-go=/tmp/protoc-gen-go \
      --go_out=pb --go_opt=paths=source_relative /src/proto/bridge.proto \
 && go vet ./... \
 && go build -trimpath -ldflags "-s -w -X main.version=v0.1.1-f3fe07f2" -o /out/wa-bridge .

# wa-mcp: every crate by its Cargo.lock checksum; prost-build runs the protoc above.
FROM ${RUST_IMAGE} AS server
COPY --from=source /src /src
COPY --from=protoc /opt/protoc /opt/protoc
ENV PROTOC=/opt/protoc/bin/protoc PROTOC_INCLUDE=/opt/protoc/include CARGO_TERM_COLOR=never
WORKDIR /src
RUN cargo fetch --locked \
 && cargo build --release --locked --offline --bin wa-mcp \
 && install -D -m 0755 target/release/wa-mcp /out/wa-mcp

FROM ${DEBIAN_IMAGE}
# Debian versions from the trixie / trixie-security indexes of 2026-11-05 (docs/CANDIDATES.md).
ARG CA_CERTIFICATES_VERSION=20250419+deb13u1
LABEL org.opencontainers.image.source="https://github.com/c0decave/sandbox-ai-mcp" \
      org.opencontainers.image.title="sandbox-ai-mcp-whatsapp" \
      org.opencontainers.image.description="WhatsApp through a linked device (whatsapp-mcp, whatsmeow), read-only unless enabled, an MCP server of sandbox-ai-mcp (stdio)" \
      org.opencontainers.image.licenses="MIT AND MPL-2.0 AND GPL-3.0-only"
# ca-certificates: the bridge speaks TLS to WhatsApp (web.whatsapp.com, the media hosts).
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates=${CA_CERTIFICATES_VERSION} \
 && rm -rf /var/lib/apt/lists/* /var/cache/apt /var/log/apt /var/log/dpkg.log
COPY --from=server /out/wa-mcp /usr/local/bin/wa-mcp
COPY --from=bridge /out/wa-bridge /usr/local/bin/wa-bridge
COPY LICENSES/ /usr/share/doc/sandbox-ai-mcp-whatsapp/
# /data and /send exist empty in the image: without mounts the server still starts (and has no account);
# sandbox-ai mounts the account's folder at /data (rw) and the files to send at /send (ro).
RUN useradd --uid 10001 --user-group --no-create-home --home-dir /tmp --shell /usr/sbin/nologin mcp \
 && install -d -o 10001 -g 10001 -m 0700 /data \
 && install -d -m 0755 /send
# WA_BRIDGE names the bridge: wa-mcp never looks for it anywhere else. WA_SEND_DIR: the only folder the bridge
# sends files from (patch 0002). Few threads: the run line allows 128 pids.
ENV HOME=/tmp WA_DATA_DIR=/data WA_BRIDGE=/usr/local/bin/wa-bridge WA_SEND_DIR=/send \
    GOMAXPROCS=2 TOKIO_WORKER_THREADS=2
USER 10001:10001
WORKDIR /tmp
ENTRYPOINT ["/usr/local/bin/wa-mcp"]
CMD ["serve"]
