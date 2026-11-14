# chrome-devtools - provenance and audit

| | |
|---|---|
| MCP server | Google's Chrome DevTools MCP, npm `chrome-devtools-mcp` **1.12.0** (ChromeDevTools/chrome-devtools-mcp, Apache-2.0: `LICENSES/chrome-devtools-mcp-Apache-2.0.txt`), tag `chrome-devtools-mcp-v1.12.0`, commit `af2834411a564d366f9cab63efb046d9084f4dba` (npm 2026-10-22 13:50 UTC) |
| In the image | the npm package of 1.12.0: tarball `sha512-lAGpH0zXT1ZdaPefP1KK/MvxwihOlu7VGQ7p4wbhD9OhN17vUC4KWk/ImUYR9DE4s+7r4r0ySV4xr2OkTa7ZMA==` (SHA-256 `4aade3167c3e781c797d6109ed603a0ca5b8cb363a289e2eaacaa9b0c5d2a360`), the only entry of `package-lock.json`; its npm provenance attestation names the workflow `.github/workflows/publish-to-npm-on-tag.yml` at `refs/tags/chrome-devtools-mcp-v1.12.0`, commit `af283441` (read, not verified with sigstore here). The package has no runtime dependencies: its `build/src/third_party/` is a rollup bundle of everything it uses (below). The 354 files left after the removals below are pinned by SHA-256 in `chrome-devtools-files.sha256`, and no other file may exist |
| Browser | Debian `chromium` `156.0.8078.79-1~deb13u1` (trixie-security), not Puppeteer's Chrome download, so apt verifies the browser; the same pin as servers/playwright |
| Debian packages | final image: `chromium=156.0.8078.79-1~deb13u1`, `ca-certificates=20250419+deb13u1`, `fonts-liberation=1:2.1.5-3`, `tini=0.19.0-3+b8` (the indexes of 2026-11-05, as servers/playwright; trixie-security keeps only the newest `chromium`: a superseded pin stops the build with apt's message, then take the new version from `apt-cache policy chromium` in the pinned base) |
| Node.js | 24.22.1, the `node` binary only, from `node:24-trixie-slim` `sha256:89c5244bc22a9bc3287d89ebc7e49b9cb5bb84cd40e6175ac3421d5a9f68b95a` (docker-library/repo-info of 2026-10-28, commit `55f75407`), the image of servers/memory, instead of Debian's Node.js 20 (end of life upstream since 2026-04) |
| Base image | the `debian:trixie-slim` digest in `Dockerfile` |

**Upstream:** https://github.com/ChromeDevTools/chrome-devtools-mcp (Google's Chrome DevTools team). Upstream supports
Chrome and Chrome for Testing; Chromium "may work" - Puppeteer drives it through the same CDP, and Debian's Chromium
is what servers/playwright and servers/gowitness run.

**Pinning rule:** prepared on 2026-11-14, cut-off 2026-10-31. 1.12.0 (2026-10-22) is the newest release published on or
before it; **1.13.0** (2026-11-11) is too new until 2026-11-25. The candidate prepared earlier (`candidates/chrome-
devtools`, the same release, its integrity left open) is replaced by this folder.

**Bundled in `build/src/third_party/`** (`bundled-packages.json`, `THIRD_PARTY_NOTICES`): `puppeteer-core` 25.16.0
(with `@puppeteer/browsers` 3.2.6, `ws` 8.22.0), `@modelcontextprotocol/server` and `/core` 2.3.1, `zod` 4.6.5,
`yargs` 18.2.0, `semver` 7.8.5, `core-js` 3.50.0, Lighthouse 13.5.0 (`lighthouse-devtools-mcp-bundle.js`, with axe-core,
third-party-web, `@paulirish/trace_engine`, ...; its `@sentry/node` replaced by an empty module) and the DevTools
frontend at `f22c645573adc85e4553747c577eebb874c3fb43` (`index.js`, two workers) - 285,693 lines of bundled JavaScript
next to 21,456 lines of the server's own.

## What runs, and what was switched off

**At start:** `node build/src/bin/chrome-devtools-mcp.js` checks the Node.js version, `checkForUpdates` (returns at
once: `CHROME_DEVTOOLS_MCP_NO_UPDATE_CHECKS`), parses the command line (no configuration file:
`CHROME_DEVTOOLS_MCP_NO_CONFIG_DISCOVERY`; otherwise `$HOME/.config/cd4a/config.json` would be read), builds the
server (no `ClearcutLogger`: usage statistics off) and serves stdio. Chromium starts with the first tool call that
needs it: Puppeteer `launch` of `/usr/bin/chromium` over a pipe (`pipe: true`: no remote-debugging port), headless,
a temporary profile under `/tmp` (`--isolated`), Puppeteer's default switches (`--disable-background-networking`,
`--disable-breakpad`, `--disable-crash-reporter`, `--disable-sync`, `--disable-client-side-phishing-detection`,
`--metrics-recording-only`, `--no-first-run`, ...) and `--no-sandbox` (Chromium's sandbox needs user namespaces the
container does not grant; the container is the boundary, as for servers/playwright). `detectDisplay` (a shell
pipeline over `/proc/*/environ` of the same uid) runs only for a headed browser: never here.

