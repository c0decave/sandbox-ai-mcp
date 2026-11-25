# duckdb - provenance and review

| | |
|---|---|
| MCP server | this repository, `src/server.py` (MIT), our own (2026-11-25): the four tools of mcp-server-motherduck 1.1.0 for a local DuckDB (`execute_query`, `list_databases`, `list_tables`, `list_columns`) |
| Upstream reviewed | PyPI `mcp-server-motherduck` **1.1.0** (motherduckdb/mcp-server-motherduck, MIT; wheel `mcp_server_motherduck-1.1.0-py3-none-any.whl`, uploaded 2026-10-07 14:43 UTC, 49 days before this review, SHA-256 `da7b98736526576bc8db46984ee3a060e487692c6b1dac174b96fdf98d081410`; sdist `a84cdf9611b3676de6eea742e4993cff936e222dc7f123e37c143bc5c34705dd`), 1,705 lines, read in full. 1.1.1 (uploaded 2026-11-11 17:58 UTC) is 14 days old only at 17:58 UTC today, after this review, and was not used |
| Engine | PyPI `duckdb` **1.5.6** (DuckDB Foundation, MIT; 2026-09-28, 58 days old; the version mcp-server-motherduck 1.1.0 pins, `duckdb==1.5.6`), hash-locked: the CPython 3.13 manylinux wheels (x86_64 `644f54ce99b3b61844bc9a3fe80e0aecb1ea4084b1fffc4396d1569db6111679`, aarch64 `364992ba1089a2b327391cfcb68fd0bd0ce9090cf293baef861a0ba6847abfee`) |
| Python packages | `requirements.txt`, hash-locked from `requirements.in` (locked with `--exclude-newer 2026-11-11`): the shared lock of servers/duckduckgo (`mcp==1.30.0` and its dependencies, the same versions and hashes) plus `duckdb==1.5.6`, which has no dependencies |
| Debian packages | `tini=0.19.0-3+b8` (the image's init, its ENTRYPOINT: no host init needed), `python3=3.13.5-1` (no `ca-certificates`: no network) |
| Base image | the `debian:trixie-slim` digest in `Dockerfile` |
| Licences | `LICENSES/`: DuckDB (MIT), mcp-server-motherduck (MIT), MCP Python SDK (MIT), sandbox-ai-mcp (MIT) |

## Why our own

- Upstream's closure: `fastmcp>=4.0.11` (with authlib, cyclopts, openapi-pydantic, rich, py-key-value-aio,
  opentelemetry-api, ...: 67 packages, `uv pip compile --exclude-newer 2026-11-11`) - a second MCP framework beside
  the SDK this repository has reviewed; our server needs the shared lock and DuckDB only.
