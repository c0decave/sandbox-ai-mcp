# searxng - provenance and audit

| | |
|---|---|
| MCP server | this repository, `src/server.py` (MIT, `LICENSES/`) |
| Service | a SearXNG instance of yours (`SEARXNG_URL`), its `/search` with `format=json`; SearXNG itself is AGPL-3.0-or-later (https://github.com/searxng/searxng, checked at `3e95f6cd`, 2026-11-05) and not part of the image |
| Python packages | `mcp==1.30.0` and its dependencies (httpx among them), hash-locked in `requirements.txt` (the same lock as duckduckgo) |
| Debian packages | `python3=3.13.5-1`, `ca-certificates=20250419+deb13u1` |
| Base image | the `debian:trixie-slim` digest in `Dockerfile` |

## Why an own server

The MCP servers published for SearXNG are Node.js programs with a page-fetching tool as well.
Search is one GET to the instance; an own server keeps it fixed, bounded and easy to audit,
and web pages stay with `web-fetch`, which refuses local-network targets.

## Audit

**Setting:** `SEARXNG_URL`, checked at every call: `http` or `https`, a host, no credentials,
query or fragment, at most 300 characters; plain `http` only to a private, loopback or
CGNAT (100.64.0.0/10) address, so a name is always reached over TLS - or, behind sandbox-ai's Tor profile
(`SANDBOX_AI_TOR=1`), to a `.onion` instance, which Tor encrypts and authenticates by its name. A `.onion`
instance without a Tor profile is refused with that reason.

**Tool:** `web_search(query, max_results, category, language, time_range, page)`: one
`GET SEARXNG_URL/search?q=…&format=json&categories=…&language=…&pageno=…&safesearch=1`
(`time_range` when given). No redirects; the answer is read as a stream and refused above
4 MiB; timeout 30 s; 403 (JSON format not allowed), 429 (the instance's limiter) and other
statuses are named.

**Arguments:** `query` 1-500 characters without control characters; `max_results` 1-50;
`page` 1-10; `category` one of SearXNG's (`general`, `news`, `science`, `it`, `images`,
`videos`, `music`, `files`, `map`, `social media`); `language` `auto`, `all` or `xx[-XX]`;
`time_range` empty, `day`, `week`, `month` or `year`.

**Results:** only entries with an http(s) URL and a title; title (300), URL (2000), snippet
(1000 characters) and up to ten engine names; suggestions and answers as bounded text.

**Network:** the instance only (`--network full` in sandbox-ai, which has no per-server egress
proxy yet; the server requests nothing else).

**Tested:** natively with the locked requirements (`tests/test_own_servers.py`: handshake,
tools/list, the URL rules, refused arguments, an unreachable instance, the parser against
`tests/fixtures/searxng.json`); `smoke.json` runs the same refusals in the container (CI).
