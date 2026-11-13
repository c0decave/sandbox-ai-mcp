"""The sandbox-ai-mcp servers of this repository, natively: MCP handshake, tool list, argument
checks and the parsers against recorded answers (no network needed). The live calls against the
real services are in each server's smoke.json, run by CI with the catalog's network."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent


def load(name):
    spec = importlib.util.spec_from_file_location(f"server_{name.replace('-', '_')}", ROOT / "servers" / name / "src/server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rpc(name, messages, env=None, timeout=60):
    """Send JSON-RPC messages to the server over stdio, one after the other, each request waiting
    for its answer; the answers by id."""
    process = subprocess.Popen([sys.executable, "-I", "-u", str(ROOT / "servers" / name / "src/server.py")],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                               env={**os.environ, **(env or {})})
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
                    raise AssertionError(f"{name} ended without answering {message['method']}")
                answer = json.loads(line)
                if "id" in answer:
                    answers[answer["id"]] = answer
    finally:
        process.stdin.close()
        process.wait(timeout)
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


def result(answer):
    content = answer["result"]["structuredContent"] if "structuredContent" in answer["result"] else \
        json.loads(answer["result"]["content"][0]["text"])
    return content.get("result", content)


try:
    import mcp  # noqa: F401 - the servers' own dependency
except ImportError:
    mcp = None


@unittest.skipIf(mcp is None, "the servers' requirements are not installed (pip install --require-hashes -r "
                              "servers/duckduckgo/requirements.txt)")
class Servers(unittest.TestCase):
    def check_tools(self, name):
        expected = json.loads((ROOT / "servers" / name / "tools.json").read_text())["tools"]
        answers = rpc(name, session())
        self.assertIn("serverInfo", answers[0]["result"])
        self.assertEqual(sorted(t["name"] for t in answers[1]["result"]["tools"]), expected)
        return answers

    def test_duckduckgo(self):
        self.check_tools("duckduckgo")
        answers = rpc("duckduckgo", session(("web_search", {"query": "x", "max_results": 99}),
                                            ("web_search", {"query": "x", "region": "--help"}),
                                            ("web_search", {"query": "a\x00b"})))
        self.assertIn("max_results", result(answers[2])["error"])
        self.assertIn("region", result(answers[3])["error"])
        self.assertIn("query", result(answers[4])["error"])
        module = load("duckduckgo")
        page = (ROOT / "tests/fixtures/duckduckgo.html").read_text()
        found = module.parse_results(page, 10)
        self.assertEqual(found[0], {"title": "Example Domain", "url": "https://example.com/",
                                    "snippet": "This domain is for use in illustrative examples."})
        self.assertEqual(len(found), 2)  # the ad without a real link and the javascript: link are dropped
        self.assertEqual(module.parse_results(page, 1), found[:1])

    def test_brave_search(self):
        self.check_tools("brave-search")
        answers = rpc("brave-search", session(("web_search", {"query": "x"}), ("web_search", {"query": "x", "count": 0}),
                                              ("news_search", {"query": "x", "freshness": "pq"})),
                      env={"BRAVE_API_KEY": ""})
        self.assertIn("BRAVE_API_KEY", result(answers[2])["error"])
        self.assertIn("count", result(answers[3])["error"])
        self.assertIn("freshness", result(answers[4])["error"])
        module = load("brave-search")
        data = json.loads((ROOT / "tests/fixtures/brave-web.json").read_text())
        self.assertEqual(module.web_results(data), [{"title": "Example Domain", "url": "https://example.com/",
                                                     "description": "Example description"}])

    def test_web_fetch_refuses_private_ipv4_behind_nat64(self):
        """An IPv6 address carrying an IPv4 one reaches that IPv4 address: it must be public too."""
        import ipaddress
        module = load("web-fetch")
        for private in ("64:ff9b::a00:1", "64:ff9b::7f00:1", "64:ff9b::c0a8:101", "64:ff9b:1::a00:1",
                        "::ffff:10.0.0.1", "2002:a00:1::1", "10.0.0.1", "::1"):
            self.assertFalse(module.public(ipaddress.ip_address(private)), private)
        for public in ("64:ff9b::808:808", "8.8.8.8", "2606:4700:4700::1111"):
            self.assertTrue(module.public(ipaddress.ip_address(public)), public)

    def test_web_fetch(self):
        self.check_tools("web-fetch")
        answers = rpc("web-fetch", session(("fetch_page", {"url": "http://127.0.0.1:9/"}),
                                           ("fetch_page", {"url": "file:///etc/passwd"}),
                                           ("fetch_page", {"url": "http://user:pw@example.org/"}),
                                           ("fetch_page", {"url": "http://localhost/"}),
                                           ("fetch_page", {"url": "http://[::1]/"}),
                                           ("fetch_page", {"url": "http://169.254.169.254/latest/meta-data/"})))
        for index in range(2, 8):
            self.assertIn("error", result(answers[index]), index)
        self.assertIn("not a public address", result(answers[2])["error"])
        self.assertIn("http or https", result(answers[3])["error"])
        module = load("web-fetch")
        page = module.page_text("<html><head><title> T </title><script>evil()</script></head><body><h1>Head</h1>"
                                "<p>One <b>two</b></p><a href='/x'>x</a><a href='javascript:1'>j</a>"
                                "<style>p{}</style></body></html>", "https://example.org/a/")
        self.assertEqual(page["title"], "T")
        self.assertEqual(page["text"], "Head\n\nOne two\nxj")  # two inline links stay on one line
        self.assertEqual(page["links"], ["https://example.org/x"])

    def test_whatweb(self):
        """WhatWeb's server: refusals, the address check, the bounded answer, redirects followed by the server
        (each hop checked), and WhatWeb's run line - against a stand-in for WhatWeb (no Ruby, no network)."""
        import ipaddress
        import tempfile
        self.check_tools("whatweb")
        answers = rpc("whatweb", session(("fingerprint", {"url": "file:///etc/passwd"}),
                                         ("fingerprint", {"url": "http://169.254.169.254/latest/"}),
                                         ("fingerprint", {"url": "http://127.0.0.1/"}),
                                         ("fingerprint", {"url": "http://user:pw@example.org/"}),
                                         ("fingerprint", {"url": "https://example.org/", "aggression": 4}),
                                         ("fingerprint", {"url": "http://exa mple.org/"}),
                                         ("plugin_info", {"search": "--debug"}),
                                         ("plugin_info", {"search": "a,b"}),
                                         ("fingerprint", {"url": "http://10.0.0.1/"})),
                      env={"ALLOW_PRIVATE_TARGETS": ""})
        self.assertIn("http or https", result(answers[2])["error"])
        self.assertIn("not a public address", result(answers[3])["error"])
        self.assertIn("not a public address", result(answers[4])["error"])
        self.assertIn("without user name or password", result(answers[5])["error"])
        self.assertIn("http or https", result(answers[7])["error"])
        self.assertIn("search", result(answers[8])["error"])
        self.assertIn("search", result(answers[9])["error"])
        self.assertIn("ALLOW_PRIVATE_TARGETS=1", result(answers[10])["error"])
        module = load("whatweb")
        # aggression 4 never reaches WhatWeb (checked after the URL, so with a URL that passes)
        module.check_url = lambda url: url
        self.assertIn("4 is not offered", asyncio.run(module.fingerprint("https://example.org/", 4))["error"])
        self.assertIn("4 is not offered", asyncio.run(module.fingerprint("https://example.org/", True))["error"])
        for private, allowed in (("10.0.0.1", True), ("172.31.1.1", True), ("192.168.1.1", True), ("100.64.0.1", True),
                                 ("fd00::1", True), ("::ffff:10.0.0.1", True), ("64:ff9b::a00:1", True),
                                 ("127.0.0.1", False), ("::1", False), ("169.254.169.254", False), ("fe80::1", False),
                                 ("0.0.0.0", False), ("224.0.0.1", False), ("192.0.2.1", False), ("240.0.0.1", False),
                                 ("255.255.255.255", False), ("64:ff9b::7f00:1", False), ("2001:db8::1", False)):
            address = ipaddress.ip_address(private)
            self.assertFalse(module.allowed(address, False), private)
            self.assertEqual(module.allowed(address, True), allowed, private)
        for public in ("8.8.8.8", "2606:4700:4700::1111", "64:ff9b::808:808"):
            self.assertTrue(module.allowed(ipaddress.ip_address(public), False), public)
        # the bounded answer of a recorded log
        fixture = json.loads((ROOT / "tests/fixtures/whatweb-example.json").read_text())
        page = module.parse_log(fixture["https"])[0]
        self.assertEqual(page["http_status"], 200)
        self.assertEqual(page["plugins"]["Title"], {"string": ["Example Domain"]})
        self.assertEqual(len(page["plugins"]["X-Powered-By"]["string"]), module.MAX_VALUES)
        self.assertEqual(len(page["plugins"]["X-Powered-By"]["string"][0]), module.MAX_VALUE)
        self.assertNotIn("request_config", page)
        self.assertIsNone(module.next_hop("https://example.com/", page))  # a javascript: meta refresh is no hop
        self.assertEqual(module.parse_log(fixture["empty"]), [])
        with self.assertRaises(module.ArgumentError):
            module.parse_log("[\n{\"target\":")  # cut off
        # WhatWeb's run line and the redirect the server follows itself, with a stand-in for WhatWeb
        folder = tempfile.mkdtemp()
        try:
            fake = Path(folder) / "fake_whatweb.py"
            calls = Path(folder) / "calls.jsonl"
            fake.write_text(
                "import json, os, sys, time\n"
                f"fixture = json.load(open({str(ROOT / 'tests/fixtures/whatweb-example.json')!r}))\n"
                "args = sys.argv[1:]\n"
                f"open({str(calls)!r}, 'a').write(json.dumps({{'args': args, 'cwd': os.getcwd(), 'env': dict(os.environ)}}) + '\\n')\n"
                "url = args[args.index('--') + 1]\n"
                "if url == 'https://slow.example/':\n"
                "    time.sleep(30)\n"
                "log = next(a for a in args if a.startswith('--log-json='))[len('--log-json='):]\n"
                "if url == 'https://down.example/':\n"
                "    open(log, 'w').write('[\\n]\\n'); print('ERROR Opening: https://down.example/ - refused', file=sys.stderr)\n"
                "elif url == 'https://cut.example/':\n"
                "    open(log, 'w').write('[\\n{\\\"target\\\"')\n"
                "else:\n"
                "    open(log, 'w').write(fixture['http' if url.startswith('http:') else 'https'])\n")
            module.RUBY, module.RUBY_FLAGS, module.WHATWEB = sys.executable, (), str(fake)
            seen = []
            module.check_url = lambda url: seen.append(url) or url
            answer = asyncio.run(module.fingerprint("http://example.com/"))
            self.assertEqual(answer["final_url"], "https://example.com/", answer)
            self.assertEqual([t["url"] for t in answer["targets"]], ["http://example.com/", "https://example.com/"])
            self.assertEqual(seen, ["http://example.com/", "https://example.com/"])  # every hop checked
            self.assertEqual(answer["targets"][1]["plugins"]["Title"]["string"], ["Example Domain"])
            runs = [json.loads(line) for line in calls.read_text().splitlines()]
            self.assertEqual(len(runs), 2)
            args = runs[0]["args"]
            self.assertEqual(args[-2:], ["--", "http://example.com/"])
            for flag in ("--follow-redirect=never", "--aggression=1", "--max-threads=1", "--quiet", "--colour=never"):
                self.assertIn(flag, args)
            for flag in ("--custom-plugin", "--grep", "-p", "--plugins", "--input-file", "-i", "--cookie-jar",
                         "--log-sql-create", "--proxy"):
                self.assertFalse(any(a == flag or a.startswith(flag + "=") for a in args), flag)
            self.assertEqual(sorted(runs[0]["env"]), ["HOME", "LANG", "LC_ALL", "PATH", "TMPDIR"])
            self.assertEqual(runs[0]["env"]["HOME"], runs[0]["cwd"])  # a fresh folder per run ...
            self.assertFalse(os.path.exists(runs[0]["cwd"]))         # ... removed afterwards
            no_hop = asyncio.run(module.fingerprint("http://example.com/", 3, False))
            self.assertEqual(len(no_hop["targets"]), 1)
            self.assertIn("--aggression=3", json.loads(calls.read_text().splitlines()[-1])["args"])
            self.assertIn("gave no answer: ERROR Opening: https://down.example/ - refused",
                          asyncio.run(module.fingerprint("https://down.example/"))["error"])
            self.assertIn("gave an incomplete answer", asyncio.run(module.fingerprint("https://cut.example/"))["error"])
            module.RUN_TIMEOUT = {1: 1, 3: 1}
            self.assertIn("did not finish within 1 s", asyncio.run(module.fingerprint("https://slow.example/"))["error"])
        finally:
            import shutil
            shutil.rmtree(folder, ignore_errors=True)

    def test_telegram(self):
        self.check_tools("telegram")
        too_long = "x" * 4097
        answers = rpc("telegram", session(("get_me", {}),
                                          ("send_message", {"chat_id": 42, "text": "x"}),
                                          ("send_message", {"chat_id": 111, "text": too_long}),
                                          ("send_message", {"chat_id": 111, "text": " "}),
                                          ("send_message", {"chat_id": 111, "text": "a\x00b"}),
                                          ("send_message", {"chat_id": 111, "text": "x", "parse_mode": "Markdown"}),
                                          ("get_chat", {"chat_id": "@somechannel"}),
                                          ("get_updates", {"limit": 101}),
                                          ("get_updates", {"timeout": 51}),
                                          ("edit_message_text", {"chat_id": 111, "message_id": 0, "text": "x"})),
                      env={"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_ALLOWED_CHATS": "111, -1001234567890"})
        self.assertIn("TELEGRAM_BOT_TOKEN", result(answers[2])["error"])
        self.assertIn("42 is not in TELEGRAM_ALLOWED_CHATS", result(answers[3])["error"])
        for index in (4, 5, 6):
            self.assertIn("text: 1-4096", result(answers[index])["error"], index)
        self.assertIn("parse_mode", result(answers[7])["error"])
        self.assertIn("numeric chat id", result(answers[8])["error"])
        self.assertIn("limit", result(answers[9])["error"])
        self.assertIn("timeout", result(answers[10])["error"])
        self.assertIn("message_id", result(answers[11])["error"])
        answers = rpc("telegram", session(("get_me", {}), ("get_updates", {})),
                      env={"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_ALLOWED_CHATS": "111,@x"})
        for index in (2, 3):  # a broken allowlist refuses everything, before the token
            self.assertIn("TELEGRAM_ALLOWED_CHATS: comma-separated", result(answers[index])["error"])

        module = load("telegram")
        data = json.loads((ROOT / "tests/fixtures/telegram-updates.json").read_text())
        updates, skipped, next_offset = module.updates_of(data["result"], frozenset({111, -1001234567890}))
        self.assertEqual(next_offset, 507)
        self.assertEqual(skipped, 3)  # chat 999, group -42 and the poll (no chat)
        self.assertEqual([u["update_id"] for u in updates], [500, 501, 503, 504])
        self.assertEqual(updates[0], {"update_id": 500, "type": "message", "message": {
            "message_id": 7, "chat": {"id": 111, "type": "private", "username": "ada", "first_name": "Ada"},
            "date": 1762300000, "from": {"id": 111, "is_bot": False, "username": "ada", "first_name": "Ada"},
            "text": "Hello bot"}})
        self.assertEqual(updates[1]["message"]["media"], ["photo"])
        self.assertEqual(updates[1]["message"]["caption"], "A picture")
        self.assertEqual(updates[2]["message"]["text"], "my token is <token>")  # token-shaped text never passes
        self.assertEqual(updates[2]["message"]["reply_to_message_id"], 6)
        self.assertEqual(updates[3], {"update_id": 504, "type": "callback_query", "chat_id": 111,
                                      "from": {"id": 111, "is_bot": False, "first_name": "Ada"}, "data": "yes"})
        updates, skipped, _ = module.updates_of(data["result"], None)
        self.assertEqual((len(updates), skipped), (7, 0))
        self.assertEqual(updates[6], {"update_id": 506, "type": "poll"})
        self.assertEqual(module.message_text("\U0001F600" * 2048), "\U0001F600" * 2048)  # UTF-16 units
        with self.assertRaises(module.ArgumentError):
            module.message_text("\U0001F600" * 2049)

    def test_telegram_requests_and_token(self):
        """Against a local stand-in for the Bot API: the request each tool sends, and the token in
        no answer and no log line, whatever fails."""
        import http.server
        import io
        import logging
        import threading
        from unittest import mock

        token = "123456:test-token-not-a-real-one-abcdef"
        seen = []

        class BotApi(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                seen.append((self.path, body))
                method = self.path.rsplit("/", 1)[-1]
                status, answer = {
                    "sendMessage": (200, {"ok": True, "result": {
                        "message_id": 12, "date": 1, "chat": {"id": 111, "type": "private"}, "text": body.get("text")}}),
                    "getChat": (400, {"ok": False, "error_code": 400, "description": f"Bad Request: chat not found {token}"}),
                    "getMe": (401, {"ok": False, "error_code": 401, "description": "Unauthorized"}),
                    "getUpdates": (429, {"ok": False, "error_code": 429, "description": "Too Many Requests",
                                         "parameters": {"retry_after": 7}}),
                }.get(method, (302, {}))
                data = json.dumps(answer).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Location", f"http://127.0.0.1:9/bot{token}/x")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), BotApi)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        module = load("telegram")
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(module.RedactingFormatter("%(name)s %(message)s"))
        logging.getLogger().addHandler(handler)
        self.addCleanup(logging.getLogger().removeHandler, handler)
        env = {"TELEGRAM_BOT_TOKEN": token, "TELEGRAM_ALLOWED_CHATS": "111"}
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(module, "API", f"http://127.0.0.1:{server.server_port}/bot"):
            sent = asyncio.run(module.send_message(111, "hi <b>you</b>", "HTML", False, 5))
            failed = [asyncio.run(module.get_chat(111)), asyncio.run(module.get_me()),
                      asyncio.run(module.get_updates(0, 20, 0)), asyncio.run(module.edit_message_text(111, 12, "x"))]
            with mock.patch.object(module, "API", "http://127.0.0.1:9/bot"):
                failed.append(asyncio.run(module.get_me()))
            logging.getLogger("telegram-mcp").error("a line with %s", f"https://api.telegram.org/bot{token}/getMe")
        self.assertEqual(sent, {"sent": {"message_id": 12, "chat": {"id": 111, "type": "private"}, "date": 1,
                                         "text": "hi <b>you</b>"}})
        self.assertEqual(seen[0], (f"/bot{token}/sendMessage", {
            "chat_id": 111, "text": "hi <b>you</b>", "disable_notification": False,
            "link_preview_options": {"is_disabled": True}, "parse_mode": "HTML",
            "reply_parameters": {"message_id": 5, "allow_sending_without_reply": True}}))
        self.assertEqual([path.rsplit("/", 1)[-1] for path, _ in seen],
                         ["sendMessage", "getChat", "getMe", "getUpdates", "editMessageText"])
        self.assertEqual(failed[0], {"error": "Telegram answered 400: Bad Request: chat not found <token>"})
        self.assertEqual(failed[1], {"error": "Telegram refused the bot token (check TELEGRAM_BOT_TOKEN)"})
        self.assertEqual(failed[2], {"error": "Telegram rate limit reached: retry after 7 s"})
        self.assertEqual(failed[3], {"error": "Telegram answered 302"})  # no redirect is followed
        self.assertEqual(failed[4], {"error": "Telegram not reachable (ConnectError)"})
        self.assertIn("a line with https://api.telegram.org/bot<token>/getMe", stream.getvalue())
        everything = json.dumps(failed) + stream.getvalue()
        self.assertNotIn(token, everything)
        self.assertNotIn("test-token", everything)

    def test_searxng(self):
        self.check_tools("searxng")
        answers = rpc("searxng", session(("web_search", {"query": "x"}), ("web_search", {"query": "x", "category": "x"}),
                                         ("web_search", {"query": "x", "time_range": "decade"}),
                                         ("web_search", {"query": "x", "language": "--all"}),
                                         ("web_search", {"query": "x", "page": 11}),
                                         ("web_search", {"query": "x"})),
                      env={"SEARXNG_URL": "http://search.example.org"})  # a name: refused before any request
        self.assertIn("plain http only to a private address", result(answers[2])["error"])
        answers = rpc("searxng", session(("web_search", {"query": "x", "category": "x"}),
                                         ("web_search", {"query": "x", "time_range": "decade"}),
                                         ("web_search", {"query": "x", "language": "--all"}),
                                         ("web_search", {"query": "x", "page": 11}),
                                         ("web_search", {"query": "x"})),
                      env={"SEARXNG_URL": "http://127.0.0.1:9"})
        self.assertIn("category", result(answers[2])["error"])
        self.assertIn("time_range", result(answers[3])["error"])
        self.assertIn("language", result(answers[4])["error"])
        self.assertIn("page", result(answers[5])["error"])
        self.assertIn("not reachable", result(answers[6])["error"])
        self.assertIn("SEARXNG_URL is not set", result(rpc("searxng", session(("web_search", {"query": "x"})),
                                                           env={"SEARXNG_URL": ""})[2])["error"])
        module = load("searxng")
        for bad in ("ftp://x", "https://u:p@x.org", "https://x.org/?q=1", "http://search.example.org",
                    "https://x.org/#a", "https://x .org"):
            with self.assertRaises(module.ArgumentError, msg=bad):
                module.instance(bad)
        self.assertEqual(module.instance("https://search.example.org/searx/"), "https://search.example.org/searx")
        self.assertEqual(module.instance("http://192.168.1.20:8888"), "http://192.168.1.20:8888")
        data = json.loads((ROOT / "tests/fixtures/searxng.json").read_text())
        found = module.results_of(data, 10)
        self.assertEqual(found[0], {"title": "Example Domain", "url": "https://example.com/",
                                    "snippet": "This domain is for use in illustrative examples.",
                                    "engines": ["duckduckgo", "brave"]})
        self.assertEqual([r["url"] for r in found], ["https://example.com/", "https://www.iana.org/help/example-domains"])
        self.assertEqual(module.results_of(data, 1), found[:1])
        self.assertEqual(module.extras_of(data), {"suggestions": ["example domain names"],
                                                  "answers": ["An answer", "From an infobox"]})

    def test_gowitness(self):
        """The screenshot server's refusals (before gowitness runs), its address policy, the argument list it
        gives gowitness and the summary of a recorded gowitness result. Needs neither gowitness nor Chromium."""
        import ipaddress
        from unittest import mock
        self.check_tools("gowitness")
        answers = rpc("gowitness", session(
            ("screenshot", {"url": "file:///etc/passwd"}),
            ("screenshot", {"url": "http://127.0.0.1:9/"}),
            ("screenshot", {"url": "http://169.254.169.254/latest/meta-data/"}),
            ("screenshot", {"url": "http://user:pw@example.org/"}),
            ("screenshot", {"url": "javascript:alert(1)"}),
            ("screenshot", {"url": "http://example.org/" + "a" * 2100}),
            ("screenshot", {"url": "https://example.org/", "width": 99999}),
            ("screenshot", {"url": "https://example.org/", "format": "gif"}),
            ("screenshot", {"url": "https://example.org/", "delay": 10, "timeout": 10}),
            ("screenshot_many", {"urls": [f"https://example.org/{i}" for i in range(6)]}),
            ("screenshot_many", {"urls": ["http://8.8.8.8/", "http://[::1]/"]})))  # literals: no name lookup
        errors = [result(answers[index]).get("error", "") for index in range(2, 13)]
        self.assertTrue(all(errors), errors)
        self.assertIn("http or https", errors[0])
        for index in (1, 2, 10):
            self.assertIn("not a public address", errors[index])
        self.assertIn("user name or password", errors[3])
        self.assertIn("http or https", errors[4])
        self.assertIn("at most 2048", errors[5])
        self.assertIn("width", errors[6])
        self.assertIn("png or jpeg", errors[7])
        self.assertIn("delay + 5", errors[8])
        self.assertIn("1 to 5", errors[9])

        module = load("gowitness")
        ip = ipaddress.ip_address
        for address in ("127.0.0.1", "::1", "169.254.169.254", "fe80::1", "0.0.0.0", "224.0.0.1", "192.0.2.1",
                        "10.0.0.1", "192.168.1.1", "100.64.0.1", "fd00::1", "::ffff:10.0.0.1", "64:ff9b::a00:1",
                        "2002:a00:1::1", "64:ff9b::7f00:1"):
            self.assertFalse(module.allowed(ip(address), False), address)
        for address in ("10.0.0.1", "172.16.0.1", "192.168.1.1", "100.64.0.1", "fd00::1", "64:ff9b::a00:1"):
            self.assertTrue(module.allowed(ip(address), True), address)
        for address in ("127.0.0.1", "::1", "169.254.169.254", "fe80::1", "0.0.0.0", "224.0.0.1", "192.0.2.1",
                        "64:ff9b::7f00:1", "64:ff9b::a9fe:a9fe"):
            self.assertFalse(module.allowed(ip(address), True), address)  # never, also with ALLOW_PRIVATE_TARGETS
        for address in ("93.184.215.14", "2606:2800:21f:cb07:6820:80da:af6b:8b2c", "64:ff9b::808:808"):
            self.assertTrue(module.allowed(ip(address), False), address)
        with mock.patch.dict(os.environ, {"ALLOW_PRIVATE_TARGETS": "yes"}):
            self.assertFalse(module.allow_private())  # exactly "1"
        with mock.patch.dict(os.environ, {"ALLOW_PRIVATE_TARGETS": "1"}):
            self.assertTrue(module.allow_private())

        opts = module.options(True, 1280, 720, 2, 30, "png", 80)
        argv = module.command("https://example.org/a b", "/tmp/gowitness-x", opts)
        self.assertEqual(argv[:3], ["/usr/local/bin/gowitness", "scan", "single"])
        self.assertIn("--url=https://example.org/a b", argv)  # one argument, never a shell
        self.assertIn("--chrome-path=/usr/bin/chromium", argv)
        self.assertIn("--screenshot-fullpage", argv)
        self.assertIn("--write-jsonl-file=/tmp/gowitness-x/result.jsonl", argv)
        for flag in ("--write-db", "--chrome-wss-url", "--chrome-user-data-dir", "--javascript", "--chrome-proxy",
                     "--save-content", "--driver=gorod", "--write-stdout", "--chrome-header"):
            self.assertFalse(any(a.startswith(flag) for a in argv), flag)
        self.assertEqual(set(module.environment("/tmp/x")),
                         {"PATH", "HOME", "TMPDIR", "LANG", "XDG_CONFIG_HOME", "XDG_CACHE_HOME"})

        recorded = json.loads((ROOT / "tests/fixtures/gowitness-example.jsonl").read_text().splitlines()[0])
        found = module.summary(recorded)
        self.assertEqual((found["status"], found["title"], found["final_url"]),
                         (200, "Example Domain", "https://example.com/"))
        self.assertEqual(found["technologies"], ["Akamai", "HTTP/3"])
        self.assertNotIn("html", found)
        self.assertNotIn("value", found["cookies"][0])  # names only
        self.assertEqual(found["tls"]["issuer"], "DigiCert Global G3 TLS ECC SHA384 2020 CA1")
        self.assertEqual(found["network"][0]["status"], 200)
        self.assertEqual(found["counts"]["headers"], len(recorded["headers"]))
        png = module.PNG_MAGIC + b"\x00\x00\x00\rIHDR" + (1280).to_bytes(4, "big") + (720).to_bytes(4, "big")
        self.assertEqual(module.png_size(png), (1280, 720))
        self.assertEqual(module.describe(png, "png")["width"], 1280)

    def test_openosint(self):
        """OpenOSINT's tool code behind this repository's server: only the passive tools, arguments refused
        before a request is built, keys in no answer and no log line. Runs where the image's modules are
        (the image, or a venv with servers/openosint/openosint-files.sha256 installed); no network needed."""
        import io
        import logging
        from unittest import mock
        try:
            import openosint  # noqa: F401 - the reviewed modules, installed by the Dockerfile
        except ImportError:
            self.skipTest("OpenOSINT's reviewed modules are not installed (they are in the image)")

        def text(answer):
            return answer["result"]["content"][0]["text"], answer["result"].get("isError", False)

        self.check_tools("openosint")
        key = "ip2l-test-key-not-a-real-one"
        answers = rpc("openosint", session(
            ("generate_dorks", {"target": "example.com"}),
            ("generate_dorks", {"target": "example.com", "json_output": True}),
            ("search_rdap", {"domain": "localhost"}),
            ("search_whois", {"domain": "example.com/path"}),
            ("search_dns", {"domain": "a\x00b.com"}),
            ("search_virustotal", {"target": "https://example.com/"}),
            ("search_virustotal", {"target": "2606:4700::1111"}),
            ("search_ip", {"ip": "169.254.169.254"}),
            ("search_abuseipdb", {"ip": "10.0.0.1"}),
            ("search_github", {"query": "octocat/../x"}),
            ("search_paste", {"query": "two words"}),
            ("search_breach", {"email": "a%2Fb@example.com"}),
            ("search_footprint", {"target": "x", "max_queries": 4}),
            ("search_gdelt_geo", {"query": "x", "timespan": 5}),
            ("search_gdelt_geo", {"query": "x", "bbox": [1, 2, 3]}),
            ("search_breach", {"email": "someone@example.com"}),
            ("search_ip2location", {"ip": "8.8.8.8"}),
            ("search_username", {"username": "x"})),
            env={"OPENOSINT_ALLOW_ACTIVE": "1", "HIBP_API_KEY": "", "IP2LOCATION_API_KEY": key,
                 "OPENOSINT_PROXY_URL": "http://127.0.0.1:9"})
        dorks, failed = text(answers[2])
        self.assertFalse(failed)
        self.assertTrue(dorks.startswith("Google dork URLs for 'example.com':"))
        self.assertIn("https://www.google.com/search?q=%22example.com%22", dorks)
        self.assertEqual(json.loads(text(answers[3])[0])["tool"], "generate_dorks")
        for index, expected in ((4, "a domain name such as example.com"), (5, "a domain name"),
                                (6, "without control characters"), (7, "URL submission is not offered"),
                                (8, "an IPv4 address"), (9, "a public address"), (10, "a public address"),
                                (11, "without / \\ ? # %"), (12, "an e-mail address or username"),
                                (13, "an e-mail address"), (14, "max_queries: an integer from 1 to 3"),
                                (15, "timespan: an integer from 15 to 1440"), (16, "bbox: four numbers")):
            message, failed = text(answers[index])
            self.assertTrue(failed, index)
            self.assertIn(expected, message, index)
        message, failed = text(answers[17])
        self.assertTrue(failed)
        self.assertIn("[key_required] HIBP_API_KEY", message)
        self.assertIn("--env NAME", message)
        self.assertNotIn("web UI", message)
        message, failed = text(answers[18])  # the request fails (no network, or the proxy on port 9)
        self.assertTrue(failed)
        self.assertNotIn(key, message)
        self.assertIn("[redacted]", message)
        self.assertTrue(text(answers[19])[1])  # an active tool is not there, OPENOSINT_ALLOW_ACTIVE or not

        os.environ["OPENOSINT_ALLOW_ACTIVE"] = "1"
        self.addCleanup(os.environ.pop, "OPENOSINT_ALLOW_ACTIVE", None)
        module = load("openosint")
        from openosint import tool_policy
        self.assertNotIn("OPENOSINT_ALLOW_ACTIVE", os.environ)
        os.environ["OPENOSINT_ALLOW_ACTIVE"] = "1"
        self.assertFalse(tool_policy.active_enabled())
        for name in ("search_virustotal_url", "scrape_url", "search_username", "search_email", "search_domain",
                     "search_phone"):
            self.assertFalse(tool_policy.is_tool_enabled(name), name)
        fenced = 'News for \'x\': 1 location(s).\n\n```geojson\n{"type": "FeatureCollection", "features": [{}]}\n```'
        stripped = module._answer("search_gdelt_geo", "x", fenced, False)
        self.assertNotIn("geojson", stripped.replace("geo point", ""))
        self.assertIn("[1 geo point(s)", stripped)
        with self.assertRaises(module.ToolError):
            module._answer("search_ip", "8.8.8.8", "Scan error: ipinfo.io returned HTTP 500.", False)
        long = module._answer("search_dns", "example.com", "x" * (module.MAX_ANSWER + 10), False)
        self.assertTrue(long.endswith("[answer cut at 64 KiB]"))
        with mock.patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_testtokenvalue"}):
            stream = io.StringIO()
            handler = logging.StreamHandler(stream)
            handler.setFormatter(module.RedactingFormatter("%(message)s"))
            logging.getLogger("t").addHandler(handler)
            logging.getLogger("t").propagate = False
            self.addCleanup(logging.getLogger("t").removeHandler, handler)
            logging.getLogger("t").warning("url with ghp_testtokenvalue")
            self.assertEqual(stream.getvalue(), "url with [redacted]\n")
            self.assertEqual(module.redact("Bearer ghp_testtokenvalue"), "Bearer [redacted]")

    def test_youtube(self):
        """The upload server over stdio (tools, refusals before any request, no credentials named), then the whole
        offline suite of tests/test_youtube.py against its fake Google - in CI with the image's own Python and
        libraries, no network."""
        self.check_tools("youtube")
        clean = {"YOUTUBE_CLIENT_ID": "", "YOUTUBE_CLIENT_SECRET": "", "YOUTUBE_REFRESH_TOKEN": "",
                 "YOUTUBE_ALLOW_PUBLIC": ""}
        video = {"title": "x", "made_for_kids": False, "contains_synthetic_media": True}
        answers = rpc("youtube", session(("list_my_videos", {}),
                                         ("upload_video", {"path": "/etc/passwd", **video}),
                                         ("upload_video", {"path": "/upload/v.mp4", "privacy": "public", **video}),
                                         ("upload_video", {"path": "/upload/v.mp4", **video})), env=clean)
        self.assertIn("no YouTube credentials", result(answers[2])["error"])
        self.assertIn("only files under /upload", result(answers[3])["error"])
        self.assertIn("YOUTUBE_ALLOW_PUBLIC=1", result(answers[4])["error"])
        self.assertIn("no YouTube credentials", result(answers[5])["error"])
        sys.path.insert(0, str(ROOT / "tests"))
        import test_youtube
        outcome = unittest.TestResult()
        unittest.defaultTestLoader.loadTestsFromModule(test_youtube).run(outcome)
        problems = [f"{test.id()}: {text[-1500:]}" for test, text in outcome.failures + outcome.errors]
        self.assertEqual(problems, [], "\n".join(problems))
        self.assertEqual(outcome.skipped, [])
        self.assertGreater(outcome.testsRun, 30)


def osint_mcp_installed():
    try:
        return importlib.util.find_spec("osint_mcp") is not None
    except ImportError:
        return False


@unittest.skipUnless(mcp is not None and osint_mcp_installed(),
                     "osint-mcp runs from its own lock (mcp 2.x): inside its image, or after "
                     "pip install --require-hashes -r servers/osint-mcp/requirements.txt")
class OsintMcp(unittest.TestCase):
    """Upstream's osint-mcp behind src/server.py: what is refused before any request, the tightened address check,
    and its parsers against tests/fixtures/osint-mcp.json. No network: CI runs it inside the image with none."""

    def test_osint_mcp(self):
        from unittest import mock
        import socket
        self.check_server()
        module = load("osint-mcp")  # replaces osint_mcp.network.public_ip, as the entrypoint does
        from osint_mcp import investigations, mailsec, network, sources
        self.assertIs(network.public_ip, module.public_ip)
        for private in ("64:ff9b::a00:1", "64:ff9b::7f00:1", "64:ff9b::c0a8:101", "64:ff9b:1::a00:1",
                        "::ffff:10.0.0.1", "2002:a00:1::1", "10.0.0.1", "127.0.0.1", "169.254.169.254", "::1",
                        "100.64.0.1", "224.0.0.1"):
            with self.assertRaises(ValueError, msg=private):
                network.public_ip(private)
        for public in ("64:ff9b::808:808", "8.8.8.8", "2606:4700:4700::1111"):
            self.assertEqual(network.public_ip(public), public)

        async def resolve(answers):
            async def getaddrinfo(self, host, port, **kwargs):
                return [(socket.AF_INET6 if ":" in a else socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, port))
                        for a in answers]
            with mock.patch.object(asyncio.BaseEventLoop, "getaddrinfo", getaddrinfo):
                return await network.resolve_public("site.example.org", 443)
        # a name that resolves to a NAT64 address of a private one is refused, like a private address itself
        with self.assertRaises(ValueError):
            asyncio.run(resolve(["93.184.215.14", "64:ff9b::a00:1"]))
        self.assertEqual(asyncio.run(resolve(["2606:2800:21f:cb07:6820:80da:af6b:8b2c", "93.184.215.14"])),
                         ["93.184.215.14", "2606:2800:21f:cb07:6820:80da:af6b:8b2c"])  # IPv4 first
        for bad in ("http://localhost/", "http://router.local/", "https://u:p@example.org/", "ftp://example.org/",
                    "http://x/", "https://" + "a" * 4100 + ".org/"):
            with self.assertRaises(ValueError, msg=bad[:60]):
                network.normalize_url(bad)

        data = json.loads((ROOT / "tests/fixtures/osint-mcp.json").read_text())
        rdap = sources.parse_rdap_domain(data["rdap_domain"])
        self.assertEqual((rdap["domain"], rdap["registered"], rdap["expires"]),
                         ("example.com", "1995-08-14T04:00:00Z", "2027-08-13T04:00:00Z"))
        self.assertEqual(rdap["nameservers"], ["a.iana-servers.net", "b.iana-servers.net"])
        self.assertEqual((rdap["registrar"], rdap["abuse_email"]),
                         ("RESERVED-Internet Assigned Numbers Authority", "abuse@example.net"))
        # wildcards stripped, names folded, only names under the domain (not example.com.evil.test)
        self.assertEqual(sources.parse_crtsh(data["crtsh"], "example.com"),
                         ["example.com", "mail.example.com", "www.example.com"])
        snapshots = sources.parse_cdx(data["cdx"])
        self.assertEqual(snapshots[0]["archive_url"], "https://web.archive.org/web/20020120142510/http://example.com:80/")

        async def ripestat(client, url, params=None, **kwargs):
            endpoint = url.rsplit("/", 2)[-2]
            return 200, data["ripestat"][endpoint]
        with mock.patch.object(sources, "fetch_json", ripestat):
            info = asyncio.run(sources.asn_info(None, "1.1.1.1", include_prefixes=False))
        self.assertEqual((info["asn"], info["prefix"], info["holder"], info["announced"]),
                         (13335, "1.1.1.0/24", "CLOUDFLARENET - Cloudflare, Inc.", True))

        spf = mailsec.parse_spf(["v=spf1 include:_spf.example.net -all"])
        dmarc = mailsec.parse_dmarc(["v=DMARC1; p=reject; rua=mailto:d@example.com"])
        self.assertEqual(mailsec.grade(spf, dmarc)[0], "A")
        self.assertEqual(mailsec.grade(mailsec.parse_spf(["v=spf1 +all"]), {"present": False})[0], "F")
        # the public suffix list is upstream's bundled snapshot: no fetch, no cache file (read-only root, no network)
        self.assertEqual(investigations.site_domain("shop.example.co.uk"), "example.co.uk")
        page = investigations.parse_page("<title>Shop</title><script>x()</script><a href='/contact'>c</a>"
                                         "<a href='https://other.example.net/terms'>t</a><p>VAT: RO 1234567</p>",
                                         "https://example.com/")
        self.assertEqual(page["legal_links"], ["https://example.com/contact"])  # same origin only
        self.assertEqual(page["external_link_domains"], ["other.example.net"])
        self.assertEqual(page["company_identifiers"], [{"label": "VAT", "value": "RO 1234567"}])

    def check_server(self):
        expected = json.loads((ROOT / "servers/osint-mcp/tools.json").read_text())["tools"]
        answers = rpc("osint-mcp", session(
            ("http_headers", {"url": "http://169.254.169.254/latest/meta-data/"}),
            ("http_headers", {"url": "http://[64:ff9b::a00:1]/"}),  # upstream alone would connect
            ("tls_certificate", {"host": "127.0.0.1", "port": 22}),
            ("dns_lookup", {"domain": "example.com", "nameserver": "10.0.0.1"}),
            ("http_headers", {"url": "http://router.local/"}),
            ("email_security", {"domain": "example.com", "dkim_selectors": ["../x"]}),
            ("recon_batch", {"domains": [f"d{i}.example" for i in range(11)]}),
            ("tls_certificate", {"host": "example.com", "port": 70000})),
            env={"OSINT_MCP_CACHE_PATH": ":memory:"})
        self.assertEqual(sorted(t["name"] for t in answers[1]["result"]["tools"]), expected)
        texts = {index: answers[index]["result"]["content"][0]["text"] for index in range(2, 10)}
        for index, text in texts.items():
            self.assertTrue(answers[index]["result"].get("isError"), text)
        for index in (2, 3, 4, 5):
            self.assertIn("private, local and reserved addresses are not supported", texts[index])
        self.assertIn("local hostnames are not supported", texts[6])
        self.assertIn("DKIM selectors", texts[7])
        self.assertIn("at most 10 items", texts[8])
        self.assertIn("65535", texts[9])


    def test_signal(self):
        """In the image (CI runs it there): the read-only tools and refused calls; signal-cli and its JVM under
        the hardened flags, with the native libraries out of their jars; and libsignal loading from there
        (signal-cli link makes the device's temporary key with it before it connects - which fails here)."""
        try:
            import signal_mcp  # noqa: F401 - signal-mcp's modules, as the image installs them
        except ImportError:
            self.skipTest("signal-mcp's modules are not installed (the image has them; tests/test_signal.py "
                          "covers the server natively where they are)")
        self.check_tools("signal")
        answers = rpc("signal", session(("get_unread", {"limit": 0}), ("get_status", {}), ("list_groups", {})))
        self.assertIn("limit: an integer from 1 to 200", result(answers[2])["error"])
        self.assertFalse(result(answers[3])["linked"])
        self.assertIn("no Signal account", result(answers[4])["error"])
        home = Path("/opt/signal-cli")
        if not (home / "classpath").is_file():
            return  # natively: no signal-cli here
        import tempfile
        import zipfile
        from unittest import mock
        with mock.patch.dict(os.environ):  # the server points HOME at /data when it is imported
            module = load("signal")
        self.assertEqual(sorted(p.name for p in (home / "native").iterdir()), ["libsignal_jni.so", "libsqlitejdbc.so"])
        for jar, prefix in (("libsignal-client-0.103.0.jar", "libsignal_jni"), ("sqlite-jdbc-3.53.4.0.jar",
                                                                              "org/sqlite/native/")):
            with zipfile.ZipFile(home / "lib" / jar) as archive:
                self.assertFalse([n for n in archive.namelist() if n.startswith(prefix)], jar)
        version = subprocess.run(module.signal_cli_argv("--version"), capture_output=True, text=True, timeout=180)
        self.assertIn("signal-cli 0.14.9", version.stdout + version.stderr)
        with tempfile.TemporaryDirectory(dir="/tmp") as folder:
            argv = module.signal_cli_argv("link", "-n", "ci")
            argv[argv.index("--config") + 1] = folder
            linked = subprocess.run(argv, capture_output=True, text=True, timeout=180)
        text = linked.stdout + linked.stderr
        self.assertNotRegex(text, r"UnsatisfiedLinkError|ExceptionInInitializerError|signal_jni|NoClassDefFoundError",
                            text[-2000:])
        self.assertNotEqual(linked.returncode, 0, "no network here: linking cannot finish")


if __name__ == "__main__":
    unittest.main()
