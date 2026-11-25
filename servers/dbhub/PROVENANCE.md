# dbhub - provenance and review

| | |
|---|---|
| MCP server | this repository, `src/server.py` (MIT), our own (2026-11-25): the two tools of Bytebase's DBHub (`execute_sql`, `search_objects`) for PostgreSQL and SQLite |
| Upstream reviewed | bytebase/dbhub **v1.6.1** (MIT; npm `@bytebase/dbhub` 1.6.1 published 2026-11-11 05:48 UTC, 14 days before this review; the source tarball `codeload.github.com/bytebase/dbhub/tar.gz/refs/tags/v1.6.1`, SHA-256 `a38cb00b0651c2f2cf56e3173e1d42bcf13f700fefa457c0bcdf9000385e01e6`): the parts this server ports read in full (below), the rest grepped. Not installed - see "Round 2's reasons" |
| Python packages | `requirements.txt`, hash-locked from `requirements.in` (locked with `--exclude-newer 2026-11-11`): the shared lock of servers/duckduckgo (`mcp==1.30.0` and its dependencies, the same versions and hashes), tzdata 2026.6 (as servers/time), and, new here: pg8000 1.31.6 (2026-10-26, BSD-3-Clause), scramp 1.5.0 (2026-10-25, MIT-0), asn1crypto 1.5.1 (2022-03-15, MIT), python-dateutil 4.0.0 (2026-11-01, BSD-3-Clause and Apache-2.0) |
| Debian packages | `tini=0.19.0-3+b8` (the image's init, its ENTRYPOINT: no host init needed), `python3=3.13.5-1` (its `sqlite3` module on Debian's libsqlite3), `ca-certificates=20250419+deb13u1` (TLS verify-full to PostgreSQL) |
| Base image | the `debian:trixie-slim` digest in `Dockerfile` |
| Licences | `LICENSES/`: DBHub (MIT), pg8000 (BSD-3-Clause), scramp (MIT-0), asn1crypto (MIT), python-dateutil, tzdata (Apache-2.0 + NOTICE), MCP Python SDK (MIT), sandbox-ai-mcp (MIT) |

## Round 2's reasons, and how they are met

Round 2 (2026-11-18, `docs/round2-reviews.md`) did not admit DBHub 1.5.1: its own code is about 10,700 lines, but stdio
with PostgreSQL and SQLite needs 95 npm packages / about 222,000 lines (the MCP TypeScript SDK v2 split packages,
hono, zod 4, ssh2 with an install script for an optional native binding, express with about 60 packages loaded at
start though only its HTTP mode uses it), which could not be reviewed completely; and its read-only mode is, in its
own README's words, a guardrail, not a permission boundary.

- **The npm package stays out**: 1.6.0 and 1.6.1 (the newest at least 14 days old today) have the same eight
  dependencies (`@iarna/toml`, `@modelcontextprotocol/node` and `/server` v2, `dotenv`, `express`, `ssh-config`,
  `ssh2`, `zod`) and the same optional drivers, so the closure did not shrink.
- **What DBHub is good at is taken over as an own server**: its two-tool design (few tokens, good for local models)
  with the same tool names, arguments and levels of detail, on the reviewed shared lock plus a pure-Python PostgreSQL
  driver (pg8000 and its three small dependencies, about 31,000 lines, audited below) and Python's own sqlite3.
