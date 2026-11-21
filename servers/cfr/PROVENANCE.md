# cfr - provenance and audit

| | |
|---|---|
| MCP server | this repository: `src/server.py` (Python, the MCP SDK), MIT (`LICENSES/`), written for this repository and reviewed in full (below) |
| Tool | CFR **0.152** (leibnitz27/cfr, MIT, `LICENSES/cfr-MIT.txt`): tag `0.152` = commit `68477be3ff7171ee17ddd1a26064b9b253f1604f`, released 2021-12-11 - the latest release |
| Release asset | `cfr-0.152.jar`, SHA-256 `f686e8f3ded377d7bc87d216a90e9e9512df4156e75b06c655a16648ae8765b2` (`ADD --checksum`). GitHub publishes no digest for assets of 2021: this is the SHA-256 of the asset as downloaded here on 2026-11-16 and **compared in CI with Maven Central's `org.benf:cfr:0.152`** (the other place it is published, not reachable from here): `maven-central.json`, `scripts/maven_central.py`, the step "Maven Central - the shipped jars against the release there" before the image is built - the Maven Central jar checked against its `.sha1`/`.sha256` there, then the whole jar byte for byte, or else every file of it but `META-INF/` byte for byte in ours and nothing else under `org/benf/cfr/`; a difference fails the job. The result is `maven-central-cfr.json` in the job's artifact `ci-cfr` |
| Java | Debian trixie `openjdk-21-jre-headless=21.0.13+9-1~deb13u2` (trixie-security, first published 2026-10-27; the same as servers/jadx) |
| Python packages | `mcp==1.30.0` and its dependencies, hash-locked in `requirements.txt` (byte-identical to web-fetch's but for the `# via` line) |
| Debian packages | `python3=3.13.5-1`, `python3-venv=3.13.5-1` (purged after the venv is made), `ca-certificates=20250419+deb13u1` (pip's download while building), the JRE above |
| Base image | the `debian:trixie-slim` digest in `Dockerfile` (the same as web-fetch's) |

**Pinning rule:** CFR 0.152 is almost five years old and upstream's newest release (there is no newer tag). No new
Python package; the JDK is the trixie-security build (exempt, 20 days old).

**The jar and its sources.** The release's `cfr-0.152-sources.jar` equals the tag's `src/` file for file (732 files,
identical but for CRLF line endings; `CfrVersionInfo.java` is generated from `src-templates/`), and every class of
`cfr-0.152.jar` (1,371 entries) has its source there. The class files themselves were not rebuilt and compared: CFR
targets Java 6, which no JDK that runs here can compile for.

## Why an own server

There is no maintained MCP server for CFR; the Java decompiler servers that exist bundle several decompilers behind a
GUI or a web service. This one is small: the class list and the class files are read by the server itself (Python's
`zipfile` and a class-file reader of ours), and CFR is started only to decompile. For APK and DEX files, and Kotlin,
use servers/jadx: **CFR 0.152 has no Kotlin option** (its `OptionsImpl` has none; Kotlin bytecode comes out as Java).

## Tools

Six, all read-only (`readOnlyHint`, `openWorldHint: false`), plain-text answers: at most **400 lines or 24,000
characters** per answer, a numbered line each, the next part named.

| Tool | What |
|---|---|
| `list_files` | the files in `/work` CFR reads (`.jar .war .ear .zip .class`; `show_all` for every file), with sizes, 8 folders deep, at most 300; no link followed |
| `list_classes` | the classes of a JAR, WAR (below `WEB-INF/classes/`), EAR or ZIP, or the one class of a `.class` file (`package`, `name_filter`, `include_inner`, `offset`); says so when the archive holds nested JARs (not read) or is an Android app (use jadx) |
| `class_outline` | from the class file itself: access, kind, class file version, superclass, interfaces, fields, methods with their descriptors (`checkPassword(Ljava/lang/String;)Z` shown as `boolean checkPassword(java.lang.String)`), inner classes |
| `decompile_class` | CFR's Java source of a class (an inner class within its outer class), in parts; optionally `rename_duplicate_members`, `rename_illegal_identifiers`, `anti_obfuscation` |
| `decompile_method` | CFR's own method mode (`--methodname`): all methods of one name; the class file is copied out of the archive and the archive is CFR's class path |
| `search_strings` | the string constants (`include_names`: field and method names too) of every class, read from the constant pools without decompiling; at most 20 s per call, `start_class` to go on |

## Audit of our code (`src/server.py`, 1,001 lines, read in full)

**Input files.** As servers/jadx: relative to `/work` or absolute under it; `..`, `~`, control characters, long names
refused; walked one name at a time with `openat(O_NOFOLLOW)`, every link refused; only a regular, non-empty file of at
most 512 MiB; `list_files` never enters or lists a link.

**Reading archives.** The opened descriptor is read with `pread` (the first bytes: `CAFEBABE` is a class file, `PK` a
zip, anything else is refused) and, for a zip, with `zipfile` on a duplicate of it (closed with the archive). At most
200,000 entries; a class file is read only up to 16 MiB of its uncompressed bytes (a zip bomb stops there); names
under `META-INF/` (multi-release copies), `module-info` and `package-info`, and names with `..` are not listed. The
last archive stays open for the next call (another file, or the same name with another device, inode, size or time,
replaces it).

**The class-file reader (`ClassFile`).** JVMS chapter 4 as far as the outline and the string search need: the
constant pool (every tag of Java 21, with the double slot of `long` and `double`), access, this and super class,
interfaces, fields and methods with their attributes skipped by length. Every read goes through `struct.unpack_from`
or a checked slice: a short, truncated or invented file raises "not a valid class file" (tested with eight broken
ones, each refused in microseconds); it allocates nothing beyond the file's own size.

**CFR.** Started per decompilation as `java -Xmx<70 % of the cgroup's memory.max - 64 MiB, at least 192 MiB; 768 MiB
without a limit> -Xss16m -XX:+UseSerialGC -XX:CICompilerCount=2 -XX:+ExitOnOutOfMemoryError -XX:-UsePerfData
-XX:+DisableAttachMechanism -XX:ErrorFile=/dev/null -Djava.io.tmpdir=<scratch>/run -Duser.home=<scratch>/run -jar
cfr-0.152.jar <input> --silent true <options>`, where:

- `<input>` is a link, in a fresh scratch folder `/tmp/cfr-mcp/<random>/in/` (mode 0700), to `/proc/self/fd/N` with
  the opened descriptor passed to the JVM: CFR reads exactly the file that was checked. For `decompile_method` the class
  file is copied out of the archive into `in/subject.class` (the one file the server writes) and the archive link is
  passed as `--extraclasspath`, so CFR still sees the other classes;
- `<options>` are built by the server only: `--analyseas JAR|WAR` (by the input's suffix), `--jarfilter
  ^<the class, regex-escaped>$` (CFR wraps it in `^.*...*$`: only that class matches), `--methodname <name>`, and the
  three switches a call may set, each mapped to one fixed flag with the value `true` (`CFR_FLAGS`:
  `--renamedupmembers`, `--renameillegalidents`, `--antiobf`). Never an output folder (`--outputdir`,
  `--outputpath`), an extra class path from an argument, a mapping file (`--obfuscationpath`), an import filter or
  `--clobber`. CFR's option parser takes any argument that starts with `--` as an option (`GetOptParser.process`):
  a method name may not start with `-`, the filter always starts with `^`, the paths with `/`;
- the environment is exactly `PATH=/usr/bin:/bin`, `LANG=C.UTF-8`, `HOME=<scratch>/run`; the working folder
  `<scratch>/run` is empty; stdin is `/dev/null`; its own session (killed as a group);
- the run has 40 s; its output is read up to 16 MiB (more stops it: "use decompile_method"), its stderr up to 64 KiB
  (the last line explains a failure); exit status 3 is "ran out of memory"; the scratch folder is removed afterwards,
  whatever happened.

The output is cached for the next parts (8 texts). **Answers:** every shown line loses control characters, NEL, the
Unicode line and paragraph separators and bidirectional controls, a line over 2,000 characters is cut, titles and
names from the input pass the same filter; lists of 300, results of 200, string constants cut at 300 characters.
**Tools only:** the resource and prompt handlers are removed. **Network:** none. **Writes:** only the scratch folder.
**Environment:** none read.

### CFR itself (the tool, read where the confinement depends on it)

Read at tag `0.152` (`68477be3`): `Main`, `Driver` (`doClass`, `doJar`, `doJarVersionTypes`), `GetOptParser`,
`OptionsImpl` (all 99 options), `ClassFileSourceImpl` (where CFR reads files), `MiscUtils.mkRegexFilter`, and the
whole source searched for `java.net`, `Runtime.exec`, `ProcessBuilder`, `getenv`, `System.getProperty`,
`Class.forName`, class loaders, file writes. What matters:

- **Files CFR reads besides the input.** (1) To resolve a type it first tries `new File("<package>/<Name>.class")`
  relative to its working folder - empty here, and always a name ending in `.class`. (2) The `Class-Path` of an input
  JAR's manifest is followed relative to the JAR's folder (`addToRelativeClassPath`): here that folder is the scratch
  folder, so a crafted JAR can make CFR open other files of the **container** (and of `/work`) as class-path entries to
  look for classes in. Nothing of the host beyond the mounted folder is reachable, nothing is written, and what CFR
  reads that way only resolves types. Known and accepted; said in the catalog entry's notes. (3) The JDK's classes by
  `jrt:/` URLs; a class in a package of no JDK module by `Class.forName` - which runs that class's static initialiser
  if it is on the JVM's class path: only CFR's own classes and the JDK are.
- **No network, no process, no environment:** the only `java.net` use is the `jrt:` reader above
  (`getUrlContent` refuses every other protocol); no process is started; `System.getProperty` is read for the class
  path, `sun.boot.class.path` and `os.name`; no environment variable.
- **Writes:** only the dumpers for `--outputdir`/`--outputpath`, never passed.

## Self-review: what was found and changed

1. A method name starting with `--` would have become a CFR option (`--methodname --outputdir ...`: CFR then refuses
   for a missing value, but the rule should not depend on that): names starting with `-` are refused.
2. `zipfile` does not close the file object it is given: the duplicate descriptor leaked on every archive switch and
   on a refusal (more than `MAX_ENTRIES` entries). Closed now (tests run with `ResourceWarning` as an error).
3. CFR's pipes were left open after a run; closed now.
4. A broken class file gave "CFR gave no source ..."; it says "not a valid class file" now.
5. With no time left a string search made no progress; at least one class per call now.
6. Tabs and line breaks passed the argument check; class names are checked before the file is opened; titles and
   "similar" lists from the input are filtered.

## Tests

- `tests/test_cfr.py` (16 tests): paths, links, pipes, empty files; member names that would be options; the class-file
  reader on the fixture's classes and on eight broken class files; descriptors; outlines; JARs, WARs, nested JARs,
  APKs, entry limits, inner classes, similar names; string search in parts (time budget, broken classes, names);
  CFR's command line against a stand-in (the descriptor read through `/proc/self/fd`, the arguments exactly as built,
  the environment exactly three variables, an empty working folder, the scratch folder removed), only three options,
  the time and output limits; with CFR at hand every tool on `demo.jar` and a single `.class`, and a class CFR cannot
  read; tools only. Run here against CFR 0.152's jar on Java 21: all pass.
- `tests/test_own_servers.py` `test_cfr`: over stdio as the image starts it, then the suite above (in CI inside the
  image with its own CFR and JVM).
- `tests/test_analysis_servers.py` `JavaDecompilers`: pins, no network, `/work` read-only, limits, imports, the one
  process start, the options CFR can get.
- `smoke.json`: every tool on `demo.jar`, three refused calls (`/etc/passwd`, a method name `--outputdir`, an APK).

**Not run here (no container engine):** the image build, the smoke spec under Podman and Bubblewrap, Trivy. Signing
waits for CI to build the image and both smoke runs to pass.