- Upstream's read-only mode is DuckDB's `read_only` flag on the database file. It does not limit what SQL reaches:
  `read_csv('/etc/passwd')`, `read_text('/proc/self/environ')`, `COPY ... TO` any path the process may write,
  `INSTALL`/`LOAD` of extensions from extensions.duckdb.org, `SET` of any setting (its README says so: "read-only mode
  still allows local file access and settings changes"). Its default query timeout is off; answers up to 50,000
  characters.
- Its MotherDuck (`md:`), S3 (`s3://`, with credentials from the environment put into `CREATE SECRET` by f-string),
  init-SQL, HTTP-transport and database-switching paths are not wanted here.

## The review (2026-11-25)

### mcp-server-motherduck 1.1.0 (1,705 lines, read in full)

`__init__.py` (the click CLI: `--db-path`, `--motherduck-token`, `--read-write`, `--max-rows` 1024, `--max-chars`
50,000, `--query-timeout` -1, `--init-sql`, `--allow-switch-databases`, HTTP transport), `server.py` (FastMCP 4, an
icon as a data URI, tool annotations), `database.py` (connections: ephemeral read-only connections to a local file,
MotherDuck with the token in the connection string - kept out of answers and logs, S3 through `INSTALL httpfs` and
`CREATE SECRET`, `--init-sql` as a file or a string, the row and character bounds by dropping 10 % of the rows at a
time, the timeout by `threading.Timer` and `interrupt()`), `instructions.py` (texts), `tools/*.py` (the catalog
queries through `duckdb_databases()`, `duckdb_tables()`, `duckdb_views()`, `duckdb_columns()` with
`quote_sql_string` escaping; `switch_database_connection` with an absolute-path check). Findings: no telemetry, no
update check, no network beyond MotherDuck/S3/extension installs; the custom user agent `mcp-server-motherduck/1.1.0`
goes only to MotherDuck. The SQL surface is unrestricted (above). Taken over: the tool names, arguments and answer
shapes (`success`, `columns`, `columnTypes`, `rows`, `rowCount`, `truncated`, `warning`), the catalog queries (with
bound parameters instead of quoted strings), the interrupt timer.

### DuckDB 1.5.6

The engine is a 58 MB native library (`_duckdb.cpython-313-x86_64-linux-gnu.so`) - like radare2 or Chromium in this
catalog an upstream component that is not read line by line; its Python package (`duckdb/`, 14,723 lines: the
relational API, type stubs, the experimental Spark API, pandas/polars/Arrow glue that needs packages not installed)
was grepped (network, processes, environment, telemetry: nothing). The library's strings name only DuckDB's
extension repositories (`extensions.duckdb.org`, `community-extensions.duckdb.org`, `nightly-extensions.duckdb.org`)
as hosts - reached only by `INSTALL`/autoinstall, both off here, and the image has no network; no telemetry library,
no `popen`/`exec`. Upstream's security guide (duckdb.org "Securing DuckDB") is what the server applies:

| Setting | Value | Effect (each checked by `tests/test_duckdb.py` against the engine) |
|---|---|---|
| `allowed_directories` | `['/work/']` | the only folder SQL may read (and, with DUCKDB_WRITE=1, write) |
| `enable_external_access` | `false` (after the above) | any other path refused: `/etc/passwd`, `/work/../x`, a link out of `/work`, `glob('/etc/*')`, `https://` URLs |
| `autoinstall_known_extensions`, `autoload_known_extensions` | `false` | no extension fetched or loaded behind a query |
| `allow_community_extensions`, `allow_unsigned_extensions` | `false` | no third-party or unsigned extension |
| `extension_directory` | `/nonexistent-extensions` | nothing loadable from HOME |
| `python_enable_replacements` | `false` | SQL cannot name the server's Python objects |
| `memory_limit`, `threads`, `temp_directory` | `512MB`, `2`, empty | bounded memory, no spill files |
| `lock_configuration` | `true` (last) | no `SET`/`RESET` of any of these from SQL |

## Our code (`src/server.py`)

- One in-memory DuckDB per server process, opened at the first call; the DuckDB files named in `DUCKDB_DATABASE`
  (comma-separated, inside `/work`, regular files only - no link) attached first, `READ_ONLY` unless DUCKDB_WRITE=1;
  the first becomes the current database.
- Statements are classified by DuckDB's own parser (`extract_statements`) before anything runs: `LOAD`/`INSTALL`
  (type LOAD), extension statements and `UPDATE EXTENSIONS` are always refused; `COPY`, `COPY DATABASE`, `EXPORT`,
  `ATTACH`, `DETACH` are refused in the read-only default. Scratch work in memory (`CREATE TEMP TABLE`, `INSERT`
  into it, `PIVOT`, which makes a temporary type) is allowed; attached files stay read-only by DuckDB's own check.
- A time limit of 60 s per query (`interrupt()`), one query at a time; the connection survives a stopped or
  out-of-memory query.
- Answers: JSON with at most `max_rows` rows (1-1000, default 200) and 24,000 characters (rows dropped from the
  end, with `truncated` and a warning saying what to do); a value is cut at 2,000 characters; dates, decimals, UUIDs,
  blobs (as `\x` hex), lists and structs as JSON can carry them. Errors: DuckDB's message, cut at 2,000 characters.
- Catalog tools with bound parameters; database, schema and table names checked (length, no control characters).
- Tools only (no resources or prompts advertised); the three catalog tools annotated read-only.

## Tests

`tests/test_duckdb.py` (12 tests against DuckDB 1.5.6 itself: files in /work by CSV, Parquet and JSON; seven paths
outside /work refused by DuckDB; the locked configuration; no extensions; the read-only mode - five writes refused,
the folder unchanged, the attached file read-only, scratch tables and PIVOT allowed; DUCKDB_WRITE=1; DUCKDB_DATABASE
paths and aliases; a linked database file refused; the catalog tools and their refusals; row, character and value
bounds; the time and memory limits; error bounds), `test_own_servers.py` `test_duckdb` (inside the image in CI); smoke
spec: 6 real calls (CSV, Parquet, JSON, the three catalog tools on `shop.duckdb`) + 4 refused (a file outside /work,
COPY, INSTALL, SET). Run on 2026-11-25 in a Python 3.13 venv made from `requirements.txt` (`--require-hashes`):
12 passed; the smoke spec over stdio 10/10.

## Risks left

- DuckDB parses untrusted files (CSV, Parquet, JSON, DuckDB databases) in native code: a crafted file is an upstream
  matter, inside a container with no network, no capabilities and a read-only `/work`.
- A query reading a FIFO or a device someone put into `/work` blocks in the kernel, where `interrupt()` cannot stop
  it; the server's next calls wait behind it (DuckDB opens what `/work` holds; sandbox-ai mounts what the user chose).
- With DUCKDB_WRITE=1 and `/work` mounted writable, SQL can overwrite files in `/work` (COPY ... TO): have
  sandbox-ai ask before `execute_query` then.
