# Tier 1 and 2, the development servers: reviews (2026-11-25)

The development servers of `/work/research-llm/mcp-additions-2026-11-25.md` (user, 2026-11-25: "start to add tier1
and tier2. then do in-depth analysis if they really work before publishing"), in the order given: gitea-mcp, the
official GitHub server, semgrep, codebase-memory, language servers. The rules of round 2 hold: the whole code that runs
reviewed, a release pinned only when it is at least 14 days old (cut-off: published before 2026-11-11), no telemetry,
no install script, no auto-update, tools only, answers within 24,000 characters, hostile inputs tested, each server
run here before it is proposed. Nothing is signed or published: an added server is a **pending** entry until CI has
built and smoked it and the catalog is signed with the human.

## Overview

| Server | Verdict | Pin / source | Network | Tools (smoked) |
|---|---|---|---|---|
| [gitea](../servers/gitea) | **added**, pending | gitea-mcp **v1.13.0** (commit `34ba56e9`, 2026-11-06), our entry point | the user's Gitea (egress-all; `--allow-tcp` for one in the LAN) | 28 read tools (28 smoked offline; every method against a fake Gitea in the build) |
| github (github/github-mcp-server) | **not added**: review not completable | v2.1.0 (2026-11-03) looked at | - | - |
| semgrep (`semgrep mcp`) | **not added**: engine not reviewable, telemetry on by default | semgrep 1.184.0 (2026-11-05) looked at | - | - |
| codebase-memory | **stays out** (round-1 reasons unchanged) | 0.12.1 is still the newest release | - | - |
| [lsp-python](../servers/lsp-python) | **added** (own), pending | our bridge + pyright **1.1.414** (2026-09-09) | none | 6 (all smoked; 9 calls with 3 refusals) |
| [lsp-go](../servers/lsp-go) | **added** (own), pending | our bridge + gopls **v0.24.0** (2026-10-14), Go 1.27.4 | none | 6 (all smoked; 11 calls with 3 refusals) |
| lsp-c, lsp-rust | **designed, not built yet** | clangd-19 (Debian 1:19.1.7-3+b1), rust-analyzer (rustup component) | none | - |

## gitea - added (pending)

| | |
|---|---|
| Verdict | **added**, pending signature; round 2's open review finished |
| Pin | gitea-mcp **v1.13.0**, tag commit `34ba56e9a95d3a59113a293f1263685c3986f37c`, published 2026-11-06 05:39 UTC (19 days); archive SHA-256 `7f4a2ba8...dda8c` |
| Reviewed | all 53 linked Go files of gitea-mcp (10,227 lines) in full; Gitea's SDK v1.5.0 on its request path and searched in full; the MCP Go SDK v1.8.0 on the server path and searched in full; Go x/ modules on network, files and processes. Details: `servers/gitea/PROVENANCE.md` |
| Round 2's conditions | `GITEA_HOST` required (no gitea.com default) - done; `--insecure` refused - not reachable at all (the entry point sets no TLS option); answers bounded - 24,000 characters, no structuredContent, no images |
| Found | upstream writes downloads (logs, artifacts, attachments, release assets) to `$HOME/.gitea-mcp` or any `output_path`: in a container no agent can read them - refused and taken out of the schemas; `.`/`..` as owner/repo pass `url.PathEscape` unchanged - refused; `commit_read get` panics on an empty answer (recovered by upstream into a tool error) |
| Verification | built here from the fetched commit with the Dockerfile's steps (hash list, `go mod verify`, linked-package check, `go vet`, `go test`); `src/main_test.go`: every method of the 28 read tools against a recording fake Gitea - only GET, only `/api/v1/`, no token in an answer; the smoke spec over stdio: 33 of 33 passed |
| Risks left | the user's token decides what writes can do (`GITEA_WRITE=1`); texts from Gitea are untrusted; a Gitea with a private CA cannot be reached yet (no CA option offered) |
| Effort | 5 h |

## github (github/github-mcp-server) - not added

| | |
|---|---|
| Verdict | **not added**: its complete review does not fit; an own thin server is the way if GitHub is wanted |
| Looked at | v2.1.0 (tag commit `4bcdcdf8`, published 2026-11-03: 22 days; v2.2.0 of 11-16 and v2.3.0 of 11-24 too new), archive SHA-256 `fb85acd5...705e` |
| Size | a build of `cmd/github-mcp-server` links **315,705 lines** of Go: its own `pkg/github` alone 42,239 (one package: every toolset is linked whatever `--toolsets` says), go-github v92 110,153, x/sys, x/text, x/net, the MCP Go SDK, cobra/viper/pflag, yaml, toml, bluemonday ... |
| Also | `pkg/github/ui_embed.go` embeds HTML built by Vite from `ui/` (a React app, `ui/package-lock.json` 3,252 lines of npm dependencies) - reviewing it means reviewing that npm tree or building without the UI; hosts in code besides GitHub's: `api.githubcopilot.com` (remote mode), `insiders.vscode.dev` (install links) |
| Not found (in a search, not a review) | telemetry: `pkg/observability` is a no-op metrics sink and slog |
| Way forward | (a) an own small read-only server over GitHub's REST API (search, files, issues, pull requests with files and diffs, Actions runs and logs), like osv and wikipedia: 8-12 h, reviewed by construction; or (b) the full review of 2.x (the research's 30-40 h estimate holds) |

