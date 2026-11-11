"""scripts/smoke_test.py, ci_results.py and make_catalog.py --only: what the build workflow needs so that one server's
failure, or an upstream service's rate limit, does not keep the others out of the catalog.

smoke_test.py runs against a stand-in container engine (its run line, the environment through --env-file=/dev/fd/N)
that starts a small stdlib MCP server, or a real server of this repository when its requirements are installed."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


smoke = load("smoke_test")
sign = load("sign_catalog")
ci_results = load("ci_results")

# A DuckDuckGo-like server: refuses region "--help"; its real call answers as DuckDuckGo does when it rate-limits
# (HTTP 202), FAKE_LIMITED times, then with results. FAKE_DOWN: the service not reachable at all.
FAKE_SERVER = textwrap.dedent("""
    import json, os, sys
    limited = int(os.environ.get("FAKE_LIMITED", "0"))
    calls = 0
    for line in sys.stdin:
        message = json.loads(line)
        if "id" not in message:
            continue
        method = message["method"]
        if method == "initialize":
            result = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "fake"}}
        elif method == "tools/list":
            result = {"tools": [{"name": name, "inputSchema": {"type": "object"}}
                                for name in os.environ.get("FAKE_TOOLS", "web_search").split(",")]}
        else:
            arguments = message["params"]["arguments"]
            if arguments.get("region") == "--help":
                answer = {"error": "region: wt-wt or a code like de-de"}
            elif os.environ.get("FAKE_DOWN"):
                answer = {"error": "DuckDuckGo not reachable: ConnectError"}
            else:
                calls += 1
                answer = ({"error": "DuckDuckGo answered HTTP 202 (rate limited? retry later)"} if calls <= limited
                          else {"results": [{"title": "Example Domain"}]})
            result = {"content": [{"type": "text", "text": json.dumps(answer)}]}
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}) + "\\n")
        sys.stdout.flush()
""")

# The engine: takes podman's/docker's run line, reads the environment from --env-file, starts the server of the
# image: "fake" the server above, "local/sandbox-ai-mcp-NAME" this repository's server NAME.
FAKE_ENGINE = textwrap.dedent("""
    import os, sys
    args = sys.argv[1:]
    assert args[0] == "run", args
    env = dict(os.environ)
    image = None
    for arg in args[1:]:
        if arg.startswith("--env-file="):
            with open(arg.split("=", 1)[1]) as handle:
                for line in handle.read().splitlines():
                    key, value = line.split("=", 1)
                    env[key] = value
        elif not arg.startswith("-") and image is None:
            image = arg
    if image == "fake":
        program = [sys.executable, "-I", "-c", os.environ["FAKE_SERVER"]]
    else:
        name = image.split("sandbox-ai-mcp-", 1)[1].split(":")[0]
        program = [sys.executable, "-I", "-u", os.path.join(os.environ["HUB_ROOT"], "servers", name, "src/server.py")]
    with open(os.environ["ENGINE_LOG"], "a") as log:
        log.write(" ".join(sorted(k for k in env if k.startswith(("BRAVE", "FAKE")))) + "\\n")
    os.execve(program[0], program, env)
