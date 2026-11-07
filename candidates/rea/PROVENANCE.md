# rea (prepared) - provenance and audit notes

| | |
|---|---|
| MCP server | morluto/rea 6.8.0 = npm `rea-agents` (MIT), tag `rea-agents-6.8.0`, commit `160d821ac9a0310afcb8d1fc427862dd6508add5` (2026-10-25), built from the commit (`npm ci` from its `package-lock.json`, integrity hashes, then `npm run compile`) |
| Node.js | official nodejs.org build, version and SHA-256 to pin (needs `^22.23.4 \|\| ^24.22.1 \|\| >=26.12.1`; Debian trixie has 20.19) |
| Debian | `git` `1:2.47.3-0+deb13u1`, `xz-utils` `5.8.1-1+deb13u2` (build stage), `procps` `2:4.0.4-9`, `tini` `0.19.0-3+b8` (trixie / trixie-security indexes of 2026-11-05) |

**Re-pin before building:** 2026-11-08 or an older release. `rea-agents` 6.8.0 (commit `160d821a`) was published 2026-10-25 and is too new under the pinning rule (`docs/CANDIDATES.md`) until 2026-11-08; the Node.js release still to be pinned must also be at least 14 days old. An older release needs its own audit.

**State:** not built. nodejs.org was not reachable where this was prepared, so
`NODE_VERSION`/`NODE_SHA256` are open and the Dockerfile refuses to build until they are set.
The upstream build (`npm run compile`: tsc, catalog recording, runtime bundling) has not been
run here. The GitHub release has no assets.

**What it is:** one MCP server (stdio; `rea mcp --http` serves streamable HTTP) over a large
reverse-engineering toolkit: native binaries through Hopper, Ghidra or IDA, JavaScript and
Electron applications, .NET, Android (ADB, JADX, apktool, JEB), Frida, GDB, Rizin/Cutter,
websites through a Chrome-family browser, HAR/pcap captures, firmware (binwalk/unblob),
WASM, SQLite, Python bytecode. Each provider needs its engine on `PATH` and reports itself
unavailable otherwise (`binary_session` lists availability). This image ships **no** engine:
what should work is the analysis written in TypeScript (JavaScript/Electron/ASAR and web
bundles in their own Node workers, the Go, Rust, Python-bytecode and .NET metadata readers
in `src/go`, `src/rust`, `src/python`, `src/dotnet` that spawn nothing, SQLite through
`node:sqlite`, evidence bundles). Which tools actually answer without engines is to be seen
from the built image's `binary_session`; WASM needs wabt, ILSpy and objdump need their CLIs. Engines (Ghidra from the ghidra candidate, binutils, rizin) could be added later,
each with its own pins.

**Tools:** about 230 names are declared with their effects in `src/contracts/toolEffects.ts`
(152 have contract files with descriptions in `src/contracts/`). Each carries flags
(`readOnly`, `writesFilesystem`, `launchesProcess`, `accessesNetwork`,
`executesForeignCode`), reported by `binary_session`.

- **Execute foreign code** (`executesForeignCode`): capture_process_scenario,
  capture_electron_scenario, capture_browser_scenario, capture_native_ui_scenario,
  observe_native_calls, execute_rizin_command, cutter_command, start_rizin_debug_session,
  rizin_debug_command, gdb_console (an unrestricted GDB command), instrument_with_frida,
  load_frida_script, resume_frida_session and their close_* tools. Most need engines the
  image does not have; `capture_process_scenario` and `capture_electron_scenario` can launch a
  mounted program, i.e. run the sample inside the container. The container is the boundary
  (no network, read-only root, `/work` read-only).
- **Network** (`accessesNetwork`): the ADB, Frida, JEB, browser/web and Inspector tools
  (devices, loopback debug endpoints, web pages); source maps of web bundles are fetched by
  `src/browser/WebSourceMapFetcher.ts`. Without network they fail. Hopper's download
  (`src/application/HopperDownload.ts`) belongs to `rea setup`, not to the server.
- **Files:** the analyses take absolute paths and read whatever the container can see
  (`/work`); extraction, evidence export and environment bundles write into fresh temporary
  directories or a caller-given absent directory (writable only in `/tmp` and `/out`).

No telemetry or update check was found in `src/` (no analytics hosts; the `https://` hosts
in non-test sources are documentation links, `github.com` release references and
`127.0.0.1`).

**To check when building:** the compile step in a clean container, that `npm prune
--omit=dev` keeps what `dist/` needs, the `/tmp` tmpfs size (64 MiB; JavaScript analysis
workers and extraction write there; `/out` may be better), memory (analysis workers;
start with `--memory=2g`), the tools/list for `tools.json` (and which tools report
themselves unavailable), whether `capture_process_scenario` should be disabled for this
image.

**Mounts:** `/work` (samples, read-only), optionally `/out` (writable).

**Network:** none.
