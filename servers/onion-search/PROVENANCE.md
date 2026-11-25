# onion-search - provenance and audit

| | |
|---|---|
| MCP server | this repository, `src/server.py` (MIT), written for this repository and reviewed by construction (below); no upstream code |
| Engines (data, not code) | **Ahmia** at `juhanurmihxlp77nkq76byazcldy2hlmovfu2epvl5ankdibsot4csyd.onion` (http): the address its operators publish in their own site's source, ahmia/ahmia-site (BSD-3-Clause), `ahmia/templates/index_tor.html` and `core.html` ("Right onion address starts with juhanurmihxlp77 and ends with 4csyd.onion"), branch master pushed 2026-10-08, read 2026-11-25. **DuckDuckGo** at `duckduckgogg42xjoc72x3sjasowoarfbgcmvfimaftt6twagswzczad.onion` (https, DuckDuckGo's certificate for that name): the address servers/web-fetch's Tor tests use, DuckDuckGo's published onion service |
| Python packages | `mcp==1.30.0` with httpx 0.28.1 and the rest of the shared lock, hash-locked in `requirements.txt` (byte-identical to servers/jadx's, reviewed there) |
| Debian packages | `tini=0.19.0-3+b8`, `python3=3.13.5-1`, `python3-venv=3.13.5-1` (purged after the venv is made), `ca-certificates=20250419+deb13u1` (pip's download while building) |
| Base image | the `debian:trixie-slim` digest in `Dockerfile` |
| Network | full, used only behind a Tor profile: the two onion hosts above and nothing else |

## Why our own server

The registry pass (`research-llm/mcp-registry-research-2026-11.md`, gap "onion search") found no upstream fit to
admit: farbodghasemlu/darkweb-mcp v1.0.1 (0 stars, one author, 6 weeks old) speaks SOCKS to `127.0.0.1:9050` and starts
its own `tor` process, and publishes MCP resources; spignelon/ddg-onion-mcp has no release (13 days old, GPL-3.0);
neutron42-jp/tor-mcp and the onion OSINT servers were unverified. sandbox-ai already routes a server through Tor
(`--vpn TOR_PROFILE`: transparent TCP through Tor, `.onion` names resolved by Tor into its virtual range,
`SANDBOX_AI_TOR=1` and `SANDBOX_AI_TOR_VIRTUAL_NETWORK` in the server's environment) and web-fetch already fetches
`.onion` pages; only search was missing. This server is that search: two tools, no SOCKS, no own `tor`, no resources.

## This server

**Tools (2):** `search_onion(query, engine="ahmia"|"duckduckgo"|"both", max_results=20)` returns data -
`{query, engines: [{engine, results: [{title, url, onion, snippet, last_seen}], count, total?, note?, error?}], note}`.
Ahmia: its front page is fetched first for the search form's hidden token (a field whose name and value change every
minute; Ahmia redirects a search without it to its front page - `ahmia/views.py`, `TorResultsView.get`), then
`/search/?q=...&<token>`; results parsed from `tor_results.html`'s markup, the target taken from Ahmia's redirect link
(`redirect_url`), kept only when it is an http(s) `.onion` URL. DuckDuckGo: `POST /html/` on its onion service, parsed
as servers/duckduckgo parses html.duckduckgo.com (sponsored results and DuckDuckGo's own links dropped). Titles at most
300 characters, snippets 1,000, 50 results per engine; queries 1-100 characters and 10 words (Ahmia's own limits).
`onion_status(check=false)` - behind Tor or not, Tor's range, the engines and their addresses; `check=true` fetches each
engine's front page through Tor and times it.

**Tor only, fail closed:** without `SANDBOX_AI_TOR=1` every search is refused before any name is looked up (an onion
name never goes to a resolver outside Tor); without a valid `SANDBOX_AI_TOR_VIRTUAL_NETWORK` (an IPv4 network in
10.0.0.0/8) too. Behind Tor, before each request and each redirect hop: the host must be one of the two engines' onion
hosts, and every address its name resolves to must lie in Tor's range - so a connection can only be Tor's mapping to
that onion service. httpx with `trust_env=False` (no proxy variables), certificates verified (DuckDuckGo), at most 3
redirects (each checked), 4 MiB per page, 30 s to connect (onion circuits are slow), 50 s per engine; both engines in
parallel, one failing does not hide the other's results. A Tor Browser User-Agent. Nothing is written.

**What is sent:** the search words, to Ahmia and/or DuckDuckGo, over Tor (from a Tor exit's circuit, not the user's
address). No result is fetched.

## Verification (2026-11-25, here; no Podman and no Tor in this sandbox)

- `tests/test_onion_search.py`: 11 tests passed - refusal without Tor (no lookup, nothing sent), refusal with a
  missing or invalid range, Ahmia's token taken from the fixture front page and sent with the query, Ahmia's results
  (an injected instruction in a snippet stays data; a `javascript:` link dropped), DuckDuckGo's results from the
  recorded page of servers/duckduckgo, a name resolving outside Tor's range never connected, a redirect to another
  host refused, one engine failing beside the other, the status check. The pages are the fixtures
  `tests/fixtures/ahmia-front.html` and `ahmia-results.html` (rendered by hand from Ahmia's templates) and
  `duckduckgo.html`.
- `smoke.json` over stdio: 5 of 5 calls passed (both tools; without Tor: the refusals and the status).

**Only a real host behind a Tor profile can prove** (mcp-live with `--vpn` of a Tor profile): that Ahmia's and
DuckDuckGo's onion services answer, that Ahmia's live markup matches its template, and the timings. CI has no Tor:
its smoke runs check the refusal path and the status.
