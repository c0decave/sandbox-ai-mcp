# MCP servers for sandbox-ai: state and candidates

State: 2026-11-20 (axross added: axross-headless-mcp 0.15.180 behind our entry point, SFTP profiles only). 2026-11-19 (smali added: Android bytecode, apktool and debug signing as our own server; frida as an own server for a device the human configures). 2026-11-17 (context7 re-pinned to 4.5.0, its diff reviewed; the research preview it adds fixed off; agentql added as an own server; the other candidates reviewed against the catalog's rule: none admitted, the reasons below). 2026-11-16 (jadx and cfr added: our own servers on jadx 1.5.6 and CFR 0.152 for Android and Java reverse
engineering; zinja-coder's jadx-mcp-server looked at and left out). 2026-11-15 (filesystem 2.1.0 added, the official MCP server confined to the mounted folders). 2026-11-14
(sequential-thinking 2.0.0 added; context7 4.4.4 and chrome-devtools 1.12.0 moved from `candidates/`, the last
pending its complete review). 2026-11-13: exec and tasks added, our own servers for agents on small local models; mcp-server-git,
sequential-thinking, serena, the ast-grep MCP server and codebase-memory reviewed for them in
[LOCAL_LLM_TOOLS.md](LOCAL_LLM_TOOLS.md)). 2026-11-11: playwright moved to `servers/`; openosint, osint-mcp, signal
and whatsapp added; memory and engram added, Basic Memory looked at and left out.

**Pinning rule (supply-chain cooldown):** a candidate pins an upstream release published at
least 14 days before it is prepared or re-pinned (npm or PyPI upload time, GitHub release date,
commit date for a git pin). The same holds for what is pinned with it: locked dependencies,
release binaries and build tools fetched from upstream (pnpm, Node.js); a lockfile from the
release commit meets it by construction. Debian packages from the pinned trixie archive are
exempt (signed distribution, security fixes). When the newest release is too new, pin the
newest one that is old enough and note in `PROVENANCE.md` what the newer one fixes.

Checked on 2026-11-06 (cut-off: published on or before 2026-10-23). Too new:

| Where | Pin | Published | Old enough on |
|---|---|---|---|
| candidates/rea | `rea-agents` 6.8.0 (commit `160d821a`) | 2026-10-25 | 2026-11-08 |
| candidates/ghidra | `pyghidra-mcp` 0.3.0, and 24 of its hash-locked dependencies (pydantic 2.14.2, onnxruntime 1.31.1, opentelemetry 1.45.2, huggingface-hub 2.4.0, grpcio 1.85.1, ...) | 2026-11-02; 2026-10-24 to 2026-11-02 | 2026-11-16 at the latest (2026-11-25: superseded - servers/ghidra is our own server on Ghidra 12.2, no pyghidra-mcp; the folder is gone) |

