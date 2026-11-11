# MCP servers for sandbox-ai: state and candidates

State: 2026-11-11 (playwright moved to `servers/`; openosint, osint-mcp, signal and whatsapp added; memory and
engram added, Basic Memory looked at and left out).

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
| candidates/context7 | `@upstash/context7-mcp` 4.5.0 (commit `a138857c`); pnpm 10.34.9 | 2026-11-03; 2026-10-25 | 2026-11-17; 2026-11-08 |
| candidates/rea | `rea-agents` 6.8.0 (commit `160d821a`) | 2026-10-25 | 2026-11-08 |
| candidates/ghidra | `pyghidra-mcp` 0.3.0, and 24 of its hash-locked dependencies (pydantic 2.14.2, onnxruntime 1.31.1, opentelemetry 1.45.2, huggingface-hub 2.4.0, grpcio 1.85.1, ...) | 2026-11-02; 2026-10-24 to 2026-11-02 | 2026-11-16 at the latest |

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

Old enough: agentql (`agentql-mcp` 1.0.1, 2026-02-21), browserbase (3.0.0, commit of
2026-03-31; pnpm 10.12.4, 2025-06-26), codebase-memory (0.12.1, 2026-10-16), chrome-devtools
(1.12.0, 2026-10-22), Ghidra 12.2 (2026-10-22), reddit (`reddit-mcp-buddy` 1.1.14, 2026-07-29;
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
| playwright | a headless Chromium through Microsoft's Playwright MCP 0.0.83 (commit `f183dad4`, 2026-09-28; Apache-2.0) with Debian's `chromium` 156.0.8078.79-1~deb13u1: 25 default tools (navigate, snapshot, click, type, forms, tabs, evaluate, run code, screenshots, console, network requests); `--isolated --no-sandbox --no-webmcp`, no `--caps` | full; `--memory 2g --pids 512` | offline tests (pins, flags, tools, limits, the smoke spec's limits as sandbox-ai takes them); the smoke spec in CI (a `data:` page, a `file:` URL and a file outside the roots refused); not built here (no container engine) |
| openosint | passive OSINT lookups with 26 reviewed modules of OpenOSINT 2.36.1 (MIT, commit `99849732`, each file pinned by SHA-256) behind an own server: dork URLs, RDAP, WHOIS, DNS, ipinfo.io, GitHub, psbdmp.ws, GDELT news; with keys HIBP, VirusTotal (no URL submission), AbuseIPDB, IP2Location.io, Bright Data SERP. Passive only (active mode cannot be enabled); OpenOSINT's active tools, LLM agent, graph, web UI and Shodan/Censys tools are not in the image | full (WHOIS referrals and RDAP servers come from the registries); seven optional keys | natively against the reviewed modules (tools, refused arguments, passive mode, key redaction); the smoke spec in CI (offline dork URLs, a live RDAP lookup, four refused calls); not built here (no container engine) |
| signal | a Signal account of yours as a linked device: signal-cli 0.14.9 (JVM release, GPL-3.0; by SHA-256 and its maintainer's signature) on Temurin JRE 25.0.5+8, with six reviewed modules of signal-mcp 1.43.3 (googlarz/signal-mcp, MIT: client and SQLite message history; not its MCP server, CLI, Desktop import or webhook) behind an own server: 8 read tools (fetch, unread, conversations, search, contacts, groups without invite links); `send_message`, `send_group_message`, `react_to_message` only with `SIGNAL_WRITE=1`, optional `SIGNAL_ALLOWED_RECIPIENTS`; no file, receipt or account change | full; `/data` writable (required: the account, linked once with `--link`); `--memory 1g --pids 256` | natively with a stand-in for signal-cli's JSON-RPC daemon (`tests/test_signal.py`); in the image: signal-cli runs and libsignal loads under the hardened flags; smoke spec without an account; not built here, no live account |
| whatsapp | a WhatsApp account linked as a device: edouard-claude/whatsapp-mcp at `f3fe07f2` (2026-10-20, MIT; Rust MCP server wa-mcp, Go bridge wa-bridge on whatsmeow `8b41cfe6`) with five patches of this repository (read-only unless `WHATSAPP_WRITE=1`, no pairing or logout tools, files sent only from `/send`, no Status or broadcast sending, libsignal's log off stdout, media capped, sender checks on edits and deletions, the account's folder owner-only); 12 read tools by default, 37 with `WHATSAPP_WRITE=1` | full; `/data` writable (the session and the message database), `/send` read-only optional | the bridge compiled and its patch unit-tested here with Go 1.26.10 and the go.sum-verified modules; the Rust patches not compiled here (no Rust toolchain); offline tests (pins, patches, tools, mounts); the smoke spec in CI (tools/list without an account, a real call, refused calls); no live call (that would need an account) |
| binwalk | what is inside a firmware file: signature scan, extraction, entropy, hex dump; Debian binwalk 2.4.3 with pinned extractors; FuzzingLabs wrapper, patched (paths under `/work`, no option injection, `/out` or `/tmp` for extraction) | none; `/work` read-only (required), `/out` writable optional | ported from axross-mcp-hub, where it was audited and smoke-tested; here: offline tests and the smoke spec in CI |
| memory | the official MCP Knowledge Graph memory server 2.0.1 (modelcontextprotocol/servers `src/memory`, Apache-2.0/MIT; npm release built by upstream CI from commit `194cc86e`, provenance-attested): entities, observations, relations in `/data/memory.jsonl`, 9 tools (create, add, delete, search by substring, open, read graph); server read line by line (its 1,280 TypeScript lines and the shipped JavaScript compared), the MCP SDK 2.4.0 on its whole stdio path (14,200 lines), zod and the bundled Ajv on their risky surfaces; no patch; `node --disallow-code-generation-from-strings` | none; `/data` writable (required), one folder per case | the smoke spec run locally through `scripts/smoke_test.py` against the reviewed packages on Node.js 26 (write, search, read back; four refused calls); offline tests; not built here (no container engine) |
| engram | Engram 3.6.0 (Gentleman-Programming/engram, MIT, commit `98912f81`), only its MCP server: an own entry point (`src/main.go`) built inside Engram's module links internal/mcp and internal/store and what they import (31,134 lines in 61 files, every one read line by line and pinned by SHA-256; the build proves nothing else of Engram is linked); mcp-go 0.44.0 read line by line; the other Go modules (modernc sqlite/libc, x/sys, x/text, uuid, jsonschema, ...) on their risky surfaces. 23 agent tools; `directory`/`cwd` arguments removed (they scan folders and would run git); arguments bounded, panics recovered, memory in `/data` with Engram's own limits | none; `/data` writable (required), one project per folder (`ENGRAM_PROJECT`, default `brain`) | `src/main_test.go` runs in the image build; smoke spec in CI (save, search, read back; four refused calls); offline tests; not built here (no Go toolchain, no container engine) |

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

## Prepared (`candidates/`): audited, pins missing

| Server | Upstream | Why not built yet |
|---|---|---|
| ghidra | pyghidra-mcp 0.3.0 + Ghidra 12.2 (Apache-2.0) | Re-pin before building: 2026-11-16 or an older release (pyghidra-mcp 0.3.0 and 24 locked dependencies too new); Debian versions of the JDK, unzip and python3 to pin; memory (needs about 4 GiB); chromadb's embedding model offline |
| codebase-memory | DeusData/codebase-memory-mcp 0.12.1 (MIT), static release binary | all pins set (release SHA-256, Debian git); not built or smoke-tested; memory for large repositories; needs `/out` writable |
| chrome-devtools | ChromeDevTools/chrome-devtools-mcp 1.12.0 (Apache-2.0) + Debian Chromium | npm package integrity to pin (npm not reachable when prepared); Chromium's limits; upstream supports Chrome only |
| context7 | upstash/context7-mcp 4.5.0 (MIT) | Re-pin before building: 2026-11-17 or an older release (4.5.0 of 2026-11-03, pnpm 10.34.9 of 2026-10-25); all pins set (pnpm by SHA-256, Debian versions); build not run; allowlist `context7.com:443`, optional `CONTEXT7_API_KEY` |
| browserbase | browserbase/mcp-server-browserbase 3.0.0 (Apache-2.0) | all pins set; build not run (Node 20 vs. Stagehand 3.0.8); the CDP host the session API returns is unverified; three secrets |
| agentql | tinyfish-io/agentql-mcp 1.0.1 = npm `agentql-mcp` (MIT), commit `affb3a5c` (no git tag) | all pins set (npm tarball SHA-512/SHA-256, lockfile by commit, Debian versions); build not run; allowlist `api.agentql.com:443`, `AGENTQL_API_KEY` required; node-fetch ignores `HTTPS_PROXY` |
| reddit | karanb192/reddit-mcp-buddy 1.1.14 = npm `reddit-mcp-buddy` (MIT), 2026-07-29, commit `dfd3f094` (npm provenance; the tag was moved later, CI-only) | all pins set (npm tarball SHA-512/SHA-256, lockfile by commit, Debian versions); build not run; read-only (no write tools in this release); allowlist `www.reddit.com:443`, `oauth.reddit.com:443`; `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET` (an app Reddit approved) and `REDDIT_USER_AGENT`, without them only RSS browsing; 1.2.0 (too new) fixes a zod memory issue, uncut error bodies and cache-key collisions; Node 20's fetch ignores `HTTPS_PROXY` |
| rea | morluto/rea 6.8.0 (MIT), without native engines | Re-pin before building: 2026-11-08 or an older release (6.8.0 of 2026-10-25); Node.js >= 22.23.4 from nodejs.org: version and SHA-256 to pin; compile step not run; which tools work without engines |

Each has a `PROVENANCE.md` with the audit notes and a Dockerfile that refuses to build until the
pins are set (codebase-memory, context7, browserbase, agentql and reddit have all pins set but were
not built yet).
The Debian versions of the new candidates were read from the trixie, trixie-updates and
trixie-security indexes of 2026-11-05 (nodejs `20.19.2+dfsg-1+deb13u3`, npm `9.2.0~ds1-3`, git
`1:2.47.3-0+deb13u1`, chromium `156.0.8078.79-1~deb13u1`). To finish one: fill the pins (its Dockerfile names the
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
| upstash/context7 | also hosted at `https://mcp.context7.com/mcp` | remote service as an alternative to the context7 candidate |
| browserbase | also hosted at `https://mcp.browserbase.com/mcp` | remote service as an alternative to the browserbase candidate |
| mindsdb/mindshub 26.1.0 (Elastic-2.0, integrations MIT; formerly mindsdb/mindsdb) | federated SQL server; its MCP (`query` tool, schema resources) is a route of its HTTP API (`:47334/mcp/streamable`, `/mcp/sse`) | a long-running stateful server, not one container per connection: run it yourself and add it as a remote endpoint |
| Blender Lab MCP (projects.blender.org/lab/blender_mcp, not reachable from here) | add-on inside a running Blender plus a stdio bridge to `localhost:9876` | host-only: needs the Blender GUI on the host and runs arbitrary `bpy` Python there; source, version and licence unverified |
| screenpipe/screenpipe app-v2.7.138 (Screenpipe Commercial License, not open source) | screen and audio recorder; `screenpipe-mcp` 0.20.4 is a client of its local API `localhost:3030` | host-only: records the host's screen, audio and accessibility tree; licence restricts commercial use |
| other Reddit MCP servers (2026-11-06): jordanburke/reddit-mcp-server 2.0.1, nite/reddit-readonly-mcp 0.2.0, Hawstein/mcp-server-reddit 0.2.1, eliasbiondo/reddit-mcp-server 0.2.1, Arindam200/reddit-mcp, adhikasp/mcp-reddit, dialog-tools/reddit-research-mcp (all MIT) | Reddit clients | reddit-mcp-buddy (the reddit candidate, 1.1.14) is cleaner: jordanburke always registers create/edit/delete tools (they fail without a login) and also asks the third-party archive `arctic-shift.photon-reddit.com`; reddit-readonly-mcp poses as Reddit's official mobile app (its client id, `gql-fed.reddit.com`); eliasbiondo reads logged-out without an API app (`redd` scraper library); Hawstein (redditwarp, anonymous) last changed 2026-06, adhikasp 2025-05 with 11 open issues; Arindam200 has posting tools with a password login (praw), last changed 2025-12; dialog-tools is a hosted research service (OpenAI agents, Descope login) |
| SupportPages-io/wtfm 0.7.3 (Apache-2.0; npm `@supportpages.io/wtfm`) | "Write the F***ing Manual": Claude Code/Codex plugin and CLI that writes end-user help articles with screenshots rendered from the project's own markup; its MCP server (`supportpages_*`, 48 tools) coordinates the writing and is the client of the hosted SupportPages.io help centre | a kit plus a hosted-service client, not a container server: the articles are written by a subagent of the user's agent that runs the server's own `node` and engine scripts (and a downloaded Chromium) in the agent's sandbox, so in a container the core feature cannot work; the rest needs a SupportPages.io account. Review record below |
| basicmachines-co/basic-memory 0.24.1 (AGPL-3.0) | Markdown notes with an SQLite index, MCP server of the `basic-memory` CLI | cannot be reviewed completely (101,481 lines of its own on the MCP path, 43 required packages); updates itself, sends promo analytics, downloads an embedding model by default; record below |

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

- **sequential-thinking, time** (modelcontextprotocol/servers, MIT): small, no network (memory: `servers/memory`).
- **git** (mcp-server-git, MIT): of little use in sandbox-ai, whose agents have git themselves.
- **SearXNG** client: search through your own SearXNG instance (allowlist of that host).
- **arXiv / Wikipedia** search: own small servers, allowlist.
