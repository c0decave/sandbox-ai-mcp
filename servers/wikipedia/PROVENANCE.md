# wikipedia - provenance and audit

| | |
|---|---|
| MCP server | this repository, `src/server.py` (MIT), our own (2026-11-18); no third-party MCP code |
| Service | the MediaWiki Action API of `{lang}.wikipedia.org/w/api.php` (`list=search`; `prop=extracts|description|info|pageprops` with `explaintext`), no key, a descriptive User-Agent as Wikimedia's policy asks |
| Python packages | the shared lock of this repository (`mcp==1.30.0` and its dependencies, hash-locked in `requirements.txt`, the same as servers/duckduckgo's) |
| Debian packages | `tini=0.19.0-3+b8` (the image's init, its ENTRYPOINT: no host init needed), `python3=3.13.5-1`, `ca-certificates=20250419+deb13u1` |
| Base image | the `debian:trixie-slim` digest in `Dockerfile` |

## Why our own and not a third-party server

The candidate of the research, Rudra-ravi/wikipedia-mcp 2.0.1 (MIT, 2026-05-01), offers about 12 tools (more than a
small model should see for one source) and depends on `fastmcp>=2.3` and `wikipedia-api` - a dependency tree that
is not in any reviewed lock here. Three tools on the shared lock cover what agents use (find, introduction, full
text or a section) and are reviewed completely as part of this repository. Nothing of the third-party server is used.

## This server

**Tools:** `search_wikipedia(query, lang, limit 1-20)` - titles, plain-text snippets, word counts, URLs, total hits
and Wikipedia's spelling suggestion; `get_summary(title, lang)` - the introduction (at most 6,000 characters), the
short description, the URL, the title a redirect came from; `get_article(title, lang, section, offset)` - the whole
article as plain text with `== headings ==`, in pages of at most 20,000 characters (`next_offset`), the list of its
sections, or one section (with its subsections) by heading. Errors as `{"error": ...}`.

**Checks:** `lang` one of 16 languages (en, de, fr, es, it, pt, nl, pl, ru, uk, sv, ja, zh, ar, tr, ko; the host is
built only from that list), queries 1-300 and titles 1-255 characters without control characters (titles also without
`# < > [ ] { } |`), numbers in their ranges. **Requests:** one GET per call (two for nothing), no redirects followed,
`maxlag=5` (Wikimedia's courtesy for bots), 20 s, at most 8 MiB read, `HTTPS_PROXY` honoured. Wikipedia's error
codes are passed on in at most 300 characters. **Answers:** within 24,000 characters as sent (texts cut to fit).

**Network:** allowlist of the 16 hosts `{lang}.wikipedia.org:443` (the catalog's maximum of 16 hosts; another language
needs a source change and a new entry). No mount, no secret. **Privacy:** queries and titles go to the Wikimedia
Foundation.

## Tested

Natively (`tests/test_wikipedia.py`, `tests/test_own_servers.py` `test_wikipedia`): handshake, tools equal to
`tools.json`, tools only, instructions; 11 refused argument sets (empty, 301 characters, NUL, an unknown language, a
host in the language, limits 0 and 500, `|` in a title, 256 characters, a negative offset, a 201-character section);
search, summary and article against a stand-in on loopback (the language's path, the parameters, the User-Agent,
snippets without markup, the redirect, sections with their levels, one section with its subsections, an unknown
section); a 300,000-character article read page by page (all of it, each page within 24,000 characters); a missing
page, Wikipedia's `maxlag` error with a 2,000-character text, 429, 503, a non-JSON answer, a refused connection. The
smoke spec: three real calls and two refused. Not run here: the image build and the real calls (wikipedia.org is not
reachable from this machine).

## Verdict

Our own code, reviewed with this repository's tests; no dependency beyond the shared lock. **Pending**: fit to sign
once CI has built it and both smoke reports pass.
