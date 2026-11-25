# chrome-devtools - provenance and audit

| | |
|---|---|
| MCP server | Google's Chrome DevTools MCP, npm `chrome-devtools-mcp` **1.12.0** (ChromeDevTools/chrome-devtools-mcp, Apache-2.0: `LICENSES/chrome-devtools-mcp-Apache-2.0.txt`), tag `chrome-devtools-mcp-v1.12.0`, commit `af2834411a564d366f9cab63efb046d9084f4dba` (npm 2026-10-22 13:50 UTC) |
| In the image | the npm package of 1.12.0: tarball `sha512-lAGpH0zXT1ZdaPefP1KK/MvxwihOlu7VGQ7p4wbhD9OhN17vUC4KWk/ImUYR9DE4s+7r4r0ySV4xr2OkTa7ZMA==` (SHA-256 `4aade3167c3e781c797d6109ed603a0ca5b8cb363a289e2eaacaa9b0c5d2a360`), the only entry of `package-lock.json`; its npm provenance attestation names the workflow `.github/workflows/publish-to-npm-on-tag.yml` at `refs/tags/chrome-devtools-mcp-v1.12.0`, commit `af283441` (read, not verified with sigstore here). The package has no runtime dependencies: its `build/src/third_party/` is a rollup bundle of everything it uses (below). The 354 files left after the removals below are pinned by SHA-256 in `chrome-devtools-files.sha256`, and no other file may exist |
| Browser | Debian `chromium` `156.0.8078.108-1~deb13u1` (trixie-security), not Puppeteer's Chrome download, so apt verifies the browser; the same pin as servers/playwright |
| Debian packages | final image: `chromium=156.0.8078.108-1~deb13u1`, `ca-certificates=20250419+deb13u1`, `fonts-liberation=1:2.1.5-3`, `tini=0.19.0-3+b8` (the indexes of 2026-11-05, as servers/playwright; trixie-security keeps only the newest `chromium`: a superseded pin stops the build with apt's message, then take the new version from `apt-cache policy chromium` in the pinned base; 156.0.8078.108 is the security release of 2026-11-23, see servers/playwright/PROVENANCE.md) |
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
next to 21,456 lines of the server's own (18,195 of them in the image, after the removals below). The whole `build/src`
of the tarball was rebuilt from commit `af283441` with its lockfile and is byte-identical to it (Review, below).

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

Two passes: the first (packaging) read the code on the paths to the network, files, processes and the configuration
and searched the rest; the second (2026-11-14, completing the review) read every remaining line of the server's own
code, rebuilt the package from source, and checked every bundled part against its published upstream release.

**The server's own code - every line read.** The image holds 18,195 lines of it (86 files; the 3,261 lines of the
removed CLI, daemon, watchdog and update script are not in the image and need no review):

- read in the first pass (4,366 lines of what is in the image, 5,180 with the removed watchdog and update script): the
  entry (`bin/chrome-devtools-mcp.js`, `bin/chrome-devtools-mcp-main.js`), the update check
  (`utils/check-for-updates.js`, `bin/check-latest-version.js`), the configuration (`config/mcp-options.js`,
  `ConfigLocator.js`, `ConfigParser.js`, `ServerConfig.js`, `category-options.js`, `browser-options.js`,
  `puppeteer-options.js`, `tool-options.js`), the telemetry (`telemetry/ClearcutLogger.js`, `WatchdogClient.js`,
  `persistence.js`, `transformation.js`, `flagUtils.js`, `watchdog/main.js`, `watchdog/ClearcutSender.js`),
  `BrowserManager.js`, `utils/files.js`, `utils/url.js`, `utils/logger.js`, `utils/errorHandling.js`,
  `utils/disclaimers.js`, `tools/tools.js`, `tools/categories.js`, `tools/pages.js`, `tools/script.js`,
  `tools/performance.js`, `tools/extensions.js`, `tools/screencast.js`;
