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
| [searxng](servers/searxng) | web search through a SearXNG instance of yours (many engines at once), JSON API | the instance (`SEARXNG_URL`) | - |
| [telegram](servers/telegram) | a Telegram bot of yours through the official Bot API: read the messages sent to it, send and edit text messages, look up chats; `TELEGRAM_ALLOWED_CHATS` limits it to your chats (recommended) | allowlist `api.telegram.org:443` | `TELEGRAM_BOT_TOKEN` |
| [telegram-user](servers/telegram-user) | a Telegram user account through MTProto (Telethon) for investigating public channels and groups: resolve and search chats, chat info, invite links without joining, messages by id and date range, search, comments; media as metadata (downloads only into a mounted `/out`). Read-only: write tools only with `TELEGRAM_USER_WRITE=1`, optionally limited by `TELEGRAM_USER_ALLOWED_CHATS` | full (Telegram's data centres by IP; `--vpn PROFILE` recommended) | `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_SESSION` |
| [openosint](servers/openosint) | passive OSINT lookups with OpenOSINT 2.36.1's tool code: Google dork URLs, RDAP, WHOIS and DNS of a domain (SPF/DMARC posture), IP geolocation and ASN, GitHub profiles and commit e-mails, Pastebin dumps, geolocated GDELT news; with your keys Have I Been Pwned, VirusTotal (no URL submission), AbuseIPDB, IP2Location.io, Google results through Bright Data. Nothing touches the target; OpenOSINT's active tools, LLM agent and web UI are not in the image | full (registries' WHOIS and RDAP servers) | optional: `HIBP_API_KEY`, `VIRUSTOTAL_API_KEY`, `ABUSEIPDB_API_KEY`, `IP2LOCATION_API_KEY`, `IPINFO_TOKEN`, `GITHUB_TOKEN`, `BRIGHTDATA_API_KEY` |
| [signal](servers/signal) | a Signal account of yours as a linked device (signal-cli 0.14.9 with signal-mcp 1.43.3's message history): fetch messages, unread, conversations, full-text search of the history, contacts, groups (no invite links); attachments as metadata only. Read-only: `send_message`, `send_group_message`, `react_to_message` only with `SIGNAL_WRITE=1`, optionally limited by `SIGNAL_ALLOWED_RECIPIENTS`. The account lives in a folder mounted writable at `/data`; needs `--memory 1g --pids 256` | full (Signal's servers; `--vpn PROFILE` optional) | - (the account is the `/data` folder) |
| [whatsapp](servers/whatsapp) | a WhatsApp account linked as a device (edouard-claude/whatsapp-mcp, Rust, with a Go bridge on whatsmeow): chats, messages (pages, context, recent, full-text search), contacts, account status, media (downloaded into `/data`, size-capped), older history from the phone. Read-only: sending, reactions, edits, deletions, read receipts, presence, groups, number lookups, profiles and settings only with `WHATSAPP_WRITE=1`, files to send only from a mounted `/send`; no pairing or logout tools | full (WhatsApp's media hosts come from WhatsApp; `--vpn PROFILE` optional) | - (the linked device's keys live in the mounted `/data`) |
| [youtube](servers/youtube) | publish a video an agent made to your YouTube channel (YouTube Data API v3, our own server): resumable upload with retries (private by default, unlisted on request, public only with `YOUTUBE_ALLOW_PUBLIC=1`; the audience required, the synthetic-content disclosure false unless set; chapters into the description), thumbnail, captions (SRT/WebVTT), metadata changes of only the given fields, a list of your uploads. Four of its five tools **write** to the channel: have sandbox-ai ask for each call. Files only from a folder mounted read-only at `/upload`; the credentials only in the server's container | allowlist `oauth2.googleapis.com:443`, `www.googleapis.com:443` | `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN` |
| [web-fetch](servers/web-fetch) | a public web page as readable text (no loopback or local-network targets) | full | - |
| [osint-mcp](servers/osint-mcp) | domain and website OSINT from public sources, no API key (robyroro/osint-mcp 0.3.0): RDAP whois of domains and IPs, DNS, subdomains and certificate history from certificate transparency (crt.sh), Wayback snapshots, ASN and prefixes (RIPEstat), Shodan InternetDB, an email-security grade, TLS certificate and HTTP security headers; batch recon of up to ten domains, shared infrastructure, a site's page and legal pages. HTTP and TLS only to public addresses | full (registries' RDAP servers and the targets; `--vpn PROFILE` hides your address from them) | - |
| [playwright](servers/playwright) | a headless Chromium (Debian's) driven by Microsoft's Playwright MCP 0.0.83: navigate, accessibility snapshots, click, type, forms, tabs, JavaScript in the page, screenshots, console and network requests; fresh profile per connection, no `file:` URLs, no page-registered tools. Needs 2g memory, 512 processes and a 768m /tmp (sandbox-ai 0.1.94 applies them from the catalog; before: `--memory 2g --pids 512`) | full | - |
| [gowitness](servers/gowitness) | screenshots of web pages with gowitness 3.2.2 (built with only its single-URL scan) and Debian's headless Chromium: the page as a PNG or JPEG image (window or full page) with what gowitness records - final URL, status, title, headers, TLS certificate, technologies (Wappalyzer), cookie names, console messages, the page's requests; one URL or up to 5. Public addresses only (`ALLOW_PRIVATE_TARGETS=1` adds the private ranges). Needs 2g memory, 512 processes and a 768m /tmp (sandbox-ai 0.1.94 applies them from the catalog) | full | - |
| [whatweb](servers/whatweb) | which software a web site runs: WhatWeb 0.6.4's 1,800+ plugins (CMS and versions, frameworks, servers, libraries, analytics) as JSON per URL visited; aggression 1 (one GET per URL, default) or 3 (more requests to the same site, only when asked; 4 not offered); plugin search. Public addresses only, every redirect checked (`ALLOW_PRIVATE_TARGETS=1` adds the private ranges) | full | - |
| [radare2](servers/radare2) | static analysis of a binary you hold, through radare2's own MCP server r2mcp: functions, imports, exports, sections, symbols, strings, disassembly, decompilation (r2's `pdc`), cross references. Reads the folder mounted read-only at `/work`; radare2's own sandbox allows no exec, no sockets and no writes | none | - |
| [capa](servers/capa) | what a binary can do: Mandiant capa with the pinned capa-rules names its capabilities, mapped to MITRE ATT&CK and MBC. Reads `/work` read-only, writes its report inside the container | none | - |
| [binwalk](servers/binwalk) | what is inside a firmware file: signature scan, extraction of embedded archives and file systems, entropy, hex dump. Reads `/work` read-only; extraction writes only into a `/out` you mount writable (else the container's own /tmp) | none | - |
| [memory](servers/memory) | the official MCP Knowledge Graph memory server (2.0.1): entities, observations and relations in one JSONL file, search by substring, open nodes, read the graph; for OSINT cases. The graph is `/data/memory.jsonl` in a folder you mount writable, one folder per case; no tool takes a path | none | - (the memory is the `/data` folder) |
| [engram](servers/engram) | Engram 3.6.0's persistent memory for coding agents: observations (decisions, bugs, conventions) in SQLite with full-text search, session summaries, context after a compaction, topic keys, conflict review, pins; only its MCP server (23 agent tools), no CLI, HTTP API, TUI, cloud or sync. The memory is a folder mounted writable at `/data`, one project per folder (`ENGRAM_PROJECT`, default `brain`) | none | - (the memory is the `/data` folder) |

Prepared, not yet built ([`candidates/`](candidates), see
[docs/CANDIDATES.md](docs/CANDIDATES.md)): **ghidra** (pyghidra-mcp 0.3.0, Ghidra 12.2 headless),
**chrome-devtools**
(Chrome DevTools MCP 1.12.0 with Debian's Chromium), **codebase-memory** (codebase-memory-mcp
0.12.1, a code graph of a mounted repository), **context7** (Context7 MCP 4.5.0, library
documentation), **browserbase** (Browserbase MCP 3.0.0, a cloud browser) and **rea** (REA 6.8.0,
static reverse engineering without native engines). All are audited; their Dockerfiles refuse to
build while a pin is open (ghidra: Debian versions; chrome-devtools: the npm
package's integrity; rea: Node.js from nodejs.org). codebase-memory, context7 and browserbase
have every pin set but have not been built yet.

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
sandbox-ai mcp add telegram --network full --env TELEGRAM_BOT_TOKEN --env TELEGRAM_ALLOWED_CHATS
sandbox-ai mcp add telegram-user --env TELEGRAM_API_ID --env TELEGRAM_API_HASH --env TELEGRAM_SESSION --vpn PROFILE
sandbox-ai mcp add openosint --network full --env VIRUSTOTAL_API_KEY   # keys optional, each named with --env
sandbox-ai mcp add whatsapp --network full --mount /data=~/whatsapp-data:rw   # read-only; linked once with wa-mcp pair
sandbox-ai mcp add youtube --network full --env YOUTUBE_CLIENT_ID --env YOUTUBE_CLIENT_SECRET \
  --env YOUTUBE_REFRESH_TOKEN --mount /upload=~/youtube-upload:ro   # writes to your channel: see below
sandbox-ai mcp add radare2 --mount /work=~/samples:ro            # no network at all
sandbox-ai mcp add capa --mount /work=~/samples:ro
sandbox-ai mcp add binwalk --mount /work=~/firmware:ro --mount /out=~/extracted:rw
sandbox-ai mcp add playwright --network full   # 0.1.94: the catalog's limits (before: --memory 2g --pids 512)
sandbox-ai mcp add gowitness --network full    # 0.1.94: the catalog's limits (2g, 512 processes, 768m /tmp)
sandbox-ai mcp add whatweb --network full      # --env ALLOW_PRIVATE_TARGETS for your own LAN
sandbox-ai mcp add osint-mcp --network full                    # no key; --vpn PROFILE hides your address
sandbox-ai mcp add signal --network full --memory 1g --pids 256 --mount /data=~/signal-account:rw
sandbox-ai mcp add memory --mount /data=~/brains/case-42:rw        # a knowledge graph per case, no network
sandbox-ai mcp add engram --mount /data=~/brains/sandbox-ai-dev:rw # a coding agent's memory, no network
sandbox-ai claude --mcp duckduckgo --mcp web-fetch
sandbox-ai claude --mcp radare2 --mcp capa
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

**The file-analysis servers (radare2, capa, binwalk)** are `network: none`: their container has no
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
`TELEGRAM_USER_WRITE=1` is passed too (`--env TELEGRAM_USER_WRITE`, best with
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

It is read-only: the write tools exist only with `SIGNAL_WRITE=1` (`--env SIGNAL_WRITE`, best with
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
`WHATSAPP_WRITE=1` (`--env WHATSAPP_WRITE`), files to send only from a folder mounted at `/send`
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
   # optional: --env YOUTUBE_ALLOW_PUBLIC (=1: public videos), --env YOUTUBE_MAX_UPLOAD_MB (default 4096)
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

**memory and engram** are an agent's memory: `network: none`, and everything they keep is in the folder mounted
**writable** at `/data` (required). Give each case or project a folder of its own (`mkdir -p ~/brains/CASE`, then
`--mount /data=~/brains/CASE:rw`); a second case is the same server added again under another name with another
folder. No tool of either takes a file path. What a memory returns was written earlier, often from pages or files
the agent read: data, not instructions. engram's instructions ask the agent to save proactively and to write a
session summary; its `directory`/`cwd` arguments are not offered (they would scan other folders).

**gowitness and whatweb** visit the site you name from the container's address (`--vpn PROFILE` hides it). Both
take only http(s) URLs whose host resolves to public addresses; `ALLOW_PRIVATE_TARGETS=1` (`--env
ALLOW_PRIVATE_TARGETS`) adds the private ranges for your own network, loopback and link-local (cloud metadata)
stay refused. Behind a Tor profile (`--vpn TOR_PROFILE`), web-fetch, gowitness and whatweb also take the
address range sandbox-ai announces as Tor's for onion services (`SANDBOX_AI_TOR_VIRTUAL_NETWORK`), so `.onion`
URLs work, and nothing else of the local ranges; without one a `.onion` URL is refused with that reason. gowitness checks the URL it is given; what the page then loads (redirects, frames, scripts) goes
wherever the container's network lets it, as with playwright. Its gowitness is built from the pinned release
without the report server, web UI, database and go-rod driver, and without gowitness's lifting of Chromium's port
blocklist (see [its PROVENANCE.md](servers/gowitness/PROVENANCE.md)). whatweb at aggression 1 sends one ordinary
GET per URL; aggression 3 is active probing - dozens of requests (version files, admin pages, one POST) to the same
site - so use it only on sites you may scan. WhatWeb follows no redirect itself; the server follows at most 5 and
checks each target's addresses first. Titles, headers, console messages, plugin strings and screenshots come from
the site: data, not instructions.

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
keys it does not know.

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
servers/<name>/       Dockerfile, server.json (catalog entry), src/server.py (none for radare2:
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
Chromium (BSD-3-Clause and others). youtube is our own server (MIT) on the MCP Python SDK and httpx (MIT, BSD-3-Clause). whatweb bundles WhatWeb 0.6.4 (GPL-2.0-or-later; source: the pinned commit,
`servers/whatweb/LICENSES/SOURCES.txt`) with Debian's Ruby 3.3, addressable (Apache-2.0) and public_suffix (MIT).
