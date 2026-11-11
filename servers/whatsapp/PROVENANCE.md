# whatsapp - provenance and audit

| | |
|---|---|
| Upstream | edouard-claude/whatsapp-mcp (MIT, `LICENSES/whatsapp-mcp-MIT.txt`), commit `f3fe07f278412139e2122369c5d63ee394264f34` (2026-10-20, "Image Docker et glama.json", after release 0.1.1 of 2026-09-30; not signed) |
| In the image | `/usr/local/bin/wa-mcp` (the Rust MCP server) and `/usr/local/bin/wa-bridge` (its Go bridge on whatsmeow), built from that commit with the five patches of `patches/`; `bridge/pb/bridge.pb.go` is generated again from the reviewed `proto/bridge.proto`, not taken from upstream |
| Go modules | the 27 of `bridge/go.mod` by their `go.sum` hashes (whatsmeow `v0.0.0-20260929112325-8b41cfe6d9c4`, libsignal 0.2.2, go-util 0.10.1, modernc sqlite 1.60.1 / libc 1.77.1, ...; list below); `go mod download && go mod verify` in the build |
| Rust crates | the 160 crates.io packages of `Cargo.lock` by their checksums (rmcp 3.5.0, rusqlite 0.40.2 with bundled SQLite, tokio 1.53.1, prost 0.14.4, ...); `cargo build --locked --offline` |
| Build images | `golang:1.26-trixie` (Go 1.26.10) `sha256:a050dcceee6eb9bf110151662dfac7662f3bec40927c7dee48731e3d92083d42` and `rust:1-slim-trixie` (Rust 1.99.1) `sha256:b8e062b1c3a80183df83d9ba187cadd2b5ab84bc78d453dbfeb2fccd5f982247`, as docker-library/repo-info recorded them on 2026-10-28 (commits `39f1d151`, `d4d021c0`); protoc 36.2 (`protocolbuffers/protobuf` release of 2026-09-17, `protoc-36.2-linux-x86_64.zip`, `sha256:121f6c7afe1d4d0e3ea6aab9432038599250134cbf4474cb1167d2c7decd4278`) with Debian's `unzip=6.0-29+deb13u1`; none of them is in the final image |
| Debian packages | `ca-certificates=20250419+deb13u1` (the bridge speaks TLS to WhatsApp) |
| Base image | the `debian:trixie-slim` digest in `Dockerfile` (`sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad`) |

**Upstream:** https://github.com/edouard-claude/whatsapp-mcp, created 2026-09-30, 3 stars, 1 fork,
1 open issue, not archived, pushed 2026-11-10. Maintainer Edouard CLAUDE (GitHub `edouard-claude`,
account of 2012, La Réunion): all 5 commits of his own up to the pin, 4 later ones by Dependabot.
Releases v0.1.0 and v0.1.1 (2026-09-30), v0.1.2 and v0.1.3 (2026-11-09); the release binaries and
`install.sh` (which fetches the latest release) are not used here - the image is built from source.
The upstream `Dockerfile` (unpinned `golang:1.26-bookworm`, `rust:1-bookworm`, an unpinned
`protobuf-compiler`) is not used either. It is two programs: `wa-mcp` (Rust, rmcp) is the MCP server
on stdio; it starts `wa-bridge` (Go) as its child and talks to it over pipes in length-prefixed
protobuf frames (`proto/bridge.proto`). The bridge links **whatsmeow** (go.mau.fi/whatsmeow by Tulir
Asokan, MPL-2.0), the unofficial client library of WhatsApp's multi-device web protocol; the account
is linked as a companion device, like WhatsApp Web. Every message is kept in an SQLite database per
account (`accounts/<alias>/store.db`, with FTS5 search), whatsmeow's keys in `session.db` next to it.

