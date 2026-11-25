# frida - provenance and audit

| | |
|---|---|
| MCP server | this repository: `src/server.py` (Python, the MCP SDK, frida's bindings), MIT (`LICENSES/`), written for this repository and reviewed in full (below) |
| Frida | **17.25.2** (frida/frida, wxWindows Library Licence 3.1, `LICENSES/frida-wxWindows-3.1.txt`), released **2026-11-02** (tag `17.25.2` = commit `29016dbd9d8fce836b2b86892b04cc31c2f767aa`) |
| Python bindings | `frida==17.25.2` from PyPI, hash-locked in `requirements.txt`: `frida-17.25.2-cp37-abi3-manylinux_2_5_x86_64.whl` SHA-256 `55cb5f7f6f75922a37e451449ec71e695400e3d6a009c275c285abf88a49dd53` and the `manylinux1_x86_64` wheel `226998c9b3cb79d99871138533d2c58525ede3b1ea45647c6483d28ced8abb73` (both uploaded 2026-11-02; the image is `linux/amd64`) |
| Device binaries | the 12 release files below, each by the SHA-256 GitHub publishes for the asset (`ADD --checksum`), kept **as published** (xz) in `/opt/frida/<platform>/<abi>/` - 197 MiB |
| adb | Debian trixie `adb=1:34.0.5-12` (android-platform-tools), run only against the adb server the human configured |
| Python packages | `mcp==1.30.0` and its dependencies, hash-locked in `requirements.txt` (the shared lock of the other servers, with `frida` added) |
| Debian packages | `tini=0.19.0-3+b8` (the image's init, its ENTRYPOINT: no host init needed), `python3=3.13.5-1`, `python3-venv=3.13.5-1` (purged after the venv is made), `ca-certificates=20250419+deb13u1` (pip's download while building), adb above |
| Base image | the `debian:trixie-slim` digest in `Dockerfile` (the same as the other servers') |

**Pinning rule (14 days):** Frida 17.25.2 was published on 2026-11-02 - 17 days before this was written, so it is
old enough; 17.26.x and 17.27.x (2026-11-05 to 2026-11-19) are **not** and were deliberately left out. The client
and the `frida-server` on the device must be the same version, so one version is pinned for all of them (the
Dockerfile's version check and `tests/test_analysis_servers.py` keep it that way).

## The binaries in the image (every Android ABI)

Each is the release asset of 17.25.2, pinned by its published digest:

| Platform/ABI | frida-server (SHA-256) | frida-gadget (SHA-256) |
|---|---|---|
| android/arm | `7fb906385e3dd99ff11dc3068ee2441cf58ecbb8cf13fbd457db62e0c03d3640` | `7825e2949268f4a23d38f8aaa3690e3659fd5c730e8062d4913ea0b308b933e1` |
| android/arm64 | `08d7b7f02256621c9089cecd6495a5eb43861bf560a7ed86ad376e75d16a1fb6` | `8c527f7844932ef0b66d99b38cc7191380e52907ca43c82f2acb6b7801945798` |
| android/x86 | `9957c81b3c60fbb48774814ea17136efa47f0da0aaac518022d097db41b9e1ba` | `bae97edf0bef867e550a1cb84775edb3461c0bf170138f587a5a668b69d5f2f6` |
| android/x86_64 | `ee675076d25599dd55c3b080ccf61c02b44d00653a06db2b0e2a2149ef69dad1` | `2924dd5ac38b33065223ac747712ee5c83a41d1a8a7fbbc3b292e8600e826a27` |
| linux/x86_64 | `2b9356fb2aab71e87cb50b6aa4dfef06892ca5851bc7013278d88754b6642ad1` | `1549939529077bc99b0dbf19c7fc4a62e11b0b77499bc73b3e4a7ef83ec24ec6` |
| linux/arm64 | `c0ee2aea83081fbfec4e2655d507d297d8df58df56c84dea56277d957fe64432` | `82e2271667f94f9da104b560b6c8d4b24763d9dc6e022548e80b30b7e35901f0` |

**Android: all four ABIs Frida publishes** (arm, arm64, x86, x86_64), as the brief asks. Of the Linux ones only
x86_64 and arm64: the remaining ten (musl, armhf, armbe8, arm64be, mips, mipsel, mips64, mips64el and the portal
binaries) would add another 127 MiB to an image that is already 197 MiB of binaries, and nothing here needs them -
adding one is two lines in the `Dockerfile` plus its digest. `frida-inject` and `frida-portal` are not shipped: no
tool starts them.

The files stay **xz-compressed, exactly as published**, so the image carries the very bytes whose digest is pinned
and nothing in `/opt/frida` is executable (`chmod -R a-x,a+r`). `export_server` unpacks one into `/out`,
`push_server` into its scratch folder right before the `adb push`; both stop at 256 MiB of output.

## What is deliberately not shipped: frida-tools

`frida-tools` (the `frida`, `frida-trace`, `frida-ps`, ... CLIs) is **not** in the image, although the brief names
it. Its release carries the agents those CLIs inject - `tracer_agent.js` (256 KB), `fs_agent.js` (147 KB),
`itracer_agent.js` (33 KB), the bridges `java.js` (237 KB), `objc.js`, `swift.js` - and `tracer_ui.zip`, a 12 MB
web application; that is ~700 KB of generated JavaScript plus a bundled UI, none of it reviewable completely to this
repository's rule, and all of it code that would be injected into a target process. The server does not need it: it
drives the bindings itself (`create_script`, `enumerate_processes`, `enumerate_applications`, `spawn`, `attach`),
and a script the agent writes (or one of yours from `/work`) does what `frida-trace` would. **For the user:** if you
want `frida-trace`'s tracing, say so - it needs its own review of those agents, or an own tracing script of ours.

Note what *is* unavoidable: the bindings' `_frida.abi3.so` (141 MiB in the wheel) is Frida's own prebuilt core, and
`frida-server` is a prebuilt device binary. Neither can be reviewed as source, as with signal-cli's release in
`servers/signal`; both are pinned by the digest their publisher published, run without network except the one
configured endpoint, as a user who is not root, with a read-only root file system apart from `/out` and the scratch
folder.

## What this server can reach (the important part)

Nothing, until the human configures it, and then exactly that:

- `FRIDA_DEVICE=HOST:PORT` - checked against `HOST:PORT` (or `[IPv6]:PORT`) before anything connects, then given to
  `add_remote_device` **once**; the one place in the file where a device is added.
- `FRIDA_ADB_SERVER=HOST:PORT` - checked the same way, put into `ANDROID_ADB_SERVER_ADDRESS`/`_PORT` **before frida
  is imported** (frida reads them when it first looks at USB devices) and passed to every `adb` call as `-H`/`-P`
  with that same environment. `adb` is the only process this server starts (one `subprocess.run`), with
  `PATH=/usr/bin:/bin`, `HOME=/tmp`, `LANG`, those two variables, stdin `/dev/null`, its own session and a time
  limit; every argument is built here.
- **frida's local device is never offered**: `wanted()` refuses the names `local`, `socket` and `barebone` by name,
  before anything is reached, and `list_devices`/`device_status` only ever show the configured remote device and the
  USB devices of the configured adb server. This matters: Frida's local device would be *this container* - the MCP
  server's own process among them.
- `get_usb_device`, `get_local_device` and `enumerate_devices`-without-filter are not used for anything a tool
  returns.

**What sandbox-ai must do for it (said in the catalog entry's notes, and worth repeating):** the entry is `network:
full`, which in sandbox-ai 0.1.98 and newer means the internet and **never** your local network, this host or the
clouds' metadata service. A device or adb server in your own network is a private address, so it has to be opened on
purpose: `sandbox-ai mcp set frida --allow-tcp 192.168.1.33:27042`. An adb server on the host that runs sandbox-ai
(`--allow-host-port 5037`) is **not** reachable from an MCP server's container at all - its connections go through
pasta without the host's loopback or its forwarded ports. For that case use adb in the agent's own sandbox (the
`android` image of sandbox-ai, started with `--allow-host-port 5037`), or make the device reachable by TCP.

## Tools

Sixteen: eight read-only (`readOnlyHint`), four that act without changing the device (`attach`, `detach`,
`run_script`, `export_server`) and four that change it (`destructiveHint`, all behind `FRIDA_WRITE=1`).
`openWorldHint` is true everywhere: a device is the outside world.

| Tool | What |
|---|---|
| `device_status` | what is configured (`FRIDA_DEVICE`, `FRIDA_ADB_SERVER`, `FRIDA_WRITE`, the folders), whether it answers, and that this container's own processes are never offered |
| `list_devices` | the configured device and the adb server's USB devices, with what each reports (os, platform, arch, access) |
| `list_processes` | pid and name of the device's processes (`name_filter`, `offset`) |
| `list_applications` | the installed apps (identifier, name, pid; `only_running`, `name_filter`, `offset`) |
| `list_abis` | the `frida-server`/`frida-gadget` binaries in the image, with their sizes |
| `export_server` | unpacks one of them into `/out` (never over an existing name), with what to do with it |
| `push_server` | the one that fits a USB device's ABI (`getprop ro.product.cpu.abi`, mapped to the image's ABIs) pushed into `/data/local/tmp` (or another folder below `/data`, `/sdcard`, `/storage`; no `.` or `..`) and started as root - `FRIDA_WRITE=1` |
| `attach` | attach to a running process by pid or name; the session is kept (at most 8) |
| `list_sessions` / `detach` | the sessions, and ending one |
| `run_script` | a script given inline or read from `/work` (`.js`, at most 256 KiB), loaded into an attached process; the messages it posts are collected for 1-120 s (at most 200, each at most 4,000 characters) |
| `enumerate_modules` | the loaded libraries of an attached process (name, base, size, path) |
| `enumerate_exports` | the exports of one library (`type`, name, address) |
| `spawn` | an app started and held before its first instruction, attached to - `FRIDA_WRITE=1` |
| `resume` / `kill` | let a held process run, or stop a process - `FRIDA_WRITE=1` |

## Audit of our code (`src/server.py`, read in full)

**Arguments.** Every tool argument goes through a checker: endpoints (`HOST:PORT`), device names (the three names of
frida's own devices refused), programs and application ids (`com.example.app`, `/system/bin/sh`; no `--option`, no
`..`, no spaces, at most 256 characters), module names, pids (1 to 4,194,304), `seconds` (1-120), `max_messages`
(1-200), `offset`, `abi`/`platform`/`kind` against what the image has, `out_name` one path segment of letters,
digits, `.`, `_`, `-`. A target folder on the device must be below `/data`, `/sdcard` or `/storage` and may hold no
`.` or `..` segment. Arguments are checked before any file is looked at.

**Scripts.** Either inline (at most 256 KiB) or from `/work`: the path is walked one name at a time with
`openat(O_NOFOLLOW)`, no `..`, no link followed, only a regular, non-empty `.js`/`.mjs`/`.ts` file of at most
256 KiB. A script is **not** parsed or rewritten here - it is handed to the device as it is, where it runs in the
target process. That is the point of the tool, and it is why the catalog entry says plainly: a script can read and
change everything the app may. The module name of `enumerate_exports` reaches the device as JSON
(`json.dumps`), never spliced into code, and the expressions of `enumerate_modules`/`enumerate_exports` are our own
strings.

**Messages from the device.** Collected by a handler with a lock, at most `max_messages`, each cut to 4,000
characters, every line passed through `shown()` (control characters, NEL, the Unicode line/paragraph separators and
the bidirectional controls replaced; a line over 2,000 characters cut), then paged (400 lines / 24,000 characters).
An `error` message is shown as its description and the first 400 characters of its stack. Binary data is counted,
never shown. A payload that is not a string becomes JSON. Nothing from a device is ever used as an argument of
anything.

**Sessions.** At most 8, each with its device, target and the scripts loaded into it; a detached session is dropped
and says so ("attach again"). `DEVICES.close()` in the `finally` of `main` detaches everything and removes the
remote device.

**Errors.** frida 17 raises each of its errors straight from `Exception` and has **no** `frida.FridaError` base
class (found while writing this: an `except frida.FridaError` would have been an `AttributeError` at run time). The
server gathers the error classes the bindings have (`FRIDA_ERRORS`, `frida_error(name)`) and turns them into
answers that say what to do: a `frida-server` that does not answer, a broken connection, a device that refuses
(and that a non-root `frida-server` cannot see other apps), a process that is gone, something the device does not
support. Nothing else leaks: an unexpected exception is logged by type and answered as "internal error (Type)".

**What is written.** Only `/out` (one new file per `export_server`, never over an existing name) and the scratch
folder below `/tmp` (one unpacked binary per `push_server`, removed in a `finally`). `/work` is only read.

**Tools only:** the resource and prompt handlers are removed. **Secrets:** none - the three variables are addresses
and a flag, none marked secret, none printed anywhere but in `device_status` (where the human put them).

## Self-review: what was found and changed while writing it

1. `frida.FridaError` does not exist in frida 17 (every error comes straight from `Exception`): the `except`
   clauses would have failed with `AttributeError` exactly when something went wrong. `FRIDA_ERRORS` is built from
   the module now, and a test with the real bindings keeps it honest.
2. Frida's **local** device was reachable by name (`device="local"`), which would have let an agent list and attach
   to the processes of this very container - the MCP server itself. The three names are refused before anything is
   reached, and `list_devices` never shows them.
3. `list_devices` answered "0 devices" when nothing was configured instead of saying what to configure.
4. `push_server` took `/data/../system/bin` (the folder pattern allowed `..` as a segment).
5. `export_server` looked for the binary before checking `out_name`, so a bad name was reported as "the image has
   no ..." - arguments are checked first now.
6. An inline script over the limit was refused with the generic argument message; it says "larger than 256 KiB" now,
   as a file does.
7. The adb server's address was only in `os.environ`; it is kept in `ADB_ENV` and passed to every `adb` call, so a
   call cannot be aimed at another adb server.

## Tests

- `tests/test_frida.py` (31 tests), all without a device: what is configured and that nothing else is reached (one
  `add_remote_device` with that address, adb only with `-H/-P` and a five-variable environment, a bad endpoint
  refused before anything connects), frida's local device refused by name through every tool, the write gate
  (`spawn`, `resume`, `kill`, `push_server` refused without `FRIDA_WRITE=1`, allowed with it), sessions (attach,
  run_script inline and from `/work`, detach, the session limit, a gone session), scripts (`..`, outside `/work`, a
  link, too large, empty, not `.js`), messages (counted, capped, control characters filtered, errors, JSON
  payloads), modules and exports (our own expression, the module name as JSON, filters, a process that does not
  answer), the binaries (`list_abis`, `export_server` unpacks the release file, never over an existing name, bad
  abi/platform/kind/out_name, no `/out`, the unpack limit), `push_server` (the ABI the device reports mapped to the
  image's, the push from the scratch folder, the folder pattern), answers in parts, and tools only against
  `tools.json`. With frida's own bindings installed: the version matches the binaries' version and the Dockerfile's
  twelve release URLs, the local device is refused for real, and every error class the server names exists.
  **31 of 31 pass** here against frida 17.25.2's own bindings.
- `tests/test_own_servers.py` `test_frida`: over stdio as the image starts it (sixteen tools, no resources or
  prompts, eight refusals), then the suite above.
- `tests/test_analysis_servers.py` `FridaServer`: the pins (client and all twelve binaries one version, every digest
  in `PROVENANCE.md`, one `ARG` each), the binaries packed and not executable, what it may reach (`network: full`
  plus the `--allow-tcp` note, one `add_remote_device`, one `subprocess.run`, no `urllib`/`socket`/`eval`), the
  local device never offered, the write gate, the limits and folders, and that every call of the smoke spec that
  needs a device is a refused call.
- `smoke.json`: `device_status`, `list_abis`, `export_server` (a real unpack into `/out`), `list_sessions`, then
  seven refused calls (no device, `local`, no session, the write gate twice, a bad abi, `../escape`).

**Not run here (no device, no container engine):** a real call to a device, the image build, the smoke spec under
Podman and Bubblewrap, Trivy. **What needs the user:** a device (or an emulator with a `frida-server`) to try
`attach`/`run_script`/`spawn` against, and the decision on `frida-tools` above. Signing waits for CI to build the
image and both smoke runs to pass.
