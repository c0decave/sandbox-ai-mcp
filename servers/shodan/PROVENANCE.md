# shodan - provenance and audit

| | |
|---|---|
| MCP server | this repository, `src/server.py` (MIT): the eleven tools of w0h1v/mcp-shodan, ported to Python |
| Upstream reviewed | w0h1v/mcp-shodan (formerly BurtTheCoder/mcp-shodan) **1.0.36** = npm `@burtthecoder/mcp-shodan` 1.0.36 (MIT, `LICENSES/mcp-shodan-MIT.txt`), published 2026-11-03 17:44 UTC (15 days before this review) from commit `8b202b05227e9a9b075139cf60bfda3e4c68cec0` (npm `gitHead`); tarball SHA-256 `13ba4fa3d3adbf76dd11e9b485fb0fcb35f9d986528ceca7573e297c9ab4b05a`, integrity `sha512-dP4yisJaeXrvOAKmIRDW2SRuGtl9jIJpxww7FfOzurzbCI4d6AgsajMhick4wUK3S934v8EWPItzm9nZWaPFaw==`, 17 files. 1.0.37-1.0.41 (2026-11-05 on) are too new |
| Services | Shodan's REST API (`https://api.shodan.io`, key as the `key` URL parameter, as Shodan requires) and Shodan's CVEDB (`https://cvedb.shodan.io`, no key) |
| Python packages | the shared lock of this repository (`mcp==1.30.0` and its dependencies, hash-locked in `requirements.txt`, the same as servers/duckduckgo's) |
| Debian packages | `python3=3.13.5-1`, `ca-certificates=20250419+deb13u1` |
| Base image | the `debian:trixie-slim` digest in `Dockerfile` |

## The review of mcp-shodan 1.0.36 (2026-11-18)

**Everything of the package was read:** `build/index.js` (70 lines), `build/helpers.js` (143) and the eleven
`build/tools/*.js` (25-158 each) - 1,184 lines with `package.json` and the README. `package.json`: dependencies
`axios` 1.20.0 (exact), `dotenv` ^18, `fastmcp` ~4.22.4 (the npm framework, not Python's), `zod` ^4.6.7; scripts
`build`, `test`, `prepublishOnly` (`tsc`) only - no install script. None of these dependencies is used here.

**What it does:** eleven read-only tools on fastmcp: `ip_lookup` (`/shodan/host/{ip}`), `shodan_search`
(`/shodan/host/search`), `shodan_count` (`/shodan/host/count`), `search_filters` (`.../filters`, `.../facets`),
`dns_lookup` (`/dns/resolve`), `reverse_dns_lookup` (`/dns/reverse`), `domain_info` (`/dns/domain/{domain}`),
`api_info` (`/api-info`), and on CVEDB `cve_lookup` (`/cve/{id}`), `cves_by_product` (`/cves`), `cpe_lookup`
(`/cpes`). axios with a 10 s timeout, the key as `key=` on every api.shodan.io request. Transports stdio or
`httpStream` (`MCP_TRANSPORT`, no authentication). `dotenv.config()` reads a `.env` of the working directory. No other
host, no file written, no process, no telemetry, no update check, no dynamic code.

**Findings in upstream (none a backdoor or malicious code):**

| Severity | Where | What | Here |
|---|---|---|---|
| medium | `cves-by-product.js`, `cpe-lookup.js` | `limit` defaults to **1,000**, each CVE with its references: answers of megabytes | limit 1-50 (CVEs) and 1-500 (CPEs), default 20/100, summaries and references cut, every answer within 24,000 characters as sent |
| medium | `ip-lookup.js`, `shodan-search.js` | banners (`data`) whole: a host's HTTP banner can be kilobytes, and with `history` hundreds of them | banners at most 600 characters (300 in search), lists bounded, history collapsed per port and product as upstream does |
| low | `dns-lookup.js`, `reverse-dns-lookup.js` | lists of any length and any strings, joined by commas into one parameter | 1-100 entries, host names and IP addresses checked |
| low | `cves-by-product.js` | `start_date`/`end_date` not checked | `YYYY-MM-DD[THH:MM:SS]` |
| low | `helpers.js` | `error.message` and Shodan's error text reach the model unbounded | 300 characters, the key replaced if it appears, statuses named |
| low | `index.js` | the server does not start without `SHODAN_API_KEY`, although CVEDB needs none | starts without it; the api.shodan.io tools say the key is missing |
| info | `helpers.js` | the key is a URL parameter (Shodan's API design): it appears in request URLs, which HTTP client logs print | httpx's request log is off; failures name only the exception class |
| info | `index.js` | `dotenv` reads `.env` from the working directory | no `.env`; the key only from the container's environment |

**Why an own server and not the npm package:** the package is 1,184 lines; its closure is not (`fastmcp` for
TypeScript with the MCP SDK, hono, undici, ...; axios), none reviewed here. `src/server.py` asks the same endpoints
with the same parameters on the shared Python lock, so nothing unreviewed is added; the findings above are fixed.

## This server

**Tools:** upstream's eleven names and arguments; answers as JSON objects with lower-case keys instead of upstream's
display strings (`ip_lookup`: `ip, org, isp, asn, location, ports, services[{port, transport, product, version, cpe,
banner, cves, http, tls}], cves, hostnames, domains, tags, cloud, history`; `shodan_search`: `query, total, page,
returned, facets, matches`; `cves_by_product`: `total, returned, cves[{cve, summary, cvss_*, epss, known_exploited,
...}], next_skip`; ...). Errors as `{"error": ...}`.

**Key:** `SHODAN_API_KEY` read for each call, checked to be 16-64 letters and digits, sent only to api.shodan.io (as
`key=`), never to cvedb.shodan.io, never returned or logged (httpx's request log, which prints URLs, is set to
warnings only; error texts are scrubbed). **Requests:** no redirects followed, the answer read up to 16 MiB, 30 s;
`HTTPS_PROXY` honoured. **Credits:** `shodan_search` with a filter and `domain_info` cost query credits (said in their
descriptions and in the instructions).

**Network:** allowlist `api.shodan.io:443`, `cvedb.shodan.io:443`. No mount. Only Shodan's database is asked: no target
host is contacted.

## Tested

Natively (`tests/test_shodan.py`, `tests/test_own_servers.py` `test_shodan`): handshake, tools equal to `tools.json`,
tools only, the missing key; 18 refused argument sets (a path in the IP, a parameter in the facets, a comma in a host
name, `localhost`, DNS type `ANY`, a path in the CVE id, both or neither of product and cpe23, `&` in a product, limit
1000, a word as date, ...); every tool against a stand-in on loopback (paths, parameters, the key only on api.shodan.io
requests, the latest banner per port, TLS versions without disabled ones, history rows, facet percentages, a host name
normalised, paging); no log record with the key; 401 with the key in Shodan's text, 429, 500 with a 2,000-character
text, a non-JSON answer, a refused connection - the key in no error; a host with 399 ports, 3,000-character banners and
3,000 CVEs, and 50 CVEs with 1,600 CPEs each, within 24,000 characters. The smoke spec: two real CVEDB calls (no key
needed) and three refused. Not run here: the image build and real calls (no key; shodan.io not reachable from here).

## Verdict

Upstream reviewed completely; no backdoor, telemetry or unexpected host. Shipped as an own server on the reviewed
shared lock, upstream's findings fixed. **Pending**: fit to sign once CI has built it and both smoke reports pass; the
keyed tools need `SHODAN_API_KEY` (the human's).
