# chrome-devtools (prepared) - provenance and audit notes

| | |
|---|---|
| MCP server | ChromeDevTools/chrome-devtools-mcp 1.12.0 (Apache-2.0), tag `chrome-devtools-mcp-v1.12.0`, commit `af2834411a564d366f9cab63efb046d9084f4dba` (2026-10-22), from the npm package `chrome-devtools-mcp@1.12.0` (integrity to pin) |
| Browser | Debian `chromium` `156.0.8078.79-1~deb13u1` (trixie-security) instead of a Chrome download |
| Node.js | Debian `nodejs` `20.19.2+dfsg-1+deb13u3` (the server accepts 20.19+) |

**State:** not built. The npm registry was not reachable where this was prepared, so the
package's `dist.integrity` is open and the Dockerfile refuses to build until it is set. The
GitHub release has no assets. Not checked: that the npm tarball matches a build of the commit.

**Why the package:** `package.json` has no runtime `dependencies` (everything, Puppeteer and
Lighthouse included, is bundled by rollup into `build/src`), so the tarball's SHA-512 pins
the whole server. Building the commit needs Node >= 22.18 for its `.ts` build scripts.

**Flags:** `--headless --isolated` (temporary profile), `--executable-path /usr/bin/chromium`
(upstream officially supports Chrome and Chrome for Testing only; Chromium "may work"),
`--chrome-arg=--no-sandbox` (same reason as playwright: no user namespaces in the container),
`--no-usage-statistics` and `CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS=1` (on by default
upstream: Clearcut logging to `play.googleapis.com`, `src/telemetry/watchdog/ClearcutSender.ts`),
`--no-performance-crux` (otherwise performance tools send trace URLs to
`chromeuxreport.googleapis.com`, `src/tools/performance.ts`), and
`CHROME_DEVTOOLS_MCP_NO_UPDATE_CHECKS=1` (otherwise a periodic check against
`registry.npmjs.org`, `src/utils/check-for-updates.ts`).

**Tools (61 names in `src/tools/*.ts`):** input (click, click_at, hover, fill, type_text,
drag, fill_form, upload_file, press_key, handle_dialog), pages (list_pages, select_page,
close_page, new_page, navigate_page, resize_page, wait_for, get_tab_id), inspection
(take_snapshot, take_screenshot, get_css_styles, get_console_message, list_network_requests,
get_network_request, evaluate_script), performance (performance_start_trace,
performance_stop_trace, performance_analyze_insight, lighthouse_audit), emulate, memory
(take_heapsnapshot and 13 more heap-snapshot tools: get_heapsnapshot_*, close_heapsnapshot,
compare_heapsnapshots, query_heapsnapshot_objects, analyze_heapsnapshot_contexts), extensions
(install_extension, uninstall_extension, list_extensions, reload_extension,
trigger_extension_action), PWA (install_pwa, uninstall_pwa, launch_pwa, get_os_app_state),
WebMCP (list_webmcp_tools, execute_webmcp_tool), DevTools UI (open_devtools,
get_devtools_comments, resolve_devtools_comment, reveal_in_devtools; experimental), and
screencast_start/stop (experimental, needs ffmpeg, not in the image). Some are behind
`--experimental*` / `--category*` flags; the tools/list of the built image is authoritative.

**What it can do:** everything a browser can on the network the container gets: open any URL
(including `file:` inside the container, unless `--no-file-navigations`), run JavaScript in
pages (`evaluate_script`, `navigate_page`'s `initScript`; off with
`--no-javascript-evaluation`), read request and response headers including cookies and
authorization headers (`--redact-network-headers` hides some). Tools that read or write
files (`upload_file`, `take_screenshot`/`take_heapsnapshot` with `filePath`,
`install_extension`) are restricted to the OS temp directory when the client does not send
MCP roots (`filesystemRoot`, `src/config/mcp-options.ts`); in the container that is `/tmp`,
and nothing of the host is mounted.

**To check when building:** that Puppeteer launches Debian's Chromium with these flags,
memory and process limits (as for playwright: `--memory=2g --pids-limit=512`), that the
`/tmp` tmpfs (64 MiB, `noexec`) is large enough for the profile and traces, the tools/list of
1.12.0 for `tools.json`, fonts.

**Network:** full (the browser goes wherever the agent sends it).