osint-mcp was pinned on 2026-11-11 (cut-off 2026-10-28) to `osint-mcp-server` **0.3.0** (2026-10-05, its newest
release, commit `815276a9`) with `mcp` 2.3.0 (2026-10-02); its lock was made with uv's `--exclude-newer
2026-10-29T00:00:00Z`, every pin on or before 2026-10-28 (`servers/osint-mcp/PROVENANCE.md`).

playwright was re-pinned on 2026-11-11 (cut-off 2026-10-28) from 0.0.84 (2026-10-31; 0.0.85 of
2026-11-09 is newer still) to **0.0.83** (2026-09-28, commit `f183dad4`), whose lockfile pins
`playwright`/`playwright-core` 1.64.0-alpha-1790635538000 of the same day; what 0.0.84 adds is in
`servers/playwright/PROVENANCE.md`.

openosint was prepared on 2026-11-11 (cut-off 2026-10-28) with OpenOSINT **2.36.1** (2026-10-19,
commit `99849732`); 2.37.0 (2026-11-02), 2.37.1 and 2.38.0 (2026-11-05) are too new. Its
`requirements.txt` was locked with `--exclude-newer 2026-10-29T00:00:00Z` (newest files of
2026-10-28: `pydantic-settings` 2.16.2, `tzdata` 2026.6).

signal (2026-11-11, cut-off 2026-10-28): signal-mcp **1.43.3** (2026-10-21, commit `d3b1945c`; 1.43.4
of 2026-11-09 is too new and only fixes `edit_message`, not offered here), signal-cli **0.14.9**
(2026-10-07; 0.14.10 of 2026-11-07 too new), Eclipse Temurin JRE **25.0.5+8** (2026-10-22), the
Python lock of duckduckgo.

whatsapp was prepared on 2026-11-11 (cut-off 2026-10-28) at commit `f3fe07f2` of
edouard-claude/whatsapp-mcp (2026-10-20; the newest commit old enough, after release 0.1.1 of
2026-09-30); 0.1.2 and 0.1.3 (both 2026-11-09) are too new until 2026-11-23 (what they fix is in
`servers/whatsapp/PROVENANCE.md`). Its lockfiles were last changed on 2026-09-30 (whatsmeow commit
`8b41cfe6` of 2026-09-29, the newest Go module of 2026-09-29, the Cargo.lock crates older); the build
images are golang:1.26-trixie (Go 1.26.10, 2026-10-20) and rust:1-slim-trixie (Rust 1.99.1,
2026-10-16) as docker-library/repo-info recorded them on 2026-10-28, protoc 36.2 (2026-09-17).

memory and engram (2026-11-11, cut-off 2026-10-28): `@modelcontextprotocol/server-memory` **2.0.1** (npm
2026-10-28 21:07 UTC, release v2.2.0 of modelcontextprotocol/servers, commit `194cc86e`; 2.1.0 of 2026-11-04 and
2.1.1 of 2026-11-11 too new, no security fix in them) with `@modelcontextprotocol/server`/`core` 2.4.0 (2026-10-23)
and zod 4.6.7 (2026-10-12), locked with `npm install --package-lock-only --before=2026-10-29T00:00:00Z` (the same
integrities as upstream's lock), on Node.js 24.22.1 (`node:24-trixie-slim` as Docker Hub served it on 2026-10-28);
Engram **3.6.0** (2026-10-24, commit `98912f81`; 3.6.1, 3.6.2, 3.7.0 and 3.7.1 of 2026-11-03 to 2026-11-11 too new;
3.7.1 bounds FTS query sizes, which our entry point does for every argument), every Go module by the release's
`go.sum` (published before 2026-10-24 by construction), Go 1.26.10 (the golang image of servers/whatsapp).

sequential-thinking (2026-11-14, cut-off 2026-10-31): `@modelcontextprotocol/server-sequential-thinking` **2.0.0** (npm
2026-10-19, tag `v2.0.0`, commit `51b6382a`; 2.1.1 of 2026-11-04 too new until 2026-11-18, no security fix), locked with
`npm install --package-lock-only --before=2026-11-01T00:00:00Z`: the SDK 2.4.0 and zod 4.6.7 of servers/memory (same
integrities), chalk 5.6.2 (2025-09-08), yargs 17.7.3 (2026-06-19, removed from the image); Node.js 24.22.1 of servers/memory.

filesystem (2026-11-15, cut-off 2026-11-01): `@modelcontextprotocol/server-filesystem` **2.1.0** (npm 2026-10-28,
commit `194cc86e` - the commit of servers/memory's 2.0.1 -, provenance-attested; 2.2.0 of 2026-11-04 too new until
2026-11-18, 2.3.0 of 2026-11-11 until 2026-11-25: it anchors reads, re-pin then), locked with `npm install
--package-lock-only --before=2026-11-01T00:00:00Z`: the SDK 2.4.0 and zod 4.6.7 of servers/memory (same integrities),
diff 8.0.4 (2026-03-23), minimatch 10.2.6 (2026-07-27), brace-expansion 5.0.12 (2026-09-14), balanced-match 4.0.4
(2026-02-22), glob 13.0.6 with three packages of its own (removed from the image); Node.js 24.22.1 of servers/memory.

context7 (2026-11-14, cut-off 2026-10-31): `@upstash/context7-mcp` **4.4.4** (npm 2026-10-19, tag commit `c7f80ce5`;
4.5.0 of 2026-11-03, 4.5.1, 4.6.0 and 4.7.0 too new, no security fix), installed from the registry with an npm lock made
with `--before=2026-11-01T00:00:00Z` (104 packages, the newest jose 6.2.14 of 2026-10-29; 74 kept), instead of the earlier
candidate's pnpm build of 4.5.0; Node.js 24.22.1 of servers/memory. **Re-pinned on 2026-11-17 to 4.5.0** (npm
2026-11-03 06:43 UTC, tag commit `a138857c`): the same dependencies, so the lock keeps its 104 packages; the diff to
4.4.4 (one new file, nine changed) read completely and compared with its TypeScript; a fourth patch fixes the new
research preview (a feedback tool that posts to context7.com) off. 4.5.1 is old enough on 2026-11-20, 4.6.0 on
2026-11-23, 4.7.0 on 2026-11-26.

chrome-devtools (2026-11-14, cut-off 2026-10-31): `chrome-devtools-mcp` **1.12.0** (npm 2026-10-22, commit `af283441`,
provenance-attested; 1.13.0 of 2026-11-11 too new until 2026-11-25), the npm tarball alone by integrity (no runtime
dependencies: Puppeteer 25.16.0, the MCP SDK 2.3.1, zod 4.6.5, Lighthouse 13.5.0 and the DevTools frontend are bundled),
Debian's Chromium of servers/playwright, Node.js 24.22.1 of servers/memory. **Fit to sign once CI passes**: every
line of its own code in the image read (18,195), the package rebuilt from `af283441` and byte-identical, the bundled
npm packages equal to their registry releases, the Lighthouse bundle equal to a build of its `v13.5.0` tag
(servers/chrome-devtools/PROVENANCE.md, Verdict).

Old enough: agentql (`agentql-mcp` 1.0.1, 2026-02-21; built in servers/ since 2026-11-17), browserbase (3.0.0, commit of
2026-03-31; pnpm 10.12.4, 2025-06-26), codebase-memory (0.12.1, 2026-10-16), chrome-devtools
(1.12.0, 2026-10-22; built in servers/ since 2026-11-14), Ghidra 12.2 (2026-10-22), reddit (`reddit-mcp-buddy` 1.1.14, 2026-07-29;
re-pinned from 1.2.0 of 2026-11-02). The other PyPI pins of ghidra are old enough; the npm
lockfiles of the other candidates were not checked package by package.

`servers/` were re-locked the same day with uv's `--exclude-newer 2026-10-24T00:00:00Z`: starlette
1.10.0 -> 1.9.0 (2026-10-18), sse-starlette 3.5.1 -> 3.5.0 (2026-09-28) in all six, pyasn1
0.6.5 -> 0.6.4 (2026-07-09) in telegram-user (0.6.5 fixes four decoding DoS advisories that do not
reach it there; re-lock to it from 2026-11-10). Every PyPI pin of `servers/` is now old enough.

## Built here (`servers/`)

| Server | What | Network | Tested |
|---|---|---|---|
| duckduckgo | web search, no key | allowlist `html.duckduckgo.com:443` | natively (handshake, tools, refused arguments, parser); live call in CI |
| brave-search | web and news search, official API | allowlist `api.search.brave.com:443`, `BRAVE_API_KEY` | natively; live call in CI with the repository secret |
| telegram | a Telegram bot through the official Bot API (no user account) | allowlist `api.telegram.org:443`, `TELEGRAM_BOT_TOKEN`, optional `TELEGRAM_ALLOWED_CHATS` | natively, with a local stand-in for the Bot API (requests, errors, the token in no answer or log line); no live call (that would need a bot and a chat) |
| telegram-user | a Telegram user account through MTProto (Telethon 1.45.0, MIT): read public channels and groups (resolve, search, info, invite links, messages, search, comments, media metadata; downloads only into a mounted `/out`); write tools only with `TELEGRAM_USER_WRITE=1` | full (data centres by IP; `--vpn PROFILE`), `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_SESSION` (login.py), optional `TELEGRAM_USER_ALLOWED_CHATS`, `TELEGRAM_MTPROXY` | natively, with a fake Telethon client (tools read-only and opt-in, limits, refused arguments, flood waits, allowed chats, downloads, login.py, the secrets in no answer or log line); not built yet; no live call (that would need an account) |
| web-fetch | a public web page as text | full, public addresses only | natively, including the address checks |
| radare2 | static analysis of a binary: functions, imports, exports, sections, symbols, strings, disassembly, decompilation (`pdc`), xrefs; upstream r2mcp 1.9.0 with radare2 6.2.4, both built from source at their release commits, started with `-s /work -g none` | none; `/work` read-only (required) | ported from axross-mcp-hub, where it was audited and smoke-tested; here: offline tests (entry, pins, mounts, fixtures) and the smoke spec in CI |
| capa | what a binary can do: Mandiant capa 10.0.0 with capa-rules 10.0.0 and capa's FLIRT signatures in the image, mapped to ATT&CK and MBC; FuzzingLabs wrapper, patched (paths under `/work`, ranges, bounded results) | none; `/work` read-only (required) | ported from axross-mcp-hub, where it was audited and smoke-tested; here: offline tests and the smoke spec in CI |
| osint-mcp | domain and website OSINT from public sources, no key: robyroro/osint-mcp 0.3.0 (MIT; PyPI `osint-mcp-server`, the wheel identical to commit `815276a9`), 15 read-only tools (RDAP, DNS, crt.sh, Wayback, RIPEstat, Shodan InternetDB, email security, TLS, HTTP headers, batch recon, shared infrastructure, site investigation); all 2025 lines read; started through `src/server.py`, which adds web-fetch's NAT64/6to4 check to upstream's address check; cache in memory | full | natively (handshake, tools, refused calls, the address check, parsers, upstream's 99 tests); `test_osint_mcp` inside the image and the smoke spec in CI (example.com DNS and TLS, RIPEstat; four local targets refused); not built here (no container engine) |
| playwright | a headless Chromium through Microsoft's Playwright MCP 0.0.83 (commit `f183dad4`, 2026-09-28; Apache-2.0) with Debian's `chromium` 156.0.8078.108-1~deb13u1: 25 default tools (navigate, snapshot, click, type, forms, tabs, evaluate, run code, screenshots, console, network requests); `--isolated --no-sandbox --no-webmcp`, no `--caps` | full; `--memory 2g --pids 512` | offline tests (pins, flags, tools, limits, the smoke spec's limits as sandbox-ai takes them); the smoke spec in CI (a `data:` page, a `file:` URL and a file outside the roots refused); not built here (no container engine) |
| openosint | passive OSINT lookups with 26 reviewed modules of OpenOSINT 2.36.1 (MIT, commit `99849732`, each file pinned by SHA-256) behind an own server: dork URLs, RDAP, WHOIS, DNS, ipinfo.io, GitHub, psbdmp.ws, GDELT news; with keys HIBP, VirusTotal (no URL submission), AbuseIPDB, IP2Location.io, Bright Data SERP. Passive only (active mode cannot be enabled); OpenOSINT's active tools, LLM agent, graph, web UI and Shodan/Censys tools are not in the image | full (WHOIS referrals and RDAP servers come from the registries); seven optional keys | natively against the reviewed modules (tools, refused arguments, passive mode, key redaction); the smoke spec in CI (offline dork URLs, a live RDAP lookup, four refused calls); not built here (no container engine) |
| signal | a Signal account of yours as a linked device: signal-cli 0.14.9 (JVM release, GPL-3.0; by SHA-256 and its maintainer's signature) on Temurin JRE 25.0.5+8, with six reviewed modules of signal-mcp 1.43.3 (googlarz/signal-mcp, MIT: client and SQLite message history; not its MCP server, CLI, Desktop import or webhook) behind an own server: 8 read tools (fetch, unread, conversations, search, contacts, groups without invite links); `send_message`, `send_group_message`, `react_to_message` only with `SIGNAL_WRITE=1`, optional `SIGNAL_ALLOWED_RECIPIENTS`; no file, receipt or account change | full; `/data` writable (required: the account, linked once with `--link`); `--memory 1g --pids 256` | natively with a stand-in for signal-cli's JSON-RPC daemon (`tests/test_signal.py`); in the image: signal-cli runs and libsignal loads under the hardened flags; smoke spec without an account; not built here, no live account |
| whatsapp | a WhatsApp account linked as a device: edouard-claude/whatsapp-mcp at `f3fe07f2` (2026-10-20, MIT; Rust MCP server wa-mcp, Go bridge wa-bridge on whatsmeow `8b41cfe6`) with five patches of this repository (read-only unless `WHATSAPP_WRITE=1`, no pairing or logout tools, files sent only from `/send`, no Status or broadcast sending, libsignal's log off stdout, media capped, sender checks on edits and deletions, the account's folder owner-only); 12 read tools by default, 37 with `WHATSAPP_WRITE=1` | full; `/data` writable (the session and the message database), `/send` read-only optional | the bridge compiled and its patch unit-tested here with Go 1.26.10 and the go.sum-verified modules; the Rust patches not compiled here (no Rust toolchain); offline tests (pins, patches, tools, mounts); the smoke spec in CI (tools/list without an account, a real call, refused calls); no live call (that would need an account) |
| binwalk | what is inside a firmware file: signature scan, extraction, entropy, hex dump; Debian binwalk 2.4.3 with pinned extractors; FuzzingLabs wrapper, patched (paths under `/work`, no option injection, `/out` or `/tmp` for extraction) | none; `/work` read-only (required), `/out` writable optional | ported from axross-mcp-hub, where it was audited and smoke-tested; here: offline tests and the smoke spec in CI |
| memory | the official MCP Knowledge Graph memory server 2.0.1 (modelcontextprotocol/servers `src/memory`, Apache-2.0/MIT; npm release built by upstream CI from commit `194cc86e`, provenance-attested): entities, observations, relations in `/data/memory.jsonl`, 9 tools (create, add, delete, search by substring, open, read graph); server read line by line (its 1,280 TypeScript lines and the shipped JavaScript compared), the MCP SDK 2.4.0 on its whole stdio path (14,200 lines), zod and the bundled Ajv on their risky surfaces; no patch; `node --disallow-code-generation-from-strings` | none; `/data` writable (required), one folder per case | the smoke spec run locally through `scripts/smoke_test.py` against the reviewed packages on Node.js 26 (write, search, read back; four refused calls); offline tests; not built here (no container engine) |
| exec | our own server (`src/server.py`, the shared lock) for agents on small local models: `run_command` (bash with a time limit, the whole process tree stopped on it, stdin empty, no terminal, a fixed non-interactive environment, output cut to start and end), background jobs, `run_tests` (only the failures), `lint` (read-only); Debian's git, make, pytest, pyflakes, PyYAML, shellcheck and Node.js 20 for the commands | none; `/work` writable (required: the project); `--memory 2g --pids 512`, a 512m /tmp | `tests/test_exec.py` (43 offline tests: limits and kills, output bounds, input, environment, paths and links, jobs, recorded test reports, real test runs, lint, stdio); `test_exec` inside the image and the smoke spec in CI; not built here (no container engine) |
| tasks | our own server (`src/server.py`, the shared lock): a plan outside the model's context in `/work/.tasks` (goal, steps, notes, `next_step`), flock-locked atomic writes, `PLAN.md` for the human | none; `/work` writable (required: the project) | `tests/test_tasks.py` (persistence, bounds, plans changed by hand, links, six processes and four threads at once, stdio); `test_tasks` inside the image and the smoke spec in CI; not built here |
| engram | Engram 3.6.0 (Gentleman-Programming/engram, MIT, commit `98912f81`), only its MCP server: an own entry point (`src/main.go`) built inside Engram's module links internal/mcp and internal/store and what they import (31,134 lines in 61 files, every one read line by line and pinned by SHA-256; the build proves nothing else of Engram is linked); mcp-go 0.44.0 read line by line; the other Go modules (modernc sqlite/libc, x/sys, x/text, uuid, jsonschema, ...) on their risky surfaces. 23 agent tools; `directory`/`cwd` arguments removed (they scan folders and would run git); arguments bounded, panics recovered, memory in `/data` with Engram's own limits | none; `/data` writable (required), one project per folder (`ENGRAM_PROJECT`, default `brain`) | `src/main_test.go` runs in the image build; smoke spec in CI (save, search, read back; four refused calls); offline tests; not built here (no Go toolchain, no container engine) |
| sequential-thinking | the official MCP sequential-thinking server 2.0.0 (modelcontextprotocol/servers `src/sequentialthinking`, Apache-2.0/MIT; npm release built by upstream CI from commit `51b6382a`, provenance-attested): one tool, `sequentialthinking`, a chain of thoughts kept in memory per connection; server read line by line against its TypeScript, chalk 5.6.2 in full, the SDK 2.4.0 and zod 4.6.7 by servers/memory's review of the identical files; yargs (declared, never imported) removed from the image; `DISABLE_THOUGHT_LOGGING=true`, `node --disallow-code-generation-from-strings`. 2.1.1 (2026-11-04) too new until 2026-11-18 | none | the smoke spec run locally through `scripts/smoke_test.py` against the packages of the lock on Node.js 26 (a thought, a revision, a branch `__proto__`; three refused calls); offline tests; not built here (no container engine) |
| filesystem | the official MCP filesystem server 2.1.0 (modelcontextprotocol/servers `src/filesystem`, Apache-2.0/MIT; npm release built by upstream CI from commit `194cc86e`, provenance-attested): 14 tools (read, media, write, `edit_file` with a diff, mkdir, list, tree, move, search, info); our `src/entry.mjs` allows exactly the folders mounted at `/work` and `/ref1`-`/ref3` (mount points from `/proc/self/mountinfo`) and never asks for MCP Roots (in 2.1.0 a client's roots replace the allowed directories); server read line by line against its TypeScript, diff, minimatch, brace-expansion and balanced-match on the paths it uses, the SDK and zod by servers/memory's review; glob (declared, never imported) removed; reads not anchored until 2.3.0 (reach the container's own files only) | none; `/work` (required), `/ref1`-`/ref3` | the smoke spec run locally through `scripts/smoke_test.py` against the packages of the lock on Node.js 26 (20 calls: writes, edit, search, tree, move; links to `/etc`, a dangling link, `..`, an unmounted `/ref1`, `~`, `/tmp` refused), the roots refusal against a client offering `file:///`, read and write races; offline tests; not built here (no container engine) |
| context7 | Upstash's Context7 MCP 4.5.0 (upstash/context7 `packages/mcp`, MIT; commit `a138857c`; re-pinned from 4.4.4 on 2026-11-17, the diff reviewed), npm release with an npm lock: two tools, `resolve-library-id` and `query-docs`, GETs to `context7.com/api/v2`; server read line by line against its TypeScript, the SDK 2.3.1 by its diff to 2.4.0, the other loaded packages (undici, express, jose, commander, zod) on their risky surfaces; only the 74 packages that load kept (OpenTelemetry and its loader patching removed, telemetry modules removed, `OTEL_SDK_DISABLED=true`); patched: no sign-in prompt (`npx ctx7 setup`), no client name, version or session id sent, tools only, no research preview | allowlist `context7.com:443`; optional `CONTEXT7_API_KEY` | refused calls, `tools/list` and the proxy path (only `CONNECT context7.com:443`) run locally through `scripts/smoke_test.py` against the prepared packages on Node.js 26; real calls only in CI (context7.com not reachable here); offline tests; not built here |
| jadx | our own server (`src/server.py` and `src/JadxBridge.java` on jadx's library, the shared lock) with jadx 1.5.6 (skylot/jadx, Apache-2.0, tag commit `28ff15e4`; the release's `jadx-1.5.6-all.jar` by SHA-256) on Debian's OpenJDK 21: 14 read-only tools for APK, DEX, JAR, AAR, AAB, XAPK, APKS, APKM, .class and .smali files - classes, packages, outlines, the Java source of a class or one method, smali, cross references, code and name search, the decoded manifest and resources; headless, only jadx's input and Kotlin plugins loaded, nothing saved, one JVM per loaded file with an empty environment and the checked file passed as its descriptor; answers in parts of 400 lines / 24,000 characters. Our code reviewed in full; jadx read where the confinement depends on it | none; `/work` read-only (required); `--memory 2g --pids 256`, a 256m /tmp | `tests/test_jadx.py` (25 tests) here against the real jadx 1.5.6 jar and the bridge compiled with javac 21 (every tool on the self-made `demo.apk` and `demo.jar`), a 78 MB JAR of 22,805 classes; `test_jadx` inside the image and the smoke spec in CI; not built here (no container engine) |
| cfr | our own server (`src/server.py`, the shared lock) with CFR 0.152 (leibnitz27/cfr, MIT, tag commit `68477be3`; the release jar by SHA-256) on Debian's OpenJDK 21: 6 read-only tools for JAR, WAR, EAR, ZIP and .class files - class lists and outlines and string constants read by the server itself, the Java source of a class or one method by CFR (renaming and anti-obfuscation on request, no other option reachable); CFR per call with an empty environment, an empty working folder, 40 s and 16 MiB of output; answers in parts of 400 lines / 24,000 characters. Our code reviewed in full; CFR read where the confinement depends on it (a JAR's `Class-Path` is followed inside the container: documented) | none; `/work` read-only (required); `--memory 1g` | `tests/test_cfr.py` (16 tests) here against the real CFR 0.152 jar on Java 21; `test_cfr` inside the image and the smoke spec in CI; not built here |
| frida | our own server (`src/server.py`, the shared lock plus frida's own bindings) with **Frida 17.25.2** (2026-11-02, 17 days old; 17.26/17.27 deliberately too new) and, for that very version, frida-server and frida-gadget for every Android ABI plus Linux x86_64/arm64 - 12 release files, each kept as published (xz) and pinned by the SHA-256 GitHub publishes. 16 tools: devices, processes, apps, attach, run_script (inline or a .js of /work, messages collected with a time limit), modules, exports, export_server/push_server, and spawn/resume/kill behind FRIDA_WRITE=1. It reaches exactly one endpoint, the human's (FRIDA_DEVICE, or an adb server at FRIDA_ADB_SERVER); frida's local device - the server's own container - is refused by name. frida-tools is **not** shipped (its injected agents and 12 MB tracer UI cannot be reviewed completely) | full, and only to the address the human opens with `--allow-tcp`; `/work` read-only, `/out` writable; `--memory 2g --pids 512` | `tests/test_frida.py` (31 tests) here against frida's own bindings with no device anywhere; `test_frida` over stdio and the smoke spec (no device: every device call a refused call) in CI; no real device call (that needs a device) |
| axross | axross-headless-mcp **0.15.180** (the user's own project, c0decave, Apache-2.0; tag `v0.15.180`, commit `07976963`; the PyPI wheel by SHA-256, byte for byte the tag's `src/`) behind our `src/server.py`: `--mcp-root /work --mcp-tools remote`, `--mcp-write` only with AXROSS_WRITE=1, SFTP profiles only, passwords from AXROSS_PASSWORDS, key files and known_hosts from `/ssh`, tools only; the image keeps the 65 files (42,294 lines) the configuration runs, measured with an audit hook, and an import guard refuses the rest; about 11,000 lines read line by line, the rest by scan and runs (PROVENANCE.md: the user decides) | none; for a profile `--network full` (+ `--allow-tcp IP:22`); `/work` ro (rw with AXROSS_WRITE=1), `/axross` and `/ssh` ro; 1g, 256 processes, 256m /tmp | `tests/test_axross.py` (6) and `test_own_servers` `Axross` (9, a local paramiko SFTP server; in CI inside the image) |
| smali | our own server (`src/server.py`, the shared lock) with baksmali/smali **3.0.10** as Google publishes them (`com.android.tools.smali` 3.0.10 in Google's Maven repository, built from google/smali commit `7a325fc45dc0`; JesusFreke's original is archived since 2024) on a class path with exactly the runtime dependencies their POMs name (Guava, jcommander, ANTLR, ... from Maven Central), every jar by URL and SHA-256, **apktool 3.0.3** with its own aapt2 and framework taken out of its jar by SHA-256, and Debian's zipalign and apksigner 35.0.2 on OpenJDK 21: 11 tools - DEX files and classes of an app, a class's smali, a search through the smali of every class, disassemble/assemble, apktool decode/build (unsigned), zipalign + a throwaway debug key per call. Input read-only at `/work`, everything written in `/out`, one JVM per call with an empty environment and a time limit, no key of ours or yours. Every jar checked against every checksum file its repository publishes, here and in CI before each build (the image holds exactly those jars); every jar scanned for process, network and environment use. Until 2026-11-22 baksmali/smali's fat release jars, replaced after CI found one class of them differing from Google's | none; `/work` read-only (required), `/out` writable; `--memory 2g --pids 256 --tmp 512m` | `tests/test_smali.py` (27 tests) here against the real baksmali 3.0.10, smali 3.0.10, apktool 3.0.3, zipalign and apksigner on Temurin 21; `test_smali` over stdio and the smoke spec in CI; not built here (no container engine) |
| agentql | our own server (`src/server.py`, the shared lock) with the one tool of tinyfish-io/agentql-mcp 1.0.1 (MIT, commit `affb3a5c`, npm 2026-02-21; its 99-line server read in full and compared with its source): `extract-web-data` - one POST of the URL and the prompt to AgentQL's hosted API, whose cloud browser and model return the data; public http(s) URLs only, no credentials in URLs, 120 s, answers within 24,000 characters, the key only in `X-API-Key`, HTTPS_PROXY honoured (upstream's node-fetch ignores it); the npm package's 97-package closure not shipped | allowlist `api.agentql.com:443`; `AGENTQL_API_KEY` | `tests/test_agentql.py` (handshake, tools only, refused URLs and prompts, the request against a stand-in, errors, bounds) and `test_agentql`; the smoke spec's refused calls through a stand-in engine; not built here; no real call (needs a key) |
| chrome-devtools | Google's Chrome DevTools MCP 1.12.0 (ChromeDevTools/chrome-devtools-mcp, Apache-2.0; commit `af283441`) with Debian's `chromium` 156.0.8078.108-1~deb13u1: 32 default tools (pages, input, snapshots, screenshots, screencasts, console, network, emulation, performance traces, Lighthouse, heap snapshots); usage statistics (Clearcut to `play.googleapis.com`), the npm update check, CrUX lookups and configuration discovery off, the statistics sender and the update script removed from the image, page-defined tools (third-party, WebMCP), extensions and PWAs off by flag; `--headless --isolated --no-file-navigations`, Puppeteer over a pipe. **Reviewed completely, fit to sign once CI passes** (own code read line by line, the bundle reproduced from source and its parts compared with their upstream releases) | full; `--memory 2g --pids 512`, 2 CPUs, a 768m /tmp | `tools/list`, the resolved configuration and the telemetry fail-closed checked locally against the installed package on Node.js 26 (no Chromium here); the smoke spec (a `data:` page, snapshot, script, a heavy page, a screenshot; a `file:` URL, a write to `/etc` and an extension tool refused) in CI; offline tests |

