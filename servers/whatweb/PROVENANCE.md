# whatweb - provenance and audit

| | |
|---|---|
| MCP server | this repository, `src/server.py` (MIT); `mcp==1.30.0` and its dependencies hash-locked in `requirements.txt` (byte-identical to web-fetch's) |
| Tool | urbanadventurer/WhatWeb **0.6.4** (GPL-2.0-or-later, `LICENSES/`), tag `v0.6.4`, commit `d279d93042d034f3fd29d5a893d44ccc0595d3f8` (GitHub release of 2026-04-02; the tag ref points at that commit, checked through the GitHub API on 2026-11-12), fetched by commit in the build stage and checked with `git rev-parse` |
| Ruby | Debian `ruby3.3=3.3.13-0+deb13u1` and `libruby3.3=3.3.13-0+deb13u1` (trixie-security), `ruby=1:3.3+b1`, `ruby-rubygems=3.6.7-2`; gems `ruby-addressable=2.8.7-2`, `ruby-public-suffix=6.0.1-1` (with Debian's `publicsuffix` list) |
| Other Debian packages | `python3=3.13.5-1`, `python3-venv=3.13.5-1` (purged after the venv is made), `ca-certificates=20250419+deb13u1`; build stage `git=1:2.47.3-0+deb13u1` |
| Base image | the `debian:trixie-slim` digest in `Dockerfile` (the same as web-fetch's) |

**Pinning rule:** 0.6.4 is WhatWeb's newest release (2026-04-02), far more than 14 days before 2026-11-12. The
Debian versions are those of the trixie and trixie-security indexes read on 2026-11-12 (`apt-get install` refuses a
version the archive no longer has; trixie-security keeps only the newest `ruby3.3`, so a newer Ruby security update
stops the build with apt's message: take the new version from the index then). The other dependencies of these
packages (`libruby`, `rake`, `ruby-csv`, `ruby-webrick` and the like, `libssl3t64`) follow from them in that
archive and are not pinned one by one, as for the other images.

## Why

WhatWeb names the software a web site runs (1,832 plugins: CMS and versions, frameworks, servers, libraries,
analytics, devices). No MCP server of WhatWeb's authors exists (searched on 2026-11-12). Third-party ones were looked
at by name and not used: `devkindhq/whatweb-mcp` (2 stars, last pushed 2026-11-09, too new for the 14-day rule and
not upstream), `openbashok/pentest-mcp` (a bundle of many tools), `Drblack000/NebulaFinger` (another tool). This
server is small and our own: it runs the unchanged WhatWeb with a fixed argument list and returns its JSON log.

## Audit

### What was read

- **Read in full:** the `whatweb` script (746 lines: option parsing, the run, logging set-up), and of `lib/`
  everything on the path of a scan: `whatweb.rb`, `gems.rb`, `whatweb/scan.rb`, `whatweb/redirect.rb`,
  `whatweb/parser.rb`, `whatweb/version.rb`, `target.rb`, `extend-http.rb`, `plugins.rb`, `plugin_support.rb`,
  `helper.rb`, `version_class.rb`, `messages.rb`, `logging.rb`, `logging/json.rb`, `simple_cookie_jar.rb`
  (its file parts). The other loggers (`logging/*.rb`) were screened: they define classes and do nothing unless their
  option is given; `mongodb.rb` and `elasticsearch.rb` (network) are removed from the image.
- **Plugins, screened automatically, every hit read by hand:** all 1,832 files of `plugins/` and the 7 of
  `my-plugins/` (a script of patterns: `system`/`exec`/`spawn`/`fork`, backticks and `%x`, `IO.popen`, `Open3`,
  `Kernel.open`/`open(`/`URI.open`, `File`/`Dir`/`FileUtils`/`IO.read|write`, `eval`/`instance_eval`/`class_eval`/
  `send`/`define_method`/`const_get`, `Marshal`/`YAML`/`JSON.load`, `require`/`load`, `Socket`/`Net::`/`Resolv`,
  `ENV`/`ARGV`/global variables, `Base64`/`pack`/hex strings, `open_target`/`Target.new`/`Version.new`, absolute
  `:url`s, `Thread`/`exit`/`trap`, `class`/`module`/`def`, `Kernel`/`ObjectSpace`/`STDOUT`/`__FILE__`/`.call`), plus
  a structural check that every plugin file consists of one `Plugin.define do ... end` with nothing before or after
  it (26 files have `=begin`/`=end` comment blocks: dead code, read). `plugins-disabled/` (30 plugins, never loaded
  here) is not in the image.
- **Gems on the path:** `addressable` 2.8.7 and `public_suffix` 6.0.1 as Debian ships them (screened for the same
  constructs: the only `Marshal.load` reads addressable's own `data/unicode.data` from the read-only package; the
  public suffix list is read from `/usr/share/publicsuffix`; the native IDN backend needs the `idn` gem, which is
  not installed, so the pure one is used). `ipaddr`, `json`, `getoptlong`, `resolv-replace`, `open-uri` are Ruby
  3.3's default gems in `libruby3.3`. Ruby itself is Debian's build and was not reviewed beyond that.

### Findings

No backdoor, no telemetry, no update check, no download of code. WhatWeb contacts nobody but the target: no plugin
of `plugins/` opens a connection to a fixed host or does DNS lookups of its own (the Country plugin looks the
address up in the shipped `country-ips.dat`). Points that shape this server:

- **Targets can be files and IP ranges** (`scan.rb` `make_target_list`, `target.rb` `initialize`/`open_file`: an
  argument that exists as a file is read as an HTTP answer; CIDR and `a.b.c.d-e` ranges expand; `--input-file`
  reads a list). The server passes exactly one checked `http(s)` URL, after `--` (GetoptLong stops there), with
  the working directory a fresh empty folder, so no argument can name a file or a range.
- **`--custom-plugin` and `--grep` build Ruby source and `eval` it** (`plugin_support.rb` `custom_plugin`);
  `--plugins`/`-p` loads Ruby files from any path given. Neither is ever passed; no option is taken from the agent.
- **The load path includes `.`** (`whatweb` line 37 `$LOAD_PATH.unshift(..., '.')`): a `json.rb` in the working
  directory would be loaded. The working directory is the fresh folder, holding only WhatWeb's own log
  `result.log` and `stderr.txt`.
- **Aggression 4** fetches the `:url` of every plugin for every target ("a lot of HTTP requests per target"); the
  server offers 1 and 3 only and refuses 4 before anything runs.
- **Aggression 3** (`plugins.rb` `ScanContext#x`): for each plugin that matched passively, its `aggressive` block
  (35 plugins) and every `:url` of its matches (273 plugins) are fetched from the same site: `URI.join` of the
  target with paths fixed in the plugin (no plugin has an absolute or `//host` URL; every `open_target`,
  `Target.new` and `Version.new` call sits inside an `aggressive` block, read). `Version.new` (WordPress, Drupal,
  Joomla, Concrete5, DotNetNuke, MODX, SilverStripe, Centreon) downloads dozens of version files; `zend.rb` sends one
  POST (`whatweb=true`) to the target. That is active probing of the target: only for sites one may scan.
- **Redirects:** with the default `always`, WhatWeb queues the target of a `Location` header or a meta refresh,
  including another host (`target.rb` `get_redirection_target`, `redirect.rb`). The server runs WhatWeb with
  `--follow-redirect=never` and follows HTTP 3xx and meta-refresh targets itself (at most 5, http(s) only, no loops),
  checking each new URL's addresses before WhatWeb runs again.
- **TLS is not verified** (`target.rb` `open_url`, `extend-http.rb` `connect`: `VERIFY_NONE`, minimum version 0):
  fine for fingerprinting, which sends nothing secret; the agent should not take a site's identity from it.
- **Cookies:** cookies a site sets are added to WhatWeb's global request headers for the following requests
  (`target.rb` `open_url`, `$CUSTOM_HEADERS['Cookie']`), also to another host. Here every WhatWeb run has one host
  (redirects start a new run), so they go back only to the site that set them. No cookie jar file is written
  (`--cookie-jar` is not passed).
- **No body limit:** `Net::HTTP` reads a whole answer into memory; the container's memory limit and the run timeout
  bound it.
- **Regular expressions** of 1,800+ plugins run over text the site sends; a pathological page can make one slow:
  bounded by the run timeout.
- **Startup hooks:** `country.rb` would write `country-ips.dat` if only `IpToCountry.csv` were present; the `.dat`
  is shipped and the CSV is removed, so it only reads (the root is read-only anyway). Plugin tutorial 6 has empty
  hooks; the tutorials are removed.
- Minor: two plugin files define `nopCommerce` (the later one wins; 1,831 plugin names load), `ee.rb` is an
  easter egg matching only WhatWeb's own home page, `awstats.rb` has a dead `puts` in a comment block.

### The server

**Tools (`tools.json`):** `fingerprint(url, aggression=1, follow_redirects=True)` and `plugin_info(search)`.

- **URL check** (before every WhatWeb run, so before each redirect hop): a string of at most 2,048 characters
  without control characters or spaces, scheme `http` or `https`, a host, no user name or password; every address
  the name resolves to must be public (web-fetch's check, NAT64 64:ff9b::/96 and 64:ff9b:1::/48, IPv4-mapped and
  6to4 addresses judged by the IPv4 address they carry). With `ALLOW_PRIVATE_TARGETS=1` (exactly `1`) the private
  ranges 10/8, 172.16/12, 192.168/16, 100.64/10 and fc00::/7 are allowed too; loopback, link-local (cloud metadata
  169.254.169.254), unspecified, multicast, broadcast, documentation and reserved addresses never are.
- **The run line** (an argument list, never a shell): `/usr/bin/ruby3.3 -W0 /opt/whatweb/whatweb --colour=never
  --quiet --log-json=FOLDER/result.log --aggression=1|3 --follow-redirect=never --max-redirects=0 --max-threads=1
  --open-timeout=10 --read-timeout=20 -- URL`, its working directory and `HOME`/`TMPDIR` a fresh folder made by
  `tempfile.mkdtemp` below `/tmp` and removed afterwards; environment only `PATH`, `HOME`, `TMPDIR`, `LANG`,
  `LC_ALL`; stdin empty, stdout discarded, stderr into a file of which the last 64 KiB are read; its own session, the
  whole process group killed after 120 s (aggression 1) or 300 s (aggression 3). User agent: WhatWeb's default
  `WhatWeb/0.6.4` (honest; no option to change it).
- **The answer:** the JSON log is read only if it is at most 2 MiB; per URL visited: `url`, `http_status` and the
  plugins matched with their `string`, `version`, `os`, `account`, `model`, `firmware`, `module`, `filepath`
  (at most 200 plugins, 20 values per field, 500 characters per value) and `certainty` when below 100;
  WhatWeb's `request_config` is dropped. A target that gave no answer becomes an error with WhatWeb's last error
  lines. Everything in it was written by the web site: data for the agent, never instructions (the tool
  description says so).
- **`plugin_info(search)`:** `whatweb --colour=never --info-plugins=WORD` for a word of 2-40 letters, digits, space,
  `. _ -` (no comma: no list), stdout into a file of the fresh folder, at most 20,000 characters returned with the
  plugin names found. No network.

**Limits:** sandbox-ai's defaults (512 MiB, 128 processes, the 64 MiB `/tmp`): WhatWeb is one Ruby process with
one scan thread; `/tmp` holds only the run folder.

**Network:** full. Requests come from the address of the container's network: the target sees it (`--vpn PROFILE`
hides it). The address check resolves the name before WhatWeb runs and WhatWeb resolves it again (`Resolv`, through
`resolv-replace`): a resolver that answers differently a moment later (DNS rebinding) is not ruled out; the
container should get no more than the outside network.

**Tested:** natively (`tests/test_own_servers.py` `test_whatweb`, also run inside the image by CI without network):
handshake, tools/list, `file:`, metadata, loopback, user:password URLs, a space, aggression 4, comma and option-like
search words and a private address without `ALLOW_PRIVATE_TARGETS` refused; the address rules for 21 addresses
with and without it; the bounded parsing of WhatWeb's JSON log (`tests/fixtures/whatweb-example.json`, written in
the format of `lib/logging/json.rb`; no Ruby here to record a live one); and, with a stand-in for WhatWeb, the run
line (the flags above, no plugin/file/proxy/cookie-jar option, the five environment variables, the folder removed),
a redirect followed by the server with both hops checked, aggression 3 passed through, an error and a cut-off answer
reported, and the timeout killing the run. Not built or run here (no Podman, no Ruby): the image build (which
checks the commit, the licence's SHA-256, the 1,832 plugin files, the removals, `--version` and that all 1,831
plugin names load without an error) and the smoke spec (`https://example.com/` fingerprinted with its title,
`plugin_info` for WordPress, four refused calls) run in CI.
