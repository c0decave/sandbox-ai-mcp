"""scripts/sign_catalog.py and scripts/rootfs.py: a catalog is signed only when every published server passed its
smoke tests with sandbox-ai under Podman and Bubblewrap, for exactly the digest and rootfs it pins; the signature
verifies (and sandbox-ai's own check, when SANDBOX_AI_CHECKOUT names a checkout, takes it, fetched from the very
URL sandbox-ai reads the catalog from)."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sign = load("sign_catalog")
rootfs = load("rootfs")
DIGEST = "sha256:" + "ab" * 32
SHA = "cd" * 32
IMAGE = f"ghcr.io/c0decave/sandbox-ai-mcp-duckduckgo@{DIGEST}"
# Where sandbox-ai reads this catalog (sandbox/mcp.py CATALOGS): the files at the top of branch main.
RAW = "https://raw.githubusercontent.com/c0decave/sandbox-ai-mcp/main/"


def load_sandbox_ai():
    checkout = Path(os.environ["SANDBOX_AI_CHECKOUT"])
    spec = importlib.util.spec_from_file_location("sandbox_ai_mcp", checkout / "sandbox/mcp.py")
    mcp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mcp)
    return mcp


@unittest.skipIf(not shutil.which("ssh-keygen"), "needs ssh-keygen")
class SignCatalog(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "hub"
        shutil.copytree(ROOT, self.root, ignore=shutil.ignore_patterns(
            ".git", "__pycache__", "candidates", "sandbox-ai"))  # CI checks sandbox-ai out beside us
        digests = json.loads((self.root / "digests.json").read_text())
        # Only duckduckgo is published here, whatever the real digests.json pins.
        digests["images"] = {name: None for name in digests["images"]}
        digests["images"]["duckduckgo"] = DIGEST
        for stale in self.root.glob("*.sig"):
            stale.unlink()
        digests["rootfs"] = {"duckduckgo": {
            "name": "duckduckgo", "image": IMAGE,
            "url": "https://github.com/c0decave/sandbox-ai-mcp/releases/download/rootfs-duckduckgo-cdcd/"
                   "rootfs-duckduckgo.tar.gz", "sha256": SHA, "size": 10,
            "entrypoint": ["/opt/venv/bin/python", "-I", "-u", "/opt/mcp/server.py"], "user": 10001,
            "workdir": "/tmp", "env": {"HOME": "/tmp"}}}
        (self.root / "digests.json").write_text(json.dumps(digests, indent=2) + "\n")
        made = subprocess.run([sys.executable, str(self.root / "scripts/make_catalog.py"), "--root", str(self.root)],
                              capture_output=True, text=True)
        self.assertEqual(made.returncode, 0, made.stderr)
        self.key = self.tmp / "key"
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "test", "-f", str(self.key)], check=True)
        kind, key = (self.tmp / "key.pub").read_text().split()[:2]
        self.signers = self.tmp / "mcp-signers"
        # As sandbox/mcp-signers is written: comments, and a comment after the key.
        self.signers.write_text("# Keys that sign the catalog of sandbox-ai-mcp\n#\n"
                                f'mcp@sandbox-ai namespaces="sandbox-ai-mcp" {kind} {key} sandbox-ai-mcp\n')
        self.reports = self.tmp / "reports"
        self.reports.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def report(self, runner, folder=None, **changes):
        """A report as scripts/smoke_test.py --report writes it."""
        report = {"name": "duckduckgo", "image": IMAGE, "network": "full", "runner": runner, "ok": True,
                  "checks": [{"check": "tools/list", "ok": True}, {"check": "tools.json", "ok": True},
                             {"check": "tools/call web_search", "ok": True}]}
        if runner.endswith("bwrap"):
            report["rootfs_sha256"] = SHA
        report.update(changes)
        folder = folder or self.reports
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"smoke-duckduckgo-{runner}.json").write_text(json.dumps(report))

    def run_sign(self):
        return sign.main(["--root", str(self.root), "--key", str(self.key), "--reports", str(self.reports)])

    def test_nothing_is_signed_without_both_passed_reports(self):
        self.assertEqual(self.run_sign(), 1)
        self.report("sandbox-ai-podman")
        self.assertEqual(self.run_sign(), 1, "the Bubblewrap report is missing")
        self.report("sandbox-ai-bwrap", ok=False, checks=[{"check": "tools/call web_search", "ok": False}])
        self.assertEqual(self.run_sign(), 1)
        self.report("sandbox-ai-bwrap", rootfs_sha256="ef" * 32)
        self.assertEqual(self.run_sign(), 1, "a report of another rootfs")
        self.report("sandbox-ai-bwrap")
        self.report("sandbox-ai-podman", image="ghcr.io/c0decave/sandbox-ai-mcp-duckduckgo@sha256:" + "00" * 32)
        self.assertEqual(self.run_sign(), 1, "a report of another image")
        self.report("sandbox-ai-podman")
        self.report("sandbox-ai-bwrap", image="ghcr.io/c0decave/sandbox-ai-mcp-duckduckgo@sha256:" + "00" * 32)
        self.assertEqual(self.run_sign(), 1, "a Bubblewrap report of another image")
        self.report("sandbox-ai-bwrap")
        bwrap = self.reports / "smoke-duckduckgo-sandbox-ai-bwrap.json"
        (self.reports / "smoke-duckduckgo-sandbox-ai-podman.json").write_bytes(bwrap.read_bytes())
        self.assertEqual(self.run_sign(), 1, "the report of the other runner under the podman name")
        self.report("sandbox-ai-podman", checks=[{"check": "tools/list", "ok": True}])
        self.assertEqual(self.run_sign(), 1, "tools.json was not compared")
        self.report("sandbox-ai-podman", checks=[{"check": "tools/list", "ok": True},
                                                 {"check": "tools.json", "ok": True}])
        self.assertEqual(self.run_sign(), 1, "no tool call was made")
        self.assertFalse((self.root / "catalog.json.sig").exists())
        self.assertFalse((self.root / "rootfs.json.sig").exists())

    def test_a_server_without_rootfs_is_signed_for_podman_alone(self):
        """A server whose Bubblewrap smoke test failed is published without a rootfs: its Podman report is enough,
        and rootfs.json vouches for no Bubblewrap form of it."""
        digests = json.loads((self.root / "digests.json").read_text())
        digests["rootfs"] = {}
        (self.root / "digests.json").write_text(json.dumps(digests, indent=2) + "\n")
        made = subprocess.run([sys.executable, str(self.root / "scripts/make_catalog.py"), "--root", str(self.root)],
                              capture_output=True, text=True)
        self.assertEqual(made.returncode, 0, made.stderr)
        self.assertEqual(self.run_sign(), 1, "no Podman report yet")
        self.report("sandbox-ai-bwrap", ok=False, checks=[{"check": "tools/call web_search", "ok": False}])
        self.report("sandbox-ai-podman")
        self.assertEqual(self.run_sign(), 0, "a failed Bubblewrap report does not matter without a rootfs")
        rootfs = json.loads((self.root / "rootfs.json").read_text())
        self.assertNotIn("duckduckgo", rootfs.get("rootfs", {}))

    def test_no_signature_with_more_network_than_the_entry_declares(self):
        """duckduckgo is an allowlist entry: a run with the full network is what sandbox-ai gives it (it
        has no egress proxy), so that report is taken; a server with network none is never vouched for
        with any network."""
        self.report("sandbox-ai-podman")
        self.report("sandbox-ai-bwrap")
        self.assertEqual(self.run_sign(), 0)
        (self.root / "catalog.json.sig").unlink()
        catalog = json.loads((self.root / "catalog.json").read_text())
        for entry in catalog["entries"]:
            if entry["name"] == "duckduckgo":
                entry["network"] = "none"
                entry.pop("hosts", None)
        (self.root / "catalog.json").write_text(json.dumps(catalog, indent=2) + "\n")
        problems = sign.problems_of(self.root, self.reports)
        self.assertTrue(any("more network than it declares" in p for p in problems), problems)

    def test_no_signature_for_a_rootfs_the_catalog_does_not_publish(self):
        self.report("sandbox-ai-podman")
        self.report("sandbox-ai-bwrap")
        document = json.loads((self.root / "rootfs.json").read_text())
        document["rootfs"]["web-fetch"] = dict(document["rootfs"]["duckduckgo"])
        (self.root / "rootfs.json").write_text(json.dumps(document, indent=2) + "\n")
        problems = sign.problems_of(self.root, self.reports)
        self.assertTrue(any("web-fetch" in p and "does not" in p for p in problems), problems)
        self.assertEqual(self.run_sign(), 1)

    def test_no_reports_folder_no_signature(self):
        self.assertEqual(sign.main(["--root", str(self.root), "--key", str(self.key),
                                    "--reports", str(self.tmp / "nothing")]), 1)
        self.assertFalse((self.root / "catalog.json.sig").exists())

    def test_the_catalog_artifact_as_downloaded(self):
        """gh run download RUN -n catalog -D DIR: the reports are in DIR/ci-digests; --reports DIR finds them."""
        nested = self.reports / "ci-digests"
        self.report("sandbox-ai-podman", folder=nested)
        self.report("sandbox-ai-bwrap", folder=nested)
        self.assertEqual(self.run_sign(), 0)
        self.report("sandbox-ai-bwrap", folder=self.reports / "another-run")
        (self.root / "catalog.json.sig").unlink()
        self.assertEqual(self.run_sign(), 1, "two reports of one server: which run is it?")

    def test_signed_and_verified(self):
        self.report("sandbox-ai-podman")
        self.report("sandbox-ai-bwrap")
        self.assertEqual(self.run_sign(), 0)
        self.assertEqual(sign.main(["--root", str(self.root), "--verify", "--signers", str(self.signers)]), 0)
        (self.root / "rootfs.json").write_text((self.root / "rootfs.json").read_text().replace(SHA, "ef" * 32))
        self.assertEqual(sign.main(["--root", str(self.root), "--verify", "--signers", str(self.signers)]), 1)

    def test_a_stale_catalog_is_not_signed(self):
        self.report("sandbox-ai-podman")
        self.report("sandbox-ai-bwrap")
        catalog = self.root / "catalog.json"
        catalog.write_text(catalog.read_text().replace("DuckDuckGo search", "Something else"))
        self.assertEqual(self.run_sign(), 1)

    @unittest.skipUnless(os.environ.get("SANDBOX_AI_CHECKOUT"), "SANDBOX_AI_CHECKOUT names a sandbox-ai checkout")
    def test_sandbox_ai_takes_the_signature(self):
        self.report("sandbox-ai-podman")
        self.report("sandbox-ai-bwrap")
        self.assertEqual(self.run_sign(), 0)
        mcp = load_sandbox_ai()
        keys = mcp.release_keys()
        trusted = keys.parse(self.signers.read_text(), "test", keys.MCP)
        source = str(self.root / "catalog.json")
        verdict = mcp.catalog_signature(source, Path(source).read_bytes(), keys=trusted)
        self.assertEqual(verdict["state"], "good", verdict)
        keys.MCP["signers"] = self.signers
        (entry,) = [e for _, e in mcp.catalog_entries([("mcp", source)])[0] if e["name"] == "duckduckgo"]
        self.assertEqual(entry["_signature"]["state"], "good")
        self.assertEqual(entry["rootfs"]["sha256"], SHA, "rootfs.json, signed like the catalog, is taken")


    @unittest.skipUnless(os.environ.get("SANDBOX_AI_CHECKOUT"), "SANDBOX_AI_CHECKOUT names a sandbox-ai checkout")
    def test_sandbox_ai_reads_it_where_it_is_published(self):
        """sandbox-ai fetches catalog.json, catalog.json.sig, rootfs.json and rootfs.json.sig from main of
        github.com/c0decave/sandbox-ai-mcp: the files sign_catalog.py writes at the top of the repository."""
        self.report("sandbox-ai-podman")
        self.report("sandbox-ai-bwrap")
        self.assertEqual(self.run_sign(), 0)
        mcp = load_sandbox_ai()
        self.assertIn(("mcp", RAW + "catalog.json"), mcp.CATALOGS)
        fetched = []

        def fetch(url):  # the repository's main branch as raw.githubusercontent.com serves it
            self.assertTrue(url.startswith(RAW), url)
            fetched.append(url[len(RAW):])
            return (self.root / url[len(RAW):]).read_bytes()

        keys = mcp.release_keys()
        keys.MCP["signers"] = self.signers
        found, problems = mcp.catalog_entries([("mcp", RAW + "catalog.json")], fetch=fetch)
        self.assertEqual(problems, [])
        self.assertEqual(fetched, ["catalog.json", "catalog.json.sig", "rootfs.json", "rootfs.json.sig"])
        (entry,) = [e for _, e in found if e["name"] == "duckduckgo"]
        self.assertEqual(entry["_signature"]["state"], "good")
        self.assertEqual(entry["rootfs"]["sha256"], SHA)
        self.assertTrue(entry["rootfs"]["url"].startswith("https://github.com/c0decave/sandbox-ai-mcp/releases/"))
        self.assertEqual(mcp.check_signature(entry)["signed_by"], entry["_signature"]["signer"])
        # The real mcp-signers do not trust a throwaway key: the same files are refused as BAD there.
        keys.MCP["signers"] = Path(os.environ["SANDBOX_AI_CHECKOUT"]) / "sandbox/mcp-signers"
        (entry,) = [e for _, e in mcp.catalog_entries([("mcp", RAW + "catalog.json")], fetch=fetch)[0]
                    if e["name"] == "duckduckgo"]
        self.assertEqual(entry["_signature"]["state"], "bad")
        with self.assertRaises(ValueError):
            mcp.check_signature(entry)


class WorkflowMakesTheReports(unittest.TestCase):
    """.github/workflows/build.yml builds every server and writes and uploads the reports sign_catalog.py wants."""

    def test_every_server_and_both_reports(self):
        import re
        workflow = (ROOT / ".github/workflows/build.yml").read_text()
        matrix = re.search(r"^\s*server: \[([^\]]*)\]", workflow, re.M)
        self.assertIsNotNone(matrix)
        built = sorted(name.strip() for name in matrix[1].replace("\n", " ").split(",") if name.strip())
        self.assertEqual(built, sorted(p.parent.name for p in (ROOT / "servers").glob("*/server.json")))
        for runner in sign.RUNNERS:
            report = f"smoke-${{{{ matrix.server }}}}-{runner}.json"
            self.assertIn(f"--runner {runner} ", workflow)
            self.assertEqual(workflow.count(report), 2, f"{report}: written once and uploaded once")
        self.assertIn("ci-digests/**/smoke-*.json", workflow, "the catalog artifact carries the reports")
        self.assertIn("rootfs.json", workflow)


class RootfsFacts(unittest.TestCase):
    def test_what_runs_it(self):
        facts = rootfs.run_facts({"Entrypoint": ["/opt/venv/bin/python", "-I"], "Cmd": ["/opt/mcp/server.py"],
                                  "User": "10001:10001", "WorkingDir": "/tmp", "Env": ["HOME=/tmp", "PATH=/usr/bin",
                                                                                      "bad name=x"]})
        self.assertEqual(facts, {"entrypoint": ["/opt/venv/bin/python", "-I", "/opt/mcp/server.py"], "user": 10001,
                                 "workdir": "/tmp", "env": {"HOME": "/tmp", "PATH": "/usr/bin"}})
        for config in ({"Entrypoint": ["python3"], "User": "10001"}, {"Entrypoint": ["/x"], "User": "root"},
                       {"Entrypoint": ["/x"], "User": "0"}, {"Entrypoint": [], "User": "1"}):
            with self.assertRaises(ValueError):
                rootfs.run_facts(config)


class SmokeAnnotation(unittest.TestCase):
    """A failed smoke run says why in an error annotation (job logs are not always readable)."""

    def test_the_annotation_names_the_reason_on_one_escaped_line(self):
        smoke = load("smoke_test")
        line = smoke.annotation({"name": "telegram", "runner": "sandbox-ai-bwrap", "image": "i@sha256:1",
                                 "exception": "RuntimeError: 50% gone", "stderr_tail": "a\nb",
                                 "checks": [{"check": "tools/list", "ok": False, "missing": ["send"]},
                                            {"check": "tools/call x", "ok": True}]})
        self.assertTrue(line.startswith("::error title=smoke telegram (sandbox-ai-bwrap)::"))
        self.assertEqual(line.count("\n"), 0)
        for part in ("RuntimeError: 50%25 gone", "failed: tools/list", "send", "stderr: a%0Ab"):
            self.assertIn(part, line)
        self.assertNotIn("tools/call x", line)


@unittest.skipUnless(os.environ.get("SANDBOX_AI_CHECKOUT"), "SANDBOX_AI_CHECKOUT names a sandbox-ai checkout")
class SmokeWithSandboxAi(unittest.TestCase):
    """smoke_test.py's sandbox-ai runners start a server with sandbox-ai's own run lines."""

    def test_the_podman_runner_keeps_podmans_image_store(self):
        """Rootless podman keeps its images below XDG_DATA_HOME: the Podman runner must not point it at a fresh
        folder, or the image the workflow pulled is "not known" there."""
        smoke = load("smoke_test")
        before = os.environ.pop("XDG_DATA_HOME", None)
        try:
            image = f"ghcr.io/c0decave/sandbox-ai-mcp-duckduckgo@{DIGEST}"
            _, env, _ = smoke.sandbox_ai_argv("sandbox-ai-podman", os.environ["SANDBOX_AI_CHECKOUT"], image,
                                              "allowlist", [], {})
            self.assertNotIn("XDG_DATA_HOME", os.environ)
            self.assertNotIn("XDG_DATA_HOME", env)
        finally:
            if before is not None:
                os.environ["XDG_DATA_HOME"] = before

    def test_the_run_lines_are_sandbox_ais(self):
        import hashlib
        import io
        import tarfile
        import tempfile
        smoke = load("smoke_test")
        checkout = os.environ["SANDBOX_AI_CHECKOUT"]
        tmp = Path(tempfile.mkdtemp())
        os.environ["XDG_DATA_HOME"] = str(tmp / "data")
        image = f"ghcr.io/c0decave/sandbox-ai-mcp-duckduckgo@{DIGEST}"
        argv, env, facts = smoke.sandbox_ai_argv("sandbox-ai-podman", checkout, image, "allowlist", [], {"K": "v"})
        self.assertEqual(argv[:2], ["podman", "run"])
        for flag in ("--cap-drop=ALL", "--read-only", "--security-opt=no-new-privileges", "--env=K"):
            self.assertIn(flag, argv)
        self.assertEqual(argv[-1], image)
        self.assertEqual(env["K"], "v")
        self.assertNotIn("v", argv, "the value comes from the environment")
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
            info = tarfile.TarInfo("server")
            info.size, info.mode = 3, 0o755
            tar.addfile(info, io.BytesIO(b"#!x"))
        archive = tmp / "rootfs.tar.gz"
        archive.write_bytes(buffer.getvalue())
        meta = {"sha256": hashlib.sha256(buffer.getvalue()).hexdigest(), "entrypoint": ["/server"], "user": 10001,
                "workdir": "/tmp", "env": {"HOME": "/tmp"}}
        argv, env, facts = smoke.sandbox_ai_argv("sandbox-ai-bwrap", checkout, image, "none", [], {}, str(archive),
                                                 meta)
        self.assertEqual(argv[-2], "--internal-bwrap")
        self.assertTrue(argv[-3].endswith("sandbox/mcp_rootfs.py"))
        self.assertEqual(facts, {"rootfs_sha256": meta["sha256"]})
        definition = json.loads(Path(argv[-1]).read_text())
        self.assertTrue(Path(definition["rootfs"]["path"], "server").is_file())
        meta["sha256"] = "00" * 32
        with self.assertRaises(ValueError):
            smoke.sandbox_ai_argv("sandbox-ai-bwrap", checkout, image, "none", [], {}, str(archive), meta)


if __name__ == "__main__":
    unittest.main()