- read in the second pass (13,829 lines, 57 files): `index.js`, `McpContext.js` (all of it), `McpPage.js`,
  `McpResponse.js`, `SlimMcpResponse.js`, `McpWorker.js`, `ToolHandler.js`, `TextSnapshot.js`, `types.js`, `version.js`;
  `collectors/` (`PageCollector.js`, `ServiceWorkerCollector.js`, `constants.js`); `config/ConfigWatcher.js`;
  `daemon/utils.js`; `devtools/` (`DevToolsCommentBridge.js`, `DevtoolsUtils.js`, `McpHostBindingAdapter.js`,
  `issueDescriptions.js`); `formatters/` (`CommentFormatter.js`, `ConsoleFormatter.js`, `CssFormatter.js`,
  `HeapSnapshotFormatter.js`, `IssueFormatter.js`, `NetworkFormatter.js`, `RemoteObjectFormatter.js`,
  `SnapshotFormatter.js`); `processors/` (`ChunkedTraceParser.js`, `HeapSnapshotManager.js`, `PerformanceTrace.js`);
  `telemetry/errors.js`, `telemetry/types.js`; `tools/` (`ToolDefinition.js`, `comments.js`, `console.js`, `css.js`,
  `emulation.js`, `input.js`, `lighthouse.js`, `memory.js`, `network.js`, `pwa.js`, `screenshot.js`, `snapshot.js`,
  `thirdPartyDeveloper.js`, `webmcp.js`, `slim/tools.js`); `utils/` (`TaskRunner.js`, `WaitForHelper.js`, `bytes.js`,
  `id.js`, `keyboard.js`, `pagination.js`, `polyfill.js`, `resourceType.js`, `text.js`, `timeout.js`). The TypeScript
  helper prelude that tsc puts at the top of 11 files is identical in all of them (checked by hash) and was read
  once. Also read: the server's wrappers around the bundle (`src/third_party/index.ts`, `cli.ts`, the two worker
  entries) and its build scripts (`rollup.config.js`, `scripts/prepare.ts`, `post-build.ts` - the stand-in modules it
  writes for DevTools' locales, CodeMirror, `Runtime` and the AI-assistance skills are inert data -,
  `append-lighthouse-notices.ts`, `update-lighthouse.ts`) and the publish workflow at the tag.
- Looked for in all of it: network access, `eval`/`Function`/dynamic `import()`, child processes, file writes outside
  the temporary directory and the roots, environment variables that change behaviour, listening sockets, hidden
  endpoints, obfuscation, data sent off the machine. Results under Findings; nothing of that kind beyond what is listed.

**The package equals its source.** Commit `af2834411a564d366f9cab63efb046d9084f4dba` (on `main` of
ChromeDevTools/chrome-devtools-mcp, tag `chrome-devtools-mcp-v1.12.0`) was cloned, `npm ci --ignore-scripts` installed
its `package-lock.json` (550 packages, each checked by npm against its lock integrity), the DevTools frontend submodule
was checked out at `f22c645573adc85e4553747c577eebb874c3fb43` (on `main` of the ChromeDevTools/devtools-frontend
mirror of chromium.googlesource.com, Gerrit change 8616444) with the sparse checkout of `scripts/prepare.ts`, and
`NODE_ENV=production npm run bundle` was run as the publish workflow does (tsc, `post-build.ts`, rollup, the notices).
All 361 files of the tarball's `build/src` (the removed ones included) and its `LICENSE`, `README.md` and
`package.json` are **byte-identical** to the rebuild, the 285,693 bundled lines included. So the bundle is exactly what
the build makes of the server's source, the DevTools frontend at that commit, the locked npm packages and the
repository's Lighthouse bundle (next paragraphs) - nothing was added to it by hand.

**The bundled npm packages equal their published releases.** For every lock entry of a package rollup put into the
bundle (`THIRD_PARTY_NOTICES`: `puppeteer-core` 25.16.0, `@puppeteer/browsers` 3.2.6, `ws` 8.22.0,
`@modelcontextprotocol/server` and `/core` 2.3.1, `ajv` 6.15.0, `uri-js`, `fast-deep-equal`, `json-schema-traverse`,
`fast-json-stable-stringify`, `zod` 4.6.5, `yargs` 18.2.0, `yargs-parser`, `y18n`, `cliui`, `string-width`,
`strip-ansi`, `ansi-regex`, `ansi-styles`, `wrap-ansi`, `emoji-regex`, `get-east-asian-width`, `escalade`,
`get-caller-file`, `semver` 7.8.5, `core-js` 3.50.0), every nested copy included, and for `lighthouse` 13.5.0, rollup
4.64.7 with its four plugins and TypeScript 6.0.2 (56 lock entries): the lock's integrity equals the registry's
(registry.npmjs.org `<name>/<version>` `dist.integrity`), the tarball downloaded afresh matches it, and every file in
the tarball equals the installed file, with no extra file installed.

