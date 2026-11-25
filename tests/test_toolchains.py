"""Build toolchains (scripts/toolchain.py, toolchain_smoke.py, make_toolchains.py, sign_toolchains.py): every recipe
is pinned and old enough, a download is used only with its pinned hash or a verified signature, an archive is
unpacked without trusting it, the tree's ELF files are held to what the manifest says they need, and only a
toolchain that passed both smoke tests for exactly its archive enters toolchains.json and is signed. With
SANDBOX_AI_CHECKOUT naming a sandbox-ai checkout, the entries go through sandbox-ai's own reader and mount code."""
import datetime
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import types
import unittest
import zipfile

ROOT = Path(__file__).resolve().parent.parent
CHECKOUT = os.environ.get("SANDBOX_AI_CHECKOUT")
TODAY = datetime.date(2026, 11, 22)


def load(name):
    spec = importlib.util.spec_from_file_location(f"{name}_tests", ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tc = load("toolchain")
make = load("make_toolchains")
sign = load("sign_toolchains")
smoke = load("toolchain_smoke")
qt = load("qt_recipe")


def tar_bytes(members, mode="w:gz"):
    """{name: bytes | None (folder) | ("sym", target) | ("chr",)} as a tar archive."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode=mode) as tar:
        for name, value in members.items():
            info = tarfile.TarInfo(name)
            if value is None:
                info.type, info.mode = tarfile.DIRTYPE, 0o755
                tar.addfile(info)
            elif isinstance(value, tuple):
                info.type = tarfile.SYMTYPE if value[0] == "sym" else tarfile.CHRTYPE
                info.linkname = value[1] if value[0] == "sym" else ""
                tar.addfile(info)
            else:
                info.size, info.mode = len(value), 0o4755 if "/bin/" in name or "/libexec/" in name else 0o644
                tar.addfile(info, io.BytesIO(value))
    return buffer.getvalue()


def elf(needed=(), glibc=None, machine=62, kind=3):
    """A minimal 64-bit ELF with a dynamic section: NEEDED entries and one version need of libc.so.6."""
    strings = b"\0"
    offsets = []
    for name in (*needed, "libc.so.6", glibc or "GLIBC_2.2.5"):
        offsets.append(len(strings))
        strings += name.encode() + b"\0"
    base = 0x1000  # everything in one PT_LOAD mapped at its file offset
    strtab = 64 + 2 * 56
    verneed = strtab + len(strings)
    dynamic = verneed + 32
    tags = [(1, offset) for offset in offsets[:len(needed)]] + [(5, base + strtab), (0x6ffffffe, base + verneed),
                                                                 (0x6fffffff, 1), (0, 0)]
    body = strings + struct.pack("<HHIII", 1, 1, offsets[-2], 16, 0) + struct.pack("<IHHII", 0, 0, 2, offsets[-1], 0)
    body += b"".join(struct.pack("<qQ", tag, value) for tag, value in tags)
    size = strtab + len(body)
    header = b"\x7fELF" + bytes([2, 1, 1, 0]) + b"\0" * 8 + struct.pack("<HHIQQQIHHHHHH", kind, machine, 1, 0, 64, 0,
                                                                         0, 64, 56, 2, 0, 0, 0)
    load_segment = struct.pack("<IIQQQQQQ", 1, 5, 0, base, base, size, size, 0x1000)
    dyn_segment = struct.pack("<IIQQQQQQ", 2, 6, dynamic, base + dynamic, base + dynamic, len(tags) * 16,
                              len(tags) * 16, 8)
    return header + load_segment + dyn_segment + body


class Repo:
    """A repository of this test: toolchains/NAME/toolchain.json and the files its URLs name."""

    def __init__(self, test):
        self.root = Path(tempfile.mkdtemp(prefix="toolchain-test-"))
        test.addCleanup(shutil.rmtree, self.root, True)
        self.files = {}

    def recipe(self, name="demo", line=None, **more):
        """toolchains/NAME/toolchain.json, or with LINE an older version's toolchains/NAME/LINE/toolchain.json."""
        recipe = {"name": name, "version": "1.2.3", "title": "Demo", "description": "A demo.", "license": "MIT",
                  "homepage": "https://example.org", "arches": ["x86_64"], "commands": {"demo": "bin/demo"},
                  "env": {"DEMO_HOME": "{prefix}"}, "caches": {}, "hosts": ["example.org"], "allow": [],
                  "needs": {"glibc": "2.17", "libraries": []}, "requires": [], **more}
        path = self.root / "toolchains" / name / (line or "")
        path.mkdir(parents=True, exist_ok=True)
        (path / "toolchain.json").write_text(json.dumps(recipe))
        return recipe

    def serve(self, url, data):
        self.files[url] = data
        return hashlib.sha256(data).hexdigest()

    def opener(self, url):
        return io.BytesIO(self.files[url])

    def build(self, name="demo", **more):
        return tc.build(name, "x86_64", self.root / "out", today=TODAY, root=self.root, opener=self.opener, **more)


class Recipes(unittest.TestCase):
    def test_every_recipe_is_pinned_and_old_enough(self):
        names = tc.recipe_ids()
        self.assertGreaterEqual(set(names), {"go", "python", "jdk", "zig", "node", "dotnet", "cc", "rust", "pyside6"})
        # the older versions offered too (the user 2026-11-23: "add toolchain support for older toolchain versions")
        self.assertGreaterEqual(set(names), {"jdk@17", "jdk@11", "node@24", "node@22", "python@3.13", "python@3.12",
                                             "python@3.11", "go@1.26", "rust@1.98", "rust@1.97"})
        self.assertEqual(tc.versions_problems(), [])
        for name in names:
            recipe = tc.load(name)
            self.assertEqual(tc.problems_of(recipe, TODAY), [], name)
            if tc.is_local(recipe):  # (built on the user's machine: nothing of it is built or run here)
                continue
            self.assertTrue(recipe.get("smoke"), f"{name}: no smoke test")
            self.assertGreaterEqual(len(recipe["smoke"]), 2, f"{name}: its smoke test only asks for a version")
            for arch in recipe["arches"]:
                tc.manifest(recipe, arch)
                for step in recipe["build"]:  # every text of every step resolves for every architecture
                    for value in step.values():
                        if isinstance(value, (str, dict)) and not isinstance(value, bool) and "in" not in value:
                            tc.substituted(str(tc.for_arch(value, arch, name)), recipe, arch)

    def test_a_release_younger_than_14_days_is_refused(self):
        recipe = tc.load("go")
        day = datetime.date.fromisoformat(recipe["build"][0]["released"])
        self.assertEqual(tc.problems_of(recipe, day + datetime.timedelta(days=14)), [])
        problems = tc.problems_of(recipe, day + datetime.timedelta(days=13))
        self.assertTrue(any("13 days before" in problem and "14 days old" in problem for problem in problems))

    def test_what_a_recipe_may_not_be(self):
        base = {"name": "x", "version": "1", "title": "X", "description": "x", "license": "MIT", "homepage": "h",
                "arches": ["x86_64"], "commands": {"x": "bin/x"}}
        fetch = {"fetch": "a.tar.gz", "url": "https://example.org/a.tar.gz", "sha256": "0" * 64,
                 "released": "2026-01-01"}
        for build, why in (
                ([{"fetch": "a.tar.gz", "url": "https://example.org/a", "released": "2026-01-01"},
                  {"unpack": "a.tar.gz"}], "needs exactly one of"),
                ([{**fetch, "url": "http://example.org/a"}, {"unpack": "a.tar.gz"}], "is not https"),
                ([{**fetch, "sha256": "abc"}, {"unpack": "a.tar.gz"}], "is not a hash"),
                ([{"fetch": "a.tar.gz", "url": "https://e.org/a", "signed": True, "released": "2026-01-01"},
                  {"unpack": "a.tar.gz"}], "before a hash or a signature vouched"),
                ([{"fetch": "a.tar.gz", "url": "https://e.org/a", "released": "2026-01-01",
                   "listed": {"in": "SUMS", "as": "a"}}, {"unpack": "a.tar.gz"}], "which no gpg step verified"),
                ([fetch, {"unpack": "a.tar.gz"}, {"fetch": "b", "url": "https://e.org/b", "sha256": "0" * 64}],
                 "fetched and never used: b"),
                ([{k: v for k, v in fetch.items() if k != "released"}, {"unpack": "a.tar.gz"}],
                 "no fetch step says when"),
                ([fetch, {"unpack": "a.tar.gz", "write": "x"}], "exactly one of")):
            problems = tc.problems_of({**base, "build": build}, TODAY)
            self.assertTrue(any(why in problem for problem in problems), (why, problems))


class Build(unittest.TestCase):
    def setUp(self):
        self.repo = Repo(self)
        self.archive = tar_bytes({"demo-1.2.3": None, "demo-1.2.3/bin": None,
                                  "demo-1.2.3/bin/demo": elf(glibc="GLIBC_2.17"),
                                  "demo-1.2.3/lib": None, "demo-1.2.3/lib/libdemo.so": elf(["libm.so.6"]),
                                  "demo-1.2.3/share/doc/README": b"read me\n"})
        self.sha = self.repo.serve("https://example.org/demo-1.2.3-x86_64.tar.gz", self.archive)
        self.steps = [{"fetch": "demo.tar.gz", "url": "https://example.org/demo-{version}-{arch}.tar.gz",
                       "sha256": {"x86_64": self.sha}, "released": "2026-10-01"},
                      {"unpack": "demo.tar.gz", "strip": 1}]

    def test_a_build_is_the_pinned_release_as_one_tree(self):
        self.repo.recipe(build=[*self.steps, {"write": "bin/hi", "mode": "755",
                                             "text": "#!/bin/sh\nexec {prefix}/bin/demo \"$@\"\n"},
                                {"link": "bin/demo2", "to": "demo"}, {"remove": ["share/doc"]}],
                         commands={"demo": "bin/demo", "hi": "bin/hi"})
        meta = self.repo.build()
        entry, out = meta["entry"], self.repo.root / "out"
        archive = out / "toolchain-demo-x86_64.tar.xz"
        self.assertEqual(entry["sha256"], hashlib.sha256(archive.read_bytes()).hexdigest())
        self.assertEqual(entry["url"], f"{tc.RELEASES}/toolchain-demo-x86_64-{entry['sha256'][:12]}/{archive.name}")
        self.assertEqual(entry["sources"], [{"url": "https://example.org/demo-1.2.3-x86_64.tar.gz", "sha256": self.sha}])
        self.assertEqual((entry["arch"], entry["env"], entry["size"]), ("x86_64", {"DEMO_HOME": "{prefix}"},
                                                                        archive.stat().st_size))
        self.assertEqual(meta["measured"]["glibc"], "2.17")
        with tarfile.open(archive) as tar:
            members = {member.name: member for member in tar.getmembers()}
        self.assertEqual(sorted(members), ["bin", "bin/demo", "bin/demo2", "bin/hi", "lib", "lib/libdemo.so", "share"])
        self.assertEqual(members["bin/demo"].mode, 0o755)  # the archive's set-user-ID bit is gone
        self.assertEqual((members["bin/demo"].uid, members["bin/demo"].mtime, members["bin/demo2"].linkname),
                         (0, 0, "demo"))
        self.assertEqual((out / "tree-demo-x86_64/bin/hi").read_text(),
                         '#!/bin/sh\nexec /opt/toolchains/demo/bin/demo "$@"\n')
        self.assertEqual(json.loads((out / "toolchain-demo-x86_64.json").read_text())["entry"], entry)

    def test_a_download_with_another_hash_is_never_unpacked(self):
        self.repo.recipe(build=self.steps)
        self.repo.files["https://example.org/demo-1.2.3-x86_64.tar.gz"] = self.archive + b"x"
        with self.assertRaisesRegex(tc.Refused, "sha256 .*, pinned is .*: not used"):
            self.repo.build()
        self.assertFalse((self.repo.root / "out/tree-demo-x86_64/bin").exists())

    def test_an_archive_is_unpacked_without_trusting_it(self):
        for members, why in (({"demo/../../escape": b"x"}, "leaves the tree"),
                             ({"demo/bin": ("sym", "/etc"), "demo/bin/x": b"x"}, "absolute link"),
                             ({"demo/up": ("sym", "../../outside")}, "leaves the tree"),
                             ({"demo/bin": ("sym", "lib"), "demo/bin/x": b"x"}, "which is no folder")):
            with self.subTest(why=why):
                top = Path(tempfile.mkdtemp(dir=self.repo.root))
                (top / "a.tar.gz").write_bytes(tar_bytes(members))
                with self.assertRaisesRegex(tc.Refused, why):
                    tc.unpack(top / "a.tar.gz", top / "tree", strip=1)
                self.assertFalse((self.repo.root / "escape").exists() or (self.repo.root / "outside").exists())
        top = Path(tempfile.mkdtemp(dir=self.repo.root))
        (top / "a.tar").write_bytes(tar_bytes({"d/dev": ("chr",), "d/ok": b"1"}, "w"))
        tc.unpack(top / "a.tar", top / "tree", strip=1)
        self.assertEqual(sorted(p.name for p in (top / "tree").iterdir()), ["ok"])  # a device is left out

    def test_a_zip_keeps_its_executable_bits_and_only_what_is_asked_for(self):
        top = Path(tempfile.mkdtemp(dir=self.repo.root))
        with zipfile.ZipFile(top / "a.whl", "w") as archive:
            for name, mode in (("pkg/zig", 0o755), ("pkg/lib/std.zig", 0o644), ("pkg/__main__.py", 0o644),
                               ("pkg-1.dist-info/RECORD", 0o644)):
                info = zipfile.ZipInfo(name)
                info.external_attr = (0o100000 | mode) << 16
                archive.writestr(info, b"x")
        tc.unpack(top / "a.whl", top / "tree", strip=1, only=["zig", "lib"])
        self.assertEqual(sorted(p.relative_to(top / "tree").as_posix() for p in (top / "tree").rglob("*")),
                         ["lib", "lib/std.zig", "zig"])
        self.assertTrue(os.access(top / "tree/zig", os.X_OK) and not os.access(top / "tree/lib/std.zig", os.X_OK))

    def test_components_are_merged_into_one_prefix(self):
        data = tar_bytes({"r/rustc/bin/rustc": elf(), "r/rustc/manifest.in": b"a", "r/cargo/bin/cargo": elf(),
                          "r/cargo/manifest.in": b"b", "r/rust-docs/share/doc/x": b"big"})
        sha = self.repo.serve("https://example.org/r.tar.gz", data)
        self.repo.recipe(commands={"rustc": "bin/rustc", "cargo": "bin/cargo"}, build=[
            {"fetch": "r.tar.gz", "url": "https://example.org/r.tar.gz", "sha256": sha, "released": "2026-10-01"},
            {"unpack": "r.tar.gz", "strip": 1, "merge": ["rustc", "cargo"]}, {"remove": ["manifest.in"]}],
            needs={"glibc": "2.17", "libraries": []})
        self.repo.build()
        tree = self.repo.root / "out/tree-demo-x86_64"
        self.assertEqual(sorted(p.relative_to(tree).as_posix() for p in tree.rglob("*")),
                         ["bin", "bin/cargo", "bin/rustc"])

    def test_the_tree_is_held_to_what_the_manifest_says_it_needs(self):
        self.repo.recipe(build=self.steps, needs={"glibc": "2.5", "libraries": []})
        with self.assertRaisesRegex(tc.Refused, r"need glibc 2\.17 \(bin/demo\), needs.glibc says 2\.5"):
            self.repo.build()
        data = tar_bytes({"d/bin/demo": elf(["libstdc++.so.6", "libdemo.so", "$ORIGIN/../lib/libdemo.so"]),
                          "d/lib/libdemo.so": elf(),
                          "d/lib/gui.so": elf(["libX11.so.6"], "GLIBC_2.38"),
                          "d/testdata/other": elf(["libnope.so"], machine=183), "d/script": b"#!/bin/sh\n"})
        self.steps[0]["sha256"] = self.repo.serve("https://example.org/demo-1.2.3-x86_64.tar.gz", data)
        self.repo.recipe(build=self.steps, needs={"glibc": "2.17", "libraries": []}, optional=["lib/gui.so"])
        with self.assertRaisesRegex(tc.Refused, r"libstdc\+\+\.so\.6 is needed by bin/demo: neither in the tree"):
            self.repo.build()
        self.repo.recipe(build=self.steps, needs={"glibc": "2.17", "libraries": ["libstdc++.so.6"]},
                         optional=["lib/gui.so"])
        measured = self.repo.build()["measured"]
        self.assertEqual((measured["glibc"], measured["libraries"]), ("2.2", ["libstdc++.so.6"]))
        self.assertEqual(measured["optional"], {"glibc": "2.38", "libraries": ["libX11.so.6"]})  # noted, not held
        self.assertIsNone(tc.elf_facts(b"#!/bin/sh\n", 62))
        self.assertEqual(tc.elf_facts(elf()[:64 + 56] .replace(b"\x02\x00\x00\x00\x06", b"\x06\x00\x00\x00\x06"), 62),
                         None)  # a cut-off file is no program of ours

    def test_what_a_tree_needs_may_differ_by_architecture(self):
        # CI run 45032125924: Kitware's aarch64 CMake needs glibc 2.28, its x86_64 one 2.17; python-build-standalone's
        # aarch64 interpreter needs libgcc_s.so.1, its x86_64 one nothing.
        data = tar_bytes({"d/bin/demo": elf(["libgcc_s.so.1"], "GLIBC_2.28", machine=183)})
        self.steps[0]["sha256"] = {"x86_64": self.sha,
                                   "aarch64": self.repo.serve("https://example.org/demo-1.2.3-aarch64.tar.gz", data)}
        needs = {"glibc": {"x86_64": "2.17", "aarch64": "2.28"},
                 "libraries": {"x86_64": [], "aarch64": ["libgcc_s.so.1"]}}
        recipe = self.repo.recipe(build=self.steps, arches=["x86_64", "aarch64"], needs=needs)
        self.assertEqual(tc.problems_of(recipe, TODAY), [])
        self.assertEqual(tc.manifest(recipe, "x86_64")["needs"], {"glibc": "2.17", "libraries": []})
        self.assertEqual(tc.manifest(recipe, "aarch64")["needs"], {"glibc": "2.28", "libraries": ["libgcc_s.so.1"]})
        meta = tc.build("demo", "aarch64", self.repo.root / "out", today=TODAY, root=self.repo.root,
                        opener=self.repo.opener)
        self.assertEqual(meta["entry"]["needs"], {"glibc": "2.28", "libraries": ["libgcc_s.so.1"]})
        self.repo.recipe(build=self.steps, arches=["x86_64", "aarch64"],
                         needs={"glibc": {"x86_64": "2.28", "aarch64": "2.17"}, "libraries": ["libgcc_s.so.1"]})
        with self.assertRaisesRegex(tc.Refused, r"need glibc 2\.28 \(bin/demo\), needs.glibc says 2\.17"):
            tc.build("demo", "aarch64", self.repo.root / "out", today=TODAY, root=self.repo.root,
                     opener=self.repo.opener)
        broken = self.repo.recipe(build=self.steps, arches=["x86_64", "aarch64"],
                                  needs={"glibc": {"x86_64": "2.17"}, "libraries": []})
        self.assertIn("demo: needs.glibc: nothing for aarch64", tc.problems_of(broken, TODAY))

    def test_a_command_the_tree_lacks_refuses_the_build(self):
        self.repo.recipe(build=self.steps, commands={"demo": "bin/demo", "gone": "bin/gone"})
        with self.assertRaisesRegex(tc.Refused, "has no bin/gone"):
            self.repo.build()
        self.assertFalse((self.repo.root / "out/toolchain-demo-x86_64.tar.xz").exists())

    def test_a_signed_checksum_file_vouches_for_the_archive_it_lists(self):
        sums = f"{self.sha}  demo-1.2.3-x86_64.tar.gz\n{'0' * 64}  other.tar.gz\n".encode()
        self.repo.serve("https://example.org/SUMS", sums)
        self.repo.serve("https://example.org/SUMS.sig", b"sig")
        keys = self.repo.serve("https://example.org/keys.kbx", b"keyring")
        calls = []

        def gpg(command, **options):
            calls.append(command)
            good = gpg.good and "--verify" in command
            return types.SimpleNamespace(returncode=0 if good else 2, stderr="", stdout=(
                "[GNUPG:] GOODSIG 1 x\n[GNUPG:] VALIDSIG AAAA 2026-10-28 1 0 4 0 1 10 00 " + gpg.signer + "\n")
                if good else "")
        gpg.good, gpg.signer = True, "C0FFEE" * 6 + "C0FF"
        self.repo.recipe(build=[
            {"fetch": "keys.kbx", "url": "https://example.org/keys.kbx", "sha256": keys},
            {"fetch": "SUMS", "url": "https://example.org/SUMS", "signed": True},
            {"fetch": "SUMS.sig", "url": "https://example.org/SUMS.sig", "signed": True},
            {"gpg": "SUMS", "signature": "SUMS.sig", "keys": "keys.kbx"},
            {"fetch": "demo.tar.gz", "url": "https://example.org/demo-{version}-{arch}.tar.gz",
             "listed": {"in": "SUMS", "as": "demo-{version}-{arch}.tar.gz"}, "released": "2026-10-01"},
            {"unpack": "demo.tar.gz", "strip": 1}])
        entry = self.repo.build(gpg=gpg)["entry"]
        verify = [call for call in calls if "--verify" in call][0]
        self.assertIn("--no-default-keyring", verify)
        self.assertEqual(verify[verify.index("--keyring") + 1], str(self.repo.root / "out/downloads/keys.kbx"))
        signed = {source["url"].rsplit("/", 1)[1]: source.get("signature") for source in entry["sources"]}
        self.assertEqual(signed, {"keys.kbx": None, "SUMS": f"OpenPGP {gpg.signer}",
                                  "demo-1.2.3-x86_64.tar.gz": f"OpenPGP {gpg.signer}"})
        gpg.good = False
        with self.assertRaisesRegex(tc.Refused, "SUMS: no good signature in SUMS.sig"):
            self.repo.build(gpg=gpg)
        gpg.good = True
        self.repo.files["https://example.org/demo-1.2.3-x86_64.tar.gz"] = self.archive + b"x"
        shutil.rmtree(self.repo.root / "out")  # (a file without a literal hash is not fetched again by itself)
        with self.assertRaisesRegex(tc.Refused, "is not the one SUMS lists"):
            self.repo.build(gpg=gpg)

    def test_a_signature_must_be_of_a_pinned_key(self):
        def gpg(command, **options):
            return types.SimpleNamespace(returncode=0, stderr="", stdout="[GNUPG:] VALIDSIG X 1 1 0 4 0 1 10 00 BEEF\n"
                                         if "--verify" in command else "pub:-:\nfpr:::::::::BEEF:\nsub:-:\nfpr:::::::::F00D:\n")
        top = Path(tempfile.mkdtemp(dir=self.repo.root))
        for name in ("data", "data.asc", "key.asc"):
            (top / name).write_bytes(b"x")
        self.assertEqual(tc.gpg_verify(top / "data", top / "data.asc", top / "key.asc", ["BE EF"], gpg), "BEEF")
        with self.assertRaisesRegex(tc.Refused, "signed by BEEF, not by one of"):
            tc.gpg_verify(top / "data", top / "data.asc", top / "key.asc", ["CAFE"], gpg)
        self.assertEqual(tc.gpg_fingerprints(top / "key.asc", gpg), ["BEEF"])  # the primary key's, not a subkey's
        calls = []

        def silent(command, **options):  # CI run 45032125924: no key listed, and nothing said why
            calls.append(command)
            return types.SimpleNamespace(returncode=2, stdout="", stderr="gpg: no valid OpenPGP data found.\n")
        with self.assertRaisesRegex(tc.Refused, r"key.asc: gpg lists no key in it \(exit 2: gpg: no valid OpenPGP"):
            tc.gpg_fingerprints(top / "key.asc", silent)
        home = calls[0][calls[0].index("--homedir") + 1]  # a home of its own, gone afterwards
        self.assertFalse(Path(home).exists())


class Catalog(unittest.TestCase):
    def setUp(self):
        self.repo = Repo(self)
        data = tar_bytes({"d/bin/demo": elf(glibc="GLIBC_2.17")})
        sha = self.repo.serve("https://example.org/d.tar.gz", data)
        self.repo.recipe(build=[{"fetch": "d.tar.gz", "url": "https://example.org/d.tar.gz", "sha256": sha,
                                 "released": "2026-10-01"}, {"unpack": "d.tar.gz", "strip": 1}],
                         smoke=[{"run": "demo", "expect": "hello"}])
        self.entry = self.repo.build()["entry"]
        self.ci = self.repo.root / "out"

    def report(self, runner, **more):
        report = {"name": "demo", "version": "1.2.3", "arch": "x86_64", "runner": runner, "ok": True,
                  "sha256": self.entry["sha256"],
                  "checks": [{"check": "mounted as sandbox-ai mounts it", "ok": True},
                             {"check": "run demo", "ok": True}], **more}
        (self.ci / f"smoke-demo-x86_64-{runner}.json").write_text(json.dumps(report))

    def test_only_what_passed_both_smoke_tests_for_its_archive_enters(self):
        self.assertEqual(make.from_ci(self.ci, self.repo.root)[0], [])
        self.report("sandbox-ai-podman")
        entries, left_out = make.from_ci(self.ci, self.repo.root)
        self.assertEqual(entries, [])
        self.assertIn("no smoke-demo-x86_64-sandbox-ai-bwrap.json", left_out[0])
        for change, why in (({"ok": False}, "sandbox-ai-bwrap failed"), ({"sha256": "0" * 64}, "is of the archive"),
                            ({"checks": [{"check": "mounted as sandbox-ai mounts it", "ok": True}]},
                             "nothing was run"), ({"arch": "aarch64"}, "is not the sandbox-ai-bwrap report")):
            self.report("sandbox-ai-bwrap", **change)
            self.assertIn(why, make.from_ci(self.ci, self.repo.root)[1][0])
        self.report("sandbox-ai-bwrap")
        entries, left_out = make.from_ci(self.ci, self.repo.root)
        self.assertEqual((entries, left_out), ([self.entry], []))
        (self.repo.root / "toolchains.json").write_text(make.document(entries))
        self.assertEqual(make.check(self.repo.root, None), [])
        self.assertEqual(sign.problems_of(self.repo.root, self.ci), [])
        # the recipe moved on after the catalog was made: not current, nothing is signed
        self.repo.recipe(build=[], hosts=["example.org", "evil.example.org"])
        self.assertTrue(any("hosts is not what" in p for p in make.check(self.repo.root, None)))
        self.assertTrue(any("not current" in p for p in sign.problems_of(self.repo.root, self.ci)))

    def test_a_toolchain_without_what_it_requires_is_left_out(self):
        self.entry["requires"] = ["cc"]
        (self.ci / "toolchain-demo-x86_64.json").write_text(json.dumps({"entry": self.entry}))
        self.report("sandbox-ai-podman")
        self.report("sandbox-ai-bwrap")
        entries, left_out = make.from_ci(self.ci, self.repo.root)
        self.assertEqual(entries, [])
        self.assertIn("requires cc, which did not pass", left_out[0])

    def test_signing_needs_the_reports_and_verifies(self):
        if not shutil.which("ssh-keygen"):
            self.skipTest("no ssh-keygen")
        self.report("sandbox-ai-podman")
        (self.repo.root / "toolchains.json").write_text(make.document([self.entry]))
        key = self.repo.root / "key"
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True)
        signers = self.repo.root / "signers"
        kind, blob = (self.repo.root / "key.pub").read_text().split()[:2]
        signers.write_text(f'mcp@sandbox-ai namespaces="sandbox-ai-mcp" {kind} {blob}\n')
        arguments = ["--root", str(self.repo.root), "--key", str(key), "--reports", str(self.ci)]
        self.assertEqual(sign.main(arguments), 1)  # the Bubblewrap report is missing
        self.assertFalse((self.repo.root / "toolchains.json.sig").exists())
        self.report("sandbox-ai-bwrap")
        self.assertEqual(sign.main(arguments), 0)
        self.assertEqual(sign.main(["--root", str(self.repo.root), "--verify", "--signers", str(signers)]), 0)
        (self.repo.root / "toolchains.json").write_text(make.document([{**self.entry, "hosts": ["evil.example.org"]}]))
        self.assertEqual(sign.main(["--root", str(self.repo.root), "--verify", "--signers", str(signers)]), 1)

    def test_the_published_catalog_agrees_with_the_recipes(self):
        if not (ROOT / "toolchains.json").is_file():
            self.skipTest("no toolchains.json yet (the first CI run of main makes it)")
        checkout = Path(CHECKOUT) if CHECKOUT and (Path(CHECKOUT) / "sandbox/toolchains.py").is_file() else None
        self.assertEqual(make.check(ROOT, checkout), [])

    @unittest.skipUnless(CHECKOUT and (Path(CHECKOUT) / "sandbox/toolchains.py").is_file(),
                         "SANDBOX_AI_CHECKOUT names no sandbox-ai with toolchains")
    def test_sandbox_ai_takes_every_entry_and_mounts_it_for_the_smoke_test(self):
        t = smoke.sandbox_ai(Path(CHECKOUT))
        for ident in tc.recipe_ids():  # every recipe's manifest, every version
            recipe = tc.load(ident)
            for arch in recipe["arches"]:
                t.validated({**tc.manifest(recipe, arch), "url": "https://example.org/a.tar.xz", "sha256": "0" * 64})
        t.validated(self.entry)
        seen = []

        def run(command, **options):
            seen.append(command)
            return types.SimpleNamespace(returncode=0, stdout="hello\n", stderr="")
        entry = {**self.entry, "arch": t.machine()}
        (self.ci / "toolchain-demo-x86_64.json").write_text(json.dumps(
            {"entry": entry, "smoke": [{"files": {"a.txt": "x"}, "run": "demo", "expect": "hello"}]}))
        for runner in smoke.RUNNERS:
            opts = types.SimpleNamespace(sandbox_ai=Path(CHECKOUT), runner=runner, image="example/image",
                                         meta=self.ci / "toolchain-demo-x86_64.json", requires=[],
                                         archive=self.ci / "toolchain-demo-x86_64.tar.xz")
            old = os.environ.get("XDG_DATA_HOME")
            try:
                report = smoke.run_smoke(opts, run)
            finally:
                os.environ.pop("XDG_DATA_HOME", None) if old is None else os.environ.update(XDG_DATA_HOME=old)
            if runner == "sandbox-ai-bwrap" and t.host_glibc() is None:
                continue
            self.assertTrue(report["ok"], report)
            self.assertEqual(report["sha256"], entry["sha256"])
            command = seen[-1]
            joined = " ".join(command)
            self.assertIn("/opt/toolchains/demo", joined)
            self.assertIn("PATH=/opt/toolchains/bin:" if runner.endswith("podman") else "/opt/toolchains/bin:", joined)
            self.assertIn("--network=none" if runner.endswith("podman") else "--unshare-all", command)
            self.assertTrue(all(",ro," in value for value in command if "dst=/opt/toolchains" in value))
            # CI run 45032125924: HOME is sandbox-ai's /root and writable, also where passwd puts root's home (Java's
            # user.home: Gradle's ~/.gradle under Podman's read-only root)
            self.assertIn("HOME=/root" if runner.endswith("podman") else "HOME /root", joined)
            self.assertTrue(any(value.startswith("type=bind,") and value.endswith(",dst=/root,rw,nodev,nosuid")
                                for value in command) if runner.endswith("podman")
                            else command[command.index(t.SANDBOX_HOME) - 2] == "--bind")
        # no image named: the agent images' base with openssl is built first (.NET loads libssl.so.3), then used
        seen.clear()
        opts = types.SimpleNamespace(sandbox_ai=Path(CHECKOUT), runner="sandbox-ai-podman", image=None,
                                     meta=self.ci / "toolchain-demo-x86_64.json", requires=[],
                                     archive=self.ci / "toolchain-demo-x86_64.tar.xz")
        old = os.environ.get("XDG_DATA_HOME")
        try:
            report = smoke.run_smoke(opts, run)
        finally:
            os.environ.pop("XDG_DATA_HOME", None) if old is None else os.environ.update(XDG_DATA_HOME=old)
        self.assertTrue(report["ok"], report)
        self.assertEqual(seen[0][:2], ["podman", "build"])
        self.assertIn(smoke.SMOKE_IMAGE, seen[0])
        self.assertIn(smoke.SMOKE_IMAGE, seen[-1])
        self.assertIn("openssl", smoke.CONTAINERFILE)
        self.assertTrue(smoke.CONTAINERFILE.startswith(f"FROM {smoke.IMAGE}\n"))

        def failing(command, **options):
            return types.SimpleNamespace(returncode=125, stdout="", stderr="no network\n")
        try:
            report = smoke.run_smoke(opts, failing)
        finally:
            os.environ.pop("XDG_DATA_HOME", None) if old is None else os.environ.update(XDG_DATA_HOME=old)
        self.assertFalse(report["ok"])
        self.assertIn("podman build failed (125): no network", report["checks"][-1]["output"])