## semgrep (`semgrep mcp`) - not added

| | |
|---|---|
| Verdict | **not added**: its engine cannot be reviewed or rebuilt here, and its MCP mode reports to Semgrep by default |
| Looked at | semgrep **1.184.0** (PyPI, 2026-11-05: 20 days; 1.185 to 1.187 too new), manylinux x86_64 wheel SHA-256 `d847abb8...00d9` |
| Engine | `semgrep/bin/semgrep-core`, a **267 MB prebuilt OCaml binary** inside the wheel (LGPL-2.1; its OCaml source is not in the wheel) - the same reason codebase-memory stayed out; building it from semgrep's source needs the OCaml/opam toolchain in CI |
| Telemetry | `semgrep mcp` turns tracing and metrics **on** (`start_tracing`: OpenTelemetry to `telemetry.semgrep.dev`, `MetricsState.ON` to `metrics.semgrep.dev`) with the git username, repository and branch, an anonymous user id and deployment data, unless `SEMGREP_MCP_DISABLE_TRACING=true`; network none would stop the sending, the switch must be set too |
| Other | default rules come from the semgrep.dev registry (`--config auto`); `semgrep_findings`, `semgrep_scan_remote` and `semgrep_scan_supply_chain` need a semgrep.dev token; it publishes prompts and resources (tools_only needed); Python side 52,857 lines + OpenTelemetry, peewee, rich, ruamel ... |
| Way forward | an own thin MCP server over the `semgrep` CLI with `--metrics=off`, local rule files only (a mounted folder), network none - once `semgrep-core` is built from a pinned source tag in CI (opam), or opengrep's equivalent; 16-24 h + CI |

## codebase-memory - stays out

Round 1's reasons hold (`candidates/codebase-memory/PROVENANCE.md`, `docs/CANDIDATES.md`): v0.12.1 (2026-10-16) is still
the newest release; what would ship is the prebuilt static binary; its repository's own C below `src/` alone is about
9 MB (pipeline 3.8 MB, mcp 1.9 MB, cli 1.5 MB, daemon 1.0 MB, ...) beside 1.27 GB of vendored tree-sitter grammars in
`internal/cbm` - not reviewable completely here. code-search (ours) covers definitions, references, outlines and a
project map; lsp-python/lsp-go now add a language server's precision.

## Language servers - our own bridge (lsp-python, lsp-go added; lsp-c, lsp-rust designed)

The research's upstream (isaacphi/mcp-language-server) is stale (2025-05) and writes (`edit_file`, `rename_symbol`).
Ours: `servers/lsp-*/src/server.py`, one bridge file for every language, six read-only tools, a position given as a
line and the symbol's name (small models find that easier than columns), files only inside the read-only project.
Design decision: **the image ships the language server and what it needs**; a sandbox-ai toolchain cannot be attached
to an MCP server's container today, and the language servers need more than the toolchains ship (gopls, pyright and
rust-analyzer are not in them). Per language one image, so each stays as small as its language allows and its
network none:

| Image | Language server | What else it needs | State |
|---|---|---|---|
| lsp-python | pyright 1.1.414 (npm tarball by SHA-256, no npm) | Node.js 20 (Debian), python3 for its search paths | added, verified here against pyright |
| lsp-go | gopls v0.24.0 (built from its module, sum.golang.org hash) | Go 1.27.4 (`go list`), GOPROXY=off, telemetry off | added, verified here against gopls |
| lsp-c | clangd-19 (Debian `1:19.1.7-3+b1`) | libc6-dev `2.41-12+deb13u5`, libstdc++-14-dev `14.2.0-19` for the system headers; `compile_commands.json` in the project | designed; the bridge already knows clangd (`--background-index=false --clang-tidy=false`); not built or run yet |
| lsp-rust | rust-analyzer (the Rust project's rustup component) | cargo, rustc and rust-src of the same toolchain (the rust image of servers/whatsapp); `CARGO_NET_OFFLINE`, `checkOnSave`, build scripts and proc macros off | designed; static.rust-lang.org is blocked here, so it can only be built and smoked in CI |

The language servers themselves (pyright, gopls with Go) are the vendors' own large programs and were reviewed on
what they can do at run time (network, telemetry, processes, files), like the browsers of playwright; see each
PROVENANCE.md. Effort: 6 h for the bridge and the two images.
