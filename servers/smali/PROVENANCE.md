# smali - provenance and audit

| | |
|---|---|
| MCP server | this repository: `src/server.py` (Python, the MCP SDK), MIT (`LICENSES/`), written for this repository and reviewed in full (below) |
| Disassembler/assembler | **smali and baksmali 3.0.10 as Google publishes them**: `com.android.tools.smali:{smali,smali-baksmali,smali-dexlib2,smali-util}:3.0.10` from **Google's Maven repository** (maven.google.com, served from `dl.google.com/dl/android/maven2`; not on Maven Central), uploaded 2026-09-04; BSD-3-Clause (`LICENSES/smali-baksmali-LICENSE.txt`, byte for byte the `LICENSE` inside Google's jars). The code is google/smali at commit `7a325fc45dc02d0e428da5b54685e5887903efca` ("Version 3.0.10", Søren Gjesse <sgjesse@google.com>, 2026-08-19), the head of its `main` branch |
| Their dependencies | exactly the runtime dependencies Google's POMs name (13 jars from **Maven Central**: Guava 31.1-android with its four companions, jsr305, jcommander 1.85, ANTLR 3.5.2 with its runtime, StringTemplate 4.0.8 and 3.2.1, ANTLR 2.7.7 - the table below) |
| Class paths | baksmali: `java -cp <its 11 jars> com.android.tools.smali.baksmali.Main`; smali: `java -cp <its 16 jars> com.android.tools.smali.smali.Main` (Google's thin jars name no `Main-Class`; `BAKSMALI_CLASSPATH`/`SMALI_CLASSPATH` in `src/server.py` and the Dockerfile's ARGs of the same name) |
| APK tool | **apktool 3.0.3** (iBotPeaches/Apktool, Apache-2.0, `LICENSES/apktool-Apache-2.0.txt`, `apktool-NOTICE.txt`), released 2026-07-20: `apktool_3.0.3.jar`, SHA-256 `dbf930b076c6b9be08d57c449cacefc3bdd6b71ebd59b3066fc0e1f5b14f9423` (the SHA-256 GitHub publishes) |
| Out of that jar | apktool's own **aapt2 2.20** (`prebuilt/linux/aapt2`), SHA-256 `df312db814c018019b2b79a993b041b738d7b76f4a8f28da25bc874a026368cc`, and its **android-framework.jar**, SHA-256 `5dd984016ed5a5eb0eef866e2c6e8cd352e1427828ec23adb18005cf5648f3d7` (installed as `/opt/apktool/framework/1.apk`) - both checked when the image is built |
| Signing and aligning | Debian trixie `zipalign=1:10.0.0+r36-1.1` (android-platform-build), `libapksig-java=35.0.2-1` and the one jar of `apksigner=35.0.2-1` (android-platform-tools-apksig, Apache-2.0), with `keytool` of the JRE |
| Java | Debian trixie `openjdk-21-jre-headless=21.0.13.1+2-1~deb13u1` (trixie-security; the same as servers/jadx and servers/cfr; 21.0.13.1+2-1~deb13u1 replaced 21.0.13+9-1~deb13u2 on 2026-11-21, in which CI's Trivy found the CRITICAL CVE-2026-114820 and CVE-2026-114938) |
| Python packages | `mcp==1.30.0` and its dependencies, hash-locked in `requirements.txt` (byte-identical to web-fetch's but for the `# via` line) |
| Debian packages | `tini=0.19.0-3+b8` (the image's init, its ENTRYPOINT: no host init needed), `python3=3.13.5-1`, `python3-venv=3.13.5-1` (purged after the venv is made), `ca-certificates=20250419+deb13u1` (pip's download while building), `unzip=6.0-29+deb13u1` (build stage), the JRE and Android tools above |
| Base image | the `debian:trixie-slim` digest in `Dockerfile` (the same as the other servers') |

## Every jar of `/opt/smali`

Each is `ADD --checksum=sha256:...` by its URL in the Dockerfile (a `<NAME>_URL` and `<NAME>_SHA256` ARG per jar),
in the image at `/opt/smali/<artifact>-<version>.jar`, 6,974,498 bytes in all. Every SHA-256 was computed here on
2026-11-22 from the jar as its repository serves it, and the jar matched **every** checksum file the repository
publishes beside it (Google publishes `.md5 .sha1 .sha256 .sha512` for all four; Maven Central `.md5 .sha1` for most,
`.sha256 .sha512` too for checker-qual and jcommander); an `.asc` signature is published beside most of them as well
(not verified here: the signers' keys are not at hand). The dates are the upload dates the repositories serve.

| Jar (`/opt/smali/`) | URL | SHA-256 | Published checksums that matched | Uploaded | Licence (`LICENSES/`) |
|---|---|---|---|---|---|
| `com.android.tools.smali:smali:3.0.10` (313,207 bytes) | https://dl.google.com/dl/android/maven2/com/android/tools/smali/smali/3.0.10/smali-3.0.10.jar | `b54c34f7a1b769b1e637f8a26909c68f399c273f3e5cde3e308e91107c135305` | .sha1 .sha256 .sha512 (and .md5) | 2026-09-04 | BSD-3-Clause, `smali-baksmali-LICENSE.txt` |
| `com.android.tools.smali:smali-baksmali:3.0.10` (132,976 bytes) | https://dl.google.com/dl/android/maven2/com/android/tools/smali/smali-baksmali/3.0.10/smali-baksmali-3.0.10.jar | `7d6578dfe5c44f1984b64268e91834432b0942d49e08186a501039dd92b58213` | .sha1 .sha256 .sha512 (and .md5) | 2026-09-04 | BSD-3-Clause, `smali-baksmali-LICENSE.txt` |
| `com.android.tools.smali:smali-dexlib2:3.0.10` (1,200,356 bytes) | https://dl.google.com/dl/android/maven2/com/android/tools/smali/smali-dexlib2/3.0.10/smali-dexlib2-3.0.10.jar | `688dee6a46962a4dd1774b64be926534b0b6504bfd5d5c9f89c0f5af284f50c1` | .sha1 .sha256 .sha512 (and .md5) | 2026-09-04 | BSD-3-Clause, `smali-baksmali-LICENSE.txt` |
| `com.android.tools.smali:smali-util:3.0.10` (33,389 bytes) | https://dl.google.com/dl/android/maven2/com/android/tools/smali/smali-util/3.0.10/smali-util-3.0.10.jar | `cc2ef8349765644e4b15371f2c9f77d69b5412a094a38fe5fd992a124b7322fe` | .sha1 .sha256 .sha512 (and .md5) | 2026-09-04 | BSD-3-Clause, `smali-baksmali-LICENSE.txt` |
| `com.google.guava:guava:31.1-android` (2,785,359 bytes) | https://repo1.maven.org/maven2/com/google/guava/guava/31.1-android/guava-31.1-android.jar | `32ac2ed709d96d278b5d2e3e5cea178fa4939939c525fb647532f013308db309` | .sha1 (and .md5) | 2022-02-28 | Apache-2.0, `guava-failureaccess-listenablefuture-Apache-2.0.txt` |
| `com.google.guava:failureaccess:1.0.1` (4,617 bytes) | https://repo1.maven.org/maven2/com/google/guava/failureaccess/1.0.1/failureaccess-1.0.1.jar | `a171ee4c734dd2da837e4b16be9df4661afab72a41adaf31eb84dfdaf936ca26` | .sha1 (and .md5) | 2018-11-19 | Apache-2.0, `guava-failureaccess-listenablefuture-Apache-2.0.txt` |
| `com.google.guava:listenablefuture:9999.0-empty-to-avoid-conflict-with-guava` (2,199 bytes) | https://repo1.maven.org/maven2/com/google/guava/listenablefuture/9999.0-empty-to-avoid-conflict-with-guava/listenablefuture-9999.0-empty-to-avoid-conflict-with-guava.jar | `b372a037d4230aa57fbeffdef30fd6123f9c0c2db85d0aced00c91b974f33f99` | .sha1 (and .md5) | 2018-09-11 | Apache-2.0, `guava-failureaccess-listenablefuture-Apache-2.0.txt` (an empty jar: a manifest and its POM) |
| `com.google.code.findbugs:jsr305:3.0.2` (19,936 bytes) | https://repo1.maven.org/maven2/com/google/code/findbugs/jsr305/3.0.2/jsr305-3.0.2.jar | `766ad2a0783f2687962c8ad74ceecc38a28b9f72a2d085ee438b7813e928d0c7` | .sha1 (and .md5) | 2017-03-31 | Apache-2.0, `jsr305-Apache-2.0.txt` |
| `org.checkerframework:checker-qual:3.12.0` (208,835 bytes) | https://repo1.maven.org/maven2/org/checkerframework/checker-qual/3.12.0/checker-qual-3.12.0.jar | `ff10785ac2a357ec5de9c293cb982a2cbb605c0309ea4cc1cb9b9bc6dbe7f3cb` | .sha1 .sha256 .sha512 (and .md5) | 2021-04-01 | MIT, `checker-qual-MIT.txt` (the jar's own `META-INF/LICENSE.txt`) |
| `com.google.errorprone:error_prone_annotations:2.11.0` (15,979 bytes) | https://repo1.maven.org/maven2/com/google/errorprone/error_prone_annotations/2.11.0/error_prone_annotations-2.11.0.jar | `721cb91842b46fa056847d104d5225c8b8e1e8b62263b993051e1e5a0137b7ec` | .sha1 (and .md5) | 2022-01-25 | Apache-2.0, `error-prone-annotations-Apache-2.0.txt` |
| `com.google.j2objc:j2objc-annotations:1.3` (8,781 bytes) | https://repo1.maven.org/maven2/com/google/j2objc/j2objc-annotations/1.3/j2objc-annotations-1.3.jar | `21af30c92267bd6122c0e0b4d20cccb6641a37eaf956c6540ec471d584e64a7b` | .sha1 (and .md5) | 2017-01-18 | Apache-2.0, `j2objc-annotations-Apache-2.0.txt` |
| `org.jcommander:jcommander:1.85` (93,826 bytes) | https://repo1.maven.org/maven2/org/jcommander/jcommander/1.85/jcommander-1.85.jar | `fa7552d2831a2b20778d86851d093edca68fbc0a77f792b6223110e4fae67a70` | .sha1 .sha256 .sha512 (and .md5) | 2024-08-18 | Apache-2.0, `jcommander-Apache-2.0.txt` |
| `org.antlr:antlr:3.5.2` (1,153,819 bytes) | https://repo1.maven.org/maven2/org/antlr/antlr/3.5.2/antlr-3.5.2.jar | `5ac36c2acfb0a0f3d37dafe20b5b570f2643e2d000c648d44503c2738be643df` | .sha1 (and .md5) | 2014-03-25 | BSD-3-Clause, `antlr3-antlr-runtime-ST4-stringtemplate-BSD-3-Clause.txt` |
| `org.antlr:antlr-runtime:3.5.2` (167,761 bytes) | https://repo1.maven.org/maven2/org/antlr/antlr-runtime/3.5.2/antlr-runtime-3.5.2.jar | `ce3fc8ecb10f39e9a3cddcbb2ce350d272d9cd3d0b1e18e6fe73c3b9389c8734` | .sha1 (and .md5) | 2014-03-25 | BSD-3-Clause, `antlr3-antlr-runtime-ST4-stringtemplate-BSD-3-Clause.txt` |
| `org.antlr:ST4:4.0.8` (239,543 bytes) | https://repo1.maven.org/maven2/org/antlr/ST4/4.0.8/ST4-4.0.8.jar | `58caabc40c9f74b0b5993fd868e0f64a50c0759094e6a251aaafad98edfc7a3b` | .sha1 (and .md5) | 2014-03-25 | BSD-3-Clause, `antlr3-antlr-runtime-ST4-stringtemplate-BSD-3-Clause.txt` |
| `org.antlr:stringtemplate:3.2.1` (148,627 bytes) | https://repo1.maven.org/maven2/org/antlr/stringtemplate/3.2.1/stringtemplate-3.2.1.jar | `f66ce72e965e5301cb0f020e54d2ba6ad76feb91b3cbfc30dbbf00c06a6df6d7` | .sha1 (and .md5) | 2009-09-22 | BSD-3-Clause, `antlr3-antlr-runtime-ST4-stringtemplate-BSD-3-Clause.txt` |
| `antlr:antlr:2.7.7` (445,288 bytes) | https://repo1.maven.org/maven2/antlr/antlr/2.7.7/antlr-2.7.7.jar | `88fbda4b912596b9f56e8e12e580cc954bacfb51776ecfddd3e18fc1cf56dc4c` | .sha1 (and .md5) | 2007-01-13 | public domain, `antlr2-public-domain.txt` |

**Pinning rule (14 days):** the newest of them, Google's four smali jars, were uploaded on 2026-09-04 (79 days
before 2026-11-22; google/smali's commit "Version 3.0.10" is of 2026-08-19); the newest dependency is jcommander 1.85
(2024-08-18). apktool 3.0.3 was released on 2026-07-20 (122 days); the Debian packages come from the pinned, signed
trixie archive (exempt). No release here is newer than the cut-off, and nothing is fetched at run time.

## How the class paths were made

Resolved from the POMs (`*.pom` beside each jar, and their parents `guava-parent` 31.1-android and 26.0-android,
`error_prone_parent` 2.11.0, `antlr-master` 3.5.2, `oss-parent` 7 and 9 for the versions they manage), as Maven
resolves a runtime class path: `compile` and `runtime` scope, transitively, `optional` and `test` left out, the
exclusions applied, the nearest version winning. Google's Gradle module metadata (`*.module`, the same upload) names the
same dependencies. Per tool:

- **baksmali** (`smali-baksmali` 3.0.10): smali-dexlib2, smali-util, Guava 31.1-android, jcommander 1.85, then through
  them jsr305 3.0.2 and Guava's failureaccess 1.0.1, listenablefuture 9999.0 (empty), checker-qual 3.12.0,
  error_prone_annotations 2.11.0, j2objc-annotations 1.3 - **11 jars**.
- **smali** (`smali` 3.0.10): the same, and ANTLR: `org.antlr:antlr` 3.5.2 (the tool, `compile` in Google's POM),
  antlr-runtime 3.5.2, stringtemplate 3.2.1 (named by smali's POM itself; optional in ANTLR's), ST4 4.0.8 (through
  the ANTLR tool), and ANTLR 2.7.7 (`antlr:antlr`, through stringtemplate) - **16 jars**. Left out: junit (test
  scope of ANTLR, StringTemplate and Error Prone). smali's POM excludes `org.antlr:antlr` below its runtime
  dependencies; nothing there names it, so the exclusion removes nothing.

smali's own classes reference only `org/antlr/runtime` of ANTLR (25 classes: the lexer, parser and tree-walker
runtime; and Guava, jcommander); of antlr-runtime only `tree/DOTTreeGenerator` references StringTemplate 3, and
StringTemplate 3 uses ANTLR 2 for its own templates. No class of smali references the ANTLR tool, ST4,
StringTemplate or ANTLR 2: they are on smali's class path because its POM names them (baksmali/smali's fat jar
carried the ANTLR tool and ANTLR 2 as well).

## The jars checked (what was done here)

1. **Every checksum the repositories publish** (above), and the SHA-256 pinned in the Dockerfile.
2. **The manifests.** Google's four hold only `Manifest-Version` (no `Main-Class`, no `Class-Path`): the main classes
   are `com.android.tools.smali.baksmali.Main` (in `smali-baksmali`) and `com.android.tools.smali.smali.Main` (in
   `smali`), named on the command line. No manifest of the 17 has a `Class-Path`, `Launcher-Agent-Class`,
   `Premain-Class`, `Agent-Class`, `Add-Opens` or `Add-Exports`; no jar is signed. **No native library** (`.so`,
   `.dll`, `.dylib`, `.jnilib`) and **no `META-INF/services`** (no service loader hook) in any of them.
3. **The class files belong to Google's sources.** Google's `-sources.jar` of the four (same repository, each matching
   its `.sha256`) hold 684 `.java` files; every top-level class of the four jars (155, 76, 992 and 16 classes) has
   its source file there, none is left over. Besides `com/android/tools/smali/`, Google's jars hold only
   `LICENSE`, `smali.properties`/`baksmali.properties` (`application.version=3.0.10`) and the manifest.
4. **What the code may reach** (every class file's constant pool read: method and class references). Google's jars:
   one `Runtime.exec`, `util/ConsoleUtil.getConsoleWidth` (`sh -c "stty size < /dev/tty"`, to wrap usage text; with
   our stdin on `/dev/null` and no terminal it fails harmlessly); no `ProcessBuilder`, no `System.getenv`, no
   `loadLibrary`, no socket, no URL, no class loader, no reflection call, no thread started; file writes in
   `baksmali/Baksmali`, `dexlib2/writer/io/{FileDataStore,FileDeferredOutputStream}` and `util/{PathUtil,
   RandomAccessFileOutputStream}` - the output we give them, a folder or file of our scratch. The dependencies:
   jcommander's `EnvironmentVariableDefaultProvider` (the only `System.getenv`) and `PropertyFileDefaultProvider`
   (a URL opened) are not used by smali's commands (we build the command line); `java.net.Socket` and `ServerSocket`
   only in antlr-runtime's remote-debug classes (`DebugEventSocketProxy`, `RemoteDebugEventSocketListener`, never
   started); `URL.openStream`/`URLClassLoader` in ST4's group loaders, Guava's `Resources`/`ClassPath` and
   `FinalizableReferenceQueue$DecoupledLoader`; ANTLR 2's `antlr/build/Tool` (the one `Runtime.exec` of the
   dependencies, a build helper of ANTLR's own) - none of them reached by baksmali or smali, and the container has no
   network anyway.
5. **Checked in CI before every build** (`maven-central.json`, `scripts/maven_central.py`; the step "Maven repository
   - the shipped jars against the release there", before the image is built; a difference fails the job, so no image
   of smali is pushed or signed without it): each of the 17 jars is downloaded from its repository with every
   checksum file published beside it (`.sha1`, `.sha256`, `.sha512`; the job's log and `maven-central-smali.json` in
   the artifact `ci-smali` say which there were), must match each of them - and at least one must be there - and
   must hash to the SHA-256 the Dockerfile pins, so the bytes `ADD --checksum` puts into the image are byte for byte
   the published jar. After the build, the step "The image ships the jars compared with their Maven repository"
   lists `/opt/smali` of the image: exactly these 17 files, each with its pinned SHA-256.

**History.** Until 2026-11-22 the image ran baksmali/smali's fat release jars (`baksmali-3.0.10-fat-release.jar`
`37ae4a41...`, `smali-3.0.10-fat-release.jar` `32fa0e88...`, GitHub assets of the third-party organisation
baksmali/smali; Google's repository was not reachable from here then). Their sources jars were checked against
Google's commit here (679 of 682 files byte-identical, the three others generated by ANTLR/JFlex), and CI compared
every file of Google's four jars with the fat jars: CI run 44945436428 found `smali/smaliParser.class` differing from
Google's (two calls in another order), and the human decided to ship Google's own jars instead. That file-by-file
comparison is gone from `scripts/maven_central.py`; what ships now is what Google and Maven Central publish.

## apktool 3.0.3 (read where the confinement depends on it)

Read: `brut/apktool/Main`, `brut/androlib/{ApkDecoder,ApkBuilder,Config}`, `brut/androlib/res/{AaptInvoker,
AaptManager,Framework}`, `brut/androlib/smali/{SmaliDecoder,SmaliBuilder}`, `brut/util/{OS,Jar,OSDetection,BrutIO}`,
and the whole jar scanned as above. What matters:

- **It starts one child process:** `brut/util/OS` (the only `ProcessBuilder` in the jar) runs **aapt2** for
  `build`, through `AaptManager`. apktool would unpack its own `prebuilt/linux/aapt2` into the temporary folder and
  `chmod +x` it (`brut/util/Jar.getResourceAsFile`, `deleteOnExit`); we never let it: the image carries that very
  binary at `/opt/apktool/aapt2` (checked by SHA-256) and `apktool_build` always passes `--aapt`. So nothing is
  unpacked or made executable at run time - which also means a `noexec` `/tmp` cannot break the tool.
- **The framework file.** `brut/androlib/res/Framework` reads `XDG_DATA_HOME` (and `System.getProperty`) to find its
  frame path, and installs its bundled `android-framework.jar` there. We always pass `--frame-path
  /opt/apktool/framework`, prepopulated with that file as `1.apk` when the image is built, so the variable is never
  read (our children get `PATH`, `LANG`, `HOME` only) and the read-only root is never written. Tested: decode and
  build work with that folder mode `0555`.
- **`OSDetection`** reads `os.name`, `PROCESSOR_ARCHITECTURE`, `PROCESSOR_ARCHITEW6432`, `sun.arch.data.model` -
  nothing else of the environment.
- **No network:** no `java.net` client, no URL opened anywhere in `brut/`; the one `java.awt` reference is the
  nine-patch image decoder.
- **It writes inside the folder it builds** (`build/`, `dist/`) - which is why `apktool_build` only takes a folder
  of `/out` and never one of the read-only `/work`.
- The jar carries **smali 3.0.9-dev** (`baksmali.properties`, `smali.properties`) for its own decode/build; apktool
  uses that, the `smali` server's own tools use Google's pinned 3.0.10 jars. Both are recorded in the answers
  ("baksmali 3.0.10", "apktool 3.0.3").
- Google's **aapt2 2.20** binary we ship is a prebuilt executable inside apktool's release: it cannot be reviewed as
  source. It runs only as `aapt2 compile|link` on the folder apktool is building, in a container without network,
  as a user who is not root, with a read-only root file system apart from `/out` and our scratch folder.

## Tools

Eleven: six read-only (`readOnlyHint`, `openWorldHint: false`), five that write into `/out`. Plain-text answers: at
most **400 lines or 24,000 characters** per answer, a numbered line each, the next part named.

| Tool | What |
|---|---|
| `list_files` | the files in `/work` these tools read (`.apk .dex .jar .apks .xapk .apkm .zip .odex .oat`; `show_all` for every file), with sizes, 12 folders deep, at most 300; no link followed |
| `list_output` | every file in `/out` with its size (what the write tools made) |
| `list_dex` | the DEX files inside an APK, APKS or JAR (`classes.dex`, `classes2.dex`, ...), read by the server itself (`zipfile`), or "a plain DEX file" |
| `list_classes` | the classes of an app (baksmali `list classes`), with `package`, `name_filter`, `dex_file` and `offset` |
| `get_smali` | one class's smali (baksmali `disassemble --classes`), in parts (`start_line`); `debug_info`, `use_locals`, `api_level` |
| `search_smali` | a text in the smali of every class, with class and line; the app is disassembled once into the scratch folder, at most 20 s per call, `start_class` goes on |
| `disassemble` | a whole app (or `classes=`) to smali files in `/out/OUT_NAME` |
| `assemble` | a folder of `.smali` files back into a DEX in `/out` (smali `assemble`, `api_level`) |
| `apktool_decode` | apktool `decode` into `/out/OUT_NAME`: manifest, resources, smali (`no_resources`, `no_sources`, `only_manifest`, `no_debug_info`, `keep_broken_resources`) |
| `apktool_build` | apktool `build` of such a folder of `/out` into an **unsigned** APK in `/out` (`debuggable`, `network_security_config`, `copy_original`) |
| `sign_apk` | zipalign, then a **throwaway** 2048-bit RSA key made by `keytool` for this one call (random password, one day valid, `CN=sandbox-ai-mcp throwaway debug key`), then `apksigner sign` (v1+v2+v3) and `apksigner verify --print-certs`; the keystore and its password go with the scratch folder |

## Audit of our code (`src/server.py`, read in full)

**Input files and folders.** A path is relative to `/work` (or `/out`, where a tool may read back what it made) or
absolute under one of them; `..`, `~`, control characters, names over 255 bytes and anything outside the two roots
are refused. Every path is walked one name at a time with `openat(O_NOFOLLOW)` from the root's descriptor: a link
anywhere on the way is refused by name, a folder where a file belongs is said so, and only a regular, non-empty file
of at most 512 MiB is opened. `list_files`/`list_output` never enter or list a link, look at at most 20,000 entries,
12 folders deep, and show at most 300 files. A folder given to `assemble` or `apktool_build` is measured first (at
most 50,000 files and 2 GiB).

**What the children get.** One place starts a process (`run`, exactly one `subprocess.Popen`): the command line is
built here - never a string a call gave - with an empty environment but `PATH=/usr/bin:/bin`, `LANG=C.UTF-8` and
`HOME=<scratch>/run`, stdin `/dev/null`, its own session (killed as a group), the working folder a fresh empty
folder below `/tmp`, and a time limit per tool (baksmali 60 s, smali 120 s, apktool 300 s, signing 120 s). The JVM
runs with a heap of 70 % of the cgroup's `memory.max` (at least 192 MiB; 768 MiB without a limit),
`-XX:+ExitOnOutOfMemoryError`, `-XX:-UsePerfData`, `-XX:+DisableAttachMechanism`, `-XX:ErrorFile=/dev/null`,
`java.io.tmpdir` and `user.home` in the scratch folder. Output is read to at most 16 MiB (more: the process group is
killed and the call says so), stderr to 1 MiB (its last lines explain a failure).

**The file a tool sees is the file that was checked.** The checked descriptor is passed to the child (`pass_fds`) and
linked in the scratch folder as `/proc/self/fd/N`, so a rename in `/work` between the check and the run cannot swap
it. The one exception is `apktool_build`: apktool starts aapt2 with paths of its own, which that link would not
resolve in the child, so it is given the real path of the folder - a folder of `/out`, opened with the same
`openat` walk, with the descriptor kept open while apktool runs and `(st_dev, st_ino)` of path and descriptor
compared right before the start ("changed while it was being read: try again").

**Arguments.** Class names are normalised and checked (`org.example.A`, `org/example/A`, `Lorg/example/A;`,
`Outer$Inner`; no comma, no space, no `-`, no `..`, nothing starting with `-`), so nothing a call gives can become
an option of baksmali's `--classes`. A DEX entry may not start with `-` or `/` and may not hold `..`; it is appended
to the input path as baksmali takes it (`app.apk/classes2.dex`). Every name a tool writes in `/out` is one path
segment of letters, digits, `.`, `_`, `-` (at most 64 characters). API levels are whole numbers 1-36. Of apktool's
options only the five decode flags and three build flags in `APKTOOL_DECODE_FLAGS` / `apktool_build` can be
switched on, each a fixed flag; never an output folder, a framework path, a library (`--lib`), an `--aapt` or a
frame tag from a call.

**What is written.** Only the scratch folder and, at the end of a call, one new name in `/out`: a tool builds its
result in the scratch folder and it is moved into place (`rename`) only if that name does not exist yet - nothing in
`/out` is ever overwritten or deleted, and a name that is a link is refused (`lexists`). Without a writable `/out`
the read tools work and the write tools say what to mount.

**Signing.** No key of yours is read and none is in the image: `keytool` makes a 2048-bit RSA key per call with a
random password (`secrets.token_urlsafe(24)`), valid one day, in the scratch folder, and the folder is removed in a
`finally` - so the key cannot sign a second APK. The password is in no answer and in no log line. The answer says
plainly that a device which knows the previous throwaway key refuses the new APK.

**Answers.** Every shown line loses control characters, NEL, the Unicode line/paragraph separators and the
bidirectional controls; a line over 2,000 characters is cut; titles and class names from the input pass the same
filter; lists at most 300 entries, searches at most 200 results. **Tools only:** the resource and prompt handlers
are removed. **Network:** none (no socket, no URL, nothing imported that could). **Environment:** none read.

## Self-review: what was found and changed while writing it

1. `apktool_build` failed with the `/proc/self/fd` link: apktool starts aapt2 with `<folder>/res`, which that child
   cannot resolve. It now gets the real path of a folder of `/out`, with the descriptor-identity check above.
2. apktool would have unpacked its own aapt2 into `/tmp` and `chmod +x`'d it (broken on a `noexec` `/tmp`, and an
   executable written at run time): the binary is in the image and `--aapt` always passed.
3. apktool installs its framework into the frame path on first use: the image prepopulates
   `/opt/apktool/framework/1.apk`, so the read-only root is never written.
4. The first version built the apksigner command line by cutting `-jar` off the JVM's flags, which left the jar out
   ("Unable to access jarfile"); `class_path_command` now builds it from the flags alone.
5. A DEX entry was first passed as `--dex-file`, an option baksmali does not have; it is part of the input path.
6. `sign_apk` first kept the keystore beside the APK in `/out`; it never leaves the scratch folder now.
7. baksmali and smali first ran from baksmali/smali's fat jars (`-jar`); CI found one class of them differing from
   Google's, and they run from Google's own jars on a class path now (`baksmali_command`, `smali_command`).

## Tests

- `tests/test_smali.py` (29 tests): paths and folders (`..`, outside the roots, links, pipes, folders, empty and
  oversized files, `~`), class names, `/out` names and DEX entries that would become options, the API level and
  flags, an existing name in `/out` (never overwritten), a missing `/out`; the command lines against a stand-in
  (baksmali and smali from their class paths with their main classes, the descriptor read through `/proc/self/fd`, the entry behind the path, the API level, only the apktool flags a
  call may set, apktool's `--aapt` and `--frame-path`, the environment exactly three variables, an empty working
  folder, the scratch folder removed, a tool that hangs or floods, the throwaway key with a random password that is
  in no answer); answers in parts and control characters filtered; tools only, against `tools.json`. With the real
  tools (6 of the 29): `list_dex`, `list_classes`, `get_smali` (with and without debug info, `.locals`),
  `search_smali`, `disassemble` → `assemble` round trip (the DEX read back with `list_classes`), `apktool_decode` →
  `apktool_build` (unsigned: no `META-INF/*.RSA`) → `sign_apk` (verified, certificates printed), `only_manifest`,
  and broken inputs. Run here on 2026-11-19 against the fat jars of the time, apktool 3.0.3 with its own aapt2,
  Debian's zipalign and apksigner 35.0.2 on Temurin 21.0.9: 27 of 27 passed. With Google's jars the 6 run in CI
  inside the image (no JVM here on 2026-11-22: the 23 others pass here).
- `tests/test_maven_central.py`: the CI check itself (a pin that is not the published jar, a published checksum that
  differs, none published, a jar from another repository or another artifact's URL, the image's folder with a jar too
  many or one changed) and smali's spec: the 17 coordinates, each from its own repository.
- `tests/test_own_servers.py` `test_smali`: over stdio as the image starts it, then the suite above (in CI inside
  the image with its own tools).
- `tests/test_analysis_servers.py` `AndroidTools`: every jar's URL and SHA-256 (ARG, `ADD --checksum`, here), the
  class paths and main classes (server and Dockerfile the same), a licence for every bundled library, no network, `/work` read-only and `/out` writable, limits,
  imports, the one process start, the options apktool can get, the throwaway key.
- `smoke.json`: every tool on the fixtures (`demo.apk`, `demo-res.apk`), then five refused calls (`/etc/passwd`,
  `..`, an `out_name` of `../escape`, a misspelled class, `apktool_build` on `/work`).
- Fixture `demo-res.apk` (`tests/fixtures/analysis-files.json`, pinned by SHA-256): the DEX of `demo.apk` in an app
  with a resource table, built here with apktool's aapt2 - apktool's build step needs one, and `demo.apk` has none.

**Not run here (no container engine, no JVM):** the image build with its `--version` checks, the six tests with the
real tools, the smoke spec under Podman and Bubblewrap, Trivy. Signing waits for CI to build the image and both smoke
runs to pass, after the check of every jar against its repository (point 5).