class Versions(unittest.TestCase):
    """Several versions of a toolchain: one recipe each - toolchains/NAME/toolchain.json the newest (ID NAME),
    toolchains/NAME/LINE/toolchain.json an older one (ID NAME@LINE, picked by sandbox-ai's --toolchain NAME@LINE) -,
    each built, smoke-tested and in the catalog on its own."""

    def setUp(self):
        self.repo = Repo(self)
        self.shas = {}
        for version in ("2.0.1", "1.9.4"):
            data = tar_bytes({f"d-{version}/bin/demo": elf(glibc="GLIBC_2.17"),
                              f"d-{version}/VERSION": version.encode()})
            self.shas[version] = self.repo.serve(f"https://example.org/d-{version}.tar.gz", data)

    def steps(self, version):
        return [{"fetch": "d.tar.gz", "url": "https://example.org/d-{version}.tar.gz", "sha256": self.shas[version],
                 "released": "2026-10-01"}, {"unpack": "d.tar.gz", "strip": 1}]

    def two(self):
        self.repo.recipe(version="2.0.1", build=self.steps("2.0.1"), smoke=[{"run": "demo", "expect": "2"}])
        self.repo.recipe(line="1.9", version="1.9.4", build=self.steps("1.9.4"), smoke=[{"run": "demo", "expect": "1"}])

    def test_each_version_has_its_recipe_and_its_id(self):
        self.two()
        self.assertEqual(tc.recipe_ids(self.repo.root), ["demo", "demo@1.9"])
        self.assertEqual(tc.load("demo@1.9", self.repo.root)["version"], "1.9.4")
        self.assertEqual(tc.id_of("demo", "1.9.4", self.repo.root), "demo@1.9")
        self.assertEqual(tc.id_of("demo", "2.0.1", self.repo.root), "demo")
        with self.assertRaisesRegex(tc.Refused, "no recipe of demo 1.8.0"):
            tc.id_of("demo", "1.8.0", self.repo.root)
        self.assertEqual(tc.versions_problems(self.repo.root), [])
        self.assertEqual(tc.main(["check", "--root", str(self.repo.root), "--date", "2026-11-22"]), 0)
        for line, version in (("17", "17.0.21+9"), ("3.12", "3.12.16"), ("1.26", "1.26.10"), ("22", "22.23.4")):
            self.assertTrue(tc.selects(line, version), (line, version))
        for line, version in (("1.2", "1.26.0"), ("3.1", "3.12.16"), ("17", "170.1")):
            self.assertFalse(tc.selects(line, version), (line, version))

    def test_what_the_versions_of_a_name_may_not_be(self):
        self.two()
        for change, why in (
                ({"line": "1.8", "version": "1.9.4"}, "does not start with 1.8"),
                ({"line": "1", "version": "1.9.4"}, "1.9.4 has more than one recipe"),
                ({"line": "2", "version": "2.1.0"}, "but 2.1.0 is newer"),
                ({"line": "1", "version": "1.0.0"}, "demo@1: 1 picks 1.9.4 too")):
            recipe = {**change}
            line = recipe.pop("line")
            self.repo.recipe(line=line, build=self.steps("1.9.4"), **recipe)
            self.assertTrue(any(why in problem for problem in tc.versions_problems(self.repo.root)),
                            (why, tc.versions_problems(self.repo.root)))
            self.assertEqual(tc.main(["check", "--root", str(self.repo.root), "--date", "2026-11-22"]), 1)
            shutil.rmtree(self.repo.root / "toolchains" / "demo" / line)
        (self.repo.root / "toolchains" / "demo" / "toolchain.json").unlink()
        self.assertTrue(any("without the newest version's toolchain.json" in problem
                            for problem in tc.versions_problems(self.repo.root)))
        with self.assertRaisesRegex(tc.Refused, "LINE the start of its version"):
            tc.load("demo@1.x", self.repo.root)

    def test_an_older_version_is_built_on_its_own_and_published_under_its_name(self):
        self.two()
        meta = tc.build("demo@1.9", "x86_64", self.repo.root / "out", today=TODAY, root=self.repo.root,
                        opener=self.repo.opener)
        entry, out = meta["entry"], self.repo.root / "out"
        self.assertEqual((entry["name"], entry["version"]), ("demo", "1.9.4"))
        self.assertTrue((out / "toolchain-demo@1.9-x86_64.tar.xz").is_file())
        self.assertEqual(json.loads((out / "toolchain-demo@1.9-x86_64.json").read_text())["entry"], entry)
        # the release is named after the archive's hash, the asset after the name: one scheme for every version
        self.assertEqual(entry["url"], f"{tc.RELEASES}/toolchain-demo-x86_64-{entry['sha256'][:12]}/"
                                       "toolchain-demo-x86_64.tar.xz")
        newest = self.repo.build()["entry"]
        self.assertEqual(newest["version"], "2.0.1")
        self.assertNotEqual(newest["sha256"], entry["sha256"])

    def test_every_version_that_passed_enters_the_catalog_newest_first(self):
        self.two()
        out = self.repo.root / "out"
        entries = {}
        for ident in ("demo@1.9", "demo"):
            entry = tc.build(ident, "x86_64", out, today=TODAY, root=self.repo.root, opener=self.repo.opener)["entry"]
            entries[ident] = entry
            for runner in smoke.RUNNERS:
                (out / f"smoke-{ident}-x86_64-{runner}.json").write_text(json.dumps(
                    {"name": "demo", "version": entry["version"], "arch": "x86_64", "runner": runner, "ok": True,
                     "sha256": entry["sha256"], "checks": [{"check": "run demo", "ok": True}]}))
        found, left_out = make.from_ci(out, self.repo.root)
        self.assertEqual(left_out, [])
        self.assertEqual([entry["version"] for entry in found], ["2.0.1", "1.9.4"])
        (self.repo.root / "toolchains.json").write_text(make.document(found))
        self.assertEqual(make.check(self.repo.root, None), [])
        self.assertEqual(sign.problems_of(self.repo.root, out), [])
        # the report of one version is never taken for another's
        (out / "smoke-demo@1.9-x86_64-sandbox-ai-bwrap.json").write_text(json.dumps(
            {"name": "demo", "version": "2.0.1", "arch": "x86_64", "runner": "sandbox-ai-bwrap", "ok": True,
             "sha256": entries["demo@1.9"]["sha256"], "checks": [{"check": "run demo", "ok": True}]}))
        found, left_out = make.from_ci(out, self.repo.root)
        self.assertEqual([entry["version"] for entry in found], ["2.0.1"])
        self.assertIn("is not the sandbox-ai-bwrap report of demo 1.9.4 x86_64", left_out[0])
        self.assertTrue(any("demo 1.9.4 x86_64: " in problem for problem in sign.problems_of(self.repo.root, out)))
        # an entry whose version has no recipe (any more)
        (self.repo.root / "toolchains.json").write_text(make.document([{**entries["demo"], "version": "1.0.0"}]))
        self.assertTrue(any("no recipe of demo 1.0.0" in p for p in make.check(self.repo.root, None)))

    def test_what_a_version_requires_is_the_newest_of_it(self):
        self.repo.recipe(name="base", build=[])
        self.repo.recipe(name="mid", requires=["base"], build=[])
        self.repo.recipe(name="top", line="1", version="1.0.0", requires=["mid"], build=[])
        self.repo.recipe(name="top", version="2.0.0", requires=["mid"], build=[])
        self.assertEqual(tc.requires("top@1", self.repo.root), ["base", "mid"])
        self.repo.recipe(name="base", requires=["top"], build=[])
        with self.assertRaisesRegex(tc.Refused, "require each other"):
            tc.requires("top@1", self.repo.root)

    def test_the_ci_builds_every_version(self):
        text = (ROOT / ".github" / "workflows" / "toolchains.yml").read_text(encoding="utf-8")
        start = text.index("toolchain: [", text.index("matrix:"))
        listed = [item.strip() for item in text[start + len("toolchain: ["):text.index("]", start)].split(",")]
        # Every recipe that is built here; a local one (android-sdk: built on the user's machine) never is.
        self.assertEqual(sorted(listed), sorted(tc.built_ids()))
        self.assertTrue(set(tc.recipe_ids()) - set(tc.built_ids()))
        self.assertIn('python3 scripts/toolchain.py requires "${NAME}"', text)
        # a recipe that is not for an architecture is excluded for it (else its job could only fail)
        excluded = set(re.findall(r"- toolchain: (\S+)\n +arch: (\S+)", text[text.index("exclude:"):]))
        self.assertEqual(excluded, {(ident, arch) for ident in tc.built_ids() for arch in tc.ARCHES
                                    if arch not in tc.load(ident)["arches"]})


