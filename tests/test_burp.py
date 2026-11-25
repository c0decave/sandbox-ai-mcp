"""The burp server (servers/burp): its own code offline - the extension's tools listed without Burp (Community's, and
Professional's with BURP_EDITION), every call refused saying why, Burp's questions on a headless start answered (the
terms, a Professional licence key that never reaches a log line, the online activation), the Burp jar found and checked
against its SHA-256, the extension's Streamable HTTP endpoint (JSON and SSE answers, the session, a session the
extension forgot opened again, the Host header it insists on) - and a whole start with a stand-in for Burp's java that
asks the questions and then serves MCP on loopback."""
from __future__ import annotations

import contextlib
import hashlib
import http.server
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "servers" / "burp" / "src" / "server.py"


def load():
    spec = importlib.util.spec_from_file_location("server_burp_test", SERVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


burp = load()


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def rpc(messages, env=None, timeout=30):
    """MESSAGES to the server over stdio as the image starts it (no /burp here: Burp does not run); answers by id."""
    process = subprocess.Popen([sys.executable, "-I", "-u", str(SERVER)], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                               env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), **(env or {})})
    answers = {}
    try:
        for message in messages:
            process.stdin.write(json.dumps(message) + "\n")
            process.stdin.flush()
            if "id" not in message:
                continue
            while message["id"] not in answers:
                line = process.stdout.readline()
                if not line:
                    raise AssertionError(f"the server ended without answering {message['method']}")
                answer = json.loads(line)
                if "id" in answer:
                    answers[answer["id"]] = answer
    finally:
        process.stdin.close()
        process.wait(timeout)
        process.stdout.close()
    return answers


