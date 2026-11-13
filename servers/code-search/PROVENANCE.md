# code-search - provenance and audit

| | |
|---|---|
| MCP server | this repository, `src/server.py` (MIT, `LICENSES/`), written for this repository and reviewed in full (below) |
| Python packages | `mcp==1.30.0` and its dependencies, hash-locked in `requirements.txt` (byte-identical to web-fetch's but for the `# via` line; the set web-fetch, files, exec and tasks run). The server itself uses the standard library and the SDK only |
| Debian packages | `python3=3.13.5-1`, `python3-venv=3.13.5-1` (purged after the venv is made), `ca-certificates=20250419+deb13u1` (for pip's download during the build) |
| Base image | the `debian:trixie-slim` digest in `Dockerfile` (the same as web-fetch's) |
| Helper binaries | none: no ripgrep, no ast-grep, no language server (why: below) |

**Pinning rule:** no new third-party release comes in: the Python set is the lock the published images already use,
the Debian versions and the base digest are theirs.

## Why an own server

[docs/LOCAL_LLM_TOOLS.md](../../docs/LOCAL_LLM_TOOLS.md) reviewed what exists: serena (GPL, 70,885 lines, usage
reporting on by default, language servers downloaded at run time), the ast-grep MCP server (no confinement but the
container's, `max_results` 0 = all, no time limit on its binary, a pattern language small models get wrong) and
codebase-memory (17 tools with graph queries, an indexing step first). Small local models fail in three ways when
they look for code: they do not find it (they grep for a guessed name), they read whole files into a 32k context,
and they guess names that do not exist. code-search answers those three directly: `find_definition` by name with
similar names when there is no such name, `read_symbol` for one function instead of the file, `outline` and
`project_map` for what a file and the project hold, with every answer short.

**No helper binary.** ripgrep (Debian's 14.1.1) would search faster, but it would be a second walker with its own
link and ignore rules beside the descriptor walk below, its output would have to be parsed back, and it would not
give the outlines anyway; a pure-Python search of a project of 1,000-2,000 files takes 0.05-0.5 s here (below),
well inside the time limits. ast-grep's structural patterns are what small models cannot write. Both stay out: one
code path, one confinement, all of it reviewed here.

## Tools

Seven, each with a short description, an example per argument and plain-text answers (no structured duplicate)
whose first line says what was found:

| Tool | What |
|---|---|
| `project_map` | a tree of the project (or a folder, `depth` 1-6, default 2): folders with their file counts, files with size and their top-level classes and functions; at most 200 lines, 25 files per folder |
| `find_definition` | where a name is defined (function, method, class, struct, interface, trait, enum, type, constant, macro, module), `kind` to narrow, `App.run` / `App::run` for a method; ranked: exact case first, then by kind (types and functions before constants), files outside tests first, shallow paths first; at most 20; none found: up to 8 similar names (containing it, then close spellings) with their place |
| `read_symbol` | the source of one function, method or class with line numbers, from the comment, decorators or annotations above it to its end; at most 250 lines (a longer one names its parts to read one by one); an ambiguous name shows the first and names the others; an unknown one is refused with the file's symbols and similar names |
| `outline` | the symbols of one file with lines, nesting and signature (one line each); constants and macros of the top level on one line by name; at most 300 |
| `find_references` | definitions first, then lines using the name as a whole word - in code files (with the function each is in), in other files (docs, configs), then in another case; at most 50, the rest counted per file with "narrow it with path" |
| `find_text` | plain text or a Python regular expression, line by line, `ignore_case`, `glob` (`*.py`, `src/**/*.ts`, `*.{ts,tsx}`, several with commas); file, line, the function the line is in and the line (cut around the match to 160 characters); `max_results` (default 30, at most 200) and `offset` to go on; counts up to 1,000 matches ("N more: offset=... shows the next ones") |
| `find_files` | by part of a name (case-insensitive) or a glob; ranked exact name, other case, name without suffix, prefix, part; files before folders, shallow first; at most 50 with sizes; none: similar names |

## Audit of the server (`src/server.py`, 2,164 lines, read in full)

**Folders.** `/work` (required) and `/ref1`-`/ref3` (optional), all mounted read-only by the user and never written:
the server has no code that writes, creates, renames or deletes (no `open()`, no `os.write`, no `O_WRONLY`, `O_RDWR`
or `O_CREAT`, no `shutil`; `tests/test_analysis_servers.py` checks the source for each of these). A path is relative
to `/work` or absolute under one of the folders (empty, `.` and `/` are `/work`); `..`, `~`, a backslash, control
characters, a name over 255 bytes and a path over 4,096 characters are refused before anything is opened.

**Walking a path (`locate`, files' approach).** From an open descriptor of the folder, one name at a time:
`fstatat` without following, then `openat(O_DIRECTORY | O_NOFOLLOW)` of the next folder by its name in the one
before, so a folder swapped for a link meanwhile fails to open. A link named in a path is followed only while it
stays inside its folder: an absolute target must lie below the folder (as the container or the tests see it), a
relative target is walked name by name with `..` going up the folders actually walked and refused at the top; at
most 16 links per path (a loop ends). The answer shows the real path, not the link's.

**Walking a tree (`walk`).** `os.scandir` on the descriptor, names sorted (answers are stable), no link followed at
all (a link is neither a file nor a folder for the walk), only regular files yielded (no device, pipe or socket),
each folder opened by `openat(O_DIRECTORY | O_NOFOLLOW)`. Not entered: `.git`, `.hg`, `.svn`, `node_modules`,
`vendor`, `bower_components`, `__pycache__`, `.venv`, `venv`, `.tox`, `.nox`, the tool caches, `build`, `dist`,
`target`, `coverage`, `htmlcov`, `*.egg-info` (the answer names those it passed: "name one in path to search it" -
a path naming one is searched), and what `.gitignore` files leave out: the root's and those of every folder above
the start and on the way (last match wins, `!` re-includes, `/` anchors, a trailing `/` means folders only, `**`
any folders, `\` escapes; `.git/info/exclude` and the global excludes file are not read). Skipped as generated:
`*.min.js`, `*.min.css`, `*.map`. Bounds: 200,000 entries listed per walk, 50,000 per folder, 64 folders deep, 500
ignore rules at once (64 KiB per `.gitignore`).

**Reading a file (`load_text`).** `openat(O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_NOCTTY)` in its folder's
descriptor, then `fstat` of the open descriptor: not a regular file - refused (a pipe swapped in never blocks the
open); over 2 MiB - not read (said so: "not read: N larger than 2 MiB"); a NUL byte in the first 8 KiB - binary,
not read. UTF-8 with replacement characters, a byte order mark dropped, CRLF read as LF.

**Matching globs and .gitignore without backtracking (`Glob`).** A glob is split into its names; each name is
matched by `fnmatch.translate`'s regular expression, which uses atomic groups since Python 3.9 (no catastrophic
backtracking on `*a*a*a*...b`), and `**` by a table over the names (names times parts). A hostile `.gitignore` or
glob therefore costs microseconds per name (tested with 14 stars against a 200-character name, and 40 `**/`).

**Regular expressions (`find_text`).** A pattern of at most 500 characters on one line; one that repeats a group
which itself repeats (`(a+)+`, `(\w+\s?)*`, `(?:a*)*`, `(x{1,3})+`) is refused with what to write instead (the
check itself is a bounded regular expression on the pattern, linear in practice: 2 ms on 500 characters); a
pattern that does not compile is refused with the error. What remains (alternations like `(a|aa)*c`) is stopped by
the timer: the search runs under a `SIGALRM` timer (`setitimer`, 10 s), whose handler raises an exception that also
interrupts the regular expression engine; the answer keeps what was found and says the search stopped. The tool
runs on the event loop's thread (FastMCP calls a synchronous tool directly), the main thread, where the timer
works; outside the main thread the walks check the clock themselves. Each line is matched in its first 10,000
characters. Plain text is first searched in the whole file in one call (a quick no); a regular expression only line
by line - the engine looks for the signal only now and then (independent review, R10).

**Outlines (`parse_outline`).** Python: `ast.parse` (exact; warnings silenced), classes, functions, methods and
nested functions with their real end lines, decorators and the comment above, signatures rebuilt from the tree
(`ast.unparse`, falling back to the source line on a recursion error), module constants (UPPER_CASE) and type
aliases, definitions inside `if`/`try`/`with` blocks; a file Python's parser refuses (a syntax error, nesting
without end) is outlined by indentation and said to be approximate. The other languages are **approximate**,
every answer says so: comments and string contents are blanked out first (same length, same lines: `//`, `/* */`,
strings with escapes, characters, C++ raw strings, Java text blocks, Go raw strings, Rust raw and byte strings
(lifetimes are not characters), JavaScript template literals and regular expression literals, shell comments,
`${...}`, quotes and here-documents), braces of C preprocessor lines and shell braces that are not words (`{a,b}`)
are dropped, then one pass matches the braces and each line is tried against the language's declaration patterns
in the context of the open containers (a method only directly inside a class, a C function only at the top level
or in a namespace or class). A declaration's body is the first `{` before a `;` within 12 lines (signatures over
lines, Allman braces, C++ initializer lists, Rust `where` clauses); its end is the matching `}`. Known to work
(tested): TypeScript/JavaScript classes, interfaces, enums, type aliases, functions, arrow functions, methods,
getters, class fields holding arrow functions; Go structs, interfaces, `type (...)` and `const (...)` groups,
methods qualified by their receiver; Rust structs, enums, traits, `impl` blocks (methods qualified by the type),
`mod`, `macro_rules!`, constants; Java classes, interfaces, enums, records, nested ones, constructors, methods with
annotations and generics; C/C++ functions (also with the return type on the line before), prototypes in headers,
structs, anonymous typedef structs, classes, namespaces, `extern "C"`, out-of-class `A::b` definitions, macros;
shell functions in both forms, extensionless scripts by their `#!` line. Known to miss or misplace (accepted, said
in the answers): code generated by macros, braces inside `#if 0` or duplicated in `#ifdef` branches, object-literal
methods and nested functions of JavaScript that are not declarations, Kotlin, C#, PHP, Ruby and other languages (no
outline: `find_text` searches them). Every pattern runs on at most the first 400 characters of a line, with bounded
repetitions, and every token pattern either always matches once started or is bounded: a 2 MiB hostile file of
each language (one-line bundles, `{` only, 100,000 unterminated here-documents, nesting without end) is outlined in
0.3-1.1 s here (the here-documents first took 149 s - fixed, see below). At most 5,000 symbols per file. (The
independent review below found more such files - memory and time - and added caps and a 5 s limit per file: R2-R7.)

**The outline cache.** Outlines are kept per file - key: folder and path; fingerprint: modification time (ns),
size, inode and change time of the very descriptor that was read - least recently used first, at most 20,000 files
and 200,000 symbols (300,000 before the independent review, R4; a file without an outline is remembered as such,
so it is not read again). `find_definition`
walks the project on every call (`fstatat` only) and parses just the changed files; after a complete walk the
cache forgets the files of that folder that are gone. One call indexes at most as much as the cache holds and
says so ("narrow it with path"); the index walk has 20 s and says when it is incomplete ("call again to go on":
what it parsed stays cached). Measured here on the sandbox-ai checkout (1,075 files, 526 code files): the first
`find_definition` 1.8 s, the next 0.02 s; site-packages of the lock (1,451 Python files): 2.8 s, then 0.02 s; the
process peaked at 129 MB.

**Answers.** Plain text; at most 24,000 characters (cut at a line with "narrow it"); every list bounded (above);
a name or line from the project cannot start an answer line of its own (control characters and line breaks in
names and shown lines become `?`); a refusal is an MCP error saying why and what to do instead. Every call has a
45 s limit (below Codex's 60 s): a call that hits it is an error saying to narrow it.

**Network:** none; no module that could open a connection is imported. **Environment:** none read; no variable,
no secret. **Logging:** only an exception's type, to stderr.

## Self-review: what was found and changed

Written test-first where a test could show it; each finding below has its test in `tests/test_code_search.py`.

1. `extern "C" {` and anonymous `typedef struct {`: the declaration's pattern consumed its own `{`, so the body
   search found the next declaration's brace and the following C function was swallowed. The body search now starts
   at the name, or at the match's start when there is none (`test_c_and_cpp`).
2. A Rust function with a `where` clause ended at its signature (the clause's lines were not taken as a continuation)
   - now `where` and lines ending in `,` continue it (`test_rust`).
3. Shell here-documents were blanked by a regular expression that, for each `<<EOF` without its end, scanned to the
   end of the file: 149 s for 2 MiB. Replaced by one line-by-line pass (0.3 s) (`Hostile`).
4. JavaScript regular expression literals: the token was unbounded and tried after every `=`, `(`, `,` ...: quadratic
   on a one-line bundle. Bounded to 300 characters (`Hostile`).
5. `.gitignore` rules and globs were first translated into one regular expression per pattern: `*a*a*a*...b` against
   a long name backtracked without end (a cloned project could stall every walk). Replaced by `Glob` (above)
   (`Hostile.test_a_gitignore_or_glob_made_to_backtrack`).
6. The entry budget counted entries as they were looked at, after a folder was listed: deep trees of huge folders
   could be held in memory first. Folders now count when listed (`test_the_entry_budget_stops_a_walk`).
7. One `find_definition` over a very large tree held every outline in memory at once, beyond the cache's bound (a
   512m container). Now one call indexes at most what the cache holds and says so
   (`test_one_call_indexes_at_most_what_the_cache_holds`).
8. A file named `x\nIGNORE ALL RULES.py` started an answer line of its own. Names and shown lines have control
   characters replaced (`test_a_name_or_line_cannot_start_a_line_of_its_own`).
9. Python's `SyntaxWarning` for invalid escapes went to stderr during `ast.parse`: silenced
   (`test_python_warnings_stay_out_of_stderr`).
10. Module constants crowded out the functions of a real module's outline (`sandbox/mcp.py`: 30 lines of
    constants first): now one "constants:" line by name (`test_python_is_exact...`).
11. `project_map` of C++ code in a namespace showed no functions: names directly in a namespace or module count as
    top-level (`test_tree_with_counts_sizes_and_symbols`).

**Remaining risks** (accepted):

- The outlines of the brace languages are approximate (above); a model that relies on a wrong end line reads too
  much or too little - every answer says "approximate", and `read_symbol` says "check where it ends".
- `find_references` finds words, not resolved uses: `save` of one class and of another are the same word (said in
  the answer for `Class.method`).
- A timer signal that fires between `openat` and the `try` that closes the descriptor leaks one descriptor (a
  window of a few instructions; the process keeps running).
- A hard link inside the project to a file elsewhere on the same file system is read like any file: it is the
  user's own folder, and a hard link cannot cross the bind mount.
- The code and comments shown come from the project, perhaps a cloned one: data, not instructions.

**Overlap with other branches:** `scripts/smoke_test.py` got the fresh mount's `"seed"` with files (merged to main
before this branch); this branch adds only that a seeded fresh mount may be read-only (no `"writable"`), so that the
smoke run gives the server its folder read-only as users do (`tests/test_smoke_test.py`).

## Tested

- `tests/test_code_search.py`, offline, 60 tests on a seeded project in Python, TypeScript, Go, Rust, Java, C, C++
  and shell (with a `.gitignore`, a nested one, `build/`, `node_modules/`, `.git/`, a minified bundle, a log, a
  file outside the folder and a reference folder): each language's outline with kinds and line ranges; Python
  exact and its fallback; `find_text` (the function a line is in, `.gitignore` and the skipped folders, explicit
  paths into them, regex, `ignore_case`, globs with braces and paths, `max_results`, `offset`, the count, long
  lines, binary and large files, a refused repeat, a backtracking pattern stopped by the timer in about 0.5 s, the
  entry budget, the answer cap, `/ref1`, `/ref2` not mounted); `find_files` (ranking, globs, paths, `/work/...`,
  similar names, the bound); `find_definition` (ranking: exact, tests later, other case marked; every language and
  qualified names; `kind`; similar names; `impl` blocks are no definitions; the cache: nothing parsed twice, only a
  changed file parsed again, a same-size change with a new time, a deleted file forgotten; the bounds on files and
  symbols; an index out of time saying so and going on); `find_references` (the order of the groups, whole words,
  a path, the rest counted per file); `read_symbol` (decorator and comment included, other languages, ambiguous and
  unknown names, a long class cut and its parts named); `project_map` (counts, sizes, symbols, depth, path, the
  bounds); paths (`..`, outside, `~`, backslash, absolute globs; links out of the folder - absolute, relative, to a
  file - refused when named and never followed by the walks; a link inside followed when named; a link loop; a
  named pipe refused and never blocking a walk; nothing written: every file's mtime unchanged); `.gitignore` rules;
  hostile files and patterns (above); over stdio: the seven tools as `tools.json` records them, read-only hints,
  descriptions under 900 characters, no output schema, a plain-text answer and a refusal as an error. Run here with
  the lock's mcp 1.30.0 on Python 3.11: all pass.
- `tests/test_own_servers.py` `test_code_search`: the tools, six refusals before any file is looked at (so the real
  `/work` is never walked), then the whole offline suite - in CI inside the image (Python 3.13), nothing skipped.
- `tests/test_analysis_servers.py` `CodeSearch`: the shared lock, the imports (standard library and the SDK only),
  no write, exec or network call in the source, the flags of every `openat`, the folders read-only in the entry and
  in the smoke run, every tool called for real in the smoke run.
- `smoke.json`: a seeded read-only `/work` with a Python, a TypeScript and a Go file, an ignored `build/` and a link
  to `/etc`: each tool called for real, then refused: a repeated repeat, `..`, the link, `/etc`. Run here natively
  over stdio against the seeded folder (11 of 11 pass); not built here (no container engine).

## Verdict

Our own code, reviewed in full; no third-party code beyond the shared lock. Ready for CI; sign once both smoke
reports pass.

## Independent review, 2026-11-13

A second reviewer, not the builder, read the server and everything shipped with it from scratch for backdoors and bad
code, without relying on the self-review above. Threat model: the agent calling the tools is a confused small model
or a prompt-injected one; the project may be a hostile clone whose files, names, links and `.gitignore` files are
crafted to hang or crash the parsers, exhaust the container's memory (sandbox-ai's default 512 MiB) or fake lines of
an answer. Line numbers are those of the reviewed commit `3f50437`.

**Read line by line:** `src/server.py` (2,166 lines), `Dockerfile` (29), `server.json` (40), `smoke.json` (131),
`tools.json` (20), `requirements.in` (1), `requirements.txt` (586: byte-identical to files' but for its `# via` line;
the same set, comments aside, as every other server of the lock), both `LICENSES/` files (21 and 26 lines, identical
to files'), this file (216), `tests/test_code_search.py` (955), and the branch's diff against its merge base `11bdf90`:
`scripts/smoke_test.py` (+5/-3, a seeded fresh mount may be read-only), `tests/test_analysis_servers.py` (+64),
`tests/test_own_servers.py` (+18), `tests/test_smoke_test.py` (+12), `.github/workflows/build.yml` (the matrix entry),
`README.md` (+28), `SECURITY.md` (+4), `catalog.json` (the entry, generated), `digests.json` (pending),
`docs/CANDIDATES.md` and `docs/LOCAL_LLM_TOOLS.md`. **Read for context:** mcp 1.30's `func_metadata.py` (a
synchronous tool is called directly on the event loop, the main thread, so `SIGALRM` reaches it) and its stdio
transport (a request with a lone surrogate is refused as invalid JSON before any tool: tried). **Scanned:** the
imports (standard library and the SDK only), every `os.` call (`open` with `O_RDONLY` only, `read`, `fstat`,
`stat` without following, `readlink`, `scandir`, `dup`, `close`), no `subprocess`, socket, URL, `eval`, `pickle`,
environment or file write. **Tried against the code** (each in its own process, memory capped): `..` and absolute
links at every depth, link loops, a link target with a line break, file names that are not UTF-8 or hold `\u2028`,
2 MiB files of each language made of one token repeated (`x\n`, `{`, `/*`, a template literal, `#define`,
`extern "C" {`, `typedef struct {`, one class name of 1.5 MB, 1,500 nested classes, JavaScript regular expression
literals), `.gitignore` files of 64 KiB (trailing spaces; `**/*/` 199 times), user regular expressions (`.*x`,
`\w*x`, `[ab]*c`, `(a|aa)*c`, nested repeats) on one-line files and per line, and the smoke spec over stdio against a
read-only seeded folder (11 of 11 pass).

### Findings (all fixed test-first: each test in `tests/test_code_search.py`, class `IndependentReview`, failed before its fix)

| # | Severity | Where (at `3f50437`) | Scenario | Status |
|---|---|---|---|---|
| R1 | medium | `server.py` 199 `display`, 320, 1434 `answer` | A file or link name that is not UTF-8 (`bad\xff.py`, common in old projects) comes from the file system with a surrogate escape; the SDK cannot serialize such an answer and the **whole server ended** (stdout closed, a traceback with paths on stderr) at the first `project_map`, `find_files`, `find_text` or `find_definition` that listed it - for the rest of the session | CONFIRMED over stdio (`test_r1_a_name_that_is_not_utf8_does_not_end_the_server`), fixed: every answer and refusal is made UTF-8 in `answer` (a surrogate becomes `?`) |
| R2 | medium | 788-792 `outline_python` | `ast.parse` takes about 1 KB of memory per token and cannot be interrupted: a 2 MB Python file of `x\n` peaked at 1.8 GB (400 KB: 367 MB traced; 256 KiB: 230 MB) - beyond the container's 512 MiB, so the server is killed; generated modules of this size are not rare | CONFIRMED (`test_r2_...`), fixed: a file of more than 100,000 tokens (counted by a pattern that stops there; real code: 400 KB and more) is outlined by indentation and says so; worst case now about 100 MB, 0.3 s |
| R3 | medium | 819, 836, 869, 1243/1267 | A qualified name repeats its containers: one class name of 1.5 MB with 5,000 methods made 5,000 strings of 1.5 MB (7.5 GB); 1,500 nested Java classes with 380-character names took 466 MB for a 1.15 MB file; `read_symbol`'s refusal listed 40 such names (2 MB, not capped) | CONFIRMED (`test_r3_...`), fixed: a name keeps at most 120 characters, a qualified name its last 240 (`...Outer.name`), at most 100 parts |
| R4 | low-medium | 88 | The cache's bound counted symbols, not bytes: 300,000 symbols of names up to 400 characters and unbounded qualified names took 877 MB (measured per symbol), and even small ones 130 MB | CONFIRMED (`test_r4_...`: a full cache of the largest symbols one file gave: 478 MiB), fixed: with R3's caps a symbol takes at most about 870 bytes; 200,000 of them: 168 MiB |
| R5 | low-medium | 882-903 `TOKENS`, `_PREPROCESSOR`, 1068 `_braces` | A repeat of an alternation makes the regular expression engine keep about 120 bytes per repetition: a 2 MiB comment, string, template literal or `#define` line took 290-305 MiB; 2 MiB of `{` took 298 MiB of brace positions | CONFIRMED (`test_r5_...`), fixed: those repeats are possessive (`*+`, Python 3.11+; the image has 3.13, results identical since none gives characters back); a file with more than 100,000 `{` is not outlined (said so) |
| R6 | low | 1236, 1243, 1271 | Hidden containers (`extern "C" {`, anonymous namespaces) piled up without bound and every line walked the pile: 160,000 lines would take about 4 minutes; each `typedef struct {` searched the whole line of its `}`: 100,000 of them likewise | CONFIRMED (`test_r6_...`: 30,000 lines 8.0 s, 24,000 typedefs 4.7 s), fixed: at most 100 containers open; the typedef's name is read right after its own `}` (the brace pass keeps its column) |
| R7 | low-medium | 1343, 1374 `index`, 2117 | No limit per file: `find_definition` and `project_map` parse files with only the call's 45 s above them, so one file made to stall the outliner (R6, or 2 MiB of JavaScript regular expression literals: 13.8 s) ended every such call in "took longer than 45 s" with nothing remembered - the same file was reached again on each call, contrary to "a second call goes on" | CONFIRMED (`test_r7_...` with a parse that does not end), fixed: one outline has 5 s (its own timer; `time_limit` now yields whether its own limit fired, so an enclosing limit is never blamed on the file); a file given up is remembered until it changes and says so |
| R8 | low | 123 `_SHOWN_CONTROLS`, 2038, 320 | `read_symbol` showed source lines as they are: a lone `\r` in a line started an answer line of its own; `\x85`, `\u2028` and `\u2029` (line breaks for `str.splitlines()` and many renderers) passed in names and shown lines; a link target with a line break went into a refusal | CONFIRMED (`test_r8_...`), fixed: those characters are `?` everywhere, `read_symbol`'s lines and link targets included (tabs stay) |
| R9 | low | 450, 395-433 `Glob`, 514-519 `tick` | `.gitignore`: trailing spaces were cut one at a time (64 KiB of them: 60 ms per file per walk, 12 s for 200 such folders); a pattern of 200 parts against a deep path cost 150 ms per entry and the walk looked at the clock every 64 entries (61 entries: 9.6 s); a `glob` argument of 80 parts likewise | CONFIRMED (`test_r9_...`), fixed: trailing spaces cut in one step (same result), patterns of more than 16 names dropped from `.gitignore` and refused as `glob`, the clock read at every entry, each `.gitignore` parsed only up to the rules still allowed |
| R10 | medium | 1574 | The SIGALRM limit does not hold for a regular expression over a whole file: the engine looks for the signal only now and then, and a single repeat (`.*x`, `\w*x`, `[ab]*c` - ordinary patterns) over a long line runs a whole scan in between; `find_text` matched every file in one call first. On a one-line file of 300 KB a 0.5 s limit fired after 37 s; at 2 MiB (a bundle or JSON not named `.min.js`) the search, the call's 45 s and the client's 60 s all pass while the single-threaded server answers nothing | CONFIRMED (`test_r10_...`), fixed: a regular expression is matched only line by line, each line to 10,000 characters (measured: the limit then holds within about 0.05 s for every pattern tried); plain text keeps the whole-file quick check (a literal has no repeat) |

**Checked and found sound:** every path walked one name at a time from the root's descriptor with `O_NOFOLLOW`;
a link named in a path followed only inside its root (`..` of a target goes up the folders actually walked, an
absolute target only below the root, 16 links at most), never by a walk; regular files only, opened `O_NONBLOCK |
O_NOCTTY` and `fstat`ed (a pipe never blocks); names over 255 bytes, paths over 4,096 characters, `~`, `\` and
control characters refused before anything is opened; nothing written, created or executed; no network; no
environment read; errors carry `strerror` only. `Glob`'s per-name regular expressions are `fnmatch`'s, with atomic
groups. The Dockerfile and lock are files' (same digest, Debian pins and hash-locked set, pip removed, user 10001);
no new third-party release, so the 14-day rule is met. The smoke spec mounts `/work` read-only, calls every tool and
the refusals; `smoke_test.py`'s change lets only a seeded fresh mount be read-only. The self-review's eleven
findings are fixed as described.

**Remaining risks** (accepted): `_NESTED_REPEAT` is a heuristic (`(a?){30}a{30}` and `(a|aa)*c` pass it); what it
lets through is stopped by the timer, which since R10 holds because no match runs on more than 10,000 characters.
Python's parser cannot be interrupted; R2 bounds it to about 100 MB and 0.3 s. A file made to stall an outline still
costs 5 s once per change (several such files make the index incomplete for a few calls; each is then remembered),
and a file that is merely slow on a loaded machine loses its outline until it changes. Under 500 `.gitignore` rules
of 16 names each a walk still costs about 8 ms per entry 60 folders deep (1.5 s for 180 files). Names longer than 120
characters are cut, so a longer one is found only by its start. `find_files` and `project_map` have no timer of their
own (the walk's budget, read at every entry, and the call's 45 s). Measured worst case of memory after the fixes:
the full cache under 170 MiB, one file's outline up to about 110 MB above the server's 50 MB: well inside 512 MiB. A
timer signal between `openat` and the `try` that closes the descriptor leaks one descriptor, and one between the
cache's update and its symbol count leaves the count slightly off (windows of a few instructions). The code shown is
the project's: data, not instructions.

**Tests:** `tests/test_code_search.py` 69 tests (ten added), the whole suite (`SANDBOX_AI_CHECKOUT=...
python -m unittest discover -s tests`: 512 tests, OK) and `make_catalog.py --check --allow-pending` pass; the smoke
spec passes natively over stdio against a read-only seeded folder.

**Verdict: fit to sign - yes**, for an image built from the fixed code once both CI smoke reports pass. No backdoor,
no network code, nothing written or read outside the mounted folders; the ten findings were availability and
answer-integrity bugs (a crash on a name, memory and time beyond the container's limits, faked answer lines), all
fixed with tests.