class LocalRecipes(unittest.TestCase):
    """A recipe with "local": true (the Android SDK, which may not be passed on): never built or downloaded here; its
    steps are what sandbox-ai runs on the user's machine, published in toolchains.json "recipes" with the SHA-256
    that names its tree there."""

    def setUp(self):
        self.repo = Repo(self)
        self.steps = [
            {"fetch": "tools.zip", "url": "https://dl.example.org/tools-{version}.zip", "size": 1234,
             "sha256": "a" * 64, "sha1": "b" * 40, "released": "2026-08-11"},
            {"unpack": "tools.zip", "to": "tools", "strip": 1},
            {"write": "licenses/sdk-license", "text": "\n{accepted}"},
            {"link": "adb", "to": "tools/adb"}, {"chmod": "tools/adb", "mode": "755"}]

    def local(self, **more):
        return self.repo.recipe(**{"name": "sdk", "version": "37.0.0", "local": True,
                                   "terms": "android-sdk-license", "unpacked": 5000, "vars": {"accepted": "24333f8a"},
                                   "commands": {"adb": "tools/adb"}, "build": self.steps, **more})

    def test_a_local_recipe_is_checked_and_never_built_here(self):
        recipe = self.local()
        self.assertEqual(tc.problems_of(recipe, TODAY), [])
        self.assertEqual(tc.recipe_ids(self.repo.root), ["sdk"])
        self.assertEqual(tc.built_ids(self.repo.root), [])

        def never(url):
            raise AssertionError(f"nothing of a local recipe is fetched here: {url}")
        with self.assertRaisesRegex(tc.Refused, "built on the user's machine"):
            tc.build("sdk", "x86_64", self.repo.root / "out", today=TODAY, root=self.repo.root, opener=never)
        self.assertFalse((self.repo.root / "out").exists())

    def test_what_a_local_recipe_may_not_be(self):
        def problems(**change):
            return " | ".join(tc.problems_of({**self.local(), **change}, TODAY))

        def step(index, **change):
            steps = [dict(item) for item in self.steps]
            steps[index] = {key: value for key, value in {**steps[index], **change}.items() if value is not None}
            return steps
        self.assertIn("is no license sandbox-ai knows", problems(terms="some-eula"))
        self.assertIn("unpacked must say", problems(unpacked=None))
        self.assertIn("plain texts", problems(vars={"a": {"x86_64": "b"}}))
        self.assertIn("built and run here", problems(smoke=[{"run": "adb version"}]))
        self.assertIn("needs its sha256", problems(build=step(0, sha256=None)))  # Google's SHA-1 alone is not enough
        self.assertIn("needs its size", problems(build=step(0, size=None)))
        self.assertIn("is not https", problems(build=step(0, url="http://dl.example.org/x.zip")))
        self.assertIn("releases are pinned once they are 14 days old", problems(build=step(0, released="2026-11-20")))
        self.assertIn("must say when it was released", problems(build=step(0, released=None)))
        self.assertIn("unpacked once, after its fetch", problems(build=step(1, unpack="other.zip")))
        self.assertIn("has no key 'only'", problems(build=step(1, only=["bin"])))
        self.assertIn("no such variable", problems(build=step(2, text="{nobody}")))
        self.assertIn("what sandbox-ai runs", problems(build=[*self.steps, {"remove": ["doc"]}]))
        self.assertIn("what sandbox-ai runs", problems(build=[*self.steps, {"gpg": "a", "signature": "b",
                                                                              "keys": "c"}]))
        self.assertIn("never unpacked", problems(build=self.steps[:1]))
        # And what only a local recipe has is refused in one that is built here.
        self.repo.recipe(build=[], terms="android-sdk-license")
        self.assertIn('terms is for a recipe with "local": true',
                      " | ".join(tc.problems_of(tc.load("demo", self.repo.root), TODAY)))

    def test_its_entry_is_the_recipe_with_the_hash_that_names_it(self):
        self.local()
        entry = tc.local_entry("sdk", "x86_64", self.repo.root)
        self.assertEqual(entry["recipe"]["terms"], "android-sdk-license")
        self.assertEqual(entry["recipe"]["steps"][0], {"fetch": "tools.zip", "size": 1234, "sha256": "a" * 64,
                                                       "sha1": "b" * 40,
                                                       "url": "https://dl.example.org/tools-{version}.zip"})
        self.assertEqual(entry["recipe"]["steps"][2], {"write": "licenses/sdk-license", "text": "\n{accepted}",
                                                       "mode": "644"})  # every key written out: what is hashed
        self.assertNotIn("url", entry)
        self.assertEqual((entry["size"], entry["unpacked"], entry["sources"]), (1234, 5000, []))
        self.assertEqual(entry["sha256"], tc.local_digest("sdk", "37.0.0", "x86_64", entry["recipe"]))
        self.steps[0]["sha256"] = "c" * 64
        self.local()
        self.assertNotEqual(tc.local_entry("sdk", "x86_64", self.repo.root)["sha256"], entry["sha256"])
        with self.assertRaisesRegex(tc.Refused, "no local recipe for aarch64"):
            tc.local_entry("sdk", "aarch64", self.repo.root)

    def test_the_catalog_lists_it_under_recipes_and_is_held_to_the_recipe(self):
        self.local()
        entries = make.local_entries(self.repo.root)
        self.assertEqual([(entry["name"], entry["arch"]) for entry in entries], [("sdk", "x86_64")])
        path = self.repo.root / "toolchains.json"
        path.write_text(make.document([], entries))
        catalog = json.loads(path.read_text())
        self.assertEqual(catalog["toolchains"], [])
        self.assertEqual(catalog["recipes"], entries)
        self.assertNotIn("recipes", json.loads(make.document([])))  # a catalog without one is as it always was
        self.assertEqual(make.check(self.repo.root, None), [])
        path.write_text(make.document([], [{**entries[0], "hosts": ["evil.example.org"]}]))
        self.assertTrue(any("hosts is not what its recipe says" in p for p in make.check(self.repo.root, None)))
        path.write_text(make.document([]))
        self.assertTrue(any("not in the recipes of toolchains.json" in p for p in make.check(self.repo.root, None)))
        path.write_text(make.document([], [*entries, {**entries[0], "name": "other"}]))
        self.assertTrue(any("no local recipe of this repository" in p for p in make.check(self.repo.root, None)))
        path.write_text(make.document([entries[0]]))  # never among the archives
        self.assertTrue(any('it belongs in "recipes"' in p for p in make.check(self.repo.root, None)))
        # --recipes writes them anew and leaves the archives' entries as they are.
        path.write_text(make.document([]))
        self.assertEqual(make.main(["--root", str(self.repo.root), "--recipes"]), 0)
        self.assertEqual(json.loads(path.read_text())["recipes"], entries)
        # One whose required toolchain is not in the catalog is left out (as an archive's entry is), and refused in.
        self.local(requires=["jdk"])
        required = make.local_entries(self.repo.root)
        make.main(["--root", str(self.repo.root), "--recipes"])
        self.assertNotIn("recipes", json.loads(path.read_text()))
        self.assertEqual(make.check(self.repo.root, None), [])
        path.write_text(make.document([], required))
        self.assertTrue(any("requires jdk, which is not in toolchains.json" in p
                            for p in make.check(self.repo.root, None)))

    def test_signing_takes_a_recipe_without_reports_but_not_a_changed_one(self):
        if not shutil.which("ssh-keygen"):
            self.skipTest("no ssh-keygen")
        self.local()
        entries = make.local_entries(self.repo.root)
        path = self.repo.root / "toolchains.json"
        path.write_text(make.document([], entries))
        key = self.repo.root / "key"
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True)
        reports = self.repo.root / "reports"
        reports.mkdir()
        arguments = ["--root", str(self.repo.root), "--key", str(key), "--reports", str(reports)]
        self.assertEqual(sign.main(arguments), 0)  # no archive, no CI run: nothing of it is downloaded here
        (self.repo.root / "toolchains.json.sig").unlink()
        path.write_text(make.document([], [{**entries[0], "sha256": "0" * 64}]))
        self.assertEqual(sign.main(arguments), 1)
        self.assertFalse((self.repo.root / "toolchains.json.sig").exists())


