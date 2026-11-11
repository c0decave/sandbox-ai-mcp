# openosint - provenance and audit

| | |
|---|---|
| Upstream | OpenOSINT/OpenOSINT **2.36.1** (MIT, `LICENSES/openosint-MIT.txt`), tag `v2.36.1`, commit `998497328cc69e71f11e4bd8d343428cf9d4bda5` (2026-10-19, GitHub release and PyPI `openosint 2.36.1` of 2026-10-19; the PyPI wheel, SHA-256 `685eca4adbd7ff9150e8061ff0c2914e1098e5c270dd54091d4c9cbb6a69c024`, has the package files of the tag byte for byte) |
| In the image | only the 26 reviewed modules of `openosint/`, fetched at that commit and checked file by file against `openosint-files.sha256` (4,436 lines) |
| MCP server | this repository, `src/server.py` (MIT, `LICENSES/axross-mcp-hub-MIT.txt`): the tools, argument checks, key redaction, size bound; OpenOSINT's own `mcp_server.py` is not in the image |
| Python packages | `mcp==1.30.0`, `aiohttp==3.14.5`, `dnspython==2.9.0`, `python-dotenv==1.2.4`, `python-whois==0.9.6` (MIT, `LICENSES/python-whois-MIT.txt`), `requests==2.34.2` and their dependencies, hash-locked in `requirements.txt` (wheels only) |
| Debian packages | `python3=3.13.5-1`, `ca-certificates=20250419+deb13u1`; build stage `git`, `ca-certificates` (not in the final image) |
| Base image | the `debian:trixie-slim` digest in `Dockerfile` |

**Upstream:** https://github.com/OpenOSINT/OpenOSINT (the server mcpservers.org lists as "openosint";
mcpservers.org itself was not reachable from where this was prepared, so the match is by name: the
GitHub organisation, the PyPI project `openosint` and its `openosint-mcp` entry point). Created
2026-05-06, 1,921 stars, 297 forks, 25 open issues, not archived, pushed 2026-11-05; 48 releases
from v1.0.0 (2026-05-08) to v2.38.0 (2026-11-05), several a week. Maintainer Tommaso Bertocchi
(GitHub `SonoTommy`, commits as `JustSouichi`): 495 of the 507 commits up to v2.36.1; the release
commit is not signed. A commercial support offer exists (`COMMERCIAL.md`); the code is MIT for any
use. `DISCLAIMER.md`: for authorised security research, journalism and investigating your own
assets; not for stalking, harassment or unauthorised surveillance.

