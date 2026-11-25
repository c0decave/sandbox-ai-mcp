# burp - provenance and audit

| | |
|---|---|
| MCP server | PortSwigger's **MCP extension 1.4.0** for Burp Suite (PortSwigger/mcp-server, GPL-3.0, `LICENSES/burp-mcp-GPL-3.0.txt`): commit `291034081160bc944b6df3eccd60c6fc99b477e1` of main, 2026-11-05 ("Update BappManifest.bmf"; version 1.4.0 = BApp serial 12). Upstream publishes no tags or releases; the commit is 20 days old on 2026-11-25. Built in the image's build stage from that commit (checked by `git rev-parse`, then every file the build reads by SHA-256: `burp-mcp-files.sha256`, and nothing else under `src/main`), with `patches/0001-sandbox-ai-mcp.patch` |
| Our code | `src/server.py` (Python standard library, MIT, `LICENSES/sandbox-ai-mcp-MIT.txt`): the image's entry point - runs your Burp headless with the extension and relays MCP over stdio to it (container mode), or lists the extension's tools without Burp; `check_dependencies.py`, `runtime-deps.init.gradle` (build stage only) |
| Not used | `libs/mcp-proxy-all.jar` (a prebuilt 15 MB fat jar of PortSwigger/mcp-proxy that upstream's `embedProxyJar` puts into the extension: not reviewable here, deleted before the build), the Gradle wrapper (`gradle/wrapper/gradle-wrapper.jar`, `gradlew`), the tests (`ProxyEndToEndTest` runs the proxy jar), the Codex plugin files (`plugins/`, `.agents/`), `.github/` |
| Build tools | Gradle **9.2.0** (2025-10-29; the version upstream's wrapper names), `gradle-9.2.0-bin.zip` of gradle/gradle-distributions by the SHA-256 GitHub publishes (`ADD --checksum`); Debian trixie `openjdk-21-jdk-headless=21.0.13.1+2-1~deb13u1`; the Gradle plugins upstream declares (Kotlin 2.4.0 JVM and serialization, `io.ktor.plugin` 3.3.1 for its shadow jar, `org.gradle.toolchains.foojay-resolver-convention` 1.0.0 - never asked: auto-download is off and the JDK above is the toolchain) from the Gradle plugin portal and Maven Central over TLS: **not hash-pinned** (no `verification-metadata.xml` upstream; see "Open") |
| Runtime dependencies | what the fat jar is made of (Gradle's `runtimeClasspath`), **each jar checked in the build against Maven Central's published `.sha1`/`.sha256`** (`check_dependencies.py`; a difference fails the build); the list with SHA-256 and POM licences is in the image as `/opt/burp-mcp/runtime-dependencies.json` |
| Image | Debian trixie-slim (the digest in `Dockerfile`, as the other servers), `tini=0.19.0-3+b8` (the image's init, its ENTRYPOINT: no host init needed), `openjdk-21-jre-headless=21.0.13.1+2-1~deb13u1`, `python3=3.13.5-1`; `/etc/hosts` of its own (the Bubblewrap form); user 10001; `/opt/burp-mcp/burp-mcp-all.jar` with its `.sha256`, the patch beside it (GPL: the source of what we changed ships with the binary) |
| Burp Suite | **not in the image, never redistributed**: container mode runs the jar you mount at `/burp` (PortSwigger's terms for Burp Suite Community and Professional allow your own use, not passing it on). sandbox-ai records your jar's SHA-256 when you add it (`BURP_JAR_SHA256`); `server.py` refuses a jar that changed since |

**Pinning rule:** the commit is 20 days old (>= 14). The MCP Kotlin SDK 0.16.0 it brings was published on Maven
Central on 2026-10-27 (29 days); Ktor 3.5.2 (2026-07-31), kotlin-stdlib 2.4.21 (2026-10-08), kotlinx-coroutines
1.11.0 (2026-05-07), kotlinx-serialization 1.11.0 (2026-04-09), Netty 4.2.6.Final (2025-09-08) - all older than
14 days. They are what upstream's build resolves at this commit (no version of ours).

## The audit (2026-11-25)

Read completely: every file of the commit except the binary ones - `src/main` (31 Kotlin files, 4,144 lines),
`build.gradle.kts`, `settings.gradle.kts`, `gradle.properties`, `gradle/libs.versions.toml`, the tests (`src/test`,
read for what they run), `.github/workflows/ci.yml`, `dependabot.yml`, `BappManifest.bmf`, `BappDescription.html`,
`README.md`, the Codex plugin (`plugin.json`, `.mcp.json`, `skills/burp-mcp/SKILL.md`, `marketplace.json`),
`gradlew`/`gradlew.bat` (not used). Of the MCP Kotlin SDK 0.16.0 (MIT): the server module read where the extension
uses it (`KtorServer.kt`: `mcp {}` and `mcpStreamableHttp`, the session manager, `HostValidation.kt`, the Streamable
HTTP transport's header checks); its 89 source files (17,969 lines, the sources jars of Maven Central) searched for
processes, files, environment, class loading, URLs and sockets: nothing but `java.net.URI` parsing.

### What the extension does

- **Listens** (Netty, through Ktor) on `config.host:config.port`, default **127.0.0.1:9876**: legacy SSE at `/`,
  Streamable HTTP at `/mcp` (JSON answers). **No authentication.** Its own checks: a `Host` header other than
  `localhost`/`127.0.0.1` (with the configured port) gets 403, so does an `Origin` or `Referer` of another host and
  any `User-Agent` that looks like a browser (`mozilla/`, `chrome/`, ... `browser`) - against DNS rebinding, not
  against a local process. The SDK adds its own localhost host and origin checks; sessions end after 30 idle
  minutes; request bodies up to 4 MiB. The host field takes any name (`0.0.0.0` too): sandbox-ai warns when Burp's
  port listens on anything but loopback.
- **Sends** nothing by itself: no telemetry, no update check, no outbound connection. The tools make Burp send what
  the client asks: `send_http1_request`, `send_http2_request` to the host and port in the call (through Burp's
  `api.http()`, so with Burp's upstream proxy and TLS settings); Collaborator (Professional) through Burp's client.
- **Writes** only on a click in Burp's MCP tab: "Install to Claude Desktop" rewrites Claude Desktop's
  `claude_desktop_config.json` (after a confirmation), "Extract server proxy jar" writes the proxy jar to
  `~/.BurpSuite/mcp-proxy/` and where you save it. **Without the proxy jar (our build) both only say it is
  missing.** Its settings live in Burp's extension data (in the project). The "Learn more" links open a browser.
- **Reads**: Burp's proxy HTTP and WebSocket history, the Organizer, scanner issues, project and user options, the
  focused message editor - each only through a tool. Exported options have `password`, `certificate_password` and
  `hashed_key` replaced (on by default, "Filter config credentials"; malformed JSON fails closed).
- **Approvals** (Burp's own dialogs, on by default): before a request to a host not auto-approved, and before
  history/Organizer reads. They block the call until answered; a call that ends cancels its dialog (1.4.0). The
  auto-approve list checks wildcards label by label and refuses commas (a fix of 1.2.2).
- **The two tools that can execute code**: `set_project_options` and `set_user_options` merge any JSON into Burp's
  configuration (user options include the extensions Burp loads, and an upstream proxy). They refuse unless "Enable
  tools that can edit your config" is ticked (off by default; the tab itself warns "Can execute code"). Our patch
  keeps them off in the container, and the preset's rules deny them everywhere.
- `get_active_editor_contents`/`set_active_editor_contents` act on whatever editor has the focus in Burp's window.
- No `Runtime.exec`, `ProcessBuilder`, reflection beyond `kotlin.reflect` for the tools' schemas, `System.getenv`;
  `System.getProperty` for `os.name`, `user.home`, `java.home` (the installers' paths) - and in our patch
  `sandbox.ai.burp.mcp`.

**Tools: 24 in Community, 27 in Professional.** Only with Burp Suite Professional (registered when
`api.burpSuite().version().edition() == PROFESSIONAL`, `Tools.kt`): `get_scanner_issues`,
`generate_collaborator_payload`, `get_collaborator_interactions`. Everything else works in Community
(Intruder there is Community's, throttled).

### Findings (none a backdoor; what they mean here)

1. **An unreviewable binary in the repository**: `libs/mcp-proxy-all.jar` is embedded by upstream's documented build
   (`./gradlew embedProxyJar`) and executed by a test. Removed before our build; our jar does not contain it
   (checked in the build). Its source is PortSwigger/mcp-proxy; we need no stdio proxy (sandbox-ai speaks to `/mcp`).
2. **No authentication on the endpoint**: any local process (any user's, on a shared host) can drive Burp through
   127.0.0.1:9876. Upstream's model; sandbox-ai never opens that port to an agent's sandbox - the host mode relay
   runs on the host behind sandbox-ai's MCP gateway, and container mode keeps the port inside the server's container.
3. **Config-editing tools can execute code** (see above): off by default upstream; off in our container mode; denied
   by the preset's rules.
4. **Burp's approval dialogs cannot work headless** (`JDialog` throws `HeadlessException`: the call fails closed with
   "Error: ..."). Our patch switches them off in the container only (`-Dsandbox.ai.burp.mcp=container`); sandbox-ai's
   MCP rules ask instead.
5. **A regex from the client** (`get_*_regex`) is compiled with `Pattern.compile` and run over the whole history in
   Burp's JVM: a catastrophic pattern ties up a thread (no time limit). Accepted (the client is the agent; the
   container has its limits; in host mode it is your Burp).
6. **Not reproducible upstream**: the manifest carries `Built-By` (the user name), `Built-Date` and `Built-JDK`. Our
   patch removes them; Gradle's archives are already without timestamps and in a fixed order.
7. Netty 4.2.6.Final comes with `ktor-server-netty` 3.3.1 while the SDK lifts other Ktor modules to 3.5.2 (upstream's
   own build has the same mix). CI's Trivy scan fails the image on a CRITICAL with a fix, as for every server.

### Our patch (`patches/0001-sandbox-ai-mcp.patch`, applied with `git apply`)

- `ExtensionBase.kt`: when the JVM runs with `-Dsandbox.ai.burp.mcp=container` (only `src/server.py` starts Burp so),
  the settings the MCP tab would set: enabled, 127.0.0.1:9876, config editing off, Burp's approval dialogs off,
  credential filtering on. Without the property nothing changes - the same jar is the one for your own Burp.
- `build.gradle.kts`: no `Built-By`, `Built-Date`, `Built-JDK` (and the unused `Instant` import).

### Container mode (`src/server.py`, read in full; tests/test_burp.py)

- **Starts** `java -Djava.awt.headless=true -Xmx<75 % of the memory limit> -XX:+ExitOnOutOfMemoryError
  -Duser.home=/data -Djava.io.tmpdir=/data/tmp -Dsandbox.ai.burp.mcp=container -jar /burp/<your jar>
  --user-config-file=<the extension, loaded> --disable-auto-update [--project-file=/data/burp-project.burp]`
  (the project file with Professional only); environment `PATH`, `LANG`, `HOME` only; its own session, ended with the
  connection.
- **Questions**: Burp's headless start asks for the terms (`y`), Professional for the licence key (`BURP_LICENSE`)
  and the activation method (`o`: online, portswigger.net). Each at most three times; an unknown question ends in the
  start's time limit (240 s, `BURP_START_TIMEOUT`) with Burp's last lines. The key is typed into Burp's stdin and
  nowhere else; it is removed from the environment of the server, and Burp's output reaches the log with it
  replaced by `[BURP_LICENSE]`.
- **Activation**: online, once - Burp keeps the licence in its Java preferences below `/data` (sandbox-ai's own
  folder of the server, kept). Every activation counts against your licence's activations; a container without a
  writable `/data` activates again each time (said in the log).
- **One connection at a time** per `/data` (a lock): Burp's licence and project live there.
- **Relay**: MCP `initialize` and `tools/list` are answered at once (the extension's tools as `Tools.kt` registers
  them, for the edition given), tool calls wait for Burp and go to `http://127.0.0.1:9876/mcp` inside the
  container (a session, opened again when the extension forgot it), answers come back unchanged; when the
  extension's real tools differ from those listed, `notifications/tools/list_changed`.
- **Network**: the catalog's `full` (the internet, never your LAN or this host) - for the targets and for the
  activation; a target in your network needs `--network lan` or `--allow-private` (your choice, said with a warning).

## Open (said in the report; for the lead)

- The Gradle plugins and the Kotlin compiler are trusted by TLS, not pinned by hash. Pinning them needs a
  `gradle/verification-metadata.xml` written by Gradle once (`--write-verification-metadata sha256`) and reviewed;
  proposed as the next step after the first CI build. The runtime jars that end up in the extension are checked
  against Maven Central in every build.
- Nothing here ran a real Burp: whether Burp's headless start asks exactly the questions `server.py` answers, loads
  the extension from `--user-config-file`, and whether the extension's Swing tab can be made headless, is what the
  live check `burp-live` (sandbox-ai's `docs/LIVE_CHECK.md`) proves with your Burp jar.
- Design note, not built: the agent's own HTTP traffic through Burp's proxy (to see it in Burp's history). It would
  chain behind sandbox-ai's connection proxy, never around it: the connection proxy decides first (allow-list,
  approvals, the privacy check, the kill switch), then hands allowed connections to Burp's listener as its upstream
  (host mode: 127.0.0.1:8080 on the host; container mode: a listener the server's container would have to publish),
  with Burp's CA added to the sandbox's trust store for that start only, and the provider's (LLM) traffic never
  through Burp. Not done here: it changes the connection proxy, which this feature leaves as it is.
