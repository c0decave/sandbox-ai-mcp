# yt-dlp - provenance and audit

| | |
|---|---|
| MCP server | this repository, `src/server.py` (MIT): the four tools, the URL and language checks, the address guard, the worker process per call, the subtitle parsers; reviewed by construction (below) |
| Engine | yt-dlp **2026.10.26** (yt-dlp/yt-dlp, Unlicense, `LICENSES/yt-dlp-Unlicense.txt`), the PyPI wheel `yt_dlp-2026.10.26-py3-none-any.whl` uploaded 2026-10-26 22:25 UTC (30 days before this review), SHA-256 `a05c5b5d8562f7e8a62f5334348b406af4930d56d3a65f8021d14af0e22339ae` (in `requirements.txt`, installed with `--require-hashes`). 2026.11.23 is too new. Installed **without extras**: the wheel declares no dependency outside its extras, so no requests, urllib3, curl-cffi, websockets, brotli, mutagen, pycryptodomex, certifi-by-yt-dlp, yt-dlp-ejs or deno is installed for it |
| Python packages | `mcp==1.30.0` and the shared lock (byte-identical to servers/jadx's, reviewed there), then yt-dlp |
| Debian packages | `tini=0.19.0-3+b8` (the init), `python3=3.13.5-1`, `python3-venv=3.13.5-1` (purged after the venv is made), `ca-certificates=20250419+deb13u1` (the CA store yt-dlp verifies with: compat option `no-certifi`) |
| Base image | the `debian:trixie-slim` digest in `Dockerfile` |
| Network | full (any video site and its CDNs); every name yt-dlp looks up must resolve to public addresses |

## Why our own server, and not kevinwatt/yt-dlp-mcp

The research's upstream, `@kevinwatt/yt-dlp-mcp` 0.10.2 (npm, MIT, 2026-10-29), is a TypeScript wrapper that spawns
the `yt-dlp` command line: 10 tools, among them video and audio **downloads** into a folder, on the MCP TypeScript SDK
(express, its own dependency tree), zod, spawn-rx and rimraf, built from source by an npm `prepare` script. The brief
asks for metadata and subtitles only. An own Python server on the shared lock calls yt-dlp as a library with exactly
the read options below and adds what the wrapper lacks: a worker process per call with a time limit, an address guard,
bounded answers. Nothing of the wrapper is used. (Round 2 re-implemented youtube-transcript without yt-dlp because
yt-dlp was not needed there; for a server whose point is yt-dlp's site support it is the engine, reviewed as below.)

## yt-dlp 2026.10.26 (2026-11-25) - the core read, the extractors reviewed on what they can do at run time

The wheel holds 1,044 Python files, 240,981 lines: the core (`YoutubeDL.py` 4,552, `networking/` 2,606, `utils/`
7,330, `plugins.py`, `cache.py`, `cookies.py`, `update.py`, `jsinterp.py`, `postprocessor/` 2,449, `downloader/`
4,275, ...) and **972 extractor modules with 211,292 lines**, one per site. Like the engines of jadx, ghidra and the
lsp servers, it was not read line by line in full: the code on this server's path was read (the parameters below and
what they switch off, `plugins.py` whole, `networking/_helper.py` and `_urllib.py` on connections, TLS and redirects,
`cache.py`, `YoutubeDL.__init__`/`extract_info`/`urlopen`, `extractor/common.py` on downloads, netrc and page dumps),
and the whole package was searched for what code can do beyond fetching web pages:

| Concern | Found | Here |
|---|---|---|
| Processes | `subprocess`/`Popen` in 16 modules: `YoutubeDL` (`bidi_workaround`: fribidi), `extractor/common.py` (`netrc_cmd`: a shell command), `cookies.py` (browser keyrings for `cookiesfrombrowser`), the downloaders and post-processors (ffmpeg, aria2c, rtmpdump, AtomicParsley), `update.py` (the self-update), `extractor/openload.py` (PhantomJS, used by 3 extractors, only when a `phantomjs` executable exists), `extractor/youtube/jsc/_builtin/*` (deno, node, bun, quickjs for YouTube's player challenges), `utils` (`get_exe_version`) | none of these parameters is set; `js_runtimes` is `{}` (the default would look for deno); nothing is downloaded or post-processed; the image has no ffmpeg, phantomjs, deno, node or fribidi, so the one probe that runs by itself (format selection asks whether ffmpeg can merge) finds nothing to start. The worker runs with `PATH=/usr/bin:/bin` |
| Dynamic code | `plugins.py` imports `yt_dlp_plugins` packages from the user's and the system's config folders, the executable's folder and every `sys.path` entry, and an old-style `ytdlp_plugins/<type>/__init__.py` | the worker sets `plugin_dirs` to `[]` (what `--no-plugin-dirs` does) before the first `YoutubeDL`, and `YTDLP_NO_PLUGINS=1`: `load_plugins` returns at once; the venv has no such package and the image's root is read-only. `jsinterp.py` is yt-dlp's own JavaScript interpreter in Python (no `eval`/`exec`); `importlib` elsewhere loads yt-dlp's own lazy extractor modules |
| Remote code | `remote_components` (yt-dlp-ejs scripts from GitHub or npm for YouTube's challenges) | `[]`; the package `yt-dlp-ejs` is not installed |
| Updates, telemetry | `update.py` checks GitHub releases - only for the command line's `-U`/`--update-to` | the command line is not used (its `bin/yt-dlp` entry point is removed from the image); no telemetry in the package |
| Files | writes: downloads, `.part` files, info JSON, subtitles, thumbnails, archives, `write_pages` dumps, the cache (`~/.cache/yt-dlp`: YouTube signature data), cookie files | `skip_download`, `simulate`, no `write*` option, `cachedir: False`, no cookie file: nothing is written (the root file system is read-only anyway; `/tmp` is the worker's cwd) |
| Credentials | `.netrc`, `netrc_cmd`, `username`/`password`, `cookiefile`, `cookiesfrombrowser`, `client_certificate` | none set (`usenetrc: False`); the worker gets no secret and none exists in the container |
| Network | its own urllib handler (requests, curl-cffi and websockets are not installed); every connection resolves through `socket.getaddrinfo` (`networking/_helper.create_connection`, `socks.py`); TLS with the CA store, certificates verified (`nocheckcertificate` not set); the environment's proxy variables are honoured | the worker's guard replaces `socket.getaddrinfo` and drops every non-public address (loopback, private, link-local, CGNAT, multicast, reserved; IPv4-mapped and 6to4 judged by the IPv4 inside); a name left without one fails like a missing name - redirects, embeds and CDN hosts included. The worker's environment has no proxy variable |
| Input parsing | the extractors parse HTML, JSON, XML and JavaScript from the sites | in a worker process of its own: a hang or a crash ends that call only (killed with its process group after 50 s) |

## This server

**Tools (4, read-only):** `get_video_info(url, start_line)` - title, channel (with followers), site and id,
upload date, length, views, likes, comments, live status, age limit, availability, categories, tags, chapters,
subtitle languages, the number of formats and the best height, the description (5,000 characters); a playlist or
channel: its first 50 entries (flat: no request per entry). `list_subtitles(url)`. `get_subtitles(url, lang,
automatic, timestamps, start_line)` - the uploader's track first (else the automatic one, or only one kind), read as
json3, WebVTT or SRT (8 MiB at most), tags and entities removed, the rolling repeats of automatic captions dropped,
one cue per line with its start time. `search_videos(query, max_results)` - YouTube's search (`ytsearchN:`), at most 30
results. No tool downloads media or writes a file.

**Arguments:** a URL must be http(s) without user or password, its host a public address or a name that is not
`localhost`, `*.local`, `*.internal`, `*.lan`, `*.home.arpa`, `*.onion`, `*.i2p` or without a dot (an 11-character YouTube
id is taken too); the worker's guard then checks what the name resolves to. A language code is 1-35 letters, digits,
`-`, `_`. Answers: at most 400 lines and 24,000 characters, `start_line` goes on; control and direction characters of
the sites' texts are replaced.

**The worker:** `server.py --worker` with `python -I`, a JSON request on stdin, a JSON answer on stdout (at most
16 MiB read), stderr discarded, a new session (killed as a group), the environment `PATH`, `LANG`, `HOME` (and
`SSL_CERT_FILE`/`SSL_CERT_DIR` where the operator set them), nothing else. Only the fields listed in `_plain` leave it
(no format URLs, no HTTP headers, no cookies).

## Verification (2026-11-25, here; no Podman in this sandbox)

yt-dlp from the pinned wheel (SHA-256 checked) in a throwaway venv with the shared lock, the server over stdio:
- `tests/test_yt_dlp.py`: 12 tests passed, among them yt-dlp itself against a page served on the loopback (the
  generic extractor finds the HTML5 video and its WebVTT track; metadata, the subtitle text, a missing language) with
  the guard opened for that test only, and the guard refusing the same page ("refused: 127.0.0.1 has no public
  address"); the worker killed at its time limit; its environment.
- `smoke.json`: 7 of 10 calls passed here - TED (`get_video_info`, `list_subtitles`: TED's extractor lists no
  subtitles for that talk), the refusals, and `localtest.me` (a public name for 127.0.0.1) refused by the guard; the
  three YouTube calls could not run here: this sandbox's egress resets connections to YouTube.

**Only CI or a real host can prove:** YouTube without a JavaScript runtime (metadata, subtitles, search) from a CI
address (bot checks are marked `upstream_limited`), the other sites, the image build (its self-test runs the worker),
the smoke runs under Podman and Bubblewrap, behind a Tor profile.