**The Lighthouse bundle equals a build of Lighthouse 13.5.0.** `lighthouse-devtools-mcp-bundle.js` (SHA-256
`f31f94212ca3d861bf1e6b1ad351e1c54797ae41033a1c3b6af36b957941c27d`, 60,837 lines) is not rolled up by the server's
build: it is a file in the repository (commit 841793ff, "reimport lighthouse 13.5.0 bundle"), made with Lighthouse's
own `yarn build-devtools-mcp`. GoogleChrome/lighthouse at tag `v13.5.0` (commit
`cb853a38a6410617518b363590c967b3fe211949`, on `main`, the `gitHead` of the npm release 13.5.0) was installed with
its `yarn.lock` (yarn 1.22.22 by the hash in its `packageManager`, `--frozen-lockfile --ignore-scripts`), and
`build-report-components.js`, `build-report.js` and `build-bundle-mcp.js` were run: the result is identical to the
shipped file except the build date in the banner (`Oct 22 2026`) and the absolute path of the developer's checkout
(`/Users/alexrudenko/src/lighthouse`, on 137 lines of `replace-modules:` markers) - identical after replacing both. Its
notices file equals the shipped `LIGHTHOUSE_MCP_BUNDLE_THIRD_PARTY_NOTICES`. The 446 JavaScript files of the npm
release `lighthouse` 13.5.0 (`core/`, `shared/`, `report/`, `third-party/`, the logger) equal the tag's, and the 57
installed copies of the packages esbuild put into the bundle (`@paulirish/trace_engine` 0.0.65, `axe-core` 4.13.0,
`third-party-web`, `csp_evaluator`, `intl-messageformat` and `@formatjs/*`, `lodash-es`, `tldts-*`, `robots-parser`,
`http-link-header`, `js-library-detector`, `lighthouse-stack-packs`, `lookup-closest-locale`, `marky`, `debug`, `ms`,
`ajv` 8 with `ajv-formats`, `tslib`, `legacy-javascript`; esbuild 0.28.0 itself) equal their registry tarballs file by
file.

**The DevTools frontend** (in `index.js` and both workers) is compiled from the git commit above; it has no npm
release at that commit (the `chrome-devtools-frontend` package nearest to it is 1.0.1721762 at 7ee90026, 18 commits
earlier), so its upstream identity is the git commit on the official repository's `main`, which the rebuild shows the
bundle was compiled from.

**Third-party code at the SDK depth** (identical upstream code from Google's Puppeteer, Lighthouse and DevTools teams
and the MCP and npm maintainers, reviewed as this repository reviews SDKs, not line by line). Every one of the five
bundle files was searched for processes, hosts and network calls, code generation, dynamic imports, workers, file
writes, listening sockets and environment reads, and the code around every hit was read:

- *Processes:* only Puppeteer's `spawn` of the browser (`executablePath` `/usr/bin/chromium`); its `taskkill`
  (Windows), `cmd.exe`/`wslinfo`/`wslpath` (WSL) helpers and the ffmpeg screencast (`--experimentalScreencast`, off; no
  ffmpeg in the image) are not reached. No other process in the bundle.
- *Browser download (Puppeteer) - unused and not even present:* rollup kept no download or install function of
  `@puppeteer/browsers`; what is left is dead (an unreferenced table of download-URL functions) or reached only from
  `trimCache()` (version lookups at `googlechromelabs.github.io`, `storage.googleapis.com`,
  `product-details.mozilla.org`), which nothing calls. `proxy-agent` and `yauzl` are external imports that are not
  installed. With `executablePath` given, `computeLaunchArguments` never resolves a cached browser; puppeteer-core's
  configuration is an empty object (no `.puppeteerrc`, no `PUPPETEER_*` configuration variables).
- *Network:* WebSocket/HTTP clients of Puppeteer and `ws` only for `connect()` to a debugging endpoint (not used:
  pipe); `ws`'s `WebSocketServer` class is defined but never instantiated - no listening socket anywhere in the
  server. DevTools' CrUX manager (`chromeuxreport.googleapis.com`) fetches only once its `field-data` setting is
  enabled, which only the server's `populateCruxData` does (`--no-performance-crux`). DevTools' resource loading goes
  through the server's `McpHostBindingAdapter.loadNetworkResource` (`McpContext.loadResource`); its other host methods
  (histograms, user-metrics actions, surveys, AIDA/AI calls, `dispatchHttpRequest`) are no-ops or refuse. DevTools'
  locale fetch is never needed (en-US is registered in memory) and would be a local `file:` URL. The rest of the
  hosts in the bundle are documentation links, third-party-web's entity list and stack-pack data.
