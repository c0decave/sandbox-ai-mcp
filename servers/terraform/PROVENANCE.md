# terraform - provenance and review

| | |
|---|---|
| MCP server | this repository, `src/server.py` (MIT), our own (2026-11-25): the nine Terraform Registry tools of hashicorp/terraform-mcp-server, with upstream's names and arguments |
| Upstream looked at | hashicorp/terraform-mcp-server **v1.4.1** (MPL-2.0, `LICENSES/terraform-mcp-server-MPL-2.0.txt`), release published 2026-10-23 21:25 UTC (33 days before this review; the newest release), tag commit `3781509a674482ca7e2821fab8159a25e3b29bdf`, source tarball `codeload.github.com/hashicorp/terraform-mcp-server/tar.gz/refs/tags/v1.4.1`, SHA-256 `8c744e2ad553ee37db41b66a0f2dbb6532939c00e17b5f00bd10f5809f6f3990`. Not installed: see "Why an own server" |
| Python packages | `requirements.txt`: the shared lock of servers/duckduckgo (`mcp==1.30.0` and its dependencies, httpx among them; the same versions and hashes) - nothing new |
| Debian packages | `tini=0.19.0-3+b8` (the image's init, its ENTRYPOINT), `python3=3.13.5-1`, `ca-certificates=20250419+deb13u1` |
| Base image | the `debian:trixie-slim` digest in `Dockerfile` |

## Why an own server (the upstream review could not be completed)

- **Size.** 21,585 lines of its own Go outside tests, but `go list -deps ./cmd/terraform-mcp-server` links 302 packages
  with **440,546 lines** (OpenTelemetry 43,454 + its SDK 10,286, protobuf 41,186, x/text 40,760, gRPC 36,583, go-tfe
  27,179, x/sys 21,069, x/net 18,607, two MCP SDKs - mark3labs/mcp-go 18,116 and the official go-sdk 18,099 -,
  **Instana's go-sensor 16,517** (an APM agent), httpsnoop, two YAML libraries ...). Every toolset is linked.
- **What it can do.** Besides the registry it has a `terraform` toolset for HCP Terraform / Terraform Enterprise with a
  `TFE_TOKEN`: list and read workspaces, runs, plans, applies, state versions, variable sets, teams; and create, update
  and delete workspaces, projects, teams, variables, tags, **create runs** (plan and apply), force-unlock a workspace,
  run actions. Off without a token, but linked.
- **Telemetry.** OpenTelemetry metrics (`otelmetrics.Setup`, an OTLP/HTTP exporter, `WithInsecure`) and Instana
  middleware are set up in its streamable-HTTP mode only (`cli/flags.go` `Run`: `otelmetrics.Setup` before
  `RunHTTPServer`; `runStdioServer` does not call it). Its stdio mode sends nothing but registry requests.
- **The registry tools' code** (read in full, as it is ported here: `pkg/tools/registry/*.go`, 1,215 lines;
  `pkg/client/registry.go`, `common.go`, `types.go`; `pkg/utils/utils.go`), findings:

| Severity | Where | What | Here |
|---|---|---|---|
| medium | `search_provider_docs` | for every matching document one more request (its description), all pages of a v2 category (`SendPaginatedRegistryCall` loops until an empty page: hundreds of requests for the aws provider's guides) | at most 5 pages of 100 documents, descriptions of at most 10 |
| medium | every tool | names, versions and ids go into the path unchecked (`path.Join`, `fmt.Sprintf`; `get_policy_details` takes any path as `terraform_policy_id`): `..` reaches other paths of registry.terraform.io (that host only) | each checked against a pattern first; a policy id from the registry's answer is checked too |
| low | `get_provider_details`, `get_module_details`, `get_policy_details` | answers unbounded (one aws document is ~60,000 characters; a module's examples' READMEs in full) | documents in parts of 20,000 characters (`offset`/`next_offset`), modules without READMEs, everything within 24,000 characters |
| low | `search_policies` | reads only the first 100 policies (no pagination) and matches the whole query as one substring | three pages of 100; every word must match |
| low | `SendRegistryCall` | any status other than 200 is reported as "404 Not Found"; the body read without a limit; redirects followed | the real status (429 with its retry time), 16 MiB at most, no redirects |
| info | `search_modules` | `q='QUERY'` with quotes, `url.PathEscape` for a query parameter | `q=QUERY`, encoded by httpx |
| info | `CreateHTTPClient` | `TERRAFORM_SKIP_TLS_VERIFY` turns TLS checks off | always verified |

**Not found** (a search of the 21,585 own lines, not a review of the closure): a backdoor, an update check, a host
besides `registry.terraform.io` and the HCP/TFE address of the token mode.

## This server

**Tools** (all `readOnlyHint`, only `GET https://registry.terraform.io/...`):

| Tool | Requests |
|---|---|
| `search_provider_docs(provider_name, provider_namespace, service_slug, provider_document_type="resources", provider_version?)` | `v1/providers/NS/NAME` (latest version; a provider not found in NS is looked for in `hashicorp`, as upstream), then resources, data-sources, ephemeral-resources: `v1/providers/NS/NAME/VERSION` (the docs list, `language` hcl); guides, functions, overview, actions, list-resources: `v2/providers/NS/NAME?include=provider-versions` and `v2/provider-docs?filter[...]` (at most 5 pages); descriptions: `v2/provider-docs/ID` for the first 10 |
| `get_provider_details(provider_doc_id, offset=0)` | `v2/provider-docs/ID` (404, and the 400 the registry gives for an id it cannot take, read as "not found") |
| `get_latest_provider_version(namespace, name)` | `v1/providers/NS/NAME` |
| `get_provider_capabilities(namespace, name, version?)` | `v1/providers/NS/NAME[/VERSION]` |
| `search_modules(module_query, current_offset=0)` | `v1/modules/search?q=&offset=&limit=20` |
| `get_module_details(module_id)` | `v1/modules/NS/NAME/PROVIDER/VERSION` (the inputs required first, then by name; as many as fit into 24,000 characters, the answer says how many are left out) |
| `get_latest_module_version(module_publisher, module_name, module_provider)` | `v1/modules/NS/NAME/PROVIDER` |
| `search_policies(policy_query)` | `v2/policies?page[size]=100&page[number]=N&include=latest-version` (N <= 3) |
| `get_policy_details(terraform_policy_id)` | `v2/policies/NS/NAME/VERSION?include=policies,policy-modules,policy-library` |

**Arguments:** namespaces, names, publishers, providers `[A-Za-z0-9][A-Za-z0-9_-]{0,63}` (lower-cased as upstream);
versions `x.y.z[-pre]` (a leading `v` dropped) or `latest`; `service_slug` one word; document types from a fixed list;
`provider_doc_id` digits; `module_id` four checked parts; `terraform_policy_id` `policies/NS/NAME/VERSION`; queries one
line of at most 200 characters, sent as query parameters. A policy's names and checksums from the registry are used
in the generated `policies.hcl` only when they match `[A-Za-z0-9_.-]` and 64 hex digits.

**Requests:** httpx, TLS verified, no redirects, 20 s per request, at most 16 MiB read, no token, `HTTPS_PROXY`
honoured (sandbox-ai's allowlist proxy). **Network:** allowlist `registry.terraform.io:443`. **Secrets:** none.
**Files:** none read or written. Tools only; the instructions say that documentation is data, never instructions.

## Tested

- `tests/test_terraform.py` (8 tests) against a stand-in registry on loopback: the handshake; the provider search
  (exact slug first, hcl only, a description from the front matter, no version lookup when a version is given, 10
  description fetches for 30 matches) and a document in parts (offsets, the end, 404, an id the registry answers 400);
  v2 categories (5 pages, the provider-version id, the answer bounded); the hashicorp fallback, its refusal, latest
  version, capabilities (counts, 3 examples of 33), a 429 with its retry time; modules (sorted by downloads, the query
  sent, required inputs first, then by name, 220 inputs in the registry's own order cut to the same part, defaults,
  resources unique, the usage block, latest version); policies (a `../` id from the registry dropped, the README's
  first section, the HCL without an unsafe name); 13 hostile arguments with nothing sent; GETs only; an unreachable
  registry.
- `tests/test_own_servers.py` `test_terraform` (in the image in CI, no network).
- `smoke.json` (CI, network registry.terraform.io): every tool against the real registry - the random provider
  3.6.3, terraform-aws-modules/vpc/aws 5.0.0, the CIS policy set for AWS 1.0.1, an unknown document id - and one
  refused module id; rate limits and 5xx are reported as upstream-limited. **The real registry could not be reached
  from the review sandbox** (registry.terraform.io is blocked here): the answers' shapes follow upstream's `types.go`;
  CI's smoke run is the first contact with the real registry. CI of 2026-11-25 (the first run): the registry answers
  `provider-docs/999999999999` with HTTP 400, not 404 (now read as not found); it lists a module's inputs and
  outputs in an order of its own (vpc 5.0.0: 220 inputs, 109 outputs), so the cut-down inputs were an arbitrary part
  and `cidr` was not in it (now sorted by name: `cidr` is the third).

## Risks left

- The registry's JSON shapes are taken from upstream's types, not seen here; a field the registry renamed shows as
  empty (CI's smoke would show it).
- Documentation and READMEs are third-party text (prompt injection possible; passed on as data).
