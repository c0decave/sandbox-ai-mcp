# memory - provenance and audit

| | |
|---|---|
| Upstream | the official MCP Knowledge Graph memory server, `@modelcontextprotocol/server-memory` **2.0.1** (modelcontextprotocol/servers `src/memory`; Apache-2.0, older contributions MIT: `LICENSES/modelcontextprotocol-servers-LICENSE.txt`), release `v2.2.0` of the repository, commit `194cc86e3ae6400958555bd4116849d822d69263` (2026-10-28) |
| In the image | the npm package of 2.0.1 (`dist/index.js`, `dist/version.js`, `package.json`; built by upstream CI from that commit, npm provenance), tarball `sha512-RbX5cm/OUbvBguVzHhJIqvG15b5K/bLODtQhHeQTkuM6XrijDtCFLl2THgLDg9JnS6pUBomNWq9n5G2bQwxD3A==` (SHA-256 `c8c164b0c60752a111b383a53f92a267bdacaf3fdc18415952808ba73aedd908`); the Dockerfile also checks `dist/index.js` and `dist/version.js` by SHA-256 |
| npm packages | `package-lock.json` (made with `npm install --package-lock-only --before=2026-10-29T00:00:00Z`; the same integrities as upstream's own lockfile at the commit): `@modelcontextprotocol/server` 2.4.0 (2026-10-23, `sha512-rgR9yxSa...`), `@modelcontextprotocol/core` 2.4.0 (2026-10-23, `sha512-z8QBKqdf...`), `zod` 4.6.7 (2026-10-12, `sha512-g8W2D2kU...`) - the server's only runtime dependencies; `npm ci --omit=dev --ignore-scripts`, nothing else in `node_modules` (the build checks the list and each version) |
| Node.js | 24.22.1, the `node` binary only, from `node:24-trixie-slim` `sha256:89c5244bc22a9bc3287d89ebc7e49b9cb5bb84cd40e6175ac3421d5a9f68b95a` as docker-library/repo-info recorded it on 2026-10-28 (commit `55f75407`; the image takes nodejs.org's release tarball checked against the release team's signed `SHASUMS256.txt`). npm, corepack and yarn of that image stay in the build stage |
| Base image | the `debian:trixie-slim` digest in `Dockerfile` (`sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad`); no Debian package is added |

**Upstream:** https://github.com/modelcontextprotocol/servers, the reference servers of the Model Context Protocol
project (created 2024-11-19, about 92,000 stars, active). The TypeScript servers are published to npm by the
repository's release workflow through npm trusted publishing (OIDC): the provenance attestation of 2.0.1 names the
workflow `.github/workflows/release.yml` at `refs/tags/v2.2.0`, commit `194cc86e`. Upstream's own `src/memory/Dockerfile`
(unpinned `node:24-alpine`, `npm install`) is not used.

**Pinning rule:** 2.0.1 (npm 2026-10-28 21:07 UTC, repository release v2.2.0 of 20:57 UTC) is the newest release
published on or before 2026-10-28. Too new: **2.1.0** (2026-11-04: read modes for `read_graph`/`search_nodes`/
`open_nodes`, an observation repeated in one `add_observations` call stored once, `idempotentHint` on the create
tools, a warning when the memory file is inside `node_modules`) and **2.1.1** (2026-11-11: descriptions for every
input property, "when to use" texts, the lock heartbeat no longer refreshing a lock it no longer owns, Docker images
built from the lockfile and run as a non-root user). None is a security fix; the heartbeat fix matters only when
several connections share one folder and a write outlasts 30 s. Re-pin to 2.1.x from 2026-11-18/2026-11-25. Every
npm package of the lock was published before 2026-10-24.

**Node.js:** the package requires Node.js 24 (`engines`); Debian trixie has 20. Node.js 24.22.1 is the October
2026 security release line; the image is the one Docker Hub served on 2026-10-28.

## What was reviewed

**The server, in full** (all of what runs of it):

| File | Lines | SHA-256 |
|---|---|---|
| `dist/index.js` (npm 2.0.1) | 999 | `779ae2294db562c14dfc347555f6ff5fa0bce87e00377c401ccb2df642928450` |
| `dist/version.js` (npm 2.0.1) | 26 | `a65814e1815264d0a88c697ec9fd678e43168329cd722d8093e53172eae6e73f` |
| `package.json` (npm 2.0.1) | 48 | `541290abb03bb020da0895535a641cb604e5454b1f5b599e02c40c02cb01f94c` |
| `src/memory/index.ts` (commit `194cc86e`) | 1280 | `cf24a82597ffa540d0176a074754edec2f499a49c101fd349fb69337e4db3fa6` |
| `src/memory/version.ts` (commit `194cc86e`) | 31 | `91188b64cd410bff18962828daa8ea4672ad308ebf1ab4e35330cc645a27dfbe` |

`index.ts` and `version.ts` were read line by line; the shipped `dist/*.js` were compared with them line by line
(`diff -w`: every line of `index.js` is either a line of `index.ts` or the same statement without its type
annotations, re-wrapped; no line of code exists only in the JavaScript).

**The MCP TypeScript SDK, in full on the path the server uses** (the static import closure of `dist/index.js`,
computed and checked; no dynamic `import()` anywhere in it; package `exports` resolved for `node`+`import`):

| File | Lines | SHA-256 |
|---|---|---|
| server `dist/stdio.mjs` | 589 | `892fcad4d0e0c7fa11a88dd769353e298b6d2b445ad833790d16b063e199b10d` |
| server `dist/index.mjs` | 1577 | `ab7434003c94a09e2c7dec6765647ed600104ad4ebcd347f574dab94f52fcf8d` |
| server `dist/mcp-oHn3ureC.mjs` | 2165 | `c542c2e9e84767827ca9ac561946ec25a7f10b9aa48e84acca12f48bf1123ea2` |
| server `dist/src-DdvbAHrR.mjs` | 7712 | `f4d33527f049feccb3183d749039072deaa21528b6ba85d05e3a5fa68b2060ad` |
| server `dist/listenRouter-Bartj63y.mjs` | 425 | `b7acfe626bff3edc2eb1a11c4ad9a1c07225b0df89be9ab5280af207e88e690a` |
| server `dist/chunk-vYduTEsO.mjs` | 41 | `d4a000980e7c6a8a2ee04c12d80cf538b11e5040e8487dad7661b09d85894e74` |
| server `dist/dialects-CDpMbily.mjs` | 33 | `9f87722e2b700a170ea4de4c88719df0ab321fa84e9f4fcf666bec3d5cb04c38` |
| server `dist/shimsNode.mjs` | 3 | `374289ae3f0d17734a08aa9ea60730a0b023d1430eab01cb057b04a7d5a83881` |
| core `dist/internal.mjs` | 3 | `c2ce2d072c43d3b8be0ce76642f7d5c19f98127ff705dac566a84fae331f6341` |
| core `dist/auth-UMQCo-ad.mjs` | 208 | `6ea7a63dfceca17fd7ab5325947bcd4d4602b5c40f2736d406de69d906559db8` |
| core `dist/schemas-DscsoNZN.mjs` | 1475 | `e4419e9d2c8059c512b28e57d4dbdf4daee773ecfce698c389585a0cbea2fd73` |
| server, core, zod `package.json` | 185, 97, 147 | `c82767fb...`, `b98e66c5...`, `c2d190d9...` |

**Risky surfaces only:** the bundled Ajv of the SDK (`dist/ajvProvider-DyjnscPj.mjs`, 8,009 lines,
`944297315b903b46248bd29fe0590ba52c91fdc1bd91ff6853a77bedf7b09c64`; searched for code generation, network, files,
environment, dynamic loading; lines 2560-2620 and 7474-8009 read in full) and the 97 files of zod 4.6.7 the server
loads (`index.js`, `v4/index.js`, 12 of `v4/classic`, 19 of `v4/core`, 64 locales; 20,080 lines; the same search,
`doc.js` and `errors.js` and the code around every hit read in full). Install scripts: none in the SDK packages or
zod (`prepublishOnly` and build scripts only); the server's `prepare` is not run for a registry tarball, and
`npm ci --ignore-scripts` runs nothing anyway.

## Findings

No backdoor, telemetry, update check, network access, process execution or code loading was found in the server,
the SDK or zod. The SDK, core, Ajv and zod do not import `fs`, `child_process`, `net`, `http`, `dns` or read the
environment; only the server's own two files touch the file system.

| Severity | Where | What | Handling |
|---|---|---|---|
| low | server `index.ts` 49-59 | `MEMORY_FILE_PATH` decides the graph file; unset, it is `memory.jsonl` next to the package (read-only in the image). No tool takes a path | the image sets `MEMORY_FILE_PATH=/data/memory.jsonl`; the entry offers no variable, so a definition cannot change it |
| low | server 392-575 | every call reads the whole file and every write rewrites it (through a random temporary file in the same folder, renamed over it, with `memory.jsonl.lock` held); no size limit on entities, observations or the file; `read_graph` returns all of it | bounded by the container's memory (512m) and the folder; notes tell users to use `search_nodes`/`open_nodes` on large cases |
| low | SDK `listenRouter` 97, 128, 333-358 | a 2026-07-28-era client can hold up to 1,024 listen subscriptions, each a copy of its own resource list (each message at most 10 MiB) | memory limit of the container; only the client hurts itself |
| info | server 176-194 | a stale lock's owner is checked with `process.kill(pid, 0)` (signal 0: existence only) when the lock names this host | harmless; in a container the host name is the container's |
| info | server 260-344 | lock and temporary files live beside the graph: `memory.jsonl.lock`, `memory.jsonl.lock.break`, `memory.jsonl.<32 hex>.tmp` | all in `/data` |
| info | server 401-472 | lines that cannot be parsed are kept and written back unchanged; extra fields of a record are kept (never `type`, never a modelled field) | no prototype pollution: extras go through `Object.fromEntries` into a WeakMap |
| info | SDK `src` 6980-6986 | `inputResponses` keys of a modern client can set the prototype of one local object (`__proto__`) | the server never reads `inputResponses` |
| info | SDK `src` 7187-7200, `stdio.mjs` 80-88 | malformed lines are dropped without an answer; a line over 10 MiB closes the transport | fine for stdio |
| info | zod `v4/core/doc.js` 32-37 | zod compiles object parsers with `new Function` from the server's own schema keys (never from input) | `node --disallow-code-generation-from-strings`: zod falls back to its interpreter; Ajv (`new Function`, line 2594) is never instantiated by this server (only elicitation and `fromJsonSchema` would) |
| info | SDK package `exports` | `--conditions=browser`/`workerd` would load other shims | the entrypoint is fixed and `NODE_OPTIONS` is not set |
| info | content | what is stored was often read from untrusted sources and comes back verbatim | entry notes: data, not instructions |

**No patches:** nothing had to change in the server or its packages. Hardening is in the run line: `node
--disallow-code-generation-from-strings` (no `eval`/`new Function` in the process), `NODE_ENV=production`,
`MEMORY_FILE_PATH` fixed, no npm in the image.

## Tools (`tools.json`, 9)

`create_entities`, `create_relations`, `add_observations`, `delete_entities`, `delete_observations`,
`delete_relations` (write), `read_graph`, `search_nodes` (case-insensitive substring of names, types and
observations; query at most 2,048 characters), `open_nodes` (read). Also one resource,
`memory://knowledge-graph` (the whole graph, subscribable). No tool takes a file path; nothing is downloaded, no
cloud or project tool exists.

## Network, data and files

- `network: none`: the container has no network namespace; the server would not use one anyway.
- Data: `/data/memory.jsonl` in the folder mounted writable (`--mount /data=DIR:rw`, required), one JSON object per
  line (`{"type":"entity","name":...,"entityType":...,"observations":[...]}`, `{"type":"relation","from":...,
  "to":...,"relationType":...}`). One folder per case: `--mount /data=~/brains/CASE:rw`.
- Without a mount `/data` is part of the read-only root: the server starts and lists its tools, every write fails
  with `EROFS`.
- The server writes nothing else: no cache, no log file (stderr only: `Knowledge Graph MCP Server running on stdio`
  and errors).

## Tested

- The smoke spec (`smoke.json`) through `scripts/smoke_test.py` with a stand-in for the container engine that ran
  the reviewed packages on Node.js 26.13 locally (`--disallow-code-generation-from-strings`, cleared environment, the
  run's fresh folder as `/data`): `tools/list` equals `tools.json`; create two entities, a relation and an
  observation, search (`tallinn` finds the entity written with "Tallinn"), open, read the graph back; refused: a
  relation to an unknown entity, a 2,049-character query, `read_file` and `delete_project` (no such tools). Also
  `--list-only`, and a write without a writable folder (refused with `ENOENT`/`EROFS`). Not built here (no container
  engine).
- `tests/test_analysis_servers.py` (`Memory`): pins, the lock, the entry and the smoke spec.
- CI: the image built, the smoke spec with the hardened run line (Node.js 24.22.1), Trivy, then sandbox-ai's own
  Podman and Bubblewrap runs.

## Verdict

Reviewed completely (the server line by line, the SDK on its whole path, zod and Ajv on their risky surfaces); no
patch needed. Ready for CI; sign once both smoke reports pass.