- *Lighthouse's own network and telemetry:* Lighthouse can report errors to Sentry (`sentry.io/174697`, a 1 % sample)
  only when its `init` runs with `flags.enableErrorReporting`: nothing in the bundle calls `init`, the server never
  passes that flag, and Lighthouse's build replaced `@sentry/node` by an empty module - nothing is sent. Lighthouse's
  `fetch` from Node.js runs only under `global.isLightrider` (Google's hosted runner, not set); otherwise robots.txt,
  llms.txt, `/.well-known/ai-catalog.json` and source maps are fetched by the browser from the audited page's own
  origin. No other host, no usage statistics, no update check.
- *Code generation:* Puppeteer's `createFunction` (functions the server's own code sends to the page; the query-handler
  sources it interpolates are Puppeteer's), Ajv 8 in the MCP SDK (the server's own schemas), Ajv 6 (only for
  `execute_3p_developer_tool`, off - see Findings), axe-core's templates (run inside the page), the heap-snapshot
  worker's `evaluateForTest` (only reachable from DevTools' test helper, which nothing calls). Dynamic imports: the
  Lighthouse bundle, Lighthouse's `requireWrapper` (only its own bundled gatherers and audits: no configuration with
  plugin paths is ever passed), Puppeteer's WebDriver-BiDi module (Firefox or `PUPPETEER_WEBDRIVER_BIDI_ONLY` only; the
  file is not in the package, so it would fail), `@toon-format/toon`/`@blackwell-systems/gcf` (only with
  `--experimentalDataFormat`, not set; not installed, and ES-module resolution never looks in `$HOME`).
- *File writes:* Puppeteer's temporary profile (`mkdtemp` under `/tmp`, removed on close), screenshot/PDF/trace/
  screencast/heap-snapshot writes only to paths the server passes (each checked by `validatePath`), Lighthouse's
  artifact saver (only with `-G`/`-A` flags, never passed), y18n's locale writes (`updateFiles: false` in yargs).
- *Environment:* besides the server's own variables (Findings) only `PUPPETEER_DANGEROUS_NO_SANDBOX`,
  `PUPPETEER_WEBDRIVER_BIDI_ONLY`, `PUPPETEER_TEST_EXPERIMENTAL_CHROME_FEATURES`, `DEBUG`, `NODE_DEBUG`,
  `WS_NO_BUFFER_UTIL`/`WS_NO_UTF_8_VALIDATE`, `YARGS_MIN_NODE_VERSION`, the locale variables and, for connecting to a
  running Chrome (not used), `CHROME_CONFIG_HOME`/`XDG_CONFIG_HOME`/`LOCALAPPDATA`; none opens a host, a file or a
  process. The image sets none of them.

**The image's hardening holds against these code paths:**

- *Flags and variables:* the server reads no option from the environment (yargs without `.env()`); its variables are
  `CI`/`CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS` (statistics off), `CHROME_DEVTOOLS_MCP_NO_UPDATE_CHECKS`,
  `CHROME_DEVTOOLS_MCP_NO_CONFIG_DISCOVERY` (also covers `PLUGIN_DATA` and `XDG_CONFIG_HOME`),
  `CHROME_DEVTOOLS_MCP_CATEGORY_EXPERIMENTAL_THIRD_PARTY` (applied only when the option is undefined; the entry's
  `--no-category-experimental-third-party` makes it `false`), `CHROME_DEVTOOLS_MCP_CRASH_ON_UNCAUGHT`, `DISPLAY` (headed
  only) and `XDG_RUNTIME_DIR` (the CLI daemon's, not on the server's path). With configuration discovery off and no
  `--config`, `--watchConfig` has no file to watch, and every option is the entry's or its default.
- *Telemetry sender removed:* `ClearcutLogger.initialize` runs only with `usageStatistics`; every other call is
  `ClearcutLogger.get()?.` and does nothing; the watchdog it would spawn is not in the image (forced on, the server
  stops).
- *No debugging port:* `pipe: true` makes Puppeteer add `--remote-debugging-pipe`, unless an argument starting with
  `--remote-debugging-` is given - the only `--chrome-arg` is `--no-sandbox` and no configuration file is read. Nothing
  else listens.
