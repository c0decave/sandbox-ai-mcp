"""scripts/maven_central.py: the jars a server ships compared with the same release on Maven Central (CI)."""

from __future__ import annotations

import hashlib
import io
import json
import re
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import maven_central  # noqa: E402

REPO = maven_central.REPOSITORY


def jar(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


LIB = {"META-INF/MANIFEST.MF": b"Manifest-Version: 1.0\n", "org/example/lib/A.class": b"\xca\xfe\xba\xbeA",
       "org/example/lib/B.class": b"\xca\xfe\xba\xbeB", "lib.properties": b"version=1.0\n"}
CORE = {"META-INF/MANIFEST.MF": b"Manifest-Version: 1.0\nX: core\n", "org/example/core/C.class": b"\xca\xfe\xba\xbeC"}
GUAVA = {"com/google/common/G.class": b"\xca\xfe\xba\xbeG"}


def fat(**changes: bytes | None) -> bytes:
    files = {"META-INF/MANIFEST.MF": b"Manifest-Version: 1.0\nMain-Class: org.example.lib.A\n"}
    files.update({k: v for k, v in LIB.items() if not k.startswith("META-INF/")})
    files.update({k: v for k, v in CORE.items() if not k.startswith("META-INF/")})
    files.update(GUAVA)
    for name, data in changes.items():
        name = name.replace("__", "/").replace("_dot_", ".")
        if data is None:
            files.pop(name)
        else:
            files[name] = data
    return jar(files)


class Server:
    """A server folder with a Dockerfile and a maven-central.json, and a fake Maven Central."""

    def __init__(self, folder: Path, shipped: bytes, sha256: str | None = None):
        self.folder = folder
        (folder / "Dockerfile").write_text(
            "FROM scratch\n"
            "ARG LIB_URL=https://github.com/example/lib/releases/download/1.0/lib-1.0-fat.jar\n"
            f"ARG LIB_SHA256={sha256 or hashlib.sha256(shipped).hexdigest()}\n")
        (folder / "maven-central.json").write_text(json.dumps({
            "schema": "sandbox-ai-mcp-maven-central", "version": 1,
            "jars": [{"url_arg": "LIB_URL", "sha256_arg": "LIB_SHA256", "image_path": "/opt/lib/lib-1.0-fat.jar",
                      "built_from": ["org.example:lib:1.0", "org.example:core:1.0"],
                      "own_prefixes": ["org/example/"]}]}))
        self.files = {"https://github.com/example/lib/releases/download/1.0/lib-1.0-fat.jar": shipped}
        for artifact, files in (("lib", LIB), ("core", CORE)):
            self.publish(f"{REPO}/org/example/{artifact}/1.0/{artifact}-1.0.jar", jar(files))
        self.asked: list[str] = []

    def publish(self, url: str, data: bytes, sha1: str | None = None, sha256: str | None = None):
        self.files[url] = data
        self.files[url + ".sha1"] = (sha1 or hashlib.sha1(data).hexdigest()).encode()
        self.files[url + ".sha256"] = (sha256 or hashlib.sha256(data).hexdigest()).encode()

    def get(self, url: str) -> bytes | None:
        self.asked.append(url)
        return self.files.get(url)


class Compare(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name) / "lib"
        self.folder.mkdir()

    def run_check(self, shipped: bytes, **kw) -> tuple[Server, dict]:
        server = Server(self.folder, shipped, **kw)
        return server, maven_central.check(self.folder, server.get)

    def test_a_fat_jar_of_the_release_files_passes_and_says_what_was_compared(self):
        server, report = self.run_check(fat())
        self.assertTrue(report["passed"], report)
        (result,) = report["jars"]
        self.assertEqual((result["identical"], result["release_files"]), (4, 4))
        self.assertEqual(result["own_files"], 3)
        self.assertEqual(result["not_compared"], 2, "the manifest and the bundled guava class")
        self.assertIn("byte for byte", result["compared"])
        self.assertIn(f"{REPO}/org/example/lib/1.0/lib-1.0.jar.sha256", server.asked)

    def test_a_jar_identical_to_the_maven_central_jar_passes_as_such(self):
        _, report = self.run_check(jar(LIB))
        self.assertTrue(report["passed"])
        self.assertEqual(report["jars"][0]["identical_to"], "org.example:lib:1.0")

    def test_a_changed_class_fails(self):
        _, report = self.run_check(fat(org__example__lib__B_dot_class=b"\xca\xfe\xba\xbeX"))
        self.assertFalse(report["passed"])
        self.assertEqual(report["jars"][0]["differing"], ["org/example/lib/B.class"])

    def test_a_class_left_out_fails(self):
        _, report = self.run_check(fat(org__example__core__C_dot_class=None))
        self.assertFalse(report["passed"])
        self.assertEqual(report["jars"][0]["missing"], ["org/example/core/C.class"])

    def test_a_changed_resource_outside_the_packages_fails(self):
        _, report = self.run_check(fat(lib_dot_properties=b"version=evil\n"))
        self.assertFalse(report["passed"])
        self.assertEqual(report["jars"][0]["differing"], ["lib.properties"])

    def test_a_class_added_to_the_release_packages_fails(self):
        _, report = self.run_check(fat(org__example__lib__Extra_dot_class=b"\xca\xfe\xba\xbeE"))
        self.assertFalse(report["passed"])
        self.assertEqual(report["jars"][0]["added"], ["org/example/lib/Extra.class"])

    def test_a_shipped_jar_that_is_not_the_pinned_one_fails(self):
        with self.assertRaisesRegex(maven_central.Problem, "the Dockerfile pins"):
            self.run_check(fat(), sha256="0" * 64)

    def test_maven_central_checksums_are_checked(self):
        server = Server(self.folder, fat())
        url = f"{REPO}/org/example/core/1.0/core-1.0.jar"
        server.publish(url, jar(CORE), sha256="1" * 64)
        with self.assertRaisesRegex(maven_central.Problem, "sha256"):
            maven_central.check(self.folder, server.get)
        server.publish(url, jar(CORE), sha1="2" * 40)
        with self.assertRaisesRegex(maven_central.Problem, "sha1"):
            maven_central.check(self.folder, server.get)

    def test_a_missing_sha1_fails_and_a_missing_sha256_is_said(self):
        server = Server(self.folder, fat())
        url = f"{REPO}/org/example/core/1.0/core-1.0.jar"
        del server.files[url + ".sha256"]
        report = maven_central.check(self.folder, server.get)
        self.assertTrue(report["passed"])
        self.assertTrue(any("no .sha256" in note for note in report["notes"]))
        del server.files[url + ".sha1"]
        with self.assertRaisesRegex(maven_central.Problem, r"\.sha1"):
            maven_central.check(self.folder, server.get)

    def test_an_artifact_not_on_maven_central_fails(self):
        server = Server(self.folder, fat())
        del server.files[f"{REPO}/org/example/core/1.0/core-1.0.jar"]
        with self.assertRaisesRegex(maven_central.Problem, "not on Maven Central"):
            maven_central.check(self.folder, server.get)

    def test_only_the_dockerfile_url_and_maven_central_are_fetched(self):
        server, _ = self.run_check(fat())
        for url in server.asked:
            self.assertTrue(url.startswith((REPO + "/", "https://github.com/example/")), url)

    def test_a_shipped_url_off_github_is_refused(self):
        Server(self.folder, fat())
        text = (self.folder / "Dockerfile").read_text().replace("https://github.com/", "http://example.org/")
        (self.folder / "Dockerfile").write_text(text)
        with self.assertRaisesRegex(maven_central.Problem, "https URL"):
            maven_central.load_spec(self.folder)

    def test_a_server_without_a_spec_has_nothing_to_do(self):
        report = maven_central.check(self.folder, lambda url: self.fail(f"fetched {url}"))
        self.assertTrue(report["passed"])
        self.assertEqual(report["jars"], [])


class TheServers(unittest.TestCase):
    """smali's fat jars and cfr's release jar are compared with Maven Central before their images are built."""

    def spec(self, name):
        return maven_central.load_spec(ROOT / "servers" / name)

    def test_smali_names_the_four_google_artifacts_of_3_0_10(self):
        jars = {Path(jar["image_path"]).name: jar for jar in self.spec("smali")["jars"]}
        self.assertEqual(sorted(jars), ["baksmali-3.0.10-fat-release.jar", "smali-3.0.10-fat-release.jar"])
        group = "com.android.tools.smali"
        self.assertEqual(jars["baksmali-3.0.10-fat-release.jar"]["built_from"],
                         [f"{group}:baksmali:3.0.10", f"{group}:dexlib2:3.0.10", f"{group}:util:3.0.10"])
        self.assertEqual(jars["smali-3.0.10-fat-release.jar"]["built_from"],
                         [f"{group}:smali:3.0.10", f"{group}:dexlib2:3.0.10", f"{group}:util:3.0.10"])
        for name, entry in jars.items():
            self.assertEqual(entry["own_prefixes"], ["com/android/tools/smali/"])
            self.assertTrue(entry["url"].endswith("/" + name))

    def test_cfr_names_org_benf_cfr_0_152(self):
        (entry,) = self.spec("cfr")["jars"]
        self.assertEqual(entry["built_from"], ["org.benf:cfr:0.152"])
        self.assertEqual(entry["image_path"], "/opt/cfr/cfr-0.152.jar")

    def test_the_image_paths_are_where_the_dockerfiles_put_the_jars(self):
        for name in ("smali", "cfr"):
            dockerfile = (ROOT / "servers" / name / "Dockerfile").read_text()
            raw = json.loads((ROOT / "servers" / name / "maven-central.json").read_text())
            for entry in raw["jars"]:
                with self.subTest(server=name, jar=entry["image_path"]):
                    # the image takes exactly the bytes compared: ADD by the same URL and SHA-256 ARGs
                    self.assertRegex(dockerfile, rf"(?m)^ADD --checksum=sha256:\${{{entry['sha256_arg']}}} "
                                                 rf"\${{{entry['url_arg']}}} \S*/{Path(entry['image_path']).name}$")
                    self.assertTrue(entry["image_path"].startswith(f"/opt/{name}/"))

    def test_the_workflow_compares_before_the_build_and_checks_the_built_image(self):
        workflow = (ROOT / ".github/workflows/build.yml").read_text()
        image_job = workflow[workflow.index("\n  image:"):workflow.index("\n  catalog:")]
        steps = re.findall(r"^      - (?:name: (.+)|uses: (\S+))$", image_job, re.M)
        names = [name or uses for name, uses in steps]
        compare = next(i for i, n in enumerate(names) if n.startswith("Maven Central - "))
        build = next(i for i, n in enumerate(names) if n.startswith("Build"))
        shipped = next(i for i, n in enumerate(names) if n.startswith("The image ships the jars compared"))
        push = names.index("Push")
        self.assertLess(compare, build)
        self.assertLess(build, shipped)
        self.assertLess(shipped, push)
        self.assertIn("scripts/maven_central.py --server", image_job)
        self.assertIn('--image "local/sandbox-ai-mcp-${SERVER}:ci"', image_job)


if __name__ == "__main__":
    unittest.main()