""")

try:
    import mcp  # noqa: F401 - the servers' own dependency
except ImportError:
    mcp = None


class SmokeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.engine = self.tmp / "engine"
        self.engine.write_text(f"#!{sys.executable}\n{FAKE_ENGINE}")
        self.engine.chmod(0o755)
        self.log = self.tmp / "engine.log"
        patcher = mock.patch.dict(os.environ, {"FAKE_SERVER": FAKE_SERVER, "HUB_ROOT": str(ROOT),
                                               "ENGINE_LOG": str(self.log)})
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("GITHUB_ACTIONS", None)

    def spec(self, limited=0, **changes):
        spec = json.loads((ROOT / "servers/duckduckgo/smoke.json").read_text())
        spec["env"] = {"FAKE_LIMITED": str(limited)}
        spec.update(changes)
        path = self.tmp / "smoke.json"
        path.write_text(json.dumps(spec))
        return path

    def run_smoke(self, spec, *extra, image="fake"):
        report = self.tmp / "report.json"
        status = smoke.main(["--engine", str(self.engine), "--image", image, "--spec", str(spec),
                             "--report", str(report), "--upstream-backoff", "0", *extra])
        return status, json.loads(report.read_text())

    def test_a_spec_raises_the_limits_of_the_run_line(self):
        argv = smoke.run_command("x", "image", memory="2g", pids=512)
        self.assertIn("--memory=2g", argv)
        self.assertIn("--pids-limit=512", argv)
        self.assertNotIn("--memory=512m", argv)
        self.assertNotIn("--pids-limit=128", argv)
        self.assertEqual([f for f in argv if f.startswith("--tmpfs=")], [f for f in smoke.RUN_FLAGS if f.startswith("--tmpfs=")])
        docker = smoke.run_command("x", "image", program="docker", memory="2g", pids=512)
        self.assertIn("--memory=2g", docker)
        self.assertFalse(any("notmpcopyup" in f for f in docker))
        self.assertEqual(smoke.run_command("x", "image"), smoke.run_command("x", "image", memory=None, pids=None))
        self.assertIn("--memory=512m", smoke.run_command("x", "image"))

    def test_limits_sandbox_ai_would_refuse_are_refused(self):
        self.assertEqual(smoke.limits({}), {})
        self.assertEqual(smoke.limits({"memory": "2g", "pids": 512}), {"memory": "2g", "pids": 512})
        for bad in ({"memory": "2G"}, {"memory": "0m"}, {"memory": 2048}, {"pids": 8}, {"pids": 5000},
                    {"pids": True}, {"pids": "512"}):
            with self.subTest(spec=bad), self.assertRaises(ValueError):
                smoke.limits(bad)

    def test_the_limits_reach_the_engine_and_the_report(self):
        status, report = self.run_smoke(self.spec(memory="2g", pids=512), "--print-argv")
        self.assertEqual(status, 0, report)
        self.assertEqual((report["memory"], report["pids"]), ("2g", 512))

    def test_the_duckduckgo_spec_names_its_rate_limit(self):
        call = json.loads((ROOT / "servers/duckduckgo/smoke.json").read_text())["calls"][0]
        self.assertFalse(call.get("expect_error"))
        self.assertIn("DuckDuckGo answered HTTP 202", call["upstream_limited"])
        server = (ROOT / "servers/duckduckgo/src/server.py").read_text()
        self.assertIn('f"DuckDuckGo answered HTTP {response.status_code} (rate limited? retry later)"', server)

    def test_a_rate_limit_that_ends_is_retried_and_passes(self):
        status, report = self.run_smoke(self.spec(limited=2))
        self.assertEqual(status, 0, report)
        real = report["checks"][1]
        self.assertEqual((real["ok"], real["attempts"], real.get("skipped")), (True, 3, None))
        self.assertEqual(report["skipped"], [])

    def test_a_rate_limit_that_stays_skips_the_real_call_only(self):
        status, report = self.run_smoke(self.spec(limited=99), "--upstream-retries", "2")
        self.assertEqual(status, 0, report)
        real, refused = report["checks"][1], report["checks"][2]
        self.assertEqual((real["ok"], real["attempts"], real["skipped"]), (True, 3, "upstream rate-limited"))
        self.assertTrue(refused["ok"])
        self.assertEqual(report["skipped"], ["tools/call web_search"])

    def test_a_rate_limit_does_not_excuse_a_failed_refusal(self):
        spec = self.spec(limited=99)
        data = json.loads(spec.read_text())
        data["calls"][1]["expect"] = "something the server does not say"
        spec.write_text(json.dumps(data))
        status, report = self.run_smoke(spec, "--upstream-retries", "0")
        self.assertEqual(status, 1)
        self.assertFalse(report["ok"])

    def test_an_unreachable_service_is_not_a_rate_limit(self):
        with mock.patch.dict(os.environ, {"FAKE_DOWN": "1"}):
            status, report = self.run_smoke(self.spec())
        self.assertEqual(status, 1)
        self.assertEqual(report["checks"][1]["attempts"], 1)
        self.assertNotIn("skipped", report["checks"][1])

    def test_a_refused_call_cannot_be_upstream_limited(self):
        spec = self.spec()
        data = json.loads(spec.read_text())
        data["calls"][1]["upstream_limited"] = ["region"]
        spec.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            self.run_smoke(spec)

    def test_annotations_on_github_actions(self):
        import contextlib
        import io
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}), contextlib.redirect_stdout(out):
            self.run_smoke(self.spec(limited=99), "--upstream-retries", "1")
        self.assertIn("::warning title=smoke duckduckgo (axross) upstream rate-limited::tools/call web_search: skipped",
                      out.getvalue())
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "true", "FAKE_DOWN": "1"}), contextlib.redirect_stdout(out):
            self.run_smoke(self.spec())
        self.assertIn("::error title=smoke duckduckgo (axross)::", out.getvalue())
        self.assertIn("%0Afailed: tools/call web_search expected", out.getvalue())

    def test_list_only_starts_without_the_secrets(self):
        """The CI's start step passes no --var: a ${VAR} of the spec is empty there, not a crash."""
        spec = ROOT / "servers/brave-search/smoke.json"
        with self.assertRaises(KeyError):  # the real calls still need every variable given
            smoke.main(["--engine", str(self.engine), "--image", "fake", "--spec", str(spec)])
        tools = self.tmp / "tools.json"
        tools.write_text(json.dumps({"tools": ["news_search", "web_search"]}))
        with mock.patch.dict(os.environ, {"FAKE_TOOLS": "news_search,web_search"}):
            status, report = self.run_smoke(spec, "--list-only", "--tools-file", str(tools))
        self.assertEqual(status, 0, report)
        self.assertIn("BRAVE_API_KEY", self.log.read_text(), "passed, empty")

    @unittest.skipIf(mcp is None, "the servers' requirements are not installed")
    def test_brave_search_starts_without_its_key(self):
        """The CI step "Start with the hardened run line" for brave-search, with the real server."""
        status, report = self.run_smoke(ROOT / "servers/brave-search/smoke.json", "--list-only", "--tools-file",
                                        str(ROOT / "servers/brave-search/tools.json"),
                                        image="local/sandbox-ai-mcp-brave-search:ci")
        self.assertEqual(status, 0, report)
        self.assertEqual(sorted(report["tools"]), ["news_search", "web_search"])

    def test_the_bwrap_usage_is_explained(self):
        hint = smoke.failure_hint("sandbox-ai-bwrap", "usage: bwrap [OPTIONS...] [--] COMMAND [ARGS...]\n")
        self.assertIn("--args", hint)
        self.assertIsNone(smoke.failure_hint("sandbox-ai-podman", "usage: bwrap"))