**Hosts contacted by the server itself, and how each is handled:**

| Host | What | Here |
|---|---|---|
| `play.googleapis.com` (`/log?format=json_proto`) | usage statistics ("Clearcut"): a detached watchdog process gets every tool call's name, success, latency bucket, sanitised parameters, the MCP client's name, daily-active and server-start events with the flags used, a session id; state in `$XDG_DATA_HOME/chrome-devtools-mcp/telemetry_state.json`. On by default upstream | `--no-usage-statistics` and `CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS=1` (`config/ServerConfig.js` 147-152), and the sender (`telemetry/watchdog/`) is not in the image: forced on, the server stops at its first event (tested) |
| `registry.npmjs.org` (`/chrome-devtools-mcp/latest`) | the update check: a detached `node bin/check-latest-version.js`, which also runs `npm config get registry`; once a day, cache in `~/.cache/chrome-devtools-mcp` | `CHROME_DEVTOOLS_MCP_NO_UPDATE_CHECKS=1` (`utils/check-for-updates.js` 23), and the script is not in the image |
| `chromeuxreport.googleapis.com` | CrUX field data: `performance_stop_trace` sends the trace's URLs (with a public API key); DevTools' CrUXManager refreshes only once its `field-data` setting is enabled, which only `populateCruxData` does | `--no-performance-crux` (`McpContext.isCruxEnabled`, `tools/performance.js` 193) |
| the pages' own hosts | Node.js `fetch` of source maps and other resources the DevTools model asks for (`McpContext#loadNetworkResource`: http(s) only, the URL patterns checked, 20 redirects at most; `file:` only inside the roots) | wanted (source maps); the network is the container's |
| `storage.googleapis.com`, `googlechromelabs.github.io` | Puppeteer's browser download and version lookup (`@puppeteer/browsers`) | not reached: `--executable-path` is given, nothing is downloaded |

No other host is contacted by the server's process: the bundle's URLs are documentation links, Lighthouse's
third-party-web and stack-pack data, and test endpoints.

**Tools (`tools.json`, 32 - the default set):** pages (`list_pages`, `new_page`, `select_page`, `close_page`,
`navigate_page`, `resize_page`, `wait_for`), input (`click`, `hover`, `fill`, `fill_form`, `type_text`, `press_key`,
`drag`, `handle_dialog`, `upload_file`), inspection (`take_snapshot`, `take_screenshot`, `get_css_styles`,
`list_console_messages`, `get_console_message`, `list_network_requests`, `get_network_request`, `evaluate_script`),
`emulate`, performance (`performance_start_trace`, `performance_stop_trace`, `performance_analyze_insight`,
`lighthouse_audit`), `take_heapsnapshot`, `screencast_start`, `screencast_stop` (Chrome's own recorder; the ffmpeg
variant is off). Switched off explicitly, so that no variable turns them on (`CHROME_DEVTOOLS_MCP_CATEGORY_EXPERIMENTAL_
THIRD_PARTY` would, tested): tools offered by the inspected page (`--no-category-experimental-third-party`, `--no-
category-experimental-webmcp`), extensions (`install_extension`, ... - registered but disabled), installed web apps
(`--no-category-pwa`); off by default and not enabled: memory-debugging tools, coordinate tools, the DevTools UI,
comment tools.

