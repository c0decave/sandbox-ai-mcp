# lsp-go - provenance and audit

| | |
|---|---|
| Server | `src/server.py`, this repository's own LSP bridge (MIT), run as `server.py go` |
| Language server | **gopls v0.24.0** (the Go team's, BSD-3-Clause, `LICENSES/gopls-BSD-3-Clause.txt`), published 2026-10-14 (42 days before this review; the newest release), module `golang.org/x/tools/gopls` from tag `gopls/v0.24.0` (commit `1f9922d1dcc5836d5c5bcb552c8fed230f885372`), checked in the build against its sum.golang.org hash `h1:nPO/LffYa4sP62Ueuema5PPnZPGaZjGl+vZGvbTek4g=`; its dependencies by its `go.sum` |
| Go toolchain | Go 1.27.4 (`/usr/local/go` of the build image `golang:1.27-trixie` `sha256:c47c3fda...c39f`, docker-library/repo-info of 2026-11-10, the image of servers/gitea): gopls loads packages with `go list` |
| Python packages | `requirements.txt`: the MCP Python SDK 1.30.0 lock of servers/osv (reviewed there), hash-locked |
| Debian packages | `tini=0.19.0-3+b8` (the init of the ENTRYPOINT), `python3=3.13.5-1` (the bridge) |
| Base image | the `debian:trixie-slim` digest in `Dockerfile` |
| Network | none |

## gopls and Go (2026-11-25)

gopls (123k lines of Go, built from source in the image's build) and the Go toolchain are the Go project's own, the
same that the toolchains of this repository ship; they were reviewed on what they can do here, not line by line:

- **Network:** gopls reaches the network only through the go command (module downloads: `GOPROXY=off` - a module not
  in the project's `vendor/` is reported, never fetched; `GOSUMDB=off` with it; toolchain downloads: `GOTOOLCHAIN=local`),
  through vulncheck (`vulncheck: "Off"`, it would ask vuln.go.dev) and through links in hovers (`linksInHover: false`:
  pkg.go.dev links are not even shown). The image has no network anyway.
- **Telemetry:** golang.org/x/telemetry counts locally and uploads only in mode "on". The image ships Go's telemetry
  setting "off" (`go telemetry off`, read-only at `XDG_CONFIG_HOME=/opt/lsp/config`): no counters are written, and
  gopls' question whether to turn uploading on is a `window/showMessageRequest` the bridge answers with `null`.
  Checked here: with that setting no telemetry directory was created during a session.
- **Files:** caches in `/tmp` (`GOCACHE`, `GOMODCACHE`, gopls' own under `$HOME/.cache`); the project is read-only.
  No cgo (`CGO_ENABLED=0`, no C compiler in the image). Staticcheck off.
- **Not used:** gopls' own MCP server (`gopls mcp`), its daemon mode, its code actions and commands (the bridge never
  asks for them).

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

`smoke.json` seeds a module (a struct, a method, a function, an unused variable, an import of a module that is not
there) and calls every tool against the real gopls: an outline, a definition across packages and into the standard
library (`/usr/local/go/src/fmt/print.go`), references, a hover with the doc comment, the compiler's error as a
diagnostic, the missing module as a diagnostic (offline, nothing fetched), a symbol by name - and refuses a path
outside the project, a symbolic link to `/etc/passwd` and a line beyond the file. Run here on 2026-11-25 with gopls
v0.24.0 built from the same module and Go 1.27.3 in the image's environment (GOPROXY=off, telemetry off): 11 of 11
passed (the standard library's path is this machine's GOROOT here, `/usr/local/go` in the image).
