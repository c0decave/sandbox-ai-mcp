# agentql (prepared) - provenance and audit notes

| | |
|---|---|
| MCP server | tinyfish-io/agentql-mcp = npm `agentql-mcp` 1.0.1 (MIT, `LICENSE` "Copyright (c) 2025 Tiny Fish"), published 2026-02-21 from `main` at commit `affb3a5c5eb817beac6a1aaa86e0ecd8a012f937` (npm provenance, SLSA v1, `.github/workflows/publish.yml`, `workflow_dispatch`); there is no git tag `v1.0.1`, the latest tag is `v1.0.0` (commit `b3de3549406f56c0743d81b254baf5104a98beca`, 2025-03-13) |
| Package | `https://registry.npmjs.org/agentql-mcp/-/agentql-mcp-1.0.1.tgz`, integrity `sha512-K2CsCfLysqSQ2iQTgLN2UGx/lrEdkpNKVsUa/+8fNseBHztn3W+jQ58ma/Vn2iCTZVcJ6PDAX+BFNcMI/IrciA==`, SHA-256 `367fd8df95f7e4b6eaa0ff541e39a4ea2295923d8a4b8b5f063720520a169ca4` (both checked against the download); 4 files, prebuilt `dist/index.js` |
| Dependencies | `@modelcontextprotocol/sdk` `^1` (locked 1.26.0) and `node-fetch` `^3.3.2` (locked 3.3.2): `npm ci --omit=dev --ignore-scripts` with the `package-lock.json` of the commit above (lockfileVersion 3, 261 packages, 97 for production, every one from registry.npmjs.org with an integrity hash, none with an install script; licences MIT, ISC, BSD-2/3-Clause) |
| Node.js, npm, git | Debian `nodejs` `20.19.2+dfsg-1+deb13u3` (the locked packages need >= 18.14.1), `npm` `9.2.0~ds1-3`, `git` `1:2.47.3-0+deb13u1` (npm and git in the build stage only) |

**State:** not built. The pins are filled; the build has not been run. 1.0.1 differs from
v1.0.0 only in the version and the SDK range (`1.6.1` -> `^1`). `main` has moved on
(HEAD `39dc4fb9c1e4`, 2026-11-03) with CI workflow changes and `overrides` in `package.json`
that raise transitive versions (hono, qs, path-to-regexp, ...; the SDK stays 1.26.0) and no
change to `src/`, without a new release. `dist/index.js` was compared by reading with
`src/index.ts` of the commit (the same code minus types); it was not recompiled.

**What it is:** a thin client, one file of about 100 lines. The tool sends the URL and the
prompt to AgentQL's hosted API, whose cloud browser loads the page and whose model extracts
the data; the server returns the JSON it gets back. No browser and no page load in the
container.

**Tools** (`src/index.ts`): `extract-web-data` (`url`, `prompt`, both required ->
`POST https://api.agentql.com/v1/query-data`, with fixed parameters `mode: fast`, no
scrolling, no screenshot, `wait_for: 0`). The URL is not checked: any address, also a private
one, is handed to AgentQL, which fetches it from its own network (not from the host).

**What is sent:** the URL and the prompt as JSON, the headers `X-API-Key: $AGENTQL_API_KEY`,
`X-TF-Request-Origin: mcp-server`, `Content-Type: application/json` and node-fetch's defaults
(`User-Agent: node-fetch`, `Accept: */*`, `Accept-Encoding: gzip, deflate, br`). The endpoint
is a constant; no environment variable changes it. On an error the API's status text and body
are returned to the agent (the key is not part of them). node-fetch 3.3.2 does not honour
`HTTPS_PROXY` (no agent from the environment): with an egress proxy as the only way out the
call fails.

**Telemetry:** none. The server, node-fetch and the stdio parts of the MCP SDK make no other
request; the SDK's HTTP server parts (express, hono, cors) are installed but not loaded.

**Files:** none (no mounts needed).

**Secret:** `AGENTQL_API_KEY`, required (from https://dev.agentql.com); without it the server
prints an error and exits before the MCP handshake. It is the only environment variable read.

**To check when building:** the build commands above (Debian npm 9.2 with a lockfile written by
a newer npm), the tools/list of 1.0.1 for `tools.json` (the smoke test needs a dummy
`AGENTQL_API_KEY` for it), that nothing is written outside `/tmp`, whether to take `main`'s
lockfile instead for the raised transitive versions (Trivy decides), and the proxy: with
sandbox-ai's current `--network full` it works; under an allowlist proxy it needs a preload
that sets a CONNECT agent, or upstream support.

**Network:** allowlist `api.agentql.com:443`.