**Pinning rule:** `f3fe07f2` (2026-10-20, 22 days old on 2026-11-11) is the newest commit on or before
2026-10-28; it is 0.1.1 plus the upstream Dockerfile and `glama.json`. 0.1.2 and 0.1.3 (2026-11-09)
are too new until 2026-11-23. What they fix: **0.1.3** - the initial history of a large account could
be lost when it is paired (the bridge's own connections to `session.db` contended, `database is
locked`; a `_txlock=immediate` DSN option); **0.1.2** - messages sent into a chat with disappearing
messages were permanent (the chat's timer is now tracked and set on every outgoing message), whatsmeow
bumped to `79dc2a8c` (2026-11-07), weekly automated whatsmeow update PRs. Neither is a fix of
something this image adds or of a finding below; re-pin to 0.1.3 from 2026-11-23 (and re-review the
diff: 0.1.2 changes `store.rs`, `write.rs`, `compose.rs`, `parse.rs`, `manage.go`, the `.proto` files
and both lockfiles). The lockfiles of the pin were last changed on 2026-09-30: every Go module was
published on or before 2026-09-29 (whatsmeow `8b41cfe6`, 2026-09-29, a commit verified by GitHub;
modernc.org/sqlite 1.60.1, 2026-09-29; libc 1.77.1, 2026-09-22; go-util 0.10.1, 2026-09-16; x/crypto
0.57.0, x/net 0.59.0, x/text 0.42.0, 2026-09-08; the others older), every crate before 2026-09-30.
Go 1.26.10 is of 2026-10-20, Rust 1.99.1 of 2026-10-16, protoc 36.2 of 2026-09-17; the two build images
are the ones Docker Hub served on 2026-10-28.

**How the sources were checked:** the upstream commit was read from GitHub's archive of it. Each of
the 27 Go modules was fetched from its repository at the pinned tag or commit (GitHub; GitLab for
modernc.org) and its `h1:` hash computed (Go's dirhash over the module's files) - all 27 equal the
`go.sum` lines, so the code read is the code the build downloads. The Go part (bridge with the
patches, every module) was compiled and vetted here with Go 1.26.10 (from GitHub's actions/go-versions,
SHA-256 checked) against those trees, offline, and `bridge.pb.go` generated again with protoc 36.2 and
protoc-gen-go 1.36.12 of `go.sum` exactly as the Dockerfile does. whatsmeow's 57 generated `.pb.go`
files (105,533 lines) were generated again from its own `.proto` files with protoc-gen-go v1.36.10
and v1.36.11 (built from their tags) and protoc 36.2: all 57 are identical to upstream's apart from
import order, alignment and the protoc version comment, so no hand-written code hides in them. The
Rust crates could not be fetched here (crates.io is not reachable from where this was prepared);
their sources were read from their repositories at the release tags, not byte-compared with the
`.crate` files - `cargo --locked` checks those against `Cargo.lock` in the build.

## What was reviewed

**whatsapp-mcp, everything that is built or runs (read line by line):** Rust `crates/wa-mcp/src/`
(7,897 lines): `main.rs` 477, `bridge.rs` 433, `lock.rs` 36, `ingest.rs` 318, `store.rs` 950,
`query.rs` 1,128, `parse.rs` 606, `compose.rs` 390, `dates.rs` 102, `domain.rs` 60, `mcp/mod.rs` 295,
`mcp/tools.rs` 712, `mcp/write.rs` 669, `mcp/manage.rs` 1,045, `mcp/live.rs` 268, `mcp/resources.rs`
259, `mcp/prompts.rs` 149; `crates/wa-proto/build.rs` 22 (runs prost-build on `bridge.proto` and the
vendored `waE2E` proto, nothing else) and `src/lib.rs` 13; the three `Cargo.toml` (82), `clippy.toml`;
the Go bridge (1,685): `main.go` 164, `bridge.go` 352, `conn.go` 94, `events.go` 278, `realtime.go`
106, `send.go` 151, `media.go` 72, `directory.go` 117, `manage.go` 351; `proto/bridge.proto` 522;
`go.mod`/`go.sum`; upstream's `Dockerfile` 28, `Makefile` 22, `install.sh` 49 and workflows (not used
here). No `go generate`, no install hooks, no build script beyond `build.rs`.

**whatsmeow `8b41cfe6` (26,675 hand-written lines, 107 files): read fully, every hand-written file,**
in two passes. First the risky surfaces, whole files: the websocket and Noise handshake (`socket/`,
`handshake.go`, WhatsApp's root key checked), `client.go`, `connectionevents.go`, `keepalive.go`,
pairing (`pair.go`, `pair-code.go`, `qrchan.go`), `request.go`, `notification.go`, `message.go`,
`send.go`, `receipt.go`, `retry.go`, `prekeys.go`, `presence.go`, `tctoken.go`, `cstoken.go`,
`reportingtoken.go` (off by default), `push.go` (only on request), `call.go`, `privacysettings.go`,
`update.go`, media (`download.go`, `download-to-file.go`, `upload.go`, `mediaconn.go`,
`mediaretry.go`), app state (`appstate.go`, `appstate/` decode, keys, hash, lthash, recovery),
`util/` (cbc, gcm, hkdf, keys, log), `binary/` decoder, unpack and XML, `store/` (client payload,
store, signal, session cache) and `store/sqlstore/` (container, store, upgrades and its 16 `.sql`
files), `argo/` - 16,796 lines; `internals.go` (840: 199 one-line pass-throughs, checked by script),
`binary/token` (tables) and `binary/proto/legacy.go` (type aliases). Then the remaining 49 files
(9,879 lines): `group.go` 1,091, `user.go` 1,049, `sendfb.go` 665 (never called: Messenger only),
`msgsecret.go` 486, `newsletter.go` 455, `appstate/encode.go` 375, `pair-passkey.go` 324,
`store/noop.go` 314, `binary/encoder.go` 309, `errors.go` 268, `store/sqlstore/lidmap.go` 267,
`binary/attrs.go` 218, `internals_generate.go` 211 (a generator with `//go:build ignore`, not
built), `broadcast.go` 143, `binary/node.go` 139, `armadillomessage.go` 133, `business.go` 123,
`types/` (jid, message, group, user, presence, events, ... and `richresponse/`, which is not
linked), the `proto/*/extra.go` helpers. The bridge calls about 60 of its functions (connect, pair,
send, upload, download, mark read, presence, media retry, history request, number check, user info,
profile pictures, business profiles, blocklist, privacy, status message, groups, app state).

