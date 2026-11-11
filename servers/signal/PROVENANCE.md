# signal - provenance and audit

| | |
|---|---|
| Upstream | googlarz/signal-mcp **1.43.3** (MIT, `LICENSES/signal-mcp-MIT.txt`), tag `v1.43.3`, commit `d3b1945c972340b72f8086da33f96f71b82f792c` (2026-10-21, GitHub release and PyPI `signal-mcp 1.43.3` of the same day; the PyPI wheel, SHA-256 `0bb472051115788374fb106b90c99339065dc3addf423c688cda0c665dbf9f61`, has every module of the tag byte for byte) |
| In the image from it | only the six reviewed modules of `src/signal_mcp/` (client, history, models, formatting, config, `__init__`), fetched at that commit and checked file by file against `signal-mcp-files.sha256` (3,439 lines). Its MCP server, CLI, Signal Desktop import, webhook and annotations are not in the image |
| MCP server | this repository, `src/server.py` (MIT, `LICENSES/sandbox-ai-mcp-MIT.txt`): the tools, argument checks, the write opt-in and allowed recipients, signal-cli's daemon, size bounds; `--link` |
| signal-cli | AsamK/signal-cli **0.14.9** (GPL-3.0, `LICENSES/signal-cli-GPL-3.0.txt`), its JVM release `signal-cli-0.14.9.tar.gz`, SHA-256 `c32b87f587198cbd277c9d71228716ee6047ee2b63e8e88728e8280d9407d65a` (2026-10-07; the digest GitHub publishes; the release's OpenPGP signature `signal-cli-0.14.9.tar.gz.asc` verified good, RSA key `FA10826A74907F9EC6BBB7FC2BA2CD21B5B09570` of AsamK, the key on his GitHub account, made 2016); tag `v0.14.9` = commit `3997429779095ff3a2d64c877126e84fce9852aa`, a signed tag GitHub verifies |
| In it | libsignal-client **0.103.0** (Signal, AGPL-3.0, `LICENSES/libsignal-AGPL-3.0.txt`) with its native library `libsignal_jni_amd64.so`, SHA-256 `e0f4e783c25d0eea3252d9da36dd1dc9752c075dd5c10d1d3f30d9798346050b`; sqlite-jdbc **3.53.4.0** (Apache-2.0) with `libsqlitejdbc.so` (Linux x86_64), SHA-256 `aaad97362c429a34b47488c4a5a966ab090450edde70c2186d1a02c0e2d17cd0`; 77 more jars (`LICENSES/SOURCES.txt`) |
| Java | Eclipse Temurin JRE **25.0.5+8** (GPL-2.0 with Classpath Exception; `/opt/java/legal`), `OpenJDK25U-jre_x64_linux_hotspot_25.0.5_8.tar.gz`, SHA-256 `6fac98f0c8202efc3135a9e9e42aa61963ec42d1c5cbb40caf231e7b14a24ef6` (GitHub release of 2026-10-22; the same value in its `.sha256.txt`); signal-cli 0.14 needs Java 25 |
| Python packages | `mcp==1.30.0` and its dependencies (`httpx==0.28.1` among them, which signal-mcp's client uses), the lock of duckduckgo byte for byte (`requirements.txt`, wheels only, hashes) |
| Debian packages | `python3=3.13.5-1`, `python3-venv=3.13.5-1` (purged after the venv is made); build stage `ca-certificates=20250419+deb13u1`, `git=1:2.47.3-0+deb13u1`, `python3=3.13.5-1` (not in the final image) |
| Base image | the `debian:trixie-slim` digest in `Dockerfile` |
| Platform | linux/amd64 only: signal-cli's release carries libsignal and SQLite for Linux x86_64 only |

**Upstream:** https://github.com/googlarz/signal-mcp - "Signal for AI assistants: an MCP server + CLI
... 80+ tools on top of signal-cli". Created 2026-05-03, 11 stars, 9 forks, 0 open issues, not
archived, pushed 2026-11-09; 63 releases from 2026-05-03 to v1.43.4 (2026-11-09), often several a
day. Maintainer Dawid Piaskowski (GitHub `googlarz`, account of 2016): 179 of 187 commits; 184
commits up to v1.43.3; the release commit is not signed; the commits name an AI model as co-author.
Python only (no binaries, no minified code in the repository). It drives signal-cli, which it does
not ship: its `Dockerfile` downloads signal-cli's GraalVM native build by version without a
checksum; its tests mock signal-cli's daemon.

**Pinning rule:** 1.43.3 (2026-10-21, 21 days old on 2026-11-11) is the newest release published on
or before 2026-10-28; 1.43.4 (2026-11-09) is too new - it only makes `edit_message` (a tool not
offered here) use `send` with `editTimestamp`, since signal-cli has no `editMessage` method, and
adds a `SECURITY.md`. signal-cli 0.14.9 (2026-10-07) is the newest old enough (0.14.10 of
2026-11-07 is too new); Temurin 25.0.5+8 (2026-10-22, Java's October 2026 update) likewise. The
Python lock is duckduckgo's (cut-off 2026-10-23, `docs/CANDIDATES.md`).

## Why signal-cli's JVM release, and why it is trusted rather than reviewed

Signal has no bot API: an MCP server reaches an account through a client of Signal's protocol.
signal-mcp drives **signal-cli** (since 2015, 5,000 stars, the client signal-cli-rest-api and most
Signal integrations use), whose JSON-RPC daemon it talks to; libsignal is Signal's own protocol
library. Reviewing signal-cli (Java), its fork of libsignal-service-java and libsignal (Rust) line
by line is beyond this audit; they are taken, like Debian's packages, from their publishers and
checked: signal-cli's release by the SHA-256 GitHub publishes and its maintainer's OpenPGP signature
(checked here), the JRE by the SHA-256 Adoptium publishes. The JVM release is used, not the GraalVM
native one: it is the same code as jars (the native binary is one opaque 117 MB executable), runs on
a separately pinned JRE, and its two native libraries can be checked by SHA-256 and kept out of
`/tmp`. What was read of signal-cli and its libraries, for how this image uses them: the start
script `bin/signal-cli` (whole; the image does not use it, the server starts java with the same
class path and option), the daemon's and the global options (`DaemonCommand`, `App`), the `receive`
JSON-RPC command (`ReceiveCommand`: only in `--receive-mode manual`, a negative timeout waits for
ever - the server allows 1-60 s), the provisioning (`ProvisioningManagerImpl`: the temporary key is
made with libsignal before the link socket opens), the service hosts (`LiveConfig`), libsignal's
native loader (`Native.kt`: a library inside the jar is copied to a temporary directory and loaded
from there; without it, `System.loadLibrary("signal_jni")`) and sqlite-jdbc's (`SQLiteJDBCLoader`:
`org.sqlite.lib.path` first, else unpacked into `java.io.tmpdir`).

`/tmp` in the container is `noexec`, so neither library could load as shipped. The build
(`prepare.py`, first stage only) takes both libraries out of their jars unchanged, checks them by
SHA-256, puts them into `/opt/signal-cli/native` and removes every native library (also those for
other systems) from the two jars; the JVM gets `-Djava.library.path` and `-Dorg.sqlite.lib.path`.
Nothing is unpacked or written into `/tmp` at run time (`-XX:-UsePerfData`: no perf data file
either). CI checks inside the image that signal-cli runs (`--version`) and that libsignal loads
(`link` without network makes its key with it, then fails to connect) under the hardened flags.

## What is reviewed

**Read line by line, shipped** (signal-mcp 1.43.3, `signal-mcp-files.sha256`):
`client.py` 2,049, `store.py` 868, `config.py` 218, `models.py` 211, `formatting.py` 85,
`__init__.py` 8 - 3,439 lines; and this repository's `src/server.py` and `prepare.py`.

**Read, not shipped:** `server.py` 2,540 (the handlers of all 81 tools and the read-only list in
full, the tool descriptions by their names and parameters, scanned for instructions to the model: none), `webhook.py` 86, `tool_annotations.py`
64; `pyproject.toml` (hatchling, no build hooks; the image does not install the package),
`Dockerfile`, `docker-compose.yml`, `smithery.yaml`, `glama.json`, `.oss-scanner/` (threat model),
both GitHub workflows. **Scanned only, not shipped:** `cli.py` 1,284 (the CLI, the background
service installer for launchd/systemd, the watch loop) and `desktop.py` 757 (decrypts Signal
Desktop's database with a key from the OS keychain): for `subprocess`/`exec`/`eval`/`pickle`/
`base64`/`ctypes`/sockets, URLs, bidi and zero-width characters, over-long lines. **Not reviewed:**
the tests (`tests/`, 11,829 lines; not shipped), signal-cli, libsignal and the JRE beyond the parts
named above.

Whole package (all 11 modules, 8,170 lines): no hidden endpoint (the only URLs are signal-cli's
download page, `signal.me`/`signal.group`/`signal.art` link prefixes in validation and help texts,
`signalcaptchas.org` in help texts, and `localhost`), no telemetry, no update check, no code
download, no `eval`/`exec`/`pickle`/`marshal`, no obfuscation, no bidi or zero-width characters;
`subprocess` always with argument lists, never a shell; `base64` only to decode attachment data
signal-cli returns; `ctypes` only in `desktop.py` for Windows' DPAPI. SQL is parameterised
throughout (the f-strings only add placeholders and fixed clauses); the full-text query is quoted
token by token.

## Findings in upstream (none is a backdoor)

Each is either not in the image or handled by `src/server.py`:

1. **Linking a device on request.** `add_device` links any `sgnl://linkdevice` URI to the account:
   a message that talks the agent into calling it hands the account (every later message, the
   contacts) to whoever made the URI. Also without confirmation: `start_change_number`/
   `finish_change_number`, `set_pin`/`remove_pin`, `update_account` (username, discoverability),
   `update_profile`, `remove_contact`, `block_contact`, `leave_group`, `delete_message`. Upstream
   only has an opt-in read-only mode (`SIGNAL_MCP_READONLY`), off by default. **Not offered here:**
   the server has its own eight read tools and three write tools.
2. **A webhook as an exfiltration channel.** `set_webhook` stores any URL; the background watcher
   (`cli.py`) then POSTs every incoming message there (`webhook.py`). **Not in the image.**
3. **Note to Self sends any file.** `send_note_to_self` passes its `attachments` without the
   `SIGNAL_MCP_SEND_ROOTS` check the other send tools have (`client.py` line 666): any readable file
   (signal-cli's key files included) goes to the account's own devices. **No tool here takes a path;
   the send roots name a folder that does not exist.**
4. **Upstream's read-only list is not read-only:** it includes `receive_direct` (stops the daemon by
   PID file and `lsof`, runs `signal-cli receive`) and `get_attachment` (writes files).
5. **Killing by PID file and port.** `stop_daemon` sends SIGTERM to the PID in
   `~/.local/share/signal-mcp/daemon.pid` and to whatever listens on TCP 7583; `ensure_daemon` does
   the same to a stale PID. **Not called here** (the server's `Client` overrides both; it starts and
   stops its own daemon process).
6. **Messages lost to the daemon.** `ensure_daemon` starts the daemon in signal-cli's default receive
   mode, in which the `receive` method is refused ("already being received") and what arrives goes
   only to the daemon's event stream, which nothing reads without the background watcher. **Here
   the daemon runs with `--receive-mode manual`:** nothing is fetched unless a tool asks, and what is
   fetched goes into the history.
7. **A proxy could see message texts.** The daemon client is an `httpx.AsyncClient` with
   `trust_env` on: with `HTTP_PROXY`/`ALL_PROXY` set, the JSON-RPC requests to `localhost`, message
   texts included, would go to that proxy. **Here `trust_env=False`** (tested with proxy variables
   set).
8. **Unbounded and wider answers.** `export_messages` returns the whole history in one answer;
   `list_groups` includes each group's invite link; received attachments are copied into
   `~/Downloads/signal-attachments`. **Here:** no export, answers at most 128 KiB (oldest messages
   left out first, `truncated`), message bodies cut at 4,000 characters and other texts at 1,000,
   at most 100 members per group, invite links removed, attachments not downloaded at all
   (`--ignore-attachments`) and never copied (metadata only).
9. **Minor:** `receive_direct` passes `max_messages` from the tool call unchecked into signal-cli's
   argument list (`--max-messages`, `str()` of whatever came); the account number given to
   `signal-cli -u` comes from `accounts.json` and must start with `+`. Not used here.
10. **Logs:** upstream logs no message text (one warning names an attachment's id). The server here
    logs only what it starts and why something failed (exception types), never a message, a name or
    a number; an uncaught exception's traceback is replaced by its type. signal-cli runs with
    `--scrub-log`, and its log is kept in memory (last 20 lines, 300 characters each) only to name why
    it did not start.

## The server

**Tools.** Read (always): `get_status` (the account's number, write tools on/off, the allowed
recipients, the history's size; starts nothing), `receive_messages` (signal-cli `receive`, timeout
1-60 s, 1-500 messages; edits and remote deletes are applied to the history), `get_unread` (fetches
at most once in 30 s, then the unread messages of the history, marked read there only),
`list_conversations`, `get_conversation` (a contact by number or UUID, or a group by id; date filter),
`search_messages` (full text; sender, dates), `list_contacts`, `list_groups`. Write, only with
`SIGNAL_WRITE=1` (not in `tools/list` otherwise): `send_message` (to a number or username, optional
formatting and quote), `send_group_message`, `react_to_message`. `SIGNAL_ALLOWED_RECIPIENTS` limits
them to listed numbers, usernames and group ids; a malformed list refuses every write. Upstream's
limit of 20 sends a minute applies. No tool sends a read receipt, a typing indicator or a file;
nothing is scheduled; no tool changes the account, the profile, contacts or groups.

**Arguments** are checked before anything else: phone numbers E.164, UUIDs, group ids (44
characters of base64), usernames (`nick.42`), timestamps, dates (`2026-01-31[T18:30]`), limits;
message text 1-4,000 characters without control characters other than newline and tab; an emoji
without letters, digits or spaces. Every argument reaches signal-cli as a JSON value over JSON-RPC,
never on a command line; the only command lines are the daemon's (the account number from
`accounts.json`, checked as E.164) and `--link NAME` (letters, digits, space, `._-`).

**The account and secrets.** There is no secret in the environment: the account is the folder
mounted at `/data` (required, writable): signal-cli's data in `/data/.local/share/signal-cli`
(the keys of this linked device, its sessions, contacts, groups) and the history in
`/data/.local/share/signal-mcp/messages.db` (SQLite, mode 0600). No tool reads a file of it other
than through the history and signal-cli's own JSON-RPC (contacts, groups); no tool takes a path.
Whoever holds the folder holds the linked device: give the server a folder of its own (`chmod 700`),
and unlink the device on the phone to revoke it. Without a writable `/data` or without a linked
account the server starts, lists its tools and every tool (but `get_status`) refuses, naming how to
link.

**Linking** (once, by a human, with the network):
`podman run --rm -it --network=pasta --user=0:0 --cap-drop=ALL --security-opt=no-new-privileges
--read-only --tmpfs=/tmp:rw,noexec,nosuid,nodev,size=64m -v DIR:/data:rw IMAGE --link NAME`
runs `signal-cli link -n NAME` in the foreground (`exec`, no shell); it prints a `sgnl://linkdevice`
link to show as a QR code (`qrencode -t ansiutf8 'sgnl://...'`) and scan in Signal on the phone
(Settings, Linked devices). The phone shows NAME among its linked devices.

**signal-cli's daemon** is started by the server (when an account is linked, at start in the
background, else on the first tool call): `java` with the JVM options below, `--config
/data/.local/share/signal-cli --scrub-log -a NUMBER daemon --http 127.0.0.1:7583 --receive-mode
manual --no-receive-stdout --ignore-attachments --ignore-stories --ignore-avatars --ignore-stickers`.
It listens on the container's own loopback only (the container's network namespace; nothing outside
reaches it); it is stopped when the server ends (and on SIGTERM). JVM: `-XX:+UseSerialGC
-XX:ActiveProcessorCount=2 -XX:MaxRAMPercentage=40 -XX:TieredStopAtLevel=1 -XX:-UsePerfData`, the
native library paths, `--enable-native-access=ALL-UNNAMED`.
**Add it with `--memory 1g --pids 256`:** Java needs more than the default 512 MiB and 128 processes. signal-cli locks the account:
one connection at a time (a second waits, then reports that the account is in use).

**Network:** `full`. signal-cli talks to Signal's servers: `chat.signal.org`, `storage.signal.org`,
`cdn.signal.org`, `cdn2.signal.org`, `cdn3.signal.org`, `cdsi.signal.org`, `svr2.signal.org`
(`LiveConfig`), over TLS pinned to Signal's own certificates; libsignal's network stack may also use
its fallbacks (other addresses or DNS over HTTPS) to reach `chat.signal.org`, so the set of
addresses is not fixed. Signal sees the container's address and when this device fetches: put
`--vpn PROFILE` in front where that matters. Fetching messages makes signal-cli send delivery
receipts, as every Signal client does (read receipts: never). Signal unlinks a linked device that
has not connected for about a month.

**Prompt injection:** message texts, quotes, link previews, names, profile "about" texts and group
titles are written by other people and come back in answers (`note` says so). With write tools on,
an injected text could ask the agent to send messages: limit them with
`SIGNAL_ALLOWED_RECIPIENTS`. The account-changing tools that would make such a text dangerous
(finding 1) are not offered.

**Base, user, build:** the pinned `debian:trixie-slim`; Debian's Python 3.13 with the hash-locked
venv (pip removed, venv tooling purged); the first stage's `git`, `ca-certificates` and download
helper are not in the final image; the server runs as uid 10001 with `python -I`, or as the
container's root when sandbox-ai mounts `/data` (rootless: you), with no capabilities. `/data` is
an empty folder in the image; `HOME=/data`.

**Tested:** natively with Python 3.13, the locked requirements and the six modules
(`tests/test_signal.py`, against a local stand-in for signal-cli's JSON-RPC daemon): `tools/list`
read-only and with the opt-in (only `SIGNAL_WRITE=1` turns it on), 19 refused arguments, the
missing account, receiving into the history (a direct message, a group message, one sent from the
phone, a receipt, an edit), unread marked locally without a receipt, conversations, search, contacts,
groups without invite links and with 100 members, the 128 KiB bound, the allowed recipients (and a
malformed list refusing every write), a quoted reply with the stored text, the daemon's requests
with proxy variables set, no message text in the log, the daemon's command line, its start, reuse,
stop and the error naming its last log line, `--link`. CI runs `tests/test_own_servers.py`
`test_signal` inside the image (`--network=none`, read-only, noexec `/tmp`, 512 MiB): the tools,
refused calls, `signal-cli --version`, the native libraries out of their jars, and libsignal loading;
then `smoke.json` (with `/data` mounted read-only: `get_status` naming it, four refused calls) under
Podman and Bubblewrap with sandbox-ai's run lines. **Not tested:** the image was not built here (no
container engine), and nothing ran against a real account: sending, receiving and SQLite's native
library (loaded once an account exists) are first exercised when an account is linked.
