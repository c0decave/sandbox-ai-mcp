# exec - provenance and audit

| | |
|---|---|
| MCP server | this repository, `src/server.py` (MIT, `LICENSES/`), written for this repository and reviewed in full (below) |
| Python packages | `mcp==1.30.0` and its dependencies, hash-locked in `requirements.txt` (byte-identical to web-fetch's but for the `# via` line); the server imports nothing else but the standard library |
| Debian packages | `python3=3.13.5-1`, `python3-venv=3.13.5-1` (purged after the venv is made), `ca-certificates=20250419+deb13u1`; for the commands: `git=1:2.47.3-0+deb13u1`, `make=4.4.1-2`, `procps=2:4.0.4-9`, `python3-pytest=8.3.5-2`, `python3-pyflakes=3.2.0-3`, `python3-yaml=6.0.2-1+b2`, `shellcheck=0.10.0-1`, `nodejs=20.19.2+dfsg-1+deb13u3` (trixie and trixie-security indexes of 2026-11-13) |
| Base image | the `debian:trixie-slim` digest in `Dockerfile` (the same as web-fetch's) |

**Pinning rule:** no new third-party release: the Python set is the lock the published web-fetch and youtube images
use; the Debian packages come from the pinned trixie archive (exempt from the 14-day rule, `docs/CANDIDATES.md`).

## Why an own server

Agents on small local models (LM Studio, Ollama or vLLM behind OpenCode, Codex, Hermes, Qwen Code, DSH) stall, die
or loop in a raw shell: `npm init` waits for an answer forever, `npm run dev` never ends, `git log` opens a pager, a
build prints 50,000 lines into a 32k context, a test run's one failure is buried in pages of passes, a `cd` in one
call is assumed in the next. exec gives such a model a shell that cannot do these things to it: every command has a
time limit and is stopped with everything it started, nothing can wait for input, output is cut to its start and
its end with the number of lines left out, long work goes to background jobs, and two helpers return only what a
model needs: the failing tests, and the problems a linter finds.

**It widens nothing.** The agent has a shell of its own already, with more than this one: exec is for models that
lose themselves in it. Its commands run in this server's container, which sandbox-ai starts with no network
(`network: none`, no network namespace at all), no capabilities, no new privileges, a read-only root, a `noexec`
/tmp, process and memory limits, and only the folder mounted at `/work` - the agent's own workspace, which the agent
can change anyway. Nothing of the host, of the agent's sandbox or of another server is reachable from it.

## Tools

| Tool | What | Changes |
|---|---|---|
| `run_command` | one `bash -c` command in `/work` (or `cwd` inside it), `timeout_seconds` (default `EXEC_TIMEOUT`, 120; at most `EXEC_MAX_TIMEOUT`, 600) | yes: whatever the command does in `/work` |
| `start_job` | the same in the background; returns a job number at once (a job that ends within a second answers with its result) | yes |
| `job_status` | running or how it ended, its time, its last `tail_lines` lines (30, at most 300); `wait_seconds` (at most 300) waits for the end first | no |
| `stop_job` | stops a job and every process it started | stops processes |
| `list_jobs` | the jobs of this connection, one line each | no |
| `run_tests` | pytest, unittest, jest, vitest, `go test` or `cargo test` (found from the project's files, or named), optionally only some `tests`; returns counts and, per failure, its name, place and at most 25 lines of its message (at most 15 failures, the others named) | yes: the project's tests are the project's code |
| `lint` | pyflakes (ruff when the image has it; a syntax check when it has neither), shellcheck, JSON and YAML parsing; one line per problem, `file:line:column: [tool] message` | no: reads files only |

`tools.json` records the write tools; with sandbox-ai's rules (`{"server": "exec", "tool": ["run_command",
"start_job", "run_tests", "stop_job"], "decision": "ask"}`) a human can confirm each command, though that defeats
much of the point for an agent working on its own.

The descriptions are short, name an example each, and say what to do instead ("use start_job"); every refusal says
what is wrong and what would work (`cwd: '../etc' is outside /work; give a folder inside it, e.g. '.' or 'src'`).
Answers are plain text (no structured duplicate), so that a small context holds them.

## Audit of the server (`src/server.py`, read in full)

**Processes.** Every command is `Popen([/bin/bash, -c, WRAPPER, /bin/bash, COMMAND])` with `start_new_session=True`
(a session and process group of its own: no controlling terminal), `stdin=DEVNULL`, stdout and stderr into one pipe,
`close_fds=True` (the MCP connection's descriptors are not inherited), `cwd` the checked start folder, and the fixed
environment below. `WRAPPER` raises the command's `oom_score_adj` to 1000 and `exec`s bash with the command: when
memory runs out, the kernel kills the command, not the server. No word of the model is ever put into a command line
of the server's own: `run_tests` and `lint` build argument lists and quote every word (`shell_quote`); test names
starting with `-` are refused, so `tests` cannot smuggle options.

**Stopping.** On the time limit or `stop_job`, `kill` collects the command's processes from `/proc`: its session,
its process group, and every descendant by parent (so also one that called `setsid`), never the server; it sends
SIGTERM to the group and to each, waits up to 2 s, then SIGKILL to what is left. When the shell has ended but a
process it left in the background still holds the output pipe, that process is stopped too after 2 s (and the
answer says so): a `run_command` leaves nothing running. Remaining: a process that double-forks into a new session
before its parent dies is no longer found by session or ancestry; the container (one per connection) ends with the
connection, and `--pids-limit` bounds it.

**Never interactive.** stdin is `/dev/null` (a prompt reads end-of-file), there is no terminal (`setsid`, a pipe),
and the environment is fixed: `CI=1`, `TERM=dumb`, `NO_COLOR=1`, `PAGER`, `GIT_PAGER`, `MANPAGER`=`cat`,
`EDITOR`/`VISUAL`/`GIT_EDITOR`/`GIT_SEQUENCE_EDITOR`=`true` (an editor returns at once; `git commit` without `-m`
aborts), `GIT_TERMINAL_PROMPT=0`, `GIT_ASKPASS`/`SSH_ASKPASS`=`/bin/false`, `GIT_SSH_COMMAND=ssh -o BatchMode=yes`,
`DEBIAN_FRONTEND=noninteractive`, `PIP_NO_INPUT=1`, `npm_config_yes=true` (and npm's fund, audit and update notices
off), `PYTHONUNBUFFERED=1`, `PYTHONDONTWRITEBYTECODE=1`, `HOME`/`TMPDIR`=`/tmp`, a fixed `PATH`, `LANG`/`LC_ALL`=
`C.UTF-8`. When a command still runs into its limit, the answer says why it may have: its last line looks like a
question (`[y/N]`, `password`, a trailing `?` or `:`) - use the program's `--yes`; or it is a server or watcher
(`--watch`, `npm start`, `run dev`, `http.server`, `uvicorn`, ...) - use `start_job`.

**Environment allow-list.** Nothing of the server's own environment reaches a command except the names
`EXEC_ENV_ALLOW` lists (checked to be variable names). The server has no secrets; give it none.

**Output.** One reader thread per command reads the pipe in 64 KiB chunks and keeps the first 64 KiB and the last
256 KiB; every byte and line in between is counted and dropped, so memory stays bounded however much a command
prints (tested with 30 MB on one line). An answer shows `EXEC_OUTPUT_LINES` lines (100: a quarter from the start,
the rest from the end) with `[... N lines omitted ...]` between, each line at most 400 characters, ANSI escapes and
control characters removed, a progress bar's `\r` redraws reduced to the last one, more than three equal lines in a
row as one line and a count, the whole answer at most 16,000 characters (more with a larger `EXEC_OUTPUT_LINES`).
The first line of every answer says how the command ended: `exit 0`, `exit 2 (failed)`, `TIMED OUT after ...`,
`killed by SIGKILL - out of memory?`, `stopped by stop_job`, with its duration.

**Start folders.** `cwd` and `path` are taken relative to `/work` (or absolute below it), normalised, refused when
they leave `/work` lexically, resolved with `realpath` and refused again when a symbolic link leads outside; they
must exist (and be a folder where one is needed); control characters are refused. This keeps a model from getting
lost; it is not the boundary - a command can `cd` anywhere in the container, which holds nothing but the image and
`/work`. Without a folder mounted at `/work` every tool says how to mount one.

**Jobs.** At most `EXEC_MAX_JOBS` (4) jobs run at once, and as many foreground commands; each job has a time limit
too (`EXEC_JOB_TIMEOUT`, 3600 s); 16 ended jobs are remembered. When the connection ends, every job is stopped.

**run_tests.** The framework comes from `package.json` (vitest, jest), `go.mod`, `Cargo.toml`, pytest's
configuration files or `test_*.py`/`*_test.py` (pytest when the image's python3 has it, else unittest). pytest runs
with `-q -p no:cacheprovider --junitxml=/tmp/...` (`junit_family=xunit1`: file and line), its XML is parsed (at most
16 MiB; `xml.etree` on Debian's expat, which refuses entity expansion attacks); unittest's text, jest's and vitest's
`--json` (at most 16 MiB), `go test -json` and cargo's text are parsed the same way. When a report cannot be read,
the command's shortened output is returned instead. jest and vitest only from the project's own
`node_modules/.bin` (resolved inside `/work`); a framework the image lacks (go, cargo) is named with what the image
has.

**lint.** Walks `path` without following links, skipping `.git`, `node_modules`, virtual environments, caches and
build folders, at most 2,000 files (20,000 entries looked at); JSON and YAML files over 2 MiB are left out and named.
Python goes to `python3 -I -m pyflakes` (ruff if the image has it), shell scripts (`.sh`, `.bash`, or a `#!` line of
sh/bash/dash/ksh) to `shellcheck --format=gcc`, JSON and YAML to a checker run by `python3 -I -c` (the standard
library's `json`, PyYAML's `safe_load_all`): `-I` keeps the project's files from being imported in place of a module,
nothing of a file is executed. eslint is never run by `lint`: it loads the project's configuration, which is code;
the answer says how to run the project's own with `run_command`.