### The three file-analysis servers, and the cooldown rule

Their pins are old enough on 2026-11-08: radare2 6.2.4 and r2mcp 1.9.0 (release commits of
2026-10-15 and earlier), capa 10.0.0 and capa-rules 10.0.0 (release commits), the FuzzingLabs
wrapper commit `0409a543` (2026-01-27), binwalk and its extractors from the pinned trixie archive
(exempt). `flare-capa==10.0.0`, `pydantic==2.14.1` and `pydantic-settings==2.16.1` come from the
hub's hash-locked `requirements.txt`; `starlette` (1.10.0 -> 1.9.0) and `sse-starlette`
(3.5.1 -> 3.5.0) were set to the versions the other servers here pin, both too new in the hub's
lock and unused by a stdio server. Re-lock all `servers/*/requirements.txt` together with
`scripts/lock.sh` at the next re-lock date.

The hub's remaining servers are **not** ported: they scan, probe or crack (network scanners,
fuzzers, SQL injection, password cracking) or capture network traffic. They stay in the hub.

## The candidates' security review of 2026-11-17

The rule for the catalog: only servers whose shipped code we reviewed completely ourselves (all of it, the install
scripts of its dependencies, every network destination, telemetry off or removable), from a release at least 14
days old, sandboxed like the others with as little network as possible. Each candidate was checked against it on
2026-11-17 (upstream, licence and release dates looked up that day):

