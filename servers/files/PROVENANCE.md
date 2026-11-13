# files - provenance and audit

| | |
|---|---|
| MCP server | this repository, `src/server.py` (MIT, `LICENSES/`), written for this repository and reviewed in full (below) |
| Python packages | `mcp==1.30.0` and its dependencies, hash-locked in `requirements.txt` (byte-identical to web-fetch's but for the `# via` line; the set web-fetch, gowitness, whatweb and youtube run). The server itself uses the standard library and the SDK only |
| Debian packages | `python3=3.13.5-1`, `python3-venv=3.13.5-1` (purged after the venv is made), `ca-certificates=20250419+deb13u1` (for pip's download during the build; Debian's pip uses the system's certificates) |
| Base image | the `debian:trixie-slim` digest in `Dockerfile` (the same as web-fetch's) |

**Pinning rule:** no new third-party release comes in: the Python set is the lock the published images already use
(taken under the 14-day rule when it was made), the Debian versions and base digest are theirs.

## Why an own server

Agents on small local models (OpenCode, Codex or Hermes with `--llm`) get file writes wrong far more often than the
large hosted ones: the whole Markdown document wrapped in a ```` ```markdown ```` fence, `\n` written as two
characters, the text sent as a JSON string, a file overwritten with a stale copy, an edit whose `old_text` matches
nothing (or three places), line numbers from a read copied into the text, a patch with off-by-one hunks. This server
makes the common file operations hard to get wrong and reports what it did: every write answers lines added and
removed and the new sha256, a whole-file write needs the sha256 the file was read with, an edit needs one exact
match, and `write_markdown` repairs the typical mistakes and lists each repair.

The reference server `@modelcontextprotocol/server-filesystem` was not taken: it resolves paths with `realpath` and
then opens them by name (a link swapped in meanwhile is followed), overwrites without a check, and has no repairs.
One file of our own on the SDK this repository already ships is smaller than reviewing and patching it.

## Tools

| Tool | Writes? | What |
|---|---|---|
| `read_file` | no | a text file, at most 1000 lines / 60,000 characters per call (`start_line`, `end_line`, `next_start_line`), optional line numbers, the whole file's sha256, its line breaks, BOM, encoding; a binary file by size and sha256 only |
| `list_dir` | no | a folder's entries (type, size, a link's target), depth 1-5, at most 500; `/` lists the mounted folders and whether they are writable |
| `glob` | no | paths matching `*`, `?`, `[...]`, `**`, at most 500 |
| `search` | no | plain text or a regular expression, line by line, `include` glob, at most 200 matches; binary files and files over the limit skipped; stopped after 20 s |
| `stat` | no | exists, type, size, mode, time, a link's target and where it leads; for a text file its lines and sha256 |
| `diff` | no | a unified diff of two files or of a file and a proposed content, at most 400 lines |
| `checksum` | no | sha256 (sha512, sha1, md5) of any file |
| `write_file` | **yes** | a whole file; an existing one only with `expected_sha256` or `overwrite=true`; `line_endings` keep/lf/crlf; binary-looking content only with `allow_binary` |
| `write_markdown` | **yes** | a Markdown file after the repairs below; `title`; `dry_run` |
| `edit_file` | **yes** | one exact replacement (or `replace_all`), with a whitespace-tolerant fallback when it finds exactly one place |
| `insert_lines` | **yes** | whole lines before line N |
| `delete_lines` | **yes** | lines N to M, answered with what they held |
| `append_file` | **yes** | text at the end (a line break added first when the file has none) |
| `apply_patch` | **yes** | a unified diff of one file; all hunks or nothing |
| `move` | **yes** | rename or move inside `/work` (into a folder when `dst` is one; no replacing without `overwrite`) |
| `copy` | **yes** | a file or folder into `/work` (from `/work` or `/ref1`-`/ref3`); links, devices and pipes inside left out |
| `mkdir` | **yes** | a folder with its parents |
| `delete` | **yes** | moved into `/work/.trash/<time>-<random>/<path>` (restore with `move`), or removed with `FILES_TRASH=0` |

### write_markdown's repairs (each reported in `repairs`)

- the whole content wrapped in a code fence: ```` ```markdown ````/`md`/`mdx`/`gfm` (or a bare fence around text with
  a heading), unwrapped when the fences inside it are balanced; an opening ```` ```markdown ```` that is never
  closed (a cut-off answer) dropped; a document that is a code block (```` ```python ````, a bare fence around code)
  stays one;
- literal escape sequences: when the text has **no** real line break but `\n`, the JSON escapes `\n`, `\t`, `\r`,
  `\"`, `\\` are decoded, except inside inline code spans; a text with real line breaks is never decoded (a
  literal `\n` outside code is reported instead);
- the whole content as a JSON string (`"# Title\n..."`): decoded;
- CRLF and lone CR line breaks: normalised to LF; an existing file written with CRLF keeps CRLF;
- a byte order mark at the start removed (an existing file's BOM is kept);
- trailing spaces and tabs outside code removed, except a hard line break (two spaces before a following line);
  code blocks untouched;
- `#Heading` without a space: fixed outside code, front matter and HTML comments; not for `#!`, `#include` and the
  other preprocessor words, `#123`, hex colours, or lines with several `#tags`;
- a code fence left open: closed at the end (with its line named);
- the first heading repeated right after itself: the repeat removed;
- blank lines at the start and the end removed, a missing final line break added;
- `title`: added as `# title` unless the content starts with that heading (another first heading is kept and named
  in a warning).

Left as is and reported in `warnings`: tables whose rows have another number of cells than the header, a delimiter
row that does not fit, pipe rows without a delimiter row; raw HTML (scripts, iframes, event handlers and
`javascript:` named separately); an HTML comment or front matter that is not closed; heading levels skipped; a link
whose `(` is not closed, an empty link target, a reference link without a definition. Lists indented with tabs are
not touched. The structural check at the end confirms the code fences are balanced.

## Audit of the server (`src/server.py`, read in full)

**Paths.** A path is relative to `/work` or absolute under `/work`, `/ref1`, `/ref2`, `/ref3`; anything else, `..`,
`~`, backslashes, control characters, NUL, names over 255 bytes and paths over 4096 characters are refused before
the file system is touched (`split_path`). `locate` then walks the path one name at a time from the root's open
descriptor: every folder is opened by its name in the folder before with `O_DIRECTORY | O_NOFOLLOW` (`openat`), so a
folder swapped for a link between the check and the open fails with `ELOOP` instead of leading elsewhere. Links:

- the **write tools follow none** - a link on the way or as the file itself is refused, with its target named;
  `delete` and `move` take a link as the link itself (never what it points to);
- the **read tools** follow a link only while it stays inside its folder: its target is spliced into the walk, `..`
  in a target goes up the folders actually walked (never above the root), an absolute target must lie under the
  same root, at most 16 links per path. A link out of the folder is refused ("never followed");
- `list_dir`, `glob`, `search` and `copy` never enter a linked folder.

Files are opened with `O_NOFOLLOW | O_NONBLOCK | O_NOCTTY` and `fstat`ed before a byte is read: only regular files are
read, devices, pipes and sockets are refused by kind (a pipe does not block the server). Nothing is written to
`/ref1`-`/ref3` (whatever their mount mode), to `/work` when it is mounted read-only (`fstatvfs`) or with
`FILES_READONLY=1`, to a `.git` folder (git's hooks would run on the host) or into `.trash` (restoring out of it
with `move` is allowed).

**Writes.** Every write goes to a new temporary file in the same folder (`O_CREAT | O_EXCL | O_NOFOLLOW`, mode 0600),
is written, given the old file's permissions (or `0666 & ~umask`), `fsync`ed, then renamed over the name, and the
folder is `fsync`ed. An interrupted write leaves the old file and removes the temporary one. A new file is put in
place with `link(2)`, which refuses a name that appeared meanwhile (`rename` after a check where a file system has no
hard links). An existing file is replaced only if it is still the very file that was read (inode, size, mtime and
ctime compared just before the rename) - and a whole-file write only with `expected_sha256` equal to its content's
sha256, or `overwrite=true`. An existing file's line breaks (CRLF, CR, the majority of a mixed file) and BOM are
kept; a write never writes into an existing inode, so a hard link elsewhere keeps the old content. Content that
looks binary (NUL, more than 5% control characters) needs `allow_binary`. Lone surrogates are refused. At most
`FILES_MAX_BYTES` (default 8 MiB, 1K-256M) per read or write; `copy` at most 1 GiB and 10,000 entries (a folder is
copied into a temporary folder and renamed into place at the end).

**Bounded answers and time.** Reads in parts (1000 lines, 60,000 characters), lists and globs at most 500 entries,
search at most 200 matches with lines cut to 300 characters, diffs at most 400 lines, previews 12 lines; glob and
search look at no more than 200,000 entries. Every call is stopped after 120 s, search, glob and diff after 20 s, by
a timer signal (FastMCP calls these synchronous tools on the main thread), which also stops a regular expression
that backtracks without end; the limits nest.

**Errors.** Every refusal says why and what to do instead (`read_file` it again, pass `expected_sha256`,
`create_dirs=true`, `replace_all`, the nearest matching lines). An `OSError` is answered with its `strerror` only, an
unexpected exception with its type only (no traceback, no paths of the container on stderr).

**Scanned:** no `subprocess`, sockets, `eval`/`exec`, `pickle`, `ctypes`, `os.system`, `chown` or `realpath`, and
no call that follows a link on a path an argument names (only the configured roots are checked with `isdir`); no network code at all; the only non-ASCII characters are written as escapes (U+FEFF, U+2028,
U+2029, U+2192). `tests/test_analysis_servers.py` (`Files`) checks the imports and these words.

## Self-review: what was found and changed

Read again file by file after the first version passed its tests, as the third-party code of this repository is
(path escapes, races, half-written files, unbounded answers, misleading answers):

- **Time limits** - the search's 20 s timer replaced the call's limit and switched it off when it ended: the
  limits nest now (an inner one restores what the outer one has left; `test_time_limits_nest`).
- **edit_file's whitespace-tolerant match** began with `[ \t]*`, so it took the line's indentation with it and the
  replacement lost it; the match starts at the first word now, and an indentation `old_text` and `new_text` share is
  not added twice.
- **delete_lines** added a line break to a file that had none at its end when an inner line was deleted.
- **A socket** was answered "No such device or address" (`ENXIO` of `open`) instead of "a socket".
- **The repeated first heading** was removed together with the blank line after the first one.
- **HTML comments** - the text before a comment on the same line was dropped from the checks, and a `#word` inside a
  comment would have become a heading.
- **write_markdown's dry_run** looked at the file through links and failed where the real write would only refuse;
  it now looks as the write would (no links) and names a refusal (`would_be_refused`, `needs`) instead.
- **delete** refused a link (the write walk refuses a link as the last name) and the restore its answer suggests
  (`move` out of `.trash`) was refused too; a link is deleted as itself and the trash is a valid `move` source.
- **move and copy** with `/work` itself as `dst` were refused (the root is never written); it means "into it" now.
  Copying a file onto itself said "inside itself".
- **The trash** - `/work/.trash` as a link is refused (never followed); it gets a `.gitignore` of `*`.

**Remaining risks** (accepted): between the last check and the `rename` of a write, another writer in the same
folder could change the file (microseconds; a concurrency question inside the workspace, not an escape). A write
gives the file a new inode: its owner becomes the server's user (with sandbox-ai's `--user=0:0` under rootless Podman,
the user), extended attributes and ACLs are not copied, setuid/setgid bits are dropped, and a hard link elsewhere
keeps the old content (by design). A file hard-linked into `/work` from outside can be read - as by anyone who has
the folder. The time limits use `SIGALRM` on the main thread; were FastMCP to call tools on a worker thread, a
regular expression would be bounded by the line and file limits only. `write_markdown`'s line numbers count the
content after unwrapping or decoding. The trash grows until the user empties it.

**Limits:** none beyond sandbox-ai's defaults (512m memory, 128 processes, a 64m /tmp): a call holds at most a few
copies of one `FILES_MAX_BYTES` file and writes nothing to `/tmp`, so `smoke.json` sets none.

## Tested

- `tests/test_files.py` (60 tests, offline, temporary folders the module's `ROOTS` point at): every path refusal
  (`..`, absolute paths elsewhere, `~`, backslashes, control characters, long names); links out of the folder,
  absolute, relative and through `..` of a deeper link, for every read tool, glob and search; links inside followed by
  reads and refused by every write; link loops; **races**: a folder swapped for a link to elsewhere while it is walked,
  and a file swapped for a link before it is opened (both refused, nothing outside read); a pipe, a socket and a
  folder as a file; the size limit and its variable; `FILES_READONLY` for every write tool; the `/ref` folders; a
  read-only mount; `.git` and the trash; reading in parts, line numbers, binary, Latin-1, CRLF, BOM; **atomicity**:
  an `fsync` that fails leaves the old file and no temporary file, a file changed in place, replaced, or created
  between read and write is not overwritten; `expected_sha256` and `overwrite`; mode, CRLF and BOM kept; hard links;
  every Markdown repair and warning above (and what is deliberately left alone: code blocks, `#include`, lists with
  tabs, a document that is a code block); dry runs; `edit_file`'s uniqueness, counts and line numbers, its tolerant
  fallback (one match taken, two refused), line-number prefixes stripped, CRLF kept; `insert_lines`/`delete_lines`
  edges; `apply_patch` (clean, offset, a failing hunk showing the file's lines and writing nothing, `\ No newline`,
  blank context, a new file, two files refused, wrong header counts); move, copy, mkdir, delete (trash, restore,
  links, `FILES_TRASH=0`, a trash that is a link); list, glob, search (a backtracking regular expression stopped),
  stat, checksum, diff; the tool list against `tools.json` with every write tool marked.
- `tests/test_own_servers.py` `test_files`: the server over stdio (tool list, refusals before any file is touched),
  then all of the above inside the image in CI (its Python and libraries, no network).
- `smoke.json`: a fresh writable `/work` seeded with a link `escape -> /etc` and a file: `write_markdown` repairing a
  fenced, mis-headed, duplicated, trailing-space sample (expects the unwrap), `read_file` of the exact repaired text,
  `write_markdown` decoding literal `\n`, `edit_file`, `search`; refused: a blind `write_file` over the file, `../etc/passwd`,
  `escape/passwd` (the link escape), `/etc/cron.d/x`; then `delete` into the trash. The same calls were run against the
  server natively (`--runner`-less, roots pointed at a seeded folder) before the first CI run; the image itself is
  built and run by CI.
