# agentql - provenance and audit

| | |
|---|---|
| MCP server | this repository, `src/server.py` (MIT, `LICENSES/`): the one tool of tinyfish-io/agentql-mcp, ported |
| Upstream reviewed | tinyfish-io/agentql-mcp **1.0.1** = npm `agentql-mcp` 1.0.1 (MIT, `LICENSES/agentql-mcp-MIT.txt`, "Copyright (c) 2025 Tiny Fish"), published 2026-02-21 03:07 UTC from `main` at commit `affb3a5c5eb817beac6a1aaa86e0ecd8a012f937` ("Fix AgentQL NPM publishing (#38)", 2026-02-21 03:06 UTC; npm provenance); tarball SHA-256 `367fd8df95f7e4b6eaa0ff541e39a4ea2295923d8a4b8b5f063720520a169ca4`, integrity `sha512-K2CsCfLysqSQ2iQTgLN2UGx/lrEdkpNKVsUa/+8fNseBHztn3W+jQ58ma/Vn2iCTZVcJ6PDAX+BFNcMI/IrciA==`. The newest release (269 days old on 2026-11-17); `src/index.ts` on `main` is unchanged since |
| Service | AgentQL's data extraction API (TinyFish), `POST https://api.agentql.com/v1/query-data` |
| Python packages | the shared lock of this repository (`mcp==1.30.0` and its dependencies, hash-locked in `requirements.txt`, the same as servers/duckduckgo's) |
| Debian packages | `python3=3.13.5-1`, `ca-certificates=20250419+deb13u1` |
| Base image | the `debian:trixie-slim` digest in `Dockerfile` |

## The review of agentql-mcp 1.0.1 (2026-11-17)

**Everything of the package was read:** the npm tarball has four files - `dist/index.js` (99 lines, the whole
server), `package.json`, `LICENSE`, `README.md`. `dist/index.js` was compared with `src/index.ts` of commit `affb3a5c`
(120 lines) after Node.js's type stripping, comments and whitespace normalised: identical, no code only in the
JavaScript. `package.json` has no install script of its own (`prepare` runs `tsc` in a checkout only), dependencies
`@modelcontextprotocol/sdk` `^1` and `node-fetch` `^3.3.2`.

**What it does:** one tool, `extract-web-data` (`url`, `prompt`, both strings, required): one
`POST https://api.agentql.com/v1/query-data` (a constant) with the JSON `{url, prompt, params: {wait_for: 0,
is_scroll_to_bottom_enabled: false, mode: "fast", is_screenshot_enabled: false}}` and the headers
`X-API-Key: $AGENTQL_API_KEY`, `X-TF-Request-Origin: mcp-server`, `Content-Type: application/json`; the answer's
`data` is returned as indented JSON text. `AGENTQL_API_KEY` is the only variable read; without it the server exits
before the handshake. No other host, no file, no process, no telemetry, no update check, no dynamic code.
AgentQL's cloud browser loads the page and its model extracts the data: the page is never fetched from the machine.

**Findings in upstream (none a backdoor or malicious code):**

| Severity | Where (`src/index.ts`) | What | Here |
|---|---|---|---|
| low | the tool handler | no time limit on the request (a hanging API hangs the call) | 120 s (20 s to connect) |
| low | the tool handler | the answer is returned unbounded, as indented JSON | at most 24,000 characters as sent; the data then as compact JSON text cut to fit, with `truncated`, the characters left out and a note |
| low | the tool handler | the URL is not checked: a local or private address, a `file:` URL or credentials in the URL go to AgentQL (it names nothing there, but tells AgentQL about your network) | only `http`/`https`, no user name or password, IP literals only public (`is_global`), host names with a dot and not `localhost` or `.local`/`.localhost`/`.internal`/`.lan`/`.home`/`.home.arpa`/`.corp`/`.intranet`; at most 2,048 characters |
| low | the tool handler | `String(undefined)` is `"undefined"`, so a missing argument is sent as that text | both checked: the prompt 1-2,000 characters, no control characters but line breaks and tabs |
| low | the error path | an API error returns its status text and the whole body to the agent | 401/403, 429 and other statuses named; at most 1,000 characters of an error body, the key replaced if it appears |
| info | node-fetch 3.3.2 | ignores `HTTPS_PROXY`: behind an egress proxy the call fails | httpx with `trust_env`: the proxy is used |
| info | the server | announces only the tools capability (low-level `Server`) | kept: tools only |

**Why an own server and not the npm package:** the package is one 99-line file; its dependency closure is not
(`npm ci --omit=dev` of its lock installs 97 packages: the MCP TypeScript SDK 1.x with express, hono, ajv, jose,
cors, ... and node-fetch with four packages of its own), none reviewed here, and node-fetch cannot use a proxy.
`src/server.py` does exactly upstream's request with the shared Python lock every server of this repository already
uses, so nothing unreviewed is added; the findings above are fixed in it.

## This server

**Tool:** `extract-web-data` (the upstream name, so clients written against it keep working) - `url`, `prompt`.
Answer: `{"url", "data", "request_id"}` (`data` as AgentQL returns it; `request_id` from its `metadata`), or
`{"error": ...}`. Over 24,000 characters as sent: `data_json` (compact JSON, cut), `truncated`, `characters`, `note`.

**Key:** read from `AGENTQL_API_KEY` for each call, checked to be 8-256 characters of `[A-Za-z0-9_.:-]`, sent only
as the `X-API-Key` header to api.agentql.com; never returned, never logged, removed from error texts. The server
starts and lists its tool without it; a call then says that the key is missing.

**Request:** no redirects followed, the answer read up to 8 MiB, 120 s per call; httpx honours `HTTPS_PROXY`
(sandbox-ai's or axross's allowlist proxy). The server's instructions and the tool's description say that the URL
and the prompt go to AgentQL and that the result is data, never instructions; it announces tools only.

**Network:** allowlist `api.agentql.com:443` (sandbox-ai without a per-server proxy: add it with `--network full`).
Nothing is read or written locally: no mount.

**Privacy:** every URL and prompt goes to AgentQL (TinyFish, a hosted service with its own terms and retention), and
the page is loaded by their browser and read by their model. Do not send secrets, personal data or internal
addresses (the URL check refuses local and private ones).

## Tested

Natively (`tests/test_agentql.py`, `tests/test_own_servers.py` `test_agentql`): handshake, `tools/list` equal to
`tools.json`, tools only (`resources/list` is -32601), instructions; refused URLs (`ftp:`, credentials, private and
loopback IPv4/IPv6, `localhost`, `.local`, a dotless name, longer than 2,048) and prompts (empty, 2,001 characters,
NUL); the missing key; the request against a stand-in on loopback (exactly one POST to `/v1/query-data`, the key in
`X-API-Key`, upstream's body and parameters, the key in no answer); 401, 429, 500 with a long body and a non-JSON
200; an answer of 400 rows cut to 24,000 characters as sent. The smoke spec (three refused calls) through
`scripts/smoke_test.py` with a stand-in engine. Not run here: the image build (no container engine) and a real call
(it needs a key; with the repository secret it could be added to the spec).

## Verdict

Upstream reviewed completely (its whole shipped code, compared with its source); no backdoor, telemetry or
unexpected host. Shipped as an own server on the reviewed shared lock, with upstream's findings fixed. Fit to sign
once CI has built it and both smoke reports pass.