class AndroidSdk(unittest.TestCase):
    """toolchains/android-sdk: the Android SDK as a toolchain built on the user's machine. Google's license forbids
    passing it on (section 3.4), so nothing of it is built, fetched or published by this repository."""

    def recipes(self):
        return {ident: tc.load(ident) for ident in tc.recipe_ids() if ident.partition("@")[0] == "android-sdk"}

    def test_three_lines_each_one_api_level_pinned_file_by_file(self):
        recipes = self.recipes()
        self.assertEqual(sorted(recipes), ["android-sdk", "android-sdk@35", "android-sdk@36"])
        self.assertEqual({ident: recipe["version"] for ident, recipe in recipes.items()},
                         {"android-sdk": "37.0.0", "android-sdk@36": "36.0.0", "android-sdk@35": "35.0.0"})
        for ident, recipe in recipes.items():
            self.assertTrue(tc.is_local(recipe), ident)
            self.assertEqual((recipe["terms"], recipe["arches"], recipe["requires"]),
                             ("android-sdk-license", ["x86_64"], ["jdk"]), ident)
            fetches = [step for step in recipe["build"] if "fetch" in step]
            self.assertEqual(len(fetches), 7, ident)
            for step in fetches:  # only Google's own host; size, SHA-256 and Google's SHA-1 each
                self.assertTrue(step["url"].startswith("https://dl.google.com/android/repository/"), step["url"])
                self.assertRegex(step["sha256"], r"^[0-9a-f]{64}$")
                self.assertRegex(step["sha1"], r"^[0-9a-f]{40}$")
                self.assertGreater(step["size"], 1 << 20)
            self.assertFalse([step for step in fetches if "emulator" in step["url"] or "sys-img" in step["url"]],
                             "no emulator, no system image: the service android-emulator")
            unpacked = {step["to"]: step["strip"] for step in recipe["build"] if "unpack" in step}
            line = recipe["version"]
            self.assertIn(f"build-tools/{line}", unpacked)
            self.assertEqual(unpacked["cmake/4.1.2"], 0)
            self.assertEqual(unpacked["platform-tools"], 1)
            for command, path in recipe["commands"].items():  # each lies in a package the recipe unpacks
                self.assertTrue(any(path.startswith(folder + "/") for folder in unpacked), (ident, command))
            written = {step["write"]: step["text"] for step in recipe["build"] if "write" in step}
            self.assertEqual(written["licenses/android-sdk-license"], "\n24333f8a63b6825ea9c5514f83c2829b004d1fee")
            for folder in unpacked:  # what sdkmanager writes beside a package: the plugin finds it by that
                self.assertIn('{xmlhead}<license id="android-sdk-license" type="text">{license}</license>',
                              written[f"{folder}/package.xml"])
            self.assertIn("This is the Android Software Development Kit License Agreement", recipe["vars"]["license"])
            self.assertIn("3.4 You may not use the SDK for any purpose not expressly permitted",
                          recipe["vars"]["license"])
            self.assertEqual(recipe["env"]["ANDROID_HOME"], "{prefix}")
            self.assertEqual(recipe["env"]["ANDROID_NDK_HOME"], "{prefix}/ndk/30.0.16248370")
            self.assertIn("android.builder.sdkDownload=false", recipe["env"]["GRADLE_OPTS"])
            self.assertEqual(recipe["hosts"], ["dl.google.com", "maven.google.com"])
            self.assertEqual(tc.problems_of(recipe, TODAY), [])
            entry = tc.local_entry(ident, "x86_64")
            self.assertGreater(entry["unpacked"], 2 << 30)
            self.assertEqual(entry["size"], sum(step["size"] for step in fetches))

    def test_this_repository_fetches_and_publishes_nothing_of_it(self):
        workflow = (ROOT / ".github" / "workflows" / "toolchains.yml").read_text(encoding="utf-8")
        start = workflow.index("toolchain: [", workflow.index("matrix:"))
        self.assertNotIn("android", workflow[start:workflow.index("]", start)])
        self.assertNotIn("dl.google.com/android", workflow)
        catalog = json.loads((ROOT / "toolchains.json").read_text(encoding="utf-8"))
        self.assertFalse([entry for entry in catalog["toolchains"] if entry["name"] == "android-sdk"])
        listed = [entry for entry in catalog.get("recipes", []) if entry["name"] == "android-sdk"]
        self.assertEqual([(entry["version"], entry["arch"]) for entry in listed],
                         [("37.0.0", "x86_64"), ("36.0.0", "x86_64"), ("35.0.0", "x86_64")])
        for entry in listed:
            self.assertNotIn("url", entry)
            self.assertFalse([step for step in entry["recipe"]["steps"]
                              if "fetch" in step and "c0decave" in step["url"]], "no asset of ours")

    @unittest.skipUnless(CHECKOUT and (Path(CHECKOUT) / "sandbox/toolchain_recipes.py").is_file(),
                         "SANDBOX_AI_CHECKOUT names no sandbox-ai with toolchains built on the user's machine")
    def test_sandbox_ai_reads_them_and_they_are_its_own_pins(self):
        recipes = load("android_sdk_recipes")
        self.assertEqual(recipes.main(["--sandbox-ai", CHECKOUT, "--check"]), 0)
        t = smoke.sandbox_ai(Path(CHECKOUT))
        catalog = json.loads((ROOT / "toolchains.json").read_text(encoding="utf-8"))
        for entry in catalog["recipes"]:
            checked = t.validated(entry)  # its reader recomputes the hash that names the tree
            self.assertEqual(checked["recipe"]["terms"], "android-sdk-license")
            self.assertEqual(checked["sha256"], entry["sha256"])


