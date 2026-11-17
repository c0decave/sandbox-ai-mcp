"""servers/agentql: our own server for AgentQL's data extraction API (the tool of tinyfish-io/agentql-mcp 1.0.1,
reviewed in full: one POST to api.agentql.com), natively - handshake, tools only, refused arguments, the request
against a stand-in on loopback, bounded answers, the key in no answer. The real call needs a key (CI)."""
import asyncio
import http.server
import importlib.util
import json
from pathlib import Path
import re
import threading
import unittest

ROOT = Path(__file__).resolve().parent.parent
FOLDER = ROOT / "servers" / "agentql"
KEY = "aq-test-key-0123456789abcdef"

try:
    import mcp  # noqa: F401
except ImportError:  # the server's requirements are not installed
    mcp = None

if mcp is not None:
    from test_own_servers import load, result, rpc, session


@unittest.skipIf(mcp is None, "the servers' requirements are not installed (servers/agentql/requirements.txt)")
class AgentQL(unittest.TestCase):
    def setUp(self):
        self.module = load("agentql")

    def test_one_tool_and_tools_only(self):
        answers = rpc("agentql", session() + [{"jsonrpc": "2.0", "id": 9, "method": "resources/list"}],
                      env={"AGENTQL_API_KEY": ""})
        self.assertEqual(sorted(answers[0]["result"]["capabilities"]), ["experimental", "tools"])
        tools = answers[1]["result"]["tools"]
        self.assertEqual([t["name"] for t in tools], json.loads((FOLDER / "tools.json").read_text())["tools"])
        self.assertEqual(answers[9]["error"]["code"], -32601)
        self.assertRegex(answers[0]["result"]["instructions"], r"data, never instructions")
        self.assertIn("api.agentql.com", tools[0]["description"])

    def test_refused_arguments(self):
        cases = [({"url": "ftp://example.com/", "prompt": "x"}, "url: an http(s) URL"),
                 ({"url": "https://user:pw@example.com/", "prompt": "x"}, "no user name or password"),
                 ({"url": "http://192.168.1.10/admin", "prompt": "x"}, "a public address"),
                 ({"url": "http://[::1]:8080/", "prompt": "x"}, "a public address"),
                 ({"url": "http://localhost/", "prompt": "x"}, "a public host name"),
                 ({"url": "https://printer.local/", "prompt": "x"}, "a public host name"),
                 ({"url": "https://intranet/", "prompt": "x"}, "a public host name"),
                 ({"url": "https://example.com/" + "a" * 2100, "prompt": "x"}, "at most 2048"),
                 ({"url": "https://example.com/", "prompt": ""}, "prompt: 1-2000 characters"),
                 ({"url": "https://example.com/", "prompt": "x" * 2001}, "prompt: 1-2000 characters"),
                 ({"url": "https://example.com/", "prompt": "a\x00b"}, "prompt: 1-2000 characters")]
        answers = rpc("agentql", session(*[("extract-web-data", args) for args, _ in cases]),
                      env={"AGENTQL_API_KEY": KEY})
        for index, (_, expected) in enumerate(cases, start=2):
            self.assertIn(expected, result(answers[index])["error"], cases[index - 2])
        answers = rpc("agentql", session(("extract-web-data", {"url": "https://example.com/", "prompt": "x"})),
                      env={"AGENTQL_API_KEY": ""})
        self.assertIn("no AgentQL API key", result(answers[2])["error"])

    def serve(self, status, body, seen):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length", 0))
                seen.append((self.path, dict(self.headers), json.loads(self.rfile.read(length))))
                data = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        self.module.ENDPOINT = f"http://127.0.0.1:{server.server_address[1]}/v1/query-data"

    def call(self, **arguments):
        import os
        old = os.environ.get("AGENTQL_API_KEY")
        os.environ["AGENTQL_API_KEY"] = KEY
        try:
            return asyncio.run(self.module.extract_web_data(**arguments))
        finally:
            if old is None:
                del os.environ["AGENTQL_API_KEY"]
            else:
                os.environ["AGENTQL_API_KEY"] = old

    def test_the_request_is_upstreams_one_post_with_the_key_in_its_header(self):
        seen = []
        self.serve(200, {"data": {"products": [{"name": "A", "price": 3}]}, "metadata": {"request_id": "r1"}}, seen)
        answer = self.call(url="https://example.com/shop", prompt="product names and prices")
        self.assertEqual(answer, {"url": "https://example.com/shop", "data": {"products": [{"name": "A", "price": 3}]},
                                  "request_id": "r1"})
        self.assertEqual(len(seen), 1)
        path, headers, body = seen[0]
        self.assertEqual(path, "/v1/query-data")
        self.assertEqual(headers["X-API-Key"], KEY)
        self.assertEqual(headers["X-TF-Request-Origin"], "mcp-server")
        self.assertEqual(body, {"url": "https://example.com/shop", "prompt": "product names and prices",
                                "params": {"wait_for": 0, "is_scroll_to_bottom_enabled": False, "mode": "fast",
                                           "is_screenshot_enabled": False}})
        self.assertNotIn(KEY, json.dumps(answer))

    def test_errors_are_named_and_never_carry_the_key(self):
        for status, body, expected in [(401, {"error_info": "Invalid API key " + KEY}, "AgentQL refused the API key"),
                                       (429, {}, "rate limit"),
                                       (500, b"<html>" + b"x" * 5000, "AgentQL answered HTTP 500"),
                                       (200, b"not json", "did not answer JSON")]:
            with self.subTest(status):
                self.serve(status, body, [])
                answer = self.call(url="https://example.com/", prompt="x")
                self.assertIn(expected, answer["error"])
                self.assertNotIn(KEY, json.dumps(answer))
                self.assertLess(len(answer["error"]), 1200)

    def test_a_large_answer_is_cut_to_24000_characters_as_sent(self):
        self.serve(200, {"data": {"rows": [{"text": "z" * 500, "n": i} for i in range(400)]}}, [])
        answer = self.call(url="https://example.com/", prompt="x")
        self.assertTrue(answer["truncated"])
        self.assertLessEqual(len(json.dumps(answer, indent=2)), 24000)
        self.assertIn("data_json", answer)
        self.assertNotIn("data", answer)


