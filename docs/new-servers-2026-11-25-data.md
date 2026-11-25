# New servers of 2026-11-25: documents and data (markitdown, duckdb, dbhub, CyberChef)

Tier 1 and 2 of `/work/research-llm/mcp-additions-2026-11-25.md`, the share of the agent mcpnew-data (the others:
mcpnew-dev, mcphard). Rules as in [round2-reviews.md](round2-reviews.md): the whole code that runs read or audited,
every dependency reviewed or already reviewed here, a release pinned only when it is at least 14 days old (cut-off for
this round: published before 2026-11-11, `uv pip compile --exclude-newer 2026-11-11`), no telemetry, no install
script, no auto-update, tools only, answers within 24,000 characters, hostile inputs tested. And the conventions of
the hardening round: tini as ENTRYPOINT, smoke calls for every tool that runs offline, the limits in the smoke spec.
Nothing here is signed or published: each added server is a **pending** catalog entry (digest `null` in
`digests.json`) until CI has built it, its smoke reports pass and the catalog is signed with the human.

Each server was also run before publishing (the user's condition): there is no Podman in the review sandbox, so each
ran from its pinned sources in a throwaway Python 3.13 venv made from its hash-locked `requirements.txt`, driven over
stdio with its smoke spec (initialize, tools/list against `tools.json`, every smoke call) with `/work` pointed at the
fixtures.

## Overview

| Server | Verdict | Pin / source | Network | Tools (smoked) | Effort |
|---|---|---|---|---|---|
| [markitdown](../servers/markitdown) | **added, pending** (own server on markitdown's library); round 2's reasons met | markitdown 0.1.9, markitdown-mcp 0.0.1a8 reviewed | none | 1 (1) | 4 h |
| [duckdb](../servers/duckdb) | **added, pending** (own server) | mcp-server-motherduck 1.1.0 reviewed; DuckDB 1.5.6 | none | 4 (4) | 2.5 h |
| dbhub | npm package **stays out** (same closure as round 2); [dbhub](../servers/dbhub) **added, pending** as an own read-only server | DBHub v1.6.1 reviewed (the ported parts); pg8000 1.31.6 | none (PostgreSQL: given at `mcp add`) | 2 (2) | 3.5 h |
| CyberChef | CyberChef-MCP **stays out**; [codec](../servers/codec) **added, pending** (own, standard library) | CyberChef-MCP 4.2.0 looked at | none | 2 (2) | 2 h |

## markitdown - added (pending)

| | |
|---|---|
| Verdict | **added** as an own server (`src/server.py`, `src/convert.py`) on markitdown 0.1.9's converters, pending signature |
| Round 2's reasons | (1) `markitdown[all]`: 74 packages / 1.66 M lines / 112 native libraries, magika (onnxruntime) imported at import: met - no extras, magika overridden out of the lock and stood in for by the file's extension (`_NoMagika`), only pure-Python libraries beside the shared lock (beautifulsoup4 4.15.0, soupsieve 4.1, markdownify 1.2.3, mammoth 1.13.0, cobble 0.1.4, pdfminer.six 20260107; ~43,000 lines, audited); (2) the MCP server fetched any URL and answered unbounded: met - files in `/work` only, pages of 24,000 characters |
| Formats | PDF (pdfminer.six text), DOCX (mammoth), XLSX and PPTX (own converters on zipfile + defusedxml), EPUB, HTML, CSV, JSON, notebooks, RSS, text |
| Limits | input 64 MiB; a child per conversion on the checked descriptor: empty environment, 1.5 GiB, 150 s CPU, no file written, killed at 120 s, output 32 MiB; ZIP checks (20,000 parts, 384 MiB, 200:1) |
| Tests | `tests/test_markitdown.py` 24 (paths, child, pages, cache; every format; zip bomb, entity bomb, deep HTML, broken files); smoke 7 real + 3 refused - **10/10 over stdio** |
| Lost against `[all]` | XLS, Outlook, images, audio, YouTube/Wikipedia pages, Azure, PDF table layout (pdfplumber/PDFium), Word equations as LaTeX (lxml) |
| Risks left | pdfminer.six and mammoth parse untrusted files (bounded by the child); the libraries audited, not read line by line |

## duckdb - added (pending), our own server

| | |
|---|---|
| Verdict | **added** as an own server on the shared lock + `duckdb==1.5.6` (upstream's pin), pending signature |
| Upstream reviewed | mcp-server-motherduck **1.1.0** (2026-10-07, wheel `da7b9873...1410`), 1,705 lines in full; 1.1.1 (2026-11-11 17:58 UTC) too new at review time |
| Why own | fastmcp 4 (67 packages); its read-only mode lets SQL read `/etc/passwd`, `COPY` anywhere, install extensions and change settings; timeout off by default; 50,000-character answers |
| Sandbox | DuckDB's own: `allowed_directories ['/work/']` then `enable_external_access=false`, no extension autoinstall/autoload/community/unsigned, no replacement scans, 512MB, 2 threads, no spill, then `lock_configuration` - each checked against the engine |
| Read-only | COPY, COPY DATABASE, EXPORT, ATTACH, DETACH refused by statement type (DuckDB's parser); LOAD/INSTALL/UPDATE EXTENSIONS never; `DUCKDB_DATABASE` files attached `READ_ONLY`; `DUCKDB_WRITE=1` opens writes |
| Tests | `tests/test_duckdb.py` 12 (against DuckDB itself); smoke 6 real + 4 refused - **10/10 over stdio** |
| Risks left | DuckDB's native parsers on untrusted files (upstream); a FIFO in `/work` blocks a query beyond `interrupt()` |

## dbhub - npm package stays out; DBHub's two tools as an own server (pending)

| | |
|---|---|
| Verdict | `@bytebase/dbhub` **stays out**: 1.6.0/1.6.1 (the newest old enough) have round 2's eight dependencies (MCP TS SDK v2, express, ssh2 with an install script, ...) - the ~222,000-line closure is unchanged. **Added** instead: an own server with DBHub's two tools, pending signature |
| Upstream reviewed | DBHub **v1.6.1** source (tarball `a38cb00b...01e6`): execute-sql, search-objects, allowed-keywords, the read-only paths of the PostgreSQL and SQLite connectors in full; `src` grepped (no telemetry; its request log is in memory for its web UI) |
| Libraries | pg8000 1.31.6, scramp 1.5.0, asn1crypto 1.5.1, python-dateutil 4.0.0 (~31,000 lines, audited); pg8000's own TLS default (unverified, falls back to plain text) never used |
| Read-only | three layers: reading keyword first, no writing word or escape-hatch function (46) outside comments and strings, one statement; the engine - PostgreSQL READ ONLY transaction always rolled back, `default_transaction_read_only`, the extended protocol (one statement), LIMIT in the server; SQLite `mode=ro`, `query_only`, an authorizer (ATTACH, `load_extension`, pragma changes, writes) |
| Secrets | `DBHUB_DSN` without password (one with a password is refused); `DBHUB_PASSWORD` the secret |
| Tests | `tests/test_dbhub.py` 18 (+1 against a real PostgreSQL with `SANDBOX_AI_MCP_PG_DSN`); smoke 5 real + 4 refused on SQLite - **9/9 over stdio** |
| Risks left | PostgreSQL not run against a real server here (no PostgreSQL in the sandbox: initdb refuses root); functions with side effects outside the list run inside the READ ONLY transaction - a read-only role is the boundary |

## CyberChef - CyberChef-MCP stays out; codec (own) added (pending)

| | |
|---|---|
| Verdict | doublegate/CyberChef-MCP **4.2.0** (GPL-3.0-or-later, 2026-09-12) **stays out**: 17.7 MB package, 105 runtime dependencies (tesseract.js fetching language data from a CDN, jimp, kbpgp, node-forge, libyara-wasm, capstone-js, d3, bootstrap, jquery, ...), a `postinstall` script, telemetry code (`cyberchef_telemetry_export`, OpenTelemetry API), 6 releases in 30 hours, hundreds of tools. **Added** instead: codec, our own server on the standard library, pending signature |
| Tools | `run_recipe` (up to 20 of 41 operations: encodings, ROT, XOR, compression both ways, charsets, JWT decode, hashes, strings, entropy, defang) and `detect` (21 magic numbers, encodings, JWT, with recipe and preview) |
| Limits | input 1 MiB; every step 16 MiB (decompressors with a maximum length; expansions refused before they are made); 20 steps; 10 s |
| Tests | `tests/test_codec.py` 9; smoke 6 real + 2 refused - **8/8 over stdio** |

## The sandbox-ai side

Branch `feature/mcpnew-data` of sandbox-ai (worktree from `/work` main): `docs-writer`, `docs-from-code` and
`research-memory` offer markitdown; `data-ml` and `database-services` offer duckdb and dbhub - as optional `--mcp`
values (none by default, each with its `mcp add` hint), because a preset's required MCP servers block its start until
they are added and these are pending; `research-memory`'s ruleset holds what markitdown converts for untrusted.
codec is offered by `forensics`, `mini-ctf` and `network-analysis` the same way.

## What only CI or a real host can prove

- The images build (Debian packages and wheels by hash; markitdown with `--no-deps`), the Trivy scan, the smoke
  specs inside the images under Podman, Bubblewrap and without a host init, and `test_own_servers` inside each image
  (Debian's Python 3.13 and libsqlite3 instead of the venv's).
- The Bubblewrap forms (rootfs) CI makes from the images, and their limits (markitdown and duckdb: memory 1g).
- dbhub against a real PostgreSQL (TLS verify-full, SCRAM, the READ ONLY transaction): set `SANDBOX_AI_MCP_PG_DSN`
  (and `SANDBOX_AI_MCP_PG_PASSWORD`) for `tests/test_dbhub.py`, or a live `sandbox-ai mcp add mcp:dbhub` on a host.
- On a real host: `sandbox-ai mcp add` of each (unsigned until the signature: `--build` or the signed catalog), the
  presets' hints, and markitdown's conversions of real-world documents (large PDFs, Office files with images).
