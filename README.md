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
network it was not given, and nothing here probes anyone.

## Servers

| Server | What it does | Network | Secret |
|---|---|---|---|
| [duckduckgo](servers/duckduckgo) | web search through DuckDuckGo's HTML page, no API key | allowlist `html.duckduckgo.com:443` | - |
| [brave-search](servers/brave-search) | web and news search through the official Brave Search API | allowlist `api.search.brave.com:443` | `BRAVE_API_KEY` |
| [searxng](servers/searxng) | web search through a SearXNG instance of yours (many engines at once), JSON API | the instance (`SEARXNG_URL`) | - |
| [telegram](servers/telegram) | a Telegram bot of yours through the official Bot API: read the messages sent to it, send and edit text messages, look up chats; `TELEGRAM_ALLOWED_CHATS` limits it to your chats (recommended) | allowlist `api.telegram.org:443` | `TELEGRAM_BOT_TOKEN` |
| [telegram-user](servers/telegram-user) | a Telegram user account through MTProto (Telethon) for investigating public channels and groups: resolve and search chats, chat info, invite links without joining, messages by id and date range, search, comments; media as metadata (downloads only into a mounted `/out`). Read-only: write tools only with `TELEGRAM_USER_WRITE=1`, optionally limited by `TELEGRAM_USER_ALLOWED_CHATS` | full (Telegram's data centres by IP; `--vpn PROFILE` recommended) | `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_SESSION` |
| [openosint](servers/openosint) | passive OSINT lookups with OpenOSINT 2.36.1's tool code: Google dork URLs, RDAP, WHOIS and DNS of a domain (SPF/DMARC posture), IP geolocation and ASN, GitHub profiles and commit e-mails, Pastebin dumps, geolocated GDELT news; with your keys Have I Been Pwned, VirusTotal (no URL submission), AbuseIPDB, IP2Location.io, Google results through Bright Data. Nothing touches the target; OpenOSINT's active tools, LLM agent and web UI are not in the image | full (registries' WHOIS and RDAP servers) | optional: `HIBP_API_KEY`, `VIRUSTOTAL_API_KEY`, `ABUSEIPDB_API_KEY`, `IP2LOCATION_API_KEY`, `IPINFO_TOKEN`, `GITHUB_TOKEN`, `BRIGHTDATA_API_KEY` |
| [web-fetch](servers/web-fetch) | a public web page as readable text (no loopback or local-network targets) | full | - |
| [playwright](servers/playwright) | a headless Chromium (Debian's) driven by Microsoft's Playwright MCP 0.0.83: navigate, accessibility snapshots, click, type, forms, tabs, JavaScript in the page, screenshots, console and network requests; fresh profile per connection, no `file:` URLs, no page-registered tools. Needs `--memory 2g --pids 512` | full | - |
| [radare2](servers/radare2) | static analysis of a binary you hold, through radare2's own MCP server r2mcp: functions, imports, exports, sections, symbols, strings, disassembly, decompilation (r2's `pdc`), cross references. Reads the folder mounted read-only at `/work`; radare2's own sandbox allows no exec, no sockets and no writes | none | - |
| [capa](servers/capa) | what a binary can do: Mandiant capa with the pinned capa-rules names its capabilities, mapped to MITRE ATT&CK and MBC. Reads `/work` read-only, writes its report inside the container | none | - |
| [binwalk](servers/binwalk) | what is inside a firmware file: signature scan, extraction of embedded archives and file systems, entropy, hex dump. Reads `/work` read-only; extraction writes only into a `/out` you mount writable (else the container's own /tmp) | none | - |

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

## Using them in sandbox-ai

```bash
sandbox-ai mcp catalog                          # entries of this catalog and the axross hub
sandbox-ai mcp add duckduckgo --network full    # pull by digest, write the definition
sandbox-ai mcp add brave-search --network full --env BRAVE_API_KEY
sandbox-ai mcp add telegram --network full --env TELEGRAM_BOT_TOKEN --env TELEGRAM_ALLOWED_CHATS
sandbox-ai mcp add telegram-user --env TELEGRAM_API_ID --env TELEGRAM_API_HASH --env TELEGRAM_SESSION --vpn PROFILE
sandbox-ai mcp add openosint --network full --env VIRUSTOTAL_API_KEY   # keys optional, each named with --env
sandbox-ai mcp add radare2 --mount /work=~/samples:ro            # no network at all
sandbox-ai mcp add capa --mount /work=~/samples:ro
sandbox-ai mcp add binwalk --mount /work=~/firmware:ro --mount /out=~/extracted:rw
sandbox-ai mcp add playwright --network full --memory 2g --pids 512   # Chromium needs more
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
`rootfs.json` the archives (a file of its own: axross reads the catalog and
takes no keys it does not know).

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
(MIT). playwright bundles Playwright MCP and Playwright (Apache-2.0) with Debian's Chromium (BSD-3-Clause
and others, `/usr/share/doc/chromium/copyright` in the image). openosint bundles 26 modules of OpenOSINT
(MIT) and python-whois (MIT). See each server's `LICENSES/` and
`PROVENANCE.md`. Prepared servers bundle upstream software under its own licence
(Apache-2.0 for Chrome DevTools MCP, Browserbase MCP, pyghidra-mcp and Ghidra;
MIT for codebase-memory-mcp, Context7 MCP and REA; see `candidates/*/LICENSES`).
