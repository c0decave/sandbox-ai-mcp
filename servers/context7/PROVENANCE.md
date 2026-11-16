# context7 - provenance and audit

| | |
|---|---|
| Upstream | Upstash's Context7 MCP server, `@upstash/context7-mcp` **4.4.4** (upstash/context7 `packages/mcp`, MIT: `LICENSES/context7-MIT.txt`), tag `@upstash/context7-mcp@4.4.4`, commit `c7f80ce5af1ff1403d167579b76784482cf7f3e2` ("chore(release): version packages (#3464)", 2026-10-19 13:46 UTC; npm 2026-10-19 13:48 UTC) |
| In the image | the npm package of 4.4.4, tarball `sha512-T2DkjhweDnC2mRAclDiTrPG3KI1zYKhhjgY2SMKD9PVrbEaGD8x35VsIOqpwwDc2qiKBvfYCF/jqr+jQMu5PUA==` (SHA-256 `2ae37c3a2b41ff4d591a275ff1dc56883cb60bfc71e34c399c14ebd38837bb38`; no npm provenance attestation for this release); its `dist/` compiled by `tsc` (not bundled), compared with the TypeScript of the commit (below). The 20 files that stay are pinned by SHA-256 in `context7-files.sha256` (three of them as patched) |
| npm packages | `package-lock.json` (made with `npm install --package-lock-only --ignore-scripts --before=2026-11-01T00:00:00Z`; 104 packages, none with an install script, each by integrity). `prepare.mjs` keeps the 74 that load: `@modelcontextprotocol/server` and `/core` 2.3.1 (2026-10-05, `sha512-e59MfWuSs...`, `sha512-laVmIhPGp...`; the server pins them exactly), `@modelcontextprotocol/node` 2.1.1 (2026-10-02, `sha512-EY92OAXN2...`), `@hono/node-server` 1.19.17 (2026-07-27, `sha512-dSneS5qhi...`), `undici` 7.30.1 (2026-10-15, `sha512-03KrMbjIF...`), `express` 5.3.0 (2026-10-09, `sha512-qCqy1xSoa...`) with the small packages it needs (body-parser 2.4.0, qs 6.17.1, router, send, ...), `jose` 6.2.14 (2026-10-29, `sha512-3JasLuki1...`), `commander` 13.1.0 (2025-01-20, `sha512-/rFeCpNJQ...`), `zod` 4.6.7 (2026-10-12, `sha512-g8W2D2kU6...`, servers/memory's). The newest of the 74 is jose (2026-10-29). Removed after `npm ci`: OpenTelemetry (9 packages), `require-in-the-middle`, `import-in-the-middle`, `module-details-from-path`, `cjs-module-lexer`, `es-module-lexer`, `hono`, 11 `@types` packages, `undici-types` - none of them loads with telemetry off |
| Node.js | 24.22.1, the `node` binary only, from `node:24-trixie-slim` `sha256:89c5244bc22a9bc3287d89ebc7e49b9cb5bb84cd40e6175ac3421d5a9f68b95a` as docker-library/repo-info recorded it on 2026-10-28 (commit `55f75407`), the image of servers/memory (the package needs >= 20.18.1). TLS uses Node.js's bundled root certificates; no Debian package is added |
| Base image | the `debian:trixie-slim` digest in `Dockerfile` (`sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad`) |

**Upstream:** https://github.com/upstash/context7 (Upstash, Inc.; a monorepo with the MCP server, the `ctx7` CLI and
the web app's SDK). Context7 is a hosted service: the server is a thin client of its API, nothing is indexed locally.
Upstream also runs it remotely (`https://mcp.context7.com/mcp`), which needs no container. Upstream builds with pnpm;
this image installs the npm release from the registry with an npm lockfile of its own instead (the earlier candidate,
`candidates/context7`, built the 4.5.0 commit with pnpm and is replaced by this folder).

**Pinning rule:** prepared on 2026-11-14, cut-off 2026-10-31. 4.4.4 (2026-10-19) is the newest release published on or
before it. Too new: **4.5.0** (2026-11-03, old enough on 2026-11-17: a `submit-docs-feedback` research-preview tool,
off unless `--research-preview`; an unset `${CONTEXT7_API_KEY}` placeholder no longer sent as the key; more OAuth
telemetry of the hosted server), **4.5.1** (2026-11-06: a filter notice kept), **4.6.0** (2026-11-09: research-preview
tools `query-code` and `get-upgrade-guide`) and **4.7.0** (2026-11-12: paging of `get-upgrade-guide`). None is a
security fix, and none changes the two default tools. Every package of the lock was published on or before 2026-10-29.

## What was reviewed

**The server, in full.** Every file of `dist/` that stays in the image was read line by line (2,117 lines in 19 files:
`index.js` 689, `lib/api.js` 181, `lib/jwt.js` 183, `lib/mcp-http-auth.js` 159, `lib/oauth-token-validation.js` 147,
`lib/oauth-audience.js` 119, `lib/auth/auth-prompt.js` 95, `lib/utils.js` 95, `lib/encryption.js` 76, `lib/constants.js`
73, `lib/telemetry-runtime.js` 73, `lib/process-shutdown.js` 63, `lib/vercelMarketplaceJwt.js` 54,
`lib/auth-lifecycle-telemetry.js` 39, `lib/log-throttle.js` 27, `lib/mcp-body-error-handler.js` 23,
`lib/telemetry-config.js` 14, `lib/mcp-route.js` 4, `lib/tool-names.js` 3), and the telemetry modules that are removed
(`lib/telemetry.js` 238, `lib/telemetry-provider.js` 72; `lib/mcp-telemetry.js` 628 and `lib/mcp-subscription-telemetry.js`
463 for what they import and send). The shipped JavaScript was compared with the TypeScript of commit `c7f80ce5`
(repository tarball `sha256:239fd1f6c6f5f82ebd273de8bb97bf6a26bbcd8abaeb0c9e7422fe2466f9771b`) after Node.js's type
stripping, with comments and whitespace normalised: 18 files are identical, `index`, `api`, `utils` and `telemetry`
differ only in type-only imports `tsc` drops and line wrapping; no code exists only in the JavaScript.

**What runs, traced.** The server was started as the image starts it (`--transport stdio`, `OTEL_SDK_DISABLED=true`,
`--disallow-code-generation-from-strings`) with a module-load hook, through `initialize`, `tools/list` and both tools:
411 files load - the server (19), the MCP SDK (11 files, 22,121 lines), undici (110, 37,596), zod (97, 20,080),
commander (8, 4,067), express and its small packages, jose (46, 2,747), `@modelcontextprotocol/node` and
`@hono/node-server` (one file each). No OpenTelemetry, hono or loader-patching package loads; they are removed.

**The MCP SDK 2.3.1:** the same project as the 2.4.0 servers/memory reviewed in full on its stdio path. The 2.3.1 files
that load were compared with 2.4.0: `stdio.mjs` (1 import moved), `chunk`, `dialects`, `shimsNode` identical; `src`
49 changed lines, read (the `x-mcp-header` type list and a `$ref` rule of 2.4.0); `mcp` and `index` (844 changed lines)
and core's `auth` (2.4.0 split it into `auth` and `schemas`) differ mostly by code moved between chunks (the listen
router, the per-request HTTP transport), scanned for network, process, file, environment and code-loading changes:
none; the bundled Ajv differs by its version. The same risky constructs in both versions (8 `fetch(` in client and
HTTP code the server does not use, one `new Function` in Ajv).

