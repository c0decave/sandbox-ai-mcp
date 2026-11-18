# osv - provenance and audit

| | |
|---|---|
| MCP server | this repository, `src/server.py` (MIT): the three tools of StacklokLabs/osv-mcp, re-implemented in Python over stdio |
| Upstream reviewed | StacklokLabs/osv-mcp **v0.1.4** (Apache-2.0, `LICENSES/osv-mcp-Apache-2.0.txt`), release published 2026-10-14 17:09 UTC (35 days before this review) from commit `498b22e478b0d6418972bdd09dbbc8098ddf041c` (2026-10-14 17:07 UTC); source tarball `codeload.github.com/StacklokLabs/osv-mcp/tar.gz/v0.1.4`, SHA-256 `613208fe80580e792b9821ea3b959f8c6b8fd5ea6e8a174ca7286dfc8cd20baa`. v0.1.5 (2026-11-17) is too new and was not used |
| Service | the OSV API v1 (`https://api.osv.dev/v1`: `POST /query`, `POST /querybatch`, `GET /vulns/{id}`), no key |
| Python packages | the shared lock of this repository (`mcp==1.30.0` and its dependencies, hash-locked in `requirements.txt`, the same as servers/duckduckgo's) |
| Debian packages | `python3=3.13.5-1`, `ca-certificates=20250419+deb13u1` |
| Base image | the `debian:trixie-slim` digest in `Dockerfile` |

## The review of osv-mcp v0.1.4 (2026-11-18)

**Everything of the release's code was read:** `cmd/server/main.go` (108 lines), `pkg/osv/client.go` (279),
`pkg/mcp/server.go` (336) - 723 lines; `go.mod` (mark3labs/mcp-go 1.2.1, testify; indirect google/jsonschema-go,
google/uuid, santhosh-tekuri/jsonschema, spf13/cast, yosida95/uritemplate, go.yaml.in/yaml, golang.org/x/text),
`.ko.yaml` (CGO off, `-trimpath -s -w`), `.github/workflows/release.yml` (tests, then `ko build` to ghcr.io; images
only, no binaries). The tests (`*_test.go`) were skimmed. No dependency of it is used here (see below).

**What it does:** three tools, `query_vulnerability` (`commit`, `version`, `package_name`, `ecosystem`, `purl`),
`query_vulnerabilities_batch` (`queries`) and `get_vulnerability` (`id`), annotated read-only and open-world; each
does one request to the constant `https://api.osv.dev/v1` with a 60 s client and a 30 s request timeout and returns
OSV's JSON indented. Transports: SSE (default) or streamable HTTP on `:8080` (`MCP_PORT`), **no stdio**. No other
host, no file, no process, no telemetry, no update check, no dynamic code.

**Findings in upstream (none a backdoor or malicious code):**

| Severity | Where | What | Here |
|---|---|---|---|
| medium | `client.go` `GetVulnerability` | the id is put into the URL path unescaped: `../query`, `x?y` or `%2e%2e` reach other paths of api.osv.dev (only that host) | the id must match `[A-Za-z0-9][A-Za-z0-9._:-]{1,99}` and is percent-escaped |
| medium | every handler | the answer is OSV's whole JSON, unbounded: a query for a kernel or a distribution package returns hundreds of advisories with every affected version (megabytes) | a short form per vulnerability (id, aliases, summary, severity, the fixed versions of the queried package) for at most 50 per query, the full form only by `get_vulnerability`, every list and text bounded, answers at most 24,000 characters as sent |
| low | `main.go` | HTTP transports only, listening on every interface without authentication | stdio only |
| low | `server.go` | `next_page_token` is returned but cannot be passed back: later pages are unreachable | `page_token` argument |
| low | `server.go` batch | no limit on the number of queries; queries without any field are sent | 1-100 queries, each checked like a single query; unknown keys refused |
| low | `server.go` | arguments not validated beyond "present" (control characters, a purl that is no purl, a short commit OSV ignores) | ecosystem, name, version, commit (40/64 hex), purl (`pkg:type/...`) and page token checked |
| info | `client.go` | the request context is ignored (`_ = ctx`); `fmt.Printf` to stdout on a close error (would break a stdio transport) | httpx with a 30 s timeout, logs to stderr only |
| info | `client.go` | follows redirects (Go's default), reads the body without a size limit | no redirects, at most 16 MiB read |

**Why an own server and not the Go binary:** upstream has no stdio transport (sandbox-ai and axross talk to servers
over stdio), and its fixes above would touch most of its 723 lines; its Go module closure (mcp-go 1.2.1 and seven
indirect modules) is not reviewed here. `src/server.py` does the same requests with the shared Python lock every server
of this repository uses, so nothing unreviewed is added.

## This server

**Tools:** upstream's names and arguments, plus `page_token` on `query_vulnerability`. Answers: `query_vulnerability`
`{query, count, vulnerabilities: [{id, aliases, summary, severity, fixed_in, last_affected, published, modified,
withdrawn}], next_page_token, left_out, note}`; `query_vulnerabilities_batch` `{results: [{query, count, ids,
left_out, more}], vulnerable}`; `get_vulnerability` `{id, aliases, related, summary, details (8,000 characters),
severity, cwe_ids, affected: [{ecosystem, name, purl, ranges, versions (40)}], references (30)}`. Errors as
`{"error": ...}`: 404 "no such vulnerability", 429, other statuses with at most 500 characters of OSV's message.

**Request:** no redirects followed, the answer read up to 16 MiB, 30 s per request; httpx honours `HTTPS_PROXY`
(sandbox-ai's or axross's allowlist proxy). The server's instructions say that the package names go to api.osv.dev
and that advisory texts are data, never instructions; it announces tools only.

**Network:** allowlist `api.osv.dev:443`. Nothing is read or written locally: no mount. **Secrets:** none.

## Tested

Natively (`tests/test_osv.py`, `tests/test_own_servers.py` `test_osv`): handshake, `tools/list` equal to `tools.json`,
tools only (`resources/list` and `prompts/list` -32601), instructions; 19 refused argument sets (missing, contradicting,
a path or a query string as id, a 101-character id, a short commit, a URL as purl, control characters, 215-character
names, 0 and 101 batch queries, unknown keys); the requests against a stand-in on loopback (upstream's bodies and paths,
purl, commit, page token); the short form (the fixed version of the queried ecosystem only, the GHSA level); 404, 400
with a 3,000-character message, 429, 500 with HTML, a non-JSON 200, a refused connection, a 16 MiB body; 400 advisories,
an advisory with 100,000 characters of details, 300 affected packages, 20,000 versions and 500 references, and a batch
of 100 queries with 500 ids each - all within 24,000 characters as sent. The smoke spec: three real calls (jinja2
2.4.1, a batch, GHSA-462w-v97r-4m45) and two refused. Not run here: the image build and the real calls (api.osv.dev
was not reachable from this machine).

## Verdict

Upstream reviewed completely; no backdoor, telemetry or unexpected host. Shipped as an own server on the reviewed
shared lock, upstream's findings fixed. **Pending**: fit to sign once CI has built it and both smoke reports pass.