DIGEST = "sha256:" + "ab" * 32
SHA = "cd" * 32


class CatalogOfWhatPassed(unittest.TestCase):
    """The catalog job: ci_results.py picks the servers, make_catalog.py --only writes their entries alone."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / "hub"
        shutil.copytree(ROOT, self.root, ignore=shutil.ignore_patterns(".git", "__pycache__", "candidates"))
        self.ci = self.tmp / "ci-digests"
        os.environ.pop("GITHUB_ACTIONS", None)
        os.environ.pop("GITHUB_STEP_SUMMARY", None)

    def artifact(self, name, passed=True, skipped=False, bwrap=True, **report_changes):
        """What the image job of NAME uploads (ci-NAME, merged into one folder); bwrap=False: its Bubblewrap smoke
        failed, so the job left its rootfs out (and passed, for Podman alone)."""
        image = f"ghcr.io/c0decave/sandbox-ai-mcp-{name}"
        pinned = f"{image}@{DIGEST}"
        folder = self.ci / "rootfs-out"
        folder.mkdir(parents=True, exist_ok=True)
        (self.ci / f"digest-{name}.json").write_text(json.dumps({"name": name, "image": image, "digest": DIGEST}))
        rootfs_file = folder / f"rootfs-{name}.json"
        rootfs_file.unlink(missing_ok=True)
        (folder / f"rootfs-{name}.json").write_text(json.dumps({
            "name": name, "image": pinned, "sha256": SHA, "size": 10, "user": 10001, "workdir": "/tmp", "env": {},
            "url": f"https://github.com/c0decave/sandbox-ai-mcp/releases/download/rootfs-{name}-cdcd/rootfs-{name}.tar.gz",
            "entrypoint": ["/opt/venv/bin/python", "-I", "-u", "/opt/mcp/server.py"]}))
        for runner in sign.RUNNERS:
            checks = [{"check": "tools/list", "ok": True}, {"check": "tools.json", "ok": True}]
            if skipped:
                checks.append({"check": "tools/call web_search", "ok": True, "skipped": "upstream rate-limited"})
            checks.append({"check": "tools/call web_search", "ok": True})  # the refused call
            report = {"name": name, "image": pinned, "runner": runner, "network": "full", "ok": True,
                      "checks": checks, **({"rootfs_sha256": SHA} if runner.endswith("bwrap") else {}),
                      **report_changes}
            if runner.endswith("bwrap") and not bwrap:
                report.update(ok=False, exception="RuntimeError: initialize: the server closed stdout (exit 1)")
                rootfs_file.unlink()
            (self.ci / f"smoke-{name}-{runner}.json").write_text(json.dumps(report))
        if passed:
            (self.ci / f"result-{name}.json").write_text(json.dumps({"name": name, "passed": True}))

    def results(self):
        out = self.tmp / "passed.txt"
        status = ci_results.main([str(self.ci), "--root", str(self.root), "--out", str(out)])
        return status, out.read_text().split() if out.exists() else []

    def test_only_the_servers_that_passed(self):
        self.artifact("duckduckgo", skipped=True)
        self.artifact("telegram-user", bwrap=False)                    # Podman only: its Bubblewrap smoke failed
        self.artifact("web-fetch", passed=False)                     # a later step failed
        self.artifact("searxng", ok=False)                             # a smoke report failed
        self.artifact("telegram", image="ghcr.io/c0decave/sandbox-ai-mcp-telegram@sha256:" + "00" * 32)
        status, passed = self.results()
        self.assertEqual((status, passed), (0, ["duckduckgo", "telegram-user"]))  # brave-search etc.: nothing at all

    def test_nothing_passed_no_catalog(self):
        self.artifact("searxng", passed=False)
        self.assertEqual(self.results(), (1, []))
        self.ci.mkdir(exist_ok=True)
        self.assertEqual(ci_results.main([str(self.tmp / "none"), "--root", str(self.root)]), 1)

    def test_make_catalog_only_leaves_the_others_pending(self):
        self.artifact("duckduckgo")
        self.artifact("telegram-user", bwrap=False)
        self.artifact("web-fetch", passed=False)
        digests = json.loads((self.root / "digests.json").read_text())
        digests["images"]["telegram"] = "sha256:" + "11" * 32          # an older digest this run does not vouch for
        (self.root / "digests.json").write_text(json.dumps(digests))
        make = [sys.executable, str(self.root / "scripts/make_catalog.py"), "--root", str(self.root)]
        done = subprocess.run([*make, "--ci-digests", str(self.ci), "--only", "duckduckgo", "telegram-user",
                               "--write-digests"], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        catalog = json.loads((self.root / "catalog.json").read_text())
        pinned = {e["name"]: e.get("digest") for e in catalog["entries"]}
        self.assertEqual({n for n, d in pinned.items() if d}, {"duckduckgo", "telegram-user"})
        self.assertEqual(set(json.loads((self.root / "rootfs.json").read_text())["rootfs"]), {"duckduckgo"})
        self.assertEqual(set(catalog["pending"]), set(pinned) - {"duckduckgo", "telegram-user"})
        check = subprocess.run([*make, "--check", "--allow-pending"], capture_output=True, text=True)
        self.assertEqual(check.returncode, 0, check.stderr)
        for wrong in (["--only", "web-fetch", "nope"], ["--only", "telegram"]):
            done = subprocess.run([*make, "--ci-digests", str(self.ci), *wrong], capture_output=True, text=True)
            self.assertEqual(done.returncode, 1, wrong)
        # What the catalog job hands over is signable with these reports (sign_catalog's check, without a key).
        self.assertEqual(sign.problems_of(self.root, self.ci), [])
        self.assertEqual(sign.skipped_calls(self.ci, ["duckduckgo"]), [])

    def test_sign_catalog_takes_a_skipped_real_call_but_nothing_else_skipped(self):
        self.artifact("duckduckgo", skipped=True)
        pinned = f"ghcr.io/c0decave/sandbox-ai-mcp-duckduckgo@{DIGEST}"
        problems = lambda: sign.server_problems(self.ci, "duckduckgo", pinned, SHA, "allowlist")  # noqa: E731
        self.assertEqual(problems(), [])
        self.assertEqual(len(sign.skipped_calls(self.ci, ["duckduckgo"])), 2)
        self.artifact("duckduckgo", checks=[{"check": "tools/list", "ok": True}, {"check": "tools/call x", "ok": True},
                                            {"check": "tools.json", "ok": True, "skipped": "upstream rate-limited"}])
        self.assertIn("skipped a check other than a tool call", problems()[0])
        self.artifact("duckduckgo", checks=[{"check": "tools.json", "ok": True},
                                            {"check": "tools/call web_search", "ok": False}])  # "ok" of the report lies
        self.assertIn("failed", problems()[0])
        self.artifact("duckduckgo", checks=[{"check": "tools.json", "ok": True},
                                            {"check": "tools/call web_search", "ok": True,
                                             "skipped": "upstream rate-limited"}])
        self.assertIn("made no tool call", problems()[0], "a skipped call is not a call that ran")


class WorkflowCatalogOfWhatPassed(unittest.TestCase):
    def test_the_catalog_job_runs_when_servers_failed(self):
        workflow = (ROOT / ".github/workflows/build.yml").read_text()
        catalog = workflow[workflow.index("\n  catalog:"):]
        self.assertIn("!cancelled() && needs.test.result == 'success'", catalog)
        self.assertIn("scripts/ci_results.py ci-digests --out passed.txt", catalog)
        self.assertIn("--only $(cat passed.txt)", catalog)
        image = workflow[workflow.index("\n  image:"):workflow.index("\n  catalog:")]
        self.assertIn("if: always() && github.event_name != 'pull_request'", image)
        self.assertIn("result-${{ matrix.server }}.json", image.split("- name: Result", 1)[1])
        start = image.split("- name: Start with the hardened run line", 1)[1].split("- name:", 1)[0]
        self.assertIn("--list-only", start)


if __name__ == "__main__":
    unittest.main()