**The other packages, on their risky surfaces** (as servers/memory did for zod and Ajv): every loaded file searched
for hosts, `child_process`, `eval`/`new Function`/`vm`, workers, file, socket and DNS use and environment reads, and the
code around each hit read:
- hosts in code (not comments or examples): only `context7.com` (the API), `mcp.context7.com` and `clerk.context7.com`
  (the hosted HTTP mode's OAuth metadata), `login.microsoftonline.com` and `integrations.vercel.com` (JWKS of the hosted
  HTTP mode's token checks, created lazily by jose, fetched only when an HTTP request carries such a token), and Ajv's
  `$id` of the JSON-Schema meta schema (never fetched);
- `child_process`: only commander (`lib/command.js`), for executable subcommands, which this server does not define;
- `new Function`: depd (express's deprecation wrapper), zod's JIT and Ajv - all refused by
  `--disallow-code-generation-from-strings` (the smoke run proves startup and both tools work with it);
- `worker_threads`: undici imports `markAsUncloneable` only; undici's HTTP parser is WebAssembly (llhttp) inside the
  package, used for the proxy path (tested below);
- environment: the server's own variables (below), `HTTP(S)_PROXY`/`NO_PROXY`, `NODE_EXTRA_CA_CERTS`, `DEBUG`,
  colour and deprecation switches.

## What it sends, and to whom

Per tool call one `GET` to `https://context7.com/api/v2/libs/search?query=...&libraryName=...` (`resolve-library-id`)
or `/api/v2/context?query=...&libraryId=...[&language=...]` (`query-docs`), through Node.js's `fetch` (undici's
`ProxyAgent` when `HTTPS_PROXY` is set: axross's allowlist proxy, which then sees only `CONNECT context7.com:443`),
60 s timeout. Headers: `X-Context7-Source: mcp-server`, `X-Context7-Server-Version: 4.4.4`, `X-Context7-Transport:
stdio`, `Authorization: Bearer $CONTEXT7_API_KEY` when the key is set. **Not sent** (patch 2): the per-process
`mcp-session-id` and the MCP client's name and version (`X-Context7-Client-IDE`, `X-Context7-Client-Version`), which
4.4.4 sends with every call. The client-IP assertion (`MCP_CLIENT_IP_ASSERTION_KEY`) exists only in HTTP mode. The
answer (text or JSON) is returned to the agent; error bodies' `message` too.

**Telemetry:** OpenTelemetry metrics only (no traces or logs exported by the server itself): counters of upstream
requests and their outcome, durations, authentication events of the hosted mode. On stdio they go nowhere unless a
MeterProvider is registered (an OpenTelemetry preload); the embedded Prometheus exporter (a local `/metrics` port)
starts only in HTTP mode. With `OTEL_SDK_DISABLED=true` (set in the image) none of it loads, and the modules are not
in the image at all: unsetting it makes the server stop at start (`ERR_MODULE_NOT_FOUND`, tested). No other
telemetry, analytics, update check or crash report exists in the server.

**Variables the server reads:** `CONTEXT7_API_KEY` (offered, secret, optional); not offered and not set:
`CONTEXT7_API_URL` (would send queries and the key to another host), `RESOURCE_URL`, `OAUTH_*`, `EMA_*`, `MCP_*`,
`VERCEL_*`, `OPENAI_APPS_CHALLENGE_TOKEN` (HTTP mode only), `HTTPS_PROXY` (set by axross's allowlist),
`NODE_EXTRA_CA_CERTS` (read as a file).

## Patches (`prepare.mjs`)

1. `dist/lib/auth/auth-prompt.js` (`9d6ef90e...` -> `a2a609e5...`): `maybeElicitAuthSignIn` returns at once. Unpatched,
   when context7.com answers an anonymous call with `X-Context7-Auth-Prompt: 1` and the client supports elicitation,
   the server asks the human to run `npx ctx7 setup --<client> --mcp --stdio -y` - an unpinned package that signs in
   through a browser and rewrites the MCP client's configuration. The key belongs in sandbox-ai's secret store.
2. `dist/lib/encryption.js` (`8e949eb8...` -> `b1a749c0...`): `generateHeaders` no longer adds `mcp-session-id`,
   `X-Context7-Client-IDE` and `X-Context7-Client-Version` - not needed for a lookup.
3. `dist/index.js` (`05aa837e...` -> `f7ba8b2c...`, review of 2026-11-17): the server no longer declares the `prompts`
   and `resources` capabilities, of which it has nothing (empty lists). Agents act on the capability: they offer a
   model tools for MCP resources (Hermes four more per server), which local models took for the way to the server's
   tools (sandbox-ai research round 1). `resources/list` and `prompts/list` are then unknown methods, as for a server
   that never had them.

Each file is checked by SHA-256 before and after, each replaced text must occur exactly once; the build stops
otherwise. `prepare.mjs` also removes the packages that do not load and the server's telemetry modules, and checks
that exactly the 74 kept packages are left, each at its locked version.

## Findings

No backdoor, obfuscated code, credential leak or unexpected host was found in the server or on the surfaces of its
packages.

| Severity | Where | What | Handling |
|---|---|---|---|
| medium | `lib/auth/auth-prompt.js` 69-95 | a server-triggered prompt (the API decides when) asks the human to run an unpinned `npx ctx7 setup ... -y` | patch 1 |
| low | `lib/encryption.js` 47-76 | the MCP client's name and version and a session id go to context7.com with every call | patch 2 |
| low | `index.js` 196-200 | the prompts and resources capabilities declared with nothing behind them (local models took the resource tools agents then offer) | patch 3 |
| low | `lib/telemetry-runtime.js`, `lib/telemetry*.js` | OpenTelemetry metrics, a Prometheus port in HTTP mode, OpenTelemetry's module-loader patching packages | `OTEL_SDK_DISABLED=true`, the modules and packages removed; fails closed if unset |
| low | `lib/constants.js` 10 | `CONTEXT7_API_URL` moves the API, the key goes with it | not offered, not set; a user who adds it with `--env` chooses another host |
| low | `lib/api.js` 166-173 | the documentation text is returned as Context7 answers it, unbounded in size | Context7 answers a few KB per call; the SDK caps nothing outgoing. Content is data, not instructions (entry notes) |
| info | tool descriptions | they tell the agent not to put secrets into queries - and to use Context7 "even when you think you know the answer" | upstream's steering towards the service; the entry notes say what leaves |
| info | `index.js` 8, 353-650 | express, the HTTP routes, OAuth and JWKS checks are loaded but run only with `--transport http`; the entry point fixes `stdio` | nothing listens; checked in the trace |
| info | commander | `child_process` for executable subcommands; none defined | unreachable |
| info | depd, zod, Ajv | `new Function` | refused by `--disallow-code-generation-from-strings` |

## Tools (`tools.json`, 2)

`resolve-library-id` (`query`, `libraryName`; aliases `userQuery`/`question`) and `query-docs` (`libraryId`, `query`,
optional `language`; aliases for `libraryId`). Both read-only, open-world. No resource, no prompt; the research-preview
tools of later releases do not exist in 4.4.4.

## Network, data and files

- `network: allowlist`, `context7.com:443` only (sandbox-ai without a per-server proxy: add it with `--network full`).
- Nothing is read or written: no mount, no cache, no log file. stderr: the start line and API errors (never the key).
- What runs at start: `node --disallow-code-generation-from-strings dist/index.js --transport stdio` - commander parses
  the fixed arguments, `lib/api.js` installs the proxy agent when `HTTPS_PROXY` is set, the server serves stdio; no
  request is made before a tool call.

## Tested

- The smoke spec's refused calls and `tools/list` through `scripts/smoke_test.py` with a stand-in for the container
  engine that ran the prepared packages (after `npm ci`, `prepare.mjs` and the SHA-256 check, as the build does) on
  Node.js 26.13 locally with the image's flags and environment: `tools/list` equals `tools.json`; refused: `query-docs`
  without a library ID, a number as `query`, `read_file` (no such tool).
- The proxy path: both tools with `HTTPS_PROXY` set to a local proxy that refuses every tunnel: the proxy saw exactly
  `CONNECT context7.com:443` per call (undici's `ProxyAgent` and its WebAssembly parser work under the hardened flags,
  the key stays inside the tunnel), the tools answered with Context7's error text.
- With `OTEL_SDK_DISABLED=false` the server stops at start (`ERR_MODULE_NOT_FOUND`).
- Not run here: the real calls (context7.com is not reachable from where this was prepared) and the image build (no
  container engine). CI runs both: the spec's two real calls (anonymous; a rate limit is retried, then skipped).
- `tests/test_analysis_servers.py` (`Context7`): pins, the lock, the prepared package set, the patches, the entry and
  the smoke spec.

## Verdict

The server reviewed completely (line by line, compared with its source), the SDK by its diff to the reviewed 2.4.0,
the other packages that load on their risky surfaces, as for servers/memory; three patches (the sign-in nudge, the
identifying headers, tools only), telemetry removed. Fit to sign once CI has built it and both smoke reports pass, including the
real calls.
