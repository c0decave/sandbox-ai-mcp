# dbhub - candidate, not admitted (review of 2026-11-18, round 2)

**Review of 2026-11-18 (round 2): not added.** The verdict and its reasons are in `docs/round2-reviews.md`; this
folder keeps what was found, for the next attempt. Nothing here is built.

| | |
|---|---|
| Upstream | bytebase/dbhub (MIT), npm `@bytebase/dbhub` |
| Release looked at | **1.5.1**, published 2026-11-03 07:01 UTC (15 days before the review; 1.6.0 to 2.0.0 are newer than 14 days), tarball SHA-256 `9c83be5157c53a0ae38439cb3fed75a297fa6afb6341d973adb7ab44714b0d58`, integrity `sha512-23pUeOwKaJrg8fJg3U6O+rc+Iwc7kiDOwRT1XUhF/CEp4KtYMxNcA+4I1mp5TiH25G0jHsK2Xmm/rnktsmlJNg==`, 37 files |
| Runtime | Node.js >= 22.5 (SQLite through the built-in `node:sqlite`) |

## Why not admitted

The catalog's rule is a complete review of everything that runs. dbhub's own code is reviewable (`dist/`: 10,712
lines of unminified JavaScript in 18 modules, plus an 822 kB minified web UI that only the HTTP transport serves), but
the closure it needs for stdio with PostgreSQL and SQLite alone is **95 npm packages with about 222,000 lines of
JavaScript** (`npm install --ignore-scripts --omit=optional --before=2026-11-04 @bytebase/dbhub@1.5.1 pg@8`), most
of it new to this repository:

| Package | Version | Lines | Note |
|---|---|---|---|
| zod | 4.6.7 | 55,631 | (zod 3/4 is in other images here; this version is not reviewed) |
| @modelcontextprotocol/server, core, node | 2.4.0, 2.4.0, 2.1.2 | 53,528 | the MCP TypeScript SDK **v2** split packages: new here (the images here use the 1.x SDK) |
| ssh2 | 1.17.0 | 26,027 | imported at start for SSH tunnels; **has an install script** (`node install.js`, builds an optional native binding) |
| hono, @hono/node-server | 4.13.16, 2.1.6 | 28,103 | the SDK v2's HTTP layer |
| express (+ about 60 small packages) | 4.22.3 | ~25,000 | imported at start although only the HTTP transport uses it |
| pg and its 9 packages | 8.23.1 | ~8,500 | |

MySQL, MariaDB, SQL Server and Oracle add their drivers (mssql brings tedious and the Azure SDK; oracledb native
code), the AWS RDS signer and Azure identity are optional dynamic imports. A complete review of this closure is several
days of work, not a round.

## First look at dbhub's own code (not a complete review)

- Tools (stdio, default): `execute_sql`, `search_objects` (and opt-in `explain_sql`); a TOML file can add custom tools.
  Small schemas: good for local models.
- Read-only (`readonly = true` per tool in the TOML): a first-keyword allowlist per dialect (`select`, `with`,
  `explain`, `show`, ...; `src/utils/allowed-keywords.ts`), a mutating-keyword scan after stripping comments and
  strings, `SELECT ... INTO` refused, per-dialect "escape hatch" functions refused (PostgreSQL `pg_read_file`,
  `pg_ls_dir`, `set_config`; MySQL `load_file`; SQL Server `OPENROWSET`; Oracle `UTL_HTTP`, ...), and the database's
  own read-only mode where it has one (PostgreSQL `default_transaction_read_only=on` and `BEGIN READ ONLY`, SQLite
  `PRAGMA query_only`, Oracle `SET TRANSACTION READ ONLY`). Upstream calls it "a guardrail, not a permission
  boundary"; a read-only database user stays the real boundary.
- `--demo` loads a bundled employee SQLite database; `dotenv` reads `.env` from the working directory.
- No telemetry library found; the HTTP transport has optional bearer tokens and an allowed-hosts list.

## What would admit it

An image with stdio only and PostgreSQL + SQLite only would still need the SDK v2, zod 4, ssh2 and express reviewed.
Cheaper: an own read-only SQL server on the shared Python lock (SQLite through the standard library opened read-only
with `PRAGMA query_only`, PostgreSQL through a pure-Python driver in a `READ ONLY` transaction), taking dbhub's two-tool
design (`execute_sql`, `search_objects`) - see the report's "Next".