class RustLinker(unittest.TestCase):
    """libexec/rust-cc, rustc's link line for zig cc. CI run 45046360314: on aarch64 rustc passes
    -Wl,--fix-cortex-a53-843419, which zig cc refuses ("unsupported linker arg"), so cargo build failed in both
    sandboxes; the wrapper leaves it out, and the rest of the line as before."""

    def test_the_wrapper_drops_what_zig_cc_refuses_and_keeps_the_rest(self):
        def writes(node):
            if isinstance(node, dict):
                if node.get("write") == "libexec/rust-cc":
                    yield node
                for value in node.values():
                    yield from writes(value)
            elif isinstance(node, list):
                for value in node:
                    yield from writes(value)
        recipe = json.loads((ROOT / "toolchains" / "rust" / "toolchain.json").read_text())
        text = next(writes(recipe))["text"]
        with tempfile.TemporaryDirectory() as tmp:
            wrapper, cc = Path(tmp) / "rust-cc", Path(tmp) / "cc"
            wrapper.write_text(text)
            cc.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
            wrapper.chmod(0o755)
            cc.chmod(0o755)
            out = subprocess.run([str(wrapper), "-Wl,--fix-cortex-a53-843419", "-fuse-ld=lld", f"-B{tmp}/gcc-ld",
                                  "-lgcc_s", "-o", "x", "a b.o"], capture_output=True, text=True, check=True,
                                 env={**os.environ, "PATH": f"{tmp}:{os.environ['PATH']}"}).stdout
        self.assertEqual(out.splitlines(), ["-lunwind", "-o", "x", "a b.o"])


