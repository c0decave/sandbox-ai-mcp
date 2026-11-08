"""The file-analysis servers (radare2, capa, binwalk) and what every server of this repository must
look like: no network, input read-only, pinned images and sources, a smoke spec that calls the tool
with a fixture whose SHA-256 is pinned - and, with SANDBOX_AI_CHECKOUT, that sandbox-ai's own reader
makes of each entry exactly what the catalog says."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
#: Servers that analyse a file the user holds: no network, input mounted read-only.
FILE_ANALYSIS = ("binwalk", "capa", "radare2")


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fixtures = load("fixtures")
make_catalog = load("make_catalog")


def servers() -> list[str]:
    return sorted(path.parent.name for path in (ROOT / "servers").glob("*/server.json"))


def read_json(*parts: str):
    return json.loads(Path(ROOT, *parts).read_text(encoding="utf-8"))


class Fixtures(unittest.TestCase):
    def test_the_binary_fixtures_match_their_pinned_sha256(self):
        found = fixtures.load()
        self.assertEqual(sorted(f["path"] for f in found), ["caps", "firmware.bin", "hello"])
        for fixture in found:
            self.assertLess(fixture["size"], 1 << 20, f"{fixture['path']} should stay a small fixture")

    def test_a_changed_fixture_is_refused(self):
        document = read_json("tests/fixtures/analysis-files.json")
        document["files"][0]["sha256"] = "0" * 64
        with tempfile.TemporaryDirectory() as folder:
            spec = Path(folder, "analysis-files.json")
            spec.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(fixtures.FixtureProblem):
                fixtures.load(spec)
            self.assertEqual(fixtures.main(["--spec", str(spec), "--check"]), 1)
            self.assertEqual(list(Path(folder).iterdir()), [spec], "nothing is written when a pin fails")

    def test_the_fixtures_are_written_without_an_executable_bit(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(fixtures.main(["--out", folder]), 0)
            for path in Path(folder).iterdir():
                self.assertFalse(path.stat().st_mode & 0o111, f"{path.name} is analysed, never executed")


class EveryServer(unittest.TestCase):
    def test_the_folders_are_complete(self):
        for name in servers():
            with self.subTest(server=name):
                folder = ROOT / "servers" / name
                for required in ("Dockerfile", "server.json", "smoke.json", "tools.json", "PROVENANCE.md"):
                    self.assertTrue((folder / required).is_file(), f"{name}: {required} is missing")
                self.assertTrue(any((folder / "LICENSES").glob("*")), f"{name}: LICENSES/ is empty")

    def test_the_base_image_is_pinned_by_digest(self):
        for name in servers():
            with self.subTest(server=name):
                text = (ROOT / "servers" / name / "Dockerfile").read_text()
                images = re.findall(r"^\s*(?:ARG\s+\w*IMAGE=|FROM\s+)(\S+)", text, re.M)
                named = [image for image in images if not image.startswith("${")]
                self.assertTrue(named, f"{name}: no base image")
                for image in named:
                    self.assertRegex(image, r"@sha256:[0-9a-f]{64}$",
                                     f"{name}: {image} is not pinned by digest")
                # Sources fetched during the build are pinned by commit, never by tag or branch.
                for value in re.findall(r"^\s*ARG\s+\w*(?:COMMIT|REF)=(\S+)", text, re.M):
                    self.assertRegex(value, r"^[0-9a-f]{40}$", f"{name}: {value} is not a commit ID")
                self.assertNotRegex(text, r"git (?:clone|checkout) .*(?:--branch|-b) ",
                                    f"{name}: a branch is not a pin")

    def test_the_final_stage_pins_its_debian_packages_and_runs_as_a_user(self):
        for name in servers():
            with self.subTest(server=name):
                text = (ROOT / "servers" / name / "Dockerfile").read_text()
                final = text[[m.start() for m in re.finditer(r"^FROM ", text, re.M)][-1]:]
                for install in re.findall(r"apt-get install[^\n]*(?:\\\n[^\n]*)*", final):
                    for package in re.findall(r"(?<![-\w])([a-z][a-z0-9.+-]{1,40})(?==\S)|"
                                              r"(?<![-\w=/])([a-z][a-z0-9.+]{2,40})(?=[\s\\])", install):
                        unpinned = package[1]
                        if unpinned and unpinned not in ("apt", "get", "install", "y", "no", "true"):
                            self.fail(f"{name}: the final image installs {unpinned} without a version")
                self.assertRegex(final, r"(?m)^USER 10001:10001$", msg=f"{name}: the server must not run as root")

    def test_the_smoke_spec_calls_the_tools_the_server_offers(self):
        for name in servers():
            with self.subTest(server=name):
                spec = read_json("servers", name, "smoke.json")
                tools = read_json("servers", name, "tools.json")["tools"]
                self.assertEqual(spec["name"], name)
                self.assertTrue(spec.get("calls"), f"{name}: the smoke spec must call the tool "
                                                   "(sign_catalog.py refuses a run without a call)")
                for tool in spec.get("expect_tools", []) + [c["tool"] for c in spec.get("calls", [])]:
                    self.assertIn(tool, tools, f"{name}: {tool} is not in tools.json")

    def test_the_smoke_spec_mounts_only_folders_the_entry_declares(self):
        for name in servers():
            with self.subTest(server=name):
                spec = read_json("servers", name, "smoke.json")
                entry = read_json("servers", name, "server.json")
                declared = {mount["target"]: mount for mount in entry.get("mounts", [])}
                for mount in spec.get("mounts", []):
                    self.assertIn(mount["target"], declared,
                                  f"{name}: the smoke mounts {mount['target']}, the entry does not offer it")
                    if mount.get("writable"):
                        self.assertNotEqual(mount["target"], "/work",
                                            f"{name}: input is mounted read-only")
                for target, mount in declared.items():
                    if mount.get("required"):
                        self.assertIn(target, [m["target"] for m in spec.get("mounts", [])],
                                      f"{name}: the entry requires {target}, the smoke does not mount it")

    def test_the_smoke_spec_uses_the_files_the_fixtures_give(self):
        available = {f["path"] for f in fixtures.load()} | {
            path.name for path in (ROOT / "tests/fixtures").glob("*") if path.is_file()}
        for name in servers():
            with self.subTest(server=name):
                spec = read_json("servers", name, "smoke.json")
                mounted = {mount["target"] for mount in spec.get("mounts", []) if mount["host"] == "${FIXTURES}"}
                for call in spec.get("calls", []):
                    for value in call.get("arguments", {}).values():
                        if not isinstance(value, str):
                            continue
                        folder, _, file = value.rpartition("/")
                        if folder in mounted:
                            self.assertIn(file, available, f"{name}: the smoke uses {value}, which no "
                                                           "fixture provides")


class FileAnalysisServers(unittest.TestCase):
    """radare2, capa and binwalk: a file the user holds, nothing else."""

    def test_they_are_all_there(self):
        self.assertEqual([name for name in servers() if name in FILE_ANALYSIS], list(FILE_ANALYSIS))

    def test_no_network_and_no_secrets(self):
        for name in FILE_ANALYSIS:
            with self.subTest(server=name):
                entry = read_json("servers", name, "server.json")
                self.assertEqual(entry["network"], "none")
                self.assertEqual(entry.get("hosts", []), [])
                self.assertEqual(entry.get("env", []), [], f"{name} needs no variable and no secret")
                self.assertEqual(read_json("servers", name, "smoke.json").get("network", "none"), "none",
                                 f"{name}: the smoke run must have no network either")

    def test_the_input_folder_is_required_and_the_only_writable_one_is_out(self):
        for name in FILE_ANALYSIS:
            with self.subTest(server=name):
                entry = read_json("servers", name, "server.json")
                mounts = {mount["target"]: mount for mount in entry["mounts"]}
                self.assertIn("/work", mounts)
                self.assertTrue(mounts["/work"].get("required"), f"{name}: /work is where the file comes from")
                self.assertIn("read-only", mounts["/work"]["description"])
                self.assertEqual(sorted(mounts), ["/out", "/work"] if name == "binwalk" else ["/work"])
                if name == "binwalk":
                    self.assertIn("writable", mounts["/out"]["description"])
                    self.assertIn("/out", entry["notes"], "the notes must say what writes there")

    def test_the_catalog_entry_says_what_the_server_does(self):
        catalog = read_json("catalog.json")
        entries = {entry["name"]: entry for entry in catalog["entries"]}
        for name in FILE_ANALYSIS:
            with self.subTest(server=name):
                self.assertIn(name, entries)
                self.assertEqual(entries[name]["id"], f"mcp:{name}")
                self.assertEqual(entries[name]["image"], make_catalog.IMAGE_PREFIX + name)
                self.assertEqual(entries[name]["category"], "Analysis: Files")
                self.assertIn("/work", entries[name]["description"])
                self.assertNotIn("digest", entries[name], "not published yet: pending-digests")

    def test_the_provenance_pins_every_source(self):
        for name in FILE_ANALYSIS:
            with self.subTest(server=name):
                text = (ROOT / "servers" / name / "PROVENANCE.md").read_text()
                self.assertIn("Base image", text)
                self.assertIn("Ported from", text)
                self.assertRegex(text, r"`[0-9a-f]{40}`", f"{name}: no commit is pinned in PROVENANCE.md")
                dockerfile = (ROOT / "servers" / name / "Dockerfile").read_text()
                for commit in re.findall(r"^ARG \w*COMMIT=([0-9a-f]{40})$", dockerfile, re.M):
                    self.assertIn(commit, text, f"{name}: {commit} is built but not in PROVENANCE.md")


@unittest.skipUnless(os.environ.get("SANDBOX_AI_CHECKOUT"), "SANDBOX_AI_CHECKOUT names a sandbox-ai checkout")
class SandboxAiAgrees(unittest.TestCase):
    """What this repository writes and what `sandbox-ai mcp add` accepts must be the same thing."""

    def setUp(self):
        self.checkout = Path(os.environ["SANDBOX_AI_CHECKOUT"]).resolve()

    def sandbox_ai_mcp(self):
        spec = importlib.util.spec_from_file_location("sandbox_ai_mcp_for_tests", self.checkout / "sandbox/mcp.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_the_committed_catalog_is_read_by_sandbox_ai(self):
        self.assertEqual(make_catalog.main(["--root", str(ROOT), "--check", "--allow-pending",
                                            "--sandbox-ai", str(self.checkout)]), 0)

    def test_a_fully_pinned_catalog_becomes_definitions_sandbox_ai_accepts(self):
        """With digests (as after a CI run) every entry, mounts and all, must become a definition."""
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        root = tmp / "repo"
        shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns(".git", "__pycache__", "candidates",
                                                                  "sandbox-ai"))
        digest = "sha256:" + "ab" * 32
        digests = json.loads((root / "digests.json").read_text())
        digests["images"] = {name: digest for name in digests["images"]}
        (root / "digests.json").write_text(json.dumps(digests, indent=2) + "\n")
        self.assertEqual(make_catalog.main(["--root", str(root)]), 0)
        self.assertEqual(make_catalog.main(["--root", str(root), "--check", "--sandbox-ai", str(self.checkout)]), 0)
        mcp = self.sandbox_ai_mcp()
        entries = mcp.read_catalog(str(root / "catalog.json"))
        for name in FILE_ANALYSIS:
            entry = next(e for e in entries if e["name"] == name)
            definition = mcp.definition_from_entry(entry, mounts=[f"/work={tmp}:ro"])
            self.assertEqual(definition["network"], "none")
            self.assertEqual(definition["image"], f"{make_catalog.IMAGE_PREFIX}{name}@{digest}")
            self.assertEqual(definition["mounts"], [{"target": "/work", "host": str(tmp), "mode": "ro"}])
            command = mcp.image_command(definition)
            self.assertIn("--network=none", command)
            self.assertIn(f"--volume={tmp}:/work:ro", command)
            self.assertIn("--read-only", command)
            with self.assertRaises(ValueError):  # the folder is required: no server without it
                mcp.definition_from_entry(entry)

    def test_the_smoke_run_line_is_sandbox_ais(self):
        smoke = load("smoke_test")
        mcp = self.sandbox_ai_mcp()
        missing = [flag for flag in mcp.RUN_FLAGS if flag not in smoke.RUN_FLAGS]
        self.assertEqual(missing, [], "scripts/smoke_test.py no longer starts servers as sandbox-ai does")
        extra = [flag for flag in smoke.RUN_FLAGS if flag not in mcp.RUN_FLAGS]
        self.assertEqual(sorted(extra), ["--memory=512m", "--pids-limit=128"],
                         "sandbox-ai adds exactly the limits per definition")


if __name__ == "__main__":
    unittest.main()
