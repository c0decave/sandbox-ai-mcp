# jadx - provenance and audit

| | |
|---|---|
| MCP server | this repository: `src/server.py` (Python, the MCP SDK) and `src/JadxBridge.java` (the JVM half, on jadx's library), MIT (`LICENSES/`), written for this repository and reviewed in full (below) |
| Tool | jadx **1.5.6** (skylot/jadx, Apache-2.0, `LICENSES/jadx-Apache-2.0.txt`, `LICENSES/jadx-NOTICE.txt`): tag `v1.5.6` = commit `28ff15e4ae69950aebea110a13e5ab895d234dfc`, released 2026-07-10 by upstream's `release.yml` workflow (`./gradlew dist`) |
| Release asset | `jadx-1.5.6.zip`, SHA-256 `545ea2be9c242511bc145755cf4bda2485ade42966e096f8b4d3da2a230e8974` (the digest GitHub publishes for the asset; `ADD --checksum` in the build stage) |
| What of it ships | only `lib/jadx-1.5.6-all.jar`, SHA-256 `fe3e12c45acf75f92369685fd02d1d7a7323385dc725680a9b98a0dac0ea554b` (checked where it is unpacked and again in the final image); not the `bin/` scripts |
| Java | Debian trixie `openjdk-21-jre-headless=21.0.13.1+2-1~deb13u1` (trixie-security; 21.0.13.1+2-1~deb13u1 replaced 21.0.13+9-1~deb13u2 on 2026-11-21, in which CI's Trivy found the CRITICAL CVE-2026-114820 and CVE-2026-114938); the bridge is compiled in a build stage with `openjdk-21-jdk-headless=21.0.13.1+2-1~deb13u1` (`javac --release 21 -Xlint:all -Werror`), which does not ship |
| Python packages | `mcp==1.30.0` and its dependencies, hash-locked in `requirements.txt` (byte-identical to web-fetch's but for the `# via` line: the set files, code-search, exec and tasks run) |
| Debian packages | `python3=3.13.5-1`, `python3-venv=3.13.5-1` (purged after the venv is made), `ca-certificates=20250419+deb13u1` (pip's download while building), the JRE above; build stage only: the JDK above, `unzip=6.0-29+deb13u1` |
| Base image | the `debian:trixie-slim` digest in `Dockerfile` (the same as web-fetch's) |

**Pinning rule:** jadx 1.5.6 is upstream's newest release and 129 days old on 2026-11-16 (well past 14 days). The
JDK is the trixie-security build (Debian packages are exempt; it is 20 days old anyway). No new Python package: the
lock is the one the published images use.

## Why an own server, and not zinja-coder's

The MCP servers for jadx that exist (2026-11-16) drive **jadx-gui**: zinja-coder/jadx-mcp-server 6.5.0 (Apache-2.0) is
a Python client of the jadx-ai-mcp plugin, which runs an HTTP server inside a running JADX GUI window and refuses to
work without one (`JadxAIMCP.java`: "Running in non-GUI mode, plugin features disabled"). A container with no display
cannot run it, and what it would ship is the opposite of this repository's rules: an unauthenticated HTTP API in the
GUI (`Javalin.create(...).start(8650)`, no host given: Jetty's default, every interface; renames, comments and the debugger's
frames by plain GET), the Python side on `fastmcp>=3.0.2`, `httpx`, `requests` unpinned, write tools (rename, comment)
and debugger tools by default. The full record is in [docs/CANDIDATES.md](../../docs/CANDIDATES.md#jadx-mcp-server-and-jadx-ai-mcp-zinja-coder-looked-at-on-2026-11-16-not-packaged).
Nothing of it is used here.

Instead this server uses jadx's own library headless (`jadx.api.JadxDecompiler`, the API jadx-cli and jadx-gui are
built on) through a small JVM program of ours, and offers what the GUI plugin offers that makes sense without a GUI
(classes, sources, methods, smali, cross references, search, manifest, resources) read-only.

## Tools

Fourteen, all read-only (`readOnlyHint`, `openWorldHint: false`), plain-text answers made for small local models: at
most **400 lines or 24,000 characters** per answer (the files server's parts), a numbered line each, and the next
part named (`start_line=...`, `offset=...`, `start_class=...`).

| Tool | What |
|---|---|
| `list_files` | the files in `/work` jadx reads (`.apk .dex .jar .aar .aab .xapk .apks .apkm .class .smali .zip`; `show_all` for every file), with sizes, 8 folders deep, at most 300, 20,000 entries looked at; no link followed |
| `open_file` | loads a file and says what is in it: classes (with inner), packages, resources, jadx's error count, from the manifest the app's package, version, minSdkVersion, permissions, components and launcher activity, the largest packages |
| `list_packages` | packages with their class counts (`prefix`, `offset`) |
| `list_classes` | top-level classes (`package`, `name_filter`, `offset`) |
| `class_outline` | kind, access, superclass, interfaces, fields, methods with the signature other tools take (`checkPassword(Ljava/lang/String;)Z`), inner classes - without decompiling |
| `get_class_source` | the Java source of a class (an inner class within its outer class), in parts |
| `get_method_source` | the Java source of the methods of one name, or of one signature (jadx's `JavaMethod.getCodeStr`) |
| `get_smali` | the class's bytecode: smali for DEX input, jadx's disassembly for `.class` input |
| `find_usages` | cross references from jadx's usage info (`getUseIn`): who calls a method, uses a field, or uses a class |
| `search_code` | text in the decompiled code (any case optional, a package to narrow it): classes are decompiled in turn for at most 20 s per call, the answer gives `start_class` to go on; a class decompiled only for the search is unloaded again |
| `search_names` | class, method and field names containing a text, nothing decompiled |
| `get_manifest` | `AndroidManifest.xml` decoded |
| `list_resources` | the other files of the app with type and size; `include_decoded` adds the files decoded from `resources.arsc` |
| `get_resource` | one resource as text (binary XML and resource tables decoded, text files as they are, at most 4 MiB), a binary one as its size and first 256 bytes in hex |

## Audit of our code (`src/server.py`, 1,047 lines; `src/JadxBridge.java`, 651 lines; read in full)

**Input files.** A path is relative to `/work` or absolute under it; `..`, `~`, any control character (tab and line
breaks too), a name over 255 bytes and a path over 4,096 characters are refused before anything is opened. The path is
walked one name at a time from the descriptor of `/work`: `openat(O_DIRECTORY | O_NOFOLLOW)` for each folder,
`openat(O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_NOCTTY)` for the file, so a link anywhere on the way is refused ("links
are not followed: name the file itself") - also one that stays inside `/work`, because the server never needs one -,
and a pipe swapped in never blocks the open. `fstat` of the open descriptor: only a regular file, not empty, at most
512 MiB. `list_files` walks with `scandir` on descriptors, never entering or listing a link.

**The file the JVM reads is the file that was checked.** The server keeps the descriptor open and makes, in a fresh
scratch folder `/tmp/jadx-mcp/<random>/in/` (mode 0700), a link with the file's own name made plain (`[A-Za-z0-9_-]`
and its suffix: jadx tells some formats - `.xapk`, `.apks`, `.aab` - by it) to `/proc/self/fd/N`, and starts the JVM
with exactly that descriptor passed (`pass_fds`). In the JVM `/proc/self/fd/N` is that inherited descriptor: jadx
opens the checked file, whatever happens to the name in `/work` meanwhile, and never a name of the caller's choosing.
Messages from jadx name the file as `/work/...`, never the scratch folder.

**The JVM.** One per loaded file: `java -Xmx<70 % of the cgroup's memory.max - 64 MiB, at least 256 MiB; 1,536 MiB
when there is no limit> -Xss8m -XX:+UseSerialGC -XX:CICompilerCount=2 -XX:+ExitOnOutOfMemoryError -XX:-UsePerfData
-XX:+DisableAttachMechanism -XX:ErrorFile=/dev/null -Djava.io.tmpdir=<scratch>/tmp -Duser.home=<scratch>/tmp
-cp jadx-1.5.6-all.jar:/opt/mcp/bridge JadxBridge <link>` - no part of it comes from a tool argument. Its environment
is exactly `PATH=/usr/bin:/bin`, `LANG=C.UTF-8`, `HOME=<scratch>/tmp` (so no `JAVA_TOOL_OPTIONS`, `JDK_JAVA_OPTIONS`,
`_JAVA_OPTIONS` and none of jadx's `JADX_*` variables, such as `JADX_DISABLE_ZIP_SECURITY`, can reach it), its working
folder the scratch folder, its stdin and stdout the protocol, its stderr `/dev/null`, its own session (killed as a
group). 13 threads with a 78 MB JAR of 22,805 classes (measured here): far below the 256 processes the entry asks for.

**The bridge (`JadxBridge.java`).** `System.out` is pointed at stderr before jadx is touched (jadx's `logback.xml`
logs to standard output) and the root logger is switched off; answers go to a stream on the original descriptor 1, one
JSON object per line (Gson from jadx's jar). It builds `JadxArgs` with the input, one thread, deobfuscation off, and
**its own plugin loader**: only the input plugins (dex, java, smali, xapk, apkm, apks, aab) and the Kotlin metadata and
source-debug plugins. Not loaded: java-convert (D8/dx conversion), rename-mappings (reads mapping files), and nothing
from the class path's service list or a plugins folder (jadx-cli's `JadxExternalPluginsLoader`, which also installs
plugins from GitHub, is never referenced). It never calls `save()`: no sources or resources are written; the output
folder named for jadx's argument check (`<tmp>/never-written`) is not created. Requests are one of eleven fixed
operations; a refusal is a message, an unexpected exception its class and message, never a stack trace. No
`java.net`, no process, no file write, no environment read (checked by `tests/test_analysis_servers.py`).

**Protocol and time.** One request at a time (a lock); a reader thread collects answers by id. Loading has its own
clock: a call waits at most 40 s for it, then answers - not as an error - that jadx is still loading and to call again;
a load is stopped after 10 minutes. Every other request has 45 s (below Codex's 60 s); one that runs over it stops the
JVM (the next call loads the file again) and says so. A JVM that ends on its own is reported: exit status 3 (out of
memory, `-XX:+ExitOnOutOfMemoryError`) as "ran out of memory ... --memory 4g". `search_code` gives jadx a 20 s budget,
checked between classes, and always gets at least one class further per call.

**Which file.** One file is loaded at a time. A call naming another file - or the same name with another device,
inode, size or modification time - stops the JVM, closes the descriptor and removes the scratch folder before the new
file is loaded. Decompiled texts are kept for the next part (8 at most, the last used first). The server's end closes
all of it.

**Answers.** Every line shown loses control characters, NEL, the Unicode line and paragraph separators and the
bidirectional overrides and isolates (a class name or a string constant cannot fake a line of the answer or reorder
it); a line over 2,000 characters is cut and says so; titles and names from the input pass the same filter. Lists:
300 entries; results: 200; a resource: 4 MiB. Class names are taken as `a.b.C`, `a/b/C`, `La/b/C;` or `a.b.C$D`; an
unknown one is refused with up to eight similar names. Member names are one name (no `.`, `/`, parentheses, spaces,
not starting with `-`); a signature must look like one.

**Tools only.** The SDK would announce empty resources and prompts; the server removes their handlers, so it offers
tools and nothing else.

**Network:** none; no module that could open a connection is imported, and the container has no network. **Writes:**
only the scratch folder below the container's `/tmp`. **Environment:** none read.

### jadx itself (the tool, read where the confinement depends on it)

jadx is the analysis tool here, as radare2 is for servers/radare2: reviewed on the paths this server's limits rely on,
not as a whole. Read at tag `v1.5.6` (`28ff15e4`), source from GitHub's tag archive:

- `JadxDecompiler.load` and `JadxArgs`: plugins come only from `args.getPluginLoader()` (ours); inputs are loaded by
  the plugins' `JadxCodeInput`s from the given files; nothing is written unless `save()` is called;
  `JadxArgsValidator` only checks the output folders, it creates none.
- Temporary files: `FileUtils.updateTempRootDir(args.getFilesGetter().getTempDir())`, `TempFilesGetter` below
  `java.io.tmpdir` (the scratch folder); nested archives (an APK in an XAPK, a JAR in an AAR) are extracted there.
- Archives: `JadxZipSecurity` refuses entry names with `../` or `..\`, entries outside the extraction folder, more than
  100,000 entries and entries whose uncompressed size is far above the compressed one (zip bombs); its only switches are
  `JADX_DISABLE_ZIP_SECURITY` and `JADX_ZIP_MAX_ENTRIES_COUNT`, environment variables the JVM never gets.
- Searched in `jadx-core`, `jadx-commons` and `jadx-plugins` (main sources) for `java.net`, sockets, `ProcessBuilder`,
  `Runtime.exec`, `ScriptEngine`, `URLClassLoader` and `System.getenv`: `Jadx.java` reads the jar's own
  `META-INF/MANIFEST.MF` through the class loader (its version); `DisasmUtils.useSystemJavaP` would run `javap` but is
  private and never called; the environment only in `Utils.getEnvVar*` (the two zip switches above) and in
  `jadx-app-commons` (the CLI's and GUI's settings, not on this path).
- The GUI's and the CLI's code (`jadx-gui`, FlatLaf, RSyntaxTextArea, graphviz-java with J2V8's native V8 library,
  `jadx-plugins-tools`) is in the jar but never loaded: the bridge's class is the entry point and references none of it.
- The 34 libraries in the jar (`META-INF/maven/*/pom.properties`): logback 1.5.38, gson 2.14.0, guava 33.6.0,
  commons-io 2.22.0, commons-lang3 3.20.0, commons-text 1.15.0, antlr 3.5.2 and ST4 4.0.8 (smali), slf4j 2.0.18,
  twelvemonkeys 3.12.0, the GUI's (graphviz-java 0.18.1, J2V8 4.6.0, ...); R8/D8 and bundletool are shaded in.

**Not verified here:** that the jar's classes are exactly what the tag's sources build to (a Gradle build needs Maven
Central, not reachable from where this was prepared); the checksum is the one GitHub publishes for upstream's own
release build. CI's Trivy scan of the image covers the bundled libraries.

## Self-review: what was found and changed

1. The protocol's request id and the method signature shared the key `id` - `get_method_source` found no method.
   Renamed to `signature`; the real-jadx tests call it with and without one.
2. A failed load's message named the scratch link; jadx's messages now name the file as `/work/...`
   (`test_a_file_jadx_cannot_read`).
3. `CALL_SECONDS` was bound as a default argument (a patched limit had no effect); read at call time now
   (`test_a_call_over_its_time_limit_stops_the_jvm_and_the_next_call_loads_again`).
4. Tabs and line breaks passed the argument check; every control character is refused now.
5. A member name starting with `-` is refused (CFR would read it as an option; here for the same rule in both).
6. A JVM that could not be started left its scratch folder and the descriptor; both are cleaned up now.
7. Class names and titles from the input reached answers unfiltered in titles and "similar" lists; filtered now.
8. A search with no time left made no progress; at least one class per call now.
9. Arguments are checked before the file is opened (a bad class name never touches `/work`).

## Tests

- `tests/test_jadx.py` (25 tests): paths and links, pipes, empty and oversized files, `list_files`; argument checks;
  parts of 400 lines / 24,000 characters, cut lines, lists, filtered lines, the manifest summary; the JVM's command line
  and heap; the protocol against a stand-in JVM (the descriptor read through `/proc/self/fd`, the environment exactly
  three variables, another and a changed file, still loading, a time limit that stops the JVM, out of memory, a failed
  load, parts and unknown classes); with jadx at hand every tool on `demo.apk` and `demo.jar`, a file jadx cannot read;
  tools only and the recorded tools. Run here against jadx 1.5.6's jar and the bridge compiled with javac 21: all pass.
- `tests/test_own_servers.py` `test_jadx`: over stdio as the image starts it, then the suite above - in CI inside the
  image with its own jadx and JVM, no network.
- `tests/test_analysis_servers.py` `JavaDecompilers`: pins (release, jar, JDK) in the Dockerfile and here, no network,
  `/work` read-only, limits, our imports, one process start with the fixed environment, the bridge's plugins.
- `smoke.json`: every tool on the fixtures, three refused calls; in CI under Podman and Bubblewrap with sandbox-ai's
  run lines (`memory 2g`, `pids 256`, a 256m `/tmp`).
- A 78 MB JAR (jadx's own, 22,805 classes) was opened here: loaded in 23 s, `find_usages` and `get_class_source`
  instant, `search_code` 945 classes per 20-second step without a package and 13,650 with one; the JVM peaked at
  1.6 GB with a 1.5 GB heap.

**Not run here (no container engine):** the image build, the smoke spec under Podman and Bubblewrap, Trivy. Signing
waits for CI to build the image and both smoke runs to pass.
