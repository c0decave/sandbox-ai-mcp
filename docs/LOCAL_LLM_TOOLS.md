# MCP tools for local LLMs

State: 2026-11-13 (cut-off for third-party pins: published on or before 2026-10-30).

Small models served by LM Studio, Ollama or vLLM and driven by OpenCode, Codex, Hermes, Qwen Code or DSH fail in a
few typical ways: a command that waits for an answer (`npm init`, `apt install`, `git commit` without `-m`) or never
ends (`npm run dev`, `jest --watch`) stalls the agent until its client gives up; a build or test log of thousands
of lines fills a 32k context; the one failing test is buried in pages of passing ones; after a context compaction or
a restart the goal and what was already found out are gone, and the same failing approach is tried again. Two
servers of our own address this, and this page reviews what exists already.

## Built here

| Server | What it gives a small model | Mounts | Network |
|---|---|---|---|
| [exec](../servers/exec) | `run_command` (bash with a time limit, stdin empty, no terminal, CI=1 and pagers/editors/prompts off, the whole process tree stopped on the limit, output cut to its start and end with the lines omitted counted), `start_job`/`job_status`/`stop_job`/`list_jobs` for long builds and servers, `run_tests` (only the failures of pytest, unittest, jest, vitest, go test, cargo test), `lint` (pyflakes, shellcheck, JSON, YAML; runs nothing of the project) | `/work` rw (the project) | none |
| [tasks](../servers/tasks) | a plan outside the context in `/work/.tasks`: `set_goal`, `add_steps`, `start_step`/`complete_step`/`block_step` with a note, `add_note` (facts, mistakes not to repeat), `next_step` (the one step to do now with what it needs), `list_steps`, `progress`, `remove_step`; `PLAN.md` beside it for the human | `/work` rw (the project) | none |

Both are our own code on the shared lock (MCP SDK 1.30.0), standard library otherwise, reviewed in full
(`PROVENANCE.md` of each), with offline tests (`tests/test_exec.py`, `tests/test_tasks.py`) that CI also runs inside
the images. Design rules for small models, applied to both: few tools with short descriptions and an example each;
plain-text answers (no structured duplicate) whose first line says what happened (`exit 1 (failed) · 2.3 s`,
`Step 3 done.`); every refusal says what to do instead; answers bounded (100 lines of output by default); the
servers' instructions say when to call what (`next_step` at the start and when unsure; `start_job` for servers).

**exec does not widen what the agent can do.** The agent has a shell of its own already, with more tools than
exec's container. exec runs its commands in that container: no network namespace, no capabilities, a read-only
root, a `noexec` /tmp, process and memory limits (2g, 512 processes, a 512m /tmp), and only the agent's own
workspace mounted at `/work`. It is a different shell for models that lose themselves in the raw one, not a new
permission. Its limits: only the image's tools (bash, coreutils, git, make, python3 with pytest, pyflakes and PyYAML,
shellcheck, Debian's Node.js 20 without npm); nothing can be installed from it (no network: install from the
agent's own shell, then run and test with exec).

```bash
sandbox-ai mcp add exec --mount /work=~/projects/app:rw     # the agent's workspace folder itself, not one inside it
sandbox-ai mcp add tasks --mount /work=~/projects/app:rw
sandbox-ai opencode --workspace ~/projects/app --mcp exec --mcp tasks
sandbox-ai codex --workspace ~/other --mcp exec --mcp-mount exec:/work=~/other:rw --mcp tasks --mcp-mount tasks:/work=~/other:rw
```

**Client time limits.** An MCP client waits a limited time for a call: Codex 60 s by default (`tool_timeout_sec`
per server), others longer. A command that outlasts the client's limit still runs to its own limit, but its answer
is lost. For Codex give exec `tool_timeout_sec` of `EXEC_MAX_TIMEOUT` plus a margin (sandbox-ai sets a long one only
for its helpers so far: a follow-up there), or set `EXEC_TIMEOUT=50` and `EXEC_MAX_TIMEOUT=55`; long work belongs in
`start_job` anyway, whose `job_status` waits at most `wait_seconds`.