| Candidate | Upstream, licence, release | Verdict |
|---|---|---|
| agentql | tinyfish-io/agentql-mcp 1.0.1, MIT, npm 2026-02-21 (the newest; 269 days old) | **added** as [servers/agentql](../servers/agentql): the whole package (one 99-line server) read and compared with its source; no backdoor, telemetry or unexpected host; shipped as an own server on the shared reviewed Python lock with upstream's findings fixed (no URL check, no time limit, unbounded answers, `HTTPS_PROXY` ignored). The candidate folder is gone |
| reddit | karanb192/reddit-mcp-buddy, MIT; 1.1.14 (2026-07-29) prepared, 1.2.0 (2026-11-02 02:44 UTC) old enough since 2026-11-16, 1.2.1 (11-10) and 1.3.0 (11-11) not | **not added yet - review not finished, nothing found against it.** The pinning rule asks for 1.2.0 now, and 1.2.0 is a different server: write tools (posting, commenting, voting, behind `REDDIT_BUDDY_WRITE`), an OAuth consent flow that writes a refresh token to a file (`core/oauth-consent.js`, `core/auth.js`), a write gate; 5,513 lines of JavaScript in 15 modules (1.1.14: about 4,300) on `@modelcontextprotocol/sdk` `^1.32.2` and zod 4 (the SDK 1.x closure, about 95 packages, is reviewed nowhere in this repository). A first scan of 1.2.0: hosts only `www.reddit.com`, `oauth.reddit.com` (and help links), `child_process` only in the CLI (`cli.js`, the `--auth` browser opener, not the server), file writes only for the token store. To finish: read 1.2.0 completely, review the SDK 1.32.2 stdio path (or port the read tools onto the shared Python lock as for agentql), keep the write tools off. **2026-11-25: done as the port** - reddit-mcp-buddy 1.2.1 (2026-11-10) reviewed on its read path, its four read tools as an own server on the shared lock ([servers/reddit](../servers/reddit), pending; app-only OAuth, no write); `candidates/reddit` removed |
| browserbase | browserbase/mcp-server-browserbase 3.0.0, Apache-2.0, 2026-03-31 (the newest release) | **not added.** Not reviewable completely, and the opposite of minimal network: every page lives in Browserbase's cloud browser (a CDP WebSocket to a host the session API hands out, not known in advance), and `act`/`observe`/`extract` send the page's content to an LLM provider (Gemini by default) - three secrets, three parties. Stagehand 3.0.8 (the core, 2.8 MB unpacked) brings 15 dependencies including the Anthropic, OpenAI, Google GenAI, LangChain and Vercel AI SDKs and 20 optional ones (12 AI SDK providers, Playwright, Puppeteer, patchright); its hosts could only be read at `main`, not at the locked release. playwright and chrome-devtools (reviewed, local browser) cover the use; Browserbase's hosted MCP endpoint (`https://mcp.browserbase.com/mcp`) needs no container |
| codebase-memory | DeusData/codebase-memory-mcp 0.12.1, MIT, 2026-10-16 (the newest) | **not added.** What would ship is the release's prebuilt, fully static 330 MB binary (embedded web UI included); its repository has 236 MB of C (tree-sitter grammars of 162 languages vendored, SQLite) plus C++, TypeScript and JavaScript - neither reviewable completely nor rebuilt and compared here, and the release's SLSA/cosign attestations could not be verified (they need a GitHub login). It also starts a detached daemon and, without a config file, a web UI on `127.0.0.1:9749` (`--ui=false` in the entry point). code-search (ours, reviewed) covers definitions, references, outlines and a project map |
| ghidra | clearbluejar/pyghidra-mcp 0.3.0 (2026-11-02, old enough since 2026-11-16), Apache-2.0; Ghidra 12.2 (2026-10-22), Apache-2.0 | **not added.** Not reviewable completely: Ghidra itself (about 103 MB of Java and 7 MB of C++ in its repository, the headless analyzer and decompiler run on every import), and the lock's 101 Python packages - chromadb 1.5.9 (with its Rust core), onnxruntime, huggingface-hub, tokenizers, grpcio, kubernetes and the OpenTelemetry OTLP exporters among them; chromadb's default embedding function downloads its ONNX model at first use. radare2, jadx, cfr and capa (reviewed) cover static analysis; a Ghidra server would need a much smaller build (Ghidra headless without chromadb's semantic search) with its own review **2026-11-25:** that smaller build exists - [servers/ghidra](../servers/ghidra) ([tier2-sec-reviews.md](tier2-sec-reviews.md)) |
| rea | morluto/rea, MIT; 6.8.0 (2026-10-25, old enough since 2026-11-08), 6.9.0 (2026-11-12) not | **not added.** Not reviewable completely: about 68 MB of TypeScript in its repository, 42 direct dependencies (node-pty with a native build, playwright-core, isomorphic-git, openpgp, ws, ...), about 230 tools, of which some run the sample or arbitrary commands (`capture_process_scenario`, `capture_electron_scenario`, `gdb_console`, Frida tools); Node.js from nodejs.org would have to be pinned besides. Too many tools for the small local models this catalog serves, too |

## Prepared (`candidates/`): audited, pins missing (see the review of 2026-11-17 above: none of these is admitted)

| Server | Upstream | Why not built yet |
|---|---|---|
| ghidra | pyghidra-mcp 0.3.0 + Ghidra 12.2 (Apache-2.0) | Re-pin before building: 2026-11-16 or an older release (pyghidra-mcp 0.3.0 and 24 locked dependencies too new); Debian versions of the JDK, unzip and python3 to pin; memory (needs about 4 GiB); chromadb's embedding model offline; superseded on 2026-11-25 by servers/ghidra, the folder is gone |
| codebase-memory | DeusData/codebase-memory-mcp 0.12.1 (MIT), static release binary | all pins set (release SHA-256, Debian git); not built or smoke-tested; memory for large repositories; needs `/out` writable |
| browserbase | browserbase/mcp-server-browserbase 3.0.0 (Apache-2.0) | all pins set; build not run (Node 20 vs. Stagehand 3.0.8); the CDP host the session API returns is unverified; three secrets |
| rea | morluto/rea 6.8.0 (MIT), without native engines | Re-pin before building: 2026-11-08 or an older release (6.8.0 of 2026-10-25); Node.js >= 22.23.4 from nodejs.org: version and SHA-256 to pin; compile step not run; which tools work without engines |

Each has a `PROVENANCE.md` with the audit notes and a Dockerfile that refuses to build until the
pins are set (codebase-memory and browserbase have all pins set but were not built yet; reddit became servers/reddit
on 2026-11-25; agentql moved to
servers/ on 2026-11-17).
The Debian versions of the new candidates were read from the trixie, trixie-updates and
trixie-security indexes of 2026-11-05 (nodejs `20.19.2+dfsg-1+deb13u3`, npm `9.2.0~ds1-3`, git
`1:2.47.3-0+deb13u1`, chromium `156.0.8078.108-1~deb13u1`). To finish one: fill the pins (its Dockerfile names the
command), build it, run `scripts/smoke_test.py` with a `smoke.json`, write `tools.json` from the tools/list, move the
folder to `servers/` and add it to the CI matrix.

## Looked at, not a container candidate

| Upstream | What it is | Why not here / what instead |
|---|---|---|
| obra/superpowers 7.0.2 (MIT) | skills plugin (14 skills, a SessionStart hook) for Claude Code, Codex, OpenCode and others | a kit for the agent itself, no MCP server |
| Fission-AI/OpenSpec 1.16.0 (MIT) | CLI `openspec` that writes skills and slash commands (`/opsx:*`) into the project | a kit; telemetry to `edge.openspec.dev` and an npm version check unless `OPENSPEC_TELEMETRY=0` / `DO_NOT_TRACK=1` |
| oraios/serena 2.1.0 (GPL-3.0-or-later, SolidLSP MIT) | MCP server of LSP-based code tools that edit the project, with a shell tool | runs where the project and its toolchains are: a kit (agent-side MCP server); it downloads language servers at run time |
| ruvnet/ruflo 3.71.4 (MIT) | agent meta-harness: hooks on every tool call, daemon, several hundred MCP tools (terminal_execute, npm auto-install, federation relays) | a kit at most, after its own review; it reconfigures the agent and runs commands itself |
| koala73/worldmonitor 2.11.8 (AGPL-3.0-only) | dashboard app; hosted MCP `https://worldmonitor.app/mcp` | remote service: allowlist `worldmonitor.app:443`, `X-WorldMonitor-Key` or OAuth; its skills plugin is a kit |
| upstash/context7 | also hosted at `https://mcp.context7.com/mcp` | remote service as an alternative to servers/context7 |
| browserbase | also hosted at `https://mcp.browserbase.com/mcp` | remote service as an alternative to the browserbase candidate |
| mindsdb/mindshub 26.1.0 (Elastic-2.0, integrations MIT; formerly mindsdb/mindsdb) | federated SQL server; its MCP (`query` tool, schema resources) is a route of its HTTP API (`:47334/mcp/streamable`, `/mcp/sse`) | a long-running stateful server, not one container per connection: run it yourself and add it as a remote endpoint |
| Blender Lab MCP (projects.blender.org/lab/blender_mcp, not reachable from here) | add-on inside a running Blender plus a stdio bridge to `localhost:9876` | host-only: needs the Blender GUI on the host and runs arbitrary `bpy` Python there; source, version and licence unverified |
| screenpipe/screenpipe app-v2.7.138 (Screenpipe Commercial License, not open source) | screen and audio recorder; `screenpipe-mcp` 0.20.4 is a client of its local API `localhost:3030` | host-only: records the host's screen, audio and accessibility tree; licence restricts commercial use |
| other Reddit MCP servers (2026-11-06): jordanburke/reddit-mcp-server 2.0.1, nite/reddit-readonly-mcp 0.2.0, Hawstein/mcp-server-reddit 0.2.1, eliasbiondo/reddit-mcp-server 0.2.1, Arindam200/reddit-mcp, adhikasp/mcp-reddit, dialog-tools/reddit-research-mcp (all MIT) | Reddit clients | reddit-mcp-buddy (the reddit candidate, 1.1.14) is cleaner: jordanburke always registers create/edit/delete tools (they fail without a login) and also asks the third-party archive `arctic-shift.photon-reddit.com`; reddit-readonly-mcp poses as Reddit's official mobile app (its client id, `gql-fed.reddit.com`); eliasbiondo reads logged-out without an API app (`redd` scraper library); Hawstein (redditwarp, anonymous) last changed 2026-06, adhikasp 2025-05 with 11 open issues; Arindam200 has posting tools with a password login (praw), last changed 2025-12; dialog-tools is a hosted research service (OpenAI agents, Descope login) |
| SupportPages-io/wtfm 0.7.3 (Apache-2.0; npm `@supportpages.io/wtfm`) | "Write the F***ing Manual": Claude Code/Codex plugin and CLI that writes end-user help articles with screenshots rendered from the project's own markup; its MCP server (`supportpages_*`, 48 tools) coordinates the writing and is the client of the hosted SupportPages.io help centre | a kit plus a hosted-service client, not a container server: the articles are written by a subagent of the user's agent that runs the server's own `node` and engine scripts (and a downloaded Chromium) in the agent's sandbox, so in a container the core feature cannot work; the rest needs a SupportPages.io account. Review record below |
| zinja-coder/jadx-mcp-server 6.5.0 with the jadx-ai-mcp plugin 6.5.0 (Apache-2.0) | MCP server for jadx: a Python client of an HTTP API that the plugin serves from inside a running JADX GUI | needs the GUI (no headless mode), an unauthenticated HTTP API with state-changing GETs, unpinned dependencies; servers/jadx is our own headless server instead. Record below |
| basicmachines-co/basic-memory 0.24.1 (AGPL-3.0) | Markdown notes with an SQLite index, MCP server of the `basic-memory` CLI | cannot be reviewed completely (101,481 lines of its own on the MCP path, 43 required packages); updates itself, sends promo analytics, downloads an embedding model by default; record below |

### jadx-mcp-server and jadx-ai-mcp (zinja-coder): looked at on 2026-11-16, not packaged

Asked for on 2026-11-16 ("an MCP server for jadx"). Looked at for this decision - not a complete review, nothing of
it is shipped: the release `v6.5.0` of zinja-coder/jadx-ai-mcp (2026-10-19, 28 days old): the plugin's `pom.xml`,
`JadxAIMCP.java`, `PluginServer.java` and the route list (5,147 lines of Java in all, the rest searched for hosts,
sockets, authentication and GUI use), and the `jadx-mcp-server-6.5.0.zip` asset of the same release: the Python
server's entry `jadx_mcp_server.py`, `src/server/config.py` and the tool modules (2,690 lines with `test.sh` and the
example client). No backdoor or hidden network access seen; it is not packaged because it cannot run in a container
and because of how it is built:

