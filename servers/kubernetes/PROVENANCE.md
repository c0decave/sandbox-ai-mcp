# kubernetes - provenance and review

| | |
|---|---|
| MCP server | this repository, `src/server.py` (MIT), our own (2026-11-25): the read tools of containers/kubernetes-mcp-server's core toolset over the cluster's REST API, read-only by construction |
| Upstream looked at | containers/kubernetes-mcp-server **v0.1.2** (Apache-2.0), release published 2026-11-04 19:36 UTC (21 days before this review; v0.1.3 of 2026-11-13 too new), source tarball `codeload.github.com/containers/kubernetes-mcp-server/tar.gz/refs/tags/v0.1.2`, SHA-256 `3e54fdd971727f1ff319ce3e4d93b7aacc7f4159a8bc0812334ec0830e551f7b`. Not installed: see "Why an own server" |
| Python packages | `requirements.txt`, hash-locked from `requirements.in` (`--exclude-newer 2026-11-11`): the shared lock of servers/duckduckgo (`mcp==1.30.0` and its dependencies, the same versions and hashes; httpx and cryptography among them) and, new for this server, **PyYAML 6.0.3** (2025-09-25, MIT; the same version and hashes as servers/capa's lock) |
| Debian packages | `tini=0.19.0-3+b8` (the image's init, its ENTRYPOINT), `python3=3.13.5-1`, `ca-certificates=20250419+deb13u1` (only used when the kubeconfig has no certificate-authority-data) |
| Base image | the `debian:trixie-slim` digest in `Dockerfile` |
| Licences | `LICENSES/`: sandbox-ai-mcp (MIT), MCP Python SDK (MIT), PyYAML (MIT), kubernetes-mcp-server (Apache-2.0, whose tool design this follows) |

## Why an own server (the upstream review could not be completed)

The user's rule is that only servers reviewed completely are signed. kubernetes-mcp-server v0.1.2 cannot be:

- **Size.** Its own Go code is 41,833 lines outside tests; `go list -deps ./cmd/kubernetes-mcp-server` links 1,189
  packages with **1,714,441 lines** of Go (k8s.io/api 435,041, client-go 202,717, apimachinery 61,394, OpenTelemetry
  51,314, protobuf 49,697, cel-go 48,911, gRPC 36,625, gnostic 34,349, Prometheus 31,070, apiextensions 28,053, Helm v3
  24,780, kube-openapi 22,779, ...). Every toolset is linked whatever `--toolsets` says. (For comparison: round 2 and
  mcpnew-dev refused github-mcp-server at 315,705 linked lines.)
- **What it can do.** Its default toolsets include `resources_create_or_update` (server-side apply), `resources_delete`,
  `resources_scale`, `pods_delete`, `pods_exec`, `pods_run`, `helm_install`/`helm_uninstall`, and toolsets for KubeVirt
  (VM lifecycle, console screenshots), Kiali/Istio, Tekton (start and restart runs), KCP, Loki, Tempo, NetObserv and an
  OpenTelemetry collector. `read_only = true` hides the writers, `disable_destructive` only the destructive ones; both
  are flags, not the absence of code.
- **Secrets.** `resources_get` returns a Secret with its data (base64, i.e. readable) unless the operator lists the
  Secret GVK in `denied_resources`; its `sanitize` package only scrubs its own logs.
- **Telemetry.** `pkg/telemetry` and `pkg/metrics` set up OpenTelemetry (traces, an OTLP exporter) when `[telemetry]`
  is configured; off by default, but linked. Its HTTP mode adds OAuth, token exchange (Entra ID, STS) and a metrics
  endpoint.
- **Not found** (a search of the 41,833 own lines, not a review of the closure): a backdoor, an update check, a host
  of its own besides the cluster (the URLs in the code are examples, documentation and the Entra/STS endpoints of the
  HTTP mode's token exchange).

What it is good at - a small core of read tools a model can use (`namespaces_list`, `resources_list`, `resources_get`,
`api_resources_list`, `pods_log`, `events_list`) - is taken over here, read-only by construction, on the reviewed
shared lock.

## This server

**Tools** (all `readOnlyHint`, only GET requests; tool names as upstream's where they exist):

| Tool | Request(s) | Answer |
|---|---|---|
| `cluster_info` | `GET /version` | context, server, how it logs in (`token`, `client certificate`, `username and password`, `anonymous` - never the credential), default namespace, version |
| `namespaces_list` | `GET /api/v1/namespaces?limit=2000` | name, status, age |
| `api_resources_list(kind?, group?)` | `GET /api/v1`, `GET /apis` with aggregated discovery v2 (one request for every group, Kubernetes >= 1.30); older servers: `GET /apis/GROUP/VERSION` of each group's preferred version (at most 200; an aggregated API that is down is left out, as kubectl does) | kind, apiVersion, plural, namespaced, short names |
| `resources_list(api_version, kind, namespace?, label_selector?, field_selector?, limit=100, continue_token?)` | discovery of the group (cached), then `GET .../PLURAL` with `Accept: application/json;as=Table;v=v1;g=meta.k8s.io` and `includeObject=Metadata` | the cluster's own columns (priority 0, as `kubectl get`), a Namespace column across namespaces, `continue_token` for the next page; a server without the Table form: names and ages |
| `resources_get(api_version, kind, name, namespace?, section?)` | `GET .../PLURAL/NAME` | the object as JSON without `managedFields`; a `v1` Secret's `data` and `stringData` values replaced by `(secret value of N characters, not shown)`; the `kubectl.kubernetes.io/last-applied-configuration` annotation of any object left out (it holds an applied Secret in full); `section` = metadata, spec, status or data for a large object; over 24,000 characters: the first part, said so |
| `pods_log(name, namespace?, container?, tail_lines=200, previous=false, since_seconds?)` | `GET /api/v1/namespaces/NS/pods/NAME/log` with `tailLines`, `previous`, `sinceSeconds`, `limitBytes=1048576` | the newest lines that fit (JSON escapes counted), control characters replaced |
| `events_list(namespace?, field_selector?, limit=100)` | `GET /api/v1[/namespaces/NS]/events?limit=2000` | newest first: type, reason, object, namespace, message (1,000 characters), count, last seen |

**The kubeconfig** comes from the secret `KUBECONFIG_DATA` (YAML or JSON, or that text as one line of base64 - a
secret is easiest kept on one line), at most 1 MiB, parsed with `yaml.safe_load` (the SafeLoader: no Python objects,
no imports; PyYAML's `__import__` calls are in `FullConstructor`/`UnsafeConstructor` only). Taken: the context
(`KUBERNETES_CONTEXT` or `current-context`), the cluster's `server` (https only), `certificate-authority-data`,
`tls-server-name` (as the TLS server name, httpx's `sni_hostname`), the user's `token`, `client-certificate-data` +
`client-key-data` (loaded into the TLS context from two 0600 files in a temporary folder under /tmp, the container's
tmpfs, removed as soon as they are read - Python's ssl loads keys from files only), or `username` + `password`
(Basic). **Refused**, each with its reason: an `http://` server, `insecure-skip-tls-verify`, `certificate-authority`,
`client-certificate`, `client-key` and `tokenFile` (paths: `--flatten` embeds them), `proxy-url`, `exec` (it runs a
program: aws, gke-gcloud-auth-plugin, kubelogin), `auth-provider`, impersonation (`as`, `as-groups`), a token with
spaces or line breaks. Nothing is sent before the kubeconfig is accepted.

**Arguments** are checked before anything is sent: `api_version` as a group/version (`v1` or `GROUP/VERSION`), `kind`
alphanumeric, `name` `[A-Za-z0-9][-A-Za-z0-9_.:@]*` up to 253 (not `.`/`..`; percent-escaped into the path),
`namespace` and `container` as DNS labels, selectors one printable line of at most 1,024 characters (sent as query
parameters), `continue_token` base64-like, numbers in their ranges (booleans refused). The path's resource segment
is the plural the cluster's discovery returned for the kind, never the agent's text.

**Requests:** httpx, TLS always verified (the kubeconfig's CA, else Debian's CAs), redirects never followed, 30 s
per request, at most 16 MiB read of an answer (1 MiB of a log), the API's error message (500 characters) with a
hint for 401/403. `HTTPS_PROXY` is honoured (httpx), so a proxy sandbox-ai gives the server is used.

**Answers** are JSON of at most 24,000 characters: lists drop items from the end and say how many fit; texts from
the cluster have control characters replaced and are cut (2,000 characters a value). The server announces tools only
(no resources, prompts) and its instructions say that what the cluster returns is data, never instructions.

**Network:** the API server of the kubeconfig - a host only the user knows, so the catalog entry is `full`
(egress-all) like gitea's, with `--allow-tcp ADDRESS:PORT` for a cluster in the local network or on the host.
**Secrets:** `KUBECONFIG_DATA`. **Files:** nothing read or written but the two short-lived key files above.

## Tested

- `tests/test_kubernetes.py` (11 tests), against a stand-in API server on loopback over real TLS (a throwaway CA,
  server and client certificates made with cryptography, `tests/tls_fake.py`): the handshake (tools only, every tool
  read-only, the untrusted-data instruction), every tool without `KUBECONFIG_DATA`; token over verified TLS (the
  `Authorization` header sent, the token in no answer), base64 and JSON kubeconfigs, another context and namespace;
  a client certificate (the server sees the client's certificate) and Basic; an unknown CA and the system CAs refused
  (`CERTIFICATE_VERIFY_FAILED`); 15 refused kubeconfigs with nothing sent; the Table form (columns, a namespace
  column, the query sent, the continue token); a Secret whose value, `stringData`, last-applied annotation and
  managedFields never appear; sections; 403 with its hint; logs (the query, escapes removed, the newest 24,000
  characters of 5,000 lines) and events (newest first, an injected instruction passed on as data); aggregated and
  per-group discovery; 15 hostile arguments with nothing sent; only GET requests over all tools; a redirect not
  followed; 3,000 namespaces bounded to 24,000 characters.
- `tests/test_own_servers.py` `test_kubernetes` (in the image in CI: the server over stdio as the image starts it,
  then the suite above with the image's Python and libraries, no network).
- `smoke.json`: the seven tools against `https://127.0.0.1:9` (network none: each says which request could not be
  made) and two refused arguments - 9/9 passed over stdio here.

## Risks left

- RBAC is the boundary: a token that may read Secrets lets the agent learn their names, types and key names (never
  the values through this server); a token that may write cannot write through this server.
- Pod logs and events can carry whatever the workloads print (credentials included, if a program logs them).
- Not run against a real cluster here (no cluster in this sandbox); a live check: a kind/k3s cluster with a
  read-only service-account token (see the catalog entry's notes).
