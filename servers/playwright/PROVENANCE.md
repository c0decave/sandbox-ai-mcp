# playwright - provenance and audit

| | |
|---|---|
| MCP server | microsoft/playwright-mcp **0.0.83** (Apache-2.0), tag `v0.0.83`, commit `f183dad4a52965583e3cc1d59b88cdc279e2e57d` (2026-09-28; GitHub release and npm `@playwright/mcp@0.0.83` of 2026-09-28) |
| Its code | `playwright` and `playwright-core` `1.64.0-alpha-1790635538000` (Apache-2.0, microsoft/playwright commit `e8149b8257d32dcf8f72573ecc43e72439da7080` of 2026-09-28, npm of 2026-09-28), the only runtime dependencies of the release's `package-lock.json`, installed by `npm ci` with their integrity hashes (`sha512-pNwaXirh...` and `sha512-/5XDUMxp...`, checked against the registry's tarballs on 2026-11-11). The MCP SDK, zod and the other libraries are bundled into `playwright-core` (`lib/utilsBundle.js`) |
| Browser | Debian `chromium` `156.0.8078.79-1~deb13u1` (trixie-security), not Playwright's download, so apt verifies the browser |
| Debian packages | final image: `nodejs=20.19.2+dfsg-1+deb13u3`, `chromium=156.0.8078.79-1~deb13u1`, `ca-certificates=20250419+deb13u1`, `fonts-liberation=1:2.1.5-3`, `tini=0.19.0-3+b8`; build stage also `npm=9.2.0~ds1-3`, `git=1:2.47.3-0+deb13u1` |
| Base image | the `debian:trixie-slim` digest in `Dockerfile` |

**Pinning rule:** 0.0.83 is the newest release published 14 days or more before 2026-11-11
(`docs/CANDIDATES.md`): 0.0.84 (2026-10-31, commit `be26c080`, prepared first) and 0.0.85
(2026-11-09) are too new. The locked `playwright-core` was published the same day as 0.0.83.

**Debian versions:** read from the trixie, trixie-updates and trixie-security indexes of
2026-11-05 (the same values as the other candidates). They could not be re-read on 2026-11-11 (no
Debian host reachable where this was built); `apt-get install` refuses a version the archive no longer
has, so a superseded `chromium` (trixie-security keeps only the newest) stops the CI build with
apt's message: then take the new version from `apt-cache policy chromium` in the pinned base.

## What 0.0.84 changes (not in this image)

From its release notes: `browser_tabs` `isolatedContext` (separate cookie jars in one browser),
`--redact-url-params`, `browser_find` `maxResults`, `browser_network_requests` `all`, locators in
JavaScript/Python/Java/C# as `target`, `--ignore-roots` (a client that advertises MCP roots but
does not answer `roots/list` stalls the first call for 5 s, see below), cookie-delete filters (behind
`--caps=storage`, off here), and fixes: `browser_wait_for` with `time` and a text, bare `host:port`
URLs, `browser_navigate_back` and a dialog, the browser closed twice on a stdio disconnect, route
headers (behind `--caps=network`, off here), several accessibility-snapshot fixes. None is a security
fix for what this image offers. Every flag used here exists in 0.0.83 (`mcp/program.ts` at
`e8149b82`).

## Audit

**Tools (25, `tools.json`):** the tools of `packages/playwright-core/src/tools/backend/*.ts` at
`e8149b82` whose capability is `core*` and that are not `skillOnly` (`backend/tools.ts`
`filteredTools`; the same 25 are in the npm bundle `lib/coreBundle.js`): `browser_click`,
`browser_close`, `browser_console_messages`, `browser_drag`, `browser_drop`,
`browser_emulate_media`, `browser_evaluate`, `browser_file_upload`, `browser_fill_form`,
`browser_find`, `browser_handle_dialog`, `browser_hover`, `browser_navigate`,
`browser_navigate_back`, `browser_network_request`, `browser_network_requests`,
`browser_press_key`, `browser_resize`, `browser_run_code_unsafe`, `browser_select_option`,
`browser_snapshot`, `browser_tabs`, `browser_take_screenshot`, `browser_type`,
`browser_wait_for`. No `--caps` is given, so the cookie and storage tools (`storage`), routes and
offline mode (`network`), PDF, coordinate mouse tools (`vision`), tracing, video and recording
(`devtools`), the `testing` assertions and `browser_get_config` (`config`) are not offered.

