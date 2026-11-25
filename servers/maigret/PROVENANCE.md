# maigret - provenance and audit

| | |
|---|---|
| MCP server | this repository, `src/server.py` (MIT): our own username checker; it judges answers as maigret 0.6.6 does, on maigret's site database taken as data. Reviewed by construction (below); none of maigret's code ships or runs |
| Data | `maigret/resources/data.json` of maigret **0.6.6** (soxoj/maigret, MIT, `LICENSES/maigret-MIT.txt`; tag `v0.6.6` = commit `ba59c7e2a1828c963ff62f7f1ab4d7e35d95ec1e`): the PyPI wheel `maigret-0.6.6-py3-none-any.whl`, uploaded 2026-09-18 08:18 UTC (68 days before this review), SHA-256 `f382e7174d202a8002b2ac3ce3cde7c11900c506399dd6110f57b9256c4181c7`; the one file taken from it, 2,385,407 bytes, SHA-256 `ef6ca66efa174209c10205ff86f7e975b591128681710639fdc786ff05e662da` (checked where it is unpacked and again in the final image). 0.6.7 (2026-11-21) is too new |
| Python packages | `mcp==1.30.0` with httpx 0.28.1 and the rest of the shared lock, hash-locked in `requirements.txt` (byte-identical to servers/jadx's, reviewed there) |
| Debian packages | `tini=0.19.0-3+b8` (the init of the ENTRYPOINT), `python3=3.13.5-1`, `python3-venv=3.13.5-1` (purged after the venv is made), `ca-certificates=20250419+deb13u1` (the sites' TLS); build stage only: `unzip=6.0-29+deb13u1` |
| Base image | the `debian:trixie-slim` digest in `Dockerfile` |
| Network | full (the sites of the database, about 5,000 hosts: no allowlist can hold them); every host checked for public addresses before each request |

## Round 2's reasons (2026-11-18) and what became of them

Round 2 did not admit maigret (`docs/round2-reviews.md`): (1) the MCP wrapper `mcp-maigret` 1.0.18 runs maigret only
as `docker run soxoj/maigret:latest` (the Docker socket in the container, an unpinned image pulled at run time);
(2) maigret 0.6.6's dependency closure is 67 packages, ~889,000 lines, 50 native libraries (aiohttp, curl-cffi with
libcurl-impersonate, lxml, reportlab, Flask, ...) - not reviewable completely; (3) maigret updates its site database
itself (`db_updater.py`: `db_meta.json` from raw.githubusercontent.com every 24 h), fetches third-party "dynamic
rules" and site tokens (`activation.py`), bypasses Cloudflare, impersonates browsers' TLS and can send results to
OpenAI (`ai.py`). Round 2 named the way out: an own checker on the pinned `data.json`. That is this server:

| Reason | Here |
|---|---|
| (1) the wrapper, the Docker socket, `:latest` | no wrapper and no container in the container: one Python process, the MCP SDK lock |
| (2) the closure | none of it: the standard library, httpx (in the shared lock already) and the MCP SDK; `data.json` is read with `json.load` and used as values (URL templates formatted with `str.format` and the URL-encoded name, strings searched with `in`, `regexCheck` with `re.search` on a name of at most 64 characters) |
| (3) auto-update, activation, bypass, AI | none: the database changes only with a reviewed re-pin; the six entries with `activation` (Twitter, Vimeo, Weibo, WikimapiaSearch, OnlyFans, ProtonMail) and every entry whose headers carry a cookie, a token or an authorization (12 entries, 5 of them not left out for another reason: guest and bearer tokens, an app id, session and Cloudflare clearance cookies) are not checked; entries behind `tls_fingerprint`, Cloudflare's JS challenge or firewall, AWS WAF, a JS challenge or DDoS-Guard (201 entries, 165 of them not disabled anyway) are listed as not checked instead of being bypassed |

## data.json, reviewed as data (2026-11-25)

5,897 entries and 23 engines (templates such as XenForo, phpBB, Discourse, MediaWiki, Mastodon, which an entry names
and whose fields it takes; merged as maigret's `MaigretSite.update_from_engine` merges them). What an entry can make
this server do: one request to a URL formed from its `url`/`urlProbe`/`urlMain`/`urlSubpath` templates, GET (or HEAD,
or POST with its `requestPayload` as JSON or a form) with its own `headers` (minus those this server sets itself and
the sensitive ones above), then a verdict from its `checkType`, `presenseStrs`, `absenceStrs`, `errors` and
`ignore403`. Checked over all entries: every URL of an entry this server uses is http (807) or https (6,312) to a DNS
name - no IP literal, no `localhost`, `.local`, `.onion` or `.i2p` (the 7 dns, 4 tor and 1 i2p entries are left out);
22 request methods are GET or POST; 7 payloads are GraphQL or form fields that take the name; no entry runs code
(maigret has no code in its data; `activation` names maigret's own functions and is not used). 694 entries are disabled
by maigret itself; 25 are for other identifiers than usernames (24 of them not disabled). That leaves **4,990** entries this server checks; the
others are listed by `list_sites` with the reason.

## This server

**Tools (4):** `search_username(username, limit=100, offset=0, tags="")` - the checkable sites ranked by maigret's
`alexaRank` (unranked ones after, in file order), `limit` (at most 200) from `offset`, optionally only those with one
of the given tags; answers the found accounts with their URLs and tags, the number not found, the sites that could not
be checked grouped by why (bot protection, 403, rate limit, a site's own error page, a timeout, no connection), the
sites not reached in time, and the next offset. `check_site(username, site)` - one site: the verdict and why, the URL
asked, the HTTP status, the check type and marks. `list_sites(tag, name_filter, offset)` and `list_tags()` - the
database, offline (nothing is sent).

**Verdicts** (maigret 0.6.6 `checking.process_site_result` and `error_detection.detect_error_page`, re-implemented and
compared): the site's `errors` markers, then maigret's 23 common bot-protection and block pages (`errors.py`
`COMMON_ERRORS`, copied; checked equal to 0.6.6's with Python's `ast` on 2026-11-25), then 403 (unless `ignore403`),
401, 429, 999 and 5xx mean "could not be checked"; else `status_code` 2xx = found; `message` = found when a presence
mark is there (or there are none) and no absence mark; `response_url` = a 2xx without following redirects. A name
with non-ASCII letters must appear in the page when the entry has no presence marks (maigret's #2633). Left out of
maigret's: its random User-Agent (one fixed browser string), mirrors appended after the ranked slice, retries, the
extraction of further identifiers from pages and the recursive search with them.

**Requests:** the username must be 1-64 letters, digits, `_`, `.`, `-` (starting with a letter or digit) and is
URL-encoded with no safe characters, so nothing of it becomes a path or a query; before each request (and each redirect,
followed by this server, at most 5) the host is resolved and refused unless every address is public (no loopback,
private, link-local, CGNAT, multicast or reserved address, IPv4-mapped included); a resolver answering differently a
moment later (DNS rebinding) is not ruled out. httpx with certificates verified, `trust_env` (sandbox-ai's allowlist
proxy when it sets one), 6 s to connect, 12 s per site, at most 2 MiB of a page read (decoded chunk by chunk, so a
compressed page cannot unpack beyond it), 24 requests at a time, 45 s per call (clients give up after 60 s). Nothing is
written; no cookie is kept between requests to different sites (each answer's cookies stay in the client of one call).

**Bounds:** answers within 24,000 characters (the list of found accounts cut with a note); `list_sites` 200 entries a
part.

## Verification (2026-11-25, here; no Podman in this sandbox)

The server from `src/server.py` with the shared lock and 0.6.6's `data.json` (SHA-256 checked), over stdio:
- `smoke.json`: initialize, tools/list = tools.json (4), 11 of 11 calls passed - `list_tags` (4,990 of 5,897
  checkable), `list_sites` (GitHub #10; Twitter "needs maigret's activation"; tag coding), `check_site` GitHub
  `blue` found (HTTP 200 from api.github.com) and `noonewouldeverusethis7` not found (HTTP 404), `search_username`
  with tag coding, and the refusals (a path as name, an unknown tag, an excluded site, an unknown site).
- `tests/test_maigret.py`: 19 tests passed (the real-database test runs inside the image only): engines, exclusions,
  the three check types, error pages, the host check, requests against a stand-in transport (probe URLs, POST
  payloads, redirects checked hop by hop, endless redirects, the 2 MiB bound), the deadline, paging, the offline tools.
- This sandbox's egress filter resets TLS handshakes made through anyio (httpx's async client) to most hosts (GitLab,
  gitea.com; plain sockets reach them), so a broad `search_username` here shows "could not connect" for most sites:
  only GitHub's answers could be judged live here.

**Only CI or a real host can prove:** `search_username` over the real top sites (how many answer, how many block a
CI or Tor address), the smoke run under Podman and Bubblewrap with full network, and the run behind a Tor profile.
