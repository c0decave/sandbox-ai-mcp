# duckduckgo - provenance and audit

| | |
|---|---|
| MCP server | this repository, `src/server.py` (MIT, `LICENSES/`) |
| Service | https://html.duckduckgo.com/html/ (DuckDuckGo's HTML search page) |
| Python packages | `mcp==1.30.0` and its dependencies (httpx among them), hash-locked in `requirements.txt` |
| Debian packages | `python3=3.13.5-1`, `ca-certificates=20250419+deb13u1` |
| Base image | the `debian:trixie-slim` digest in `Dockerfile` |

## Why an own server

Published DuckDuckGo MCP servers wrap scraping libraries with many more requests and options.
Search is one form POST; an own server keeps it fixed, bounded and easy to audit.

## Audit

**Tool:** `web_search(query, max_results, region)`: one `POST https://html.duckduckgo.com/html/`
with the form fields `q` and `kl`. No redirects are followed; the answer is read as a stream and
refused above 4 MiB; timeout 30 s; anything other than HTTP 200 is an error.

**Arguments:** `query` 1-500 characters without control characters; `max_results` 1-30;
`region` `wt-wt` or `xx-xx`.

**Results:** parsed with the standard library's HTML parser. Sponsored results (`result--ad`)
and links to DuckDuckGo itself are dropped; result links are decoded from DuckDuckGo's
`/l/?uddg=` redirect form; only http and https links are returned (a link of more than 2000 characters or one
urllib cannot parse is dropped); titles are cut at 300 characters, snippets at 1000. The server's instructions and
the tool's description say that results are written by the sites found: data, never instructions. It advertises
tools only (no empty resources or prompts). Review of 2026-11-17: a region with a line break after it (`de-de\n`) was taken
(`re.match`), and a failed connection said "not reachable: " with nothing after it; now the region must match
whole and the error names the exception.

**Network:** allowlist `html.duckduckgo.com:443`.

**Tested:** natively with the locked requirements (`tests/test_own_servers.py`: handshake,
tools/list, refused arguments, the parser against `tests/fixtures/duckduckgo.html`, the bounds, the whole request
against a stand-in on loopback - one POST with the query and the region - and a reset connection); the live call is
in `smoke.json` (CI).