**Flags:** `--headless`; `--isolated` (Playwright's launch makes a temporary profile under `/tmp`,
removed when the browser closes; nothing persists between connections); `--no-sandbox`
(Chromium's own sandbox needs user namespaces the container does not grant; the container is the
boundary: no capabilities, read-only root, no new privileges; with `--browser chromium` Playwright
would turn it off on Linux anyway, `mcp/config.ts`); `--browser chromium --executable-path
/usr/bin/chromium` (`chromium` is the `chrome-for-testing` channel, but an executable path is
used as given, `resolveExecutablePath`, and no browser is downloaded or looked up; `/usr/bin/chromium`
is Debian's wrapper, which `exec`s `/usr/lib/chromium/chromium`); `--output-dir
/tmp/playwright-output` (screenshots and other files without an explicit name); `--no-webmcp`
(added here: otherwise a page that registers tools through the WebMCP API gets them into
`tools/list` and the agent can be offered tools a web page wrote, `backend/browserBackend.ts`
`dynamicTools`). Playwright starts Chromium with `--disable-dev-shm-usage` and its
background-networking, component-update and sync switches off (`chromiumSwitches.ts`).

**What it can do:** whatever a browser can on the network the container gets: open any http(s),
`data:` or `about:` URL, fill forms, run JavaScript in pages (`browser_evaluate`), take
screenshots. `--allowed-origins`/`--blocked-origins` are no security boundary (upstream says so):
the boundary is the container's network. **`browser_run_code_unsafe` runs arbitrary JavaScript in
the server's Node.js process** (a `vm` context with `fetch`, which is no boundary; upstream calls it
"RCE-equivalent"): that is code execution inside the container, as uid 10001, with its read-only
root, its `noexec` `/tmp` and its network, never more. Page texts, titles, console messages and
network responses are written by whoever made the page: data for the agent, never instructions.

**Files:** `file:` URLs are refused (`Access to "file:" protocol is blocked`, `checkUrlAllowed`)
and every file name a tool is given must resolve, symlinks followed, inside the output directory or
the workspace (`checkFile`: `File access denied ... outside allowed roots`). The workspace is the
client's first MCP root, else the working directory `/tmp`; a client root is a path of the agent's
machine that does not exist in the container (nothing of the host is mounted). A client that
advertises roots makes the server ask `roots/list` (up to 5 s) before its first tool call.

**Sockets:** the launched browser is bound to a Unix socket below `/tmp` (`BrowserServer`, for
Playwright's own reconnects) and registered under `$HOME/.cache/ms-playwright` (`/tmp`); nothing
listens on TCP. The stdio server has no telemetry or update check.

**Limits:** Chromium needs more than sandbox-ai's defaults (512 MiB, 128 processes, which counts
threads), and a /tmp of more than 64 MiB (its profile, cache, shared memory - Playwright starts it with `--disable-dev-shm-usage` - and screenshots are there; a full one crashed every real page): `smoke.json` runs it with 2g, 2 CPUs, 512 processes and a 768m /tmp, which rootfs.json recommends and sandbox-ai 0.1.94 applies (an older one: add the server with `--memory 2g --pids 512`). Its
profile, disk cache and output files share the 64 MiB `/tmp`; a long session on large pages can
fill it (Chromium then stops caching; screenshots fail with ENOSPC). The browser closes after an
hour without a tool call and starts again with the next one (`--idle-timeout` default).

**Network:** full.

**Tested:** offline (`tests/`: the folder, pins, catalog entry, smoke spec and the limits it runs
with); the smoke spec in CI after the build (a `data:` page navigated, snapshot, a script in the
page, and two refused calls: a `file:` URL and a file name outside the allowed roots). The tools/list
of the built image must equal `tools.json`.