**Files:** every path a tool reads or writes (`filePath`, `sourcePath`, `upload_file`, traces, heap snapshots,
screencasts) must resolve, links followed, inside the MCP client's roots or `os.tmpdir()` (`McpContext.validatePath`):
`/tmp` here, where nothing of the host is (a client's roots are paths of the agent's machine that do not exist in the
container). `file:` URLs are refused (`--no-file-navigations`, `utils/url.js` 240); the browser can still reach
`/tmp` (its own profile) through other means, inside the container.

**What it can do:** whatever a browser can on the network the container gets, and run JavaScript in pages
(`evaluate_script`, `initScript`). Nothing runs JavaScript in the server's own process from a tool argument.
Network responses (headers, bodies), console messages and page texts come back to the agent as they are
(`--redact-network-headers` is not set: the pages are the agent's own visits).

## What was reviewed

- **Read in full** (5,180 lines): the entry (`bin/chrome-devtools-mcp.js`, `bin/chrome-devtools-mcp-main.js`), the
  update check (`utils/check-for-updates.js`, `bin/check-latest-version.js`), the configuration (`config/mcp-options.js`,
  `ConfigLocator.js`, `ConfigParser.js`, `ServerConfig.js`, `category-options.js`, `browser-options.js`,
  `puppeteer-options.js`, `tool-options.js`), the telemetry (`telemetry/ClearcutLogger.js`, `WatchdogClient.js`,
  `persistence.js`, `transformation.js`, `flagUtils.js`, `watchdog/main.js`, `watchdog/ClearcutSender.js`),
  `BrowserManager.js`, `utils/files.js`, `utils/url.js`, `utils/logger.js`, `utils/errorHandling.js`,
  `utils/disclaimers.js`, `tools/tools.js`, `tools/categories.js`, `tools/pages.js`, `tools/script.js`,
  `tools/performance.js`, `tools/extensions.js`, `tools/screencast.js`; in `McpContext.js` the roots, `validatePath`,
  file writes and `loadResource`.
- **Searched, with the code around every hit read:** the rest of the server's own code (16,276 lines) and the whole
  bundle for hosts, `fetch`, `child_process`/`spawn`/`exec`, `eval`/`new Function`, workers, file writes and
  environment reads. Process execution: Puppeteer's launch of the browser, its `taskkill`/WSL helpers (Windows and
  WSL only), the ffmpeg screencast (off), the watchdog and update-check children (removed). `new Function`: Puppeteer's
  `createFunction` for functions it sends to the page, Ajv in the bundled SDK, DevTools' formatter workers. File
  writes: only `validatePath`-checked tool outputs, the telemetry state and update cache (both off), `--log-file`
  (not set), the profile.
- **Not reviewed line by line:** the server's own tools, formatters and collectors beyond the files above (about
  16,000 lines), and the 285,693 lines of bundled third-party code (Puppeteer, the MCP SDK, zod, yargs, Lighthouse,
  the DevTools frontend). Not checked: that the bundle equals a build of commit `af283441` with its lockfile (the
  build needs Node.js >= 22.18 and the DevTools frontend checkout), and that its parts equal their published releases.

## Findings

