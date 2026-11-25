# arxiv - provenance and audit

| | |
|---|---|
| MCP server | this repository, `src/server.py` (MIT), our own (2026-11-18); no third-party MCP code |
| Service | arXiv's API (`https://export.arxiv.org/api/query`, Atom) for search and metadata, and arXiv's HTML renderings (`https://arxiv.org/html/<id>`, LaTeXML) for full text; no key |
| Python packages | the shared lock of this repository (`mcp==1.30.0` and its dependencies, hash-locked in `requirements.txt`, the same as servers/duckduckgo's); XML and HTML with the standard library |
| Debian packages | `tini=0.19.0-3+b8` (the image's init, its ENTRYPOINT: no host init needed), `python3=3.13.5-1`, `ca-certificates=20250419+deb13u1` |
| Base image | the `debian:trixie-slim` digest in `Dockerfile` |

## Why our own and not a third-party server

The research's candidate, blazickjp/arxiv-mcp-server 0.8.2 (Apache-2.0, 2026-10-08), is strong but offers 19 tools
and 3 prompts (too many for a small model), writes downloaded papers and "watches" into a storage folder, also asks
`api.semanticscholar.org`, and needs `mcp<2.0.0` with its own dependency tree (PDF libraries among them) - a separate
lock to review. It is not clearly better for this catalog's use; three tools on the shared lock cover search,
abstract and full text and are reviewed completely here. Nothing of it is used.

## This server

**Tools:** `search_papers(query, max_results 1-30, sort relevance|submitted|updated, start)` - arXiv's own query syntax
passed on (plain words become `all:...`), each paper with id, title, up to 20 authors, dates, categories and the first
500 characters of the abstract, the total and `next_start`; `get_paper(id)` - metadata, whole abstract, comment,
journal reference, DOI, abstract/PDF/HTML links; `read_paper(id, offset)` - the full text from the HTML rendering as
plain text (headings as `#` lines, formulas as their LaTeX `alttext` between `$`, tables as `|` rows; scripts, styles,
navigation, page header and footer left out), in pages of at most 20,000 characters (`next_offset`; the last 8 texts
kept for paging). A paper without an HTML rendering (most before late 2023, or a failed conversion) gets a clear error;
PDFs are not parsed (no PDF library in the lock).

**Checks:** ids new-style (`2401.12345`, optional `v7`) or old-style (`hep-th/9901001`), also given as `arXiv:...` or an
arxiv.org abs/pdf/html URL; queries 1-300 characters without control characters; numbers in their ranges.
**Requests:** API requests one at a time and at least 3 s apart (arXiv's API terms), 30 s each, at most 16 MiB read,
no redirects followed except arXiv's own from `/html/<id>` to `/html/<id>v<n>` on the same site; `HTTPS_PROXY`
honoured. The Atom feed is parsed with the standard library after refusing any `<!DOCTYPE`/`<!ENTITY>` (no entity
expansion, no external references). **Answers:** within 24,000 characters as sent (lists halved, texts cut, with a
note).

**Network:** allowlist `export.arxiv.org:443`, `arxiv.org:443`. No mount, no secret. **Privacy:** queries and ids go to
arXiv (Cornell University).

## Tested

Natively (`tests/test_arxiv.py`, `tests/test_own_servers.py` `test_arxiv`): handshake, tools equal to `tools.json`,
tools only; 6 accepted and 9 refused id forms (a path, a query string, another host, None, a number, ...); 7 refused
argument sets over stdio; search and get against a stand-in on loopback (parameters, `all:` added only for plain words,
the User-Agent, abstracts cut in lists and whole in `get_paper`, 30 authors cut to 20, `next_start`); the 3-second pace
(two searches at least the interval apart); the HTML text (redirect to the newest version followed, a redirect to
another site refused, 404, scripts/header/navigation/footer left out, formulas as LaTeX, entities decoded); a
230,000-character paper read page by page; 503, 500, a broken feed, a feed with an entity declaration, no entry, 30
long entries within 24,000 characters, a refused connection. The smoke spec: three real calls and two refused. Not run
here: the image build and the real calls (arxiv.org is not reachable from this machine).

## Verdict

Our own code, reviewed with this repository's tests; no dependency beyond the shared lock. **Pending**: fit to sign
once CI has built it and both smoke reports pass.
