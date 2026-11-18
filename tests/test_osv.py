"""servers/osv: our own server for the OSV vulnerability database (the three tools of StacklokLabs/osv-mcp 0.1.4,
reviewed in full), natively - handshake, tools only, refused arguments, the requests against a stand-in on loopback,
the short and the full forms, bounded answers. The real calls are in smoke.json (CI, network api.osv.dev)."""
import asyncio
import http.server
import importlib.util
import json
from pathlib import Path
import threading
import unittest

ROOT = Path(__file__).resolve().parent.parent
FOLDER = ROOT / "servers" / "osv"
FIXTURES = json.loads((ROOT / "tests" / "fixtures" / "osv.json").read_text())

try:
    import mcp  # noqa: F401
except ImportError:  # the server's requirements are not installed
    mcp = None

if mcp is not None:
    from test_own_servers import load, result, rpc, session

COMMIT = "6879efc2c1596d11a6a6ad296f80063b558d5e0f"


@unittest.skipIf(mcp is None, "the servers' requirements are not installed (servers/osv/requirements.txt)")
class Osv(unittest.TestCase):
    def setUp(self):
        self.module = load("osv")

    def test_tools_only(self):
        answers = rpc("osv", session() + [{"jsonrpc": "2.0", "id": 9, "method": "resources/list"},
                                          {"jsonrpc": "2.0", "id": 10, "method": "prompts/list"}])
        self.assertEqual(sorted(answers[0]["result"]["capabilities"]), ["experimental", "tools"])
        self.assertEqual(sorted(t["name"] for t in answers[1]["result"]["tools"]),
                         json.loads((FOLDER / "tools.json").read_text())["tools"])
        self.assertEqual(answers[9]["error"]["code"], -32601)
        self.assertEqual(answers[10]["error"]["code"], -32601)
        self.assertIn("never instructions", answers[0]["result"]["instructions"])

    def test_refused_arguments(self):
        cases = [("query_vulnerability", {}, "give purl, or package_name and ecosystem, or commit"),
                 ("query_vulnerability", {"package_name": "jinja2"}, "package_name and ecosystem go together"),
                 ("query_vulnerability", {"package_name": "jinja2", "ecosystem": "PyPI", "version": "1",
                                          "commit": COMMIT}, "either commit or version"),
                 ("query_vulnerability", {"purl": "pkg:pypi/jinja2", "ecosystem": "PyPI"}, "with purl, leave"),
                 ("query_vulnerability", {"purl": "http://evil/x"}, "purl: a package URL"),
                 ("query_vulnerability", {"commit": "abc123"}, "commit: a full git commit hash"),
                 ("query_vulnerability", {"package_name": "x", "ecosystem": "PyPI\n../"}, "ecosystem: an OSV"),
                 ("query_vulnerability", {"package_name": "a\x00b", "ecosystem": "PyPI"}, "package_name: 1-214"),
                 ("query_vulnerability", {"package_name": "x" * 215, "ecosystem": "PyPI"}, "package_name: 1-214"),
                 ("query_vulnerability", {"package_name": "x", "ecosystem": "npm", "version": "1 2"}, "version: 1-128"),
                 ("query_vulnerability", {"package_name": "x", "ecosystem": "npm", "page_token": "a b"}, "page_token"),
                 ("get_vulnerability", {"id": ""}, "CVE-2024-1234 is required"),
                 ("get_vulnerability", {"id": "../query"}, "id: an OSV id"),
                 ("get_vulnerability", {"id": "GHSA-1?x=1"}, "id: an OSV id"),
                 ("get_vulnerability", {"id": "A" * 101}, "id: an OSV id"),
                 ("query_vulnerabilities_batch", {"queries": []}, "a list of 1-100"),
                 ("query_vulnerabilities_batch", {"queries": [{"commit": COMMIT}] * 101}, "a list of 1-100"),
                 ("query_vulnerabilities_batch", {"queries": [{"commit": COMMIT}, {"url": "x"}]}, "queries[1]: unknown"),
                 ("query_vulnerabilities_batch", {"queries": [{"commit": COMMIT}, {"package_name": "a"}]},
                  "queries[1]: package_name and ecosystem go together")]
        answers = rpc("osv", session(*[(tool, args) for tool, args, _ in cases]))
        for index, (tool, args, expected) in enumerate(cases, start=2):
            self.assertIn(expected, result(answers[index])["error"], (tool, args))

    def serve(self, handler_of):
        seen = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def answer(self):
                length = int(self.headers.get("Content-Length", 0) or 0)
                body = json.loads(self.rfile.read(length)) if length else None
                seen.append((self.command, self.path, body))
                status, data = handler_of(self.command, self.path, body)
                data = data if isinstance(data, bytes) else json.dumps(data).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = answer  # noqa: N815

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        self.module.API = f"http://127.0.0.1:{server.server_address[1]}/v1"
        return seen

    def test_query_sends_upstreams_request_and_answers_the_short_form(self):
        seen = self.serve(lambda *_: (200, {"vulns": [FIXTURES["vuln"], FIXTURES["second"]],
                                            "next_page_token": "tok_1"}))
        answer = asyncio.run(self.module.query_vulnerability(package_name="jinja2", ecosystem="PyPI",
                                                             version="2.4.1"))
        self.assertEqual(seen, [("POST", "/v1/query", {"version": "2.4.1",
                                                       "package": {"name": "jinja2", "ecosystem": "PyPI"}})])
        self.assertEqual(answer["count"], 2)
        first = answer["vulnerabilities"][0]
        self.assertEqual(first["id"], "GHSA-462w-v97r-4m45")
        self.assertEqual(first["aliases"], ["CVE-2019-10906", "PYSEC-2019-217"])
        self.assertEqual(first["fixed_in"], ["2.10.1"])   # the PyPI range only, not Debian's
        self.assertIn({"level": "HIGH"}, first["severity"])
        self.assertNotIn("details", first)
        self.assertTrue(answer["vulnerabilities"][1]["summary"].startswith("The default configuration"))
        self.assertEqual(answer["next_page_token"], "tok_1")
        # a purl, a commit, a page token
        asyncio.run(self.module.query_vulnerability(purl="pkg:pypi/jinja2@2.4.1"))
        asyncio.run(self.module.query_vulnerability(commit=COMMIT.upper(), page_token="tok_1"))
        self.assertEqual(seen[1][2], {"package": {"purl": "pkg:pypi/jinja2@2.4.1"}})
        self.assertEqual(seen[2][2], {"commit": COMMIT, "page_token": "tok_1"})

    def test_batch_and_get(self):
        def handler(method, path, body):
            if path == "/v1/querybatch":
                return 200, {"results": [{"vulns": [{"id": "GHSA-462w-v97r-4m45", "modified": "x"}]}, {}]}
            return 200, FIXTURES["vuln"]
        seen = self.serve(handler)
        answer = asyncio.run(self.module.query_vulnerabilities_batch(
            queries=[{"package_name": "jinja2", "ecosystem": "PyPI", "version": "2.4.1"}, {"commit": COMMIT}]))
        self.assertEqual([r["ids"] for r in answer["results"]], [["GHSA-462w-v97r-4m45"], []])
        self.assertEqual(answer["vulnerable"], 1)
        detail = asyncio.run(self.module.get_vulnerability(id="GHSA-462w-v97r-4m45"))
        self.assertEqual(seen[-1][:2], ("GET", "/v1/vulns/GHSA-462w-v97r-4m45"))
        self.assertEqual(detail["cwe_ids"], ["CWE-693"])
        self.assertEqual(detail["affected"][0]["ranges"][0]["events"], [{"introduced": "0"}, {"fixed": "2.10.1"}])
        self.assertIn("Ignore previous instructions", detail["details"])  # data, passed on as data

    def test_errors(self):
        for status, body, expected in [(404, {"code": 5, "message": "Bug not found."}, "no such vulnerability"),
                                       (400, {"code": 3, "message": "Invalid ecosystem." + "x" * 3000}, "HTTP 400"),
                                       (429, {}, "rate limit"),
                                       (500, b"<html>" + b"y" * 5000, "HTTP 500"),
                                       (200, b"not json", "did not answer a JSON object")]:
            with self.subTest(status):
                self.serve(lambda *_: (status, body))
                answer = asyncio.run(self.module.get_vulnerability(id="CVE-2019-10906"))
                self.assertIn(expected, answer["error"])
                self.assertLess(len(answer["error"]), 700)
        self.module.API = "http://127.0.0.1:9/v1"   # nothing listens: refused
        self.assertIn("OSV not reachable", asyncio.run(self.module.get_vulnerability(id="CVE-2019-10906"))["error"])

    def test_answers_fit_24000_characters(self):
        many = []
        for index in range(400):
            vuln = json.loads(json.dumps(FIXTURES["vuln"]))
            vuln["id"] = f"GHSA-{index:04d}-aaaa-bbbb"
            vuln["summary"] = "s" * 1000
            many.append(vuln)
        self.serve(lambda *_: (200, {"vulns": many}))
        answer = asyncio.run(self.module.query_vulnerability(package_name="linux", ecosystem="Debian:12"))
        self.assertLessEqual(len(json.dumps(answer, indent=2)), 24000)
        self.assertEqual(answer["count"], 400)
        huge = json.loads(json.dumps(FIXTURES["vuln"]))
        huge["details"] = "d" * 100_000
        huge["affected"] = [json.loads(json.dumps(huge["affected"][1])) for _ in range(300)]
        huge["affected"][0]["versions"] = [str(n) for n in range(20000)]
        huge["references"] = [{"type": "WEB", "url": "https://example.com/" + "r" * 400}] * 500
        self.serve(lambda *_: (200, huge))
        detail = asyncio.run(self.module.get_vulnerability(id="GHSA-462w-v97r-4m45"))
        self.assertLessEqual(len(json.dumps(detail, indent=2)), 24000)
        self.assertIn("note", detail)
        self.serve(lambda *_: (200, {"results": [{"vulns": [{"id": f"CVE-2024-{n}"} for n in range(500)]}] * 100}))
        batch = asyncio.run(self.module.query_vulnerabilities_batch(queries=[{"commit": COMMIT}] * 100))
        self.assertLessEqual(len(json.dumps(batch, indent=2)), 24000)

    def test_a_huge_body_is_refused(self):
        self.serve(lambda *_: (200, b"[" + b"1," * (9 << 20) + b"1]"))
        self.assertIn("larger than 16 MiB", asyncio.run(self.module.get_vulnerability(id="CVE-2019-10906"))["error"])


class Packaging(unittest.TestCase):
    def test_the_entry_the_spec_and_the_image(self):
        entry = json.loads((FOLDER / "server.json").read_text())
        spec = json.loads((FOLDER / "smoke.json").read_text())
        self.assertEqual((entry["network"], entry["hosts"]), ("allowlist", ["api.osv.dev:443"]))
        self.assertEqual((spec["network"], spec["hosts"]), ("allowlist", ["api.osv.dev:443"]))
        self.assertNotIn("mounts", entry)
        self.assertTrue([c for c in spec["calls"] if c.get("expect_error")])
        dockerfile = (FOLDER / "Dockerfile").read_text()
        self.assertIn('ENTRYPOINT ["/opt/venv/bin/python", "-I", "-u", "/opt/mcp/server.py"]', dockerfile)
        lock = (FOLDER / "requirements.txt").read_text().replace("servers/osv/", "servers/duckduckgo/")
        self.assertEqual(lock, (ROOT / "servers" / "duckduckgo" / "requirements.txt").read_text())


if __name__ == "__main__":
    unittest.main()