| Severity | Where | What | Handling |
|---|---|---|---|
| medium | `telemetry/`, `config/mcp-options.js` 123-127 | usage statistics to Google on by default, with the MCP client's name and tool parameters (sanitised) | flag and variable; the sender removed from the image |
| medium | `tools/performance.js` 193, 208-232 | trace URLs to the CrUX API by default | `--no-performance-crux` |
| low | `utils/check-for-updates.js`, `bin/check-latest-version.js` | daily npm registry query in a detached process; `npm config get registry` through a shell | variable; the script removed |
| low | `config/ConfigLocator.js` | a configuration file in `$HOME/.config/cd4a` (here `/tmp`, writable by the browser's process) would be read at start | `CHROME_DEVTOOLS_MCP_NO_CONFIG_DISCOVERY=1` |
| low | `config/ServerConfig.js` 153-156 | `CHROME_DEVTOOLS_MCP_CATEGORY_EXPERIMENTAL_THIRD_PARTY` offers tools that the inspected page defines | explicit `--no-category-*` flags |
| low | `BrowserManager.js` 95-110 | `detectDisplay` reads `DISPLAY` from every same-uid process's environment through a shell | headless only: never called |
| low | `McpContext.js` 986-1010 | the server's own process fetches URLs a page names (source maps) | the container's network; documented in the entry |
| info | `tools/script.js` | `evaluate_script`, `initScript`: JavaScript in the page (its origin, its cookies) | the tool's purpose |
| info | Lighthouse bundle | `@sentry/node` stubbed out, error reporting never initialised | nothing sent |
| info | Node.js flags | not run with `--disallow-code-generation-from-strings`: Puppeteer's `createFunction` and the bundled Ajv need `new Function` in the server's process | none needed: no tool argument reaches them as code |

No backdoor, obfuscated payload, credential collection or hidden host was found in what was read and searched.

## Network, data and files

- `network: full` (the browser goes wherever the agent sends it).
- Limits as servers/playwright: 2g memory, 2 CPUs, 512 processes, a 768m `/tmp` (`smoke.json`; sandbox-ai 0.1.94
  applies them from rootfs.json's `limits`; before: `--memory 2g --pids 512`).
- Nothing persists: profile, traces, screenshots and heap snapshots live in the container's `/tmp`.
- The session's own browser is **not** offered as a target (`--browser-url`, `--ws-endpoint`, `--auto-connect` are
  not set and cannot be through the entry): it would hand the agent's logged-in browser, its cookies and every open
  tab to a second process over CDP, which sandbox-ai's own browser control already covers with its approvals.

## Tested

- `tools/list` through `scripts/smoke_test.py` with a stand-in for the container engine (the package as installed by
  `npm ci`, after the build's removals and SHA-256 check, on Node.js 26.13 locally, with the image's arguments and
  environment): the 32 tools of `tools.json`; `install_extension` refused ("disabled"); nothing written to `$HOME`.
  The resolved configuration with the entry's arguments and `CHROME_DEVTOOLS_MCP_CATEGORY_EXPERIMENTAL_THIRD_PARTY=1`:
  statistics, CrUX, `file:` navigations, third-party, WebMCP, extensions and PWA all off, isolated, headless,
  `/tmp` the only root. With statistics forced on (no flag, no variable) the server stops (the watchdog is missing).
- Not run here: anything with the browser (no Chromium where this was prepared) and the image build. CI runs the
  smoke spec: a `data:` page opened, snapshot, script, a page of 40,000 rows with six 4000x4000 canvases, a
  screenshot; refused: a `file:` URL, a snapshot written to `/etc`, an extension tool.
- `tests/test_analysis_servers.py` (`ChromeDevTools`): pins, the lock, the removals and the file list, the flags, the
  limits and the smoke spec.

## Verdict

**Not yet fit to sign.** Packaged, pinned and hardened (telemetry, update check, CrUX and configuration discovery off;
the sender and the update script removed; page-defined tools and extensions off), and nothing malicious was found -
but the review is not complete under this repository's rule: about 16,000 lines of the server's own code were only
searched, not read, and the 285,693-line bundle was only searched (the depth servers/playwright's `playwright-core`
had when it was signed; the rule for this catalog asks for a complete review). To finish:
read the remaining own code (tools, formatters, collectors, `McpResponse`, `McpPage`, `McpContext`), rebuild the
package from commit `af283441` with its lockfile and compare it with `build/src` file by file, compare the bundled
Puppeteer 25.16.0, MCP SDK 2.3.1 and zod 4.6.5 with their npm releases, and let CI build it and pass both smoke
runs. Until then the catalog entry stays pending: take a CI run's digests without it
(`scripts/make_catalog.py --ci-digests DIR --only <the other servers> --write-digests`), so that it is not signed.
