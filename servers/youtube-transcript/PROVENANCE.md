# youtube-transcript - provenance and audit

| | |
|---|---|
| MCP server | this repository, `src/server.py` (MIT): the four tools of jkawamoto/mcp-youtube-transcript, on youtube-transcript-api, without yt-dlp |
| Upstream reviewed | jkawamoto/mcp-youtube-transcript **v0.8.3** (MIT, `LICENSES/mcp-youtube-transcript-MIT.txt`), release published 2026-10-28 06:37 UTC (21 days before this review) from commit `fc6e33cfdc8618d375dc600bb54f0576d84615fe`; source tarball `codeload.github.com/jkawamoto/mcp-youtube-transcript/tar.gz/v0.8.3`, SHA-256 `a23dd2d79c4a06b73cf278ea2908cd88000fc484aaa16b79d3406ef7f9b9d0fd`. v0.8.4 (2026-11-14) is too new. PyPI's `mcp-youtube-transcript` stops at 0.3.5 (2025): upstream publishes on GitHub (an `.mcpb` bundle) only |
| Library | `youtube-transcript-api` **1.2.4** (MIT, jdepoix), PyPI wheel uploaded 2026-01-29 09:09 UTC, SHA-256 `03878759356da5caf5edac77431780b91448fb3d8c21d4496015bdc8a7bc43ff`; 1.2.5 (2026-11-05) is too new |
| Python packages | `requirements.txt`, hash-locked: the shared lock of this repository (`mcp==1.30.0` and the same versions as servers/duckduckgo), plus `youtube-transcript-api` 1.2.4, `requests` 2.34.2, `urllib3` 2.8.0, `charset-normalizer` 3.5.2 (the versions and hashes of servers/osint-mcp's reviewed lock; charset-normalizer's compiled modules removed as there) and `defusedxml` 0.7.1 (2021-03-08, reviewed here) |
| Debian packages | `python3=3.13.5-1`, `ca-certificates=20250419+deb13u1` |
| Base image | the `debian:trixie-slim` digest in `Dockerfile` |

## The review (2026-11-18)

**mcp-youtube-transcript 0.8.3, all of it:** `src/mcp_youtube_transcript/__init__.py` (306 lines), `cli.py` (65),
`__main__.py` (15); `pyproject.toml`, `manifest.json`, `server.json`, `Dockerfile`, `.github/workflows/*.yml`
(release: `uv build` and an `.mcpb` bundle attached to the GitHub release). Four tools on the MCP SDK 2.x `MCPServer`:
`get_transcript`, `get_timed_transcript` (paged by `--response-limit`, default 50,000 characters), `get_video_info`
and `get_available_languages`.

| Severity | Where | What | Here |
|---|---|---|---|
| high (for this catalog) | `pyproject.toml`, `__init__.py` | **depends on yt-dlp** (any version since 2025.9.26) for `get_video_info` and for the title in every transcript: hundreds of thousands of lines of extractors and a JavaScript interpreter that cannot be reviewed completely; current yt-dlp needs an external JS runtime and can fetch "remote components" for YouTube | no yt-dlp: the title and the facts come from YouTube's player answer, which youtube-transcript-api already fetches |
| medium | `__init__.py` `_app_lifespan` | with `SCRAPINGANT_API_TOKEN` every request goes through a third-party proxy **with TLS verification off** (`http_client.verify = False`, `nocheckcertificate`) | no third-party proxies (Webshare, ScrapingAnt); `HTTPS_PROXY` (sandbox-ai's allowlist proxy) only, verification always on |
| medium | `__init__.py` | the default page of 50,000 characters is twice what clients show a model; with `--response-limit` <= 0 no limit at all | pages of at most 20,000 characters, every answer within 24,000 |
| low | `__init__.py` `_parse_video_id` | any host is accepted; a URL without `v=` raises a `ValueError` whose text echoes the URL; the id is not checked (`../x`, `&`) | youtube.com/youtu.be/youtube-nocookie.com hosts only, the id must be 11 characters of `[A-Za-z0-9_-]` |
| low | `__init__.py` | `lru_cache` without bound on videos and transcripts | 16 videos and 16 transcripts |
| low | `__init__.py` | upstream's error texts reach the model: paragraphs with links and a Webshare referral code | one short sentence per failure |
| info | `cli.py` | `HTTP_PROXY`/`HTTPS_PROXY` read as options | the same through requests' environment |

**youtube-transcript-api 1.2.4, the code that runs:** `_api.py` (127), `_transcripts.py` (492), `_errors.py` (272),
`proxies.py` (186), `_settings.py` (3), `__init__.py` (56) read in full; `formatters.py` (208), `_cli.py` (203) and
`__main__.py` (15) read (not imported by this server); `test/` is not installed into the image (removed in the
Dockerfile). Requests: `GET https://www.youtube.com/watch?v=ID` (with a `CONSENT` cookie set from the page's own
form when YouTube shows its consent page), `POST https://www.youtube.com/youtubei/v1/player?key=KEY` (the key from the
page) with the ANDROID client context, then `GET` of the caption track's `baseUrl` from that answer (YouTube's
`/api/timedtext` on www.youtube.com; any other host is refused by the allowlist). Captions are parsed with
`defusedxml` (no DTD entities, no external references). No other host, no file, no process, no telemetry, no update
check, no dynamic code. Findings: **no timeout** on any request (a stalled connection hangs the call) and **no size
limit** on answers; redirects followed. Here a `requests.Session` subclass sets 10 s to connect and 30 s between bytes,
reads at most 8 MiB and follows no redirect. The server calls the pinned version's own private steps
(`_fetch_video_html`, `_extract_innertube_api_key`, `_fetch_innertube_data`, `_extract_captions_json`, and
`_assert_playability` - which only reads the player's `playabilityStatus` and raises upstream's error - when
`get_video_info` gets no `videoDetails`) to keep the player answer for the title and facts: a re-pin must re-check
them.

