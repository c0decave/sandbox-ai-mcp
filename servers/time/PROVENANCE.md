# time - provenance and audit

| | |
|---|---|
| MCP server | upstream's `mcp-server-time` **2026.10.28** (modelcontextprotocol/servers `src/time`, MIT / Apache-2.0 transition, `LICENSES/modelcontextprotocol-servers-LICENSE.txt`), started by this repository's `src/server.py` |
| Upstream reviewed | PyPI wheel `mcp_server_time-2026.10.28-py3-none-any.whl`, uploaded 2026-10-28 21:06 UTC (21 days before this review), SHA-256 `4b8a1865e8c45da2d2247e72ca83ea087e5c8bc597c9ca93c63e9103aeb46c31`; its three modules are byte-identical to `src/time/src/mcp_server_time/` of commit `74af74c8ba3bfd27f3b0d9ae6c7e4c43965e7859` ("chore: stamp Python CalVer versions for 2026.10.28", 2026-10-28 18:49 UTC) and to the sdist (`b2b62b44...42cf3`): `server.py` SHA-256 `4bc15c31a98b694ad9c2abeaf75277f9cbeb5716d81989d8d7d7623bc175a095`, `__init__.py` `54a9c499...2ff12d`, `__main__.py` `1432ee99...2ca6c7` |
| Why not newer | 2026.11.4 (uploaded 2026-11-04 21:34 UTC) is 14 days old only on 2026-11-18 21:34 UTC, after this review; 2026.11.11 and 2026.11.18 are too new |
| Python packages | `requirements.txt`, hash-locked (`requirements.in`): the MCP Python SDK **2.3.0** lock of servers/osint-mcp, reviewed there (same versions of every shared package), plus `mcp-server-time` 2026.10.28, `tzdata` 2026.6 (2026-10-28, IANA 2026f) and `tzlocal` 5.4.5 (2026-10-22); every pin was published before 2026-11-04 (locked with `--exclude-newer 2026-11-04`) |
| Debian packages | `python3=3.13.5-1` (no `ca-certificates`: no network) |
| Base image | the `debian:trixie-slim` digest in `Dockerfile` |

## The review (2026-11-18)

**Everything that runs of upstream was read:** `mcp_server_time/server.py` (288 lines), `__init__.py` (19),
`__main__.py` (3); the wheel's `RECORD`, `entry_points.txt` (one console script) and `METADATA`. A wheel runs no code
when installed. The sdist's `pyproject.toml` builds with hatchling, without hooks.

**What it does:** an `MCPServer` (the SDK 2.x high-level server) named `mcp-time` with two tools, both annotated
read-only: `get_current_time(timezone)` (`datetime.now(ZoneInfo(...))`: ISO time, weekday, DST) and
`convert_time(source_timezone, time, target_timezone)` (`HH:MM` of today in the source zone; refuses a time skipped by
a clock change; the offset between the zones). Zone names are accepted only when `zoneinfo` loads them and they are
an exact key of `available_timezones()` (upstream's own fix for case-insensitive file systems). An unknown tool is a
JSON-RPC `-32602` error (upstream's middleware). The local zone, named in the tool descriptions, comes from
`--local-timezone` or `tzlocal.get_localzone_name()`, else `UTC`. No network, no file written, no process, no
telemetry, no update check, no dynamic code.

**Dependencies reviewed for this server** (the rest is servers/osint-mcp's reviewed SDK 2.3.0 lock: its scan there
covers every wheel of it, OpenTelemetry is the API alone with no exporter):

| Package | Lines | How |
|---|---|---|
| `tzlocal` 5.4.5 | 1,260 in 5 modules | read in full (`unix.py`, `utils.py`, `__init__.py`; `win32.py` and the zone-name table `windows_tz.py` only import on Windows). Reads `TZ`, `/etc/timezone`, `/var/db/zoneinfo`, `/etc/sysconfig/clock`, `/etc/conf.d/clock`, the `/etc/localtime` link; its one `subprocess` (`getprop`) runs only on Termux (`/system/bin/getprop` present) |
| `tzdata` 2026.6 | 6 lines of Python (`__init__.py`: two version strings) | the rest is the binary zone files and `zones`, data read by `zoneinfo` only |

**Findings in upstream (none a backdoor or malicious code):**

| Severity | Where | What | Here |
|---|---|---|---|
| low | `get_zoneinfo` | an invalid zone is echoed in full in the error (a 200,000-character argument gives a 200,000-character answer), and for a path-like value or a folder of the database `zoneinfo`'s message can name a file of the container | every zone argument checked first: 1-64 characters of `[A-Za-z0-9_+-]`, at most four `/`-separated parts; the message does not echo it |
| low | `convert_time` | an over-long `time` is parsed (cheap; error text fixed) | at most 16 characters |
| info | `serve` | the SDK registers resources and prompts handlers: the server announced both capabilities with nothing behind them | `tools_only`: only `tools` is announced, `resources/list` and `prompts/list` are `-32601` |
| info | the container | `tzlocal` finds no zone in the slim image (UTC), so a model is told UTC is local | `LOCAL_TIMEZONE` (checked like upstream's flag; a bad one ends the server before the handshake with one line) |

## This server

`src/server.py` imports upstream's module, builds its server with `create_server(local zone)`, wraps each tool's
function (argument checks before upstream's code; an answer over 24,000 characters refused - upstream's are a few
hundred), removes the resources and prompts handlers, and runs it over stdio. Tool names, schemas, descriptions and
answers are upstream's.

**Network:** none. **Mounts:** none. **Secrets:** none.

## Tested

Natively with this lock (`tests/test_time.py`): handshake (`capabilities` only `tools`, `serverInfo.version`
2026.10.28), `tools/list` equal to `tools.json`, `resources/list` and `prompts/list` -32601; the local zone from
`LOCAL_TIMEZONE` and from `TZ`; a bad `LOCAL_TIMEZONE` (unknown, a path, 500 characters) ends the server with one short
line and nothing on stdout; both tools (Kathmandu's +05:45, UTC to Kolkata +5.5h, Berlin to UTC); refused arguments
with short answers that name no file: a path, an absolute path, a folder of the database, a wrong case, empty, 200,000
characters, NUL, a list of 50,000 numbers, a 100,000-character time, `25:61`, an unknown tool (-32602). The smoke
spec (two real calls, three refused). Not run here: the image build (no container engine on this machine).

## Verdict

Upstream reviewed completely; no backdoor, telemetry or unexpected access. Packaged on the reviewed SDK 2.3.0 lock with
two new, reviewed packages. **Pending**: fit to sign once CI has built it and both smoke reports pass.
