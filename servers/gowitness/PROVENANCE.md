# gowitness - provenance and audit

| | |
|---|---|
| MCP server | this repository, `src/server.py` (MIT): two tools around gowitness's `scan single` |
| gowitness | sensepost/gowitness **3.2.2** (GPL-3.0), tag `3.2.2`, commit `601c84367aaf26eae7d1b5181b70633cb662cf66` (GitHub release of 2026-10-11, commit of 2026-10-11), built from source in the image with `gowitness-chromedp-only.patch` and ten files removed (below) |
| Go modules | the release's `go.mod`/`go.sum` (95 modules); `go mod download` and `go mod verify` check every archive against `go.sum`. 43 of them are linked after the reduction, each listed with its licence under `/usr/share/doc/sandbox-ai-mcp-gowitness/modules` in the image |
| Go toolchain | `golang:1.26-trixie` (Go 1.26.10) by digest, build stage only |
| Browser | Debian `chromium` `156.0.8078.79-1~deb13u1` (trixie-security), not a download, so apt verifies the browser (the same version `servers/playwright` pins) |
| Python packages | `mcp==1.30.0` and its dependencies, hash-locked in `requirements.txt` (byte-identical to `servers/web-fetch`) |
| Debian packages | `python3=3.13.5-1` (`python3-venv=3.13.5-1` only to build the venv, then purged), `chromium=156.0.8078.79-1~deb13u1`, `ca-certificates=20250419+deb13u1`, `fonts-liberation=1:2.1.5-3`, `tini=0.19.0-3+b8` |
| Base image | the `debian:trixie-slim` digest in `Dockerfile` (the one the other servers use) |

**Pinning rule:** 3.2.2 is gowitness's newest release, published on 2026-10-11, 32 days before this review
(2026-11-12); 3.2.1 (2026-10-10) and 3.2.0 (2026-09-14) are older. Every module the release pins is older than the
release. The Debian versions are those of the trixie and trixie-security indexes read on 2026-11-12; `apt-get
install` refuses a version the archive no longer has, so a superseded `chromium` (trixie-security keeps only the
newest) stops the CI build with apt's message: then take the new version from `apt-cache policy chromium` in the
pinned base, here and in `servers/playwright`.

## Why our own server

sensepost publishes no MCP server for gowitness (checked on GitHub on 2026-11-12; the only search hit,
k3nn3dy-ai/screenshot_mcp, is an unrelated screenshot tool with no release). gowitness is a command-line tool with a
report web server; the server here runs only its single-URL scan, with an argument list it builds itself, and turns
gowitness's JSON line and screenshot file into a bounded MCP answer.

## Audit

### What was read

The bytes reviewed are the ones the build uses: the tag's tree fetched by commit, and every module of `go.mod`
rebuilt from its upstream repository (GitHub, GitLab for modernc.org) at the pinned version and checked against
`go.sum`'s `h1:` hash - all 95 matched on 2026-11-12.

- **gowitness, read line by line:** everything on the path the server runs - `main.go`, `cmd/root.go`,
  `cmd/scan.go`, `cmd/scan_single.go`, `cmd/version.go`, the `init` functions of the other `cmd/scan_*.go` (flag
  definitions only), `pkg/runner` (`runner.go`, `options.go`, `driver.go`), `pkg/runner/drivers/chromedp.go` and
  `userdata.go`, `pkg/writers/writer.go` and `json.go`, `pkg/models/models.go`, `pkg/log`, `internal/islazy`,
  `internal/ascii`, `internal/version`, `pkg/imagehash` - and the removed files far enough to know what they do.
  Not on the server's path and only screened: `pkg/readers` (the file, CIDR, Nmap and Nessus scan modes) and the CSV,
  stdout, memory and none writers.
- **Its dependencies, read where they act:** chromedp's browser launch (`allocate.go`, `allocate_linux.go`, the
  remote-allocator part of `util.go`), wappalyzergo's loader (`tech.go`, `fingerprints_data.go`, the pattern
  compiler in `patterns.go`), glamour's style detection, termenv's terminal queries, colorprofile's tmux check.
- **Every linked package screened** (161 packages of 43 modules, 259,000 lines after the reduction; 278 packages,
  881,000 lines before it) for `init` functions (all 128 of the unreduced build read), process starts, network
  dials and HTTP clients, environment reads, file writes, `go:embed`, `go:linkname`/`unsafe` and fixed hosts; every
  hit read. The fixed hosts that remain are documentation strings in the generated DevTools protocol code
  (cdproto) and bluemonday/goldmark comments; nothing dials them.