- **It needs the GUI.** The plugin is a jadx-gui plugin: `JadxAIMCP.init` takes `context.getGuiContext()`, and
  without one logs "Running in non-GUI mode, plugin features disabled" and starts nothing. Every route works on
  `MainWindow` (the open project, the selected class, the selected text, the debugger panel). A container without a
  display has no MainWindow.
- **An unauthenticated HTTP API in the GUI.** `PluginServer.start` runs `Javalin.create(...).start(port)` with no host
  (Jetty's default: every interface; the README and the Python side speak of `127.0.0.1:8650`); no token, no origin
  check. State changes are plain GETs: `/rename-class`, `/rename-method`, `/rename-field`, `/rename-package`,
  `/rename-variable`, `/add-comment` - any web page the analyst opens can send them (no CORS preflight for a simple
  GET), and so can anything on the network. `/debug/*` reads the debugger's stack frames, threads and variables.
- **The Python server** is a thin client of that API (`httpx`, `trust_env=False`), on `fastmcp>=3.0.2`, `httpx>=0.28.1`
  and `requests>=2.32.3` unpinned (a large, moving dependency tree for a few HTTP calls); its `--http` mode serves MCP
  without authentication (with a warning). Its tools include the write tools above and the debugger tools, on by
  default; lists are paginated by item count, a class's source comes back whole (not bounded in characters).

servers/jadx offers the same reverse-engineering reads (classes, sources, methods, smali, cross references, search,
manifest, resources) headless, from jadx's own library in a JVM of its own per file, read-only, with no listening
socket; renaming and comments are left out (they change only the GUI's project).

### Basic Memory: looked at on 2026-11-11, not packaged

**Upstream.** https://github.com/basicmachines-co/basic-memory (Basic Machines, AGPL-3.0, Python >= 3.12). Newest
release old enough (cut-off 2026-10-28): **v0.24.1**, commit `1d0e09b6f4876c3f339c30e8dbfcf66e59e2c356`
(2026-10-23; PyPI wheel `sha256:b528fff0...`); v1.0.0 (2026-10-29) is too new. The GitHub tarball of the commit was
read (`sha256:b7de744c...`), never installed or run.

**What `basic-memory mcp` is.** A Typer CLI command (`cli/commands/mcp.py`) that starts a FastMCP 4.1.3 server whose
tools call Basic Memory's own FastAPI app in-process (ASGI transport), which runs its services, repositories
(SQLAlchemy, Alembic migrations), Markdown parser, file sync (watchfiles) and search (SQLite FTS5 plus sqlite-vec
vectors). Its MCP tools include `write_note`, `read_note`, `edit_note`, `move_note`, `delete_note`, `search_notes`,
`build_context`, `recent_activity`, `list_directory`, the POSIX-like `ls`/`cat`/`grep`/`find`/`head`/`tail`, schema
tools, ChatGPT `search`/`fetch`, `list_memory_projects`, `create_memory_project`, `delete_project`,
`list_workspaces` (cloud workspaces).

**Why it cannot be reviewed completely.** The static import closure of `basic_memory.mcp.server` with its tools,
prompts and resources is 308 modules, **101,481 lines** of Basic Memory's own Python (121,009 with the CLI entry;
`src/` has about 135,000). Required dependencies (not extras): 43, among them `litellm` (>= 1.91.5), `openai`,
`logfire`, `fastembed`, `asyncpg`, `psycopg`, `fastapi[standard]`, `fastapi-redis-sdk`, `pyright`, `pytest-aio`,
`pytest-asyncio`, `sqlite-vec`, `watchfiles`, `uvloop`; the closure imports `litellm`, `openai`, `logfire`,
`fastembed`, `pymilvus`, `redis` and `requests` (some lazily). A line-by-line review of that code and the risky
surfaces of that dependency tree was not done, so it cannot be signed under our rule.

**Network and telemetry by default** (what was read, with lines at `1d0e09b6`):
- `cli/commands/mcp.py` 102-116: on the stdio transport the MCP server starts `run_auto_update` in a thread;
  `config_models.py` 698: `auto_update` defaults to true; `cli/auto_update.py` asks `https://pypi.org/pypi/basic-memory/json`
  (122-126) and runs `uv tool upgrade` or `brew upgrade` (`_run_subprocess`, 94-111, 416). Off only by config.
- `cli/analytics.py` 28-107: events of the CLI-to-cloud funnel go to `https://api-gateway.umami.dev/api/send`
  (site id baked in) unless `BASIC_MEMORY_NO_PROMOS=1`; called from `cli/promo.py` 126 and the cloud commands.
- CHANGELOG #1696 (0.24.0): semantic search is always on, the `semantic_search_enabled` switch is gone; FastEmbed
  downloads its embedding model (and the default reranker) on first use into `<data dir>/fastembed_cache`.
- `telemetry.py`: Logfire is off unless `logfire_enabled` (`config_models.py` 205-212, default false).
- `cli/commands/mcp.py` 67-80: stdio honours `BASIC_MEMORY_FORCE_CLOUD` and per-project cloud routing.
- `file_utils.py` 290-320: a configured `formatter_command` is run as a subprocess on every saved note
  (`format_on_save`, off by default).

**Findings.** No backdoor or obfuscated code in what was read (the files above, the MCP command, the telemetry,
analytics, auto-update and config modules). Against our rules: (1) not reviewable completely at its size;
(2) self-update and analytics on by default; (3) a model download at run time with no switch left to turn semantic
search off; (4) cloud tools and project deletion in the default tool set.

**Verdict.** Not packaged and not a candidate. Revisit if upstream ships a local-only server without the cloud,
update and analytics code, or as an own small server over Basic Memory's documented note format
(`NOTE-FORMAT.md`) and its SQLite FTS index, reviewed like the other own servers here.

### wtfm: looked at on 2026-11-11, not packaged

**Upstream.** https://github.com/SupportPages-io/wtfm, organisation SupportPages-io (the company behind
supportpages.io; every commit by one maintainer, Simon Moxon, plus a bot that syncs `engine/` from a private
upstream repository "RTFM", engine 1.63.0 at its commit `39ab1c9a`). Created 2026-09-25, 124 stars, active
(last push 2026-11-05). Apache-2.0. JavaScript/TypeScript, Node.js >= 22.12. Tags only, no GitHub releases.
Newest version old enough (cut-off 2026-10-28): **v0.7.3**, commit `e6c0b52f` of 2026-10-27, npm 0.7.3 of
2026-10-27 with an npm provenance attestation for that commit; its `package-lock.json` (129 production
packages) has nothing newer than 2026-10-27 (qs 6.17.0), direct pins @modelcontextprotocol/sdk 1.32.1,
puppeteer 25.16.0 (2026-10-22, install script downloads Chrome for Testing), zod 4.6.7, marked 17.0.6,
yauzl 3.4.0, @clack/prompts 1.6.0. Pinning would have been possible.