class Packaging(unittest.TestCase):
    def test_the_entry_the_spec_and_the_image(self):
        entry = json.loads((FOLDER / "server.json").read_text())
        spec = json.loads((FOLDER / "smoke.json").read_text())
        self.assertEqual((entry["network"], entry["hosts"]), ("allowlist", ["api.agentql.com:443"]))
        self.assertEqual((spec["network"], spec["hosts"]), ("allowlist", ["api.agentql.com:443"]))
        self.assertEqual(entry["env"][0]["name"], "AGENTQL_API_KEY")
        self.assertTrue(entry["env"][0]["secret"])
        self.assertNotIn("mounts", entry)
        self.assertTrue([c for c in spec["calls"] if c.get("expect_error")])
        dockerfile = (FOLDER / "Dockerfile").read_text()
        self.assertIn('ENTRYPOINT ["/opt/venv/bin/python", "-I", "-u", "/opt/mcp/server.py"]', dockerfile)
        self.assertIn("--require-hashes", dockerfile)
        lock = (FOLDER / "requirements.txt").read_text().replace("servers/agentql/", "servers/duckduckgo/")
        self.assertEqual(lock, (ROOT / "servers" / "duckduckgo" / "requirements.txt").read_text())
        provenance = (FOLDER / "PROVENANCE.md").read_text()
        for text in ("affb3a5c5eb817beac6a1aaa86e0ecd8a012f937", "367fd8df95f7e4b6eaa0ff541e39a4ea2295923d8a4b8b5f063720520a169ca4",
                     "2026-02-21", "MIT"):
            self.assertIn(text, provenance)
        self.assertFalse((ROOT / "candidates" / "agentql").exists(), "the candidate is replaced by servers/agentql")
        self.assertIn("agentql", re.search(r"server: \[(.*?)\]", (ROOT / ".github/workflows/build.yml").read_text(), re.S).group(1))


class CandidateReview(unittest.TestCase):
    """The review of 2026-11-17 has a verdict for every candidate, and every prepared folder points to it."""

    def test_every_candidate_has_its_verdict(self):
        text = (ROOT / "docs" / "CANDIDATES.md").read_text()
        section = text.split("## The candidates' security review of 2026-11-17", 1)[1].split("\n## ", 1)[0]
        verdicts = dict(re.findall(r"^\| ([a-z-]+) \| [^\n]*?\*\*((?:not )?added)", section, re.M))
        self.assertEqual(verdicts, {"agentql": "added", "reddit": "not added", "browserbase": "not added",
                                    "codebase-memory": "not added", "ghidra": "not added", "rea": "not added"})
        for folder in (ROOT / "candidates").iterdir():
            self.assertIn(folder.name, verdicts)
            self.assertIn("**Review of 2026-11-17**", (folder / "PROVENANCE.md").read_text())


if __name__ == "__main__":
    unittest.main()