FAKE_BSDTAR = """#!/bin/sh
# bsdtar -c -f - --format pax @ARCHIVE of these tests: an "archive" is the 7z magic, then a tar
for last; do :; done
[ -n "$FAKE_BSDTAR_FAILS" ] && { echo "Unsupported 7z filter" >&2; exit 1; }
tail -c +7 "${last#@}"
"""


def seven_zip(members):
    return tc.SEVEN_ZIP + tar_bytes(members, "w")


class WithBsdtar(unittest.TestCase):
    """A bsdtar of these tests on PATH (the real one decodes 7z; what it hands over is a tar stream either way)."""

    def setUp(self):
        self.repo = Repo(self)
        self.tools = self.repo.root / "tools"
        self.tools.mkdir()
        (self.tools / "bsdtar").write_text(FAKE_BSDTAR)
        (self.tools / "bsdtar").chmod(0o755)
        self.path = os.environ["PATH"]
        os.environ["PATH"] = f"{self.tools}{os.pathsep}{self.path}"
        self.addCleanup(os.environ.update, {"PATH": self.path})
        self.addCleanup(os.environ.pop, "FAKE_BSDTAR_FAILS", None)


class SevenZip(WithBsdtar):
    def test_a_7z_archive_is_read_through_bsdtar_and_unpacked_like_any_other(self):
        top = self.repo.root
        (top / "a.7z").write_bytes(seven_zip({"6.1.0/gcc_64/bin/moc": elf(), "6.1.0/gcc_64/lib/dev": ("chr",),
                                              "6.1.0/gcc_64/lib/libQt6Core.so": ("sym", "libQt6Core.so.6"),
                                              "6.1.0/gcc_64/lib/libQt6Core.so.6": elf(), "6.1.0/other/x": b"x"}))
        tc.unpack(top / "a.7z", top / "tree", strip=2)
        self.assertEqual(sorted(p.relative_to(top / "tree").as_posix() for p in (top / "tree").rglob("*")),
                         ["bin", "bin/moc", "lib", "lib/libQt6Core.so", "lib/libQt6Core.so.6", "x"])
        self.assertEqual(stat_mode(top / "tree/bin/moc"), 0o755)  # tar_bytes gave it a set-user-ID bit
        self.assertEqual(os.readlink(top / "tree/lib/libQt6Core.so"), "libQt6Core.so.6")
        for members, why in (({"a/../../escape": b"x"}, "leaves the tree"),
                             ({"a/bin": ("sym", "/etc"), "a/bin/x": b"x"}, "absolute link")):
            (top / "bad.7z").write_bytes(seven_zip(members))
            with self.assertRaisesRegex(tc.Refused, why):
                tc.unpack(top / "bad.7z", top / "bad", strip=1)
            self.assertFalse((top.parent / "escape").exists())

    def test_without_bsdtar_or_when_it_fails_nothing_is_unpacked(self):
        top = self.repo.root
        (top / "a.7z").write_bytes(seven_zip({"a/x": b"x"}))
        os.environ["FAKE_BSDTAR_FAILS"] = "1"
        with self.assertRaisesRegex(tc.Refused, "a.7z: bsdtar could not read it .*Unsupported 7z filter"):
            tc.unpack(top / "a.7z", top / "tree")
        os.environ["PATH"] = str(top / "nothing")
        with self.assertRaisesRegex(tc.Refused, "a.7z is a 7z archive: bsdtar .libarchive-tools. is needed"):
            tc.unpack(top / "a.7z", top / "tree2")
        self.assertFalse((top / "tree2").exists() and any((top / "tree2").iterdir()))

    def test_a_fetched_file_is_copied_and_a_line_replaced_only_after_its_hash(self):
        text = b"GNU LESSER GENERAL PUBLIC LICENSE\n"
        sha = self.repo.serve("https://example.org/LGPL.txt", text)
        archive = tar_bytes({"d/bin/demo": elf(), "d/mkspecs/qconfig.pri": b"QT_EDITION = Enterprise\nQT_LICHECK = "
                                                                          b"licheck64\nQT_VERSION = 6.1.0\n"})
        steps = [{"fetch": "d.tar.gz", "url": "https://example.org/d.tar.gz",
                  "sha256": self.repo.serve("https://example.org/d.tar.gz", archive), "released": "2026-10-01"},
                 {"unpack": "d.tar.gz", "strip": 1},
                 {"fetch": "LGPL.txt", "url": "https://example.org/LGPL.txt", "sha256": sha},
                 {"copy": "LGPL.txt", "to": "licenses/LGPL-3.0-only.txt"},
                 {"replace": "mkspecs/qconfig.pri", "line": "QT_EDITION =", "with": "QT_EDITION = OpenSource"},
                 {"replace": "mkspecs/qconfig.pri", "line": "QT_LICHECK =", "with": "QT_LICHECK ="}]
        self.repo.recipe(build=steps)
        entry = self.repo.build()["entry"]
        tree = self.repo.root / "out/tree-demo-x86_64"
        self.assertEqual((tree / "licenses/LGPL-3.0-only.txt").read_bytes(), text)
        self.assertEqual((tree / "mkspecs/qconfig.pri").read_text(),
                         "QT_EDITION = OpenSource\nQT_LICHECK =\nQT_VERSION = 6.1.0\n")
        self.assertIn({"url": "https://example.org/LGPL.txt", "sha256": sha}, entry["sources"])
        self.repo.recipe(build=[*steps, {"replace": "mkspecs/qconfig.pri", "line": "QT_NOTHING", "with": "x"}])
        with self.assertRaisesRegex(tc.Refused, "mkspecs/qconfig.pri has no line that begins with 'QT_NOTHING'"):
            self.repo.build()
        self.repo.files["https://example.org/LGPL.txt"] = text + b"x"
        shutil.rmtree(self.repo.root / "out" / "downloads")  # (a kept download with the pinned hash is not fetched again)
        self.repo.recipe(build=steps)
        with self.assertRaisesRegex(tc.Refused, "LGPL.txt: sha256 .*, pinned is"):
            self.repo.build()
        for wrong, why in (([{"copy": "LGPL.txt", "to": "x"}, *steps], "LGPL.txt is used before a hash"),
                           ([*steps, {"replace": "a", "line": "b"}], "replace PATH needs"),
                           ([*steps, {"replace": "a", "line": "b", "with": "c\nd"}], "replace PATH needs")):
            self.assertTrue(any(why in problem for problem in tc.problems_of(self.repo.recipe(build=wrong), TODAY)),
                            why)
        self.assertTrue(any("smoke_apt must be a list of Debian package names" in problem for problem in
                            tc.problems_of(self.repo.recipe(build=steps, smoke_apt=["g++; rm -rf /"]), TODAY)))


def stat_mode(path):
    return os.stat(path).st_mode & 0o7777