No backdoor, telemetry, update check or download was found in gowitness or in what it links after the reduction.

### Findings, and what was done

1. **The go-rod driver ships prebuilt binaries and downloads a browser** (not on the server's path, but linked by
   upstream): `github.com/ysmood/leakless` embeds its helper as gzip+base64 blobs (`bin_amd64_linux.go`, one per
   platform) that go-rod's launcher writes to a temporary folder and runs; `github.com/ysmood/fetchup` downloads a
   Chromium when no browser path is given. Neither can be reviewed as source. **Removed:**
   `pkg/runner/drivers/go-rod.go` and the `gorod` case of `cmd/scan.go`; go-rod, leakless, fetchup, got, gson and
   goob are no longer linked (the build checks it).
2. **The report commands embed a prebuilt web UI** (`web/ui/dist`, 1.1 MB of minified JavaScript, served by
   `gowitness report server`) and open SQLite, MySQL and PostgreSQL databases. Not offered by the server and not
   reviewable as source. **Removed:** `cmd/report*.go` (7 files) and `pkg/writers/db.go` with its use in
   `cmd/scan.go`; the `web` and `pkg/database` packages, gorm, its three drivers, pgx, the MySQL driver,
   modernc.org's SQLite and libc (about 400,000 lines of transpiled C), chi and swag are no longer linked.
3. **gowitness lifts Chromium's port blocklist** (`chromedp.Flag("explicitly-allowed-ports", restrictedPorts())`
   with all of Chromium's restricted ports: SMTP, POP3, IMAP, IRC, SIP, X11...): any page it opens could make the
   browser speak HTTP to those services on the container's network (cross-protocol requests). **Removed** (the flag
   and `restricted_ports.go`): Chromium's own blocklist applies again; a screenshot of a web server on one of those
   ports fails with `ERR_UNSAFE_PORT`.
4. **The PNG and JPEG decoders came from go-rod:** the chromedp driver decodes every screenshot for its perception
   hash (`image.Decode`), and upstream registers the two formats only through go-rod's `lib/utils`. Without it every
   screenshot would fail ("failed to decode screenshot image"). **Added:** `pkg/runner/drivers/image_formats.go`
   (two blank imports); the build checks that `image/png` and `image/jpeg` are linked.
5. **Terminal probing at start-up:** `internal/ascii` renders gowitness's help texts with glamour in an `init`
   function; with stdout not a terminal glamour takes its no-TTY style and termenv sends no terminal query.
   colorprofile runs `tmux info` only when `TMUX` is set. The server starts gowitness with stdin empty, stdout a
   pipe and six environment variables (`PATH`, `HOME` and `TMPDIR` in the call's folder, `LANG`, two XDG folders):
   no `TMUX`, `TERM`, `GLAMOUR_STYLE`, proxy, `CHROMIUM_FLAGS` or cobra completion variables.
6. **How the browser runs** (chromedp's `DefaultExecAllocatorOptions` with gowitness's flags): `--headless`,
   `--no-sandbox` (Chromium's sandbox needs user namespaces the container does not grant; the container is the
   boundary), `--ignore-certificate-errors` (a site with a bad certificate is still shown; the TLS details are
   returned), `--disable-background-networking`, component update, sync, breakpad, crash reporter, translate,
   domain reliability and pings off, permission prompts denied, a fixed desktop Chrome 128 user agent, the window
   size asked for, a temporary profile in the call's folder. JavaScript dialogs are accepted, cookies cleared per
   tab. chromedp starts Chromium with `--remote-debugging-port=0`: DevTools listens on a random port of the
   container's own loopback for the run (Chromium checks the Host and Origin of DevTools connections) and gets
   `SIGKILL` when gowitness ends (`Pdeathsig`).
7. **wappalyzergo** (technology fingerprints) compiles the JSON fingerprints embedded in the module with Go's
   linear-time regular expressions and matches the first response's headers and the page's HTML; it reads no file
   (`NewFromFile` is not used) and makes no request.

The patch and the removed files are listed in `Dockerfile`; the build fails if the patch does not apply, if a removed
package is still linked, if the decoders are missing, or if gowitness's own tests (`internal/islazy`,
`pkg/runner/drivers`) fail.