**Pinning rule:** 2.36.1 (2026-10-19, 23 days old on 2026-11-11) is the newest release published on
or before 2026-10-28 (`docs/CANDIDATES.md`); 2.37.0 (2026-11-02), 2.37.1 and 2.38.0 (both
2026-11-05) are too new. `requirements.txt` was locked with uv's `--exclude-newer
2026-10-29T00:00:00Z` (uv 0.13.7 on the host, the flags of `scripts/lock.sh`; the container of
`lock.sh` was not available): every locked file was uploaded on or before 2026-10-28. The newest are
`pydantic-settings` 2.16.2 and `tzdata` 2026.6 (2026-10-28), `sse-starlette` 3.6.0 (2026-10-25),
`starlette` 1.10.0 and `multidict` 7.2.1 (2026-10-24), `certifi` 2026.10.23, `pycparser` 3.12
(2026-10-22), `python-dateutil` 3.0.0 (2026-10-21, published by its maintainer `pganssle` with
trusted publishing, GitHub release of the same day), `pydantic` 2.14.1, `pydantic-core` 2.50.1 and
`aiohttp` 3.14.5 (2026-10-11), `dnspython` 2.9.0 (2026-10-09); `python-whois` 0.9.6 is of
2025-10-07, `requests` 2.34.2 of 2026-05-14. The MCP stack (`mcp` 1.30.0 and its dependencies) is
the one the other servers here use, some of its dependencies a few days newer than their lock of
2026-11-06 (cut-off 2026-10-23).

**What the newer releases change (not in this image):** 2.37.0 adds CLI subcommands, an Agent
Skill and a Claude Code plugin ("no tool behaviour changed"). 2.37.1 stops the automatic copy of a
package-root `.env` into `~/.openosint/config.env` (a security hardening of `openosint/env.py`, which
this image does not contain: nothing here reads or writes a `.env` or `config.env`). 2.38.0 adds
`openosint setup brightdata`, per-placement referral links and a shared Bright Data error
classifier (`search_dorks_live` and `search_footprint` stop at the first account-level failure
instead of sending every query). None is a security fix for what this image runs.

## What is reviewed, and what is in the image

The whole MCP path of OpenOSINT 2.36.1 was read line by line: `openosint/mcp_server.py` (775
lines, to know what upstream offers; not shipped) and every module the passive tools import,
which are exactly the files of `openosint-files.sha256` (lines):

`__init__.py` 8, `brightdata.py` 18, `config_store.py` 142, `json_output.py` 50, `paths.py` 12,
`proxy.py` 141, `regexes.py` 56, `settings_catalog.py` 229, `tool_policy.py` 336,
`tools/__init__.py` 0, `tools/exceptions.py` 22, `tools/gdelt_gkg.py` 545,
`tools/generate_dorks.py` 70, `tools/search_abuseipdb.py` 106, `tools/search_breach.py` 119,
`tools/search_dns.py` 430, `tools/search_dorks_live.py` 311, `tools/search_footprint.py` 280,
`tools/search_gdelt_geo.py` 344, `tools/search_github.py` 174, `tools/search_ip.py` 110,
`tools/search_ip2location.py` 179, `tools/search_paste.py` 104, `tools/search_rdap.py` 224,
`tools/search_virustotal.py` 312, `tools/search_whois.py` 114 - 4,436 lines.

Nothing else of the package is in the image: the Dockerfile's build stage fetches the commit, checks
every listed file's SHA-256 and copies only those into the venv's `site-packages/openosint` (no
`pip install openosint`, so no build backend, entry point or install hook of OpenOSINT runs, and
its 21 declared dependencies - `anthropic`, `fastapi`, `uvicorn`, `asyncpg`, `reportlab`,
`authlib`, `rich`, `prompt_toolkit`, ... - are not installed). Left out with them: the CLI and REPL,
the LLM agent (`agent.py`, `multi_target.py`, `pivot.py`, playbooks), the web and cloud servers, the
web UI (`openosint/web/`, which carries 1.4 MB of minified third-party JavaScript - maplibre,
cytoscape, alpine.js - that could not be reviewed), the graph (`openosint/graph/`), the exposure
scanner, `env.py` (the `.env` and `config.env` loader), `utils.py` (`run_subprocess`) and the active
tools. A scan of the whole 2.36.1 wheel (22,023 lines of Python) for `exec`/`eval`/`compile`,
`pickle`/`marshal`, `base64` decoding, `__import__`/`importlib` and dynamic imports from URLs,
`subprocess`/`os.system`, bidi or zero-width characters and over-long lines found none of them in
the shipped modules; outside them only `asyncio.create_subprocess_exec` in `utils.py`, called by the
four active tools that run `sherlock`, `holehe`, `sublist3r` and `phoneinfoga` (not shipped). The
hosts named anywhere in the package are the services below plus the LLM providers (Anthropic,
OpenAI-compatible, Ollama), `api.ipify.org` (the exposure scanner's own address) and map tiles of
the web UI - none of them in shipped code. No telemetry, update check or download of code exists in
the shipped modules.

**Findings in the shipped modules** (none is a backdoor; each is handled by `src/server.py`):

1. **Keys in tool results.** `search_ip` (`?token=`) and `search_ip2location` (`?key=`) put the key
   into the request URL, and a failed request's text (`requests`' `Max retries exceeded with url:
   /?key=...`) is returned as the tool result: the agent would see the key. The server replaces the
   value of every key variable with `[redacted]` in every answer and every log line (tested).
2. **Arguments in request paths.** `search_ip`, `search_paste`, `search_breach`, `search_github` and
   `search_virustotal` put the argument unescaped into the URL path (`https://ipinfo.io/{ip}/json`,
   `.../breachedaccount/{email}`, `/users/{query}`, `/domains/{domain}`), so `../`, `?`, `#` or `%2F`
   could steer the request to another path of the same service, with the key attached. The host
   cannot change. The server accepts only well-formed values first: a domain name, a public IP
   address, an e-mail address without `%`, a username/e-mail charset for pastes, a GitHub query
   without `/ \ ? # %`.
