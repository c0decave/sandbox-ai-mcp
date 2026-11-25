# gitea - provenance and audit

| | |
|---|---|
| Upstream | gitea/gitea-mcp **v1.13.0** (MIT, `LICENSES/gitea-mcp-MIT.txt`), Gitea's own MCP server, tag commit `34ba56e9a95d3a59113a293f1263685c3986f37c` (tag 2026-11-05 18:27 UTC, release published 2026-11-06 05:39 UTC: 19 days before this review); source archive `https://gitea.com/gitea/gitea-mcp/archive/v1.13.0.tar.gz` SHA-256 `7f4a2ba841673ae31c8e48003f1ef2d0a5034f8e5fb734e3e57d9dedc3bdda8c` (the files of the archive and of a `git fetch` of the commit are the same) |
| In the image | `/usr/local/bin/gitea-mcp`: this repository's entry point `src/main.go` (MIT) built inside gitea-mcp's module at that commit as `cmd/sandbox-ai-mcp`; of gitea-mcp it links its `operation` packages (the tools) and `internal` packages: `gitea-mcp-files.sha256`, 53 Go files with 10,227 lines plus `go.mod`, `go.sum`, `LICENSE`, each checked by SHA-256 in the build before anything is downloaded; the build fails if any other package or file of gitea-mcp is linked. Not built: upstream's `main.go` and `cmd/` (flags, HTTP transport, OAuth provider wiring, health check, token file) |
| Go modules | by `go.sum` of the commit, `go mod download && go mod verify` in the build (proxy.golang.org, checked against sum.golang.org): `gitea.dev/sdk` v1.5.0 (Gitea's Go SDK, MIT, 2026-10-27, `gitea.com/gitea/go-sdk` commit `16e9d24b`), `github.com/modelcontextprotocol/go-sdk` v1.8.0 (the official MCP Go SDK, MIT/Apache-2.0, 2026-09-04, commit `3f3b699b`), `golang.org/x/crypto` v0.58.0, `x/oauth2` v0.36.0, `x/sync` v0.22.0, `x/sys` v0.49.0, `x/time` v0.15.0 (BSD-3-Clause), `github.com/segmentio/encoding` v0.5.4 and `segmentio/asm` v1.2.1 (MIT, MIT-0), `google/jsonschema-go` v0.4.3 (MIT), `yosida95/uritemplate/v3` v3.0.2 (BSD-3-Clause), `42wim/httpsig` v1.3.0 (BSD-3-Clause), `hashicorp/go-version` v1.9.0 (MPL-2.0); every one older than the release (a lockfile of the release commit) |
| Build image | `golang:1.27-trixie` (Go 1.27.4) `sha256:c47c3fda018d13d43a6bf5ebac3e5bba8a23a35782aa4faf531afaf47c64c39f`, as docker-library/repo-info recorded it on 2026-11-10 (commit `2d1d058f`; its newest layers of 2026-11-10, 15 days old); not in the final image. `CGO_ENABLED=0`, `GOTOOLCHAIN=local`, `-mod=readonly`, `-trimpath`, Go's telemetry off |
| Debian packages | `tini=0.19.0-3+b8` (the image's init, its ENTRYPOINT: no host init needed), `ca-certificates=20250419+deb13u1` (an https:// Gitea) |
| Base image | the `debian:trixie-slim` digest in `Dockerfile` |

**Upstream:** https://gitea.com/gitea/gitea-mcp, maintained by the Gitea project (releases every one to two weeks since
2025). One Go binary: MCP over stdio or streamable HTTP (optionally with OAuth against Gitea), about 40 tools in 19
scopes, many of them "`<scope>_read`"/"`<scope>_write`" tools that pick their operation with a `method` argument.
gitea.com answered from here (the round-2 note expected it not to); `gitea.dev` (the SDK's vanity host) does not
answer, proxy.golang.org serves its module. storage.googleapis.com, where proxy.golang.org redirects some module zips,
is blocked here: `segmentio/encoding` was fetched with `GOPROXY=direct` from GitHub and checked against
sum.golang.org like the others (CI reaches both).

**Pinning rule:** v1.13.0 (published 2026-11-06) is the newest release; it is 19 days old. v1.12.0 (2026-10-30, round
2's pin) is superseded: v1.13.0 replaces zap by log/slog (one module less), adds `get_job_log_preview`'s `pattern`
and `offset`, and fixes the token-file decoding.

## The review (2026-11-25)

Read in full: every linked file of gitea-mcp (`internal/*`: flag, gitea - the HTTP client, its transport, REST helper
and attachment download -, tool - registration, read-only filter, scopes, method dispatch, panic recovery -, params,
to, slim, attachment, annotation, oauth, log, context; `operation/*`: every handler of actions, issue, label,
milestone, notification, packages, project, pull, repo - branch, commit, file, release, repo, tag, tree -, search,
timetracking, user, version, wiki) and upstream's `main.go` and `cmd/` (not linked). Gitea's SDK (17,064 linked lines)
was read on its request path (`client.go`: `NewClient`, `doRequest`, auth, redirects, the storage redirect, version
check; `helper.go`; the path escaping `escapeValidatePathSegments`) and searched in full for anything but requests to
the configured host (no other host, no `os/exec`, files only in the SSH-signing helpers `httpsign*.go`, which only
`UseSSHCert`/`UseSSHPubkey` turn on - gitea-mcp never does). The MCP Go SDK (18,779 linked lines) was read on the
server path (stdio transport with its line limit, JSON-RPC framing, `tools/list` and `tools/call` dispatch,
middleware) and searched in full: its HTTP client code (`sse.go`, `streamable.go` client, `oauthex`, `auth`) is
linked but only reached in HTTP and client modes, which this entry point never starts; `oauthex`'s
`https://check-proxy-existence.com` is a request object only built to ask a transport's proxy function, never sent;
`mcp/cmd.go`'s `os/exec` is the client's command transport. Go's x/ modules (crypto: linked for `ssh` signing in the
SDK, unused here) were searched for network, file and process use only.

- **Network:** every request goes to `GITEA_HOST` + `/api/v1/...` (gitea-mcp's `DoJSON`/`DoBytes`, the SDK's
  `c.url+path`) or `/attachments/` (the attachment download, refused here). Redirects: at most 10, a non-GET request
  never follows one, attachment downloads only to the same origin. Proxy variables are honoured (Go's default
  transport). No other host, no telemetry, no update check, no version check beyond Gitea's own `/api/v1/version`.
  A dynamic check (`src/main_test.go`, run in the build): every method of every one of the 28 read tools against a
  recording fake Gitea sent only `GET` requests, only under `/api/v1/`, and no answer contained the token.
- **Files:** upstream writes downloads (job logs, artifacts, attachments, release assets) to `$HOME/.gitea-mcp/...` or
  to any `output_path` the caller names (`os.MkdirAll` + write, mode 0600) - in a container that is a file no agent
  can read. The entry point takes `output_path` out of every schema and refuses it, and takes the four download
  methods out of their method lists and refuses them. Nothing else of the linked code writes files (the health-check
  file and token file are upstream's `cmd`/HTTP mode, not linked or not reached).
- **Processes:** none (`os/exec` is not used by gitea-mcp or Gitea's SDK).
- **Paths of the API:** every name is `url.PathEscape`d (gitea-mcp and the SDK), which keeps `.` and `..`; Gitea could
  resolve `repos/../...` to another endpoint (with the same token). The entry point refuses `.`/`..` and slashes in
  owner, repo, org, username, team, workflow and Actions-secret names; `get_file_contents` refuses `.`/`..` path
  segments itself. Branch, tag and label names may hold slashes and are left as gitea-mcp escapes them.
- **Read-only:** `tool.Tools()` lists a scope's write tools only when `flag.ReadOnly` is false; the entry point sets it
  from `GITEA_WRITE=1` alone. Every read tool's handler sends only GET (test above). With writes on, the write tools
  create, change and delete issues, comments, pull requests (merge included), reviews, files (one commit per call),
  branches, tags, releases and assets, labels, milestones, projects, wiki pages, Actions runs, secrets and variables,
  branch protections, organisations: have sandbox-ai ask for each call; a read-only token keeps Gitea from accepting
  any of them.
- **Secrets:** the token goes only into the `Authorization: token ...` header to `GITEA_HOST`; Actions secrets are
  listed by name only (`toSecretMetas`), their values are never read. Errors carry at most 8 KiB of Gitea's answer.
- **Answers:** upstream's answers are compact JSON ("slim" maps), but unbounded: a file, a diff, a log preview of up
  to `max_bytes`, a list with a large `per_page`. The entry point cuts every answer at 24,000 characters with a note
  saying how to ask for less, drops `structuredContent` (the same JSON again, set for `get_file_contents`) and
  images (upstream inlines image attachments up to 5 MiB; `MaxInlineAttachmentBytes` is 0 here).
- **Robustness:** a panic in a handler becomes a tool error (upstream's `MCPHandler`; seen with the fake Gitea:
  `commit_read` `get` on an empty answer); arguments are at most 512 KiB of JSON, stdin lines at most 4 MiB (the
  SDK's default is 16 MiB). TLS is always verified: upstream's `-insecure`, client certificates, CA file, Unix socket,
  extra headers and OAuth are not reachable (the entry point sets none of them and parses no flags).
- **Host:** upstream falls back to `https://gitea.com`; the entry point requires `GITEA_HOST` (http or https, a host,
  optionally a port and a path; no user, query or fragment). Without it the server starts, lists its tools and every
  call says what is missing (so `mcp add` can list it before the variable is set).
- **Capabilities:** tools only (`ServerCapabilities{Tools}`), no resources or prompts.

**Not found:** telemetry, analytics, update checks, other hosts, obfuscated code, `init()` functions doing more than
registering tools, `unsafe` outside the Go x/ and segmentio modules' well-known uses.

## Tools

Read-only (default): the 28 tools of `tools.json`. With `GITEA_WRITE=1` also `actions_config_write`,
`actions_run_write`, `branch_write`, `commit_write`, `create_or_update_file`, `delete_file`, `create_organization`,
`issue_write`, `label_write`, `milestone_write`, `notification_write`, `package_write`, `project_write`,
`pull_request_write`, `pull_request_review_write`, `release_write`, `repo_write`, `tag_write`, `timetracking_write`,
`wiki_write`. `GITEA_SCOPES` and `GITEA_TOOLS` cut the list as upstream's `-S` and `-O` do.

## Smoke

`smoke.json` calls every one of the 28 tools: `get_gitea_mcp_server_version` answers; the other 27 are called with
`GITEA_HOST=http://127.0.0.1:9` (nothing listens there) and must answer the connection error naming their API path
(`127.0.0.1:9/api/v1/...`) - the tool, its argument handling and its request are exercised, no Gitea is needed. The
refused calls (a download method, `output_path`, `..` as owner, a write tool without `GITEA_WRITE`) must be refused.
What each tool does with Gitea's answers is tested in the build (`src/main_test.go`, a fake Gitea); a real Gitea
(the user's) is the live check.
