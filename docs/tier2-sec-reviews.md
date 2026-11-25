# Tier 1 and 2, the security and OSINT servers: reviews (2026-11-25)

The security and OSINT servers of `/work/research-llm/mcp-additions-2026-11-25.md` (user, 2026-11-25: "start to add
tier1 and tier2. then do in-depth analysis if they really work before publishing"), in the order given: ghidra,
maigret, yt-dlp, onion search. The rules of round 2 hold: the whole code that runs reviewed (engines too large to read
line by line - Ghidra, yt-dlp - reviewed on what they can do at run time, as jadx, the browsers of playwright and the
language servers of lsp-python/lsp-go were), a release pinned only when it is at least 14 days old (cut-off: published
before 2026-11-11), no telemetry, no install script, no auto-update, tools only, answers within 24,000 characters,
hostile inputs tested, each server run here before it is proposed. Nothing is signed or published: an added server is
a **pending** entry until CI has built and smoked it and the catalog is signed with the human.

All four are our own servers: in each case the upstream MCP server was the part that failed review (pyghidra-mcp's
101-package closure; mcp-maigret's Docker socket and maigret's own closure and auto-update; yt-dlp-mcp's TypeScript
wrapper with downloads; no admissible onion-search server), while the engine or data underneath could be pinned and
reviewed.

## Overview

| Server | Verdict | Pin / source | Network | Tools (smoked) |
|---|---|---|---|---|
| [ghidra](../servers/ghidra) | **added** (own), pending | Ghidra **12.2** (2026-10-22, zip SHA-256 `2c2cd776...7be67`), Temurin **25.0.5+8** JRE/JDK (2026-10-22) | none | 10 (all smoked: 20 calls with 6 refusals) |
| [maigret](../servers/maigret) | **added** (own), pending | maigret **0.6.6**'s `data.json` only (2026-09-18, wheel `f382e717...81c7`, file `ef6ca66e...62da`) | full | 4 (all smoked: 11 calls; 2 network calls marked `upstream_limited`) |
| [yt-dlp](../servers/yt-dlp) | **added** (own), pending | yt-dlp **2026.10.26** (2026-10-26, wheel `a05c5b5d...39ae`), no extras | full, public addresses only | 4 (all smoked: 10 calls; the YouTube calls `upstream_limited`) |
| [onion-search](../servers/onion-search) | **added** (own), pending | Ahmia and DuckDuckGo onion addresses (their own publications) | full, through Tor only | 2 (both smoked: the refusal path and the status; real searches only behind Tor) |

## ghidra - added (own server, pending)

| | |
|---|---|
| Verdict | **added**, pending signature; round 1's candidate (pyghidra-mcp) stays out and its folder is gone |
| Pins | Ghidra 12.2 (`Ghidra_12.2_build`, revision `8ca90770`, the newest release, 34 days); Eclipse Temurin 25.0.5+8 (Ghidra 12.2 needs Java 25; the JRE is servers/signal's, the JDK only compiles the bridge); the shared MCP SDK lock |
| Reviewed | our `src/server.py` (868 lines; its file and JVM handling is servers/jadx's) and `src/GhidraBridge.java` (715 lines) by construction; Ghidra (2,557,934 lines of Java in its 82 source archives, the C++ decompiler) on what it can do at run time: network clients, processes, files, dynamic code, telemetry, native code in jars - searched over the source archives. Details: `servers/ghidra/PROVENANCE.md` |
| Round 1's reasons | chromadb, onnxruntime, huggingface-hub (a model download), grpcio, kubernetes, OpenTelemetry - none of it: no Python package besides the shared lock; write tools (rename, set types, save, delete) - none: ten read tools |
| Found and closed | Ghidra writes a packed-database cache to `/var/tmp/<user>-ghidra` by default (redirected with its settings, temp and cache folders into the scratch folder); a class of ours on `-cp` is loaded by the parent class loader and cannot see Ghidra (the bridge is an external Ghidra module); raw firmware has no load spec (open_file takes a `language`); the debugger, Ghidra Server, BSim, PyGhidra, GhidraGo and extensions removed from the image |
| Verification | here with the pinned zip and JDK, over stdio: smoke 20/20; tests 30/30 with the real Ghidra; a 29.9 MB library (53,209 functions) analysed with the time limit and decompiled; only `decompile` and `demangler_gnu` started; nothing written outside the scratch folder |
| Risks left | the input is parsed by Ghidra's loaders and the native decompiler (the container is the boundary: no network, read-only input, non-root, limits); image about 600 MB; memory 3 GiB and more for large binaries |
| Effort | 3 h |

## maigret - added (own checker on its data, pending)

| | |
|---|---|
| Verdict | **added**, pending signature; round 2's replacement built |
| Pin | maigret 0.6.6 (2026-09-18; 0.6.7 of 2026-11-21 too new): only `resources/data.json` (5,897 entries, 23 engines) and the licence ship; none of maigret's code |
| Round 2's reasons | (1) mcp-maigret's `docker run soxoj/maigret:latest` - no wrapper, no Docker; (2) a 67-package closure - none, the shared lock; (3) database auto-update, activation tokens, "dynamic rules", Cloudflare bypass, TLS impersonation, OpenAI summary - none: the data changes only with a reviewed re-pin; 6 activation entries, 12 entries with site cookies or tokens in their headers and 201 entries behind protections a plain client cannot pass are listed as not checked (4,990 of 5,897 are checked) |
| Reviewed | `src/server.py` by construction; maigret 0.6.6's `checking.process_site_result`, `make_site_result`, `error_detection.detect_error_page`, `sites.MaigretSite`/`update_from_engine`/`ranked_sites_dict` read and re-implemented; `errors.COMMON_ERRORS` copied and compared with `ast`; `data.json` reviewed as data (URL schemes and hosts, methods, payloads, headers) |
| Found and closed | maigret quotes the name with `/` left unencoded (`quote(username)`): here the name is restricted and encoded with no safe characters; redirects are followed by this server and every hop's host checked for public addresses |
| Verification | smoke 11/11 here (GitHub's API answered found/not found live); tests 19/19; this sandbox's egress resets anyio TLS to most hosts, so a broad search could not be judged here |
| Risks left | sites see the searched name (Tor hides the user); false positives and negatives are maigret's data's; DNS rebinding not ruled out |
| Effort | 2 h |

## yt-dlp - added (own server on the engine, pending)

| | |
|---|---|
| Verdict | **added**, pending signature; the research's upstream (kevinwatt/yt-dlp-mcp 0.10.2, TypeScript, downloads) not used |
| Pin | yt-dlp 2026.10.26 (2026.11.23 too new), the wheel without extras: no dependency at all |
| Reviewed | `src/server.py` by construction; yt-dlp's core on this server's path read (plugins, networking and TLS, cache, `YoutubeDL` init/extract/urlopen, netrc and page dumps in `extractor/common.py`) and the whole package (240,981 lines, 972 extractor modules) searched for processes, dynamic and remote code, updates, files, credentials and network - each found switched off or absent (PROVENANCE.md has the table) |
| Found and closed | plugins load from config folders and every `sys.path` entry by default (`plugin_dirs` emptied, `YTDLP_NO_PLUGINS`); `js_runtimes` defaults to looking for deno (`{}`); the cache writes YouTube data to `~/.cache` (`cachedir: False`); the generic extractor fetches any URL and follows a page's redirects and embeds (a guard on `socket.getaddrinfo` in the worker keeps public addresses only); a hang of an extractor (one worker process per call, killed at 50 s) |
| Verification | tests 12/12 here, among them yt-dlp itself against a page on the loopback (metadata and the subtitle text) and the guard refusing it; smoke 7/10 here (TED and the refusals; YouTube is reset by this sandbox's egress) |
| Risks left | the extractors parse hostile pages (in the worker, no secrets, nothing written); YouTube without a JavaScript runtime and from CI addresses is unproven; yt-dlp's 211,292 lines of extractors were searched, not read |
| Effort | 2 h |

## onion search - added (own server, pending)

| | |
|---|---|
| Verdict | **added**, pending signature |
| Source | none upstream: darkweb-mcp (SOCKS, its own `tor`, resources, 0 stars), ddg-onion-mcp (no release) and the unverified others were not taken (registry pass); Ahmia's onion address and search-form token from its own site's source (ahmia/ahmia-site), DuckDuckGo's onion address as servers/web-fetch's Tor tests have it |
| Design | fail closed: refuses without sandbox-ai's Tor profile before any lookup; behind it, only the two engines' onion hosts, each name resolving into Tor's range before a connection (redirects too); results as data |
| Verification | tests 11/11 (fixtures rendered from Ahmia's templates, DuckDuckGo's recorded page); smoke 5/5 here (the refusal path and the status) |
| Risks left | only mcp-live behind a real Tor profile proves that the engines answer and Ahmia's live markup matches its template |
| Effort | 1.5 h |

## Presets (sandbox-ai)

The presets that propose them (sandbox-ai branch `feature/mcpnew-sec`): ghidra - software-analysis, firmware-iot,
hardware-analysis, forensics, mini-ctf; maigret - the OSINT presets; yt-dlp - research-memory and the OSINT presets;
onion-search - the Tor presets. None writes: no rules files are needed.