**The other Go modules compiled into the bridge** (25 besides whatsmeow; which packages determined by following
the imports for linux/amd64, then confirmed with `go list -deps`): `go.mau.fi/libsignal` 0.2.2 (the
Signal protocol: 26 packages, 6,294 hand-written lines, GPL-3.0) and `go.mau.fi/util` 0.10.1 (15
packages, 5,307 lines; dbutil, random, exhttp, ...) were **read fully**, as were
`github.com/beeper/argo-go` 1.1.2 (4,890) and `github.com/coder/websocket` 1.8.15 (3,288 and an
assembly file that is XOR only and not even called). Scanned for the risky surfaces (exec, sockets and
HTTP, file writes, environment, `init`, `go:linkname`/`go:embed`, unsafe beyond the usual, encoded
blobs, hard-coded hosts): google.golang.org/protobuf 1.36.12, golang.org/x/net 0.59.0 (http2, idna,
proxy), x/sys 0.48.0, x/text 0.42.0, x/crypto 0.57.0 (curve25519, hkdf, pbkdf2), x/sync, x/exp,
zerolog 1.35.1, filippo.io/edwards25519 1.2.0, google/uuid 1.6.0, gqlparser 2.5.27 (`ast` only),
go-humanize, bigfft, orderedmap, goid, go-isatty, go-colorable. **modernc.org/sqlite 1.60.1 and
modernc.org/libc 1.77.1** are SQLite and musl translated from C to Go (232,630 and 163,856 generated
lines): not read; scanned, their string tables decoded, and a call graph over everything compiled in
(about 9,200 functions) built to see what SQLite can reach: only file, memory, time and signal system
calls - libc's `system()` (the only `os/exec` in the whole bridge), `popen`, the `exec` family, `fork`,
sockets and name lookups are unreachable (and dropped by the linker); `dlopen` returns 0.
`ncruces/go-strftime` is in `go.mod` but not compiled in.

