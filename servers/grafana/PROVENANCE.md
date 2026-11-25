# grafana - provenance and review

| | |
|---|---|
| MCP server | this repository, `src/server.py` (MIT), our own (2026-11-25): nine read tools of grafana/mcp-grafana over Grafana's HTTP API, read-only by construction |
| Upstream looked at | grafana/mcp-grafana **v2.3.0** (Apache-2.0, `LICENSES/mcp-grafana-Apache-2.0.txt`), release published 2026-11-10 17:45 UTC (14 days 18 hours before this review; v2.4.0 of 2026-11-24 too new), source tarball `codeload.github.com/grafana/mcp-grafana/tar.gz/refs/tags/v2.3.0`, SHA-256 `90857dbd58efe2da1453ebbd56f85d3dab45dd9fc2942a0ea231cd81ad7fa659`. Not installed: see "Why an own server" |
| Python packages | `requirements.txt`: the shared lock of servers/duckduckgo (`mcp==1.30.0` and its dependencies, httpx among them; the same versions and hashes) - nothing new |
| Debian packages | `tini=0.19.0-3+b8` (the image's init, its ENTRYPOINT), `python3=3.13.5-1`, `ca-certificates=20250419+deb13u1` |
| Base image | the `debian:trixie-slim` digest in `Dockerfile` |

## Why an own server (the upstream review could not be completed)

- **Size.** 47,890 lines of its own Go outside tests; `go list -deps ./cmd/mcp-grafana` links 765 packages with
  **1,495,449 lines** (Grafana's generated OpenAPI client 245,456, the Kafka client franz-go 121,063, OpenTelemetry
  73,262, the AWS SDK 55,037, goccy/go-json 54,934, Apache Arrow 52,305, protobuf, gRPC, gogo/protobuf, Prometheus ...).
- **What it can do.** 116 tools in 22 default categories: besides reading, `update_dashboard`, `create_folder`,
  `create_datasource`/`update_datasource`, `alerting_rules_write`, `alerting_routing_write`, silences, contact points,
  `create_incident`/`update_incident`, annotations, snapshots, `install_plugin`, OnCall, and `grafana_api_request` (any
  API call), `query_sql`/`query_influxdb` (raw queries "unfiltered, so they can mutate data", its own flag help says).
  `--disable-write` hides the writers; they stay linked.
- **Hosts besides the user's Grafana:** `grafana.com/api/plugins` (plugin search), grafana.com documentation
  (`search_docs`, `get_doc`), Grafana Cloud services (asserts, agent observability, cloud logging), an optional OTLP
  endpoint; `/metrics` in its HTTP mode.
- **Not found** (a search of the 47,890 own lines, not a review of the closure): a backdoor or an update check.

What it does well - dashboards' panels and queries summarised for a model, PromQL/LogQL through Grafana's datasource
proxy with the resources endpoint as a fallback, the frontend-settings fallback for a Viewer that may not list
datasources - is taken over here on the reviewed shared lock, read-only by construction.

## This server

**Tools** (all `readOnlyHint`, only GET requests to `GRAFANA_URL`):

| Tool | Request(s) |
|---|---|
| `search_dashboards(query?, tag?, folder_uid?, limit=50, page=1)` | `/api/search?type=dash-db&...` |
| `get_dashboard_summary(uid)` | `/api/dashboards/uid/UID` - title, folder, tags, time, variables, every panel (rows' too) with datasource and queries (`expr`, `rawSql`, `query`, `rawQuery`, `target`) |
| `list_datasources(type?)` | `/api/datasources`; on 403 (a Viewer) `/api/frontend/settings`'s datasources |
| `query_prometheus(datasource_uid, expr, start?, end?, step_seconds?, query_type="range")` | `/api/datasources/proxy/uid/UID/api/v1/query_range` (or `/query`); on 403/404/405 `/api/datasources/uid/UID/resources/api/v1/...` |
| `list_prometheus_metric_names(datasource_uid, contains?, limit=200)` | `.../api/v1/label/__name__/values` (filtered here by a substring, no regular expression from the agent) |
| `list_prometheus_label_values(datasource_uid, label, match?, limit=200)` | `.../api/v1/label/LABEL/values?match[]=` |
| `query_loki_logs(datasource_uid, logql, start?, end?, limit=100, direction="backward")` | `/api/datasources/proxy/uid/UID/loki/api/v1/query_range`; fallback `/api/datasources/uid/UID/resources/query_range` (Loki's resources handler adds `/loki/api/v1/` itself, as upstream notes) |
| `list_loki_label_values(datasource_uid, label?, start?, end?)` | `.../labels` or `.../label/LABEL/values` |
| `list_alert_rules(state?)` | `/api/prometheus/grafana/api/v1/rules` |

**Settings:** `GRAFANA_URL` (https, or http in your own network; no user, query or fragment), the secret
`GRAFANA_SERVICE_ACCOUNT_TOKEN` (one word, sent as `Authorization: Bearer`, in no answer), `GRAFANA_ORG_ID` (digits,
`X-Grafana-Org-Id`), `GRAFANA_CA_CERT` (PEM or base64 PEM, must load). Anything else refused before a request.

**Arguments:** uids `[A-Za-z0-9._-]{1,128}` (percent-escaped into paths), label names Prometheus' pattern, queries one
line of at most 5,000 characters (sent as query parameters), times `now`, `now-N[smhdw]`, RFC 3339 or Unix seconds
(end default now, start default an hour before end; at most 400 days; at most 11,000 points per series), numbers in
their ranges, enumerations checked.

**Answers:** at most 50 series of 120 points each (thinned evenly; `points` says how many there were), log lines
newest first with control characters replaced (2,000 characters each), every list within 24,000 characters (cut from
the end, said so). A datasource's own error (a PromQL parse error) is passed on (500 characters).

**Requests:** httpx, TLS verified (Debian's CAs or `GRAFANA_CA_CERT`), no redirects, 30 s, at most 16 MiB read.
**Network:** `GRAFANA_URL` - a host only the user knows: `full` (egress-all) like gitea, `--allow-tcp` for a Grafana in
the local network. **Secrets:** the token. **Files:** none.

## Tested

- `tests/test_grafana.py` (9 tests) against a stand-in Grafana on loopback over real TLS (a private CA given as
  `GRAFANA_CA_CERT`, PEM and base64; without it `CERTIFICATE_VERIFY_FAILED`): the handshake; dashboards (the token
  and org headers, the query sent, more pages; panels in rows, variables; the token in no answer); datasources and the
  Viewer fallback; Prometheus (60 series of 400 points bounded to 24,000 characters, thinned to 120, the step for 6
  hours, an instant query at a given time, metric names by substring, label values with `match[]`, a datasource's 400);
  Loki through the resources fallback (the proxy path first, ns times, newest first, an injected instruction passed on
  as data with its escape replaced) and label names; alert rules (firing first, by state); 6 refused settings and 12
  refused arguments with nothing sent; only GETs; a redirect not followed; an unreachable Grafana; the time parser.
- `tests/test_own_servers.py` `test_grafana` (in the image in CI, no network).
- `smoke.json`: the nine tools against `http://127.0.0.1:9` (network none: each names the request it could not make)
  and two refused arguments - 11/11 passed over stdio here.

## Risks left

- The service account's role is the boundary of what can be read; a Viewer can run any query its datasources allow.
- Not run against a real Grafana here; the API paths are Grafana's documented ones and upstream's (proxy and resources
  fallback). A live check: a Grafana with a Prometheus and a Loki datasource and a Viewer token.