**The server's own process.** `harden` makes the server non-dumpable (`prctl(PR_SET_DUMPABLE, 0)`): its commands run
as the same user, but without `CAP_SYS_PTRACE` (sandbox-ai drops every capability) they cannot open
`/proc/<server>/fd/*` - its stdin and stdout are the MCP connection, where a forged message would reach the client -
nor read its memory or environment (tested: `cat /proc/$PPID/environ` is refused, also in the smoke run). A command
can still signal the server (the same user): it ends its own connection, nothing more.

**Network:** none. The server sends no request; the container has no network namespace.

## Self-review: what was found and changed

- Output was first cleaned before the parsers read it: a line cut at 400 characters broke shellcheck's JSON report
  and would have broken `go test -json` lines. Parsers now read the raw kept output; shellcheck uses its one-line
  `gcc` format, so a report larger than what is kept still yields the problems of the kept lines.
- A single line longer than 64 KiB vanished from the answer (cut at both ends of the kept parts); the start of such
  a line is now shown, marked `[... the line goes on]`.
- The watcher hint matched `/dev/null` (`\bdev\b`); it names concrete commands now.
- A newline in `cwd` passed the control-character check (which allowed `\n` and `\t`); any character below 32 is
  refused now.
- `lint` first ran an eslint it found on `PATH`, which loads the project's JavaScript configuration: removed, so that
  `lint` (read-only in `tools.json`) runs nothing of the project.

