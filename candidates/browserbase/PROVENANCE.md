# browserbase (prepared) - provenance and audit notes

| | |
|---|---|
| MCP server | browserbase/mcp-server-browserbase 3.0.0 = npm `@browserbasehq/mcp` (Apache-2.0), tag `v3.0.0` (annotated tag object `afb36691890b26e57ddf5d8f00ec9df07a7b1583`), commit `f6bd321a3790fcacabc24a7beaa505d3037e19c6` (2026-03-31), dependencies from its `pnpm-lock.yaml` (`--frozen-lockfile`) |
| pnpm | 10.12.4 (the version `packageManager` names) as GitHub's standalone `pnpm-linux-x64`, SHA-256 `ac2768434cbc6c5fec71da4abae7845802bbfe326d590aa0004cdf8bf0815b26` (digest GitHub publishes) |
| Node.js, git | Debian `nodejs` `20.19.2+dfsg-1+deb13u3`, `git` `1:2.47.3-0+deb13u1` (build stage only) |

**State:** not built. The pins are filled; the build has not been run. Upstream's own
Dockerfile uses Node 22; `package.json` names no engine, so Node 20 is to be checked.
`main` has moved on since v3.0.0 (HEAD `3e6f53461949037d5e65dd425da3ceb1263f11d6` on
2026-11-05) without a newer release.

**What it is:** a stdio server that creates a browser session in Browserbase's cloud
(`@browserbasehq/sdk`, base URL `https://api.browserbase.com`, overridable with
`BROWSERBASE_BASE_URL`) and controls it over CDP with Stagehand 3.0.8. `act`, `observe` and
`extract` let an LLM read the page and choose actions: page content goes to the model
provider (default `google/gemini-2.5-flash-lite`, key `GEMINI_API_KEY` or `GOOGLE_API_KEY`;
`--modelName`/`--modelApiKey` select another provider). Browserbase also hosts the same
server at `https://mcp.browserbase.com/mcp` (README), which needs no container.

**Tools** (`src/tools/*.ts`): `start` (create or reuse a Browserbase session; flags
`--proxies`, `--contextId`, `--keepAlive`, `--advancedStealth` change it), `end`,
`navigate` (any URL, `page.goto`), `act` (natural-language action), `observe` (list
actionable elements), `extract` (structured data from the page). No tool reads or writes
local files.

**Secrets:** `BROWSERBASE_API_KEY`, `BROWSERBASE_PROJECT_ID`, `GEMINI_API_KEY`. Without a
model key the server warns and uses a dummy key (`src/config.ts`), so `act`/`observe`/
`extract` fail.

**Network** (allowlist): `api.browserbase.com:443` (session API); the CDP WebSocket URL the
session API returns (a Browserbase `connect` host, exact name not verified here; Stagehand's
`main` also references `api.stagehand.browserbase.com`); the model provider
(`generativelanguage.googleapis.com:443` for the default Gemini model). The Stagehand
source was read at its `main` (`ce298c60bd7e617e38d67db8db7d34de9d37cd18`), not at the
locked 3.0.8, so the host list is indicative.

**To check when building:** Node 20 vs. Stagehand 3.0.8's requirements, the exact hosts
(log the session's `connectUrl`), that `pnpm prune --prod` leaves a working tree, memory,
the tools/list of 3.0.0 for `tools.json`.