**What it is.** `wtfm setup` registers the MCP server and a writer subagent with Claude Code or Codex. For an
article, the agent calls `supportpages_prepare_article`; the server returns a task brief whose entry point is a
shell command - the server's own `process.execPath` with `dist/writer-entry.js` and the engine directory of
its installation (`src/writer-entry.ts` 20-29, `src/bridge.ts` 314-345). The user's agent runs it and every
generation command (`... --exec <command>`) in its own environment: 67 engine scripts (16,687 lines) that
compile the project's CSS (`npm install --no-save @tailwindcss/cli`, `npx tailwindcss|sass|postcss` in the
project, unpinned), fetch Bootstrap/Bulma/Foundation and every CDN stylesheet the project references with
`curl` (`engine/detect-project/scripts/compile_css.sh` 233-235, 355-380, 408-414), render mockups in
puppeteer's Chromium, and optionally call OpenAI with the user's `OPENAI_API_KEY`. `wtfm init`/`analyse`
start the agent with `--dangerously-skip-permissions` (Codex: `--dangerously-bypass-approvals-and-sandbox`).

**Why not a container server.** In a container the brief names a `node` and files the agent does not have,
and the workspace path must be the same on both sides; local writing - the feature that needs no account -
cannot work. Making it work means running WTFM's engine, npm/npx and Chromium inside the agent's sandbox,
i.e. a kit to be reviewed as such. What would remain in a container is the SupportPages.io client
(list/get/update/publish/delete articles, hosted generation, video walkthroughs, sections and
recommendations): it needs an account, a device credential written to `~/.config/supportpages` (lost with
each per-connection container unless mounted), the project mounted writable (state in `.rtfm/supportpages`),
and the browser opened on the host.