class FakeUpstream:
    """PyPI's JSON API, the license files of a tag and Qt's online repository, as these tests serve them."""

    def __init__(self):
        self.files = {}

    def opener(self, url):
        if url not in self.files:
            raise OSError(f"404: {url}")
        return io.BytesIO(self.files[url])

    def licenses(self, version):
        for repository, name, _ in qt.LICENSES:
            self.files[f"{qt.RAW}/{repository}/v{version}/LICENSES/{name}"] = f"{name} of {repository}\n".encode()

    def wheel(self, package, version, requires=(), tag="manylinux_2_34_x86_64", members=None, day="2026-10-08"):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for name, data in (members or {}).items():
                info = zipfile.ZipInfo(name)
                info.external_attr = (0o100000 | (0o755 if name.endswith(("/uic", "/designer")) else 0o644)) << 16
                archive.writestr(info, data)
        data = buffer.getvalue()
        name = f"{package.lower()}-{version}-cp310-abi3-{tag}.whl"
        url = f"https://files.pythonhosted.org/packages/ab/cd/{name}"
        self.files[url] = data
        other = {"filename": name.replace(tag, "win_amd64"), "packagetype": "bdist_wheel", "url": url + ".win",
                 "digests": {"sha256": "0" * 64}, "upload_time": f"{day}T10:00:00"}
        self.files[f"{qt.PYPI}/{package}/{version}/json"] = json.dumps({
            "info": {"requires_dist": list(requires), "requires_python": "<3.16,>=3.10"},
            "urls": [other, {"filename": name, "packagetype": "bdist_wheel", "url": url, "yanked": False,
                             "digests": {"sha256": hashlib.sha256(data).hexdigest()},
                             "upload_time": f"{day}T10:00:00"}]}).encode()
        return url

    def pyside6(self, version="6.12.0", extras=True):
        self.licenses(version)
        requires = [f"PySide6_Essentials=={version}", f"PySide6_Addons=={version}",
                    'tomli>=2.0.1; python_version < "3.11"',
                    *((f"PySide6_WebEngine=={version}.140", f"PySide6_Pdf=={version}.140") if extras else ())]
        self.wheel("PySide6", version, requires, members={f"pyside6-{version}.dist-info/METADATA": b"Name: PySide6\n"})
        self.wheel("shiboken6", version, members={"shiboken6/__init__.py": b"", "shiboken6/Shiboken.abi3.so": elf()})
        self.wheel("PySide6_Essentials", version, members={
            "PySide6/__init__.py": b"", "PySide6/scripts/pyside_tool.py": b"", "PySide6/designer": elf(),
            "PySide6/QtCore.abi3.so": elf(["libQt6Core.so.6"]), "PySide6/Qt/libexec/uic": elf(),
            "PySide6/Qt/lib/libQt6Core.so.6": elf(["libglib-2.0.so.0", "libz.so.1"], "GLIBC_2.34"),
            "PySide6/Qt/plugins/platforms/libqxcb.so": elf(["libxcb-cursor.so.0", "libQt6Core.so.6"])})
        self.wheel("PySide6_Addons", version, members={
            "PySide6/QtCharts.abi3.so": elf(["libQt6Core.so.6"]),
            "PySide6/Qt/lib/libQt6Multimedia.so.6": elf(["libpulse.so.0"])})
        if extras:
            self.wheel("PySide6_WebEngine", f"{version}.140", members={
                "PySide6/Qt/lib/libQt6WebEngineCore.so.6": elf(["libnss3.so"])})
            self.wheel("PySide6_Pdf", f"{version}.140", members={"PySide6/QtPdf.abi3.so": elf(["libQt6Core.so.6"])})

    def qt_repository(self, version="6.12.0", day="2026-10-06"):
        self.licenses(version)
        number, stamp = version.replace(".", ""), f"{version}-0-202610060909"
        top = f"{version}/gcc_64"
        archives = {
            "qtbase-Linux-RHEL_9_6-GCC-Linux-RHEL_9_6-X86_64.7z": {
                **{f"{top}/{path}": elf(["libstdc++.so.6"]) for path in sorted(set(qt.SDK_COMMANDS.values()))},
                f"{top}/lib/libQt6Core.so.6": elf(["libglib-2.0.so.0"], "GLIBC_2.34"),
                f"{top}/lib/libQt6Core.so": ("sym", "libQt6Core.so.6"),
                f"{top}/include/QtCore/qglobal.h": b"// qglobal\n",
                f"{top}/lib/cmake/Qt6/Qt6Config.cmake": b"# Qt6\n",
                f"{top}/mkspecs/qconfig.pri": b"QT_ARCH = x86_64\nQT_EDITION = Enterprise\nQT_LICHECK = licheck64\n",
                f"{top}/plugins/platforms/libqxcb.so": elf(["libxcb-cursor.so.0"])},
            "icu-linux-Rhel8.6-x64.7z": {f"{top}/lib/libicuuc.so.73": elf()},
            "qtcharts-Linux-RHEL_9_6-GCC-Linux-RHEL_9_6-X86_64.7z": {f"{top}/lib/libQt6Charts.so.6": elf()},
            "qtwebengine-Linux-RHEL_9_6-GCC-Linux-RHEL_9_6-X86_64.7z": {
                f"{top}/lib/libQt6WebEngineCore.so.6": elf(["libnss3.so"])},
            "qtmcu-Linux.7z": {f"{top}/lib/libQt6Mcu.so.6": elf()},
        }

        def package(name, files, at=stamp):
            return (f"<PackageUpdate><Name>{name}</Name><Version>{at}</Version><ReleaseDate>{day}</ReleaseDate>"
                    f"<DownloadableArchives>{', '.join(files)}</DownloadableArchives><SHA1>00</SHA1></PackageUpdate>")

        def serve(folder, name, files, at=stamp):
            for file in files:
                data = seven_zip(archives[file])
                self.files[f"{folder}/{name}/{at}{file}"] = data
                self.files[f"{folder}/{name}/{at}{file}.sha256"] = \
                    f"{hashlib.sha256(data).hexdigest()}  {at}{file}\n".encode()
            return package(name, files, at)
        desktop = f"{qt.QT_REPOSITORY}/desktop/qt6_{number}/qt6_{number}"
        base = [name for name in archives if name.startswith(("qtbase", "icu"))]
        self.files[f"{desktop}/Updates.xml"] = ("<Updates>" + "".join([
            package(f"qt.qt6.{number}", []),
            serve(desktop, f"qt.qt6.{number}.linux_gcc_64", base),
            serve(desktop, f"qt.qt6.{number}.addons.qtcharts.linux_gcc_64", [n for n in archives if "qtcharts" in n]),
            # never taken: debug information, sources, a module outside the lists
            package(f"qt.qt6.{number}.debug_info.linux_gcc_64", ["qtbase-debug.7z"]),
            package(f"qt.qt6.{number}.src", ["qtbase-src.7z"]),
            package(f"qt.qt6.{number}.addons.qtmcu.linux_gcc_64", ["qtmcu-Linux.7z"]),
        ]) + "</Updates>").encode()
        engine = f"{qt.QT_REPOSITORY}/extensions/qtwebengine/{number}/x86_64"
        self.files[f"{engine}/Updates.xml"] = ("<Updates>" + serve(
            engine, f"extensions.qtwebengine.{number}.linux_gcc_64",
            [n for n in archives if "qtwebengine" in n]) + "</Updates>").encode()
        pdf = f"{qt.QT_REPOSITORY}/extensions/qtpdf/{number}/x86_64"
        self.files[f"{pdf}/Updates.xml"] = b"<Updates><PackageUpdate><Name>extensions.qtpdf.x.src</Name>" \
            b"<Version>1</Version></PackageUpdate></Updates>"