**defusedxml 0.7.1:** `ElementTree.py` (154) and `common.py` (129), the modules youtube-transcript-api imports, and
`__init__.py` (67), read in full: a subclass of the standard library's pure-Python `XMLParser` that raises on
entity declarations and external references. Its other modules (minidom, sax, lxml, xmlrpc facades) are not imported.

**requests, urllib3, charset-normalizer:** the versions and hashes of servers/osint-mcp's lock, reviewed there by its
scan of every wheel (no code at interpreter start, no telemetry, no download of code).

## This server

**Tools:** upstream's four names; `url` (a YouTube URL or the bare id), `lang` (default `en`; English if that language
has no transcript, as upstream), `next_cursor` (the snippet index an earlier page gave). Answers: `get_transcript`
`{video_id, title, language, language_code, generated, transcript, next_cursor, snippets}`; `get_timed_transcript`
`{..., snippets: [{text, start, duration}], next_cursor, total}`; `get_available_languages` `{video_id, title,
languages: [{code, name, generated, translatable}]}`; `get_video_info` `{video_id, title, channel, channel_id,
length_seconds, length, view_count, live, description (5,000 characters), keywords}`. Upstream's `upload_date` is not
offered (it came from yt-dlp). Errors as `{"error": ...}` in one sentence.

**Network:** allowlist `www.youtube.com:443`. No mount, no secret, no account, no cookie kept beyond the consent
cookie of one process.

## Tested

Natively with this lock (`tests/test_youtube_transcript.py`): handshake, `tools/list` equal to `tools.json`, tools
only, instructions; 7 accepted URL forms and 13 refused (other hosts, look-alike hosts, a user part, `file:`,
`javascript:`, wrong id lengths, a path in the id, None, a number, 501 characters); refused arguments over stdio; the
whole flow against a stand-in for www.youtube.com on loopback (watch page, upstream's player request body, the
`&fmt=srv3` removal, captions with entities and markup, a second language, the English fallback, the facts, one watch
page for all calls of a video); a transcript of 3,000 snippets read page by page (every line once, each page within
24,000 characters); bot check, age restriction, unavailable, unplayable with a 900-character reason, no captions, a
player answer of another shape, a reCAPTCHA page, HTTP 500, a redirect, a 9 MiB page and an XML entity declaration -
each one short sentence, no referral link; `get_video_info` says the same for a player answer without facts (CI's
first build, 2026-11-21: a runner got the bot check and the answer was only "YouTube gave no facts", which the
smoke spec could not tell from a broken server). The smoke spec: two real calls (marked upstream-limited for YouTube's bot
check, which GitHub's runners often get) and two refused. Not run here: the image build and the real calls
(www.youtube.com is not reachable from this machine).

## Verdict

Upstream and the library reviewed completely; no backdoor or telemetry. yt-dlp, the third-party proxies and the
disabled TLS verification are not shipped. **Pending**: fit to sign once CI has built it and both smoke reports pass.