**Remaining risks** (accepted): a command can read and change everything in `/work` and use the container's
resources up to its limits - that is its purpose; a double-forked daemon in a new session can outlive its command
until the connection ends; the cwd check is a guide, not a boundary; MCP clients have their own time limits (Codex
60 s by default) - a call that outlasts the client's limit keeps running until its own limit, and its answer is
lost: raise the client's limit for this server, or lower `EXEC_TIMEOUT`/`EXEC_MAX_TIMEOUT` below it.

**Limits:** `memory: 2g`, `pids: 512`, `tmp: 512m` in `smoke.json` (written into `rootfs.json` by
`scripts/make_catalog.py`, applied by `sandbox-ai mcp add` 0.1.94): builds and test runs need more than the default
512m, 128 processes and a 64m /tmp.

## Tested

- `tests/test_exec.py`, offline, 43 tests: exit codes, start folders, the start-and-end output with the count
  omitted, 30 MB of output kept bounded in memory, colours, progress bars and repeats removed; stdin empty and no
  terminal (`read`, `input()`, `cat` return at once); the fixed environment and its allow-list; `oom_score_adj`;
  `git commit` without `-m` aborting instead of waiting; the time limit stopping a command with a background child,
  a child in a session of its own and one that ignores SIGTERM; a background process left behind; the hints for a
  prompt and a server; signals named; the limits' settings; `cwd` outside `/work`, through links, a link loop, a
  file, a newline, without a mount; jobs (status, wait, tail, stop with a `setsid` child, the job time limit, the
  number of jobs, ended jobs forgotten, a failing job); recorded reports of pytest (JUnit XML), unittest, jest/vitest,
  `go test -json`, cargo (a failure and a build error); a report of 20 failures cut to 15; framework detection; test
  selection refusing options; frameworks the image lacks; real unittest and pytest runs returning only the failure;
  lint of JSON, YAML, Python and shell (with and without the tools), links and `node_modules` skipped, one file;
  over stdio: the tools as `tools.json` records them (read-only hints matching), answers and refusals as errors, the
  server's `/proc` closed to its commands. Run here with the lock's mcp 1.30.0 on Python 3.11, once with pytest,
  pyflakes, PyYAML and shellcheck 0.10.0 on the commands' `PATH` (all 43 pass) and once without (one skip).
- `tests/test_own_servers.py` `test_exec`: tools and the refusal without `/work`, then the whole offline suite -
  in CI inside the image (its Python, its Debian tools, its user, no network), with no test skipped.
- `smoke.json`: a command, 50,000 lines cut, an empty stdin, a time limit, `/proc` of the server refused, no network
  (`OSError` connecting), a project written, `run_tests` returning `FAILED test_calc.py::test_wrong`, `lint` finding
  shellcheck's SC2086, a job and its status; refused: a start folder outside `/work`, one through a link, an unknown
  job, `read_file` (no such tool). Run here natively against a temporary folder (the calls that need the image's
  tools or no network differ here as expected); not built here (no container engine).

## Verdict

Our own code, reviewed in full; no third-party code beyond the shared lock and Debian's packages. Ready for CI;
sign once both smoke reports pass.