class QtRecipes(WithBsdtar):
    """scripts/qt_recipe.py: the recipes of pyside6 (PyPI) and qt (download.qt.io) are written from upstream's own
    metadata, every download pinned; what it writes builds."""

    def setUp(self):
        super().setUp()
        self.upstream = FakeUpstream()

    def build(self, recipe, line=None):
        qt.written(recipe, line, self.repo.root)
        ident = recipe["name"] + (f"@{line}" if line else "")
        return tc.build(ident, "x86_64", self.repo.root / "out", today=TODAY, root=self.repo.root,
                        opener=self.upstream.opener)

    def test_pyside6_is_the_wheels_pypi_names_pinned_by_its_hashes(self):
        self.upstream.pyside6()
        recipe = qt.pyside6("6.12.0", self.upstream.opener)
        self.assertEqual(tc.problems_of(recipe, TODAY), [])
        fetches = [step for step in recipe["build"] if "fetch" in step]
        wheels = [step for step in fetches if step["fetch"].endswith(".whl")]
        self.assertEqual([step["fetch"] for step in wheels],
                         ["shiboken6.whl", "pyside6_essentials.whl", "pyside6_addons.whl", "pyside6_webengine.whl",
                          "pyside6_pdf.whl", "pyside6.whl"])
        for step in wheels:
            self.assertEqual(step["sha256"], hashlib.sha256(self.upstream.files[step["url"]]).hexdigest())
            self.assertEqual(step["released"], "2026-10-08")
            self.assertTrue(step["url"].startswith("https://files.pythonhosted.org/packages/"))
            self.assertIn({"unpack": step["fetch"], "to": "python"}, recipe["build"])
        self.assertEqual((recipe["arches"], recipe["requires"], recipe["env"]),
                         (["x86_64"], ["python"], {"PYTHONPATH": "{prefix}/python", "QT_QPA_PLATFORM": "offscreen"}))
        self.assertTrue(all(name.startswith("pyside6-") for name in recipe["commands"]))  # the plain names are qt's
        self.assertLessEqual(len(recipe["description"]), 1000)  # (sandbox-ai takes no longer text)
        self.assertIn("pyside-setup-everywhere-src-6.12.0.tar.xz", recipe["description"])
        meta = self.build(recipe)
        tree = self.repo.root / "out/tree-pyside6-x86_64"
        self.assertTrue((tree / "python/PySide6/Qt/lib/libQt6Core.so.6").is_file())
        self.assertTrue((tree / "python/pyside6-6.12.0.dist-info/METADATA").is_file())
        self.assertEqual(os.readlink(tree / "bin/pyside6-uic"), "pyside6-tool")
        self.assertIn('PYTHONPATH="/opt/toolchains/pyside6/python${PYTHONPATH:+:$PYTHONPATH}" exec python3 -c',
                      (tree / "bin/pyside6-tool").read_text())
        self.assertEqual(sorted(p.name for p in (tree / "licenses").iterdir()),
                         sorted(name for _, name, _ in qt.LICENSES))
        notice = (tree / "NOTICE.txt").read_text()
        for wanted in ("LGPL-3.0-only, GPL-2.0-only or GPL-3.0-only", "pyside-setup-everywhere-src-6.12.0.tar.xz",
                       "qt-everywhere-src-6.12.0.tar.xz", "No module of the commercial-only editions"):
            self.assertIn(wanted, notice)
        # what the libraries need: the 16 named ones; xcb, Multimedia and WebEngine are noted, not checked
        self.assertEqual(meta["measured"]["libraries"], ["libglib-2.0.so.0", "libz.so.1"])
        self.assertEqual(meta["measured"]["optional"]["libraries"], ["libnss3.so", "libpulse.so.0",
                                                                     "libxcb-cursor.so.0"])
        self.assertEqual(meta["entry"]["needs"], {"glibc": "2.34", "libraries": qt.LIBRARIES})
        self.assertEqual(len(qt.LIBRARIES), 16)  # sandbox-ai takes at most 16 (toolchains.LIMITS)

    def test_the_folder_on_pythons_module_path_shadows_nothing_of_python(self):
        """pyside6 sets PYTHONPATH={prefix}/python (sandbox-ai takes it only as a folder of the toolchain's own tree):
        every Python process of the sandbox imports from there first, so the folder may hold nothing named as a module
        of the standard library, and no sitecustomize."""
        self.upstream.pyside6()
        recipe = qt.pyside6("6.12.0", self.upstream.opener)
        self.build(recipe)
        self.assertEqual(tc.python_path_problems(recipe, self.repo.root / "out/tree-pyside6-x86_64"), [])
        for name, why in (("json.py", "python holds json.py"), ("sitecustomize.py", "holds sitecustomize.py"),
                          ("ssl/__init__.py", "holds ssl")):
            with self.subTest(name=name):
                self.upstream.wheel("PySide6_Pdf", "6.12.0.140", members={name: b"print('everywhere')\n"})
                shutil.rmtree(self.repo.root / "out")
                with self.assertRaisesRegex(tc.Refused, why):
                    self.build(qt.pyside6("6.12.0", self.upstream.opener))
        tree = self.repo.root / "tree"
        (tree / "python").mkdir(parents=True)
        for value, why in (("/root/lib", "only one folder of the toolchain's own tree"),
                           ("{prefix}/python:{prefix}/more", "only one folder"), ("{prefix}/..", "only one folder"),
                           ("{prefix}/missing", "no folder of the tree")):
            self.assertIn(why, tc.python_path_problems({"env": {"PYTHONPATH": value}}, tree)[0])
        self.assertEqual(tc.python_path_problems({"env": {"JAVA_HOME": "{prefix}"}}, tree), [])

    def test_a_release_before_the_separate_wheels_and_what_pypi_may_not_say(self):
        self.upstream.pyside6("6.11.3", extras=False)
        recipe = qt.pyside6("6.11.3", self.upstream.opener)
        self.assertEqual([step["fetch"] for step in recipe["build"] if step.get("fetch", "").endswith(".whl")],
                         ["shiboken6.whl", "pyside6_essentials.whl", "pyside6_addons.whl", "pyside6.whl"])
        self.build(recipe, "6.11")
        self.assertTrue((self.repo.root / "out/toolchain-pyside6@6.11-x86_64.tar.xz").is_file())
        self.upstream.wheel("PySide6_Addons", "6.11.3", tag="manylinux_2_39_x86_64")
        with self.assertRaisesRegex(qt.Refused, "built for glibc .*2.39.*measure again"):
            qt.pyside6("6.11.3", self.upstream.opener)
        self.upstream.wheel("PySide6", "6.11.3", ["PySide6_Essentials==6.11.2", "PySide6_Addons==6.11.3"])
        with self.assertRaisesRegex(qt.Refused, "does not pin PySide6_Essentials to 6.11.3"):
            qt.pyside6("6.11.3", self.upstream.opener)
        document = json.loads(self.upstream.files[f"{qt.PYPI}/shiboken6/6.11.3/json"])
        document["urls"][1]["url"] = "https://example.org/shiboken6.whl"
        self.upstream.files[f"{qt.PYPI}/shiboken6/6.11.3/json"] = json.dumps(document).encode()
        with self.assertRaisesRegex(qt.Refused, "outside its file host"):
            qt.wheel("shiboken6", "6.11.3", self.upstream.opener)
        with self.assertRaisesRegex(qt.Refused, "a release such as 6.12.0"):
            qt.pyside6("6.12", self.upstream.opener)

    def test_the_committed_pyside6_recipes_are_what_the_script_writes(self):
        for ident, version in (("pyside6", "6.12.0"), ("pyside6@6.11", "6.11.3")):
            recipe = tc.load(ident)
            self.assertEqual(recipe["version"], version)
            wheels = [step for step in recipe["build"] if step.get("fetch", "").endswith(".whl")]
            self.assertGreaterEqual(len(wheels), 4)
            self.assertTrue(all(step["url"].startswith("https://files.pythonhosted.org/packages/")
                                and f"-{version}" in step["url"] and "manylinux_2_34_x86_64" in step["url"]
                                for step in wheels), ident)
            licenses = [step for step in recipe["build"] if step.get("fetch", "").startswith("license-")]
            self.assertEqual([step["url"].split("/LICENSES/")[0] for step in licenses],
                             [f"{qt.RAW}/{repository}/v{version}" for repository, _, _ in qt.LICENSES])
            # everything but the pins is the script's: a change of the template is a change of the recipes
            for key in ("commands", "env", "needs", "requires", "optional", "smoke", "arches", "allow", "license"):
                self.assertEqual(recipe[key], {"commands": {f"pyside6-{name}": f"bin/pyside6-{name}"
                                                            for name in qt.PYSIDE_TOOLS},
                                               "env": {"PYTHONPATH": "{prefix}/python",
                                                       "QT_QPA_PLATFORM": "offscreen"},
                                               "needs": {"glibc": qt.GLIBC, "libraries": qt.LIBRARIES},
                                               "requires": ["python"], "optional": qt.OPTIONAL,
                                               "smoke": qt.PYSIDE_SMOKE, "arches": ["x86_64"], "allow": [],
                                               "license": "LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only"}[key],
                                 f"{ident}: {key}")

    def test_qt_is_the_archives_of_the_online_repository_pinned_by_its_hashes(self):
        self.upstream.qt_repository()
        said = []
        recipe = qt.qt("6.12.0", self.upstream.opener, out=said.append)
        self.assertEqual(tc.problems_of(recipe, TODAY), [])
        fetches = [step for step in recipe["build"] if step.get("fetch", "").endswith(".7z")]
        self.assertEqual([step["fetch"] for step in fetches],
                         ["qt-qtbase-Linux-RHEL_9_6-GCC-Linux-RHEL_9_6-X86_64.7z", "qt-icu-linux-Rhel8.6-x64.7z",
                          "qtcharts-qtcharts-Linux-RHEL_9_6-GCC-Linux-RHEL_9_6-X86_64.7z",
                          "qtwebengine-qtwebengine-Linux-RHEL_9_6-GCC-Linux-RHEL_9_6-X86_64.7z"])
        for step in fetches:
            self.assertTrue(step["url"].startswith("https://download.qt.io/online/qtsdkrepository/linux_x64/"))
            self.assertEqual(step["sha256"], hashlib.sha256(self.upstream.files[step["url"]]).hexdigest())
            self.assertEqual(step["released"], "2026-10-06")
            self.assertIn({"unpack": step["fetch"], "strip": 2}, recipe["build"])
        self.assertIn("left out: qt.qt6.6120.addons.qtmcu.linux_gcc_64 (not among ADDONS)", said)
        self.assertIn("not in the repository for 6.12.0: qtpdf", said)
        self.assertFalse(any("debug" in step.get("url", "") or "src" in step.get("fetch", "")
                             for step in recipe["build"]))
        self.assertEqual((recipe["requires"], recipe["smoke_apt"][0], recipe["env"]["CMAKE_PREFIX_PATH"]),
                         (["pyside6"], "g++", "{prefix}"))
        self.assertNotIn("QT_PLUGIN_PATH", recipe["env"])
        self.assertLessEqual(len(recipe["description"]), 1000)
        self.assertIn("qt-everywhere-src-6.12.0.tar.xz", recipe["description"])
        # what it writes builds: the tree is the SDK's prefix, set to the open-source edition
        self.repo.recipe(name="pyside6", build=[])
        meta = self.build(recipe)
        tree = self.repo.root / "out/tree-qt-x86_64"
        for path in ("bin/qmake", "libexec/moc", "include/QtCore/qglobal.h", "lib/cmake/Qt6/Qt6Config.cmake",
                     "lib/libicuuc.so.73", "lib/libQt6Charts.so.6", "lib/libQt6WebEngineCore.so.6",
                     "licenses/LGPL-3.0-only.txt", "NOTICE.txt"):
            self.assertTrue((tree / path).is_file(), path)
        self.assertFalse((tree / "lib/libQt6Mcu.so.6").exists())
        self.assertEqual((tree / "mkspecs/qconfig.pri").read_text(),
                         "QT_ARCH = x86_64\nQT_EDITION = OpenSource\nQT_LICHECK =\n")
        self.assertEqual(((tree / "bin/qt.conf").read_text(), (tree / "libexec/qt.conf").read_text()),
                         ("[Paths]\nPrefix=..\n",) * 2)
        self.assertEqual(meta["smoke_apt"], ["g++", "make", "cmake", "ninja-build", "libgl1-mesa-dev"])
        self.assertEqual(len(meta["entry"]["sources"]), 4 + len(qt.LICENSES))

    def test_what_the_online_repository_may_not_say(self):
        self.upstream.qt_repository()
        desktop = f"{qt.QT_REPOSITORY}/desktop/qt6_6120/qt6_6120"
        good = dict(self.upstream.files)
        archive = next(url for url in good if url.endswith("X86_64.7z") and "qtbase" in url)
        for change, why in (
                ({archive + ".sha256": b"not a hash\n"}, "sha256: no SHA-256"),
                ({f"{desktop}/Updates.xml": good[f"{desktop}/Updates.xml"].replace(b"6.12.0-0-", b"6.12.1-0-")},
                 "is 6.12.1-0-202610060909, not 6.12.0"),
                ({f"{desktop}/Updates.xml": good[f"{desktop}/Updates.xml"].replace(b"qtbase-Linux", b"../x/Linux")},
                 "no plain name"),
                ({f"{desktop}/Updates.xml": good[f"{desktop}/Updates.xml"].replace(b"2026-10-06", b"soon")},
                 "has no release date"),
                ({f"{desktop}/Updates.xml": b"<Updates></Updates>"}, "it names no package"),
                ({f"{desktop}/Updates.xml": b"<html>"}, "not XML")):
            with self.subTest(why=why):
                self.upstream.files = {**good, **change}
                with self.assertRaisesRegex(qt.Refused, why):
                    qt.qt("6.12.0", self.upstream.opener, out=lambda line: None)
        self.upstream.files = {key: value for key, value in good.items() if key != f"{desktop}/Updates.xml"}
        with self.assertRaisesRegex(qt.Refused, "Updates.xml: .*404"):
            qt.qt("6.12.0", self.upstream.opener, out=lambda line: None)
        # an extension the repository does not have (so) is left out and said, the rest is the recipe
        engine = f"{qt.QT_REPOSITORY}/extensions/qtwebengine/6120/x86_64/Updates.xml"
        self.upstream.files = {key: value for key, value in good.items() if key != engine}
        said = []
        recipe = qt.qt("6.12.0", self.upstream.opener, out=said.append)
        self.assertTrue(any(line.startswith("left out: the extension qtwebengine (") and "404" in line
                            for line in said), said)
        self.assertFalse(any("qtwebengine" in step.get("fetch", "") for step in recipe["build"]))
        # an archive that changed after it was pinned is never unpacked
        self.upstream.files = dict(good)
        recipe = qt.qt("6.12.0", self.upstream.opener, out=lambda line: None)
        self.upstream.files[archive] = good[archive] + b"x"
        self.repo.recipe(name="pyside6", build=[])
        with self.assertRaisesRegex(tc.Refused, "sha256 .*, pinned is .*: not used"):
            self.build(recipe)

    def test_a_release_younger_than_14_days_is_not_a_recipe_yet(self):
        self.upstream.qt_repository(day="2026-11-15")
        recipe = qt.qt("6.12.0", self.upstream.opener, out=lambda line: None)
        self.assertTrue(any("was released 2026-11-15, 7 days before" in problem
                            for problem in tc.problems_of(recipe, TODAY)))


class SmokeImage(unittest.TestCase):
    def test_the_image_has_what_the_agent_images_give_qt_and_a_toolchains_own_packages_on_top(self):
        for package in ("libegl1", "libgl1", "libfontconfig1", "libxkbcommon0", "libglib2.0-0", "libdbus-1-3",
                        "fonts-dejavu-core", "openssl"):
            self.assertIn(f" {package} ", smoke.CONTAINERFILE.replace("\\\n", " "))
        self.assertEqual(smoke.containerfile(), smoke.CONTAINERFILE)
        own = smoke.containerfile(["g++", "cmake", "libgl1-mesa-dev"])
        self.assertTrue(own.startswith(smoke.CONTAINERFILE))
        self.assertIn("apt-get install -y --no-install-recommends \\\n    g++ cmake libgl1-mesa-dev \\\n", own)
        with self.assertRaisesRegex(ValueError, "Debian package names"):
            smoke.containerfile(["g++ && curl evil"])
        seen = []

        def run(command, **options):
            seen.append(command)
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")
        with tempfile.TemporaryDirectory() as tmp:
            image, problem = smoke.smoke_image(Path(tmp) / "a", run, ["g++"], "qt")
            self.assertEqual((image, problem), ("localhost/sandbox-ai-toolchain-smoke-qt:latest", None))
            self.assertIn("g++", (Path(tmp) / "a/Containerfile").read_text())
            self.assertEqual(smoke.smoke_image(Path(tmp) / "b", run)[0], smoke.SMOKE_IMAGE)
        self.assertEqual([command[command.index("-t") + 1] for command in seen],
                         ["localhost/sandbox-ai-toolchain-smoke-qt:latest", smoke.SMOKE_IMAGE])


if __name__ == "__main__":
    unittest.main()