3. **VirusTotal URL submission** (`search_virustotal` with an `http(s)://` target) makes VirusTotal
   fetch the URL and publishes it to its community. Upstream gates it behind active mode; the server
   additionally refuses URLs before the call.
4. **Active mode by environment.** `OPENOSINT_ALLOW_ACTIVE=1` would enable the DKIM selector probes
   of `search_dns` and VirusTotal URL submission. The server removes the variable and replaces
   `tool_policy.env_allows_active` before any tool runs (tested: active mode stays off with the
   variable set).
5. **Third-party text unbounded.** Results are plain text of unbounded length in places (WHOIS name
   server lists, VirusTotal categories). The server cuts every answer at 64 KiB and strips the
   GeoJSON block `search_gdelt_geo` appends for OpenOSINT's web globe (headlines and article URLs);
   what remains is place names and counts.
6. **Errors as results.** Upstream returns failures as ordinary text (`Scan error: ...`); the server
   turns them into MCP errors (`isError`), so a client can tell a failed lookup from a finding.
7. **Missing-key messages** name OpenOSINT's web UI and `config.env`; the server replaces that line
   with how to pass the variable to this server. They also carry upstream's links to get a key,
   including a Bright Data referral link (`get.brightdata.com/...?utm_source=github`; OpenOSINT says
   it earns a commission) and IP2Location's sponsored link - as upstream ships them.
8. `config_store.write_config` and `migrate_legacy_env` can write files, but only `env.py` (not
   shipped) calls them; the shipped code calls only `config_path()` for the text of the
   missing-key message. Nothing in the image writes a file.

## Audit of the tools

| Tool | What it does | Contacts | Key (env) |
|---|---|---|---|
| `generate_dorks` | 12 Google search URLs for a target, built locally | nothing | - |
| `search_rdap` | registrar, created/expires, name servers, status of a domain; registrant fields are never read | `data.iana.org:443` (bootstrap, cached 1 h), then the TLD's RDAP base URL from it (e.g. `rdap.verisign.com`) | - |
| `search_whois` | WHOIS of a domain (`python-whois`, its own socket client, not the `whois` command) | port 43: the TLD's server (built-in table or `whois.iana.org`), then the "Whois Server:" referral of that answer | - |
| `search_dns` | A, AAAA, MX, NS, TXT, CNAME, SOA, `_dmarc` TXT; SPF/DMARC warnings; no DKIM probes | the container's resolver (UDP/TCP 53) | - |
| `search_ip` | geolocation, ASN, hostname of a public IP | `ipinfo.io:443` | `IPINFO_TOKEN` (optional) |
| `search_github` | a user's profile, 10 repositories, e-mails of up to 15 commits; else a user search | `api.github.com:443` (up to 5 requests) | `GITHUB_TOKEN` (optional) |
| `search_paste` | Pastebin IDs and dates of dumps naming the query | `psbdmp.ws:443` | - |
| `search_gdelt_geo` | geolocated news places of the last hour(s), matched locally against the query (the query is not sent) | `data.gdeltproject.org:443` (`lastupdate.txt`, then GKG files of ~8 MB, https only, no redirects, size caps) | - |
| `search_breach` | breaches of an e-mail address | `haveibeenpwned.com:443` | `HIBP_API_KEY` |
| `search_virustotal` | VirusTotal data on an IPv4 address, a domain or a file hash | `www.virustotal.com:443` | `VIRUSTOTAL_API_KEY` |
| `search_abuseipdb` | abuse confidence score and reports of an IP | `api.abuseipdb.com:443` | `ABUSEIPDB_API_KEY` |
| `search_ip2location` | geolocation, ISP, proxy/VPN/Tor/datacenter flags of an IP | `api.ip2location.io:443` | `IP2LOCATION_API_KEY` |
| `search_dorks_live` | Google results of 5 dorks (5 billed requests) | `api.brightdata.com:443`, which queries Google | `BRIGHTDATA_API_KEY`, `BRIGHTDATA_SERP_ZONE` |
| `search_footprint` | 1-3 entity-aware Google queries (billed) | `api.brightdata.com:443`, which queries Google | `BRIGHTDATA_API_KEY`, `BRIGHTDATA_SERP_ZONE` |

