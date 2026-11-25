# Build toolchains

`toolchains/NAME/toolchain.json` is the recipe of a toolchain sandbox-ai mounts read-only into a sandbox at
`/opt/toolchains/NAME` (`sandbox-ai AGENT --toolchain NAME`, `sandbox-ai toolchain attach RUN NAME`; sandbox-ai's
`docs/TOOLCHAINS_DESIGN.md` has the format of an entry, the mount and the threat model). This repository builds
them, tests them and publishes `toolchains.json`, signed with the key that signs `catalog.json`.

| toolchain | what | older versions (`NAME@LINE`) | from | needs of the system |
|---|---|---|---|---|
| `go` | Go 1.27.3 | `go@1.26`: 1.26.10 | dl.google.com (`.sha256`) | nothing but the kernel |
| `python` | CPython 3.14.10 with pip, uv 0.13.7 | `python@3.13`: 3.13.18, `python@3.12`: 3.12.16, `python@3.11`: 3.11.18 | python-build-standalone 20261026, astral-sh/uv (GitHub, `SHA256SUMS`) | glibc 2.17 (aarch64: also libgcc_s) |
| `jdk` | Temurin 21.0.13+9, Maven 3.9.16, Gradle 9.9.0, Kotlin 2.4.21 | `jdk@17`: 17.0.21+9, `jdk@11`: 11.0.33+10 (Gradle 8.14.6: Gradle 9 needs Java 17) | adoptium (GitHub), Maven Central, gradle-distributions, JetBrains/kotlin | glibc 2.17 |
| `zig` | Zig 0.17.1 | - | the Zig project's wheel on PyPI | nothing but the kernel |
| `cc` | cc, c++, gcc, g++, clang as `zig cc`; CMake 4.4.4, Ninja 1.13.2 | - | Kitware, ninja-build (GitHub); requires `zig` | glibc 2.17 (aarch64: 2.28, CMake), libstdc++, libgcc_s (Ninja) |
| `node` | Node.js 26.13.0 with npm, TypeScript 6.0.3 | `node@24`: 24.22.2, `node@22`: 22.23.4 | nodejs.org (`SHASUMS256.txt`, signed), npm | glibc 2.28, libstdc++, libgcc_s, libatomic |
| `dotnet` | .NET SDK 10.0.403 | - (.NET 8 and 9 ended 2026-11-10) | builds.dotnet.microsoft.com (SHA-512 of dotnet/core) | glibc 2.27, libstdc++, libgcc_s, libssl 3 |
| `rust` | Rust 1.99.1: rustc, cargo, rustfmt, clippy | `rust@1.98`: 1.98.1, `rust@1.97`: 1.97.1 | static.rust-lang.org (OpenPGP signature); requires `cc` | glibc 2.17, libgcc_s |
| `android-sdk` | the Android SDK, API 37: platform and build-tools 37.0.0, platform-tools 37.0.1, command-line tools 23.0, NDK r30, CMake 4.1.2 and 3.22.1 | `android-sdk@36`: 36.0.0, `android-sdk@35`: 35.0.0 (one API level each) | dl.google.com, **on the user's machine** (a local recipe, below); requires `jdk`; x86_64 only | glibc 2.28, libgcc_s, libz |
| `pyside6` | Qt for Python: PySide6 6.12.0 with Qt 6.12.0 itself (every module, Designer, Linguist, Assistant, `pyside6-uic` ...) | `pyside6@6.11`: 6.11.3 (Qt's LTS line) | The Qt Company's wheels on PyPI (its JSON API's SHA-256); requires `python`; x86_64 only | glibc 2.34 and 16 libraries (below) |
| `qt` | Qt for C++: the Qt SDK (headers, libraries, CMake packages, mkspecs, moc, uic, rcc, qmake ...) | `qt@6.11` | download.qt.io's online repository (`ARCHIVE.sha256`); requires `pyside6`; x86_64 only | as `pyside6`; GCC from the image or the host |

Not here yet, and why: Ruby and PHP (upstream publishes sources only; the prebuilt, relocatable builds are third
parties' - jdx/ruby, swoole-cli, FrankenPHP - or would be built here with `cc`), Erlang/OTP and Elixir (the builds
of builds.hex.pm need OpenSSL 3, libtinfo and glibc 2.34 and an install step that runs their code), Haskell (GHC's
binary distributions are per distribution, call gcc and binutils and link gmp, numa, tinfo and ffi of the system)
and Swift (one distribution's build, about 3 GiB, needs that distribution's gcc and libc development files). Each
needs a decision first: whose build to trust, or a build from source in this CI.

## Qt

Two toolchains, two upstreams, both written by `scripts/qt_recipe.py` from upstream's own metadata (never by hand):

```bash
python3 scripts/qt_recipe.py pyside6 6.12.0 --write               # toolchains/pyside6/toolchain.json
python3 scripts/qt_recipe.py pyside6 6.11.3 --line 6.11 --write   # toolchains/pyside6/6.11/toolchain.json
python3 scripts/qt_recipe.py qt 6.12.0 --write                    # toolchains/qt/toolchain.json (needs download.qt.io)
python3 scripts/qt_recipe.py qt 6.11.3 --line 6.11 --write
python3 scripts/toolchain.py check                                # the 14-day rule, the pins
```

- **`pyside6`** (Python): the wheels shiboken6, PySide6_Essentials, PySide6_Addons (6.12: also PySide6_WebEngine,
  PySide6_Pdf) for manylinux x86_64, with the URL, SHA-256 and upload day of PyPI's JSON API, unpacked into
  `python/`; `PYTHONPATH={prefix}/python` makes `import PySide6` work in the python3 on PATH and in a virtual
  environment (sandbox-ai takes `PYTHONPATH` from a toolchain only as a folder of its own tree, and the build
  refuses a tree whose folder holds a name of Python's standard library or a `sitecustomize`). They carry Qt
  itself; nothing is installed from a registry (`allow` is empty: the toolchain `python` opens PyPI unless it is
  mounted offline). 6.12.0: an archive of 173 MiB, 661 MiB unpacked (6.11.3: 639 MiB). `QT_QPA_PLATFORM=offscreen` where nothing set it (sandbox-ai's `--gui` sets `xcb`).
- **`qt`** (C++): the 7z archives of the open-source online repository (desktop `gcc_64`, the add-ons of `ADDONS`,
  the extensions Qt WebEngine and Qt PDF), named by its `Updates.xml`, each pinned by the SHA-256 download.qt.io
  publishes beside it; never debug information, sources, documentation, examples, or a package outside the lists.
  aqtinstall is not used (py7zr and nine packages below it would have to be read in full): `scripts/toolchain.py`
  reads 7z through `bsdtar`, which only decodes - every file is written by the builder, with its checks. What the
  Qt installer does after unpacking are steps: `mkspecs/qconfig.pri` to the open-source edition (`replace`),
  `bin/qt.conf`, `libexec/qt.conf`. The recipes of 6.12.0 and 6.11.3 were written by the two commands above and
  are in the matrix of `toolchains.yml` (x86_64 only, aarch64 in its `exclude`); their first CI build is what shows
  whether the archive layout `VERSION/gcc_64/`, the commands' paths and the libraries (from Qt's documentation and the
  wheels) hold.
- **The compiler.** Qt's builds are GCC's (libstdc++). The toolchain `cc` is Clang with libc++: Qt's exported
  functions with `std::` types in their signature (`QTimer::singleShot(std::chrono...)`, `QObject::startTimer`,
  `QMetaType::registerConverterFunction(std::function...)`: 100 symbols in Qt Core alone) do not link with it. `qt`
  therefore does not require `cc`: its smoke test and sandbox-ai's preset `qt-cpp` use GCC, make, CMake and Ninja of
  the image (the variant `gcc`; under Bubblewrap the host's) - `smoke_apt` names the packages.
- **Licenses.** LGPL-3.0-only, GPL-2.0-only or GPL-3.0-only (some modules GPL-3.0-only). The wheels and archives
  hold no license text, so each tree gets `licenses/` (from the release's tag in github.com/pyside/pyside-setup and
  github.com/qt/qtbase, pinned) and `NOTICE.txt` (what it is, the third-party code inside, the source archives of
  exactly these binaries); the entry's `sources` name every download. Nothing of the commercial-only editions.
- **What it needs.** glibc 2.34 and `libstdc++`, `libgcc_s`, `libz`, `libzstd`, `libglib-2.0`, `libgthread-2.0`,
  `libEGL`, `libGL`, `libX11`, `libfontconfig`, `libfreetype`, `libxkbcommon`, `libbrotlicommon`, `libbrotlidec`,
  `libgssapi_krb5`, `libdbus-1` (Qt Core, Gui, Widgets, Qml, Quick, Network, D-Bus: measured on the wheels of 6.11.3
  and 6.12.0; sandbox-ai's images have all 16). `optional`, noted but not checked at a start: the xcb and Wayland
  platforms, Multimedia (libpulse), WebEngine (Chromium's libraries), the GTK theme, CUPS, SQL drivers other than
  SQLite. **aarch64 is not offered**: Qt's builds for it need glibc 2.38, sandbox-ai's images have 2.36, and an
  entry needs its Podman smoke test.

## Versions

Each version of a toolchain is a recipe of its own: `toolchains/NAME/toolchain.json` is the newest (its ID is NAME),
`toolchains/NAME/LINE/toolchain.json` an older one (ID `NAME@LINE`: `jdk@17`, `python@3.12`). LINE is the start of
its version up to a `.`, `+`, `-` or `_` - what `sandbox-ai --toolchain NAME@LINE` and `sandbox-ai toolchain add
NAME@LINE` pick it by (the newest version of the catalog that starts so) -, so a line picks its own recipe's version
and no other of the name; a name without `@` is its newest. `scripts/toolchain.py check` holds the recipes to that
(and to: the newest is the name's own recipe, no version twice). Every version is mounted at `/opt/toolchains/NAME`:
one version of a name per sandbox. A toolchain another requires is its newest (`rust@1.98` requires `cc`). An older
version is offered while upstream supports it (JDK, Node.js, Python, .NET: their LTS and maintained lines; Go: the
two newest minors); Rust supports only its newest, its two minors before it are offered for checking a crate's
oldest supported Rust. .NET 8 and 9 reached their end of support on 2026-11-10 and are not offered.

## Toolchains built on the user's machine (local recipes)

The Android SDK is published under the Android Software Development Kit License Agreement
(https://developer.android.com/studio/terms). Its section 3.4: "you may not copy (except for backup purposes),
modify, adapt, redistribute ... the SDK or any part of the SDK". So this repository builds, fetches and publishes
**nothing** of it - no archive, no release asset, no CI job that downloads it. `toolchains/android-sdk/` holds recipes
with `"local": true`:

- `scripts/toolchain.py check` holds one to what sandbox-ai runs: `fetch` (https, with `size`, `sha256`, the
  publisher's `sha1` where there is one, and `released`: 14 days), `unpack` (zip: `to`, `strip`), `write`, `link`,
  `chmod` - nothing else; `vars` are plain texts; `terms` names the license (`android-sdk-license`); `unpacked` says
  how large the tree gets. `build` refuses it; `ids --built` (the CI matrix) leaves it out.
- `scripts/make_toolchains.py` puts its entry into `toolchains.json` under `"recipes"`, beside `"toolchains"`: the
  manifest, `"recipe": {"terms", "vars", "steps"}` and `"sha256"` - the SHA-256 of the recipe (name, version,
  architecture, recipe as canonical JSON), which names its tree in sandbox-ai's store as an archive's hash does. A
  sandbox-ai from before recipes reads `"toolchains"` alone. `--recipes` writes them anew after a recipe changed.
- sandbox-ai (`sandbox/toolchain_recipes.py`): `sandbox-ai toolchain add android-sdk` checks the catalog's signature,
  says the license and asks (`--accept-android-sdk-license` for a script; never asked in the modes high and
  paranoid), fetches each file from dl.google.com, holds it to the recipe's size and hashes before it is unpacked,
  unpacks the zips without trusting them and keeps the tree read-only. Then it is a toolchain like every other
  (`--toolchain android-sdk`, `toolchain attach`).

`scripts/android_sdk_recipes.py --sandbox-ai DIR` writes the three recipes from sandbox-ai's own pins
(`sandbox/recipes/android-dev/sdk.lock`, the `package.xml` files, the acceptance file): one list of pins for the image
variant android-dev, the service image android-emulator and this toolchain; `--check` (a test, with
`SANDBOX_AI_CHECKOUT`) holds the recipes to it. What a line is: one API level (its platform and build-tools) with
platform-tools, the command-line tools, the NDK and CMake; no emulator and no system image (sandbox-ai's service
`android-emulator`). The tree is read-only in the sandbox, so the recipe writes the license's acceptance
(`licenses/android-sdk-license`) and each `package.xml` itself and sets `GRADLE_OPTS` so that the Android Gradle plugin
does not try to install what a project names beyond the line.

What the signature says of a recipe: it is this repository's (`make_toolchains.py --check`), and every download is
pinned by its size and SHA-256 (of a download somebody made and compared with Google's SHA-1). No smoke report
stands behind it. Before signing a changed recipe, run sandbox-ai's live check on a machine of yours:
`sandbox-ai live_check --only toolchain-live` adds android-sdk and assembles an app with it.

## A recipe

`scripts/toolchain.py` (its docstring has every key) runs the `build` steps: `fetch` (a download, used only with
its pinned `sha256`/`sha512`, with the hash a verified checksum file `listed` for it, or after a `gpg` step
verified it against pinned keys), `unpack` (tar, zip or - through `bsdtar` - 7z, without trusting it), `copy` (a
fetched, verified file: a license text), `write`, `link`, `move`, `remove`, `chmod`, `replace` (the lines of a text
file that begin so). They are data, never a shell. Every `fetch` of a release says when it was `released`: one younger than 14
days is refused. The manifest keys (`commands`, `env`, `caches`, `hosts`, `allow`, `needs`, `requires`) are what
sandbox-ai reads; `needs` is a claim the build checks against every ELF file of the tree (its `NEEDED` libraries
must be in the tree, glibc's own or named; its `GLIBC_x.y` versions not above the floor), files matching `optional`
(a JDK's desktop libraries, test data) aside. `needs.glibc` and `needs.libraries` may each be a map by
architecture (`{"x86_64": "2.17", "aarch64": "2.28"}`): upstream often builds aarch64 on a newer system. `smoke` compiles and runs a hello world;
`smoke_apt` names Debian packages its sandbox gets beyond the agent images' base (a compiler that is the image's,
not the toolchain's: Qt's GCC).

```bash
python3 scripts/toolchain.py check                        # every recipe: keys, pins, release dates (no download)
python3 scripts/toolchain.py ids                          # every recipe's ID: go, go@1.26, jdk, jdk@17 ...
python3 scripts/toolchain.py ids --built                  # those built here (the CI matrix): not android-sdk
python3 scripts/toolchain.py build go --arch x86_64 --out out
python3 scripts/toolchain.py build go@1.26 --arch x86_64 --out out     # out/toolchain-go@1.26-x86_64.*
python3 scripts/toolchain_smoke.py --sandbox-ai ../sandbox-ai --runner sandbox-ai-bwrap \
    --meta out/toolchain-go-x86_64.json --archive out/toolchain-go-x86_64.tar.xz --report smoke.json
```

## What the CI run produces

`.github/workflows/toolchains.yml`, per recipe (every version: its matrix lists every ID, a test holds it to
`scripts/toolchain.py ids`) and architecture (x86_64, aarch64 on its own runner): the build;
the smoke test under Podman (the image sandbox-ai's agent images are built on, with the `openssl` they add - .NET
loads libssl at run time - and the libraries of their GUI base that Qt names) and under Bubblewrap, both through sandbox-ai's own store, plan, session folder and
mounts (`SANDBOX_AI_REF`), without network, HOME a writable `/root` as in every sandbox (Java takes root's home
from passwd, not from `$HOME`: Gradle's `~/.gradle`); on `main` the archive
as the release `toolchain-NAME-ARCH-<first 12 hex digits of its SHA-256>` (its asset `toolchain-NAME-ARCH.tar.xz`,
for every version alike); the artifact `tc-ID-ARCH` (the entry, both reports `smoke-ID-ARCH-RUNNER.json`). The `catalog` job makes `toolchains.json` of the toolchains whose two reports passed for exactly
their archive (and whose required toolchains passed too); every other is named in a warning and left out. The
artifact `toolchains` holds it with the reports; the pre-release `ci-toolchains-RUN` has the same files.

## Signing

As `docs/SIGNING.md` for the MCP catalog, with the same key, after the run of `main`:

```bash
KEY=~/.config/sandbox-ai/mcp-signing-key
SANDBOX_AI=../sandbox-ai
RUN=$(gh run list -R c0decave/sandbox-ai-mcp --workflow toolchains.yml --branch main -L 1 --json databaseId -q '.[0].databaseId')
gh run watch "$RUN" -R c0decave/sandbox-ai-mcp --exit-status
CI=$(mktemp -d)
gh run download "$RUN" -R c0decave/sandbox-ai-mcp -n toolchains -D "$CI"
cp "$CI/toolchains.json" .
python3 scripts/make_toolchains.py --check --sandbox-ai "$SANDBOX_AI"    # every entry as sandbox-ai reads it
python3 scripts/sign_toolchains.py --key "$KEY" --reports "$CI"          # refuses without both reports per entry
                                                                         # (a recipe of "recipes" has none: above)
python3 scripts/sign_toolchains.py --verify --signers "$SANDBOX_AI/sandbox/mcp-signers"
git add toolchains.json toolchains.json.sig
git commit -m "Toolchains of CI run $RUN, signed"                        # starts no rebuild
```

After a local recipe alone changed (no CI run): `python3 scripts/make_toolchains.py --recipes`, then `--check`,
`sign_toolchains.py --key "$KEY" --reports "$CI"` with the reports of the last run (the archives' entries are
unchanged), and commit both files.

sandbox-ai reads `toolchains.json` and `toolchains.json.sig` from the top of branch `main`
(`https://raw.githubusercontent.com/c0decave/sandbox-ai-mcp/main/toolchains.json`). The first run needs a published
sandbox-ai that has `sandbox/toolchains.py` (or `SANDBOX_AI_REF` pointing at a tag that has it).