### The server

**Tools (`tools.json`):** `screenshot(url, full_page, width, height, delay, timeout, format, jpeg_quality)` and
`screenshot_many(urls, ...)` (1-5 URLs, one after the other, JPEG by default). The answer is a JSON text (final URL,
status, reason, protocol, title, headers, TLS, technologies, cookie names and flags - never their values -,
console messages, the page's requests, perception hash, the image's type, size and SHA-256) and the image as MCP
image content. The page's HTML, which gowitness records for its fingerprints, is not returned.

**Arguments:** URLs only http or https, at most 2048 characters, no spaces or control characters, a host name, no
user name or password, a port 1-65535. The host is resolved and every address must be public (global unicast; for
IPv6 carrying an IPv4 address - NAT64, IPv4-mapped, 6to4 - that one too, as in `servers/web-fetch`); with
`ALLOW_PRIVATE_TARGETS=1` (exactly `1`) also 10/8, 172.16/12, 192.168/16, 100.64/10 and fc00::/7. Loopback,
link-local (cloud metadata at 169.254.169.254), unspecified, multicast, documentation and reserved addresses are
always refused. `width` 320-3840, `height` 240-2160, `delay` 0-10 s, `timeout` 5-120 s and at least `delay` + 5,
`format` png or jpeg, `jpeg_quality` 10-100. No other gowitness option can be reached: no JavaScript, headers,
proxy, profile folder, remote browser, database, other writers or scan modes.

**Running gowitness:** `asyncio.create_subprocess_exec` with an argument list (never a shell), stdin empty, its own
session (the whole process group, Chromium included, is killed when the call ends or after `timeout` + 45 s), one
browser at a time, in a fresh folder under `/tmp` (screenshot, JSON line, Chromium's profile and temporary files)
that is removed after the call. Its stderr is kept to its last 64 KiB and only its last three error lines (300
characters each) are returned when it recorded nothing.

**Bounds:** a screenshot at most 5 MiB (else an error that suggests JPEG, a smaller window or no full page), all
images of one `screenshot_many` call at most 12 MiB (the rest are named as left out), the JSON line at most 32 MiB;
the screenshot must be the one plain file gowitness wrote and start with the PNG or JPEG signature. Every returned
text is cut (1000 characters per header value, 500 per title or console message), lists bounded (60 headers, 100
technologies, 60 cookies, 20 console messages, 50 requests, 50 certificate names) with their full counts.

**What it cannot rule out:** the address check covers the URL given, before gowitness runs. Redirects, frames,
scripts and images the page then loads go wherever the container's network lets them (local network included), and
Chromium resolves the name again itself (DNS rebinding). The boundary is the container: no capabilities, read-only
root, nothing of the user mounted, a `noexec` `/tmp`. Each visit comes from the user's address (`--vpn PROFILE`
hides it). Everything returned - title, headers, console messages, cookie names, the picture itself - is written
by whoever runs the site: data for the agent, never instructions.

**Limits:** Chromium needs more than sandbox-ai's defaults (512 MiB, 128 processes, which counts threads): add the
server with `--memory 2g --pids 512` and a /tmp of 768m (`smoke.json` runs it with these; the `tmp` value is for
the run line's `/tmp` size once the smoke harness and sandbox-ai take it). gowitness starts Chromium with
`--disable-dev-shm-usage`, so its shared memory, profile and cache are in `/tmp`: the default 64 MiB is enough for a
simple page, not for large ones.

**Network:** full.

**Tested:** offline (`tests/test_own_servers.py` `test_gowitness`: tools/list, eleven refused calls - `file:`,
`javascript:`, loopback, IPv6 loopback, cloud metadata, user:password, an over-long URL, bad width, format, delay and
timeout, six URLs -, the address policy with and without `ALLOW_PRIVATE_TARGETS`, the argument list and environment,
the summary of a recorded gowitness JSON line in `tests/fixtures/gowitness-example.jsonl`, written in the format of
`pkg/models` and not recorded live; CI also runs it inside the image). The patch was checked against a clean checkout
of the commit. In CI after the build: the smoke spec (a screenshot of `https://example.com/` must come back as
`image/png`, `screenshot_many` must record its title, three refused calls), the tools/list against `tools.json`,
Trivy, and the Bubblewrap run. gowitness was not compiled here (no Go toolchain where this was written): the image
build is the first compilation of the reduced tree.