**Rust crates:** which of the 160 are compiled for x86_64-unknown-linux-gnu was worked out from the
manifests and features at each locked version: 80 are linked into `wa-mcp`, about 45 run only at build
time (build scripts, proc-macros, prost-build and its helpers, cc), the rest are never compiled (Windows,
wasm, other targets; `defmt`, `sqlite-wasm-rs`, `rsqlite-vfs`, `jiff-tzdb` - optional or for other
targets). Every version's tag or release commit predates the lock (2026-09-30) and maps to the crate's
usual repository; no name looks like a typosquat. **Read fully:** the 21 build scripts that run
(libsqlite3-sys 853 lines, libc 393, rustix 281, proc-macro2 267, anyhow 194, thiserror 195,
serde_core 113, syn 86, serde 69, ref-cast 50, zmij 45, quote 32, rmcp 23, prettyplease 21, getrandom
11, parking_lot_core 11, serde_derive 8, num-traits 7, ...) and the probe files they compile; how
prost-build finds and runs protoc (`PROTOC`, `protoc --include_imports -o <tmp> ...`); every place
`cc` starts a process; libsqlite3-sys' `lib.rs` and bindings (only `extern "C"` declarations);
getrandom's Linux backend; rmcp 3.5.0's module gating for the features used (server, macros,
transport-io, schemars: about 23,000 lines compile - the model, the server service and handler, the
stdio transport; no HTTP, auth, child-process, socket or worker module). **Scanned** by pattern, each
hit checked (about 2 million lines: tokio, regex, jiff, hashbrown, serde_json, rusqlite, libc, rustix,
clap, ...): processes, sockets, environment, file writes, `extern`/`asm!`/`dlopen`, `include_bytes!`
and long encoded strings, code that runs at program start (`link_section`, `.init_array`,
`global_asm`). The proc-macros read only `CARGO_PKG_*` and the variables named in their input. The
bundled SQLite is **3.53.2** (`sqlite3/sqlite3.c`, source id `2026-06-03 19:12:13 d6e03d8c...`): 129
of its 138 component files compared with sqlite/sqlite at tag `version-3.53.2` after undoing the
amalgamation's standard edits - identical; the generated parts (parser, opcodes, keyword hash, about
58,000 of 269,000 lines) were not compared. Notes: rmcp's `build.rs` runs `git config
core.hooksPath .githooks` in the directory two levels above the crate if it has `.githooks` and `.git`
(a developer convenience of 2026-01; with crates from the registry it is a no-op); libc's `build.rs`
runs `emcc -dumpversion` if one is on the PATH (none in the build image); the build honours
`LIBSQLITE3_SYS_USE_PKG_CONFIG`, `LIBSQLITE3_FLAGS`, `CC`/`CFLAGS`, `PROTOC` (set here), none of which
the Dockerfile sets otherwise. SQLite is compiled with `SQLITE_ENABLE_LOAD_EXTENSION`, but rusqlite's
`load_extension` feature is off and wa-mcp forbids `unsafe`, so nothing can load an extension. At run
time the crates read `RUST_LOG`, `NO_COLOR`/`CLICOLOR`, `TOKIO_WORKER_THREADS`, `TZ`/`TZDIR` and
`/etc/localtime` (jiff has no bundled time-zone data on Linux and the image has no tzdata: dates are
shown and `today`/`yesterday` taken in UTC), `SQLITE_TMPDIR`/`TMPDIR`, and the three variables wa-mcp
declares (`WA_DATA_DIR`, `WA_BRIDGE`, `WA_READ_ONLY`).

**Not reviewed:** the Go standard library and Rust's `std`; the machine-translated bodies of
modernc sqlite/libc and SQLite's C amalgamation in libsqlite3-sys (only how they are reached and what
they may call); the bodies of the large Go packages that were scanned (x/net/http2, protobuf's
`internal/impl`, x/sys's generated syscall stubs) and of the Rust crates outside their risky
surfaces; the build images' toolchains (Go, Rust, gcc), taken as the Docker official images ship them.

## Findings

No backdoor, no exfiltration, no telemetry or analytics, no update check, no code download and no
hidden endpoint were found in whatsapp-mcp, whatsmeow or the dependencies. whatsapp-mcp itself opens
no connection (no HTTP or socket crate in `Cargo.lock`; Rust starts only the bridge, Go reaches
WhatsApp only through whatsmeow), uses no `unsafe` (`forbid`), binds every SQL value as a parameter
(FTS5 queries are split into quoted terms) and validates account aliases (`[a-z0-9][a-z0-9_-]{0,31}`,
in Rust and in Go) before they become a folder name. Its server instructions and prompts tell the
model that message contents are data, never instructions, and to show anything before it is sent.

What was found, and what this image does about it (the patches are below):

1. **Any local file could be sent to anyone** (security bug; write tools only). `send_media` and
   `update_group`'s `photo_path` took any absolute path, and the bridge read and uploaded it
   (`send.go:65-76`, `manage.go:103`): a prompt-injected agent with write tools could send
   `/data/accounts/*/session.db` - the account's keys - or `/proc/self/environ` to any number.
   **Patch 0002:** the bridge sends only regular files whose real path (symlinks resolved) lies under
   `WA_SEND_DIR` (`/send` in the image, a folder you mount read-only) and not under the data folder;
   without it no file can be sent.
2. **libsignal printed to the frame channel** (security bug, remote denial of service). libsignal's
   default logger writes Info/Warning/Error with `fmt.Println` to stdout, and nothing set another
   logger; stdout is the bridge's protobuf channel to wa-mcp. Undecryptable or malformed messages,
   which anyone can send, make libsignal log, which breaks the channel and stops the server.
   **Patch 0002:** `logger.Setup` with a logger on the bridge's stderr (debug lines, which would name
   keys, dropped).
3. **Read-only only on request.** Upstream exposes all 39 tools unless `--read-only`/`WA_READ_ONLY`
   is given; `session_pair` gives the agent a pairing code for any number it chooses and serves that
   account, `session_logout` unlinks the device. **Patch 0001:** read-only unless `WHATSAPP_WRITE` is
   exactly `1`; `session_pair` and `session_logout` are never offered (link the device yourself, below).
   Upstream's read-only mode is sound: the write and management routers are not registered at all,
   so their tools are neither listed nor callable (rmcp answers `tool not found`).
4. **Edits and deletions were applied without a sender check** (integrity). A protocol message only
   names the target id, and the store applied any edit or "delete for everyone" to the message of
   that id in the chat, and a new message with an id already stored replaced sender and text: a group
   member could rewrite what another member - or you - said, as the agent reads it. **Patch 0003:**
   an edit applies only to a message of the same sender; a deletion only to a message of the same
   sender or by a group admin (as WhatsApp allows); a message with an id stored for another sender does
   not overwrite it.
5. **A panic from a tool argument.** `dates.rs` turned a duration like `99999999d` into a jiff span,
   which panics out of range (rmcp runs each call in its own task, so the call fails, not the server).
   **Patch 0004:** durations up to a million units.
6. **The account's folder followed the umask** (files 0644, folders 0755): `session.db` (the keys)
   and `store.db` (every message) readable by other users of the host where the folder allowed it.
   **Patch 0005:** `accounts/` and `accounts/<alias>/` are set to 0700 at every start.
7. **A Status to every contact.** whatsmeow sends a message to `status@broadcast` as a WhatsApp
   Status, encrypted to every contact of the address book; the bridge passed any recipient through.
   **Patch 0002:** no sending to a status or a broadcast list (`@broadcast`).
8. **Downloads unbounded.** whatsmeow reads a media file whole into memory (`io.ReadAll`, no limit),
   WhatsApp documents go up to 2 GB. **Patch 0002:** nothing larger than `WHATSAPP_MEDIA_MB` (1-2000
   MiB, default 64) is fetched as the message declares it, nor written as it arrives. A sender who
   declares a small size for a large file still makes the bridge read it before it is refused: the
   container's memory limit ends that container, nothing else.

Noted, not changed (residual risks):

- **What WhatsApp sees and what goes out unasked.** whatsmeow sends what the protocol needs: acks and
  delivery receipts for every message (never read receipts: only `mark_read`, a write tool, sends
  those), retry receipts, prekey uploads, keepalives, app-state syncs, a "please resend" to your own
  phone when a message does not decrypt, privacy tokens on outgoing messages, and once after pairing a
  `unified_session` stanza (a time-derived number). On every connect the server fetches the contact
  list and the joined groups. In read-only mode two tools still talk to WhatsApp, to your own phone
  only: `request_history` (asks the phone for older messages) and `get_media` (downloads from
  WhatsApp's media hosts and, for expired media, asks the phone to upload it again). The device
  reports its OS as `whatsmeow` (and pairs by code as "Chrome (macOS)"), which WhatsApp can tell from
  its own clients: an unofficial client can get a number banned, above all for automated sending.
- **Trust in WhatsApp's servers.** whatsmeow accepts a changed identity key of a contact silently
  (`AutoTrustIdentity`) and does not verify signed device lists, so a malicious or compromised
  WhatsApp server could add a device that receives what you send; some malformed server stanzas
  panic and end the process. That is the trust a linked device has to place in WhatsApp.
- **Data at rest in `/data`.** `session.db` holds every private key in plain SQLite and, until the
  server has stored a message (the bridge's acknowledged delivery), its decrypted text
  (`event_buffer`, up to 14 days); `store.db` holds every message, contact and group. Whoever has
  the folder is the account: keep it private (patch 0005 makes `accounts/` owner-only).
- **Logs (stderr).** wa-mcp logs counts, connection states and, outside `RUST_LOG`, the account's own
  number when it connects; whatsmeow at info logs JIDs (phone numbers) and message ids, never message
  text or keys (`debug` would log every stanza, including the pairing QR's secret: not set here).
- **One connection per account.** The server takes an exclusive lock on every account at start;
  sandbox-ai starts a container per agent connection, so a second connection to the same `/data`
  exits ("déjà utilisé") until the first ends.
- **Limits.** Sending is rate-limited to 20 messages a minute per account (per container, in memory);
  `check_whatsapp` (number lookups, 50 at a time), `mark_read`, presence and the group and settings
  tools are not. Texts sent have no length limit. Media resources read a cached file whole (bounded
  by the download cap).
- **What whatsmeow trusts the server for, besides devices:** a business's verified name is not
  checked against its certificate's signature; an error with code 0 carries WhatsApp's raw answer
  into the tool's error text; JIDs are parsed leniently (a second `@` and out-of-range device numbers
  are cut, never injected: the wire format is length-prefixed). `msgsecret.go` would panic on a poll
  vote or reaction with a short IV, but only `Decrypt*` functions the bridge never calls reach it
  (the bot-message path is under `recover`). A server `passkey_prologue_request` can replace the
  pairing secret while a pairing code is shown (it then fails; nothing after pairing).
- **Smaller upstream issues:** a cached media file name strips leading dots, so a sender-chosen id
  `.X` could collide with `X` in the same chat; `get_media` is annotated read-only although it writes
  into `/data`; bridge requests have no timeout; one failed account start or store error ends `serve`.
  whatsmeow's `DeleteIdentity` uses a `LIKE` whose `_` can match another LID; argo-go's decoder has
  unchecked allocations but is unreachable (`newsletter.go` returns "argo decoding is currently broken"
  before it); libsignal changes a session's chain state before the MAC check (a late or forged message
  can spoil a session, which whatsmeow's retry receipts re-key).

## The patches (`patches/`, applied with `git apply` in order)

| Patch | SHA-256 | What |
|---|---|---|
| `0001-read-only-unless-whatsapp-write.patch` | `ef1e60965e58ab882ca6f41219106534dc9b1ce9cab2d632c15410c2332aa6d9` | `main.rs`: read-only unless `WHATSAPP_WRITE=1`; `mcp/mod.rs`: `remove_route("session_pair")`, `remove_route("session_logout")` |
| `0002-bridge-stderr-logs-send-folder-media-limit.patch` | `177a819253f4d94b9feaf508e4fb0c8b3463ef09843936aa2a1c9742c37699ee` | `main.go`: libsignal's logger on stderr; `media.go`, `send.go`, `manage.go`: files to send only from `WA_SEND_DIR`, never from the data folder; no sending to a status or broadcast list; downloads capped by `WHATSAPP_MEDIA_MB` |
| `0003-store-sender-checks.patch` | `e18728e12e62456ce8f5c0a16fef3d15e31fc4bbd117736ed7220382b4751e7e` | `store.rs`: sender checks on edits, deletions and re-stored ids |
| `0004-durations-in-range.patch` | `1d3c3e7df280ec6a5d71d12fcfe5c964c86ddda57d9e9b5a17154e99e7de9a1a` | `dates.rs`: no duration jiff cannot hold |
| `0005-private-account-folder.patch` | `f9098def16c84c8f59a818751d8a6b6f6eba310af42bc7cee4f3be70236babf7` | `lock.rs`: `accounts/` and `accounts/<alias>/` 0700 |

The Go patch was compiled, vetted and unit-tested here (the send folder with symlinks into the data
folder, `..`, `/proc/self/environ`, a send folder inside the data folder; the media limit's values;
the declared size; `status@broadcast` and a broadcast list refused), and the patched bridge started with a closed stdin writes nothing to stdout. The
Rust patches could not be compiled here (no Rust toolchain): they are small and use only APIs of the
pinned versions (rmcp 3.5.0's `ToolRouter::remove_route`, `std`), and the CI build compiles them.

## Tools

**Always (read-only, 12):** `list_accounts`, `session_status` (connection, the account's own number,
message counts), `list_chats`, `get_chat`, `list_messages`, `get_message_context`, `list_recent`,
`search_messages` (FTS5), `search_contacts`, `get_contact` - all from the local database -
`get_media` (downloads a message's media into `/data/accounts/<alias>/media/<chat>/<id>.<ext>`, the
names reduced to `[A-Za-z0-9._-]`; images and audio up to 8 MiB also inline) and `request_history`
(asks your phone for up to 500 older messages of a chat, waits up to 45 s). Resources
(`whatsapp://...`), resource subscriptions and the five prompts (`catch_up`, `summarize_chat`,
`draft_reply`, `daily_digest`, `extract_actions`: texts only, each says not to send) read the
database only.

**With `WHATSAPP_WRITE=1` (25 more):** `send_message`, `send_media` (from `/send` only),
`send_location`, `send_poll`, `react`, `edit_message` (own, 15 min), `delete_message` (own within
60 h; in a group what WhatsApp lets you), `mark_read`, `send_presence`, `check_whatsapp`,
`create_group`, `update_group` (photo from `/send` only), `update_group_participants`,
`group_invite_link`, `preview_group_link`, `join_group`, `list_join_requests`,
`handle_join_requests`, `leave_group`, `link_to_community`, `update_chat` (archive, pin, mute,
unread), `get_profile`, `set_about`, `blocklist`, `privacy_settings`.

**Never:** `session_pair`, `session_logout`.

Tool descriptions are in French (upstream's). A chat is a JID, an international number or a name
(accent- and case-insensitive, ambiguous names return the candidates).

## Network, session and files

**Network:** `full`. The bridge holds a websocket to `wss://web.whatsapp.com/ws/chat` (Noise protocol
inside TLS, WhatsApp's certificate chain checked against the root key in whatsmeow); media go to and
come from the hosts WhatsApp names at run time in its `media_conn` answer (`*.whatsapp.net`), so there
is no fixed host list for an allowlist. whatsmeow honours `HTTPS_PROXY` for media. WhatsApp sees the
connection's address: `--vpn PROFILE` puts sandbox-ai's VPN in front if that matters. Nothing else is
contacted: no telemetry, no update check, no third party.

**Session and secrets:** no secret variable. The linked device's keys are written as it runs (prekeys,
ratchets, app-state keys), so they live in `session.db` in the folder mounted writable at `/data`,
next to `store.db` and `media/`. Without a `/data` mount the server starts (the image has an empty
`/data` on its read-only root), has no account, and every tool but `list_accounts` says
`aucun compte appairé`.

**Files:** the server writes only under `/data` (and SQLite's temporary files in `/tmp`); with mounts,
sandbox-ai runs it as your user (`--user=0:0` in rootless podman); without, as uid 10001. It reads
files to send only from `/send`.

## Linking the device (once, by a human)

Run the image's own `wa-mcp pair` on the host against the folder you will mount, enter the 8-character
code on the phone (WhatsApp > Linked devices > Link a device > Link with phone number instead), and
stop it with Ctrl-C once the history lines stop:

```bash
mkdir -m 700 ~/whatsapp-data
podman run --rm -it --cap-drop=ALL --security-opt=no-new-privileges --read-only --tmpfs=/tmp --user=0:0 \
  --volume ~/whatsapp-data:/data:rw IMAGE@DIGEST pair me --phone 4915123456789
sandbox-ai mcp add whatsapp --network full --mount /data=~/whatsapp-data:rw
# to allow sending: --env WHATSAPP_WRITE (=1) and --mount /send=~/whatsapp-send:ro
```

Without `--phone` it prints a QR code to scan instead. The device appears on the phone as
"Chrome (macOS)"; unlink it there when the work is done, and delete the folder.

## Tested

- **Offline tests** (`tests/test_analysis_servers.py`, `WhatsApp`): the 12 read tools of `tools.json`
  and none of the 27 others, `WHATSAPP_WRITE` neither required nor set in the smoke run, the gate and
  the two removed routes in patch 0001, each patch changing only its files and named here with its
  SHA-256, the send folder, media limit and libsignal logger in patch 0002, `/data` and `/send`
  optional and no secret, the pins (commit, the three image digests, protoc's checksum) named here,
  `bridge.pb.go` generated in the build; with the checks every server has (digests, Debian versions,
  user 10001, the smoke spec's tools).
- **Built and run here:** the bridge (patched) with Go 1.26.10 against the `go.sum`-verified modules,
  `go vet`, the patch's unit tests, a start without input (no byte on stdout).
- **CI:** the image built, started with the hardened run line without network and without an
  account (`tools/list` equal to `tools.json`), a real call (`list_accounts`: `{"accounts":[]}`) and
  two refused ones (`list_chats` without an account, an account alias `../data`), Trivy, then the same
  with sandbox-ai under Podman and Bubblewrap.
- **Not tested:** a live account (CI has none), the Rust build (not run here), the pairing itself.

## Verdict

**Published** (`servers/`, pending its first CI build). Everything of whatsapp-mcp that is built or
runs, the whole hand-written part of whatsmeow, libsignal, go-util, argo-go and coder/websocket were
read line by line; the generated protobuf code was reproduced from its sources; the remaining modules
and crates were reviewed where they could reach the network, processes, files, the environment or
keys, and the two machine-translated SQLite builds by what they can reach. Nothing found sends data
anywhere but WhatsApp, and what this image adds on top of upstream closes what was found: read-only
unless `WHATSAPP_WRITE=1`, no pairing or logout by the agent, no file sent but from `/send`, no
Status or broadcast, libsignal off the frame channel, capped downloads, sender-checked edits and
deletions, an owner-only account folder. What remains is the nature of the thing: an unofficial
client that trusts WhatsApp's servers, whose keys and messages lie in the folder you mount, and whose
messages are written by other people.