def session(*calls):
    messages = [{"jsonrpc": "2.0", "id": 0, "method": "initialize",
                 "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                            "clientInfo": {"name": "test", "version": "1"}}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}]
    for index, (tool, arguments) in enumerate(calls, start=2):
        messages.append({"jsonrpc": "2.0", "id": index, "method": "tools/call",
                         "params": {"name": tool, "arguments": arguments}})
    return messages


class FakeExtension:
    """The extension's /mcp as its SDK serves it (enableJsonResponse): initialize opens a session (Mcp-Session-Id),
    notifications get 202, requests a JSON answer or, with sse=True, an SSE stream; a Host other than
    127.0.0.1:PORT or localhost:PORT gets 403 (KtorServerManager.isValidHost)."""

    def __init__(self, tools=("url_encode",), sse=False):
        self.tools, self.sse = list(tools), sse
        self.sessions = set()
        self.opened = 0
        self.seen = []
        self.port = free_port()
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                owner.seen.append((dict(self.headers), body))
                host = self.headers.get("Host")
                if host not in (f"127.0.0.1:{owner.port}", f"localhost:{owner.port}"):
                    return self.answer(403, b"")
                if "application/json" not in self.headers.get("Accept", "") or \
                        "text/event-stream" not in self.headers.get("Accept", ""):
                    return self.answer(406, b"")
                if body.get("method") == "initialize":
                    owner.opened += 1
                    sid = f"s{owner.opened}"
                    owner.sessions.add(sid)
                    return self.json({"jsonrpc": "2.0", "id": body["id"], "result": {
                        "protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                        "serverInfo": {"name": "burp-suite", "version": "1.1.2"}}}, {"Mcp-Session-Id": sid})
                if self.headers.get("Mcp-Session-Id") not in owner.sessions:
                    return self.answer(404, b"Session not found")
                if "id" not in body:
                    return self.answer(202, b"")
                if body["method"] == "tools/list":
                    result = {"tools": [{"name": n, "inputSchema": {"type": "object"}} for n in owner.tools]}
                else:
                    text = f"called {body['params']['name']} with {json.dumps(body['params'].get('arguments'))}"
                    result = {"content": [{"type": "text", "text": text}], "isError": False}
                return self.json({"jsonrpc": "2.0", "id": body["id"], "result": result})

            def json(self, message, headers=None):
                if owner.sse:
                    data = f"event: message\ndata: {json.dumps(message)}\n\n".encode()
                    return self.answer(200, data, headers, "text/event-stream")
                return self.answer(200, json.dumps(message).encode(), headers, "application/json")

            def answer(self, status, data, headers=None, kind="application/json"):
                self.send_response(status)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(data)))
                for name, value in (headers or {}).items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(data)

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class StaticTools(unittest.TestCase):
    def test_without_burp_the_extensions_community_tools_are_listed_and_every_call_says_why(self):
        answers = rpc(session(("url_encode", {"content": "a b"})))
        self.assertEqual(answers[0]["result"]["serverInfo"]["name"], "burp-suite")
        self.assertEqual(answers[0]["result"]["capabilities"], {"tools": {"listChanged": True}})
        names = sorted(t["name"] for t in answers[1]["result"]["tools"])
        self.assertEqual(names, json.loads((ROOT / "servers/burp/tools.json").read_text())["tools"])
        self.assertEqual(len(names), 24)
        self.assertNotIn("get_scanner_issues", names)
        self.assertTrue(answers[2]["result"]["isError"])
        self.assertIn("no Burp jar is mounted at /burp", answers[2]["result"]["content"][0]["text"])

    def test_professional_adds_the_scanner_and_collaborator_tools(self):
        answers = rpc(session(), env={"BURP_EDITION": "professional"})
        names = {t["name"] for t in answers[1]["result"]["tools"]}
        self.assertTrue({"get_scanner_issues", "generate_collaborator_payload",
                         "get_collaborator_interactions"} <= names)
        self.assertEqual(len(names), 27)

    def test_other_methods_are_not_found_and_a_broken_line_is_a_parse_error(self):
        answers = rpc([{"jsonrpc": "2.0", "id": 5, "method": "resources/list"}])
        self.assertEqual(answers[5]["error"]["code"], -32601)

    def test_a_wrong_edition_is_said_by_every_call(self):
        answers = rpc(session(("url_encode", {"content": "x"})), env={"BURP_EDITION": "enterprise"})
        self.assertIn("BURP_EDITION must be community or professional", answers[2]["result"]["content"][0]["text"])

    def test_the_schemas_are_the_extensions(self):
        tools = {t["name"]: t for t in burp.static_tools("professional")}
        self.assertEqual(tools["send_http1_request"]["inputSchema"]["required"],
                         ["content", "targetHostname", "targetPort", "usesHttps"])
        self.assertNotIn("tabName", tools["create_repeater_tab"]["inputSchema"]["required"])
        self.assertEqual(tools["send_http2_request"]["inputSchema"]["properties"]["headers"],
                         {"type": "object", "additionalProperties": {"type": "string"}})
        self.assertEqual(tools["get_collaborator_interactions"]["inputSchema"]["required"], [])


class Questions(unittest.TestCase):
    def test_burps_headless_questions(self):
        self.assertEqual(burp.question_of("Burp Suite Professional Terms and Conditions\n...\n"
                                          "Do you accept the terms and conditions? (y/n)"), "terms")
        self.assertEqual(burp.question_of("Do you accept the license agreement? (y/n)\n"), "terms")
        self.assertEqual(burp.question_of("Please enter your license key:"), "licence")
        self.assertEqual(burp.question_of("Enter preferred activation method (o: online activation; m: manual "
                                          "activation; r: re-enter license key)\n"), "activation")
        self.assertIsNone(burp.question_of("Proxy service started on 127.0.0.1:8080\n"))
        self.assertIsNone(burp.question_of(""))

    def test_the_answers(self):
        self.assertEqual(burp.answer_of("terms", ""), "y\n")
        self.assertEqual(burp.answer_of("licence", " KEY \n"), "KEY\n")
        self.assertEqual(burp.answer_of("activation", "KEY"), "o\n")
        with self.assertRaisesRegex(ValueError, "needs the secret BURP_LICENSE"):
            burp.answer_of("licence", "")

    def test_the_licence_never_reaches_a_log_line(self):
        scrub = burp.Scrubber("ABCD-EFGH-IJKL-MNOP-QRST")
        self.assertEqual(scrub("key ABCD-EFGH-IJKL-MNOP-QRST ok"), "key [BURP_LICENSE] ok")
        self.assertEqual(scrub("key ABCDEFGHIJKLMNOPQRST ok"), "key [BURP_LICENSE] ok")
        self.assertEqual(burp.Scrubber("")("text"), "text")


class Jar(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: [p.unlink() for p in self.folder.iterdir()] and None or self.folder.rmdir())

    def test_the_one_jar_or_the_named_one(self):
        self.assertIsNone(burp.find_jar(str(self.folder)))
        (self.folder / "burpsuite_pro_v2026.10.jar").write_bytes(b"PK")
        self.assertEqual(burp.find_jar(str(self.folder)).name, "burpsuite_pro_v2026.10.jar")
        (self.folder / "other.jar").write_bytes(b"PK")
        with self.assertRaisesRegex(ValueError, "several jars"):
            burp.find_jar(str(self.folder))
        self.assertEqual(burp.find_jar(str(self.folder), "other.jar").name, "other.jar")
        with self.assertRaisesRegex(ValueError, "directly in"):
            burp.find_jar(str(self.folder), "/etc/passwd")
        with self.assertRaisesRegex(ValueError, "directly in"):
            burp.find_jar(str(self.folder), "../x.jar")

    def test_a_link_is_not_used(self):
        (self.folder / "real.bin").write_bytes(b"PK")
        os.symlink(self.folder / "real.bin", self.folder / "burp.jar")
        with self.assertRaisesRegex(ValueError, "no regular file"):
            burp.find_jar(str(self.folder))

    def test_a_jar_that_changed_does_not_run(self):
        (self.folder / "burp.jar").write_bytes(b"PK original")
        wanted = hashlib.sha256(b"PK original").hexdigest()
        found, edition = burp.burp_from_environment({"BURP_JAR_SHA256": wanted, "BURP_EDITION": "community"},
                                                    folder=str(self.folder), data=str(self.folder))
        self.assertEqual((found.jar.name, edition), ("burp.jar", "community"))
        (self.folder / "burp.jar").write_bytes(b"PK changed")
        with self.assertRaisesRegex(ValueError, "changed since it was added"):
            burp.burp_from_environment({"BURP_JAR_SHA256": wanted}, folder=str(self.folder), data=str(self.folder))

    def test_the_command_line(self):
        command = burp.burp_command(Path("/burp/b.jar"), "/data", "professional", 3072, "/data/tmp/u.json")
        self.assertIn("-Djava.awt.headless=true", command)
        self.assertIn("-Dsandbox.ai.burp.mcp=container", command)
        self.assertIn("--disable-auto-update", command)
        self.assertIn("--project-file=/data/burp-project.burp", command)
        self.assertNotIn("--project-file=/data/burp-project.burp",
                         burp.burp_command(Path("/burp/b.jar"), "/data", "community", 3072, "/x"))
        extension = burp.user_options()["user_options"]["extender"]["extensions"][0]
        self.assertEqual((extension["extension_file"], extension["loaded"]), (burp.EXTENSION, True))

    def test_the_heap(self):
        memory = self.folder / "memory.max"
        memory.write_text(str(4 << 30))
        self.assertEqual(burp.heap_mib(str(memory)), 3072)
        memory.write_text("max\n")
        self.assertEqual(burp.heap_mib(str(memory)), 2048)


class Endpoint(unittest.TestCase):
    def test_json_and_sse_answers(self):
        self.assertEqual(burp.parse_answer("application/json", b'{"id":1}'), [{"id": 1}])
        self.assertEqual(burp.parse_answer("text/event-stream; charset=utf-8",
                                           b'event: message\r\ndata: {"id":1}\r\n\r\ndata: {"id":2}\n\n'),
                         [{"id": 1}, {"id": 2}])
        with self.assertRaises(ValueError):
            burp.parse_answer("text/html", b"<html>")

    def test_a_session_with_the_host_the_extension_wants_and_opened_again_when_forgotten(self):
        for sse in (False, True):
            fake = FakeExtension(sse=sse)
            self.addCleanup(fake.close)
            endpoint = burp.Endpoint(port=fake.port)
            answer = endpoint.request("tools/call", {"name": "url_encode", "arguments": {"content": "a b"}}, 7)
            self.assertEqual(answer["id"], 7)
            self.assertIn("called url_encode", answer["result"]["content"][0]["text"])
            headers = fake.seen[-1][0]
            self.assertEqual(headers["Host"], f"127.0.0.1:{fake.port}")
            self.assertEqual(headers["Mcp-Session-Id"], "s1")
            self.assertNotIn("mozilla", headers["User-Agent"].lower())
            fake.sessions.clear()  # the extension ends idle sessions after 30 minutes
            answer = endpoint.request("tools/list", {}, 8)
            self.assertEqual(answer["result"]["tools"][0]["name"], "url_encode")
            self.assertEqual(endpoint.session, "s2")


FAKE_JAVA = textwrap.dedent('''\
    #!PYTHON
    """A stand-in for Burp's java: Burp's headless questions, then the extension's /mcp on loopback."""
    import http.server, json, os, sys, threading
    home = os.environ["HOME"]
    port = int(open(os.path.join(home, "port")).read())
    open(os.path.join(home, "argv.json"), "w").write(json.dumps(sys.argv[1:]))
    def ask(question):
        sys.stdout.write(question)
        sys.stdout.flush()
        return sys.stdin.readline().strip()
    if ask("Do you accept the terms and conditions? (y/n)") != "y":
        sys.exit(3)
    if os.path.exists(os.path.join(home, "pro")):
        key = ask("\\nPlease enter your license key:")
        open(os.path.join(home, "typed-key"), "w").write(key)
        print("checking key " + key)
        if ask("Enter preferred activation method (o: online activation; m: manual activation; r: re-enter "
               "license key)\\n") != "o":
            sys.exit(4)
    print("Burp is ready")
    sys.stdout.flush()
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if "id" not in body:
                self.send_response(202); self.send_header("Content-Length", "0"); self.end_headers(); return
            if body["method"] == "initialize":
                result = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "burp-suite"}}
            elif body["method"] == "tools/list":
                result = {"tools": [{"name": "url_encode", "inputSchema": {"type": "object"}}]}
            else:
                result = {"content": [{"type": "text", "text": "a%20b"}], "isError": False}
            data = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": result}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Mcp-Session-Id", "s1"); self.send_header("Content-Length", str(len(data)))
            self.end_headers(); self.wfile.write(data)
    http.server.HTTPServer(("127.0.0.1", port), Handler).serve_forever()
''').replace("#!PYTHON", "#!" + sys.executable + " -I")


class WholeStart(unittest.TestCase):
    def start(self, professional):
        home = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(home)], check=False))
        java = home / "java"
        java.write_text(FAKE_JAVA)
        java.chmod(0o755)
        jar = home / "burp.jar"
        jar.write_bytes(b"PK")
        port = free_port()
        (home / "port").write_text(str(port))
        if professional:
            (home / "pro").write_text("")
        stderr = io.StringIO()
        runner = burp.Burp(jar, str(home), "professional" if professional else "community",
                           "AAAA-BBBB-CCCC-DDDD-EEEE" if professional else "", 60, True, java=str(java), port=port)
        self.addCleanup(runner.stop)
        with contextlib.redirect_stderr(stderr):
            runner.start()
            self.assertIsNone(runner.wait())
        return runner, home, port, stderr.getvalue()

    def test_community_accepts_the_terms_and_its_tools_come_from_the_extension(self):
        runner, home, port, said = self.start(False)
        argv = json.loads((home / "argv.json").read_text())
        self.assertIn("-Dsandbox.ai.burp.mcp=container", argv)
        self.assertIn("Burp asked (terms); answered", said)
        out = io.StringIO()
        server = burp.Server(runner, "community", burp.Endpoint(port=port), out=out)
        server.listed = sorted(t["name"] for t in burp.static_tools("community"))
        server.call(3, {"name": "url_encode", "arguments": {"content": "a b"}})
        lines = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual(lines[0]["method"], "notifications/tools/list_changed")  # 1 tool here, 24 listed first
        self.assertEqual(lines[1]["result"]["content"][0]["text"], "a%20b")

    def test_professional_types_the_licence_and_activates_online_and_the_key_is_never_logged(self):
        runner, home, port, said = self.start(True)
        self.assertEqual((home / "typed-key").read_text(), "AAAA-BBBB-CCCC-DDDD-EEEE")
        self.assertIn("Burp asked (licence); answered", said)
        self.assertIn("Burp asked (activation); answered", said)
        self.assertIn("checking key [BURP_LICENSE]", said)
        self.assertNotIn("AAAA-BBBB", said)
        argv = json.loads((home / "argv.json").read_text())
        self.assertIn(f"--project-file={home}/burp-project.burp", argv)

    def test_a_second_connection_on_the_same_data_folder_is_refused(self):
        runner, home, port, said = self.start(False)
        second = burp.Burp(runner.jar, str(home), "community", "", 30, True, java=runner.java, port=port)
        with contextlib.redirect_stderr(io.StringIO()):
            second.start()
            self.assertIn("runs already for another connection", second.wait())

    def test_professional_without_a_licence_says_what_to_do(self):
        home = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(home)], check=False))
        java = home / "java"
        java.write_text(FAKE_JAVA)
        java.chmod(0o755)
        (home / "port").write_text(str(free_port()))
        (home / "pro").write_text("")
        runner = burp.Burp(home / "java", str(home), "professional", "", 60, True, java=str(java),
                           port=int((home / "port").read_text()))
        self.addCleanup(runner.stop)
        with contextlib.redirect_stderr(io.StringIO()):
            runner.start()
            self.assertIn("needs the secret BURP_LICENSE", runner.wait())


if __name__ == "__main__":
    unittest.main()
