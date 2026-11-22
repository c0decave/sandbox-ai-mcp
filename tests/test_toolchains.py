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
                info.size, info.mode = len(value), 0o4755 if "/bin/" in name else 0o644
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

    def recipe(self, name="demo", **more):
        recipe = {"name": name, "version": "1.2.3", "title": "Demo", "description": "A demo.", "license": "MIT",
                  "homepage": "https://example.org", "arches": ["x86_64"], "commands": {"demo": "bin/demo"},
                  "env": {"DEMO_HOME": "{prefix}"}, "caches": {}, "hosts": ["example.org"], "allow": [],
                  "needs": {"glibc": "2.17", "libraries": []}, "requires": [], **more}
        path = self.root / "toolchains" / name
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
        names = sorted(path.parent.name for path in (ROOT / "toolchains").glob("*/toolchain.json"))
        self.assertGreaterEqual(set(names), {"go", "python", "jdk", "zig", "node", "dotnet", "cc", "rust"})
        for name in names:
            recipe = tc.load(name)
            self.assertEqual(tc.problems_of(recipe, TODAY), [], name)
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
        self.assertEqual(make.from_ci(self.ci)[0], [])
        self.report("sandbox-ai-podman")
        entries, left_out = make.from_ci(self.ci)
        self.assertEqual(entries, [])
        self.assertIn("no smoke-demo-x86_64-sandbox-ai-bwrap.json", left_out[0])
        for change, why in (({"ok": False}, "sandbox-ai-bwrap failed"), ({"sha256": "0" * 64}, "is of the archive"),
                            ({"checks": [{"check": "mounted as sandbox-ai mounts it", "ok": True}]},
                             "nothing was run"), ({"arch": "aarch64"}, "is not the sandbox-ai-bwrap report")):
            self.report("sandbox-ai-bwrap", **change)
            self.assertIn(why, make.from_ci(self.ci)[1][0])
        self.report("sandbox-ai-bwrap")
        entries, left_out = make.from_ci(self.ci)
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
        entries, left_out = make.from_ci(self.ci)
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
        for path in sorted((ROOT / "toolchains").glob("*/toolchain.json")):  # every recipe's manifest
            recipe = tc.load(path.parent.name)
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


if __name__ == "__main__":
    unittest.main()
