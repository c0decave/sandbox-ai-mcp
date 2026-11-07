# MCP servers for sandbox-ai: state and candidates

State: 2026-11-06.

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
| candidates/playwright | `@playwright/mcp` 0.0.84 (commit `be26c080`) | 2026-10-31 | 2026-11-14 |
| candidates/context7 | `@upstash/context7-mcp` 4.5.0 (commit `a138857c`); pnpm 10.34.9 | 2026-11-03; 2026-10-25 | 2026-11-17; 2026-11-08 |
| candidates/rea | `rea-agents` 6.8.0 (commit `160d821a`) | 2026-10-25 | 2026-11-08 |
| candidates/ghidra | `pyghidra-mcp` 0.3.0, and 24 of its hash-locked dependencies (pydantic 2.14.2, onnxruntime 1.31.1, opentelemetry 1.45.2, huggingface-hub 2.4.0, grpcio 1.85.1, ...) | 2026-11-02; 2026-10-24 to 2026-11-02 | 2026-11-16 at the latest |

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

## Prepared (`candidates/`): audited, pins missing

| Server | Upstream | Why not built yet |
|---|---|---|
| ghidra | pyghidra-mcp 0.3.0 + Ghidra 12.2 (Apache-2.0) | Re-pin before building: 2026-11-16 or an older release (pyghidra-mcp 0.3.0 and 24 locked dependencies too new); Debian versions of the JDK, unzip and python3 to pin; memory (needs about 4 GiB); chromadb's embedding model offline |
| playwright | microsoft/playwright-mcp 0.0.84 (Apache-2.0) + Debian Chromium | Re-pin before building: 2026-11-14 or an older release (0.0.84 of 2026-10-31); Debian versions of nodejs, npm, git, chromium to pin; Chromium's limits; the channel name for Debian's Chromium |
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
trixie-security indexes of 2026-11-05 (for playwright these are nodejs `20.19.2+dfsg-1+deb13u3`,
npm `9.2.0~ds1-3`, git `1:2.47.3-0+deb13u1`, chromium `156.0.8078.79-1~deb13u1`; 0.0.84 is still
playwright-mcp's latest release). To finish one: fill the pins (its Dockerfile names the
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

## The axross-mcp-hub servers

radare2, capa, floss, binwalk, yara, mcpcap, tshark, sleuthkit, exiftool, gitleaks, john,
nmap, nuclei, sqlmap, ffuf, dnstwist and crt.sh are audited and published by
https://github.com/c0decave/axross-mcp-hub. Its catalog uses the same schema; sandbox-ai reads it
next to this one, so they are not duplicated here.

## Next candidates

- **sequential-thinking, time, memory** (modelcontextprotocol/servers, MIT): small, no network.
- **git** (mcp-server-git, MIT): of little use in sandbox-ai, whose agents have git themselves.
- **SearXNG** client: search through your own SearXNG instance (allowlist of that host).
- **arXiv / Wikipedia** search: own small servers, allowlist.
