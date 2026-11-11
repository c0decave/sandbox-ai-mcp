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


if __name__ == "__main__":
    unittest.main()