- **Read-only, three layers** (DBHub has the same three; here each is checked by tests, the engine layer against a
  real SQLite file and, for PostgreSQL, against a stand-in of the driver plus a test for a real server that CI or a
  person can run with `SANDBOX_AI_MCP_PG_DSN`): the keyword check, one statement per call, and the engine. A database
  role that can only read remains the boundary (said in the entry's notes, as DBHub says).

## The review of DBHub 1.6.1 (2026-11-25)

Read in full (the logic ported): `src/tools/execute-sql.ts` (one statement or several, the access policy, the
engine backstop flag, results as `statements`, an in-process request log for its web UI - `trackToolRequest` writes
to an in-memory store, nothing is sent), `src/tools/search-objects.ts` (748 lines: object types schema, table, view,
column, procedure, function, index; LIKE patterns turned into regular expressions; detail levels names, summary,
full; row counts from statistics or `COUNT(*)`; a limit of 1-1000, default 100), `src/utils/allowed-keywords.ts` (the
reading keywords per dialect - PostgreSQL select/with/explain/show, SQLite select/with/explain/pragma -, the writing
keywords looked for in CTEs, the escape-hatch functions - PostgreSQL `pg_read_file`, `pg_read_binary_file`,
`pg_ls_dir`, `set_config`), `src/utils/readonly-transaction.ts` (MySQL's session flag), the read-only paths of
`src/connectors/postgres/index.ts` (`default_transaction_read_only` at connect, `BEGIN READ ONLY` per execution,
`statement_timeout`) and `src/connectors/sqlite/index.ts`. Grepped (hosts, telemetry, processes): the whole `src`
(18,048 lines outside tests): the only hosts are documentation links (dbhub.ai, GitHub issues) and Azure SQL's
`database.windows.net` (its SQL Server connector); no telemetry or analytics library, no update check. Findings that
the port avoids: PostgreSQL text passed through `node-postgres`'s simple query protocol runs several statements (DBHub
splits and checks them; here the extended protocol runs exactly one); a request log in memory holding every SQL text.

## The libraries (new to this repository)

Grepped for network, processes, code loading, file access, environment and telemetry; every hit read:

- **pg8000 1.31.6** (4,400 lines): one TCP (or Unix) socket to the configured host; TLS through Python's `ssl` -
  its default (`ssl_context=None`) tries TLS **without any certificate check and falls back to plain text**; this
  server never uses that default: `verify-full` (certificate and host name against the system CAs or `sslrootcert`),
  `require` (TLS, unchecked) or `disable` (`False`). `native.Connection.run()` without parameters uses the simple
  query protocol (several statements possible): this server sends user SQL through `execute_unnamed` (the extended
  protocol, one statement, the text unchanged - no `:name` placeholder parsing). Notifications and notices are kept
  in deques of 100. No COPY stream is passed, so a COPY cannot move data. Passwords: SCRAM through scramp, MD5, or
  clear text when the server asks for it (only over TLS with the default verify-full).
- **scramp 1.5.0** (1,375 lines): SCRAM-SHA-256(-PLUS) with `hashlib`/`hmac`; channel binding reads the TLS
  socket's certificate (through asn1crypto). Nothing else.
- **asn1crypto 1.5.1** (16,658 lines): ASN.1 parsing for the channel binding's certificate; no I/O.
- **python-dateutil 4.0.0** (8,568 lines): pg8000 parses some date/time texts with it; time zones from `tzdata`
  through `importlib.resources`; no I/O beyond that.

## Our code (`src/server.py`)

- `DBHUB_DSN`: `postgres://`/`postgresql://` with user, host, port, database (a password in it is refused: it goes into the secret `DBHUB_PASSWORD`, so the DSN can be shown),
  `sslmode` (verify-full default, require, disable) and `sslrootcert` only - any other parameter refused; or
  `sqlite:///work/...` (no `..`, a regular file, no link). No message ever contains the password (tested).
- PostgreSQL: `application_name` sandbox-ai-mcp-dbhub, `statement_timeout` 30 s, `idle_in_transaction_session_timeout`
  60 s, `default_transaction_read_only` on (read-only mode) as startup parameters; each call in `START TRANSACTION
  READ ONLY` ... `ROLLBACK` (DBHUB_WRITE=1: `START TRANSACTION` ... `COMMIT` for `execute_sql`; the catalog queries
  of `search_objects` always read-only); a reading `SELECT`/`WITH`/`VALUES`/`TABLE` is wrapped as `SELECT * FROM
  (...) LIMIT max_rows + 1` so only that many rows leave the server (pg8000 holds a whole result in memory); catalog
  queries with bound parameters; a broken connection is closed and opened again at the next call.
- SQLite: `file:...?mode=ro` (rw with DBHUB_WRITE=1), `hard_heap_limit` 256 MiB, `trusted_schema` off, `query_only`
  on, an authorizer that refuses ATTACH/DETACH, `load_extension` and the shell's file functions always, every
  pragma with a value except the reading ones (table_info, index_list, ...), and in the read-only mode every write
  action; a progress handler stops a statement after 30 s.
- The keyword check (before any connection is used): the first word a reading one; none of insert, update,
  delete, drop, alter, create, truncate, merge, grant, revoke, rename, into, upsert anywhere outside comments,
  strings, dollar-quoted strings and quoted identifiers; none of 46 escape-hatch functions in call position
  (`pg_read_file`, `set_config`, `dblink*`, `lo_*`, `pg_terminate_backend`, `nextval`, `query_to_xml`, `pg_sleep`,
  `load_extension`, ...); no `;` between statements.
- Answers: JSON with `columns`, `rows`, `rowCount` (at most `max_rows`, 1-1000, default 200, and 24,000 characters,
  with `truncated` and a warning), values cut at 2,000 characters; errors as one line (PostgreSQL's message, code and
  detail; never the DSN).
- Tools only (no resources or prompts advertised); `search_objects` annotated read-only.

## Tests

`tests/test_dbhub.py` (18 tests, one more with `SANDBOX_AI_MCP_PG_DSN`: the DSN and its refusals without the
password; the TLS modes; the classifier on 17 reading and 23 refused statements; SQLite on the pinned `shop.sqlite`:
reads, the three read-only layers - the engine refusing six writes even past the classifier -, DBHUB_WRITE=1, links
and missing files, the time limit, search_objects and its refusals, bounds; PostgreSQL through a stand-in of
pg8000's connection: the startup parameters, TLS verify-full, `START TRANSACTION READ ONLY` / the limited statement
through the extended protocol / `ROLLBACK`, EXPLAIN not wrapped, a failure rolled back, writes committed with
DBHUB_WRITE=1, catalog queries read-only with bound parameters), `test_own_servers.py` `test_dbhub` (inside the image
in CI); smoke spec: 5 real calls and 4 refused on `shop.sqlite`. Run on 2026-11-25 in a Python 3.13 venv made from
`requirements.txt` (`--require-hashes`): 18 passed, 1 skipped (no PostgreSQL here: initdb refuses to run as root in
this sandbox); the smoke spec over stdio 9/9.

## Risks left

- PostgreSQL is not exercised against a real server in this repository's CI yet (`RealPostgres` runs where
  `SANDBOX_AI_MCP_PG_DSN` names one): the stand-in tests pin what is sent, a live run proves the server's answers.
- The keyword layer is a guardrail: a function with side effects that is not on the list (an extension's, a user's
  own `SECURITY DEFINER` function) runs inside the READ ONLY transaction, which stops writes to tables but not
  everything a function can do. Use a role that can only read.
- A SQLite database in WAL mode on a read-only mount may not open read-only (SQLite wants its `-shm` file); copy it
  or checkpoint it first.
- With DBHUB_WRITE=1 every statement is committed: have sandbox-ai ask before `execute_sql` then.
