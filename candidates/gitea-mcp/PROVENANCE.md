# gitea-mcp - candidate, not admitted yet (review of 2026-11-18, round 2)

**Review of 2026-11-18 (round 2): not added.** The verdict and its reasons are in `docs/round2-reviews.md`; this
folder keeps what was found, for the next attempt. Nothing here is built.

## The pin (verified - gitea.com answered this time)

gitea.com was reachable from this machine on 2026-11-18 (the brief expected it not to be); its API
(`/api/v1/repos/gitea/gitea-mcp/releases`, `/tags`) gave:

| Release | Published (UTC) | Commit | Age on 2026-11-18 |
|---|---|---|---|
| v1.13.0 | 2026-11-06 05:39 (tag 2026-11-05 18:27) | `34ba56e9a95d3a59113a293f1263685c3986f37c` | 12 days: too new until 2026-11-20 |
| **v1.12.0** | **2026-10-30 18:58** | **`9c3166fcd78c2eea03cb697d88ac243cda9aff97`** | **19 days: the pin** |
| v1.11.0 | 2026-10-22 23:50 | `21f40d77ee66ec332da07d721df69579638b2142` | 27 days |

Source archive `https://gitea.com/gitea/gitea-mcp/archive/v1.12.0.tar.gz`, SHA-256
`4474a6879175e0d39bae98cb0b3feb4b0cac6e86724b30bf977b0a14d7e70dbf`. Correction to the first pass: v1.13.0 was
published on 2026-11-06 (its tag on 11-05), so it is old enough only from 2026-11-20.

## First look at v1.12.0 (not a complete review)

- Size: **10,693 lines of Go** outside tests (`operation/` 24 packages, `internal/`, `cmd/`); `pull.go` 1,202,
  `issue.go` 674, `actions/runs.go` 657.
- Modules (`go.mod`): `github.com/modelcontextprotocol/go-sdk` v1.8.0 (the official MCP Go SDK: 22,326 lines outside
  tests and examples), `gitea.dev/sdk` v1.3.0 (Gitea's Go SDK; `gitea.dev` did not answer from here), `go.uber.org/zap`
  v1.28.0 (+ exp), and indirectly `golang.org/x/crypto`, `x/oauth2`, `x/sync`, `x/sys`, `x/time`, `x/tools`,
  `segmentio/encoding` + `segmentio/asm`, `google/jsonschema-go`, `42wim/httpsig`, `davidmz/go-pageant`,
  `hashicorp/go-version`, `yosida95/uritemplate`. None of them is reviewed in this repository (engram uses mcp-go, not
  the official Go SDK). proxy.golang.org was not reachable from here.
- About 40 tools in 24 groups (issues, pulls, repos, files, branches, releases, labels, milestones, wiki, actions
  runs and artifacts, packages, notifications, time tracking, projects, search, users, orgs); many write (create,
  update, delete, merge, file commits). `-r`/`--read-only` exposes only read-only tools, `-O`/`GITEA_TOOLS` and
  `-S`/`GITEA_SCOPES` cut the list - good for local models.
- Network: one Gitea host (`-H`/`GITEA_HOST`, **default `https://gitea.com`**: an entry must set it), or a Unix socket;
  `-k`/`GITEA_INSECURE` turns TLS verification off; `GITEA_EXTRA_HEADERS` adds headers; mTLS options; an HTTP
  transport with optional OAuth (not used over stdio). No other host and no telemetry found by a scan of the URLs; no
  `os/exec`.
- Token: `-T`, `GITEA_ACCESS_TOKEN` or `GITEA_ACCESS_TOKEN_FILE`.
- Attachments: images inlined up to 5 MiB (`-max-inline-attachment-bytes`): an answer bound is needed.

## Why not added in this round

A complete review to this repository's standard (every linked line of gitea-mcp and of the MCP SDK it is built on,
the other modules on their risky surfaces, as for engram) is 12-20 h for gitea-mcp's 10,693 lines plus the Go SDK's
22,326 and the linked part of Gitea's SDK; it did not fit into this round after the other eight servers. Nothing found
so far argues against it.

## Plan for the next round

1. Review v1.12.0 (or v1.13.0 from 2026-11-20) completely: `cmd/`, `internal/`, every `operation/` package; the Go
   SDK's server, stdio transport and JSON-RPC; Gitea's SDK client; zap on its file/sink surfaces.
2. Image: build from the pinned commit with `go mod download && go mod verify` (CI reaches proxy.golang.org),
   `CGO_ENABLED=0`, entry point `gitea-mcp -t stdio -r` (read-only by default; writes only when the human drops `-r`),
   `GITEA_HOST` required (no default to gitea.com), `GITEA_INSECURE` refused, an answer bound of 24,000 characters (an
   own small wrapper or a patch), tools-only checked.
3. Entry: `network: allowlist` with the user's Gitea host (sandbox-ai adds it at `mcp add`), secret
   `GITEA_ACCESS_TOKEN`.
