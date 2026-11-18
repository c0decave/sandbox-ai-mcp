# markitdown - candidate, not admitted (review of 2026-11-18, round 2)

**Review of 2026-11-18 (round 2): not added.** The verdict and its reasons are in `docs/round2-reviews.md`; this
folder keeps what was found, for the next attempt. Nothing here is built.

| | |
|---|---|
| Upstream | microsoft/markitdown (MIT): `markitdown-mcp` and `markitdown` on PyPI |
| Releases looked at | `markitdown-mcp` **0.0.1a8** (wheel uploaded 2026-10-21 19:41 UTC, SHA-256 `f525ad3dfd3a2637b2ccb3c516d66f3a5d958a7316c31601106f1e9308a51b5b`) and `markitdown` **0.1.9** (2026-10-21 19:41 UTC, SHA-256 `52f59c48bea9cf887224c56247f648d68beb7aa7af5a12d414748210c83c20ea`); both 28 days old |

## The MCP server (read in full: `markitdown_mcp/__main__.py`, 152 lines)

One tool, `convert_to_markdown(uri)`: `MarkItDown(enable_plugins=MARKITDOWN_ENABLE_PLUGINS).convert_uri(uri)` for
`http:`, `https:`, `file:` and `data:` URIs, returned whole. Findings: it fetches any URL (an SSRF in a container
with network); the answer is unbounded (a spreadsheet or a long PDF is megabytes); `MARKITDOWN_ENABLE_PLUGINS`
loads third-party plugins through Python entry points; HTTP/SSE transports with a warning for non-local binds. Errors
are mapped to short texts without paths (good). Restricted to `file:` inside a mounted folder, bounded and with
plugins off, the server itself would be fine.

## Why not admitted

`markitdown-mcp` requires `markitdown[all]`, and `markitdown` itself imports **magika** (Google's file-type detector:
an ONNX model run by **onnxruntime**) when it is imported. The closure (`uv pip install --exclude-newer 2026-11-04
markitdown-mcp==0.0.1a8 markitdown[all]==0.1.9`): **74 packages, about 1.66 million lines of Python, 112 native
libraries, 312 MB** - onnxruntime (63 MB), numpy (30 MB), pandas (45 MB), lxml (12 MB), Pillow, pypdfium2 (PDFium),
the Azure SDKs (Document Intelligence, Content Understanding, identity), SpeechRecognition and pydub (audio sent to a
speech API), youtube-transcript-api. Even the extras for local office files and PDF alone (pdf, docx, xlsx, pptx)
keep magika/onnxruntime, numpy, pandas, lxml, Pillow and pypdfium2. That cannot be reviewed completely.

## What would admit it, or replace it

- An own `documents` server on the shared lock: DOCX, XLSX, PPTX, ODT/ODS/ODP and EPUB are ZIP files of XML (the
  standard library's `zipfile` with a size and ratio limit, XML without DTDs or entities), HTML and CSV with the
  standard library; Markdown out, paged within 24,000 characters, files only from a read-only `/work`. PDF would need
  one reviewed pure-Python parser (pdfminer.six) as a second step. Estimate 6-8 h without PDF.
- markitdown with magika replaced by extension-based detection would still need lxml, pandas and PDFium reviewed.
