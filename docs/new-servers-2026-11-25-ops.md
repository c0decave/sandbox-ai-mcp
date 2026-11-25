# New servers of 2026-11-25: operations and mail (kubernetes, terraform, grafana, reddit, imap)

Tier 1 and 2 of `/work/research-llm/mcp-additions-2026-11-25.md`, the share of the agent mcpnew-ops (the others:
mcpnew-dev, mcpnew-data, mcpnew-sec, mcphard). Rules as in [round2-reviews.md](round2-reviews.md): the whole code that
runs read or reviewed, a release pinned only when it is at least 14 days old (cut-off for this round: published
before 2026-11-11), no telemetry, no install script, no auto-update, tools only, answers within 24,000 characters,
hostile inputs tested; and the hardening round's conventions: tini as ENTRYPOINT, a smoke call for every tool.
Nothing here is signed or published: each server is a **pending** catalog entry (digest `null` in `digests.json`)
until CI has built it, its smoke reports pass and the catalog is signed with the human.

**The common finding:** the three official Go servers link 0.4 to 1.7 million lines each - more than round 2 and
mcpnew-dev refused for github-mcp-server (315,705) - and each also drives writes (applies, deletes, runs, dashboard
and alert changes) that a flag hides. As mcpnew-data did where upstream is too big to review completely, their read
tools are taken over as **own servers on the shared, reviewed lock** (`mcp==1.30.0` + httpx), read-only by
construction: only GET requests, no write tool at all. The same for reddit (its npm closure stays out) and imap (no
upstream fits). Secrets are catalog variables of their own (`secret: true`), never part of a URL or a connection
string.

