# lsp-python - provenance and audit

| | |
|---|---|
| Server | `src/server.py`, this repository's own LSP bridge (MIT), run as `server.py python` |
| Language server | **pyright 1.1.414** (Microsoft, MIT, `LICENSES/pyright-MIT.txt`), npm `pyright` published 2026-09-09 (77 days before this review; the newest release), tarball SHA-256 `bf5f473f6167c0d14175492c3263d783b4489a6956e1c06c18e15228e3a3fa42` (= the sha512 integrity the registry publishes, `FPZZb51j...uwuXww==`), unpacked to `/opt/lsp/pyright` without npm and without install scripts; its source maps are left out |
| Python packages | `requirements.txt`: the MCP Python SDK 1.30.0 lock of servers/osv (reviewed there), hash-locked |
| Debian packages | `tini=0.19.0-3+b8` (the init of the ENTRYPOINT), `python3=3.13.5-1` (the bridge; pyright also asks it for its search paths), `nodejs=20.19.2+dfsg-1+deb13u3` (runs pyright) |
| Base image | the `debian:trixie-slim` digest in `Dockerfile` |
| Network | none |

## pyright (2026-11-25)

pyright is Microsoft's Python type checker; the npm package is its webpack bundle (`dist/pyright-internal.js` 3.2 MB,
`vendor.js` 0.7 MB, typeshed's stubs). It was not read line by line (a compiled bundle of a large TypeScript code
base, like the browsers of servers/playwright): it was reviewed on what it can do at run time. Its bundle requires no
`http`, `https`, `dns`, `dgram` or `tls` module - no network client at all; `net` (only for the IPC transports it
offers instead of stdio), `child_process` (`execFileSync`/`execSync` of a Python interpreter to read `sys.path`, and
worker processes of itself), `worker_threads`, `fs`. Hosts in it are documentation links (aka.ms, github.com). No
telemetry. It writes no files into the workspace (no cache, no config). The image gives it no network anyway, and the
project read-only. The only dependency the package declares is `fsevents` (macOS, optional), not installed.

## The bridge (src/server.py, ours)

`src/server.py` (MIT, this repository; the same file in every `lsp-*` image, a test holds them equal) is an MCP server
over stdio (the MCP Python SDK lock of `servers/osv`, reviewed there) that starts one language server per connection
at the first call and speaks LSP to it over pipes (Content-Length framing, messages at most 4 MiB). It is written for
these images and reviewed by construction; `tests/test_lsp.py` runs it against a stand-in language server
(`tests/fixtures/fake_lsp.py`).

- **Tools (6, read-only):** `definition`, `references`, `hover`, `diagnostics`, `document_symbols`,
  `workspace_symbols`. It sends a language server only `initialize`/`initialized`, `textDocument/didOpen` and
  `didChange` (the text it read itself), `definition`, `references`, `hover`, `documentSymbol` and
  `workspace/symbol`; it answers the server's `workspace/configuration` with the server's own read-only options and
  every other request of the server (show-message prompts such as gopls' telemetry question, progress, capability
  registration) with `null`. No rename, code action, formatting, command execution or `workspace/applyEdit` exists
  in it (a test lists every LSP method in the file).
- **Files:** the project is `/work` (mounted read-only; `LSP_ROOT` narrows it to a folder at or below `/work`,
  resolved first). A tool's `file` is resolved with `realpath` (symbolic links followed) and refused outside the
  project, when it is not a regular file, when its suffix is not the language's, and above 2 MiB. Location results
  outside the project (the standard library) are shown by path and line, without their text.
- **Positions:** 1-based lines and columns in characters, converted to LSP's UTF-16 units and back (a character
  beyond the Basic Multilingual Plane counts two); instead of a column the symbol's name as written in that line
  (its first whole-word occurrence).
- **Bounds:** at most 100 locations, 100 diagnostics, 200 symbols, 6,000 characters of hover; every answer at most
  24,000 characters as sent (lists halved, then texts shortened, "cut" says so). Requests time out after 90 s
  (`LSP_TIMEOUT`), diagnostics wait at most 20 s and until the server has been quiet for 1.5 s (pyright and gopls
  publish twice). A language server that ends is started again by the next call.
- **Capabilities:** tools only (`tools_only`, as in servers/osv).

## Smoke

`smoke.json` seeds a small package (a class, a function, a type error) and calls every tool against the real
pyright: an outline, a definition across files, the references of a class, a hover with its docstring, the type
error as a diagnostic, a symbol by name - and refuses a path outside the project, a symbolic link to `/etc/passwd`
and a line beyond the file. Run here on 2026-11-25 with pyright 1.1.414 from the same tarball: 9 of 9 passed.