**Data that leaves** (all to `https://app.supportpages.io/api/v1`, `SUPPORTPAGES_API_URL` overrides):
telemetry without credentials, **on by default** (`/writer_telemetry`: random install id, version, client
name, OS, arch, Node major, event counts, scrubbed stack frames of unexpected errors; off with
`DO_NOT_TRACK=1` or `SUPPORTPAGES_TELEMETRY=0`; the install id is sent with the device sign-in so later usage
is linked to the account); device sign-in (`/mcp/pairings`, hostname as device label, scopes read, import,
projects:create plus optionally publish, manage, generate; bearer token `sp_local_<64 hex>`); with an
account, uploads of each article (JSON, PNG screenshots, a manifest with the project's git HEAD commit and
dirty flag) and live previews while writing; hosted generation (`wtfm yolo`, hosted create/edit/gaps)
needs SupportPages.io read access to the repository - the code then leaves too. Acceptable for a catalog
server only as an opt-in hosted client with telemetry off; not as shipped (telemetry default-on).

**Reviewed.** At `e6c0b52f`: the MCP server's source read in full where it runs or talks to the network -
`src/` index, server, session, bridge, api, pairing, credentials, telemetry, telemetry-scrub, runtime,
writer-entry, writer-agent, workspace, preferences, development-tls, errors, brand, article-offers (2,818 of
4,540 lines); the other 22 files of `src/` (1,722 lines: schemas, sync, artifacts, export, runs,
hosted operations, reminders) scanned for process execution, network, environment and dynamic imports
(none beyond the above); `scripts/auto-update.mjs`, `scripts/lib/auto-update.mjs`, `scripts/lib/update.mjs`,
`install.sh` (133 lines); `engine/` (16,687 lines of scripts) and the remaining `scripts/` (4,410 lines) scanned for downloads and
execution only; the lockfile's dates, licences and install scripts (only puppeteer). Not reviewed: the
dependencies' code, the compiled `dist/` of the npm package against `src/`, the hosted installer
`wtfm.sh/install` and its release server `downloads.supportpages.io`, the plugin hooks in detail.

