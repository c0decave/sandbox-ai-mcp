# tasks - provenance and audit

| | |
|---|---|
| MCP server | this repository, `src/server.py` (MIT, `LICENSES/`), written for this repository and reviewed in full (below) |
| Python packages | `mcp==1.30.0` and its dependencies, hash-locked in `requirements.txt` (byte-identical to web-fetch's but for the `# via` line); the server imports nothing else but the standard library |
| Debian packages | `python3=3.13.5-1`, `python3-venv=3.13.5-1` (purged after the venv is made), `ca-certificates=20250419+deb13u1` |
| Base image | the `debian:trixie-slim` digest in `Dockerfile` (the same as web-fetch's) |

**Pinning rule:** no new third-party release: the lock, the Debian versions and the base digest are web-fetch's.

## Why an own server

A small local model forgets: after a context compaction or a restart of the agent its goal, its plan and what it
already found out are gone, and it tries the same failing thing again. tasks keeps them outside the model's
context, in the project folder, in a form a small model can follow: one goal, short steps with a state, a note per
change, and `next_step`, which answers "what now?" with the one step to work on and only the context it needs.
The human sees the same plan as `PROJECT/.tasks/PLAN.md`.

Why not the memory servers (`memory`, `engram`): they keep knowledge (entities, observations, searchable), not an
ordered plan with states; a model has to know what to search for. tasks is small, has no query language, and its
answers always end with what to do next.

## Tools

| Tool | What | Writes |
|---|---|---|
| `set_goal` | the goal (at most 2,000 characters); `clear_steps` removes the old steps; a changed goal leaves a note | yes |
| `add_steps` | steps (a list, or one text with a step per line: leading numbers, bullets and `[ ]` dropped), at most 50 per call, 500 characters each, 200 in all; `after_step` inserts (0: at the start) | yes |
| `remove_step` | removes a step | yes |
| `start_step` | in progress (also reopens a done or blocked one), optional note | yes |
| `complete_step` | done, with a note of what was done; answers with the next step | yes |
| `block_step` | blocked, with the reason (required); answers with the next step | yes |
| `add_note` | a note to the plan (facts, mistakes not to repeat; the newest 100 kept) or to a step (the newest 10 kept), at most 1,000 characters | yes |
| `next_step` | the goal, the progress, the step in progress (else the first to do) with its notes and what to call, the last done step and its note, the next three, the blocked ones, the latest 5 notes; when only blocked steps are left, those and their reasons; when all are done, to check the goal | no |
| `list_steps` | the goal and every step with its state (`[ ]`, `[>]`, `[x]`, `[!]`) and its last note, compact | no |
| `progress` | the goal, then the steps grouped as done, in progress, blocked, to do | no |

Step numbers are given once and never reused: a step inserted later keeps its number, so a model that still has an
old list never completes the wrong step. The server's instructions tell the model to call `next_step` at the start
and whenever it is unsure.

## Audit of the server (`src/server.py`, read in full)

**Files.** Only `/work/.tasks/` (the project folder mounted writable at `/work`): `plan.json` (the plan), `PLAN.md`
(written from it after every change, marked as overwritten) and `.lock`. No tool takes a path. The folder is opened
with `O_DIRECTORY | O_NOFOLLOW` relative to a descriptor of `/work`, and every file in it with `O_NOFOLLOW` through
that folder's descriptor: a `.tasks` or `plan.json` that is a symbolic link (or a file in place of the folder) is
refused with what to do, never followed. Reading creates nothing.

**Concurrency.** Every change holds an exclusive `flock` on `.lock` for read-change-write; reads hold a shared one.
A write goes to a new temporary file (`O_CREAT | O_EXCL | O_NOFOLLOW`, a random name), is synced, renamed over the
old file (`os.replace` in the same folder: atomic), and the folder is synced. Several connections (several
containers on one host folder) and several threads can change one plan; none of their changes is lost (tested with
six processes and four threads at once).

**Reading what is stored.** The agent can write `.tasks` with its own tools, and a human may edit `plan.json`: every
field is checked on reading (version, types, unique step numbers, known states) and bounded (texts cut, notes
capped); a file over 4 MiB or one that is not a regular file is refused. A plan that cannot be read is never
overwritten: the error says to fix it or move it away. Texts are stored as given, control characters removed; they
come back to the model as data.

**Bounds.** Goal 2,000, step 500, note 1,000 characters; 50 steps per call, 200 in all; 10 notes per step and 100
of the plan (the oldest dropped, counted in `PLAN.md`); answers show notes shortened to 120-400 characters. So the
file stays below about 2.5 MB and every answer small.

**Network:** none; the server sends nothing anywhere.

## Self-review: what was found and changed

- The folder's error handling first mixed a permission error, a read-only mount and a link in one branch, so a
  read-only `/work` could be reported as "not a folder": now creating the folder reports the mount, opening it the
  link or file in the way.
- `block_step` without a reason would have stored a blocked step nobody can unblock sensibly: the reason is
  required.

**Remaining risks** (accepted): the agent (or anyone who can write the project) can change the plan behind the
server's back - the server checks what it reads, and the plan is the agent's own; notes written from something the
model read come back as text in later answers (data, not instructions).

## Tested

- `tests/test_tasks.py`, offline, 12 tests: no plan yet (nothing written by reading); a plan from goal to done
  (`next_step` and `complete_step` answers, notes kept in mind, only blocked steps left, all done); the plan read by
  a new process and `PLAN.md`; insertion, removal and numbers never reused; a new goal keeping or clearing steps;
  every bound; plans changed by hand refused and kept; a `.tasks` link, file, and a linked `plan.json` refused; a
  workspace that cannot be written; one that is not mounted; six processes and four threads changing one plan; over
  stdio: the tools as `tools.json` records them (read-only hints matching), a session, refusals as errors. Run here
  with the lock's mcp 1.30.0 on Python 3.11 (all pass).
- `tests/test_own_servers.py` `test_tasks`: tools and the refusal without `/work`, then the whole offline suite - in
  CI inside the image, with no test skipped.
- `smoke.json`: no plan yet, a goal, three steps, start, a note, complete (the next step returned), next step (the
  note shown), progress, the list; refused: an unknown step, an empty goal, `read_file` (no such tool). Run here
  natively against a temporary folder (all pass); not built here (no container engine).

## Verdict

Our own code, reviewed in full; no third-party code beyond the shared lock. Ready for CI; sign once both smoke
reports pass.
