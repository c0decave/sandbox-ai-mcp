# sandbox-ai-mcp

Audited, container-packaged [MCP](https://modelcontextprotocol.io) servers for
[sandbox-ai](https://github.com/c0decave/sandbox-ai): search, web access and analysis tools an
agent can use **without its own sandbox getting the network or the files they need**. Each server
runs in a container of its own (no capabilities, read-only root, no network unless its entry
grants it, only the folders you mount), and agents reach it through sandbox-ai's MCP bridge.

The catalog uses the schema of
[axross-mcp-hub](https://github.com/c0decave/axross-mcp-hub) (`axross-mcp-catalog`, version 1):
sandbox-ai reads both catalogs, and axross can read this one too. Three of the hub's file-analysis
servers are built here as well, to this repository's standards and tested with sandbox-ai's own run
lines: **radare2**, **capa** and **binwalk** - each with `network: none` and the files to look at
mounted read-only. The hub's network and password tools stay there; nothing here reaches out to a
network it was not given, and nothing here scans networks or tries passwords. Two servers look at a web site
you name: **gowitness** opens it in a browser for a screenshot, **whatweb** fingerprints its software (one
ordinary request per URL; more requests to that site only with its aggression 3, when asked for).

## Servers

| Server | What it does | Network | Secret |
|---|---|---|---|
| [duckduckgo](servers/duckduckgo) | web search through DuckDuckGo's HTML page, no API key | allowlist `html.duckduckgo.com:443` | - |
| [brave-search](servers/brave-search) | web and news search through the official Brave Search API | allowlist `api.search.brave.com:443` | `BRAVE_API_KEY` |
| [context7](servers/context7) | current documentation and code examples of libraries and frameworks from Upstash's Context7 service (Context7 MCP 4.5.0): `resolve-library-id` finds a library's Context7 ID, `query-docs` answers a question from its documentation. The library and the question go to context7.com, nothing else (no client name, session id, telemetry or sign-in prompt); works without a key, rate-limited | allowlist `context7.com:443` | optional: `CONTEXT7_API_KEY` |
| [searxng](servers/searxng) | web search through a SearXNG instance of yours (many engines at once), JSON API | the instance (`SEARXNG_URL`) | - |
| [telegram](servers/telegram) | a Telegram bot of yours through the official Bot API: read the messages sent to it, send and edit text messages, look up chats; `TELEGRAM_ALLOWED_CHATS` limits it to your chats (recommended) | allowlist `api.telegram.org:443` | `TELEGRAM_BOT_TOKEN` |
| [telegram-user](servers/telegram-user) | a Telegram user account through MTProto (Telethon) for investigating public channels and groups: resolve and search chats, chat info, invite links without joining, messages by id and date range, search, comments; media as metadata (downloads only into a mounted `/out`). Read-only: write tools only with `TELEGRAM_USER_WRITE=1`, optionally limited by `TELEGRAM_USER_ALLOWED_CHATS` | full (Telegram's data centres by IP; `--vpn PROFILE` recommended) | `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_SESSION` |
| [openosint](servers/openosint) | passive OSINT lookups with OpenOSINT 2.36.1's tool code: Google dork URLs, RDAP, WHOIS and DNS of a domain (SPF/DMARC posture), IP geolocation and ASN, GitHub profiles and commit e-mails, Pastebin dumps, geolocated GDELT news; with your keys Have I Been Pwned, VirusTotal (no URL submission), AbuseIPDB, IP2Location.io, Google results through Bright Data. Nothing touches the target; OpenOSINT's active tools, LLM agent and web UI are not in the image | full (registries' WHOIS and RDAP servers) | optional: `HIBP_API_KEY`, `VIRUSTOTAL_API_KEY`, `ABUSEIPDB_API_KEY`, `IP2LOCATION_API_KEY`, `IPINFO_TOKEN`, `GITHUB_TOKEN`, `BRIGHTDATA_API_KEY` |
| [signal](servers/signal) | a Signal account of yours as a linked device (signal-cli 0.14.9 with signal-mcp 1.43.3's message history): fetch messages, unread, conversations, full-text search of the history, contacts, groups (no invite links); attachments as metadata only. Read-only: `send_message`, `send_group_message`, `react_to_message` only with `SIGNAL_WRITE=1`, optionally limited by `SIGNAL_ALLOWED_RECIPIENTS`. The account lives in a folder mounted writable at `/data`; needs `--memory 1g --pids 256` | full (Signal's servers; `--vpn PROFILE` optional) | - (the account is the `/data` folder) |
| [whatsapp](servers/whatsapp) | a WhatsApp account linked as a device (edouard-claude/whatsapp-mcp, Rust, with a Go bridge on whatsmeow): chats, messages (pages, context, recent, full-text search), contacts, account status, media (downloaded into `/data`, size-capped), older history from the phone. Read-only: sending, reactions, edits, deletions, read receipts, presence, groups, number lookups, profiles and settings only with `WHATSAPP_WRITE=1`, files to send only from a mounted `/send`; no pairing or logout tools | full (WhatsApp's media hosts come from WhatsApp; `--vpn PROFILE` optional) | - (the linked device's keys live in the mounted `/data`) |
| [youtube](servers/youtube) | publish a video an agent made to your YouTube channel (YouTube Data API v3, our own server): resumable upload with retries (private by default, unlisted on request, public only with `YOUTUBE_ALLOW_PUBLIC=1`; the audience required, the synthetic-content disclosure false unless set; chapters into the description), thumbnail, captions (SRT/WebVTT), metadata changes of only the given fields, a list of your uploads. Four of its five tools **write** to the channel: have sandbox-ai ask for each call. Files only from a folder mounted read-only at `/upload`; the credentials only in the server's container | allowlist `oauth2.googleapis.com:443`, `www.googleapis.com:443` | `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN` |
| [bluesky](servers/bluesky) | post to your Bluesky account (AT Protocol, our own server): posts of up to 300 graphemes with link, mention and hashtag facets, languages, replies, threads of up to 10, up to 4 images with alt text (their EXIF and location removed) or a link card from what the agent gives (the site is never fetched), deleting only your own posts; your profile, posts and threads read-only. **Read-only unless `BLUESKY_WRITE=1`**, and then have sandbox-ai ask for each write. An app password only (the account password is refused), kept in the server's container; images only from a folder mounted read-only at `/upload` | allowlist `bsky.social:443` (your PDS), `public.api.bsky.app:443` | `BLUESKY_APP_PASSWORD` (with `BLUESKY_HANDLE`) |
| [youtube-transcript](servers/youtube-transcript) | the transcript (subtitles) of a public YouTube video for research (the tools of jkawamoto/mcp-youtube-transcript 0.8.3 on youtube-transcript-api 1.2.4, both reviewed in full, as an own server without yt-dlp): `get_transcript` (text) and `get_timed_transcript` (with timestamps) in pages within 24,000 characters, `get_available_languages`, `get_video_info` (title, channel, length, views, description). No account, no download; YouTube often blocks cloud and Tor addresses. Pending: not yet built and signed | allowlist `www.youtube.com:443` | - |
| [web-fetch](servers/web-fetch) | a public web page as readable text (no loopback or local-network targets) | full | - |
| [agentql](servers/agentql) | structured data from a public web page through AgentQL's hosted API (the tool of tinyfish-io/agentql-mcp 1.0.1, reviewed in full, as an own server): `extract-web-data` sends the URL and a description of the data to AgentQL, whose cloud browser loads the page and whose model returns the data as JSON; public http(s) URLs only, answers within 24,000 characters | allowlist `api.agentql.com:443` | `AGENTQL_API_KEY` |
| [osint-mcp](servers/osint-mcp) | domain and website OSINT from public sources, no API key (robyroro/osint-mcp 0.3.0): RDAP whois of domains and IPs, DNS, subdomains and certificate history from certificate transparency (crt.sh), Wayback snapshots, ASN and prefixes (RIPEstat), Shodan InternetDB, an email-security grade, TLS certificate and HTTP security headers; batch recon of up to ten domains, shared infrastructure, a site's page and legal pages. HTTP and TLS only to public addresses | full (registries' RDAP servers and the targets; `--vpn PROFILE` hides your address from them) | - |
| [playwright](servers/playwright) | a headless Chromium (Debian's) driven by Microsoft's Playwright MCP 0.0.83: navigate, accessibility snapshots, click, type, forms, tabs, JavaScript in the page, screenshots, console and network requests; fresh profile per connection, no `file:` URLs, no page-registered tools. Needs 2g memory, 512 processes and a 768m /tmp (sandbox-ai 0.1.94 applies them from the catalog; before: `--memory 2g --pids 512`) | full | - |
| [chrome-devtools](servers/chrome-devtools) | a headless Chromium (Debian's) driven by Google's Chrome DevTools MCP 1.12.0: pages and tabs, accessibility snapshots, click, type, forms, JavaScript in the page, screenshots and screencasts, console messages, network requests with their bodies, device/network/CPU emulation, performance traces with DevTools' insights, Lighthouse audits, heap snapshots; fresh profile per connection, no `file:` URLs, no page-defined tools or extensions; usage statistics, update check and CrUX lookups off. Reviewed completely (its own code line by line, the bundle rebuilt from source and compared with its upstream releases); signed once CI has built it. Needs 2g memory, 512 processes and a 768m /tmp (sandbox-ai 0.1.94 applies them from the catalog) | full | - |
| [gowitness](servers/gowitness) | screenshots of web pages with gowitness 3.2.2 (built with only its single-URL scan) and Debian's headless Chromium: the page as a PNG or JPEG image (window or full page) with what gowitness records - final URL, status, title, headers, TLS certificate, technologies (Wappalyzer), cookie names, console messages, the page's requests; one URL or up to 5. Public addresses only (`ALLOW_PRIVATE_TARGETS=1` adds the private ranges). Needs 2g memory, 512 processes and a 768m /tmp (sandbox-ai 0.1.94 applies them from the catalog) | full | - |
| [whatweb](servers/whatweb) | which software a web site runs: WhatWeb 0.6.4's 1,800+ plugins (CMS and versions, frameworks, servers, libraries, analytics) as JSON per URL visited; aggression 1 (one GET per URL, default) or 3 (more requests to the same site, only when asked; 4 not offered); plugin search. Public addresses only, every redirect checked (`ALLOW_PRIVATE_TARGETS=1` adds the private ranges) | full | - |
| [radare2](servers/radare2) | static analysis of a binary you hold, through radare2's own MCP server r2mcp: functions, imports, exports, sections, symbols, strings, disassembly, decompilation (r2's `pdc`), cross references. Reads the folder mounted read-only at `/work`; radare2's own sandbox allows no exec, no sockets and no writes | none | - |
| [capa](servers/capa) | what a binary can do: Mandiant capa with the pinned capa-rules names its capabilities, mapped to MITRE ATT&CK and MBC. Reads `/work` read-only, writes its report inside the container | none | - |
| [binwalk](servers/binwalk) | what is inside a firmware file: signature scan, extraction of embedded archives and file systems, entropy, hex dump. Reads `/work` read-only; extraction writes only into a `/out` you mount writable (else the container's own /tmp) | none | - |
| [jadx](servers/jadx) | Android and Java reverse engineering with jadx 1.5.6, headless (our own server on jadx's library): open an APK, DEX, JAR, AAR, AAB, XAPK, APKS, APKM, .class or .smali file and get its classes and packages, a class's outline, the Java source of a class or one method, smali, cross references (who calls a method, uses a field or class), a search of the decompiled code and of names, the decoded AndroidManifest.xml and resources. Answers in parts of 400 lines / 24,000 characters. Reads `/work` read-only, saves nothing; needs 2g memory, 256 processes, a 256m /tmp (sandbox-ai 0.1.94 applies them from the catalog) | none | - |
| [cfr](servers/cfr) | Java decompilation with CFR 0.152 (our own server): the classes of a JAR, WAR, EAR or ZIP (or a .class file), a class's outline from the class file, the Java source of a class or one method (renaming and anti-obfuscation on request), a search of the string constants of every class. Reads `/work` read-only, saves nothing; needs 1g memory. For APK/DEX and Kotlin use jadx | none | - |
| [memory](servers/memory) | the official MCP Knowledge Graph memory server (2.0.1): entities, observations and relations in one JSONL file, search by substring, open nodes, read the graph; for OSINT cases. The graph is `/data/memory.jsonl` in a folder you mount writable, one folder per case; no tool takes a path | none | - (the memory is the `/data` folder) |
| [sequential-thinking](servers/sequential-thinking) | the official MCP sequential-thinking server (2.0.0): one tool with which an agent writes its reasoning down as numbered thoughts that can revise or branch from earlier ones; kept in memory for one connection only, nothing read or written, thought logging off | none | - |
| [osv](servers/osv) | known vulnerabilities of open-source packages from the OSV database (osv.dev, no key; the tools of StacklokLabs/osv-mcp 0.1.4, reviewed in full, as an own server over stdio): `query_vulnerability` (a package version by name and ecosystem or purl, or a commit: id, CVE aliases, summary, severity, the versions that fix it), `query_vulnerabilities_batch` (up to 100 at once), `get_vulnerability` (one advisory in full); answers within 24,000 characters. Pending: not yet built and signed | allowlist `api.osv.dev:443` | - |
| [time](servers/time) | the official MCP time server (mcp-server-time 2026.10.28): `get_current_time` (date, time, weekday, DST of an IANA zone) and `convert_time` (a wall-clock time from one zone to another). Models do not know the current date and get zone arithmetic wrong; the local zone they are told is `LOCAL_TIMEZONE` (else UTC). Zone names checked, tools only. Pending: not yet built and signed | none | - |
| [exec](servers/exec) | shell commands for agents on small local models, in the project folder: a time limit per call (the whole process tree stopped on it), stdin empty and no terminal (CI=1, pagers, editors and prompts off), output cut to its start and end with the lines omitted counted, background jobs (status, wait, tail, stop), `run_tests` (only the failures of pytest, unittest, jest, vitest, go test, cargo test), `lint` (pyflakes, shellcheck, JSON, YAML). The project folder mounted writable at `/work`; needs 2g memory, 512 processes and a 512m /tmp (sandbox-ai 0.1.94 applies them from the catalog) | none | - |
| [tasks](servers/tasks) | a plan outside the model's context, for agents on small local models: goal, steps with their state and a note, notes of facts and mistakes not to repeat, `next_step` (the one step to work on now, with what it needs), progress; kept in `/work/.tasks` of the project (`PLAN.md` for you to read), locked, written atomically | none | - (the plan is in the project folder) |
| [code-search](servers/code-search) | find and read code by name, for agents on small local models (our own server): `find_definition` (exact matches first, similar names when there is none), `read_symbol` (one function or class with line numbers instead of the whole file), `outline` of a file, `find_references`, `find_text` (bounded, with the function each line is in, an offset to go on), `find_files`, `project_map`. Python exact (its own parser); JavaScript/TypeScript, Go, Rust, Java, C/C++ and shell approximate. Honours `.gitignore`, skips dependencies and build output; every answer bounded, every search time-limited. The project mounted read-only at `/work` (`/ref1`-`/ref3` beside it), nothing written | none | - (the project is the `/work` folder, read-only) |
| [engram](servers/engram) | Engram 3.6.0's persistent memory for coding agents: observations (decisions, bugs, conventions) in SQLite with full-text search, session summaries, context after a compaction, topic keys, conflict review, pins; only its MCP server (23 agent tools), no CLI, HTTP API, TUI, cloud or sync. The memory is a folder mounted writable at `/data`, one project per folder (`ENGRAM_PROJECT`, default `brain`) | none | - (the memory is the `/data` folder) |
| [files](servers/files) | reliable reads and writes of the agent's workspace, made for small local models that get file writes wrong (our own server): read in parts with the file's sha256, list, glob, search, stat, diff, checksum; atomic writes that never replace a file changed since it was read (`expected_sha256`), `write_markdown` that repairs what local models get wrong (a fence around everything, literal `\n`, CRLF, `#Heading`, an open code fence, ...) and lists each repair, exact edits, line inserts and deletes, strict patches, move, copy, delete into a trash. Every write answers lines added/removed and the new sha256. Only the folder mounted at `/work` is written (`/ref1`-`/ref3` read-only); no link followed out of a folder, none through on a write; `FILES_READONLY=1` | none | - (the workspace is the `/work` folder) |
| [filesystem](servers/filesystem) | the official MCP filesystem server (2.1.0) for agents on capable models that expect the reference tool set: read whole files (or head/tail), media as base64, several at once, write, `edit_file` with a git-style diff (`dryRun`), `create_directory`, list (with sizes), `directory_tree`, `move_file`, `search_files` (glob on names), `get_file_info`. Allowed are exactly the folders mounted at `/work` and `/ref1`-`/ref3`; MCP Roots are never used, so a client cannot widen them; links out of the folders refused. Which of files and filesystem: *files or filesystem?* under [Using them in sandbox-ai](#using-them-in-sandbox-ai) | none | - (the folders you mount) |

Looked at on 2026-11-17 and not admitted (the reasons: [docs/CANDIDATES.md](docs/CANDIDATES.md#the-candidates-security-review-of-2026-11-17);
their prepared folders stay in [`candidates/`](candidates)): **ghidra** (pyghidra-mcp 0.3.0 with Ghidra 12.2 and 101
Python packages), **codebase-memory** (a prebuilt 330 MB static binary; 236 MB of C in its repository), **browserbase** (a cloud
browser that sends pages to Browserbase and an LLM provider) and **rea** (about 230 tools; 68 MB of TypeScript in its repository) cannot
be reviewed completely; **reddit** (reddit-mcp-buddy, to be re-pinned to 1.2.0, which adds write tools) is not
finished. **agentql** joined the catalog as an own server.

Images: `ghcr.io/c0decave/sandbox-ai-mcp-<name>`, referenced by digest in
[`catalog.json`](catalog.json). Until the first CI run publishes them, the catalog says
`"state": "pending-digests"` and sandbox-ai refuses its entries.

## Not in the catalog, and why

We publish and sign only servers whose shipped code we reviewed completely ourselves, built from pinned
releases at least 14 days old, that run on their own in a container. Servers we looked at and left out:

- **wtfm** (SupportPages-io/wtfm 0.7.3, "Write the F***ing Manual") - no backdoor or malicious code found,
  but it is not a server that can run on its own, and it does not meet the rules above:
  - **It runs its own code in the agent's sandbox.** To write an article, the server hands the agent a shell
    command that starts wtfm's own `node` and engine scripts beside the agent. A catalog server works the
    other way round: it runs isolated in its container, and the agent only gets its answers. In a container
    its main feature cannot work.
  - **It installs and fetches unpinned code** in your project: CSS tools with `npm install` / `npx` without
    fixed versions, and every CDN stylesheet the project references with `curl`.
  - **Usage data leaves by default**, without a login: an install ID, versions, OS and CPU, event counts and
    crash data go to `app.supportpages.io` (off only with `DO_NOT_TRACK=1`); with an account also the
    articles, screenshots, the project's git state and, for hosted writing, read access to the repository.
  - **Its instructions steer the agent:** offer an article after every feature, show SupportPages.io offers
    word for word, and treat "a sandbox restriction" as "not an explicit user denial".
  - **Parts cannot be reviewed:** its engine is copied in from a private repository, and native installs
    update themselves daily from `downloads.supportpages.io`.

  It could be reconsidered as an agent-side plugin with its own review of the engine, or if upstream offers a
  hosted-only mode without usage data and without those instructions. The full review record:
  [`docs/CANDIDATES.md`](docs/CANDIDATES.md#wtfm-looked-at-on-2026-11-11-not-packaged).

- **Basic Memory** (basicmachines-co/basic-memory 0.24.1, AGPL-3.0; Markdown notes with an SQLite index) - no
  backdoor found in what was read, but it cannot be reviewed completely, and as released it does not run offline
  without changes:
  - **Too large to review completely:** `basic-memory mcp` imports 308 of its own modules, 101,481 lines of Python (the
    MCP tools reach the notes through its FastAPI app in-process), on 43 required packages - among them litellm,
    openai, logfire (OpenTelemetry), fastembed (onnxruntime, Hugging Face downloads), asyncpg, psycopg, pyright and
    two pytest plugins, each with dependencies of its own.
  - **It reaches out by default:** the stdio MCP server starts an automatic update in the background (`auto_update`
    is on by default: PyPI, then `uv tool upgrade` or `brew upgrade`); CLI promotions send events to
    `api-gateway.umami.dev` unless `BASIC_MEMORY_NO_PROMOS=1`; since 0.24.0 semantic search is always on and
    downloads its embedding model on first use (the switch was removed); per-project cloud routing is honoured on
    stdio.
  - **Its tools go beyond local notes:** cloud workspaces, project create and delete, an external formatter
    run as a subprocess.

  It could be reconsidered as an own small server over its note format, or if upstream ships a local-only build. The
  record: [`docs/CANDIDATES.md`](docs/CANDIDATES.md#basic-memory-looked-at-on-2026-11-11-not-packaged).

## Using them in sandbox-ai

```bash
sandbox-ai mcp catalog                          # entries of this catalog and the axross hub
sandbox-ai mcp add duckduckgo --network full    # pull by digest, write the definition
sandbox-ai mcp add brave-search --network full --env BRAVE_API_KEY
sandbox-ai mcp add context7 --network full --env CONTEXT7_API_KEY   # library docs; the key is optional
sandbox-ai mcp add agentql --network full --env AGENTQL_API_KEY       # URL and prompt go to AgentQL's cloud
sandbox-ai mcp add telegram --network full --env TELEGRAM_BOT_TOKEN --env TELEGRAM_ALLOWED_CHATS
sandbox-ai mcp add telegram-user --env TELEGRAM_API_ID --env TELEGRAM_API_HASH --env TELEGRAM_SESSION --vpn PROFILE
sandbox-ai mcp add openosint --network full --env VIRUSTOTAL_API_KEY   # keys optional, each named with --env
sandbox-ai mcp add whatsapp --network full --mount /data=~/whatsapp-data:rw   # read-only; linked once with wa-mcp pair
sandbox-ai mcp add youtube --network full --env YOUTUBE_CLIENT_ID --env YOUTUBE_CLIENT_SECRET \
  --env YOUTUBE_REFRESH_TOKEN --mount /upload=~/youtube-upload:ro   # writes to your channel: see below
sandbox-ai mcp add bluesky --network full --env BLUESKY_HANDLE=alice.bsky.social \
  --env BLUESKY_APP_PASSWORD@BLUESKY_ALICE --mount /upload=~/bluesky-upload:ro   # read-only; posting: see below
sandbox-ai mcp add radare2 --mount /work=~/samples:ro            # no network at all
sandbox-ai mcp add capa --mount /work=~/samples:ro
sandbox-ai mcp add binwalk --mount /work=~/firmware:ro --mount /out=~/extracted:rw
sandbox-ai mcp add jadx --mount /work=~/apks:ro                  # APK/DEX/JAR decompiler, no network
sandbox-ai mcp add cfr --mount /work=~/jars:ro                   # JAR/class decompiler, no network
sandbox-ai mcp add playwright --network full   # 0.1.94: the catalog's limits (before: --memory 2g --pids 512)
sandbox-ai mcp add chrome-devtools --network full   # DevTools on its own headless Chromium (once signed)
sandbox-ai mcp add gowitness --network full    # 0.1.94: the catalog's limits (2g, 512 processes, 768m /tmp)
sandbox-ai mcp add whatweb --network full      # --env ALLOW_PRIVATE_TARGETS=1 for your own LAN
sandbox-ai mcp add osint-mcp --network full                    # no key; --vpn PROFILE hides your address
sandbox-ai mcp add signal --network full --memory 1g --pids 256 --mount /data=~/signal-account:rw
sandbox-ai mcp add memory --mount /data=~/brains/case-42:rw        # a knowledge graph per case, no network
sandbox-ai mcp add engram --mount /data=~/brains/sandbox-ai-dev:rw # a coding agent's memory, no network
sandbox-ai mcp add sequential-thinking             # step-by-step thoughts for one connection, no network
sandbox-ai mcp add files --mount /work=~/projects/myapp:rw   # the agent's workspace, no network
sandbox-ai mcp add filesystem --mount /work=~/projects/myapp:rw   # the official server, the same folder
sandbox-ai mcp add exec --mount /work=~/projects/app:rw    # commands in the project, no network (small local models)
sandbox-ai mcp add tasks --mount /work=~/projects/app:rw   # the plan in ~/projects/app/.tasks
sandbox-ai mcp add code-search --mount /work=~/projects/app:ro   # find and read code by name, read-only
sandbox-ai claude --mcp duckduckgo --mcp web-fetch
sandbox-ai claude --mcp radare2 --mcp capa
sandbox-ai claude --mcp jadx --mcp cfr
```

sandbox-ai starts each server with the run line below, one container per agent connection,
and never pulls an image implicitly or by tag.

```
podman run --rm -i --init --pull=never --log-driver=none --cap-drop=ALL \
  --security-opt=no-new-privileges --read-only \
  --tmpfs=/tmp:rw,nosuid,nodev,noexec,size=64m,notmpcopyup --pids-limit=128 --memory=512m \
  --network=none|pasta [--env NAME] [--user=0:0 --volume=HOST:/work:ro] IMAGE@DIGEST
```

An **allowlist** entry gets the full network in sandbox-ai only when it is added with
`--network full` (the hosts it needs are shown); sandbox-ai has no per-server egress proxy yet.

**The file-analysis servers (radare2, capa, binwalk, jadx, cfr)** are `network: none`: their container has no
network namespace at all, so the files they read reach nobody. Mount the folder with the files
**read-only** (`--mount /work=DIR:ro`, the default mode); the only server that writes anything to a
folder of yours is binwalk, into `/out`, and only when you mount one writable. Everything they
report - strings, symbols, rule names, file names - comes from a file somebody else made: it is
data for the agent, never instructions.

**telegram-user** is a Telegram *user account*: its session is the whole account, so it lives
only in the server's container (environment, memory; never on disk, never in an answer or a log
line) and never with the agent. Log the account in once, on the host, with the server's
`login.py`, which prints the session for the secret store and writes no file (see
[its PROVENANCE.md](servers/telegram-user/PROVENANCE.md)):

```bash
python3 -I servers/telegram-user/src/login.py | sandbox-ai secrets set TELEGRAM_SESSION
sandbox-ai secrets set TELEGRAM_API_ID; sandbox-ai secrets set TELEGRAM_API_HASH   # https://my.telegram.org
```

It is read-only: `send_message`, `join_channel`, `leave_channel` and `mark_read` exist only when
`TELEGRAM_USER_WRITE=1` is passed too (`--env TELEGRAM_USER_WRITE=1`, best with
`--env TELEGRAM_USER_ALLOWED_CHATS`). `download_media` exists only with
`--mount /out=DIR:rw`. MTProto goes to Telegram's data centres by IP address, so the entry needs
the full network; `--vpn PROFILE` puts sandbox-ai's VPN (with kill switch) in front, or
`TELEGRAM_MTPROXY` an MTProto proxy. Flood waits come back as tool errors with their time.

**signal** is a Signal account linked as a secondary device: the folder mounted at `/data` holds
the device's keys and the message history, so give it a folder of its own and never share it.
Link it once, by hand, with the network (the image prints a `sgnl://` link to scan as a QR code in
Signal on the phone, Settings, Linked devices; see [its PROVENANCE.md](servers/signal/PROVENANCE.md)):

```bash
mkdir -m 700 ~/signal-account
podman run --rm -it --network=pasta --user=0:0 --cap-drop=ALL --security-opt=no-new-privileges --read-only \
  --tmpfs=/tmp:rw,noexec,nosuid,nodev,size=64m -v ~/signal-account:/data:rw \
  ghcr.io/c0decave/sandbox-ai-mcp-signal@DIGEST --link sandbox-ai
qrencode -t ansiutf8 'sgnl://linkdevice?...'     # the link it printed
```

It is read-only: the write tools exist only with `SIGNAL_WRITE=1` (`--env SIGNAL_WRITE=1`, best with
`--env SIGNAL_ALLOWED_RECIPIENTS`); no tool sends a file, a read receipt or changes the account.
Fetching messages sends Signal's delivery receipts; unread is tracked in the local history only.
signal-cli locks the account: one connection at a time.
**whatsapp** is a WhatsApp account linked as a device, like WhatsApp Web. Its keys and its message
database have to be written as it runs, so they live in a folder of yours mounted writable at `/data`
(not in a variable): whoever has that folder is the account. Keep it private, give it to this
server only, and link the device into it once, on the host, with the image's own `wa-mcp pair`
(the code is entered on the phone under Linked devices; see
[its PROVENANCE.md](servers/whatsapp/PROVENANCE.md)):

```bash
mkdir -m 700 ~/whatsapp-data
podman run --rm -it --cap-drop=ALL --security-opt=no-new-privileges --read-only --tmpfs=/tmp --user=0:0 \
  --volume ~/whatsapp-data:/data:rw IMAGE@DIGEST pair me --phone 4915123456789   # Ctrl-C once the history is in
```

It is read-only: the tools that send or change anything on WhatsApp exist only with
`WHATSAPP_WRITE=1` (`--env WHATSAPP_WRITE=1`), files to send only from a folder mounted at `/send`
(`--mount /send=DIR:ro`); pairing and logging out are never offered to the agent. One connection
at a time can use an account. Message texts, names and files come from other people.

**youtube** publishes to your YouTube channel without the agent ever holding your Google credentials: the OAuth
client and its refresh token are given to the server's container only (sandbox-ai's secrets), the server refreshes
its access token itself, and no answer or log line carries a token. Set it up once:

1. **A Google Cloud project** (https://console.cloud.google.com/, *New project*) with the **YouTube Data API v3**
   enabled (*APIs & Services*, *Library*).
2. **The OAuth consent screen** (*Google Auth Platform*): an app name and your e-mail, audience *External*, under
   *Data access* the scopes `.../auth/youtube.upload` and `.../auth/youtube.readonly` (and `.../auth/youtube.force-ssl`
   if you want captions and metadata changes). Then **publish the app** (*Audience*, *In production*): while it is in
   *Testing*, Google lets every refresh token expire after 7 days. For your own channel it need not be verified;
   Google's consent page then says "Google hasn't verified this app" (*Advanced*, continue).
3. **A client** (*Clients*, *Create client*, type **Desktop app**) and its JSON (*Download JSON*).
4. **The refresh token, on the host** (standard library only, nothing to install; it waits on 127.0.0.1 for Google's
   redirect and prints the token to the secret store, never to the terminal):

   ```bash
   CLIENT=~/Downloads/client_secret_XXXX.apps.googleusercontent.com.json
   python3 -I servers/youtube/src/authorize.py --client-secrets "$CLIENT" --open \
     | sandbox-ai secrets set YOUTUBE_REFRESH_TOKEN          # add --scopes upload,readonly,force-ssl for captions/updates
   python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["installed"]["client_id"])' "$CLIENT" \
     | sandbox-ai secrets set YOUTUBE_CLIENT_ID
   python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["installed"]["client_secret"])' "$CLIENT" \
     | sandbox-ai secrets set YOUTUBE_CLIENT_SECRET
   ```

   Sign in with the Google account of the channel. The token stays valid until you revoke it
   (https://myaccount.google.com/permissions). The image has the same script at `/opt/mcp/authorize.py`.
5. **The server**, with the folder it may upload from mounted read-only at `/upload` - a folder of its own that you
   fill with what may be published, or the agent's workspace folder itself (sandbox-ai refuses a folder *inside* a
   tree a sandbox can write):

   ```bash
   mkdir -p ~/youtube-upload
   sandbox-ai mcp add youtube --network full --env YOUTUBE_CLIENT_ID --env YOUTUBE_CLIENT_SECRET \
     --env YOUTUBE_REFRESH_TOKEN --mount /upload=~/youtube-upload:ro
   # optional: --env YOUTUBE_ALLOW_PUBLIC=1 (public videos), --env YOUTUBE_MAX_UPLOAD_MB=8192 (default 4096)
   sandbox-ai claude --mcp youtube --rules ~/.config/sandbox-ai/youtube.json
   ```

6. **Ask for every write.** `upload_video`, `set_thumbnail`, `upload_captions` and `update_metadata` change your
   channel; this ruleset makes sandbox-ai ask you for each call, with its arguments (answer *Allow once*: an approval
   counts for the run at most), allows the list and refuses anything else of the server:

   ```json
   {"version": 1, "mcp": [
     {"id": "youtube-list", "server": "youtube", "tool": "list_my_videos", "decision": "allow"},
     {"id": "youtube-writes", "server": "youtube", "decision": "ask", "reason": "publishes to or changes your YouTube channel",
      "tool": ["upload_video", "set_thumbnail", "upload_captions", "update_metadata"]},
     {"id": "youtube-rest", "server": "youtube", "tool": "*", "decision": "deny", "priority": 1000}
   ]}
   ```

What to know: **uploads stay private until Google audits your project** - every video a new API project uploads
through the API is locked to private whatever privacy was asked, until the project passes Google's audit
(https://support.google.com/youtube/contact/yt_api_form); the answer of `upload_video` says so too. **The quota** is
10,000 units a day per project: an upload costs about 1600 (about six a day), captions 400, a thumbnail or an update
50 (and 1 to read the video's privacy first), a list 3; it resets at midnight Pacific Time, and the error says so.
Videos are private by default; public needs `YOUTUBE_ALLOW_PUBLIC=1`, which also guards every change (metadata,
thumbnail, captions) to a video that is public already or scheduled to become public. `made_for_kids` must be given
with every upload; `contains_synthetic_media` (YouTube's disclosure of realistic AI-made or altered content) is false
unless the agent sets it - tell it to when your videos show such content. The scopes each tool needs:
`youtube.upload` for `upload_video` and `set_thumbnail` (which reads the video's privacy first with
`youtube.readonly`), `youtube.readonly` for `list_my_videos`, `youtube.force-ssl` for `upload_captions` and
`update_metadata` (broad: Google lets it edit and delete videos and comments - no tool of the server does, but ask
for it only if you need those two). Custom thumbnails need a channel verified by phone. Files come only from
`/upload`: no links, devices, hidden names, hard links or other users' files; every field is checked against
YouTube's limits first (title 100 characters, description 5000 bytes, tags 500 characters, chapters from 0:00, at
least 3 of 10 s). sandbox-ai gives the entry the full network (it cannot limit a server to hosts yet); the server
sends requests to `oauth2.googleapis.com` and `www.googleapis.com` only. See
[its PROVENANCE.md](servers/youtube/PROVENANCE.md).

**files** gives an agent - above all one on a small local model (OpenCode, Codex or Hermes with `--llm`) - file
tools that are hard to get wrong. Small models break files in typical ways: the whole Markdown document inside a
```` ```markdown ```` fence, `\n` written as two characters, the text sent as a JSON string, a stale copy written over
newer work, an edit that matches nothing or three places, line numbers from a read copied into the text. The server
makes each of these either impossible or visible: a whole-file write needs the `sha256` that `read_file` gave (or
`overwrite=true`), `edit_file` needs exactly one match (a whitespace-tolerant fallback only when it finds exactly one,
and it says so), `apply_patch` applies all hunks or none and shows the file's lines where one does not fit,
`write_markdown` repairs the Markdown mistakes and lists every repair (`dry_run=true` only shows them), and every write
answers lines added and removed and the new `sha256`, so the model can check its own work. Writes are atomic
(temporary file, `fsync`, `rename`), keep the file's permissions, line breaks and byte order mark, and refuse
binary-looking content; `delete` moves into `/work/.trash`. Mount the project the agent works in (the very folder;
sandbox-ai refuses a folder *inside* a tree a sandbox can write) and, if you like, read-only folders beside it:

```bash
sandbox-ai mcp add files --mount /work=~/projects/myapp:rw            # one entry per project:
sandbox-ai mcp add files --as files-docs --mount /work=~/projects/docs:rw --mount /ref1=~/reference:ro
# optional: --env FILES_READONLY (=1: reads only), --env FILES_MAX_BYTES (default 8M), --env FILES_TRASH (=0: no trash)
sandbox-ai opencode --llm ollama:qwen3 --mcp files --rules ~/.config/sandbox-ai/files.json   # your --llm server
```

Paths are relative to `/work` or absolute under `/work` and `/ref1`-`/ref3`; `..` is refused, a link is followed by
the read tools only while it stays inside its folder and by the write tools never, devices, pipes and sockets are
refused, and `.git` and `.trash` are not written. Recommended approvals - reads and edits allowed (the workspace is the
agent's anyway), deleting and moving asked for, anything else refused:

```json
{"version": 1, "mcp": [
  {"id": "files-reads", "server": "files", "decision": "allow",
   "tool": ["read_file", "list_dir", "glob", "search", "stat", "diff", "checksum"]},
  {"id": "files-writes", "server": "files", "decision": "allow",
   "tool": ["write_file", "write_markdown", "edit_file", "insert_lines", "delete_lines", "append_file", "apply_patch",
            "mkdir", "copy"]},
  {"id": "files-removes", "server": "files", "decision": "ask", "reason": "deletes or moves files of the workspace",
   "tool": ["delete", "move"]},
  {"id": "files-rest", "server": "files", "tool": "*", "decision": "deny", "priority": 1000}
]}
```

Tell a small model in its instructions to use `write_markdown` for `.md` files and `edit_file` for small changes, and to
read before it writes. See [its PROVENANCE.md](servers/files/PROVENANCE.md).

**files or filesystem?** Both work on the folders you mount and nothing else, without network. **files** is our own
server, made for agents on small local models: a whole-file write needs the `sha256` the file was read with, an edit
needs one exact match, `write_markdown` repairs what small models break, every write reports what changed, reads come
in parts with a hash, `delete` goes into a trash, and `/ref1`-`/ref3` are always read-only. **filesystem** is the
official reference server (`@modelcontextprotocol/server-filesystem`), for agents on capable models and clients
written against its tool names (`read_text_file`, `edit_file`, `directory_tree`, `search_files`, `move_file`,
`get_file_info`, ...): it overwrites without asking, edits by text match with a whitespace-tolerant fallback and
answers with a diff, reads whole files, returns images and audio as media content, and lists a folder as a JSON tree.
Its allowed directories are exactly the mounted folders: the image's entry takes the mount points of `/work` and
`/ref1`-`/ref3` from the container's mount table and never asks the client for MCP Roots (in 2.1.0 a client's roots
would replace them). A folder is read-only when you mount it `:ro`; for a read-only agent allow only its read tools.
Until it is re-pinned to 2.3.0 (from 2026-11-25) a read raced by someone swapping a folder for a link can land outside
the folders - inside its own container only, never in your files ([PROVENANCE.md](servers/filesystem/PROVENANCE.md),
finding 1).

```bash
sandbox-ai mcp add filesystem --mount /work=~/projects/myapp:rw --mount /ref1=~/reference:ro
```

Use **files** for OpenCode, Codex or Hermes on a local model, **filesystem** where a capable model or a client
expects the official tools; one of them per folder is enough.

**bluesky** posts to your Bluesky account without the agent ever holding your credentials: your handle and an
**app password** are given to the server's container only (sandbox-ai's secrets); the server signs in at your PDS
itself, keeps the session in memory, renews it there, and no answer or log line carries the password or a token.
Set it up once:

1. **An app password** (Bluesky: *Settings*, *Privacy and security*, *App passwords*, *Add App Password*; leave
   *Allow access to your direct messages* off). It looks like `xxxx-xxxx-xxxx-xxxx`. Never use the account
   password: the server refuses anything not shaped like an app password before sending it, and should Bluesky's
   session say it was the account password (full access) or an app password with access to direct messages, it
   ends that session and refuses. An app password can post, delete posts and change your profile and follows, but
   cannot change your e-mail or password or delete the account; revoke it there at any time.
2. **Keep it on the host**, in sandbox-ai's secret store (it asks for the value without showing it, or reads it
   from standard input; never from the command line):

   ```bash
   sandbox-ai secrets set BLUESKY_ALICE          # paste the app password at the prompt
   ```

3. **The server**, with your handle as a plain value, the secret by name, writing switched on, and the folder it may
   take images from mounted read-only at `/upload` (a folder of its own, or the agent's workspace folder itself;
   sandbox-ai refuses a folder *inside* a tree a sandbox can write):

   ```bash
   mkdir -p ~/bluesky-upload
   sandbox-ai mcp add bluesky --network full --env BLUESKY_HANDLE=alice.bsky.social \
     --env BLUESKY_APP_PASSWORD@BLUESKY_ALICE --env BLUESKY_WRITE=1 --mount /upload=~/bluesky-upload:ro
   # an account on its own PDS: --env BLUESKY_PDS=https://pds.example.org (default https://bsky.social)
   sandbox-ai claude --mcp bluesky --rules ~/.config/sandbox-ai/bluesky.json
   ```

   Without `BLUESKY_WRITE=1` the server is read-only: `post`, `thread` and `delete_post` are listed but refuse every
   call. `sandbox-ai mcp set bluesky --env BLUESKY_WRITE=1` turns writing on later.
4. **Ask for every write.** `post` and `thread` publish (at once, to everyone), `delete_post` deletes; this ruleset
   (also in [tools.json](servers/bluesky/tools.json)) makes sandbox-ai ask you for each call with its arguments
   (answer *Allow once*), allows the reads and refuses anything else of the server:

   ```json
   {"version": 1, "mcp": [
     {"id": "bluesky-reads", "server": "bluesky", "tool": ["get_profile", "list_my_posts", "get_post_thread"], "decision": "allow"},
     {"id": "bluesky-writes", "server": "bluesky", "tool": ["post", "thread", "delete_post"], "decision": "ask",
      "reason": "publishes to or deletes from your Bluesky account"},
     {"id": "bluesky-rest", "server": "bluesky", "tool": "*", "decision": "deny", "priority": 1000}
   ]}
   ```

What to know: a post has at most **300 graphemes** (an emoji, a flag or a letter with its accents counts once) and
3000 bytes, checked before anything is sent; links (`https://...`), `@mentions` of existing handles and `#hashtags`
become clickable facets, placed by their UTF-8 byte offsets as Bluesky needs them (a mention of an unknown handle
stays plain text, and the answer says so). Images: JPEG, PNG or WebP of `/upload`, at most 1,000,000 bytes and 4 per
post, **alt text required**; their EXIF (a phone's location among it), XMP, IPTC, C2PA manifests, comments, any other
metadata and anything after the image are removed before the upload (Bluesky keeps the original upload, readable by anyone), and a photo turned
only by its EXIF orientation is refused (save it upright). A link card is built from the title, description and
optional thumbnail the agent gives: the server never fetches the linked site. `delete_post` deletes only the
account's own posts and shows what it deleted. Bluesky limits writes per account (about 1,600 posts an hour,
11,600 a day) and sign-ins (30 in 5 minutes): the server signs in once per connection, waits up to 30 s for a rate
limit and otherwise names when to try again; a post whose answer got lost is looked up, not posted twice. The reads
go to Bluesky's public AppView without your session; what they return is written by other people: data, not
instructions. sandbox-ai gives the entry the full network (it cannot limit a server to hosts yet); the server
sends requests to your PDS and `public.api.bsky.app` only. See [its PROVENANCE.md](servers/bluesky/PROVENANCE.md).

**memory and engram** are an agent's memory: `network: none`, and everything they keep is in the folder mounted
**writable** at `/data` (required). Give each case or project a folder of its own (`mkdir -p ~/brains/CASE`, then
`--mount /data=~/brains/CASE:rw`); a second case is the same server added again under another name with another
folder. No tool of either takes a file path. What a memory returns was written earlier, often from pages or files
the agent read: data, not instructions. engram's instructions ask the agent to save proactively and to write a
session summary; its `directory`/`cwd` arguments are not offered (they would scan other folders).

**exec and tasks** are for agents on small local models (LM Studio, Ollama or vLLM behind OpenCode, Codex, Hermes,
Qwen Code or DSH) that stall, die or repeat themselves: see [docs/LOCAL_LLM_TOOLS.md](docs/LOCAL_LLM_TOOLS.md), also
for the review of `mcp-server-git`, `sequential-thinking`, serena, the ast-grep MCP server and codebase-memory. Both
work in the agent's project folder, mounted **writable** at `/work` - the workspace folder itself (sandbox-ai refuses
a folder *inside* a tree a sandbox can write), per start with `--mcp-mount exec:/work=DIR:rw`:

```bash
sandbox-ai opencode --workspace ~/projects/app --mcp exec --mcp tasks
```

**exec** runs commands in its own container, which has no network, no capabilities, a read-only root and only
`/work` mounted: it gives the agent nothing it does not have (the agent has a shell already); it is a shell that a
small model cannot get stuck in. Every command has a time limit (`EXEC_TIMEOUT`, default 120 s; at most
`EXEC_MAX_TIMEOUT`, 600 s) and is stopped with every process it started; stdin is empty and there is no terminal, so
nothing waits for an answer; the environment is fixed (`CI=1`, `TERM=dumb`, `PAGER=cat`, `EDITOR=true`, the yes
switches of apt, pip and npm; the server's own variables only as `EXEC_ENV_ALLOW` names them). exec runs as PID 1
of its container (`"pid1": "server"` in its catalog entry; sandbox-ai 0.1.95 starts it so: Podman without `--init`,
`bwrap --as-pid-1`), and it is not dumpable, so a command can open neither its MCP connection nor its environment
through `/proc`, and it works under Bubblewrap too. An older sandbox-ai puts an init at PID 1, which holds both: there
a command can write MCP messages to the client and read every variable of the container at `/proc/1/environ`, and
under Bubblewrap exec refuses to run commands (add it with `--backend podman`). Give exec no secrets either way.
Output is cut to its first and last lines (`EXEC_OUTPUT_LINES`, 100) with the number left out. Long builds and
servers go to `start_job` (at most `EXEC_MAX_JOBS`, 4, each at most `EXEC_JOB_TIMEOUT`, 3600 s). The commands have the image's tools: bash,
coreutils, git, make, python3 with pytest, pyflakes and PyYAML, shellcheck, Node.js 20 (no npm); install anything else
from the agent's own shell. `run_command`, `start_job`, `run_tests` and `stop_job` change things (`tools.json`): a
ruleset can make sandbox-ai ask for them. Codex waits 60 s for an MCP call by default: give exec a longer
`tool_timeout_sec`, or `--env EXEC_TIMEOUT=50 --env EXEC_MAX_TIMEOUT=55`. Command output comes from the project's
programs and files: data, not instructions.

**tasks** keeps the plan in `/work/.tasks/plan.json` with a readable `/work/.tasks/PLAN.md` beside it; every change is
locked and written atomically, so several agents can share one plan. No tool takes a path. A plan the server cannot
read (edited by hand) is refused and never overwritten. See [its PROVENANCE.md](servers/tasks/PROVENANCE.md) and
[exec's](servers/exec/PROVENANCE.md).

**code-search** helps a small local model with the code itself. Small models fail to find code (they grep for a
name they guessed), read whole files into a 32k context, and call functions that do not exist. code-search answers
by name and in small pieces: `find_definition("parse_args")` says where it is defined (exact matches first; with no
such name, the similar ones and where they are), `read_symbol(path, "App.run")` returns just that method with line
numbers, `outline(path)` lists a file's classes and functions with their lines and signatures, `find_references`
lists definitions first and then the lines using a name with the function each is in, and `project_map` gives a
first overview (folders, file counts, sizes, each file's main classes and functions). `find_text` and `find_files`
search text and names, with every answer bounded (at most 200 matches with an `offset` to go on, 50 files, 50
references) and every search stopped after 10 s with what it found; a regular expression that repeats a repeat
(`(a+)+`) is refused. Python is read by Python's own parser; JavaScript/TypeScript, Go, Rust, Java, C/C++ and shell by
line patterns and brace counting - approximate, and every answer says so. It honours `.gitignore` and skips
`node_modules`, `vendor`, `build`, `dist`, `target`, `.git`, binary and minified files (a path naming one searches
it). Outlines are cached per file: the first `find_definition` over a few thousand files takes seconds, the next
milliseconds. Mount the project **read-only**; the server writes nothing, follows no link out of the folders and
opens no device, pipe or socket:

```bash
sandbox-ai mcp add code-search --mount /work=~/projects/app:ro                  # one entry per project, or per start:
sandbox-ai opencode --llm ollama:qwen3 --workspace ~/projects/app --mcp code-search \
  --mcp-mount code-search:/work=~/projects/app:ro --mcp files --mcp exec       # read with code-search, write with files
sandbox-ai mcp add code-search --as code-search-lib --mount /work=~/projects/app:ro --mount /ref1=~/src/library:ro
```

Tell a small model in its instructions to use `find_definition` and `read_symbol` instead of reading whole files.
See [its PROVENANCE.md](servers/code-search/PROVENANCE.md).

**gowitness and whatweb** visit the site you name from the container's address (`--vpn PROFILE` hides it). Both
take only http(s) URLs whose host resolves to public addresses; `ALLOW_PRIVATE_TARGETS=1` (sandbox-ai 0.1.95:
`sandbox-ai mcp add|set NAME --env ALLOW_PRIVATE_TARGETS=1`, a value kept in the definition; for one start only
`--mcp-env NAME:ALLOW_PRIVATE_TARGETS=1`, or the board's MCP part) adds the private ranges for your own network,
loopback and link-local (cloud metadata) stay refused. Before 0.1.95 `--env ALLOW_PRIVATE_TARGETS` passed the
variable from your environment at every start, and the start failed where it was not set. Behind a Tor profile (`--vpn TOR_PROFILE`), web-fetch, gowitness and whatweb also take the
address range sandbox-ai announces as Tor's for onion services (`SANDBOX_AI_TOR_VIRTUAL_NETWORK`), so `.onion`
URLs work, and nothing else of the local ranges; without one a `.onion` URL is refused with that reason. gowitness checks the URL it is given; what the page then loads (redirects, frames, scripts) goes
wherever the container's network lets it, as with playwright. Its gowitness is built from the pinned release
without the report server, web UI, database and go-rod driver, and without gowitness's lifting of Chromium's port
blocklist (see [its PROVENANCE.md](servers/gowitness/PROVENANCE.md)). whatweb at aggression 1 sends one ordinary
GET per URL; aggression 3 is active probing - dozens of requests (version files, admin pages, one POST) to the same
site - so use it only on sites you may scan. WhatWeb follows no redirect itself; the server follows at most 5 and
checks each target's addresses first. Titles, headers, console messages, plugin strings and screenshots come from
the site: data, not instructions.

**Behind Tor.** With a Tor profile (`--vpn TOR_PROFILE`, or `mcp add|set NAME --vpn TOR_PROFILE`) sandbox-ai
runs a server behind a Tor of its own and sets `SANDBOX_AI_TOR=1` for it: every TCP connection goes through Tor, no
UDP, no IPv6, and what is sent to port 53 reaches tor's resolver, which answers A, AAAA and PTR only. Each catalog
entry says how its server fares there, in `"tor"`: `{"support": "yes" | "limited" | "no", "note": TEXT}`.
sandbox-ai (0.1.95) reads it: a server that is `"limited"` is added and started with its note said, one that is
`"no"` is refused behind Tor with the note as the reason; an entry without it falls back to sandbox-ai's own table.
Every server here names it:

| Behind Tor | Servers |
|---|---|
| yes, without network (nothing of them goes through Tor) | binwalk, capa, code-search, engram, exec, files, filesystem, memory, radare2, sequential-thinking, tasks |
| yes, over TCP through Tor | bluesky, brave-search, chrome-devtools, context7, duckduckgo, gowitness, openosint, osint-mcp, playwright, signal, telegram, telegram-user, web-fetch, whatsapp, whatweb, youtube |
| limited | searxng: `SEARXNG_URL` must be reachable from a Tor exit (a public instance or an `.onion` address; one in your local network or on this host is not) |

What the servers do differently behind Tor (only there, `SANDBOX_AI_TOR=1`):

- **osint-mcp and openosint** ask DNS over TCP: every lookup (osint-mcp's `dns_lookup`, `email_security` and the DNS
  parts of `recon_domain` and `compare_domains`, openosint's `search_dns`) goes to public resolvers - 1.1.1.1, 9.9.9.9,
  8.8.8.8, or the `nameserver` a `dns_lookup` call names - over TCP, through tor's TransPort and an exit like every other
  connection, with longer timeouts (10 s per resolver, 20 s per lookup). Through tor's resolver alone MX, TXT, NS,
  SOA, CAA and DMARC got no answer. The resolvers see the exit's address and the names asked, never yours;
  `/etc/resolv.conf` is not read there. The names HTTP and TLS connect to are still looked up through tor's resolver.
- **whatweb** waits longer: `--open-timeout` 30 s and `--read-timeout` 60 s instead of 10 and 20, a run 240 s instead of
  120 (aggression 3: 900 instead of 300). A circuit and the exit's connection come before the first byte.
- **web-fetch, gowitness and whatweb** take `.onion` URLs (see above); **searxng** a `.onion` instance.

No server here scans ports or needs UDP; a port scan through Tor's TransPort would see every port open (tor accepts
each connection before an exit tries it), which is why sandbox-ai refuses axross-mcp-hub's nmap behind Tor. Some
services refuse, rate-limit or challenge Tor exits; such a lookup then fails with that service's answer.

## Security model

- **Containment first:** no capabilities, no new privileges, read-only root, small `noexec`
  /tmp, process and memory limits, rootless podman, network only as the entry says, files only
  through mounted folders.
- **Pinned supply chain:** base images by digest, Debian packages by version, Python packages
  hash-locked (`requirements.txt`, wheels only, pip removed from the image), upstream sources by
  commit, release files by their published SHA-256, images by digest.
- **Audited code:** every tool argument is validated; requests go only where the server's
  purpose needs; answers are size-bounded. Each server's `PROVENANCE.md` has the audit.
- **CI:** every image is built, started with the run line above (without its secrets), its parsers
  run against recorded answers inside it, its smoke spec run (real calls and refused ones; a real
  call the upstream service rate-limits is retried, then skipped and named), scanned with Trivy (a
  CRITICAL vulnerability with a fix fails the build), pushed to GHCR with SBOM and provenance, and
  its digest reported. A server that fails stays out of that run's catalog; the others go in.

## Signed: works with sandbox-ai, under Podman and Bubblewrap

Every server comes in two forms of one build: the image (Podman) and its root
file system as an archive (Bubblewrap; a release asset named after its hash).
The build workflow runs both the way sandbox-ai runs them, with sandbox-ai's own
code: its `podman run` line, and its Bubblewrap runner (the archive checked
against its SHA-256, unpacked without trusting it, `bwrap --unshare-all`,
read-only root, no capabilities, cleared environment, slirp4netns without the
host's loopback for network). `catalog.json` pins the image digests,
`rootfs.json` the archives and the limits a server needs beyond sandbox-ai's
defaults (`"limits"`: memory, pids, cpus and tmp, the size of its /tmp; made by
`scripts/make_catalog.py` from the server's `smoke.json`, so `sandbox-ai mcp add`
applies what CI tested), a file of its own: axross reads the catalog and takes no
keys it does not know. Two keys of a catalog entry are sandbox-ai's own, which axross
leaves unread: `"tor"` (above, under *Behind Tor*) and `"pid1": "server"` (exec runs
as PID 1 of its container); the smoke runs with sandbox-ai's run lines start exec so
too (`scripts/smoke_test.py` takes `pid1` from the `server.json` beside the spec).

A release of the catalog is signed, on your machine, never in CI (every step: [docs/SIGNING.md](docs/SIGNING.md)):

```bash
ssh-keygen -t ed25519 -f ~/.config/sandbox-ai/mcp-signing-key -C sandbox-ai-mcp   # once
# its line, in sandbox-ai's sandbox/mcp-signers:
#   mcp@sandbox-ai namespaces="sandbox-ai-mcp" ssh-ed25519 AAAA... sandbox-ai-mcp
gh run download RUN -n catalog -D ci                  # catalog.json, rootfs.json, the smoke reports (ci/ci-digests)
cp ci/catalog.json ci/rootfs.json ci/digests.json .
python3 scripts/sign_catalog.py --key ~/.config/sandbox-ai/mcp-signing-key --reports ci
python3 scripts/sign_catalog.py --verify --signers ../sandbox-ai/sandbox/mcp-signers
git add catalog.json rootfs.json digests.json catalog.json.sig rootfs.json.sig
```

`sign_catalog.py` signs only when the catalog is current and every published
server passed both smoke runs (Podman and Bubblewrap, `tools/list` matching
`tools.json`) for exactly the digest and rootfs the files pin. sandbox-ai's
`mcp add` takes an entry only from a catalog whose signature verifies against
`sandbox/mcp-signers` (`--unsigned` for a catalog of your own).

## Repository layout

```
servers/<name>/       Dockerfile, server.json (catalog entry, with "tor"), src/server.py (none for radare2:
                      its MCP server is upstream's, built from source), requirements.*,
                      PROVENANCE.md, LICENSES/, smoke.json, tools.json
candidates/<name>/    prepared servers: Dockerfile with open pins, PROVENANCE.md, LICENSES/
catalog.json          generated by scripts/make_catalog.py from server.json + digests.json
rootfs.json           the Bubblewrap form of each published server (archive URL and SHA-256)
digests.json          digests of the last published build (null = not yet published)
scripts/              make_catalog.py, smoke_test.py, rootfs.py, sign_catalog.py, ci_results.py,
                      fixtures.py, lock.sh
tests/                catalog tests; tests of the own servers (natively, with recorded answers);
                      fixtures/ (recorded answers, and analysis-files.json: the binary smoke
                      inputs as base64, pinned by SHA-256)
```

## Maintenance

```
python3 -m unittest discover -s tests            # catalog tests (server tests skip without mcp)
pip install --require-hashes -r servers/duckduckgo/requirements.txt && python3 -m unittest discover -s tests
SANDBOX_AI_CHECKOUT=/path/to/sandbox-ai python3 -m unittest discover -s tests   # also against sandbox-ai itself
python3 scripts/make_catalog.py --check          # catalog current and fully pinned?
python3 scripts/make_catalog.py --check --allow-pending --sandbox-ai /path/to/sandbox-ai
                                                 # every entry as sandbox-ai's own reader takes it
python3 scripts/fixtures.py                      # write the binary smoke fixtures into tests/fixtures
scripts/lock.sh                                  # re-lock requirements.txt (in podman)
podman build -t local/sandbox-ai-mcp-duckduckgo servers/duckduckgo
python3 scripts/smoke_test.py --image local/sandbox-ai-mcp-duckduckgo --spec servers/duckduckgo/smoke.json
podman build -t local/sandbox-ai-mcp-radare2 servers/radare2
python3 scripts/smoke_test.py --image local/sandbox-ai-mcp-radare2 --spec servers/radare2/smoke.json \
  --var FIXTURES="$PWD/tests/fixtures"           # after scripts/fixtures.py
```

After a CI run on `main`, take its digests into the catalog:

```
scripts/make_catalog.py --ci-digests <downloaded digest-*.json> --write-digests
```

## Licence

MIT ([LICENSE](LICENSE)). telegram-user bundles Telethon (MIT) and its dependencies
(`servers/telegram-user/LICENSES`). The file-analysis images bundle third-party software under its
own licence: radare2 (LGPL-3.0-only, single plugins and dependencies GPL-3.0, Apache-2.0, BSD, MIT,
Zlib) with r2mcp (MIT); Mandiant capa and capa-rules (Apache-2.0) with the FuzzingLabs MCP wrapper
(MIT); Debian's binwalk and its extractors (MIT/Expat and their own licences) with that wrapper
(MIT). osint-mcp bundles osint-mcp (MIT) with dnspython (ISC) and tldextract (BSD-3-Clause).
playwright bundles Playwright MCP and Playwright (Apache-2.0) with Debian's Chromium (BSD-3-Clause
and others, `/usr/share/doc/chromium/copyright` in the image). openosint bundles 26 modules of OpenOSINT
(MIT) and python-whois (MIT). signal bundles six modules of
signal-mcp (MIT), signal-cli (GPL-3.0) with libsignal-client (AGPL-3.0) and its other jars, and
Eclipse Temurin (GPL-2.0 with Classpath Exception); `servers/signal/LICENSES/SOURCES.txt` names
their sources. See each server's `LICENSES/` and
(MIT). whatsapp bundles whatsapp-mcp (MIT) and its bridge, which links whatsmeow and go-util (MPL-2.0) and libsignal
(GPL-3.0): the bridge binary is GPL-3.0 (`servers/whatsapp/LICENSES`). playwright bundles Playwright MCP and Playwright (Apache-2.0) with Debian's Chromium (BSD-3-Clause
and others, `/usr/share/doc/chromium/copyright` in the image). See each server's `LICENSES/` and
`PROVENANCE.md`. Prepared servers bundle upstream software under its own licence
(Apache-2.0 for Chrome DevTools MCP, Browserbase MCP, pyghidra-mcp and Ghidra;
MIT for codebase-memory-mcp, Context7 MCP and REA; see `candidates/*/LICENSES`). memory bundles the official
Knowledge Graph memory server (Apache-2.0, older parts MIT), the MCP TypeScript SDK (Apache-2.0), zod (MIT) and
Node.js (MIT and others); engram bundles Engram and mcp-go (MIT) with modernc.org/sqlite and libc (BSD-3-Clause;
SQLite is public domain) and the other Go modules it links (their licences under
`/usr/share/doc/sandbox-ai-mcp-engram/modules` in the image). gowitness bundles gowitness 3.2.2 (GPL-3.0, built from
the pinned commit with the changes `servers/gowitness/Dockerfile` lists) with the Go modules it links (MIT, BSD,
Apache-2.0; their licences under `/usr/share/doc/sandbox-ai-mcp-gowitness/modules` in the image) and Debian's
Chromium (BSD-3-Clause and others). youtube, bluesky, exec and tasks are our own servers (MIT) on the MCP Python SDK and httpx (MIT, BSD-3-Clause); exec's image
has Debian's git (GPL-2.0), make (GPL-3.0), procps, pytest, pyflakes, PyYAML (MIT), shellcheck (GPL-3.0) and Node.js
(MIT and others) for its commands, each with its copyright file under `/usr/share/doc` in the image. whatweb bundles WhatWeb 0.6.4 (GPL-2.0-or-later; source: the pinned commit,
`servers/whatweb/LICENSES/SOURCES.txt`) with Debian's Ruby 3.3, addressable (Apache-2.0) and public_suffix (MIT).