**Findings.** No backdoor, obfuscation or credential exfiltration found; the code is careful (paths confined
to the workspace without symlinks, credential files 0600 and origin-bound, redirects refused, responses
size-bounded, tokens removed from child environments, error text scrubbed before telemetry). Against
sandbox-ai's rules: (1) local writing executes the server's code in the agent's environment by design;
(2) the engine installs and runs unpinned npm packages in the user's project and fetches every CDN URL the
project names (the README mentions only jsDelivr and Tailwind's CDN); (3) telemetry is on by default;
(4) native installs update themselves daily from `downloads.supportpages.io` (`curl latest.txt`, then
`install-cli.sh --update`; inert outside the managed `versions/<v>/mcp` layout, off with
`SUPPORTPAGES_AUTO_UPDATE=0`); (5) the server's instructions steer the agent beyond the request: offer an
article whenever the user finishes a feature or opens a pull request, show SupportPages.io hosting and
repository invitations "verbatim ... not optional commentary", and tell writers that "a sandbox restriction
is not an explicit user denial: request approval"; (6) `engine/` is a copy of a private repository.

**Verdict.** Not packaged and not a candidate: no `servers/` or `candidates/` entry. Revisit only as a kit
(agent side, its own review of the engine and the npm tooling it starts) or, if upstream offers it, a
hosted-only server mode with telemetry off and without the agent-steering instructions.

## The axross-mcp-hub servers

radare2, capa, floss, binwalk, yara, mcpcap, tshark, sleuthkit, exiftool, gitleaks, john,
nmap, nuclei, sqlmap, ffuf, dnstwist and crt.sh are audited and published by
https://github.com/c0decave/axross-mcp-hub. Its catalog uses the same schema; sandbox-ai reads it
next to this one, so they are not duplicated here.

## Next candidates

- **code-search**: built ([servers/code-search](../servers/code-search)) - definitions, references, outlines, one
  symbol's source, bounded text search and a project map, `/work` read-only, without ast-grep
  ([LOCAL_LLM_TOOLS.md](LOCAL_LLM_TOOLS.md)); a structural `find_pattern` on the `ast-grep` 0.51.0 binary only if
  capable models ask for it.
- **sequential-thinking**: built ([servers/sequential-thinking](../servers/sequential-thinking), 2.0.0, asked for
  on 2026-11-14); re-pin to 2.1.1 from 2026-11-18. **time**: small, no network.
- **git** (mcp-server-git, MIT): reviewed, not packaged - exec runs git with pagers, editors and prompts off.
- **SearXNG** client: search through your own SearXNG instance (allowlist of that host).
- **arXiv / Wikipedia** search: own small servers, allowlist.
- **Round 2 (2026-11-18)**: added as pending entries - time, osv, youtube-transcript, wikipedia, arxiv, shodan,
  calculator; not added - dbhub, markitdown, maigret (not reviewable completely; `candidates/`), gitea-mcp (pin
  v1.12.0 verified, review open; added on 2026-11-25 as servers/gitea with v1.13.0, see tier1-dev-reviews.md). Verdicts and reasons: [round2-reviews.md](round2-reviews.md);
  the helpers for local models: [local-helpers.md](local-helpers.md).
