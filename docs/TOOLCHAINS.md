# Build toolchains

`toolchains/NAME/toolchain.json` is the recipe of a toolchain sandbox-ai mounts read-only into a sandbox at
`/opt/toolchains/NAME` (`sandbox-ai AGENT --toolchain NAME`, `sandbox-ai toolchain attach RUN NAME`; sandbox-ai's
`docs/TOOLCHAINS_DESIGN.md` has the format of an entry, the mount and the threat model). This repository builds
them, tests them and publishes `toolchains.json`, signed with the key that signs `catalog.json`.

| toolchain | what | from | needs of the system |
|---|---|---|---|
| `go` | Go 1.27.3 | dl.google.com (`.sha256`) | nothing but the kernel |
| `python` | CPython 3.14.10 with pip, uv 0.13.7 | python-build-standalone 20261026, astral-sh/uv (GitHub, `SHA256SUMS`) | glibc 2.17 |
| `jdk` | Temurin 21.0.13+9, Maven 3.9.16, Gradle 9.9.0, Kotlin 2.4.21 | adoptium (GitHub), Maven Central, gradle-distributions, JetBrains/kotlin | glibc 2.17 |
| `zig` | Zig 0.17.1 | the Zig project's wheel on PyPI | nothing but the kernel |
| `cc` | cc, c++, gcc, g++, clang as `zig cc`; CMake 4.4.4, Ninja 1.13.2 | Kitware, ninja-build (GitHub); requires `zig` | glibc 2.17, libstdc++, libgcc_s (Ninja) |
| `node` | Node.js 26.13.0 with npm, TypeScript 6.0.3 | nodejs.org (`SHASUMS256.txt`, signed), npm | glibc 2.28, libstdc++, libgcc_s, libatomic |
| `dotnet` | .NET SDK 10.0.403 | builds.dotnet.microsoft.com (SHA-512 of dotnet/core) | glibc 2.27, libstdc++, libgcc_s, libssl 3 |
| `rust` | Rust 1.99.1: rustc, cargo, rustfmt, clippy | static.rust-lang.org (OpenPGP signature); requires `cc` | glibc 2.17, libgcc_s |

Not here yet, and why: Ruby and PHP (upstream publishes sources only; the prebuilt, relocatable builds are third
parties' - jdx/ruby, swoole-cli, FrankenPHP - or would be built here with `cc`), Erlang/OTP and Elixir (the builds
of builds.hex.pm need OpenSSL 3, libtinfo and glibc 2.34 and an install step that runs their code), Haskell (GHC's
binary distributions are per distribution, call gcc and binutils and link gmp, numa, tinfo and ffi of the system)
and Swift (one distribution's build, about 3 GiB, needs that distribution's gcc and libc development files). Each
needs a decision first: whose build to trust, or a build from source in this CI.

## A recipe

`scripts/toolchain.py` (its docstring has every key) runs the `build` steps: `fetch` (a download, used only with
its pinned `sha256`/`sha512`, with the hash a verified checksum file `listed` for it, or after a `gpg` step
verified it against pinned keys), `unpack` (tar or zip, without trusting it), `write`, `link`, `move`, `remove`,
`chmod`. They are data, never a shell. Every `fetch` of a release says when it was `released`: one younger than 14
days is refused. The manifest keys (`commands`, `env`, `caches`, `hosts`, `allow`, `needs`, `requires`) are what
sandbox-ai reads; `needs` is a claim the build checks against every ELF file of the tree (its `NEEDED` libraries
must be in the tree, glibc's own or named; its `GLIBC_x.y` versions not above the floor), files matching `optional`
(a JDK's desktop libraries, test data) aside. `smoke` compiles and runs a hello world.

```bash
python3 scripts/toolchain.py check                        # every recipe: keys, pins, release dates (no download)
python3 scripts/toolchain.py build go --arch x86_64 --out out
python3 scripts/toolchain_smoke.py --sandbox-ai ../sandbox-ai --runner sandbox-ai-bwrap \
    --meta out/toolchain-go-x86_64.json --archive out/toolchain-go-x86_64.tar.xz --report smoke.json
```

## What the CI run produces

`.github/workflows/toolchains.yml`, per toolchain and architecture (x86_64, aarch64 on its own runner): the build;
the smoke test under Podman (the image sandbox-ai's agent images are built on) and under Bubblewrap, both through
sandbox-ai's own store, plan, session folder and mounts (`SANDBOX_AI_REF`), without network; on `main` the archive
as the release `toolchain-NAME-ARCH-<first 12 hex digits of its SHA-256>`; the artifact `tc-NAME-ARCH` (the entry,
both reports). The `catalog` job makes `toolchains.json` of the toolchains whose two reports passed for exactly
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