- *`file:` URLs off:* `navigate_page` and `new_page` call `validateUrl` with `fileNavigations: false` (also through
  `view-source:`); the slim `navigate` is disabled (no `--slim`); Lighthouse audits the page's current URL;
  `install_pwa` (which would take a `file:` bundle) is off with `--no-category-pwa`. Files the server reads or writes
  for a tool (`filePath`, `outputDirPath`, `upload_file`, heap snapshots, `get_network_request` bodies, source maps
  named with `file:`) go through `validatePath` (inside the client's roots or `/tmp`, symbolic links resolved; written
  with `O_NOFOLLOW`).
- *Page-defined tools, extensions, web apps:* every such tool is disabled by its category or condition, and
  `ToolHandler` refuses a disabled tool even when called directly; `McpResponse` lists page tools only when the
  category is on.

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
| low | `tools/thirdPartyDeveloper.js` 80-81 | `execute_3p_developer_tool` compiles the JSON schema a web page declares for its tool with Ajv 6 - code generated in the server's process from page input (Ajv's own guidance: do not compile untrusted schemas) | the category is off by `--no-category-experimental-third-party` (and the variable cannot turn it on); the tool is refused |
| low | `McpContext.js` 1022-1025, `McpHostBindingAdapter.js` | a page can name a `file:` source map; the server then reads it, but only inside the roots or `/tmp` (`validatePath`), and what it parses reaches the agent, never the page | container-only `/tmp`; documented |
| info | `McpPage.js` 943-954, `tools/comments.js` | `import('/bundled/...')` and `evaluate` inside a DevTools window (the browser, not the server) | DevTools UI and comment tools off |
| info | `McpResponse.js` 548-569, `third_party/index.js` (`getToonEncode`, `getGcfEncode`) | dynamic imports of the optional peer packages `@toon-format/toon` and `@blackwell-systems/gcf` | only with `--experimentalDataFormat`/`--experimentalToonFormat` (not set); not installed, fails closed |
| info | `daemon/utils.js` 82-104 | runs `ps` (or PowerShell) to identify a CLI daemon's process | the file is kept only for a constant `ClearcutLogger.js` imports; the server never calls these functions |
| info | bundle (`@puppeteer/browsers`) | browser download and version lookup code | tree-shaken to unreferenced or uncalled code (`trimCache` only); `proxy-agent`/`yauzl` absent; `executablePath` given |
| info | Lighthouse bundle | built on a developer's machine and committed (`/Users/alexrudenko/src/lighthouse` in its markers), not by CI | reproduced from tag `v13.5.0` with its `yarn.lock`: identical but for the date and that path |

No backdoor, obfuscated payload, credential collection, hidden host or listening socket was found: not in the
server's own code (read in full), not in the bundle (byte-identical to a rebuild from source, its npm parts identical
to their registry releases, the Lighthouse bundle identical to a build of its tag, reviewed at the SDK depth).

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
  limits, the smoke spec and the review record.
- The reproduction (2026-11-14, Node.js 26.13 and npm 11.20; upstream published with Node.js 24, the output is the
  same): the upstream tree at `af283441` with `npm ci --ignore-scripts` and the DevTools frontend at `f22c6455`, then
  `NODE_ENV=production npm run bundle` - byte-identical to the tarball (361 of 361 files in `build/src`, and the other
  3); Lighthouse at `cb853a38` with yarn 1.22.22 and its lockfile, then its report and MCP-bundle builds - identical but
  for the build date and the checkout path; every bundled npm package compared file by file with a fresh registry
  download.

## Verdict

**Fit to sign once CI passes.** The review is complete under this repository's rule: every line of the server's own
code in the image read (18,195 lines, two passes); the shipped package rebuilt from commit `af283441` with its lockfile
and byte-identical, so the 285,693 bundled lines are exactly upstream's build of upstream code; every bundled npm
package identical to its registry release; the Lighthouse bundle identical to a build of Lighthouse's `v13.5.0` tag;
the DevTools frontend the official repository's commit `f22c6455`; all of that third-party code reviewed at the SDK
depth (processes, hosts, code generation, file access, environment). Nothing malicious was found; the hardening
(statistics, update check, CrUX and configuration discovery off, the sender and the update script removed, a pipe
instead of a debugging port, no `file:` navigations, page-defined tools, extensions and web apps off) holds on every
path read. Remaining before signing: CI builds the image from this tree (the SHA-256 list, the removals, the apt pins)
and both sandbox-ai smoke runs pass (the browser has not run where this was reviewed); then sign the digest of that
run. Not covered, as for every server here: Debian's Chromium (signed with servers/playwright), Node.js 24.22.1 (as
servers/memory) and the build tools themselves (tsc, rollup, esbuild - registry releases; a compromised build tool would
have produced upstream's tarball too).
