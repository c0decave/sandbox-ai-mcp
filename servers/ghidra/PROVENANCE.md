# ghidra - provenance and audit

| | |
|---|---|
| MCP server | this repository: `src/server.py` (Python, the MCP SDK) and `src/GhidraBridge.java` (the JVM half, on Ghidra's headless API), MIT (`LICENSES/`), written for this repository and reviewed in full by construction (below) |
| Tool | Ghidra **12.2** (NationalSecurityAgency/ghidra, Apache-2.0, `LICENSES/ghidra-Apache-2.0.txt`; its bundled libraries' licences ship in `/opt/ghidra/licenses`, the GNU demangler's GPL in `/opt/ghidra/GPL`): tag `Ghidra_12.2_build`, release published 2026-10-22 08:31 UTC (34 days before this review; the newest release), build revision `8ca9077040cc43cd790babcfccf19475622a3e9a` (`application.properties`) |
| Release asset | `ghidra_12.2_PUBLIC_20261016.zip`, 569,712,708 bytes, SHA-256 `2c2cd776db3c1f6a097ba418922378ac3649cadd5e844a6f5f088ae628a7be67` (the digest GitHub publishes for the asset; `ADD --checksum` in the build stage) |
| Java | Eclipse Temurin **25.0.5+8** (GPL-2.0 with Classpath Exception; `/opt/java/legal`), released 2026-10-22: the JRE `OpenJDK25U-jre_x64_linux_hotspot_25.0.5_8.tar.gz`, SHA-256 `6fac98f0c8202efc3135a9e9e42aa61963ec42d1c5cbb40caf231e7b14a24ef6` (servers/signal's JRE) runs it; the JDK of the same release (`OpenJDK25U-jdk_x64_linux_hotspot_25.0.5_8.tar.gz`, SHA-256 `68982529869257d0ee6b824ec5aa270ff8b118bb438670da0b97ebdab178d7fb`) compiles the bridge in the build stage and does not ship. Ghidra 12.2 needs Java 25 (`application.java.min=25`); Debian trixie has no Java 25 |
| Python packages | `mcp==1.30.0` and its dependencies, hash-locked in `requirements.txt` (byte-identical to servers/jadx's, reviewed there) |
| Debian packages | `tini=0.19.0-3+b8` (the init of the ENTRYPOINT), `python3=3.13.5-1`, `python3-venv=3.13.5-1` (purged after the venv is made), `ca-certificates=20250419+deb13u1` (pip's download while building), `libstdc++6=14.2.0-19` (Ghidra's native decompiler and demangler are C++); build stage only: `unzip=6.0-29+deb13u1` |
| Base image | the `debian:trixie-slim` digest in `Dockerfile` (the same as web-fetch's) |
| Network | none |

**Pinning rule:** Ghidra 12.2 and Temurin 25.0.5+8 are both of 2026-10-22, 34 days before 2026-11-25 (the cut-off is
2026-11-11). Temurin 25.0.5.1+2 (2026-11-18) is too new. No new Python package.

## Why an own server, and not pyghidra-mcp

The candidate of round 1 (`clearbluejar/pyghidra-mcp` 0.3.0, prepared in `candidates/ghidra` until this review) was not
admitted (docs/CANDIDATES.md, 2026-11-17): its lock of 101 Python packages - chromadb with its Rust core,
onnxruntime, huggingface-hub (which downloads an embedding model at first use), grpcio, kubernetes, the OpenTelemetry
exporters - is not reviewable completely, and it offers write tools (rename, set types, save, delete). The two reasons
are addressed by not using it at all: this server drives Ghidra's own Java API through a small JVM program of ours
(as servers/jadx does with jadx's library), offers only reads, and adds no third-party code besides Ghidra and the JRE.
The candidate folder is removed.

## Ghidra 12.2 (2026-11-25) - reviewed on what it can do at run time

Ghidra is NSA's reverse-engineering suite: 2,557,934 lines of Java in the 82 source archives the release ships
(`lib/*-src.zip` of every module) plus the C++ decompiler (`Ghidra/Features/Decompiler/src/decompile`, shipped as the
native `decompile` and `sleigh` programs). It cannot be read line by line here; like jadx (servers/jadx), the browsers
of playwright and the language servers of lsp-python/lsp-go, it was reviewed on what it can do at run time - network,
processes, files, dynamic code, telemetry and update checks - with its source archives searched in full for each, and
then run here under this server (below). What does not ship cannot do anything: the build stage deletes
`Ghidra/Debug` (the debugger: agents that start gdb, lldb and WinDbg, the trace RMI sockets, JDWP), the Ghidra Server
(`Features/GhidraServer`, `server/`), BSim (its PostgreSQL and Elasticsearch clients), PyGhidra (the JPype bridge),
GhidraGo (`ghidra://` URL handling), the optional extensions (`Extensions/`, not installed), the documentation, the
Docker files and every Windows and macOS binary. What stays: the framework, `Features/Base` and the analysis modules
(Decompiler, FileFormats, the demanglers, PDB, FunctionID with its databases, Swift, Rust, Objective-C, ...), the
processor specifications (`Ghidra/Processors`, the compiled `.sla` files).

| Concern | What the source shows | Here |
|---|---|---|
| Network | clients in what ships: `ghidra.net.HttpClients` (Java's HttpClient), used by the PDB analyzer's `HttpSymbolServer` and DWARF's `HttpDebugInfoDProvider` (debuginfod) - both only for locations the user configures in the GUI's dialogs (`ExternalDebugFilesService.getDefault()`: the same folder and a local cache; no symbol server by default; `DEBUGINFOD_URLS` is read only by a GUI dialog); the LibreTranslate string translator and the Eclipse/VS Code connectors (GUI plugins, a user's action); the project classes' Ghidra Server client (RMI) - no project is opened | the container has **no network** (`network: none`); the bridge opens no project and configures no symbol server or debuginfod URL; the JVM gets an empty environment |
| Processes | started by what ships, headless: the decompiler (`os/linux_x86_64/decompile`, one process per `DecompInterface`) and the GNU demangler (`GPL/DemanglerGnu/os/linux_x86_64/demangler_gnu_v2_41`, by the demangler analyzer) - native programs of the release; `lzfse` (FileFormats, an Apple container format) only when such a file system is opened; the Swift demangler only if `swift-demangle` exists (it does not); the DMG server's helper (`GPL/DMG`, deleted); browser, VS Code, Eclipse, the taint tool and the certificate manager are GUI actions | seen while the smoke spec ran (sampled with `ps`): `decompile` and `demangler_gnu_v2_41`, nothing else; the bridge starts nothing itself (a test holds `ProcessBuilder` and `Runtime.exec` out of it) |
| Files | Ghidra writes its settings (`preferences`, `application.log`, `script.log`) to the user settings folder, its packed-database cache to `/var/tmp/<user>-ghidra` by default, temporary program databases below `java.io.tmpdir`; it reads its own installation and the input | `application.settingsdir`, `application.cachedir`, `application.tempdir`, `java.io.tmpdir` and `user.home` all point into the scratch folder of the open file (`/tmp/ghidra-mcp/<random>`, removed with the JVM); run here, nothing was written anywhere else (checked: `/var/tmp`, the home folder). The input is the descriptor the server opened (a link to `/proc/self/fd/N`): Ghidra reads exactly the checked file. The installation is root-owned and read-only |
| Dynamic code | Ghidra's class path: its modules' jars, the `Ghidra/patch` folder (a README only), the application's and the user's `Extensions` folders, external modules named by `ghidra.external.modules`; GhidraScripts (Java compiled at run time, OSGi bundles) only when a script is run | the application's `Extensions` is deleted, the user's is in the empty scratch folder; `ghidra.external.modules` names only this server's module (`/opt/mcp/ghidra-module`: the bridge's jar); no script is run (a test holds `GhidraScript` out of the bridge); XML external entities off (`javax.xml.accessExternal*` empty, as Ghidra's `launch.properties` sets) |
| Telemetry, update checks | none found in the source (searched for usage reporting, version and update checks: none) | - |
| Native code in jars | `flatlaf` (the GUI's look and feel) and JNA (in `Framework/Pty`, the debugger's terminals) carry native libraries; neither is loaded headless | nothing is unpacked into `/tmp` (which the container mounts `noexec`) |
| Input parsing | Ghidra's loaders (Java) parse the untrusted file; the decompiler (C++) works on what the analysis made of it | the server's sandbox is the boundary: no network, the input read-only, a non-root user, limits; a crash of the decompiler fails one call |

## The server (src/server.py and src/GhidraBridge.java, ours)

`src/server.py` follows servers/jadx's server (its path walk, descriptor passing, JVM handling and answer paging are
the same code, reviewed there) and starts one JVM per opened file: Ghidra's own launcher (`ghidra.Ghidra` with
`ghidra.GhidraClassLoader`, the VM arguments of `support/launch.properties` that apply headless) runs
`GhidraBridge`, found as an external module. The JVM gets an empty environment (`PATH`, `LANG`, `HOME` only), a
heap of 60 % of the container's memory limit (the decompiler, a native process, needs the rest), serial GC, at most
two analysis threads (`cpu.core.limit`), no attach mechanism, no perf data, no class-data sharing; nothing of a call
becomes a JVM option (every argument of a call comes after the main class, and a language id must match
`PROCESSOR:LE|BE:SIZE:VARIANT`).

`src/GhidraBridge.java` (an own program of 715 lines) imports the one file with `ProgramLoader` (Ghidra's
default loaders; with `language`/`compiler` from `open_file` for raw firmware), keeps only the primary program
(libraries are not loaded from disk, Ghidra's default), runs `AutoAnalysisManager` with a `TimeoutTaskMonitor`
(`GHIDRA_ANALYSIS_SECONDS`, 30-3600, default 300: a larger binary is analysed in part and `open_file` says so), opens
one `DecompInterface` (30 s per function) and then answers nine read operations over stdin/stdout, one JSON line
each. `System.out` is pointed at stderr before Ghidra starts, so Ghidra's console log never reaches the protocol. It
renames nothing, sets no type, saves nothing, opens no project, runs no script, starts no process, opens no socket.

**Tools (10, read-only):** `list_files`, `open_file` (format, language, compiler, image base, SHA-256, counts,
entry points, memory blocks; raw firmware with `language`), `list_functions`, `decompile_function`,
`disassemble_function` (address, bytes, instruction, the called function), `function_calls` (callers and callees),
`find_references` (to an address, a function, a label or an import; the calls to an import's thunks included),
`list_imports`, `list_exports`, `list_strings`. A function is named by its name, `Namespace::name`, or an address
inside it. Answers at most 400 lines or 24,000 characters (lists 300 entries), with `start_line`/`offset` to go on;
shown lines lose control and direction characters (a string of the input cannot fake a line of the answer).

**Bounds:** inputs up to 256 MiB, regular files in `/work` only (no `..`, no link followed, no pipe); a call waits at
most 40 s for an import still running and then says to call again; a request has 50 s, the import the analysis limit
plus 300 s; a JVM over its time is killed (its process group) and the next call imports again; out of memory is said
(`--memory 6g` for large binaries).

## Verification (2026-11-25, here; no Podman in this sandbox)

Ghidra 12.2 from the pinned zip (SHA-256 checked), pruned as the Dockerfile prunes it, the bridge compiled with the
pinned Temurin JDK 25.0.5+8 (`javac --release 25 -Xlint:all,-path,-classfile -Werror`), the server run over stdio from
`src/server.py` with the lock of servers/jadx:

- `smoke.json` (the `hello`, `caps` and `firmware.bin` fixtures): initialize, tools/list = tools.json (10), 20 of 20
  calls passed - every tool, the refusals (`..`, `/etc/passwd`, an unknown function, an unknown language), raw firmware
  refused without a language and imported as `ARM:LE:32:v8` with it (the vector table's eight functions).
- `tests/test_ghidra.py`: 30 tests passed, among them the RealGhidra class against the real Ghidra.
- A large binary (`libjvm.so` of Temurin, 29.9 MB, 53,209 functions, 69,650 strings): "still importing" answers every
  40 s, the analysis stopped at `GHIDRA_ANALYSIS_SECONDS` (120 s; with 30 s the note "the analysis was stopped after
  30 s" appears), then `decompile_function JNI_CreateJavaVM` in 0.4 s, lists of 300 entries within 24,000 characters.
- Processes and files: only `decompile` and `demangler_gnu_v2_41` were started; nothing was written outside the
  scratch folder, which is gone after the run.

**Only CI or a real host can prove:** the image build (the self-test at its end runs Ghidra's whole start inside the
image), the smoke run under Podman and Bubblewrap with `noexec` /tmp, 3 GiB memory and 512 processes, and the image's
size (about 600 MB: Ghidra 500 MB pruned, the JRE 140 MB).