Every tool also takes `json_output` (OpenOSINT's JSON envelope of the text lines).

**Not offered:** the active tools `search_username` (sherlock), `search_email` (holehe, probes
sign-up and reset forms and may notify the account owner), `search_domain` (sublist3r),
`search_phone` (phoneinfoga) and `scrape_url` (fetches any URL through Bright Data's unblocker) - their
modules and binaries are not in the image; `investigate_multi` (an Anthropic-driven agent that sends
the targets to the LLM provider and writes report files); `graph_export`, `graph_neighbors`,
`graph_review_candidates` (need the `followthemoney` extra and a local graph database that would not
outlive the container); `search_shodan` and `search_censys` (their SDKs are optional extras:
`shodan` 1.31.0 is an sdist of 2023 that would have to be built, `censys` brings `rich`,
`argcomplete` and `backoff` - more third-party code to review; they can be added later).

**Network:** `full`. The set of hosts is not fixed: RDAP base URLs come from IANA's bootstrap file,
WHOIS goes to whichever server the registry names (port 43), and DNS goes through the resolver. The
fixed hosts are those of the table. Nothing contacts the target itself: DNS answers come through
the resolver, RDAP and WHOIS from the registries. What a lookup names (a domain, an address, an
e-mail address, a person's name for the Bright Data tools) goes to the service of that tool, and
the service sees the container's address: put `--vpn PROFILE` in front where that matters.

**Secrets:** only as environment variables, all optional (the keyless tools work without any):
`HIBP_API_KEY`, `VIRUSTOTAL_API_KEY`, `ABUSEIPDB_API_KEY`, `IP2LOCATION_API_KEY`, `IPINFO_TOKEN`,
`GITHUB_TOKEN`, `BRIGHTDATA_API_KEY` (and the non-secret `BRIGHTDATA_SERP_ZONE`). Each is sent
only to its service: as a header (`hibp-api-key`, `x-apikey`, `Key`, `Authorization: Bearer`) or,
for ipinfo.io and IP2Location, as a query parameter. `aiohttp` (GitHub) drops `Authorization` on a
redirect to another origin; `requests` keeps custom headers (`hibp-api-key`, `x-apikey`) on a
redirect - only the service itself could send one, since the path is fixed by the argument checks.
Their values are redacted from answers and logs. Use a `GITHUB_TOKEN` without scopes, not a
working token.

**Files and commands:** nothing is written (the container's root is read-only; `/tmp` stays unused),
no `.env` or config file is read, no subprocess is started (`python-whois` can run the `whois`
command, only with `command=True`, which OpenOSINT does not pass; the image has no `whois` binary).

**Prompt injection:** every answer is third-party data, much of it written by whoever owns the
thing looked up: WHOIS and RDAP fields (registrar, organisation, e-mail), DNS TXT records (up to 5
of 100 characters, SPF and DMARC of 120), reverse-DNS hostnames and ISP names, GitHub names, bios,
locations and repository descriptions, VirusTotal file names and categories, Google titles and
snippets (200 characters each), GDELT place names. The server's instructions and the catalog notes
say so; answers are bounded to 64 KiB.

**Limits and residual risks:**

- A WHOIS referral is chosen by the registry's answer: a hostile registry could name any host,
  including an address of the container's network; only the domain name is sent there, on port 43.
  WHOIS and RDAP answers are read without a size cap (`python-whois` reads to the end of the
  stream; `requests` reads the RDAP JSON whole): a hostile server can exhaust the container's
  memory (512 MiB), which ends that container, nothing else. `search_whois` gives up after 15 s; the
  thread reading may go on until its socket times out (10 s per read).
- `search_gdelt_geo` keeps the newest GKG file and backfills older ones on a background thread,
  one download at a time (24 MB compressed and 96 MB decompressed caps per file, 30,000 articles
  at most). The window is `OPENOSINT_GDELT_WINDOW_HOURS`, 1 hour by default here (4 files of about
  8 MB; upstream's default is 6), since every agent connection is a new container.
- `search_dorks_live` and `search_footprint` cost money per query (Bright Data bills each); the
  server allows 5 and 1-3 per call, as upstream.
- psbdmp.ws, the paste search, is a third-party index whose availability was not checked.
- The tools can collect personal data (breach membership, e-mails from commits, a person's search
  footprint). OpenOSINT's disclaimer applies: authorised investigations only.

**Dependencies, their risky parts:** `python-whois` 0.9.6 was read where it acts: `__init__.py`
(the `subprocess.Popen` of the `whois` command only with `command=True`; IP input resolved with
`gethostbyaddr`, which the server never passes) and `whois.py`'s `NICClient` (plain sockets to port
43, `SOCKS` proxy from the environment, no other I/O); `parser.py` is regular expressions over the
answer, with no `eval`/`exec`. `dnspython` (`ctypes` only in `win32util.py`, not used on Linux),
`python-dotenv` (its `cli.py` can run a command, an entry point nothing here calls; the image needs
the package only because `config_store.py` imports `dotenv_values`), `requests`, `urllib3`,
`aiohttp` (`base64` only for basic auth, multipart and websocket keys), `yarl`, `multidict`,
`frozenlist`, `propcache`, `aiosignal`, `aiohappyeyeballs`, `charset-normalizer`, `idna`, `certifi`,
`six` (its `exec` is the Python 2 shim), `python-dateutil` (`ctypes` only for Windows time zones):
scanned for `subprocess`, `exec`/`eval`, `pickle`, `base64`, `ctypes`, `__import__` and code
fetched at run time; nothing beyond the uses named. `aiohttp`, `multidict`, `yarl`, `propcache`,
`frozenlist` (and from the MCP stack `pydantic-core`, `cryptography`, `rpds-py`, `cffi`) come as
compiled wheels built by their projects' CI, like in the other servers here.

**Base, user, build:** the pinned `debian:trixie-slim`, Debian's Python 3.13; the venv's `pip` is
removed and the venv tooling purged; the build stage's `git` is not in the final image; the server
runs as uid 10001 with `python -I`.

**Tested:** natively with the locked requirements and the 26 modules installed into a Python 3.13
venv (`tests/test_own_servers.py` `test_openosint`: the 14 tools of `tools.json`, 13 refused
arguments, a key-required answer, active mode staying off with `OPENOSINT_ALLOW_ACTIVE=1`, an
active tool not offered, the GeoJSON block stripped, the 64 KiB bound, key redaction in an answer
and a log line). CI runs the same test inside the image without network, then `smoke.json`
(the offline `generate_dorks`, a live `search_rdap` of example.com through IANA and Verisign, and
four refused calls). Not built here (no container engine); the live RDAP call could not be tried
from where this was prepared (no route to `data.iana.org`).
