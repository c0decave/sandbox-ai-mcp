# brave-search - provenance and audit

| | |
|---|---|
| MCP server | this repository, `src/server.py` (MIT, `LICENSES/`) |
| Service | the Brave Search API, https://api.search.brave.com/res/v1/ (web/search, news/search) |
| Python packages | `mcp==1.30.0` and its dependencies, hash-locked in `requirements.txt` |
| Debian packages | `python3=3.13.5-1`, `ca-certificates=20250419+deb13u1` |
| Base image | the `debian:trixie-slim` digest in `Dockerfile` |

## Why an own server

Brave's official MCP server is a Node.js program with more tools (local, image, video search,
summarizer). Web and news search are two GET requests; an own Python server keeps the image in
line with the other servers here.

## Audit

**Tools:** `web_search`, `news_search`: `GET .../web/search` and `GET .../news/search` with the
parameters `q`, `count`, `offset`, `country`, `freshness`. No redirects; answers above 8 MiB are
refused; timeout 30 s; 401/403/429 and other errors are named.

**Key:** read from `BRAVE_API_KEY` for each request, checked to be 8-128 characters of
`[A-Za-z0-9_-]`, sent only as the `X-Subscription-Token` header to api.search.brave.com; never
returned or logged.

**Arguments:** `query` 1-400 characters without control characters; `count` 1-20; `offset` 0-9;
`country` two letters or `ALL`; `freshness` `pd`, `pw`, `pm`, `py` or empty.

**Results:** only entries with an http(s) URL; title, URL, description (news: age, source).

**Network:** allowlist `api.search.brave.com:443`.

**Tested:** natively (`tests/test_own_servers.py`: handshake, tools/list, missing key and refused
arguments, the parser against `tests/fixtures/brave-web.json`). A live call needs a key; CI runs
it when the repository secret `BRAVE_API_KEY` is set.