Each server was run before publishing (the user's condition): there is no Podman here, so each ran from its sources in
a throwaway Python 3.13 venv made from its hash-locked `requirements.txt`, over stdio as its image starts it
(`python -I -u server.py`), twice: with its smoke spec (`smoke.json`), and against its stand-in service from `tests/`
(TLS with a throwaway CA where the service has TLS) with a real call of every tool.

## Overview

| Server | Verdict | Pin / source | Network | Secret | Tools (smoked) | stdio here |
|---|---|---|---|---|---|---|
| [kubernetes](../servers/kubernetes) | upstream **stays out** (1,714,441 linked lines); **added, pending** as an own read-only server | containers/kubernetes-mcp-server v0.1.2 (2026-11-04) looked at; PyYAML 6.0.3 (capa's pin) | egress-all (the cluster) | `KUBECONFIG_DATA` | 7 (7) | smoke 9/9, stand-in 7/7 |
| [terraform](../servers/terraform) | upstream **stays out** (440,546 linked lines, Instana and OTel linked, HCP write tools); **added, pending** as an own server | hashicorp/terraform-mcp-server v1.4.1 (2026-10-23), its registry tools read in full | allowlist `registry.terraform.io:443` | - | 9 (9) | stand-in 9/9; smoke needs the registry (blocked here: CI) |
| [grafana](../servers/grafana) | upstream **stays out** (1,495,449 linked lines, 116 tools, writes, `grafana_api_request`); **added, pending** as an own read-only server | grafana/mcp-grafana v2.3.0 (2026-11-10) looked at | egress-all (your Grafana) | `GRAFANA_SERVICE_ACCOUNT_TOKEN` | 9 (9) | smoke 11/11, stand-in 9/9 |
| [reddit](../servers/reddit) | npm package **stays out** (MCP SDK 1.x closure, write tools in 1.2); **added, pending** as an own app-only read server; `candidates/reddit` removed | reddit-mcp-buddy 1.2.1 (2026-11-10) reviewed on its read path | allowlist `www.reddit.com:443`, `oauth.reddit.com:443` | `REDDIT_CLIENT_SECRET` | 4 (4) | smoke 6/6, stand-in 4/4 |
| [imap](../servers/imap) | **added, pending** (own, standard library); mcp-email-server stays out | - | egress-all (your mail server) | `IMAP_PASSWORD` | 4 (4) | smoke 6/6, stand-in 4/4 |

## kubernetes - upstream stays out; own read-only server added (pending)

| | |
|---|---|
| Upstream | containers/kubernetes-mcp-server **v0.1.2** (Apache-2.0, 2026-11-04, 21 days; v0.1.3 of 11-13 too new), tarball `3e54fdd9...1f7b`. 41,833 own lines; `go list -deps` of its command: 1,189 packages, 1,714,441 lines (k8s.io/api, client-go, apimachinery, OpenTelemetry, cel-go, gRPC, Prometheus, Helm ...). Default toolsets include apply, delete, scale, `pods_exec`, `pods_run`, Helm install, KubeVirt, Tekton; `read_only` is a flag. `resources_get` returns Secrets with their data unless `denied_resources` lists them. OTel telemetry optional (off by default). No backdoor or update check found in the own code (a search, not a review of the closure) |
| This server | 7 tools: `cluster_info`, `namespaces_list`, `api_resources_list` (aggregated discovery v2, per-group fallback), `resources_list` (the cluster's Table form: kubectl's columns for any kind), `resources_get` (managedFields and last-applied left out; a Secret's values replaced; `section`), `pods_log` (tail, previous, since; the newest 24,000 characters), `events_list` (newest first). Only GETs; no redirects |
| Kubeconfig | the secret `KUBECONFIG_DATA` (YAML/JSON or base64), `yaml.safe_load`; token, client certificate (loaded from 0600 files in /tmp, removed at once), Basic; refused: http, insecure-skip-tls-verify, file paths, proxy-url, exec plugins, auth-provider, impersonation |
| Tests | `tests/test_kubernetes.py` 11 (real TLS against a stand-in API server: token, client certificate, base64/JSON, an unknown CA, 15 refused kubeconfigs, Table form, Secret redaction, logs, events, discovery, 15 hostile arguments, GETs only, a redirect, 3,000 namespaces bounded) |
| Tor | limited (TCP to the API server; one in the local network not through Tor) |
| Risks left | RBAC is the boundary (Secret names and keys visible to a token that may list them); logs carry whatever workloads print; not run against a real cluster |

## terraform - upstream stays out; own registry server added (pending)

| | |
|---|---|
| Upstream | hashicorp/terraform-mcp-server **v1.4.1** (MPL-2.0, 2026-10-23, 33 days), tarball `8c744e2a...3f990`. 21,585 own lines; 302 linked packages, 440,546 lines (OpenTelemetry, gRPC, go-tfe, two MCP SDKs, Instana's go-sensor ...). HCP Terraform / TFE tools create runs, workspaces, variables (with a token). OTel metrics and Instana in its HTTP mode only. Its registry tools (1,215 lines + client) read in full: unchecked path parts, N+1 description fetches over all pages, unbounded answers, only 100 policies searched, every non-200 reported as 404 |
| This server | upstream's 9 registry tools with its names and arguments; checked identifiers; at most 5 pages and 10 description fetches; documents in parts of 20,000 characters; 3 pages of policies, all words must match; the real status (429 with its retry time); no token |
| Tests | `tests/test_terraform.py` 8 (a stand-in registry: v1 and v2 paths, the hashicorp fallback, bounded pages, modules, policies with a `../` id from the registry dropped, 13 hostile arguments, GETs only) |
| Smoke | every tool against the real registry in CI (random 3.6.3, terraform-aws-modules/vpc/aws 5.0.0, the CIS policy set 1.0.1, an unknown document id); 429/5xx count as upstream-limited. registry.terraform.io is blocked in the review sandbox: **CI's run is the first contact with the real registry** |
| Tor | limited |

## grafana - upstream stays out; own read-only server added (pending)

| | |
|---|---|
| Upstream | grafana/mcp-grafana **v2.3.0** (Apache-2.0, 2026-11-10 17:45 UTC, 14 days 18 hours; v2.4.0 of 11-24 too new), tarball `90857dbd...a659`. 47,890 own lines; 765 linked packages, 1,495,449 lines (Grafana's OpenAPI client, the Kafka client franz-go, the AWS SDK, Arrow ...). 116 tools with writes (dashboards, datasources, alert rules, incidents, plugin install), `grafana_api_request`, raw SQL "unfiltered"; hosts grafana.com (plugins, docs) and Grafana Cloud services. No backdoor or update check found in the own code (a search) |
| This server | 9 tools: `search_dashboards`, `get_dashboard_summary` (panels in rows, queries, variables), `list_datasources` (frontend-settings fallback for a Viewer), `query_prometheus` (range/instant; 50 series of 120 points), `list_prometheus_metric_names` (substring, no regex from the agent), `list_prometheus_label_values`, `query_loki_logs`, `list_loki_label_values`, `list_alert_rules`. The datasource proxy first, the resources endpoint as fallback (upstream's routing). Only GETs |
| Settings | `GRAFANA_URL`, the secret `GRAFANA_SERVICE_ACCOUNT_TOKEN`, `GRAFANA_ORG_ID`, `GRAFANA_CA_CERT` (a private CA) |
| Tests | `tests/test_grafana.py` 9 (real TLS with a private CA, the headers sent, the Viewer fallback, Prometheus bounded and thinned, Loki through the fallback, alerts, 6 refused settings and 12 refused arguments, GETs only, a redirect, times) |
| Tor | limited |
| Risks left | a Viewer can run any query its datasources allow; not run against a real Grafana |

## reddit - npm package stays out; own app-only read server added (pending)

| | |
|---|---|
| Round 1 open point | "read 1.2.0 completely, review the SDK 1.32.2 stdio path (or port the read tools onto the shared Python lock as for agentql), keep the write tools off" - **done as the port** |
| Upstream | reddit-mcp-buddy **1.2.1** (MIT, npm 2026-11-10 17:07 UTC; 1.3.0 of 11-11 09:02 too new), tarball `1f1f09fa...c6f3`: its read path read in full (tools, API client, auth, rate limiter, cache), the write tools, the consent listener and the CLI skimmed (off by default, not ported). Hosts only www/oauth.reddit.com; no telemetry. Reddit ended logged-out access on 2026-11-13: no anonymous mode left |
| This server | 4 tools: `browse_subreddit`, `search_reddit` (one request for several subreddits), `get_post_details` (by id or a reddit.com/redd.it link, never fetched), `user_analysis`. App-only OAuth (`client_credentials`) instead of upstream's password grant (full account scope); the token in memory only |
| Settings | `REDDIT_CLIENT_ID`, the secret `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT` (required; upstream's default named its author) |
| Tests | `tests/test_reddit.py` 6 (the token request, kept and renewed after a 401, GETs only after it, every tool's request, 429/403/404/wrong credentials/unreachable without the secret in any error, 18 hostile arguments, bounded answers) |
| Smoke | stand-in credentials, network none (the token request cannot be made) - CI has no approved Reddit app, and Reddit no longer approves new ones (2026-10-31) |
| Tor | limited (Reddit often blocks Tor exits) |

## imap - own read-only server added (pending)

| | |
|---|---|
| Why own | the registry pass's candidate (mcp-email-server 1.14.0) is 24,700 lines with a web UI and 75 releases and sends mail; the gap list asked for 4-5 tools without SMTP on `imaplib` |
| This server | 4 tools: `list_folders` (modified UTF-7, roles, counts), `search_messages` (criteria as quoted strings, one non-ASCII term as a literal with `CHARSET UTF-8`; newest first), `read_message` (plain text, or HTML as text; in parts), `list_attachments` (names, types, sizes - never contents). `EXAMINE` and `BODY.PEEK` only; no changing command in the file; no SMTP; TLS always (implicit or STARTTLS, verified, a private CA possible) |
| Tests | `tests/test_imap.py` 8 against a stand-in IMAP4rev1 server over real TLS (implicit and STARTTLS): folders, searches, messages, attachments, CA checks, a wrong password, 5 refused settings and 12 refused arguments (sequence sets, injected `\r\n` commands), after every test only reading commands and only `BODY.PEEK` |
| Tor | limited |
| Risks left | the password opens the mailbox to IMAP (this code is the read-only boundary; use an app password); mail is the classic prompt-injection carrier (research-memory's ruleset holds its results untrusted) |

## The stdio verification here (transcript summary)

`python -I -u servers/NAME/src/server.py` in a Python 3.13 venv of the server's lock, driven over stdio:

- **Smoke specs** (as CI runs them, network none here): kubernetes 9/9, grafana 11/11, reddit 6/6, imap 6/6 - every
  tool called; terraform 1/10 (its refused call; the nine real registry calls need registry.terraform.io, blocked
  here - CI).
- **Against the stand-ins** (`tests/`; TLS with a throwaway CA for kubernetes, grafana and imap; terraform and reddit
  pointed at theirs by a bootstrap that sets the base URL, their only fixed hosts): initialize answers tools only,
  tools/list equals `tools.json` for all five; real calls kubernetes 7/7, grafana 9/9, terraform 9/9, reddit 4/4,
  imap 4/4 - every answer within 24,000 characters (the largest: query_prometheus 20,244, get_provider_details 20,157);
  the IMAP stand-in received only `CAPABILITY, LOGIN, LIST, STATUS, EXAMINE, UID SEARCH, UID FETCH, LOGOUT`.
- The repository's suite: 925 tests pass (101 skipped for servers whose requirements are not in this venv); the one
  failure, `test_frida`, needs frida, which is not in this venv (unrelated). `make_catalog.py --check --allow-pending
  --sandbox-ai /work`: 41 pinned entries accepted, the 5 new ones refused for their missing digest, as they must be.

## The sandbox-ai side

Branch `feature/mcpnew-ops` of sandbox-ai (worktree from `/work` main): `infrastructure` offers terraform, kubernetes
and grafana; `research-memory` offers reddit and imap (its ruleset holds both servers' results for untrusted); as
optional `--mcp` values (none by default, each with its `mcp add` hint), because a preset's required MCP servers block
its start until they are added, and these are pending until the catalog is signed. `observer` (named in the
research's mapping) watches another sandbox-ai session, not a cluster: it gets none.

## What only CI or a real host can prove

- The images build (Debian packages and wheels by hash), the Trivy scan, the smoke specs inside the images under
  Podman, Bubblewrap and without a host init, `test_own_servers` inside each image (Debian's Python 3.13).
- terraform's smoke against the real registry (the answers' shapes follow upstream's `types.go`; not seen here).
- Live: a cluster (kind/k3s) with a read-only service-account token; a Grafana with Prometheus and Loki and a Viewer
  token; a mailbox (Dovecot, Gmail with an app password, Proton Mail Bridge with `IMAP_CA_CERT`); reddit only with the
  user's own approved app.
