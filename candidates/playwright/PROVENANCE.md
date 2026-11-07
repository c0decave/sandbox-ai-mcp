# playwright (prepared) - provenance and audit notes

| | |
|---|---|
| MCP server | microsoft/playwright-mcp 0.0.84 (Apache-2.0), commit `be26c080edfae7c761db1e757c4aff9f6453b4d7`, dependencies from its `package-lock.json` (`npm ci`, integrity hashes) |
| Browser | Debian `chromium` (version to pin) instead of Playwright's download, so the browser is verified by apt |
| Node.js | Debian `nodejs` (version to pin) |

**Re-pin before building:** 2026-11-14 or an older release. `@playwright/mcp` 0.0.84 (commit `be26c080`) was published 2026-10-31 and is too new under the pinning rule (`docs/CANDIDATES.md`) until 2026-11-14; an older release needs its own audit.

**State:** not built. The Debian package versions could not be looked up where this was
prepared; the Dockerfile refuses to build until they are set (see its header).

**Flags:** `--headless --isolated` (profile in memory only), `--no-sandbox` (Chromium's own
sandbox needs user namespaces the container does not grant; the container is the boundary:
no capabilities, read-only root, no new privileges), `--browser chromium --executable-path
/usr/bin/chromium` (to verify: Playwright accepts Debian's Chromium under this channel name),
`--output-dir /tmp/playwright-output`.

**What it can do:** whatever a browser can: open any URL the network lets it reach, fill forms,
run JavaScript, take screenshots and PDFs. `--allowed-origins` and `--blocked-origins` are no
security boundary (upstream says so); the boundary is the container's network.

**To check when building:** memory and process limits (Chromium needs more than 512 MiB and
more than 128 processes; the definition in sandbox-ai sets `--memory=2g --pids-limit=512`), the
tools/list of 0.0.84 for `tools.json`, fonts.

**Network:** full.
