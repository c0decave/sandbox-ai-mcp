# sequential-thinking - provenance and audit

| | |
|---|---|
| Upstream | the official MCP sequential-thinking server, `@modelcontextprotocol/server-sequential-thinking` **2.0.0** (modelcontextprotocol/servers `src/sequentialthinking`; Apache-2.0, older contributions MIT: `LICENSES/modelcontextprotocol-servers-LICENSE.txt`, the same file as servers/memory's), tag `v2.0.0` of the repository, commit `51b6382a3e827aceb6bce430b1208d69b93d95ea` (npm 2026-10-19 06:51 UTC) |
| In the image | the npm package of 2.0.0 (`dist/index.js`, `dist/lib.js`, `dist/version.js`, `package.json`; built by upstream CI from that commit: the npm provenance attestation names `.github/workflows/release.yml` at `refs/tags/v2.0.0`, commit `51b6382a`), tarball `sha512-LAljkLByTHuOOPoQHAGNX5EiUJAvYuuTG7yEvdK5pRg7s7oxchNh8LwSkcuW3Y8bvQk4uZgjbjH3x7rNKpJ3Iw==` (SHA-256 `16abc08487e9bf78a7a11e9fbd5473dc9121eb70a6c811c6be375f931856b057`); the Dockerfile also checks the three `dist/*.js` by SHA-256 |
| npm packages | `package-lock.json` (made with `npm install --package-lock-only --ignore-scripts --before=2026-11-01T00:00:00Z`): `@modelcontextprotocol/server` 2.4.0 (2026-10-23, `sha512-rgR9yxSa...`), `@modelcontextprotocol/core` 2.4.0 (2026-10-23, `sha512-z8QBKqdf...`), `zod` 4.6.7 (2026-10-12, `sha512-g8W2D2kU...`) - the same integrities as servers/memory's lock, so the same files - and `chalk` 5.6.2 (2025-09-08, `sha512-7NzBL0rN...`; never 5.6.1, the release of 2025-09-08 npm pulled as compromised). `yargs` 17.7.3 (2026-06-19) and the eleven packages only it needs are in the lock because 2.0.0 declares yargs, but nothing imports it: the build deletes them after `npm ci --omit=dev --ignore-scripts` and checks that only `@modelcontextprotocol/{core,server,server-sequential-thinking}`, `chalk` and `zod` are left, each at its version |
| Node.js | 24.22.1, the `node` binary only, from `node:24-trixie-slim` `sha256:89c5244bc22a9bc3287d89ebc7e49b9cb5bb84cd40e6175ac3421d5a9f68b95a` as docker-library/repo-info recorded it on 2026-10-28 (commit `55f75407`), the image of servers/memory. The package requires Node.js 24 (`engines`); npm, corepack and yarn of that image stay in the build stage |
| Base image | the `debian:trixie-slim` digest in `Dockerfile` (`sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad`); no Debian package is added |

**Upstream:** https://github.com/modelcontextprotocol/servers, the reference servers of the Model Context Protocol
project (see servers/memory's PROVENANCE.md). Upstream's own `src/sequentialthinking/Dockerfile` (unpinned
`node:24-alpine`, `npm install`) is not used.

**Pinning rule:** prepared on 2026-11-14, cut-off 2026-10-31. 2.0.0 (2026-10-19) is the newest release published on or
before it. Too new: **2.1.1** (2026-11-04, old enough on **2026-11-18**): drops the unused `yargs` dependency, caps
the history at 1,000 thoughts per connection (`MAX_THOUGHT_HISTORY`), caps the stderr box at 100 columns and 1,000
rows (#5433: a long thought logged many times its own size), and shortens the tool description to 1,024 characters.
None is a security fix for this image: the box is never drawn here (thought logging is off, below) and the history
lives only as long as one connection, inside the container's 512 MiB. Re-pin to 2.1.1 from 2026-11-18 (the same
review, plus its `lib.js` diff). Every npm package of the lock was published before 2026-10-24.

## What was reviewed

**The server, in full** (all of what runs of it):

| File | Lines | SHA-256 |
|---|---|---|
| `dist/index.js` (npm 2.0.0) | 205 | `209921bc90eaaedb484ddd75471452ecc254086bcb0ffda395a99619332760b3` |
| `dist/lib.js` (npm 2.0.0) | 107 | `dd1a882a435cd672b0da9a407a0445a4dcf53fa4374572eb5d79815b5ccd56e2` |
| `dist/version.js` (npm 2.0.0) | 30 | `ae5a797a13cbc960f2303f2af3b2429135694875547e2dfb3b9700e4f8e10f19` |
| `package.json` (npm 2.0.0) | 51 | `96720db91c691efcaa68a01a3c7bdad2af04eafcbbe75887165a7fc10c41ebe0` |
| `src/sequentialthinking/index.ts` (commit `51b6382a`) | 229 | `91ccd44119dd6de7adcde9728db6ca6f3a599e7d2eea661081fc414f35d67f6a` |
| `src/sequentialthinking/lib.ts` (commit `51b6382a`) | 149 | `0c2b906460971a1f654d364ed8f5d69f96d15b6b121dfe101dedb425db8bc8e0` |
| `src/sequentialthinking/version.ts` (commit `51b6382a`) | 33 | `2eb05e2e2984f6c77d7d4b3289bfd087f2fc67b51c9c12b5423fb6637240deb9` |

The `.ts` files were read line by line; the shipped `dist/*.js` were compared with them after Node.js's own type
stripping (`module.stripTypeScriptTypes`) and whitespace normalisation: the only differences are line wrapping and
`} catch` placement - no line of code exists only in the JavaScript. The repository tarball of the commit:
`sha256:d6f69230be5aeba3500ee4f435c0638f037fd5c6d22bd80cfe5cfa9846ef0a69` (codeload.github.com).

**The MCP TypeScript SDK and zod:** the server imports `@modelcontextprotocol/server` and `/server/stdio` and `zod` -
the same entry points servers/memory imports, and the same files by SHA-256 (all eleven SDK and core files of
servers/memory's table were hashed again here and are identical: `stdio.mjs` `892fcad4...`, `index.mjs` `ab743400...`,
`mcp-oHn3ureC.mjs` `c542c2e9...`, `src-DdvbAHrR.mjs` `f4d33527...`, `listenRouter-Bartj63y.mjs` `b7acfe62...`,
`chunk-vYduTEsO.mjs` `d4a00098...`, `dialects-CDpMbily.mjs` `9f87722e...`, `shimsNode.mjs` `374289ae...`, core
`internal.mjs` `c2ce2d07...`, `auth-UMQCo-ad.mjs` `6ea7a63d...`, `schemas-DscsoNZN.mjs` `e4419e9d...`). That review
(the SDK in full on its stdio path, the bundled Ajv and zod 4.6.7 on their risky surfaces) is reused, not repeated.
The static import closure of `dist/index.js` was computed again (116 files, no import with a computed name): it is
servers/memory's closure plus chalk's three files.

**chalk 5.6.2, in full** (641 lines): `source/index.js` (226, `64b22b1c442e6d460069807b521bf0a84e112c00c2b4163bc59deab20a9292db`),
`source/utilities.js` (`698ce3cb21b00b570631742d3a9e168de31df74b3a88220c4bcf18ac30fd00cd`), `source/vendor/ansi-styles/index.js`
(224, `92efdc3e5203d02d1710ff60dea3965066f97a77c0feaaa919b2693c989b7ec1`), `source/vendor/supports-color/index.js`
(191, `e82368a5f05d145e33de6ae3464056511664b620735ef58d1800a7bcda6691e5`). It imports `node:process`, `node:os`
(`os.release()` on Windows only) and `node:tty` (`isatty(1)`, `isatty(2)`), reads `process.argv` and colour variables
(`FORCE_COLOR`, `TERM`, `CI`, ...) and builds ANSI escape strings; no file, network, process or code-loading call.
Install scripts: none in chalk, zod or the SDK; `npm ci --ignore-scripts` runs nothing anyway.

## Findings

No backdoor, telemetry, update check, network access, file access, process execution or code loading was found in the
server, chalk, the SDK or zod.

| Severity | Where | What | Handling |
|---|---|---|---|
| low | `lib.ts` 27-82, 98-101 (`formatThought`, `processThought`) | unless `DISABLE_THOUGHT_LOGGING=true`, every thought is drawn as a box on stderr: the thought text on one row padded to its own length and two borders as long, about three times its size in memory and in sandbox-ai's logs, for every call | the image sets `DISABLE_THOUGHT_LOGGING=true`; the entry offers no variable to undo it. `formatThought` is then never called (the check on line 98 comes first) |
| low | `lib.ts` 16-19, 103-110 | the history and branches grow without a cap for as long as one connection lasts (2.1.1 caps them at 1,000); each message is at most 10 MiB (the SDK's stdio cap) | one connection only, inside the container's 512 MiB; only the client hurts itself |
| info | `index.ts` 26-37 | a string `nextThoughtNeeded` other than true/false is refused with a message that quotes it | echoes the caller's own value |
| info | `lib.ts` 19, 105-109 | branches live in a null-prototype object: `branchId` `__proto__` or `constructor` is an ordinary key | checked in the smoke run (`__proto__` listed as a branch) |
| info | `package.json` | `yargs` ^17.7.2 is declared and imported nowhere | removed from the image with the packages only it needs |
| info | content | the thoughts are the model's own text and come back only as counts | nothing of them is returned or stored beyond the connection |

**No patches:** nothing had to change in the server or its packages. Hardening is in the image: `node
--disallow-code-generation-from-strings` (no `eval`/`new Function` in the process; zod falls back to its interpreter,
Ajv is never instantiated by this server), `NODE_ENV=production`, `DISABLE_THOUGHT_LOGGING=true`, no npm in the image,
no Debian package added, uid 10001.

## Tools (`tools.json`, 1)

`sequentialthinking`: `thought` (string), `thoughtNumber`, `totalThoughts` (integers >= 1, numeric strings coerced),
`nextThoughtNeeded` (boolean or "true"/"false"), optional `isRevision`, `revisesThought`, `branchFromThought`,
`branchId`, `needsMoreThoughts`. It answers with `thoughtNumber`, `totalThoughts` (raised to `thoughtNumber` when
that is larger), `nextThoughtNeeded`, the branch ids and the length of the history, as text and as structured
content. No other tool, prompt or resource.

## Network, data and files

- `network: none`: the container has no network namespace; the server would not use one anyway.
- Nothing is read or written: no mount, no cache, no log file. stderr carries one line at start
  (`Sequential Thinking MCP Server running on stdio`) and transport errors.
- What runs at start: `node --disallow-code-generation-from-strings dist/index.js`, which reads its own
  `package.json` for the version (`version.js`) and serves stdio; one `SequentialThinkingServer` per connection.

## Tested

- The smoke spec (`smoke.json`) through `scripts/smoke_test.py` with a stand-in for the container engine that ran the
  packages of the lock, after the build's own removal and checks (the package list, the three SHA-256), on Node.js 26.13
  locally with `--disallow-code-generation-from-strings`, a cleared environment and `DISABLE_THOUGHT_LOGGING=true`:
  `tools/list` equals `tools.json`; a thought, a revision and a branch named `__proto__` counted; refused: thought
  number 0, `nextThoughtNeeded` "maybe", `read_file` (no such tool); stderr held only the start line. Not built here (no
  container engine).
- `tests/test_analysis_servers.py` (`SequentialThinking`): pins, the lock, the entry and the smoke spec.
- CI: the image built, the smoke spec with the hardened run line (Node.js 24.22.1), Trivy, then sandbox-ai's own
  Podman and Bubblewrap runs.

## Verdict

Reviewed completely (the server line by line against its source, chalk in full, the SDK and zod by servers/memory's
review of the identical files); no patch needed, thought logging off. Fit to sign once CI has built it and both smoke
reports pass.

## Review of 2026-11-17 (group C)

Run here (Node.js 26, the lock's packages, the dist files' SHA-256 checked): the smoke spec through a stand-in engine
(ok); tools only (no resources or prompts capability); the schema valid (draft 2020-12 and 7); answers are counts,
a few hundred characters. Nothing changed; the history cap of 2.1.1 comes with the planned re-pin.
