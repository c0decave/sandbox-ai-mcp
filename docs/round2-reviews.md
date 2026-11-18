# MCP round 2: reviews (2026-11-18)

The second round of `/work/research-llm/mcp-registry-research-2026-11.md` (its "Second pass" section has the registry
research): full reviews of the servers it ranked highest, in the order the brief set, and the helpers for local
models. Rules as everywhere in this repository: the whole code that runs read, every dependency reviewed or already
reviewed here, a release pinned only when it is at least 14 days old (cut-off for this round: published before
2026-11-04 18:00 UTC), no telemetry, no install script, no auto-update, tools only, answers within 24,000 characters,
hostile inputs tested. Nothing here is signed or published: each added server is a **pending** catalog entry (digest
`null` in `digests.json`) until CI has built it, both smoke reports pass and the catalog is signed with the human.

Effort is the time this review and packaging took (or would take), not counting CI.

## time - added (pending)

| | |
|---|---|
| Verdict | **added**, pending signature |
| Upstream | modelcontextprotocol/servers `src/time`, PyPI `mcp-server-time` |
| Pin | **2026.10.28** (wheel SHA-256 `4b8a1865e8c45da2d2247e72ca83ea087e5c8bc597c9ca93c63e9103aeb46c31`, = commit `74af74c8`); 2026.11.4 turns 14 days old on 2026-11-18 21:34 UTC, after this review |
| Dependencies | the SDK 2.3.0 lock of osint-mcp (reviewed there) + tzdata 2026.6 (data) + tzlocal 5.4.5 (read in full) |
| Network | none |
| Tools | `get_current_time`, `convert_time` (2026.10.28 has no `get_time_ago`; that came later) |
| Changes | zone arguments checked before upstream (long or path-like values echoed or answered with a container path), answers bounded, tools only, `LOCAL_TIMEZONE` |
| Tests | `tests/test_time.py` (5 tests, 11 hostile calls), smoke spec 2 real + 3 refused calls |
| Effort | 2 h |
| Risks left | the container's clock is the host's (a wrong host clock is a wrong answer); `convert_time` converts a time of *today* only (upstream's design); the zone database ages with the pin (IANA 2026f) |

## osv - added (pending), our own server

| | |
|---|---|
| Verdict | **added** as an own server (stdio, the shared lock), pending signature |
| Upstream reviewed | StacklokLabs/osv-mcp **v0.1.4** (2026-10-14, commit `498b22e4`, tarball SHA-256 `613208fe80580e792b9821ea3b959f8c6b8fd5ea6e8a174ca7286dfc8cd20baa`), 723 lines of Go read in full |
| Why own | upstream serves SSE/HTTP only (no stdio), its fixes touch most of its code, its Go module closure is not reviewed here |
| Network | allowlist `api.osv.dev:443` |
| Tools | `query_vulnerability` (+ `page_token`), `query_vulnerabilities_batch` (1-100), `get_vulnerability` |
| Upstream findings fixed | id unescaped in the URL path (other paths of the API reachable), unbounded answers (megabytes for a kernel package), page token not accepted, batch unlimited, no argument checks, redirects followed, unlimited body |
| Tests | `tests/test_osv.py` (8 tests: 19 refused argument sets, stand-in requests, errors, bounds), `test_own_servers.py` `test_osv`; smoke spec 3 real + 2 refused calls |
| Effort | 3 h |
| Risks left | the package names asked about reach Google (osv.dev); the short form shows the fixed versions of the queried ecosystem only, which a model may take for the whole picture (get_vulnerability has all); real calls not run here (api.osv.dev unreachable from this machine) |

## youtube-transcript - added (pending), our own server

| | |
|---|---|
| Verdict | **added** as an own server on youtube-transcript-api (without yt-dlp), pending signature |
| Upstream reviewed | jkawamoto/mcp-youtube-transcript **v0.8.3** (2026-10-28, commit `fc6e33cf`, tarball SHA-256 `a23dd2d79c4a06b73cf278ea2908cd88000fc484aaa16b79d3406ef7f9b9d0fd`), 386 lines read in full |
| Library pinned | youtube-transcript-api **1.2.4** (2026-01-29, wheel `03878759...43ff`), read in full; defusedxml 0.7.1 (read); requests/urllib3/charset-normalizer from osint-mcp's reviewed lock |
| Why own | upstream 0.8.3 depends on **yt-dlp** (not reviewable completely; needs a JS runtime, can fetch remote components) for the title and video facts; it also has a ScrapingAnt proxy mode with TLS verification off and a 50,000-character default page |
| Network | allowlist `www.youtube.com:443` |
| Tools | `get_transcript`, `get_timed_transcript`, `get_available_languages`, `get_video_info` (upstream's names; no upload date - that was yt-dlp's) |
| Fixed | no timeout and no size limit in the library (10/30 s, 8 MiB), redirects not followed, video ids checked, pages within 24,000 characters, bounded caches, one-sentence errors (upstream's carry a referral link) |
| Tests | `tests/test_youtube_transcript.py` (7 tests against a stand-in for YouTube), `test_own_servers.py` `test_youtube_transcript`; smoke spec 2 real (upstream-limited for YouTube's bot check) + 2 refused |
| Effort | 4 h |
| Risks left | YouTube's bot check on cloud, VPN and Tor addresses (then every call fails, by design); it uses private steps of the pinned library (re-check on re-pin); YouTube's page format can change and break it; the video ids reach Google |

## dbhub - not added (candidates/dbhub)

| | |
|---|---|
| Verdict | **not added**: cannot be reviewed completely in this round |
| Release looked at | `@bytebase/dbhub` **1.5.1** (2026-11-03, tarball SHA-256 `9c83be5157c53a0ae38439cb3fed75a297fa6afb6341d973adb7ab44714b0d58`); 1.6.0-2.0.0 too new |
| Why | its own code is 10,712 lines, but stdio with PostgreSQL and SQLite needs 95 npm packages / ~222,000 lines: the MCP TypeScript SDK **v2** split packages (new here), hono, zod 4.6, ssh2 (with an install script for an optional native binding), express 4 with ~60 packages imported at start though only HTTP uses it; more drivers for MySQL, SQL Server (Azure SDK), Oracle |
| First look | good design for local models (2 tools); read-only is layered (keyword allowlist, mutating-keyword scan, escape-hatch functions, the database's own read-only transaction) but upstream calls it a guardrail, not a boundary |
| Effort | 1 h to this verdict; a complete review: days |
| Next | an own read-only SQL server on the shared Python lock (SQLite via the standard library, read-only; PostgreSQL via a small pure-Python driver in a READ ONLY transaction) with dbhub's two-tool design |

## wikipedia - added (pending), our own server

| | |
|---|---|
| Verdict | **added**, our own server on the shared lock, pending signature |
| Third-party compared | Rudra-ravi/wikipedia-mcp 2.0.1 (~12 tools, fastmcp 2.x and wikipedia-api: an unreviewed tree) - not clearly better |
| Network | allowlist of 16 hosts `{en,de,fr,es,it,pt,nl,pl,ru,uk,sv,ja,zh,ar,tr,ko}.wikipedia.org:443` |
| Tools | `search_wikipedia`, `get_summary`, `get_article` (pages, sections) |
| Tests | `tests/test_wikipedia.py` (7 tests), `test_own_servers.py` `test_wikipedia`; smoke 3 real + 2 refused |
| Effort | 2.5 h |
| Risks left | article text can be wrong or vandalised (said in the notes); 16 languages only (the catalog's host limit); real calls not run here |

## arxiv - added (pending), our own server

| | |
|---|---|
| Verdict | **added**, our own server on the shared lock, pending signature |
| Third-party compared | blazickjp/arxiv-mcp-server 0.8.2 (19 tools + 3 prompts, writes a paper store, asks Semantic Scholar, `mcp<2` with PDF libraries) - not clearly better |
| Network | allowlist `export.arxiv.org:443`, `arxiv.org:443` |
| Tools | `search_papers`, `get_paper`, `read_paper` (HTML full text, formulas as LaTeX, pages) |
| Tests | `tests/test_arxiv.py` (9 tests), `test_own_servers.py` `test_arxiv`; smoke 3 real + 2 refused |
| Effort | 3 h |
| Risks left | papers without an HTML rendering (most before late 2023) have no full text here (no PDF parser in the lock); the 3 s pace makes many searches slow by design; real calls not run here |

## markitdown - not added (candidates/markitdown)

| | |
|---|---|
| Verdict | **not added**: cannot be reviewed completely |
| Releases looked at | markitdown-mcp **0.0.1a8** (wheel `f525ad3d...51b5b`), markitdown **0.1.9** (wheel `52f59c48...20ea`), both 2026-10-21 |
| The server | 152 lines, read: fetches http(s)/file/data URIs (SSRF), unbounded answers, plugins by entry point - fixable by a wrapper (file: only, bounded, plugins off) |
| Why | markitdown imports magika (ONNX model on onnxruntime) at import; markitdown-mcp needs `markitdown[all]`: 74 packages, ~1.66 million lines of Python, 112 native libraries, 312 MB (onnxruntime, numpy, pandas, lxml, Pillow, PDFium, Azure SDKs, speech recognition) |
| Effort | 1 h to this verdict |
| Next | an own `documents` server on the shared lock (DOCX/XLSX/PPTX/ODF/EPUB as ZIP+XML, HTML, CSV with the standard library; PDF later through one reviewed pure-Python parser): 6-8 h |

## shodan - added (pending), our own server

| | |
|---|---|
| Verdict | **added** as an own server on the shared lock, pending signature |
| Upstream reviewed | npm `@burtthecoder/mcp-shodan` **1.0.36** (w0h1v/mcp-shodan, 2026-11-03, commit `8b202b05`, tarball SHA-256 `13ba4fa3d3adbf76dd11e9b485fb0fcb35f9d986528ceca7573e297c9ab4b05a`), 1,184 lines read in full |
| Why own | its closure (TypeScript fastmcp, axios, ...) is not reviewed here; the fixes touch most tools |
| Network | allowlist `api.shodan.io:443`, `cvedb.shodan.io:443` |
| Tools | upstream's 11: `ip_lookup`, `shodan_search`, `shodan_count`, `search_filters`, `dns_lookup`, `reverse_dns_lookup`, `domain_info`, `api_info`, `cve_lookup`, `cves_by_product`, `cpe_lookup` |
| Upstream findings fixed | CVE/CPE limits of 1,000 (megabytes), whole banners, unchecked lists and dates, unbounded error texts, no start without a key although CVEDB needs none, `.env` read; the key (a URL parameter by Shodan's design) kept out of logs and errors |
| Tests | `tests/test_shodan.py` (8 tests), `test_own_servers.py` `test_shodan`; smoke 2 real (CVEDB, no key) + 3 refused |
| Effort | 3 h |
| Risks left | 11 tools is many for a small local model (a router helps, see docs/local-helpers.md); the key travels as a URL parameter (Shodan's API); credits are spent by `shodan_search` with filters and `domain_info`; the keyed tools untested against the real API here |

## maigret - not added (candidates/maigret)

| | |
|---|---|
| Verdict | **not added** |
| Releases looked at | npm `mcp-maigret` **1.0.18** (2026-11-03, commit `4324d5d8`, tarball `d0cafc86...42e9`, 324 lines read in full); PyPI `maigret` **0.6.6** (2026-09-18, wheel `f382e717...81c7`) |
| Why | the wrapper runs maigret only as `docker run soxoj/maigret:latest` (Docker socket in the container; an unpinned image pulled automatically = auto-update of code); maigret 0.6.6's closure is 67 packages / ~889,000 lines / 50 native libraries (curl-cffi's libcurl-impersonate, aiohttp, lxml, reportlab, Flask); its site-database auto-update (off with `--no-autoupdate`), third-party "dynamic rules", Cloudflare bypass and an OpenAI summary are in the code |
| Effort | 1.5 h to this verdict |
| Next | an own checker on maigret's pinned `data.json` as data (httpx, a bounded subset of sites, no auto-update, no activation code): 8-10 h |
