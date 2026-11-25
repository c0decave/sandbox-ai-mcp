"""scripts/maven_central.py: every jar a server ships is byte for byte the published one in its Maven repository (CI)."""

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
GOOGLE = "https://dl.google.com/dl/android/maven2"


def jar(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


LIB = jar({"META-INF/MANIFEST.MF": b"Manifest-Version: 1.0\n", "org/example/lib/A.class": b"\xca\xfe\xba\xbeA"})
CORE = jar({"META-INF/MANIFEST.MF": b"Manifest-Version: 1.0\n", "org/example/core/C.class": b"\xca\xfe\xba\xbeC"})
ASSET_URL = "https://github.com/example/core/releases/download/1.0/core-1.0.jar"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Server:
    """A server folder with a Dockerfile and a maven-central.json, and a fake Maven repository: lib is shipped from
    the repository itself, core as a GitHub release asset (as cfr's jar is)."""

    def __init__(self, folder: Path, lib_pin: str | None = None, core_pin: str | None = None,
                 repository: str | None = None, asset: bytes = CORE):
        self.folder = folder
        self.repo = repository or REPO
        self.lib_url = f"{self.repo}/org/example/lib/1.0/lib-1.0.jar"
        self.core_url = f"{self.repo}/org/example/core/1.0/core-1.0.jar"
        (folder / "Dockerfile").write_text(
            "FROM scratch\n"
            f"ARG LIB_URL={self.lib_url}\n"
            f"ARG LIB_SHA256={lib_pin or sha256(LIB)}\n"
            f"ARG CORE_URL={ASSET_URL}\n"
            f"ARG CORE_SHA256={core_pin or sha256(CORE)}\n"
            "ADD --checksum=sha256:${LIB_SHA256} ${LIB_URL} /opt/lib/lib-1.0.jar\n"
            "ADD --checksum=sha256:${CORE_SHA256} ${CORE_URL} /opt/lib/core-1.0.jar\n")
        self.write_spec([
            {"coordinate": "org.example:lib:1.0", "url_arg": "LIB_URL", "sha256_arg": "LIB_SHA256",
             "image_path": "/opt/lib/lib-1.0.jar"},
            {"coordinate": "org.example:core:1.0", "url_arg": "CORE_URL", "sha256_arg": "CORE_SHA256",
             "image_path": "/opt/lib/core-1.0.jar"}], repository)
        self.files: dict[str, bytes] = {ASSET_URL: asset}
        self.publish(self.lib_url, LIB)
        self.publish(self.core_url, CORE)
        self.asked: list[str] = []

    def write_spec(self, jars: list[dict], repository: str | None = None, version: int = 2):
        (self.folder / "maven-central.json").write_text(json.dumps({
            "schema": "sandbox-ai-mcp-maven-central", "version": version, "jars": jars,
            **({"repository": repository} if repository else {})}))

    def publish(self, url: str, data: bytes, sha1: str | None = None, sha256_text: str | None = None):
        self.files[url] = data
        self.files[url + ".sha1"] = (sha1 or hashlib.sha1(data).hexdigest()).encode()
        self.files[url + ".sha256"] = (sha256_text or sha256(data)).encode()

    def get(self, url: str) -> bytes | None:
        self.asked.append(url)
        return self.files.get(url)


class Compare(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name) / "lib"
        self.folder.mkdir()

    def check(self, server: Server) -> dict:
        return maven_central.check(self.folder, server.get)

    def test_jars_that_are_the_published_ones_pass_and_say_which_checksums_were_checked(self):
        server = Server(self.folder)
        report = self.check(server)
        self.assertTrue(report["passed"], report)
        lib, core = report["jars"]
        self.assertEqual((lib["coordinate"], lib["jar"], lib["sha256"]), ("org.example:lib:1.0", "lib-1.0.jar",
                                                                          sha256(LIB)))
        self.assertEqual(sorted(lib["checksums"]), ["sha1", "sha256"])
        self.assertEqual(lib["checksums"]["sha1"], hashlib.sha1(LIB).hexdigest())
        self.assertEqual(lib["shipped_from"], "the repository")
        self.assertEqual(core["shipped_from"], ASSET_URL)
        self.assertIn("byte for byte", lib["compared"])
        self.assertIn(server.lib_url + ".sha256", server.asked)
        summary = "\n".join(maven_central._summary(report))
        self.assertIn("org.example:lib:1.0", summary)
        self.assertIn("sha1, sha256", summary)

    def test_a_pin_that_is_not_the_published_jar_fails(self):
        report = self.check(Server(self.folder, lib_pin="0" * 64))
        self.assertFalse(report["passed"])
        lib = report["jars"][0]
        self.assertFalse(lib["passed"])
        self.assertEqual(lib["repository_sha256"], sha256(LIB))
        self.assertIn("0" * 64, "\n".join(maven_central._summary(report)))

    def test_a_release_asset_that_differs_from_the_published_jar_fails(self):
        # cfr's case: the image takes the GitHub asset; it must be the very bytes Maven Central publishes
        other = jar({"org/example/core/C.class": b"\xca\xfe\xba\xbeX"})
        report = self.check(Server(self.folder, core_pin=sha256(other), asset=other))
        self.assertFalse(report["passed"])
        self.assertFalse(report["jars"][1]["passed"])
        self.assertTrue(report["jars"][0]["passed"])

    def test_a_release_asset_that_is_not_the_pinned_one_fails(self):
        server = Server(self.folder)
        server.files[ASSET_URL] = b"something else"
        with self.assertRaisesRegex(maven_central.Problem, "the Dockerfile pins"):
            self.check(server)

    def test_every_published_checksum_is_checked(self):
        for kind in ("sha1", "sha256", "sha512"):
            with self.subTest(kind=kind):
                server = Server(self.folder)
                server.files[f"{server.core_url}.{kind}"] = ("1" * {"sha1": 40, "sha256": 64, "sha512": 128}[kind]).encode()
                with self.assertRaisesRegex(maven_central.Problem, kind):
                    self.check(server)

    def test_a_checksum_file_without_a_checksum_fails(self):
        server = Server(self.folder)
        server.files[server.lib_url + ".sha1"] = b"<html>not found</html>"
        with self.assertRaisesRegex(maven_central.Problem, "holds no sha1"):
            self.check(server)

    def test_a_missing_checksum_file_is_said_and_one_is_enough(self):
        server = Server(self.folder)
        del server.files[server.lib_url + ".sha256"]
        report = self.check(server)
        self.assertTrue(report["passed"])
        self.assertEqual(sorted(report["jars"][0]["checksums"]), ["sha1"])
        self.assertTrue(any("no .sha256" in note for note in report["notes"]))

    def test_a_jar_without_any_published_checksum_fails(self):
        server = Server(self.folder)
        del server.files[server.lib_url + ".sha256"], server.files[server.lib_url + ".sha1"]
        with self.assertRaisesRegex(maven_central.Problem, "publishes no checksum"):
            self.check(server)

    def test_googles_maven_repository_per_jar(self):
        # smali 3.0.10 is on Google's Maven (maven.google.com), not on Maven Central (CI, 2026-11-21); its
        # dependencies are on Maven Central: each jar names its repository
        server = Server(self.folder)
        google_lib = f"{GOOGLE}/org/example/lib/1.0/lib-1.0.jar"
        server.publish(google_lib, LIB)
        text = (self.folder / "Dockerfile").read_text().replace(server.lib_url, google_lib)
        (self.folder / "Dockerfile").write_text(text)
        server.write_spec([
            {"coordinate": "org.example:lib:1.0", "url_arg": "LIB_URL", "sha256_arg": "LIB_SHA256",
             "image_path": "/opt/lib/lib-1.0.jar", "repository": GOOGLE},
            {"coordinate": "org.example:core:1.0", "url_arg": "CORE_URL", "sha256_arg": "CORE_SHA256",
             "image_path": "/opt/lib/core-1.0.jar"}])
        report = self.check(server)
        self.assertTrue(report["passed"], report)
        self.assertEqual(report["jars"][0]["repository"], GOOGLE)
        self.assertEqual(report["jars"][1]["repository"], REPO)
        self.assertIn(google_lib + ".sha1", server.asked)
        self.assertNotIn(server.lib_url, server.asked)

    def test_another_repository_is_refused(self):
        Server(self.folder, repository="https://maven.example.org/releases")
        with self.assertRaisesRegex(maven_central.Problem, "repository"):
            maven_central.load_spec(self.folder)

    def test_a_repository_url_of_another_artifact_is_refused(self):
        server = Server(self.folder)
        text = (self.folder / "Dockerfile").read_text().replace(server.lib_url, server.core_url)
        (self.folder / "Dockerfile").write_text(text)
        with self.assertRaisesRegex(maven_central.Problem, "is not the jar of org.example:lib:1.0"):
            maven_central.load_spec(self.folder)

    def test_a_url_off_github_and_off_the_repository_is_refused(self):
        Server(self.folder)
        text = (self.folder / "Dockerfile").read_text().replace("https://github.com/", "http://example.org/")
        (self.folder / "Dockerfile").write_text(text)
        with self.assertRaisesRegex(maven_central.Problem, "https URL"):
            maven_central.load_spec(self.folder)

    def test_the_fat_jar_schema_is_refused(self):
        server = Server(self.folder)
        server.write_spec([{"url_arg": "LIB_URL", "sha256_arg": "LIB_SHA256", "image_path": "/opt/lib/lib-1.0.jar",
                            "built_from": ["org.example:lib:1.0"], "own_prefixes": ["org/example/"]}], version=1)
        with self.assertRaisesRegex(maven_central.Problem, '"version": 2'):
            maven_central.load_spec(self.folder)
        server.write_spec([{"url_arg": "LIB_URL", "sha256_arg": "LIB_SHA256", "image_path": "/opt/lib/lib-1.0.jar",
                            "built_from": ["org.example:lib:1.0"]}])
        with self.assertRaisesRegex(maven_central.Problem, "coordinate"):
            maven_central.load_spec(self.folder)

    def test_a_jar_named_twice_is_refused(self):
        server = Server(self.folder)
        entry = {"coordinate": "org.example:lib:1.0", "url_arg": "LIB_URL", "sha256_arg": "LIB_SHA256",
                 "image_path": "/opt/lib/lib-1.0.jar"}
        server.write_spec([entry, dict(entry)])
        with self.assertRaisesRegex(maven_central.Problem, "twice"):
            maven_central.load_spec(self.folder)

    def test_an_artifact_not_in_the_repository_fails(self):
        server = Server(self.folder)
        del server.files[server.core_url]
        with self.assertRaisesRegex(maven_central.Problem, f"not in {REPO}"):
            self.check(server)

    def test_only_the_dockerfile_urls_and_the_repository_are_fetched(self):
        server = Server(self.folder)
        self.check(server)
        for url in server.asked:
            self.assertTrue(url.startswith((REPO + "/", ASSET_URL)), url)
        self.assertEqual(server.asked.count(server.lib_url), 1, "a jar shipped from the repository is fetched once")

    def test_a_server_without_a_spec_has_nothing_to_do(self):
        report = maven_central.check(self.folder, lambda url: self.fail(f"fetched {url}"))
        self.assertTrue(report["passed"])
        self.assertEqual(report["jars"], [])


class Image(unittest.TestCase):
    """--image: the built image's folders of jars hold exactly the compared jars, each with its pinned SHA-256."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name) / "lib"
        self.folder.mkdir()
        Server(self.folder)

    def engine(self, listing: str) -> str:
        """A stand-in for docker: prints LISTING (sha256sum's output) and the arguments it got to a file."""
        script = Path(self.tmp.name) / "engine"
        (Path(self.tmp.name) / "listing").write_text(listing)
        script.write_text(f"#!/bin/sh\necho \"$@\" > {self.tmp.name}/arguments\ncat {self.tmp.name}/listing\n")
        script.chmod(0o755)
        return str(script)

    def test_exactly_the_compared_jars_pass(self):
        engine = self.engine(f"{sha256(LIB)}  /opt/lib/lib-1.0.jar\n{sha256(CORE)}  /opt/lib/core-1.0.jar\n")
        self.assertEqual(maven_central.check_image(self.folder, "img", engine), [])
        arguments = (Path(self.tmp.name) / "arguments").read_text().split()
        self.assertIn("--network=none", arguments)
        self.assertEqual(arguments[arguments.index("img") + 1:], ["/opt/lib", "!", "-type", "d", "-exec",
                                                                  "sha256sum", "{}", "+"])

    def test_a_changed_missing_or_extra_jar_fails(self):
        for listing, expected in (
                (f"{'0' * 64}  /opt/lib/lib-1.0.jar\n{sha256(CORE)}  /opt/lib/core-1.0.jar\n", "lib-1.0.jar in the image"),
                (f"{sha256(CORE)}  /opt/lib/core-1.0.jar\n", "missing"),
                (f"{sha256(LIB)}  /opt/lib/lib-1.0.jar\n{sha256(CORE)}  /opt/lib/core-1.0.jar\n"
                 f"{sha256(b'x')}  /opt/lib/extra.jar\n", "/opt/lib/extra.jar")):
            with self.subTest(expected=expected):
                problems = maven_central.check_image(self.folder, "img", self.engine(listing))
                self.assertTrue(any(expected in problem for problem in problems), problems)


class TheServers(unittest.TestCase):
    """smali's jars (Google's own, with their dependencies) and cfr's release jar are checked against their Maven
    repository before their images are built."""

    SMALI = "com.android.tools.smali"
    #: Google's four jars and exactly the runtime dependencies their POMs name (compile and runtime scope,
    #: transitively, nearest wins), resolved from the POMs on 2026-11-22.
    GOOGLE_JARS = [f"{SMALI}:smali:3.0.10", f"{SMALI}:smali-baksmali:3.0.10", f"{SMALI}:smali-dexlib2:3.0.10",
                   f"{SMALI}:smali-util:3.0.10"]
    CENTRAL_JARS = ["com.google.guava:guava:31.1-android", "com.google.guava:failureaccess:1.0.1",
                    "com.google.guava:listenablefuture:9999.0-empty-to-avoid-conflict-with-guava",
                    "com.google.code.findbugs:jsr305:3.0.2", "org.checkerframework:checker-qual:3.12.0",
                    "com.google.errorprone:error_prone_annotations:2.11.0", "com.google.j2objc:j2objc-annotations:1.3",
                    "org.jcommander:jcommander:1.85", "org.antlr:antlr:3.5.2", "org.antlr:antlr-runtime:3.5.2",
                    "org.antlr:ST4:4.0.8", "org.antlr:stringtemplate:3.2.1", "antlr:antlr:2.7.7"]

    def spec(self, name):
        return maven_central.load_spec(ROOT / "servers" / name)

    def test_smali_ships_googles_jars_and_their_dependencies_from_the_repositories_themselves(self):
        jars = self.spec("smali")["jars"]
        self.assertEqual(sorted(j["coordinate"] for j in jars), sorted(self.GOOGLE_JARS + self.CENTRAL_JARS))
        for entry in jars:
            with self.subTest(jar=entry["coordinate"]):
                expected = GOOGLE if entry["coordinate"].startswith(self.SMALI + ":") else REPO
                self.assertEqual(entry["repository"], expected)
                self.assertEqual(entry["url"], maven_central.maven_url(entry["coordinate"], expected))
                _, artifact, version = entry["coordinate"].split(":")
                self.assertEqual(entry["image_path"], f"/opt/smali/{artifact}-{version}.jar")
        self.assertFalse([j for j in jars if "fat" in j["url"] or "github.com" in j["url"]])

    def test_cfr_names_org_benf_cfr_0_152(self):
        (entry,) = self.spec("cfr")["jars"]
        self.assertEqual(entry["coordinate"], "org.benf:cfr:0.152")
        self.assertEqual(entry["repository"], REPO)
        self.assertEqual(entry["image_path"], "/opt/cfr/cfr-0.152.jar")
        self.assertTrue(entry["url"].startswith("https://github.com/leibnitz27/cfr/releases/download/0.152/"))

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

    def test_every_jar_smali_adds_is_in_the_spec(self):
        dockerfile = (ROOT / "servers" / "smali" / "Dockerfile").read_text()
        args = {jar["url_arg"] for jar in json.loads((ROOT / "servers/smali/maven-central.json").read_text())["jars"]}
        added = re.findall(r"(?m)^ADD --checksum=sha256:\$\{[A-Z0-9_]+\} \$\{([A-Z0-9_]+)\} (\S+)$", dockerfile)
        smali_jars = {arg for arg, target in added if target.startswith("/build/smali/")}
        self.assertEqual(smali_jars, args)
        self.assertEqual(len(args), 17)

    def test_every_variable_of_a_smoke_spec_is_passed_by_every_smoke_step(self):
        # agentql's and shodan's smoke steps died on "the spec uses ${AGENTQL_API_KEY}: pass --var" (CI, 2026-11-21):
        # a key a repository secret may hold is passed, empty without the secret, like BRAVE_API_KEY
        workflow = (ROOT / ".github/workflows/build.yml").read_text()
        used = set()
        for spec in (ROOT / "servers").glob("*/smoke.json"):
            used |= set(re.findall(r"\$\{([A-Z0-9_]+)\}", spec.read_text()))
        steps = [chunk for chunk in workflow.split("\n      - ") if "scripts/smoke_test.py" in chunk
                 and "--list-only" not in chunk]
        self.assertEqual(len(steps), 4, "docker, sandbox-ai under Podman, without the host's init, under Bubblewrap")
        for step in steps:
            for name in sorted(used):
                with self.subTest(step=step.split("\n", 1)[0], variable=name):
                    if name == "FIXTURES":
                        self.assertIn('--var "FIXTURES=${GITHUB_WORKSPACE}/tests/fixtures"', step)
                    else:
                        self.assertIn(f'--var "{name}=${{{name}}}"', step)
                        self.assertIn(f"{name}: ${{{{ secrets.{name} }}}}", step)

    def test_the_workflow_compares_before_the_build_and_checks_the_built_image(self):
        workflow = (ROOT / ".github/workflows/build.yml").read_text()
        image_job = workflow[workflow.index("\n  image:"):workflow.index("\n  catalog:")]
        steps = re.findall(r"^      - (?:name: (.+)|uses: (\S+))$", image_job, re.M)
        names = [name or uses for name, uses in steps]
        compare = next(i for i, n in enumerate(names) if n.startswith("Maven repository - "))
        build = next(i for i, n in enumerate(names) if n.startswith("Build"))
        shipped = next(i for i, n in enumerate(names) if n.startswith("The image ships the jars compared"))
        push = names.index("Push")
        self.assertLess(compare, build)
        self.assertLess(build, shipped)
        self.assertLess(shipped, push)
        self.assertIn("scripts/maven_central.py --server", image_job)
        self.assertIn('--image "local/sandbox-ai-mcp-${SERVER}:ci"', image_job)
        self.assertNotIn("fat jar", image_job)


if __name__ == "__main__":
    unittest.main()
