# context7 (prepared) - provenance and audit notes

| | |
|---|---|
| MCP server | upstash/context7 `packages/mcp` = `@upstash/context7-mcp` 4.5.0 (MIT), tag `@upstash/context7-mcp@4.5.0`, commit `a138857cc23f0abaf214b72b15d974e61598369b` (2026-11-03), dependencies from the workspace's `pnpm-lock.yaml` (`--frozen-lockfile`, integrity hashes) |
| pnpm | 10.34.9 standalone `pnpm-linux-x64`, SHA-256 `3ec79240658f0ee4e8977f21ee2c598c7a8b8d06b86dc564f2ec6cb099fd8ac2` (digest GitHub publishes); upstream CI uses `pnpm/action-setup` with `version: 10` |
| Node.js, git | Debian `nodejs` `20.19.2+dfsg-1+deb13u3` (the package needs >= 20.18.1), `git` `1:2.47.3-0+deb13u1` (build stage only) |

**Re-pin before building:** 2026-11-17 or an older release. `@upstash/context7-mcp` 4.5.0 (commit `a138857c`) was published 2026-11-03 (too new until 2026-11-17) and pnpm 10.34.9 on 2026-10-25 (too new until 2026-11-08) under the pinning rule (`docs/CANDIDATES.md`); an older release needs its own audit.

**State:** not built. The pins are filled; the build (in particular `pnpm deploy --legacy` of
the workspace package, and pnpm 10.34 against a lockfile written by an unknown 10.x) has not
been run.

**What it is:** a thin client. Both tools send the agent's question to Context7's hosted API
and return the documentation text it answers with; nothing is indexed locally. The same
service is also offered as a remote MCP server (`https://mcp.context7.com/mcp`, header
`Authorization: Bearer <key>`), which needs no container at all.

**Tools** (`src/lib/tool-names.ts`): `resolve-library-id` (library name + query ->
`GET https://context7.com/api/v2/libs/search`), `query-docs` (library ID + query ->
`GET https://context7.com/api/v2/context`), and `submit-docs-feedback`
(`POST /api/v2/feedback`), listed only with `--research-preview` /
`CONTEXT7_RESEARCH_PREVIEW`, which the entry point does not set.

**What is sent** (`src/lib/encryption.ts` `generateHeaders`, `src/lib/api.ts`): the query and
library name, `X-Context7-Source: mcp-server`, the server version, the MCP client's name and
version, the transport, and `Authorization: Bearer $CONTEXT7_API_KEY` when the key is set.
The client-IP assertion header is only produced with `MCP_CLIENT_IP_ASSERTION_KEY` (HTTP
mode). `CONTEXT7_API_URL` overrides the API base; the image does not set it. `HTTPS_PROXY`
is honoured.

**Telemetry:** OpenTelemetry metrics with an embedded Prometheus exporter unless
`OTEL_SDK_DISABLED=true` (`src/lib/telemetry-config.ts`); the image sets it. No other
outbound telemetry was found in `packages/mcp/src`. OAuth (`clerk.context7.com`) and JWKS
lookups are only used by the HTTP transport.

**Files:** none (no mounts needed).

**Secret:** `CONTEXT7_API_KEY`, optional (anonymous use is rate-limited).

**To check when building:** the build commands above, the tools/list of 4.5.0 for
`tools.json`, that nothing is written outside `/tmp`.

**Network:** allowlist `context7.com:443`.
