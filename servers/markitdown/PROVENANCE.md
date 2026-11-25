# markitdown - provenance and review

| | |
|---|---|
| MCP server | this repository, `src/server.py` and `src/convert.py` (MIT), our own (2026-11-25): the tool of markitdown-mcp 0.0.1a8 (`convert_to_markdown`) on markitdown's library, restricted to files in `/work` |
| Upstream reviewed | PyPI `markitdown-mcp` **0.0.1a8** (wheel `markitdown_mcp-0.0.1a8-py3-none-any.whl`, uploaded 2026-10-21 19:41 UTC, 35 days before this review, SHA-256 `f525ad3dfd3a2637b2ccb3c516d66f3a5d958a7316c31601106f1e9308a51b5b`; 152 lines, read in full - not installed, see "Why our own") and `markitdown` **0.1.9** (wheel uploaded 2026-10-21 19:41 UTC, SHA-256 `52f59c48bea9cf887224c56247f648d68beb7aa7af5a12d414748210c83c20ea`; sdist `8f692236fc104b9251e1b86bdea969c6a1617174fe37eebb78ac6fa62a2894f0`), microsoft/markitdown, MIT |
| Python packages | `requirements.txt`, hash-locked from `requirements.in` with `overrides.txt` (magika left out), every pin published before 2026-11-11 (14 days before this review): the shared lock of servers/duckduckgo and servers/youtube-transcript (`mcp==1.30.0`, requests, urllib3, charset-normalizer, idna, certifi, defusedxml 0.7.1; the same versions and hashes) and six 1.17.0 (as servers/capa and openosint), plus, new here: markitdown 0.1.9, beautifulsoup4 4.15.0 (2026-06-07), soupsieve 4.1 (2026-11-10), markdownify 1.2.3 (2026-06-30), mammoth 1.13.0 (2026-09-26), cobble 0.1.4 (2024-06-01), pdfminer.six 20260107 (2026-01-07) |
| Debian packages | `tini=0.19.0-3+b8` (the image's init, its ENTRYPOINT: no host init needed), `python3=3.13.5-1` (no `ca-certificates`: no network) |
| Base image | the `debian:trixie-slim` digest in `Dockerfile` |
| Licences | `LICENSES/`: markitdown (MIT, from the repository's tag v0.1.9: the wheel ships none), beautifulsoup4, soupsieve, markdownify, pdfminer.six, six, MCP Python SDK (MIT), mammoth (BSD-2-Clause), cobble (BSD-2-Clause, declared in its README; it ships no text - the note says so), defusedxml (PSF-2.0), sandbox-ai-mcp (MIT) |

## Round 2's reasons, and how they are met

Round 2 (2026-11-18, `docs/round2-reviews.md`) did not admit markitdown for two reasons:

1. **The closure could not be reviewed completely**: markitdown-mcp requires `markitdown[all]` (74 packages, about
   1.66 million lines, 112 native libraries: onnxruntime, numpy, pandas, lxml, Pillow, PDFium, Azure SDKs, speech
   recognition), and markitdown itself imports magika (an ONNX model on onnxruntime) at import.
   **Met by leaving those out**: the image installs markitdown 0.1.9 without any extra and without magika (`--no-deps`
   on a lock resolved with magika overridden away), and only these pure-Python libraries beside the shared lock:
   beautifulsoup4, soupsieve, markdownify, mammoth, cobble, pdfminer.six (about 43,000 lines; pdfminer.six's
   `cryptography` is the shared lock's). magika is stood in for by `convert.py`'s `_NoMagika` (an object in
   `sys.modules` before markitdown is imported): markitdown asks it for each stream, gets "not available" and keeps the
   guess from the file's extension - which for files in a folder is what decides anyway. No native library is added
   to the image beyond what the shared lock already has (cryptography, pydantic-core, rpds-py, cffi).
2. **The MCP server fetched any URL and answered unbounded**: `convert_uri` takes `http:`, `https:`, `file:` and
   `data:` URIs (an SSRF in a container with network) and the whole document is one answer (megabytes).
   **Met by an own server**: only files in `/work` (a path, or a `file:` URI of one), no network at all, answers in
   parts of 24,000 characters with the next offset, plugins never loaded.

What is lost against upstream's `[all]`: XLS (old Excel), Outlook MSG, images (EXIF, LLM captions), audio
(transcription), YouTube/Wikipedia/Bing pages, Azure Document Intelligence/Content Understanding, ZIP recursion,
PDF form/table layout (pdfplumber needs pypdfium2 and Pillow: PDFs come out as their text), Word equations as LaTeX
and the repair of broken Word styles (both need lxml; markitdown skips the step without it). XLSX and PPTX, which
upstream converts with pandas and python-pptx (lxml, Pillow), are converted by two small converters of our own in
`convert.py` (zipfile and defusedxml only).

## The review (2026-11-25)

### markitdown-mcp 0.0.1a8 (152 lines, read in full)

One tool, `convert_to_markdown(uri)`: `MarkItDown(enable_plugins=MARKITDOWN_ENABLE_PLUGINS).convert_uri(uri)`,
returned whole; errors mapped to short texts without paths (good); `--http`/`--sse` transports with Starlette and
uvicorn (a warning when bound to a non-local address). Findings, all fixed by the own server: any `http(s):` URL
fetched (SSRF), `file:` anywhere in the file system, `data:` URIs of any size, unbounded answers, third-party
plugins by entry point when the variable is set. No telemetry, no update check.

### markitdown 0.1.9 (7,560 lines)

Read in full: `_markitdown.py` (847: the converter registry, `convert_stream`, the magika guess, the URI handling not
used here), `_base_converter.py`, `_stream_info.py`, `_exceptions.py`, `_uri_utils.py`, and every converter this
server registers - `_plain_text_converter.py`, `_html_converter.py`, `_markdownify.py`, `_csv_converter.py`,
`_ipynb_converter.py`, `_rss_converter.py`, `_docx_converter.py` with `converter_utils/docx/pre_process.py` and
`_images.py`, `_epub_converter.py`, and of `_pdf_converter.py` the pdfminer path and `_merge_partial_numbering_lines`
(used by our PDF converter). Grepped and read where hit: the rest (`__main__.py` the CLI, the Azure, audio, image,
exiftool, LLM, YouTube, Wikipedia, Bing, Outlook, ZIP converters, `docx/math/omml.py`) - none of it is registered or
reachable here.

- **Network**: `MarkItDown()` creates a `requests.Session` (no request is made; only `convert_uri` with http(s) and
  the YouTube converter would use it - neither is reachable). The image has no network anyway.
- **Processes**: only `_exiftool.py` (`subprocess.run` of exiftool, from the image converter; not registered, no
  exiftool in the image).
- **Files**: `convert_local` opens the path it is given (not used: the child converts the descriptor it is given as a
  stream); the CLI writes its `-o` file (not used).
- **Plugins**: `importlib.metadata.entry_points(group="markitdown.plugin")`, only with `enable_plugins=True` - the
  child passes `False` and no plugin is installed.
- **Environment**: `EXIFTOOL_PATH`, `AZURE_API_KEY`, `MARKITDOWN_*` read only on the unused paths; the child starts
  with an empty environment.
- **Parsing**: EPUB and RSS through `defusedxml.minidom` (no DTDs, no entities); DOCX through mammoth (below) after
  `pre_process_docx`, which reads every part of the ZIP into memory - the child checks the ZIP first (entries, total
  size, compression ratio); its BeautifulSoup `features="xml"` passes need lxml and fail without it (caught by
  markitdown, the step skipped). HTML through BeautifulSoup's `html.parser`; `_CustomMarkdownify` drops
  `javascript:` links and shortens `data:` URIs of images (`keep_data_uris` false: mammoth's embedded images become
  `data:image/png;base64...`).
- **Telemetry, update checks, backdoors**: none found.

### The libraries (new to this repository)

Each was grepped for network (`socket`, `urllib`, `http.client`, `requests`, `urlopen`), processes (`subprocess`,
`os.system`, `os.popen`), code loading (`eval`, `exec`, `pickle`, `marshal`, `importlib`, `ctypes`, entry points),
file writes and deletions, environment variables, threads/signals/atexit hooks and telemetry; every hit was read,
and the modules on the paths markitdown calls were read where they parse input (as "audited" in this repository's
other PROVENANCE files, not line by line):

- **beautifulsoup4 4.15.0** (10,634 lines, MIT): no network or process; `diagnose.py` (a debugging helper, never
  imported) uses a temporary file; the `xml` feature needs lxml, absent. Parsing with the standard library's
  `html.parser`.
- **soupsieve 4.1** (5,119 lines, MIT): CSS selectors; module-level locks only; nothing else found.
- **markdownify 1.2.3** (878 lines, MIT, read in full): HTML tree to Markdown; nothing found.
- **mammoth 1.13.0** (5,190 lines, BSD-2-Clause): `docx/files.py` opens external images by URL (`urlopen`) or by
  path **only with `external_file_access=True`**; the default is `False` (`mammoth/__init__.py`) and markitdown does not pass it
  (an external image then becomes an error in mammoth's messages, never a request). XML through
  `xml.dom.minidom` (expat: no external entities; the expansion protection of expat 2.4+ against entity bombs - a test
  feeds one). `cli.py` writes files (not used).
- **cobble 0.1.4** (216 lines, BSD-2-Clause, read in full): `exec` of class source text built from the library's own
  class and field names (mammoth's document model), never from input.
- **pdfminer.six 20260107** (20,997 lines, MIT): CMaps are loaded only as JSON (`.json.gz`) from `CMAP_PATH`
  (default `/usr/share/pdfminer/`, absent here) and the package's own folder, with a path check against the folder -
  the pickle loading of older releases (a published code-execution advisory of 2025) is gone - no `pickle` in the package; `image.py` writes images only with an output folder
  (`extract_text` passes none); `pdf2txt.py`/`dumppdf.py` are scripts in the venv's `bin` (not used). `cryptography`
  only for encrypted PDFs (RC4/AES). Hostile PDFs can make it slow (known upstream): the child's CPU and time limits.
- **six 1.17.0**: the same wheel as servers/capa's.

### Our code (`src/server.py`, `src/convert.py`)

- Paths as servers/cfr: relative to `/work`, absolute under it, or `file:///work/...` (`localhost` allowed, other
  hosts refused), percent-decoded once; `..`, `~`, control characters, other schemes refused; every name opened with
  `O_NOFOLLOW` from `/work`'s descriptor (no link followed, also not inside `/work`); only a regular, non-empty file
  of at most 64 MiB.
- The child (`convert.py`) gets that descriptor as its standard input, `-I`, an environment of `LANG`, `HOME` and
  `PATH` only, `/` as its folder, its own session (killed as a group at the time limit, 120 s); it limits itself
  before importing markitdown: 1.5 GiB of address space, 150 s CPU, no file written (`RLIMIT_FSIZE` 0), 64
  descriptors, no core. What it prints is capped at 32 MiB; errors are one line without the file's text.
- ZIP containers (DOCX, XLSX, PPTX, EPUB) are checked before a converter reads them: at most 20,000 parts, 384 MiB
  unpacked, no part over 1 MiB compressed more than 200:1.
- Own XLSX converter: workbook, relationships, shared strings, styles (date formats 14-22, 45-47 and custom formats
  with d/m/y) and each sheet through `defusedxml.ElementTree` (`forbid_dtd`); at most 2,000,000 cells and 512
  columns; booleans, inline strings, dates (1900 and 1904 systems); `|` escaped. Own PPTX converter: slides in the
  presentation's order, titles, text, grouped shapes, tables, speaker notes; external relationships ignored.
- Answers: 24,000 characters at most, cut after a line where one ends in the last fifth, with "(more: offset=N)";
  the converted Markdown is kept (8 documents, 96 MiB) by device, inode, size, mtime and ctime of the file.
- Tools only (no resources or prompts advertised), read-only annotations.

## Tests

`tests/test_markitdown.py` (24 tests: paths and links, the child's environment, descriptor, time limit and output
cap, exit statuses, pages, the cache; with markitdown installed every format on the fixtures, a zip bomb, an entity
bomb, 20,000 nested `<div>`s, broken files, a binary file and the whole server over stdio), `test_own_servers.py`
`test_markitdown` (inside the image in CI); smoke spec: 7 conversions (DOCX, PDF, XLSX, PPTX, EPUB, HTML, CSV from
`tests/fixtures`) + 3 refused calls. Run on 2026-11-25 in a Python 3.13 venv made from `requirements.txt`
(`--require-hashes --no-deps`): 24 passed.

## Risks left

- pdfminer.six and mammoth parse untrusted files; a crafted file can be slow or large: bounded by the child's limits,
  and the image has no network and no writable folder of the user's.
- The libraries are audited for what they reach (network, processes, files, code loading), not read line by line.
- The Markdown is the document's author's text: data, never instructions (said in the server's instructions).
