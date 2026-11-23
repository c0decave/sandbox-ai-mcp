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

Not here yet, and why: Ruby and PHP (upstream publishes sources only; the prebuilt, relocatable builds are third
parties' - jdx/ruby, swoole-cli, FrankenPHP - or would be built here with `cc`), Erlang/OTP and Elixir (the builds
of builds.hex.pm need OpenSSL 3, libtinfo and glibc 2.34 and an install step that runs their code), Haskell (GHC's
binary distributions are per distribution, call gcc and binutils and link gmp, numa, tinfo and ffi of the system)
and Swift (one distribution's build, about 3 GiB, needs that distribution's gcc and libc development files). Each
needs a decision first: whose build to trust, or a build from source in this CI.

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

## A recipe

`scripts/toolchain.py` (its docstring has every key) runs the `build` steps: `fetch` (a download, used only with
its pinned `sha256`/`sha512`, with the hash a verified checksum file `listed` for it, or after a `gpg` step
verified it against pinned keys), `unpack` (tar or zip, without trusting it), `write`, `link`, `move`, `remove`,
`chmod`. They are data, never a shell. Every `fetch` of a release says when it was `released`: one younger than 14
days is refused. The manifest keys (`commands`, `env`, `caches`, `hosts`, `allow`, `needs`, `requires`) are what
sandbox-ai reads; `needs` is a claim the build checks against every ELF file of the tree (its `NEEDED` libraries
must be in the tree, glibc's own or named; its `GLIBC_x.y` versions not above the floor), files matching `optional`
(a JDK's desktop libraries, test data) aside. `needs.glibc` and `needs.libraries` may each be a map by
architecture (`{"x86_64": "2.17", "aarch64": "2.28"}`): upstream often builds aarch64 on a newer system. `smoke` compiles and runs a hello world.

```bash
python3 scripts/toolchain.py check                        # every recipe: keys, pins, release dates (no download)
python3 scripts/toolchain.py ids                          # every recipe's ID: go, go@1.26, jdk, jdk@17 ...
python3 scripts/toolchain.py build go --arch x86_64 --out out
python3 scripts/toolchain.py build go@1.26 --arch x86_64 --out out     # out/toolchain-go@1.26-x86_64.*
python3 scripts/toolchain_smoke.py --sandbox-ai ../sandbox-ai --runner sandbox-ai-bwrap \
    --meta out/toolchain-go-x86_64.json --archive out/toolchain-go-x86_64.tar.xz --report smoke.json
```

## What the CI run produces

`.github/workflows/toolchains.yml`, per recipe (every version: its matrix lists every ID, a test holds it to
`scripts/toolchain.py ids`) and architecture (x86_64, aarch64 on its own runner): the build;
the smoke test under Podman (the image sandbox-ai's agent images are built on, with the `openssl` they add: .NET
loads libssl at run time) and under Bubblewrap, both through sandbox-ai's own store, plan, session folder and
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
python3 scripts/sign_toolchains.py --verify --signers "$SANDBOX_AI/sandbox/mcp-signers"
git add toolchains.json toolchains.json.sig
git commit -m "Toolchains of CI run $RUN, signed"                        # starts no rebuild
```

sandbox-ai reads `toolchains.json` and `toolchains.json.sig` from the top of branch `main`
(`https://raw.githubusercontent.com/c0decave/sandbox-ai-mcp/main/toolchains.json`). The first run needs a published
sandbox-ai that has `sandbox/toolchains.py` (or `SANDBOX_AI_REF` pointing at a tag that has it).
