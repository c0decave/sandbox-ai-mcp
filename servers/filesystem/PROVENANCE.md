# filesystem - provenance and audit

| | |
|---|---|
| Upstream | the official MCP filesystem server, `@modelcontextprotocol/server-filesystem` **2.1.0** (modelcontextprotocol/servers `src/filesystem`; Apache-2.0, older contributions MIT: `LICENSES/modelcontextprotocol-servers-LICENSE.txt`, the same file as servers/memory's and the repository's `LICENSE` at the commit), commit `194cc86e3ae6400958555bd4116849d822d69263` (npm 2026-10-28 21:08 UTC; the commit servers/memory's 2.0.1 was built from) |
| In the image | the npm package of 2.1.0 (`dist/*.js`, eight files, and `package.json`; built by upstream CI from that commit: the npm provenance attestation names `.github/workflows/release.yml` at `refs/tags/v2.2.0` - the repository's release tag of that day, under which the filesystem package was published as 2.1.0 - and commit `194cc86e`), tarball `sha512-BMihuyTNi975iQTQDsZ6x+JVg99CAiX83jBV0wGMyc/0DcBO55ulCQqEzwx7lbG5U9/97XiPP9n0sK/iUtSsEg==` (SHA-256 `65aba6b962efa7fdfdd51d70b48c06e7786c8bbc57292520dec21924836031df`); the Dockerfile checks the eight `dist/*.js` and `package.json` by SHA-256 |
| Our code | `src/entry.mjs` (MIT, this repository), the entry point in place of upstream's `dist/index.js`: the allowed directories are the mounted folders, MCP Roots are never used (below) |
| npm packages | `package-lock.json` (made with `npm install --package-lock-only --ignore-scripts --before=2026-11-01T00:00:00Z`): `@modelcontextprotocol/server` 2.4.0 (2026-10-23, `sha512-rgR9yxSa...`), `@modelcontextprotocol/core` 2.4.0 (2026-10-23, `sha512-z8QBKqdf...`), `zod` 4.6.7 (2026-10-12, `sha512-g8W2D2kU...`) - the same integrities as servers/memory's lock, so the same files - `diff` 8.0.4 (2026-03-23, `sha512-DPi0Fmji...`), `minimatch` 10.2.6 (2026-07-27, `sha512-vpLQEs+V...`), `brace-expansion` 5.0.12 (2026-09-14, `sha512-YovQ3rzh...`), `balanced-match` 4.0.4 (2026-02-22, `sha512-BLrgEcRT...`). `glob` 13.0.6 (2026-02-19, `sha512-Wjlyrolm...`) with `path-scurry` 2.0.2, `lru-cache` 11.5.3 and `minipass` 7.1.3 are in the lock because 2.1.0 declares glob, but nothing imports it (2.2.0 drops it): the build deletes them after `npm ci --omit=dev --ignore-scripts` and checks that only the eight packages above are left, each at its version. No package of the lock has an install script |
| Node.js | 24.22.1, the `node` binary only, from `node:24-trixie-slim` `sha256:89c5244bc22a9bc3287d89ebc7e49b9cb5bb84cd40e6175ac3421d5a9f68b95a` as docker-library/repo-info recorded it on 2026-10-28 (commit `55f75407`), the image of servers/memory. The package requires Node.js 24 (`engines`); npm, corepack and yarn of that image stay in the build stage |
| Base image | the `debian:trixie-slim` digest in `Dockerfile` (`sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad`); no Debian package is added |

**Upstream:** https://github.com/modelcontextprotocol/servers, the reference servers of the Model Context Protocol
project (see servers/memory's PROVENANCE.md). Upstream's own `src/filesystem/Dockerfile` (unpinned `node:24-alpine`,
`npm install`) and its `dist/index.js` entry are not used.

**Pinning rule:** prepared on 2026-11-15, cut-off 2026-11-01. 2.1.0 (2026-10-28) is the newest release published on or
before it. Too new: **2.2.0** (2026-11-04 21:36 UTC, old enough on **2026-11-18**): `--confine-roots`, `--read-only`,
`append_file`, `copy_file`, a `file://` resource template, `directory_tree` `depth`, drops `glob`, moves `minimatch` to
11 (GHSA-g3hv-75wg-m249, not reachable here: below). **2.3.0** (2026-11-11 07:10 UTC, old enough on **2026-11-25**):
`--read-only-dir`, and #5516 "anchor read tools to the validated file ... a FIFO, socket or device is refused rather
than read" - the fix of finding 1 below. Re-pin to 2.3.0 from 2026-11-25 (the review of its diff; entry.mjs then also
passes `--read-only-dir` for `/ref1`-`/ref3` mounted read-only). Every npm package of the lock was published on or
before 2026-10-28 (the server itself; the newest dependency is the SDK of 2026-10-23).

**Known CVEs of this server:** CVE-2025-53110 (GHSA-hc55-p739-j48w, path validation bypass by a colliding prefix:
`/work-evil` accepted for `/work`) and CVE-2025-53109 (GHSA-q66q-fx2p-7w4m, a symlink out of the allowed directories
followed), both high, affecting `<= 0.6.2` and `>= 2025.1.14, < 2025.7.1`; fixed in 2025.7.1. 2.1.0 is outside both
ranges, and the fixes are in its code: `isPathWithinAllowedDirectories` compares at a separator boundary
(`path-validation.ts` 95-104), and every path is `realpath`'d and the real path checked again (`lib.ts` 507-536,
`resolveUnicodeEquivalentPath` component by component for paths that do not exist yet). Both were tried locally
(Tested). The npm advisory database lists no other advisory for the package (queried 2026-11-15); `npm audit` of the
lock reports only GHSA-3g3m-2fjr-6pw4 (glob, removed from the image) and GHSA-g3hv-75wg-m249 (minimatch, below).

## What was reviewed

**The server, in full** (all of what runs of it):

| File | Lines | SHA-256 |
|---|---|---|
| `dist/index.js` (npm 2.1.0) | 131 | `fd44be644b81d088eded98d73a5521a179850e716102aa1d7a9edccf6d79fba9` |
| `dist/server.js` | 701 | `139c72a59734005319ea66463ea4d405bb29b456082b9a6b68074d1063dbbc34` |
| `dist/lib.js` | 711 | `7acd502f656812f99e22e0352649564b5ce2707b5623a136239c0da7ab36b72c` |
| `dist/pinned-directory.js` | 472 | `170ab06bde78c692297ead795c279dae77db7c57f1dd37fc907a8304ce8fdd85` |
| `dist/path-utils.js` | 146 | `5736001d7214f0d8eb47abeb0849f777529c17aa7b8b5c3320209e89bd963f38` |
| `dist/path-validation.js` | 88 | `07fbf314443ad3f4a30ab462b122a18f53bbc895f628e3a5830bca8aed59386b` |
| `dist/roots-utils.js` | 85 | `750172b0d92bdcccd17925e04f80b18aeb284e844b1fdd0a457fabf4a3e76ef9` |
| `dist/version.js` | 35 | `044a3819acfb25e8038eb742845502eb255fa719aaa158b4befad5a58a44854d` |
| `package.json` (npm 2.1.0 = the commit's) | 53 | `42ddd58e3f5580d07af425bc7394d78496db410c3a522c73c174ea108a051771` |
| `src/filesystem/index.ts` (commit `194cc86e`) | 165 | `13cc40839afb7063d237b096da9db917c245eeb7f0bc9ce8c605309dc2f4a3fe` |
| `src/filesystem/server.ts` | 934 | `672a909d31499e7ffde523705a31c90eb8d2a69f3b135ff0a1d5c23bf98083fc` |
| `src/filesystem/lib.ts` | 982 | `a22dea03adb1dedc11ad188c6c00234c3246b7e65ebfe4c1f4104e4b2298fe19` |
| `src/filesystem/pinned-directory.ts` | 595 | `4d93dfa9b54ef8be3851efdfdb0ab0ae9b47b89f363b0afad5f9193a8087d129` |
| `src/filesystem/path-utils.ts` | 166 | `a49fdacfa37b75d852d93348fbaad62b463da3b27e1b43c5aed24fe45f64b64a` |
| `src/filesystem/path-validation.ts` | 106 | `aafed3c6e61f7474999dcdbaad50331261ae999adf8b383bf3ba2ec500745e65` |
| `src/filesystem/roots-utils.ts` | 114 | `4072b713d3b3b8cb75d2ddb7c45e909e73110d313f2e6aa11b380d89bf4e843b` |
| `src/filesystem/version.ts` | 39 | `e72b5868f3eb33ae2a68f01b46f8dc729f757cdfe6104e8b54053cd8ebb2dfba` |

The `.ts` files were read line by line (3,101 lines). The shipped `dist/*.js` were compared with them after Node.js's
own type stripping (`module.stripTypeScriptTypes`), with comments and whitespace removed: all eight are identical but
for what `tsc` itself writes differently (`(error as X).code` becomes `error.code`, `0o777n` becomes `511n`) - no code
exists only in the JavaScript. The repository tarball of the commit:
`sha256:f229c62ede67ee3f801ed81ad9efe4d04d6e2e4db4ea059038f665200068a604` (codeload.github.com). The package's
`README.md` (not loaded) was read for the documented behaviour.

**The MCP TypeScript SDK and zod:** the server imports `@modelcontextprotocol/server` (`McpServer`) and
`@modelcontextprotocol/server/stdio` (`serveStdio`, `StdioServerTransport`) and `zod` - the entry points servers/memory
imports, at the same integrities, so servers/memory's review (the SDK in full on its stdio path, the bundled Ajv and zod
4.6.7 on their risky surfaces) covers them. The static import closure of `dist/index.js` and of `entry.mjs` was computed
again (144 files; no `import()` - the one hit is a comment in zod -, `require` only in `version.js` for its own
`package.json` and in code strings of the SDK's never-instantiated Ajv provider): the SDK and zod files are
servers/memory's; the rest is the server and the four packages below. The SDK parts entry.mjs uses were read again for
this: `Server.listRoots` (`mcp-oHn3ureC.mjs` 1395-1401, every `roots/list` request goes through it, the legacy
input-required shim's included, 848), `oninitialized` (854, called from the `notifications/initialized` handler, 871)
and `setNotificationHandler` (`src-DdvbAHrR.mjs` 6915-6940), and `serveStdio` (`stdio.mjs` 286 ff.).

**diff 8.0.4** (BSD-3-Clause, 1,787 lines of `libesm`): the server calls only `createTwoFilesPatch`; that path read in
full (`patch/create.js`, `diff/line.js`, `diff/base.js`, `util/params.js`: Myers' O(ND) line diff, no timeout without
a callback); the other modules `index.js` loads (word, sentence, css, json, array diffs, patch parse/apply/reverse,
converters) searched for file, network, process, environment and code-loading calls - none (two `setTimeout`s, used
only with a callback).
**minimatch 10.2.6** (BlueOak-1.0.0, `dist/esm`, 2,165 lines in six files): `index.js`, `assert-valid-pattern.js`,
`escape.js`, `unescape.js` and `brace-expressions.js` read in full, `ast.js` (840) read in full on the glob-to-RegExp
path; it reads `process.env.__MINIMATCH_TESTING_PLATFORM__` once (platform override for its own tests; the server's
environment is fixed by the image) and builds `RegExp`s from the pattern; nothing else. **brace-expansion 5.0.12**
(MIT, 328) and **balanced-match 4.0.4** (MIT, 53) read in full: string processing only, bounded (100,000 expansions,
4,000,000 characters, nesting 1,000, 1,000 rewrites; CVE-2026-14257 fixed in this version).

**Telemetry, update checks, network:** none. The server imports only `fs`, `fs/promises`, `path`, `os` (`homedir()`
for `~`), `url`, `string_decoder`, `timers/promises`, `node:module` (to read its own `package.json`) and the packages
above; nothing reads the environment but minimatch's platform variable and Node's own `HOME`; nothing opens a socket,
spawns a process or loads code. stderr only: one start line, roots messages (never reached here) and transport errors.

## The two changes of entry.mjs

**1. The allowed directories are exactly the mounted folders.** Upstream takes them from its command line; here the
command line is the image's `ENTRYPOINT` (`/work /ref1 /ref2 /ref3`; sandbox-ai's `image_command` and its rootfs
entrypoint, and axross, add no arguments) and entry.mjs keeps only the targets `/proc/self/mountinfo` lists as mount
points (field 5, octal escapes decoded; absolute, normalized, never `/`). The image has the four as empty folders,
because the Bubblewrap form binds onto them; one nobody mounted is therefore not allowed (smoke: `/ref1` refused). None
mounted - only a start that just lists the tools, like CI's first one (sandbox-ai requires `/work`): the server runs
with no allowed directory and refuses every path (upstream's check admits nothing against an empty list); an unreadable
`/proc/self/mountinfo` stops it (exit 1). Upstream's `resolveAllowedDirectories` then normalizes them and adds a
target's realpath when it differs - a mount point's never does, and entry.mjs exits if the result holds anything but the
mounted targets. `list_allowed_directories` shows them (smoke: `Allowed directories:\n/work`).

**2. MCP Roots are never used.** In 2.1.0 the roots of a 2025-era client that declares the `roots` capability
**replace** the command-line directories (`server.ts` 830-855, `updateAllowedDirectoriesFromRoots`; `roots-utils.ts`
takes any existing directory, `file:///` included), after initialize and again on every
`notifications/roots/list_changed`. A client - or a prompt-injected agent's client configuration - could so widen the
server to the whole container (`/`, `/proc`, `/tmp`, the image). Checked locally with upstream's own entry: a client
answering `roots/list` with `file:///` got `Allowed directories: /` and read `/etc/hostname`. entry.mjs builds each
connection's server with upstream's `createServer` and then replaces `listRoots` with a refusal (every `roots/list` the
server could send goes through it), `oninitialized` with a no-op (no roots request after initialize) and the
`roots/list_changed` handler with a no-op. With the same client the image's entry sent no `roots/list` at all, and the
allowed directories stayed `/work` before and after a `roots/list_changed` (Tested). 2.2.0's `--confine-roots` would
only narrow; there is nothing a client should change here, so roots stay off after the re-pin as well.

Nothing else of upstream's is changed or patched: `createServer`, the tools and path validation run as shipped.

## Path safety (symlinks, path validation, TOCTOU)

How 2.1.0 decides (`lib.ts` 451-537, `validatePath`): `~` expanded (HOME=/tmp: outside), a Windows drive path refused
on POSIX, the path made absolute (`path.resolve`, so `..` is gone before any check; a relative path is resolved
against the first allowed directory), checked at a separator boundary against the allowed directories (NUL bytes
refused), then `realpath`'d (15 s bound) and the real path checked again; a path that does not exist is resolved
component by component from the allowed directory down (`resolveUnicodeEquivalentPath`: each existing component -
a dangling link too - `realpath`'d and checked, the missing tail appended to a checked real directory). The Unicode
(NFC/NFD, space separators) and letter-case respellings (`lib.ts` 208-349) only map a request onto an allowed
directory's own spelling, confirmed by `readdir`/`lstat` on a case-insensitive file system; on Linux they find
nothing to map and the request is refused as before. Every tool validates every path it takes;
`list_directory_with_sizes`, `search_files` and `directory_tree` validate each entry before they stat it or descend
(a `Dirent` from `readdir`, so a link is never descended), and `search_files`/`directory_tree` stop at 100,000
entries.

Writes (`pinned-directory.ts`): a new file is created with `O_CREAT|O_EXCL|O_NOFOLLOW` relative to its directory
after a `chdir` into it whose `getcwd()` must be the validated directory (so a directory swapped for a link between
the check and the write is detected, and nothing follows a link at the leaf); an existing file is `lstat`'d (a regular
file only), opened `O_RDWR|O_NOFOLLOW` the same way and must be the very inode `lstat` saw before it is truncated and
written; `create_directory` creates and enters each missing component relative to the previous one and checks where
it landed; `move_file` renames into the anchored destination directory (a source path swapped meanwhile can only move
an entry of the same mount: `rename` across mounts fails with `EXDEV`, and the cross-device copy anchors the source as
well). The `chdir` window is synchronous, so no other request runs while the working directory is borrowed.

| # | Severity | Where | What | Handling |
|---|---|---|---|---|
| 1 | medium upstream, low here | `server.ts` 257-281, 356-431; `lib.ts` 556-561, 828-925 (reads) | **Reads are not anchored (TOCTOU):** `read_text_file`, `read_multiple_files`, `read_media_file`, `edit_file`'s read, `list_directory`, `get_file_info` and `head`/`tail` open the validated path again by name. A folder swapped for a link to outside between the check and the open is followed. Reproduced locally: 3,000 reads of `d/passwd` while another process swapped `d` between a folder and a link to `/etc` - 409 returned `/etc/passwd`. The same race against 3,000 writes: 331 written inside, the rest refused, `/etc/passwd` untouched (run as root, so only the anchoring stopped it). A FIFO in the folder blocks the read that opens it | The race needs a second writer in the mounted folder: the host user, the agent through its own sandbox (the project folder is often the same), or this server's own `move_file` with a link to outside already in the folder. What a read can reach is the **container's** file system: the image's public files, `/proc` of the server (its environment holds `HOME` and `NODE_ENV` only), the empty `/tmp`, the other mounted folders - never the host's files (the container has only its mounts) and never a write. Fixed upstream in 2.3.0 (#5516); re-pin on 2026-11-25. Recorded in `server.json`'s notes |
| 2 | medium | `server.ts` 830-931 | **MCP Roots replace the allowed directories** (client-controlled widening, above) | entry.mjs: roots never requested, `roots/list_changed` ignored; tested |
| 3 | low | `lib.ts` 563-616, README | a write through a file with more hard links changes it at every name; the allowed-directory check is by path. A hard link into the folder can only be made by someone who reaches both names (the host user: the sandboxed agent cannot name a host file outside its mounts) | documented; `get_file_info` shows `hardLinks` |
| 4 | low | `lib.ts` 556-561, `server.ts` 134-147, 412-431 | no size limit: a whole file is read into memory (`read_media_file` also base64-encoded), `read_multiple_files` reads all at once; `edit_file` diffs the whole file (Myers without a time limit) | bounded by the container's 512 MiB; only the client hurts itself |
| 5 | low | `lib.ts` 927-982, `server.ts` 647-711 (minimatch) | `search_files`' `pattern` and `excludePatterns` go to minimatch for every entry: brace expansion up to 100,000 alternatives, extglob `RegExp`s that can backtrack. GHSA-g3hv-75wg-m249 (CVE-2026-118764, globparts amplification, 10.x) needs `optimizationLevel >= 2` (`minimatch/dist/esm/index.js` 332-341 `preprocess`, 652-655 `matchOne`); the server never sets it (default 1), so the advisory's path is not reached | CPU of the server's own container; the call's caller hurts itself. 2.2.0 moves to minimatch 11 |
| 6 | info | `lib.ts` 174-199 | a relative path is resolved against the first allowed directory (`/work`) | documented in the tools' behaviour |
| 7 | info | `lib.ts` 623-651 | `move_file`/`write_file`/`edit_file` act on a link's target when the link points inside (validatePath returns the real path); a link to outside cannot be moved, renamed or written through at all | stays inside the folders |
| 8 | info | `server.ts` 434-460 | `write_file` overwrites an existing file without a check (no read-before-write, unlike servers/files) | the reason servers/files exists for small models (README) |
| 9 | info | `pinned-directory.ts` 182-199 | the server `chdir`s for each write; a removed working directory falls back to `/` | synchronous, restored; nothing relative is used elsewhere |
| 10 | info | `server.ts` 156-180, 240-250 | a 2026-07-28-era client has no roots anyway; that era is served from the same factory | entry.mjs builds both eras the same way |

No backdoor, telemetry, update check, network access, process execution or code loading was found in the server,
entry.mjs, diff, minimatch, brace-expansion, balanced-match, the SDK or zod.

**No patches:** nothing of upstream's files is changed. Hardening is in the image: entry.mjs (the mounted folders
only, no roots), `node --disallow-code-generation-from-strings` (no `eval`/`new Function` in the process; zod falls
back to its interpreter, Ajv is never instantiated by this server), `NODE_ENV=production`, no npm in the image, no
Debian package added, uid 10001 (sandbox-ai's Podman run gives `--user=0:0` with a mount: root of the rootless user
namespace, that is you, with no capabilities), read-only root file system, `network: none`.

## Tools (`tools.json`, 14)

`read_text_file` (`head`/`tail` N lines) and `read_file` (deprecated alias), `read_media_file` (base64 image/audio
content, any other file as an embedded `resource` blob with a `file://` URI), `read_multiple_files` (failures per file),
`write_file`, `edit_file` (`edits` of `oldText`/`newText`, exact first, else whitespace-tolerant line match keeping
the file's indentation; CRLF kept; `dryRun`; answers a fenced git-style diff), `create_directory` (mkdir -p),
`list_directory`, `list_directory_with_sizes` (`sortBy` name/size), `directory_tree` (JSON; `excludePatterns`),
`move_file` (files and folders, never over an existing destination; across mounts a regular file only),
`search_files` (glob on names relative to `path`, `excludePatterns`), `get_file_info` (size, times, permissions,
`hardLinks`), `list_allowed_directories`. No prompt or resource.

## Network, data and files

- `network: none`: the container has no network namespace; the server would not use one anyway.
- Reads and writes only below the mounted folders (`/work` required, `/ref1`-`/ref3` optional; a folder mounted `:ro`
  makes every write to it fail with `EROFS`). The rest of the container is read-only but `/tmp`, which the server
  never uses. No cache, no log file; stderr: the start line naming the allowed folders, and transport errors.
- What runs at start: `node --disallow-code-generation-from-strings /opt/filesystem/entry.mjs /work /ref1 /ref2 /ref3`,
  which reads `/proc/self/mountinfo` and the server's own `package.json` (version) and serves stdio.

## Tested

- The smoke spec (`smoke.json`, 20 calls) through `scripts/smoke_test.py` with a stand-in for the container engine
  that ran the packages of the lock after the build's own removals and checks (the package list, the nine SHA-256),
  on Node.js 26.13 locally with `--disallow-code-generation-from-strings` and a cleared environment, through
  `entry.mjs`'s `main` with a mount table naming only the seeded folder, and the spec's `/work` replaced by that folder
  (no container engine here): `tools/list` equals `tools.json`; the allowed directories are the mounted folder only;
  created, written, edited (diff), read, searched, listed as a tree, moved, `get_file_info`; refused: a read through
  `escape` (a link to `/etc`), a write through it, a write through a link to `/etc/passwd`, a write to a dangling link,
  a move into `escape`, `/etc/passwd`, `/work/../../../../../../../../etc/passwd`, the unmounted `/ref1`, `~/.bashrc`, a
  move to `/tmp`, `copy_file` (no such tool in 2.1.0). Afterwards nothing new existed in `/etc` or `/tmp` and
  `/etc/passwd` was unchanged (the run was root, so only the server refused). The same with `--list-only` (no mount,
  as CI's first start): it started and listed the recorded tools, every path refused.
- By hand, the same way: a sibling folder sharing the prefix (`w-evil` for `w`, CVE-2025-53110), `../w-evil`, a link to
  it (CVE-2025-53109), `search_files` through that link, a NUL byte, `/proc/self/environ`, `read_multiple_files` with
  `/etc/shadow`, `create_directory`, `move_file`, `read_media_file`, `get_file_info` and `edit_file` through links to
  outside: all refused, nothing created outside. The read and write races of finding 1 (3,000 calls each).
- The real entry as the image runs it, against this sandbox's own mount table (`/work` is a mount point here, `/ref1`
  absent; read-only calls only): `Allowed directories: /work`; a client declaring `roots` was never sent `roots/list`,
  also not after `notifications/roots/list_changed`; `/etc/hostname` and `/` refused. Upstream's `dist/index.js` with
  the same client: widened to `/` (finding 2). `entry.mjs` with no mounted target (a folder that is no mount point, `/`,
  a `..` path, or none): `Allowed directories:` empty, `/work/README.md` and `/etc/hostname` refused.
- `tests/test_analysis_servers.py` (`Filesystem`): pins, the lock, the entry, roots off, the mounts and the smoke spec.
- CI: the image built, the smoke spec with the hardened run line (Node.js 24.22.1, a real `/work` mount), Trivy, then
  sandbox-ai's own Podman and Bubblewrap runs. Not built here (no container engine).

## Verdict

Reviewed completely (the server line by line against its source, entry.mjs, diff, minimatch, brace-expansion and
balanced-match on everything the server reaches, the SDK and zod by servers/memory's review of the identical files);
no backdoor or telemetry. Two findings that matter for sandbox-ai are handled by entry.mjs (allowed directories =
the mounted folders; roots off); the unanchored reads of 2.1.0 (finding 1) reach only the container's own files and
are fixed in 2.3.0, to be re-pinned from 2026-11-25. Fit to sign once CI has built it and both smoke reports pass.