## Existing servers, reviewed

Rule as everywhere here: we publish only what we reviewed completely, pinned to a release at least 14 days old,
running on its own in a container.

### `mcp-server-git` (modelcontextprotocol/servers `src/git`) - not packaged; exec covers it

| | |
|---|---|
| Release | PyPI `mcp-server-git` **2026.10.28** (2026-10-28) is the newest old enough; 2026.11.4 and 2026.11.11 are too new until 2026-11-18 and 2026-11-25 |
| Licence | MIT (the package); the repository is moving to Apache-2.0 |
| Code path | `server.py` 846 lines + 33 (wheel of 18 KB, read); on GitPython 3.2.1 (BSD-3-Clause, 20,704 lines of Python), gitdb 4.0.12, smmap 5.0.3, click, pydantic and **mcp 2.x** (`mcp<3,>=2.3`: not our 1.30 lock; osint-mcp's lock has mcp 2.3.0) |
| Tools | 12: `git_status`, `git_diff_unstaged`, `git_diff_staged`, `git_diff`, `git_commit`, `git_add`, `git_reset`, `git_log`, `git_create_branch`, `git_checkout`, `git_show`, `git_branch`; confined to `--repository` |
| Network | none: no push, pull, fetch or clone tool |
| Telemetry | none |

**Findings.** GitPython runs the `git` binary for every call, so the image needs git anyway; `git_commit` and
`git_checkout` run the repository's hooks (the project's code, as exec's `run_command` would); `git_diff` and
`git_show` return the whole diff, unbounded - a large diff fills a small context; GitPython has had option-injection
CVEs (CVE-2022-24439, CVE-2023-40267), which the server's fixed argument lists avoid. **Recommendation: do not
package.** It is of little use beside exec, which runs `git` with the pager, editor and credential prompts off and
the output bounded; its structured tools would help a small model only with bounded diffs. If wanted later, three
bounded tools (`git_status`, `git_diff` with a line limit, `git_log`) fit into exec as our own code in an hour,
without a second SDK lock and 20,000 lines of GitPython.

### `sequential-thinking` (modelcontextprotocol/servers `src/sequentialthinking`) - not packaged now; 2.1.1 from 2026-11-18 if wanted

| | |
|---|---|
| Release | npm `@modelcontextprotocol/server-sequential-thinking` **2.0.0** (2026-10-19, npm provenance) is the newest old enough; 2.1.1 (2026-11-04) is too new until 2026-11-18 |
| Licence | "SEE LICENSE IN LICENSE": the repository's Apache-2.0, older contributions MIT (as the memory server) |
| Code path | 342 lines read in full (`dist/index.js` 205, `dist/lib.js` 107, `dist/version.js` 30); runtime: `@modelcontextprotocol/server` (^2.3.1: 2.4.0 as in servers/memory, whose review covers the SDK's stdio path and zod), zod, chalk ^5.3.0 (5.6.2 - never 5.6.1, the release of 2025-09-08 that npm pulled as compromised); `yargs` ^17.7.2 is declared but imported nowhere in 2.0.0 (2.1.1 drops it) |
| Tools | 1: `sequentialthinking` (9 parameters: the thought, its number, the estimated total, whether another is needed, revision and branch fields) |
| Network, telemetry | none; every thought is logged to stderr unless `DISABLE_THOUGHT_LOGGING=true` |

**Findings.** Clean and tiny: the history lives in memory per connection (null-prototype branches, no prototype
pollution), nothing is read or written. **But it does little for a small model:** it stores nothing beyond the
connection and returns only counters, so it does not survive a compaction or a restart - the failure it would be
wanted for; a small model has to manage `thoughtNumber`, `totalThoughts` and `nextThoughtNeeded` itself, gets them
wrong or keeps thinking without acting (the tool's own text asks it to "repeat the process until satisfied"); models
with native reasoning gain nothing. tasks keeps what matters (goal, steps, findings, mistakes) on disk and always
answers with what to do next. **Recommendation: not now.** If users ask for it, package **2.1.1 from 2026-11-18**
as-is (no yargs), with servers/memory's Dockerfile pattern (npm ci of a lock with the same SDK 2.4.0 and zod
4.6.7, `node --disallow-code-generation-from-strings`, the SDK review reused): about an hour, reviewing the
then-current 2.1.1 sources line by line.

### serena (oraios/serena) - not packaged

| | |
|---|---|
| Release | 2.1.0 (2026-10-19; PyPI `serena-agent`), old enough |
| Licence | GPL-3.0-or-later (its SolidLSP part MIT) |
| Code path | 70,885 lines in 183 files of its own (the wheel), 57 pinned requirements, among them anthropic, agno, flask, pywebview, pystray, pythonnet, tiktoken, sqlalchemy, requests; language servers downloaded at run time (npm, GitHub releases, Microsoft) |
| Tools | symbol search, references, symbol-level edits, file tools, a shell command tool, memories, onboarding |
| Network | downloads language servers on first use; `tiktoken` fetches its encodings |
| Telemetry | **on by default**: at every start it sends OS, version, backend, context and dashboard state to `oraios-software.de/serena_usage.php` (off with `SERENA_USAGE_REPORTING=false` or `CI=true`); its web dashboard (Flask, on by default) checks PyPI for a newer version and may open a browser |

**Recommendation: do not package** (as recorded in docs/CANDIDATES.md): far too large to review completely, it
reaches out by default, needs the project's toolchains and language servers where the project is (a kit on the
agent's side, not a container server), and its editing and shell tools overlap the agent's own. Its idea - symbols
instead of text - is the right one for small models; see the own code search below.

### ast-grep MCP (ast-grep/ast-grep-mcp) - write our own small one

| | |
|---|---|
| Release | none (no tags): commit `1e41164726d7` of 2026-10-28 is the newest old enough; it needs the `ast-grep` CLI, **0.51.0** (2026-10-15; 0.51.1 and 0.51.2 too new), Rust, MIT, release binaries and PyPI wheels with published hashes |
| Licence | MIT (both) |
| Code path | `main.py`, 444 lines (read); mcp 2.2.0 (not our lock), pydantic, pyyaml; plus the ast-grep binary (a large Rust code base with tree-sitter grammars: reviewable on its risky surfaces only) |
| Tools | 4: `dump_syntax_tree`, `test_match_code_rule`, `find_code`, `find_code_by_rule` |
| Network, telemetry | none |

**Findings.** `project_folder` is any absolute path (no confinement but the container's mounts); `max_results`
defaults to 0, all matches - a broad pattern floods a small context; the `ast-grep` process has no time limit;
patterns and YAML rules are hard for small models to write. **Recommendation: write our own small `code-search`
server** in exec's style: the pinned `ast-grep` 0.51.0 binary by SHA-256 for structural search plus a plain text
search (the standard library or Debian's ripgrep), `/work` only, bounded results (file:line and a line of context,
the count of the rest), time limits, and a file outline (functions and classes of a file) - three tools a small model
can use without learning a pattern language.

### codebase-memory (`candidates/codebase-memory`) - keep as a candidate, not for small models

codebase-memory-mcp **0.12.1** (2026-10-16, old enough), MIT, a static C binary (330 MB with 162 tree-sitter
grammars and an embedded web UI, switched off with `--ui=false`), no network of its own and no telemetry (its README;
see `candidates/codebase-memory/PROVENANCE.md` for the audit notes); its index needs `/out` writable and about 2g
memory. **For small models it is the wrong shape:** 17 tools with graph queries (`query_graph` takes Cypher-like
queries), large answers, an indexing step to run first. It stays a candidate for capable models; it is not built
yet (the image and its smoke test are open), and its code base is too large for a complete line-by-line review -
it would be packaged on a review of its risky surfaces, as the binary analysis tools are. For small models the own
`code-search` above is the better fit.

## Next

1. `code-search` (own, above): text and structural search and file outlines, bounded, `/work` read-only.
2. sandbox-ai: a long `tool_timeout_sec` for exec under Codex (as for its helpers), and presets that add exec and
   tasks for local-model agents.
3. sequential-thinking 2.1.1 from 2026-11-18, only if users ask for it.
