"""The sandbox-ai-mcp servers of this repository, natively: MCP handshake, tool list, argument
checks and the parsers against recorded answers (no network needed). The live calls against the
real services are in each server's smoke.json, run by CI with the catalog's network."""
import asyncio
import contextlib
import errno
import http.server
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

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


#: What the stand-in resolver answers (tests of the lookups behind Tor): a record of each type, for any name.
DNS_RECORDS = {"A": ["93.184.215.14"], "AAAA": ["2606:2800:21f:cb07:6820:80da:af6b:8b2c"], "MX": ["10 mail.example.com."],
               "NS": ["a.iana-servers.net."], "TXT": ['"v=spf1 -all"'], "CAA": ['0 issue "letsencrypt.org"'],
               "SOA": ["ns.icann.org. noc.dns.icann.org. 2026111501 7200 3600 1209600 3600"],
               "PTR": ["one.one.one.one."]}


def dns_answer(request):
    """The answer to the DNS message REQUEST from DNS_RECORDS (no record of the type asked: an empty answer)."""
    import dns.message
    import dns.rdatatype
    import dns.rrset
    response = dns.message.make_response(request)
    question = request.question[0]
    kind = dns.rdatatype.to_text(question.rdtype)
    if kind in DNS_RECORDS:  # through find_rrset, which keeps the message's index of its records
        records = dns.rrset.from_text(question.name, 300, "IN", kind, *DNS_RECORDS[kind])
        response.find_rrset(response.answer, records.name, records.rdclass, records.rdtype, create=True).update(records)
    return response


def free_port(host="127.0.0.1") -> int:
    with socket.socket() as probe:
        probe.bind((host, 0))
        return probe.getsockname()[1]


@contextlib.contextmanager
def local_http(respond, host="127.0.0.1"):
    """An HTTP server on HOST (a port of its own, yielded): RESPOND(handler) answers each GET, handler.answer(status,
    content type, body, headers) sends an answer."""
    class Handler(http.server.BaseHTTPRequestHandler):
        def answer(self, status, kind, body, headers=None):
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802 - the name http.server calls
            respond(self)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer((host, 0), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()


@contextlib.contextmanager
def local_reset(host="127.0.0.2"):
    """A server on HOST that takes each connection and resets it at once (RST); its port is yielded."""
    listener = socket.socket()
    listener.bind((host, 0))
    listener.listen(8)

    def run():
        while True:
            try:
                connection, _ = listener.accept()
            except OSError:
                return
            connection.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            connection.close()

    threading.Thread(target=run, daemon=True).start()
    try:
        yield listener.getsockname()[1]
    finally:
        listener.close()


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

    def test_agentql(self):
        """agentql (more in tests/test_agentql.py): its tool, the key and the URL checks, no network."""
        self.check_tools("agentql")
        answers = rpc("agentql", session(("extract-web-data", {"url": "https://example.com/", "prompt": "x"}),
                                         ("extract-web-data", {"url": "http://10.0.0.1/", "prompt": "x"}),
                                         ("extract-web-data", {"url": "https://example.com/", "prompt": ""})),
                      env={"AGENTQL_API_KEY": ""})
        self.assertIn("AGENTQL_API_KEY", result(answers[2])["error"])
        self.assertIn("a public address", result(answers[3])["error"])
        self.assertIn("prompt", result(answers[4])["error"])
        module = load("agentql")
        self.assertEqual(module.bounded({"url": "u", "data": {"a": 1}}), {"url": "u", "data": {"a": 1}})

    def test_osv(self):
        """osv (more in tests/test_osv.py): its tools, refused arguments and the short form, no network."""
        self.check_tools("osv")
        answers = rpc("osv", session(("get_vulnerability", {"id": "../query"}),
                                     ("query_vulnerability", {"package_name": "jinja2"})))
        self.assertIn("id: an OSV id", result(answers[2])["error"])
        self.assertIn("go together", result(answers[3])["error"])
        module = load("osv")
        vuln = json.loads((ROOT / "tests/fixtures/osv.json").read_text())["vuln"]
        short = module.summary_of(vuln, {"package": {"name": "Jinja2", "ecosystem": "PyPI"}})
        self.assertEqual((short["id"], short["fixed_in"]), ("GHSA-462w-v97r-4m45", ["2.10.1"]))

    def test_wikipedia(self):
        """wikipedia (more in tests/test_wikipedia.py): its tools, refused arguments, the section parser."""
        self.check_tools("wikipedia")
        answers = rpc("wikipedia", session(("get_summary", {"title": "x", "lang": "en.evil.example"})))
        self.assertIn("lang: one of", result(answers[2])["error"])
        module = load("wikipedia")
        names = [name for _level, name, _s, _e in module._sections("Intro\n== A ==\nx\n=== B ===\ny\n== C ==\n")]
        self.assertEqual(names, ["(introduction)", "A", "B", "C"])

    def test_arxiv(self):
        """arxiv (more in tests/test_arxiv.py): its tools, refused arguments, ids and the HTML text."""
        self.check_tools("arxiv")
        answers = rpc("arxiv", session(("get_paper", {"id": "../../etc/passwd"})))
        self.assertIn("id: an arXiv id", result(answers[2])["error"])
        module = load("arxiv")
        self.assertEqual(module.paper_id("https://arxiv.org/abs/1706.03762v7"), "1706.03762v7")
        title, text = module.html_text('<title>T</title><nav>x</nav><h2>1 Intro</h2><p>a <math alttext="x^2">'
                                       '<mi>x</mi></math> b</p>')
        self.assertEqual((title, text), ("T", "## 1 Intro\n\na $x^2$ b"))

    def test_shodan(self):
        """shodan (more in tests/test_shodan.py): its tools, the missing key, refused arguments, the CVE form."""
        self.check_tools("shodan")
        answers = rpc("shodan", session(("ip_lookup", {"ip": "8.8.8.8"}), ("cve_lookup", {"cve": "../x"})),
                      env={"SHODAN_API_KEY": ""})
        self.assertIn("no Shodan API key", result(answers[2])["error"])
        self.assertIn("cve: a CVE id", result(answers[3])["error"])
        module = load("shodan")
        entry = module._cve_entry({"cve_id": "CVE-2021-44228", "cvss_v3": 10.0, "kev": True}, full=False)
        self.assertEqual((entry["cvss_v3"]["severity"], entry["known_exploited"]), ("critical", True))

    def test_calculator(self):
        """calculator (more in tests/test_calculator.py): its tools, exact results, a hostile expression."""
        self.check_tools("calculator")
        answers = rpc("calculator", session(("calculate", {"expression": "0.1 + 0.2"}),
                                            ("calculate", {"expression": "9**9**9"})))
        self.assertEqual(json.loads(answers[2]["result"]["content"][0]["text"])["result"], "0.3")
        self.assertIn("too large", result(answers[3])["error"])
        module = load("calculator")
        self.assertEqual(module.date_add("2024-01-31", months=1)["result"], "2024-02-29")

    def test_youtube_transcript(self):
        """youtube-transcript (more in tests/test_youtube_transcript.py): its tools, refused arguments and the whole
        flow against a stand-in for www.youtube.com on loopback, with the image's own library; no network."""
        try:
            import youtube_transcript_api  # noqa: F401 - in the image, or from servers/youtube-transcript's lock
        except ImportError:
            self.skipTest("youtube-transcript-api is not installed (servers/youtube-transcript/requirements.txt)")
        from test_youtube_transcript import VID, StandIn
        self.check_tools("youtube-transcript")
        answers = rpc("youtube-transcript", session(("get_transcript", {"url": "https://evil.example/?v=" + VID})))
        self.assertIn("youtube.com or youtu.be", result(answers[2])["error"])
        module = load("youtube-transcript")
        StandIn(self)
        self.assertEqual(module.get_transcript(VID)["transcript"].split("\n")[0], "Hello & welcome")
        self.assertEqual(module.get_video_info(VID)["title"], "A song")

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

    def web_fetch_on_loopback(self, names, env=None, timeout=None):
        """web-fetch loaded with loopback taken as public, the names of NAMES resolved by a stand-in (NAMES maps a
        name to its answer without a family given, a list of addresses; asked for IPv4 only, the stand-in answers
        127.0.0.1); returns (module, the families asked for per name)."""
        if sys.platform != "linux":
            self.skipTest("needs Linux's loopback range (127.0.0.2)")
        module = load("web-fetch")
        module.public = lambda address: address.is_loopback  # only what the test serves; 10.0.0.1 stays refused
        if timeout is not None:
            module.TIMEOUT = timeout
        asked, real = [], socket.getaddrinfo

        def getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
            host = host.decode() if isinstance(host, bytes) else host
            if host not in names:
                return real(host, port, family, type, proto, flags)
            asked.append((host, int(family)))
            addresses = ["127.0.0.1"] if family == socket.AF_INET else names[host]
            return [(socket.AF_INET6 if ":" in a else socket.AF_INET, socket.SOCK_STREAM, 6, "",
                     (a, int(port), 0, 0) if ":" in a else (a, int(port))) for a in addresses]

        patches = [mock.patch("socket.getaddrinfo", getaddrinfo),
                   mock.patch.dict(os.environ, env or {})]
        for name in ("SANDBOX_AI_RUN", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy",
                     "all_proxy"):
            if name not in (env or {}):
                patches.append(mock.patch.dict(os.environ, {name: ""}))
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        return module, asked

    def test_web_fetch_retries_over_ipv4(self):
        """A name with IPv6 and IPv4 addresses whose connection failed is tried once more over IPv4 only (an IPv6
        path that takes the connection and then resets it is not left by httpx's async client on its own)."""
        with local_http(lambda handler: handler.answer(200, "text/plain", b"hello over IPv4")) as port:
            module, asked = self.web_fetch_on_loopback({"dual.example.org": ["::1", "127.0.0.2"]})
            page = asyncio.run(module.fetch_page(f"http://dual.example.org:{port}/"))
        self.assertEqual(page.get("text"), "hello over IPv4", page)
        self.assertIn(("dual.example.org", int(socket.AF_INET)), asked)

    def test_web_fetch_ipv4_retry_keeps_the_checks(self):
        """The retry goes through the same checks: a redirect to a private address is refused there too."""
        with local_http(lambda handler: handler.answer(302, "text/plain", b"", {"Location": "http://10.0.0.1/"})) \
                as port:
            module, asked = self.web_fetch_on_loopback({"dual.example.org": ["::1", "127.0.0.2"]})
            page = asyncio.run(module.fetch_page(f"http://dual.example.org:{port}/"))
        self.assertIn("not a public address", page.get("error", ""), page)
        self.assertIn(("dual.example.org", int(socket.AF_INET)), asked)

    def test_web_fetch_says_why_a_connection_failed(self):
        """The error names what happened (refused, reset, no answer within the time limit) and what to do next;
        a name with only IPv4 addresses is not tried twice; inside a sandbox-ai sandbox it says how to allow a host."""
        port = free_port()
        module, asked = self.web_fetch_on_loopback({"v4.example.org": ["127.0.0.2"]})
        error = asyncio.run(module.fetch_page(f"http://v4.example.org:{port}/"))["error"]
        self.assertIn("not reachable: the host refused the connection", error)
        self.assertIn("another source", error)
        self.assertNotIn("IPv4 only", error)
        self.assertNotIn(("v4.example.org", int(socket.AF_INET)), asked)

        with local_reset() as port:
            error = asyncio.run(module.fetch_page(f"http://v4.example.org:{port}/"))["error"]
        self.assertIn("connection was reset", error)
        self.assertNotIn("sandbox-ai", error)
        module, _ = self.web_fetch_on_loopback({"v4.example.org": ["127.0.0.2"]}, env={"SANDBOX_AI_RUN": "calm-otter"})
        with local_reset() as port:
            error = asyncio.run(module.fetch_page(f"http://v4.example.org:{port}/"))["error"]
        self.assertIn(f"sandbox-ai net allow calm-otter --allow-tcp ADDRESS:{port} with the address v4.example.org "
                      "resolves to", error)
        reset = module.httpx.ConnectError("")
        reset.__cause__ = ConnectionResetError(errno.ECONNRESET, "Connection reset by peer")
        error = module.not_reachable("https://v4.example.org/", reset, reset)
        self.assertIn("reset during the TLS handshake", error)
        self.assertIn("the same when tried again over IPv4 only", error)
        self.assertIn("sandbox-ai net allow calm-otter --allow-host v4.example.org;", error)

        module, _ = self.web_fetch_on_loopback({"v4.example.org": ["127.0.0.2"]}, timeout=0.5)
        with local_http(lambda handler: time.sleep(3), host="127.0.0.2") as port:
            error = asyncio.run(module.fetch_page(f"http://v4.example.org:{port}/"))["error"]
        self.assertIn("no answer within 0.5 s", error)
        self.assertNotRegex(error, r"not reachable: ?$")

    def test_web_fetch_says_a_missing_page_is_missing(self):
        """HTTP 404 and 410 say that the page does not exist (a local model fetched the same URL again and again)."""
        module, _ = self.web_fetch_on_loopback({"v4.example.org": ["127.0.0.1"]})
        with local_http(lambda handler: handler.answer(404, "text/html", b"<p>gone</p>")) as port:
            error = asyncio.run(module.fetch_page(f"http://v4.example.org:{port}/old"))["error"]
        self.assertIn("answered HTTP 404: the page does not exist; do not fetch this URL again", error)

    def check_tools_only(self, name, untrusted=True):
        """NAME advertises tools only (no resources or prompts: it publishes none, and local models took the
        resource tools their agents then offer for the way to the server's tools); UNTRUSTED: its instructions
        say that what it returns is third-party data, never instructions."""
        answers = rpc(name, session())
        capabilities = answers[0]["result"]["capabilities"]
        self.assertIn("tools", capabilities)
        self.assertNotIn("resources", capabilities)
        self.assertNotIn("prompts", capabilities)
        if untrusted:
            self.assertRegex(answers[0]["result"].get("instructions") or "", r"never (as )?instructions")
        return answers

    def test_duckduckgo_checks_and_bounds(self):
        """A region with a line break after it is refused (re.match took "de-de\\n"); titles and snippets are
        bounded; a connection that fails says how, also when the exception has no text."""
        module = load("duckduckgo")
        error = asyncio.run(module.web_search("x", region="de-de\n"))["error"]
        self.assertIn("region", error)
        page = ('<div class="result"><a class="result__a" href="https://example.com/">' + "T" * 5000 + '</a>'
                '<a class="result__snippet">' + "s " * 50000 + "</a></div>")
        found = module.parse_results(page, 10)
        self.assertLessEqual(len(found[0]["title"]), 300)
        self.assertLessEqual(len(found[0]["snippet"]), 1000)
        with local_reset() as port:
            module.ENDPOINT = f"http://127.0.0.2:{port}/html/"
            error = asyncio.run(module.web_search("x"))["error"]
        self.assertRegex(error, r"DuckDuckGo not reachable \((ReadError|RemoteProtocolError|ConnectError)")

    def test_brave_search_checks_and_bounds(self):
        """A country with a line break after it is refused; Brave's <strong> highlighting and HTML entities are
        turned into text; titles and descriptions are bounded, a result with an over-long URL left out; a failed
        connection says how."""
        module = load("brave-search")
        with mock.patch.dict(os.environ, {"BRAVE_API_KEY": "test-key-1234"}):
            error = asyncio.run(module.web_search("x", country="de\n"))["error"]
        self.assertIn("country", error)
        data = {"web": {"results": [{"title": "too long", "url": "https://example.com/" + "x" * 5000},
                                    {"title": "A &amp; <strong>B</strong>", "url": "https://example.com/",
                                     "description": "The <strong>example</strong> " + "d" * 5000}]},
                "results": [{"title": "N" * 1000, "url": "https://example.org/", "description": "<b>n</b>",
                             "age": "2 days", "meta_url": {"hostname": "example.org"}}]}
        web = module.web_results(data)[0]
        self.assertEqual(web["title"], "A & B")
        self.assertTrue(web["description"].startswith("The example ddd"))
        self.assertLessEqual(len(web["description"]), 1000)
        self.assertEqual(len(module.web_results(data)), 1)  # a URL of more than 2000 characters (cut, it is wrong)
        news = module.news_results(data)[0]
        self.assertLessEqual(len(news["title"]), 300)
        self.assertEqual(news["description"], "n")
        with mock.patch.dict(os.environ, {"BRAVE_API_KEY": "test-key-1234"}), local_reset() as port:
            module.API = f"http://127.0.0.2:{port}/res/v1/"
            error = asyncio.run(module.web_search("x"))["error"]
        self.assertRegex(error, r"Brave Search not reachable \((ReadError|RemoteProtocolError|ConnectError)")
        self.assertNotIn("test-key-1234", error)

    def test_searxng_checks_and_bounds(self):
        """A language with a line break after it is refused; fifty results with long snippets still fit what clients
        show a model (about 25,000 characters), the ones left out counted; a result whose URL is over-long is left
        out (cut, it would be wrong)."""
        module = load("searxng")
        with mock.patch.dict(os.environ, {"SEARXNG_URL": "http://127.0.0.1:9"}):
            error = asyncio.run(module.web_search("x", language="de\n"))["error"]
        self.assertIn("language", error)
        data = {"results": [{"title": f"Result {n} " + "t" * 400, "url": f"https://example.com/{n}/" + "u" * 1500,
                             "content": "c " * 1000, "engines": ["a", "b"]} for n in range(50)],
                "suggestions": ["s" * 400] * 20, "answers": ["a" * 600] * 20}
        found = module.results_of(data, 50)
        answer = {"query": "x", "results": found, "count": len(found), **module.extras_of(data)}
        self.assertLessEqual(len(json.dumps(answer, indent=2)), 25_000)
        self.assertGreater(len(found), 5)
        self.assertEqual(module.omitted(data, found, 50), 50 - len(found))

    def test_duckduckgo_and_brave_ask_their_endpoints(self):
        """The whole way through a stand-in of each service on loopback: DuckDuckGo gets one POST with the query and
        the region, Brave one GET with the key in its header (never in an answer); the recorded answers come back."""
        import urllib.parse as parse
        seen = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def reply(self, kind, body):
                self.send_response(200)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):  # noqa: N802
                form = self.rfile.read(int(self.headers["Content-Length"])).decode()
                seen.append(("POST", self.path, parse.parse_qs(form)))
                self.reply("text/html", (ROOT / "tests/fixtures/duckduckgo.html").read_bytes())

            def do_GET(self):  # noqa: N802
                seen.append(("GET", self.path, self.headers.get("X-Subscription-Token")))
                self.reply("application/json", (ROOT / "tests/fixtures/brave-web.json").read_bytes())

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        port = server.server_address[1]
        duckduckgo = load("duckduckgo")
        duckduckgo.ENDPOINT = f"http://127.0.0.1:{port}/html/"
        found = asyncio.run(duckduckgo.web_search("example domain", max_results=5, region="de-de"))
        self.assertEqual(found["results"][0]["url"], "https://example.com/")
        self.assertEqual(seen[0], ("POST", "/html/", {"q": ["example domain"], "kl": ["de-de"]}))
        brave = load("brave-search")
        brave.API = f"http://127.0.0.1:{port}/res/v1/"
        with mock.patch.dict(os.environ, {"BRAVE_API_KEY": "test-key-1234"}):
            found = asyncio.run(brave.web_search("example", count=3, country="de", freshness="pw"))
        self.assertEqual(found["results"], [{"title": "Example Domain", "url": "https://example.com/",
                                             "description": "Example description"}])
        method, path, key = seen[1]
        self.assertEqual((method, key), ("GET", "test-key-1234"))
        self.assertEqual(parse.parse_qs(path.partition("?")[2]),
                         {"q": ["example"], "count": ["3"], "offset": ["0"], "country": ["DE"], "freshness": ["pw"]})
        self.assertNotIn("test-key-1234", json.dumps(found))

    def test_searxng_asks_its_instance(self):
        """The whole way through an instance (a stand-in on loopback): one GET of /search with the arguments, the
        recorded answer read back; a redirect is not followed."""
        import urllib.parse as parse
        asked = []
        recorded = (ROOT / "tests/fixtures/searxng.json").read_bytes()

        def respond(handler):
            asked.append(handler.path)
            if "redirect" in handler.path:
                return handler.answer(302, "text/plain", b"", {"Location": "http://10.0.0.1/"})
            handler.answer(200, "application/json", recorded)
        with local_http(respond) as port:
            answers = rpc("searxng", session(("web_search", {"query": "example domain", "category": "news",
                                                             "language": "de", "time_range": "week", "page": 2}),
                                             ("web_search", {"query": "redirect"})),
                          env={"SEARXNG_URL": f"http://127.0.0.1:{port}/searx/"})
        found = result(answers[2])
        self.assertEqual([r["url"] for r in found["results"]],
                         ["https://example.com/", "https://www.iana.org/help/example-domains"])
        path, _, query = asked[0].partition("?")
        self.assertEqual(path, "/searx/search")
        self.assertEqual(parse.parse_qs(query), {"q": ["example domain"], "format": ["json"], "categories": ["news"],
                                                 "language": ["de"], "pageno": ["2"], "safesearch": ["1"],
                                                 "time_range": ["week"]})
        self.assertEqual(result(answers[3]), {"error": "SearXNG answered HTTP 302"})
        self.assertEqual(len(asked), 2)

    def test_web_fetch_offers_tools_only(self):
        self.check_tools_only("web-fetch")

    def test_duckduckgo_offers_tools_only(self):
        self.check_tools_only("duckduckgo")

    def test_brave_search_offers_tools_only(self):
        self.check_tools_only("brave-search")

    def test_searxng_offers_tools_only(self):
        self.check_tools_only("searxng")

    def test_youtube_offers_tools_only(self):
        self.check_tools_only("youtube", untrusted=False)

    def test_openosint_offers_tools_only(self):
        try:
            import openosint  # noqa: F401 - the reviewed modules, installed by the Dockerfile
        except ImportError:
            self.skipTest("OpenOSINT's reviewed modules are not installed (they are in the image)")
        self.check_tools_only("openosint")

    def test_web_fetch_connects_only_to_the_address_it_checked(self):
        """DNS rebinding: a name that resolves to a public address for the check and to another one a moment later,
        when the connection is made, must not reach that other address. The connection is made to an address
        checked when it is made (here 127.0.0.1 stands for a public address; 127.0.0.2 for the local network)."""
        import ipaddress
        with local_http(lambda handler: handler.answer(200, "text/plain", b"secret of the local network"),
                        host="127.0.0.2") as port:
            module, _ = self.web_fetch_on_loopback({"rebind.example.org": ["127.0.0.1"]})
            module.public = lambda address: address == ipaddress.ip_address("127.0.0.1")
            answers = iter([["127.0.0.1"], ["127.0.0.1"]])  # fetch_page's check, fetch_once's check

            def getaddrinfo(host, port_, family=0, type=0, proto=0, flags=0):
                addresses = next(answers, ["127.0.0.2"])  # the checks' lookups public, every later one not
                return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, int(port_))) for a in addresses]

            with mock.patch("socket.getaddrinfo", getaddrinfo):
                page = asyncio.run(module.fetch_page(f"http://rebind.example.org:{port}/"))
        self.assertNotIn("secret", json.dumps(page))
        self.assertIn("not a public address", page.get("error", ""), page)

    def test_web_fetch_reads_a_page_whose_head_is_not_closed(self):
        """HTML lets </head> out (minified pages do): the body's text must not be dropped with the head."""
        module = load("web-fetch")
        page = module.page_text("<html><head><title>T</title><meta charset=utf-8><body><p>Hello</p></body></html>",
                                "https://example.org/")
        self.assertEqual((page["title"], page["text"]), ("T", "Hello"))
        page = module.page_text("<head><title>T</title><link rel=x href=/a><p>Hi <a href=/b>b</a>",
                                "https://example.org/")
        self.assertEqual((page["title"], page["text"], page["links"]), ("T", "Hi b", ["https://example.org/b"]))
        page = module.page_text("<title>Page</title><body><svg><title>icon</title></svg><p>x</p>", "https://e.org/")
        self.assertEqual((page["title"], page["text"]), ("Page", "x"))  # an SVG's title is not the page's

    def test_web_fetch_parts_fit_what_clients_show(self):
        """Claude Code, Qwen Code and Hermes show the model only a preview of a tool result much above 25,000
        characters: a part is at most 24,000 characters and 400 lines with text (blank lines between blocks not
        counted) whatever max_characters says, links and title are bounded, and next_start goes on where a part ended (the parts together are the whole text)."""
        lines = [f"line {number} w" + "w" * (number % 120) for number in range(3000)]
        body = ("<html><head><title>" + "T" * 100_000 + "</title></head><body>"
                + "".join(f"<p>{line}</p>" for line in lines)
                + "".join(f"<a href='/{number}/{'x' * 3000 if number % 7 == 0 else 'y'}'>l</a>" for number in range(600))
                + "</body></html>").encode()
        with local_http(lambda handler: handler.answer(200, "text/html", body)) as port:
            module, _ = self.web_fetch_on_loopback({"big.example.org": ["127.0.0.1"]})
            url = f"http://big.example.org:{port}/"
            parts, start = [], 0
            while start is not None:
                page = asyncio.run(module.fetch_page(url, max_characters=100000, start=start, links=True))
                self.assertNotIn("error", page)
                self.assertLessEqual(len(json.dumps(page, ensure_ascii=False, indent=2)), 25_000)
                self.assertLessEqual(len(page["text"]), 24_000)
                self.assertLessEqual(len([line for line in page["text"].splitlines() if line.strip()]), 400)
                self.assertLessEqual(len(page["title"]), 300)
                self.assertTrue(all(len(link) <= 500 for link in page["links"]))
                parts.append(page["text"])
                start = page.get("next_start")
                self.assertEqual(page["more"], start is not None)
        whole = module.page_text(body.decode(), url)["text"]
        self.assertTrue(whole.startswith("\n\n".join(lines)))  # a blank line between paragraphs
        self.assertEqual("".join(parts), whole)
        self.assertEqual(len(whole), page["total_characters"])
        self.assertGreater(len(parts), 3)

    def test_web_fetch_decodes_the_page_in_its_charset(self):
        """A page in ISO-8859-1 or windows-1252 (the Content-Type's charset, or a <meta charset> without one) is text,
        not replacement characters."""
        latin = "<html><body><p>Grüße aus Köln</p></body></html>".encode("iso-8859-1")
        meta = '<html><head><meta charset="windows-1252"></head><body><p>“Grüße”</p></body></html>'.encode("cp1252")
        module, _ = self.web_fetch_on_loopback({"old.example.org": ["127.0.0.1"]})
        with local_http(lambda handler: handler.answer(200, "text/html; charset=ISO-8859-1", latin)) as port:
            page = asyncio.run(module.fetch_page(f"http://old.example.org:{port}/"))
        self.assertEqual(page.get("text"), "Grüße aus Köln", page)
        with local_http(lambda handler: handler.answer(200, "text/html", meta)) as port:
            page = asyncio.run(module.fetch_page(f"http://old.example.org:{port}/"))
        self.assertEqual(page.get("text"), "“Grüße”", page)

    def test_web_fetch_gives_up_after_its_deadline(self):
        """A host that sends a byte now and then (within each read's time limit) cannot keep a call open for ever:
        the whole fetch has a deadline, and the error says so."""
        def drip(handler):
            handler.send_response(200)
            handler.send_header("Content-Type", "text/plain")
            handler.end_headers()
            for _ in range(40):
                try:
                    handler.wfile.write(b"x")
                    handler.wfile.flush()
                except OSError:
                    return
                time.sleep(0.1)

        module, _ = self.web_fetch_on_loopback({"slow.example.org": ["127.0.0.1"]}, timeout=1)
        module.DEADLINE = 1.5
        with local_http(drip) as port:
            began = time.monotonic()
            page = asyncio.run(module.fetch_page(f"http://slow.example.org:{port}/"))
        self.assertLess(time.monotonic() - began, 3.5)
        self.assertIn("no complete answer within 1.5 s", page.get("error", ""), page)

    def test_web_fetch_answers_a_malformed_url_with_an_error(self):
        module = load("web-fetch")
        for url in ("http://[::1", "http://example.org:99999/", "http://exa­mple..org/"):
            page = asyncio.run(module.fetch_page(url))
            self.assertIn("error", page, url)

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
        long = module._answer("search_dns", "example.com", "x" * 100_000, False)
        self.assertLessEqual(len(long), 24_000)  # clients show a model only a preview of a larger tool result
        self.assertTrue(long.endswith("[answer cut at 24,000 characters]"))
        cut_json = module._answer("search_dns", "example.com", "line of text\n" * 10_000, True)
        self.assertLessEqual(len(cut_json), 24_000)
        self.assertEqual(json.loads(cut_json)["tool"], "search_dns")
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

    def test_openosint_dns_over_tcp_behind_tor(self):
        """Behind sandbox-ai's Tor profile (SANDBOX_AI_TOR=1) no UDP passes, and tor's DNSPort, where port 53 is sent,
        answers A, AAAA and PTR only: search_dns got no MX, NS, TXT, SOA or DMARC. There every lookup goes over TCP -
        through tor's TransPort and an exit - to public resolvers (TOR_RESOLVERS), with longer timeouts; without Tor
        OpenOSINT's resolver is unchanged. No network: the queries are answered here."""
        from unittest import mock
        try:
            import dns.query
            import dns.resolver
            from openosint.tools import search_dns
        except ImportError:
            self.skipTest("OpenOSINT's reviewed modules are not installed (they are in the image)")
        original = dns.resolver.Resolver
        with mock.patch.dict(os.environ):
            os.environ.pop("SANDBOX_AI_TOR", None)
            load("openosint")
            self.assertIs(dns.resolver.Resolver, original)
        asked = []

        def tcp(request, where, timeout=None, port=53, *args, **kwargs):
            asked.append(("tcp", where, port, timeout))
            return dns_answer(request)

        def udp(request, where, *args, **kwargs):
            asked.append(("udp", where))
            raise OSError("no UDP behind Tor")

        with mock.patch.dict(os.environ, {"SANDBOX_AI_TOR": "1"}), \
                mock.patch.object(dns.resolver, "Resolver", original), \
                mock.patch.object(dns.query, "tcp", tcp), mock.patch.object(dns.query, "udp", udp):
            module = load("openosint")
            self.assertIs(dns.resolver.Resolver, module.TorResolver)
            found = asyncio.run(search_dns.collect_dns_records("example.com", 10))
            text = asyncio.run(search_dns.run_dns_osint("example.com", timeout_seconds=10))
            resolver = dns.resolver.Resolver()
            resolver.timeout, resolver.lifetime = 2, 5.0  # OpenOSINT sets its own: Tor's are the least
            self.assertEqual((resolver.timeout, resolver.lifetime), (module.TOR_DNS_TIMEOUT, module.TOR_DNS_LIFETIME))
            self.assertEqual(resolver.nameservers, list(module.TOR_RESOLVERS))
        self.assertIs(dns.resolver.Resolver, original)
        self.assertEqual((found.mx, found.ns, found.txt, found.dmarc),
                         (DNS_RECORDS["MX"], DNS_RECORDS["NS"], DNS_RECORDS["TXT"], DNS_RECORDS["TXT"]))
        self.assertEqual(found.soa, DNS_RECORDS["SOA"])
        self.assertIn("mail.example.com", text)
        self.assertGreater(len(asked), 8)
        self.assertEqual({(kind, where in module.TOR_RESOLVERS, port) for kind, where, port, _ in asked},
                         {("tcp", True, 53)})
        self.assertTrue(all(timeout > 5 for *_, timeout in asked), asked)  # Tor's timeout, not OpenOSINT's 5 s

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

    def offline_suite(self, module_name, minimum):
        """The offline suite of tests/MODULE_NAME.py: no failure; inside the image (CI) nothing skipped either."""
        sys.path.insert(0, str(ROOT / "tests"))
        module = __import__(module_name)
        outcome = unittest.TestResult()
        unittest.defaultTestLoader.loadTestsFromModule(module).run(outcome)
        problems = [f"{test.id()}: {text[-1500:]}" for test, text in outcome.failures + outcome.errors]
        self.assertEqual(problems, [], "\n".join(problems))
        if Path("/opt/mcp/server.py").is_file() and sys.prefix == "/opt/venv":
            self.assertEqual([(test.id(), why) for test, why in outcome.skipped], [])
        self.assertGreater(outcome.testsRun, minimum)

    def test_exec(self):
        """The command server over stdio as the image starts it (without a folder at /work every tool says so), then
        the offline suite of tests/test_exec.py - in CI with the image's own Python, its pytest, pyflakes, PyYAML and
        shellcheck, as its unprivileged user, no network."""
        self.check_tools("exec")
        if not os.path.ismount("/work"):  # where /work is a mounted folder, the server would run its commands in it
            answers = rpc("exec", session(("run_command", {"command": "true"}), ("lint", {}),
                                          ("job_status", {"job_id": 1}), ("list_jobs", {})))
            for index in (2, 3):
                self.assertTrue(answers[index]["result"]["isError"])
                self.assertIn("no folder is mounted at /work", answers[index]["result"]["content"][0]["text"])
            self.assertIn("there is no job 1", answers[4]["result"]["content"][0]["text"])
            self.assertIn("no jobs", answers[5]["result"]["content"][0]["text"])
        self.offline_suite("test_exec", 40)

    def test_tasks(self):
        """The plan server over stdio as the image starts it (without a folder at /work every tool says so), then the
        offline suite of tests/test_tasks.py (persistence, bounds, links, concurrency) - in CI inside the image."""
        self.check_tools("tasks")
        if not os.path.ismount("/work"):  # where /work is a mounted folder, the server would write its plan into it
            answers = rpc("tasks", session(("next_step", {}), ("set_goal", {"goal": "x"})))
            for index in (2, 3):
                self.assertTrue(answers[index]["result"]["isError"])
                self.assertIn("no folder is mounted at /work", answers[index]["result"]["content"][0]["text"])
        self.offline_suite("test_tasks", 10)

    def test_files(self):
        """The workspace file server over stdio (tools, refusals before any file is touched), then the whole offline
        suite of tests/test_files.py against temporary folders - in CI with the image's own Python and libraries, no
        network."""
        self.check_tools("files")
        answers = rpc("files", session(("read_file", {"path": "../etc/passwd"}),
                                       ("read_file", {"path": "/etc/passwd"}),
                                       ("write_file", {"path": "notes.md", "content": "x"}),
                                       ("write_markdown", {"path": "notes.txt", "content": "x"})),
                      env={"FILES_READONLY": "1"})
        self.assertIn("'..' is not allowed", result(answers[2])["error"])
        self.assertIn("outside the folders this server can reach", result(answers[3])["error"])
        self.assertIn("FILES_READONLY=1", result(answers[4])["error"])
        self.assertIn("use write_file for other files", result(answers[5])["error"])
        sys.path.insert(0, str(ROOT / "tests"))
        import test_files
        outcome = unittest.TestResult()
        unittest.defaultTestLoader.loadTestsFromModule(test_files).run(outcome)
        problems = [f"{test.id()}: {text[-1500:]}" for test, text in outcome.failures + outcome.errors]
        self.assertEqual(problems, [], "\n".join(problems))
        self.assertEqual(outcome.skipped, [])
        self.assertGreater(outcome.testsRun, 50)
    def test_bluesky(self):
        """The posting server over stdio (tools, the write switch and refusals before any request, no credentials
        named), then the whole offline suite of tests/test_bluesky.py against its fake PDS and AppView - in CI with
        the image's own Python and libraries, no network."""
        self.check_tools("bluesky")
        clean = {"BLUESKY_HANDLE": "", "BLUESKY_APP_PASSWORD": "", "BLUESKY_WRITE": "", "BLUESKY_PDS": ""}
        image = [{"path": "/etc/passwd", "alt": "x"}]
        answers = rpc("bluesky", session(("get_profile", {}), ("post", {"text": "x"}),
                                         ("post", {"text": "x", "images": image}),
                                         ("delete_post", {"uri": "at://did:plc:" + "a" * 24 + "/app.bsky.feed.post/x"}),
                                         ("list_my_posts", {})), env=clean)
        self.assertIn("no Bluesky credentials", result(answers[2])["error"])
        self.assertIn("writing is off", result(answers[3])["error"])
        self.assertIn("only files under /upload", result(answers[4])["error"])
        self.assertIn("BLUESKY_WRITE=1", result(answers[5])["error"])
        self.assertIn("no Bluesky credentials", result(answers[6])["error"])
        answers = rpc("bluesky", session(("post", {"text": "x"})), env={**clean, "BLUESKY_WRITE": "1"})
        self.assertIn("no Bluesky credentials", result(answers[2])["error"])
        sys.path.insert(0, str(ROOT / "tests"))
        import test_bluesky
        outcome = unittest.TestResult()
        unittest.defaultTestLoader.loadTestsFromModule(test_bluesky).run(outcome)
        problems = [f"{test.id()}: {text[-1500:]}" for test, text in outcome.failures + outcome.errors]
        self.assertEqual(problems, [], "\n".join(problems))
        self.assertEqual(outcome.skipped, [])
        self.assertGreater(outcome.testsRun, 30)

    def test_code_search(self):
        """The code search server over stdio as the image starts it (its seven tools; refusals before any file is
        looked at, so the real /work is never walked), then the offline suite of tests/test_code_search.py on a seeded
        project in temporary folders - in CI with the image's own Python and libraries, no network."""
        self.check_tools("code-search")
        answers = rpc("code-search", session(("outline", {"path": "../etc/passwd"}),
                                             ("read_symbol", {"path": "/etc/passwd", "name": "root"}),
                                             ("find_text", {"pattern": "(a+)+$", "regex": True}),
                                             ("find_definition", {"name": "parse args("}),
                                             ("find_definition", {"name": "x", "kind": "banana"}),
                                             ("project_map", {"depth": 9})))
        expected = ("'..' is not allowed", "outside the folders this server can reach", "can take forever",
                    "a name like parse_args", "kind: one of", "depth: a whole number from 1 to 6")
        for index, text in enumerate(expected, start=2):
            self.assertTrue(answers[index]["result"]["isError"], index)
            self.assertIn(text, answers[index]["result"]["content"][0]["text"])
        self.offline_suite("test_code_search", 50)

    def test_jadx(self):
        """The jadx server over stdio as the image starts it (its fourteen tools, no resources or prompts; refusals
        before any file is opened, so the real /work is never read), then the offline suite of tests/test_jadx.py -
        inside the image with jadx itself (the fixtures decompiled for real), no network."""
        answers = self.check_tools("jadx")
        self.assertNotIn("resources", answers[0]["result"]["capabilities"])
        self.assertNotIn("prompts", answers[0]["result"]["capabilities"])
        answers = rpc("jadx", session(("open_file", {"path": "../etc/passwd"}), ("open_file", {"path": "/etc/passwd"}),
                                      ("get_class_source", {"path": "a.apk", "class_name": "a b"}),
                                      ("search_code", {"path": "a.apk", "text": "x", "max_results": 0}),
                                      ("get_method_source", {"path": "a.apk", "class_name": "a.B",
                                                             "method_name": "--outputdir"})))
        expected = ("'..' is not allowed", "only files in /work can be read", "class_name: a class name",
                    "max_results: a whole number from 1 to 200", "method_name: only the name")
        for index, text in enumerate(expected, start=2):
            self.assertTrue(answers[index]["result"]["isError"], index)
            self.assertIn(text, answers[index]["result"]["content"][0]["text"])
        self.offline_suite("test_jadx", 20)

    def test_cfr(self):
        """The cfr server over stdio as the image starts it (its six tools, no resources or prompts; refusals before
        any file is opened), then the offline suite of tests/test_cfr.py - inside the image with CFR itself, no
        network."""
        answers = self.check_tools("cfr")
        self.assertNotIn("resources", answers[0]["result"]["capabilities"])
        answers = rpc("cfr", session(("list_classes", {"path": "../etc/passwd"}),
                                     ("decompile_class", {"path": "/etc/passwd"}),
                                     ("decompile_method", {"path": "a.jar", "class_name": "a.B",
                                                           "method_name": "--outputdir"}),
                                     ("decompile_class", {"path": "a.jar", "class_name": "a.B",
                                                          "anti_obfuscation": "--outputdir"})))
        expected = ("'..' is not allowed", "only files in /work can be read", "method_name: only the name",
                    "Input should be a valid boolean")
        for index, text in enumerate(expected, start=2):
            self.assertTrue(answers[index]["result"]["isError"], index)
            self.assertIn(text, answers[index]["result"]["content"][0]["text"])
        self.offline_suite("test_cfr", 12)

    def test_smali(self):
        """The smali server over stdio as the image starts it (its eleven tools, no resources or prompts; refusals
        before any file is opened or anything is written), then the offline suite of tests/test_smali.py - inside the
        image with baksmali, smali, apktool, zipalign and apksigner themselves, no network."""
        answers = self.check_tools("smali")
        self.assertNotIn("resources", answers[0]["result"]["capabilities"])
        answers = rpc("smali", session(("list_classes", {"path": "../etc/passwd"}),
                                       ("get_smali", {"path": "/etc/passwd", "class_name": "a.B"}),
                                       ("disassemble", {"path": "a.apk", "out_name": "../escape"}),
                                       ("get_smali", {"path": "a.apk", "class_name": "--classes"}),
                                       ("apktool_build", {"folder": "/work", "out_name": "x.apk"}),
                                       ("get_smali", {"path": "a.apk", "class_name": "a.B",
                                                      "api_level": "twenty-one"})))
        expected = ("'..' is not allowed", "only files in", "out_name:", "class_name:", "only files in /out",
                    "Input should be a valid integer")
        for index, text in enumerate(expected, start=2):
            self.assertTrue(answers[index]["result"]["isError"], index)
            self.assertIn(text, answers[index]["result"]["content"][0]["text"])
        self.offline_suite("test_smali", 20)

    def test_frida(self):
        """The frida server over stdio as the image starts it (its sixteen tools, no resources or prompts; without a
        configured device every device tool says what to configure, the write tools refuse, frida's local device is
        refused by name), then the offline suite of tests/test_frida.py - inside the image with frida's own bindings,
        and no device anywhere."""
        answers = self.check_tools("frida")
        self.assertNotIn("resources", answers[0]["result"]["capabilities"])
        answers = rpc("frida", session(("device_status", {}), ("list_devices", {}),
                                       ("list_processes", {"device": "local"}),
                                       ("spawn", {"program": "com.example.app"}),
                                       ("push_server", {}),
                                       ("run_script", {"session": 1, "script": "send(1)"}),
                                       ("export_server", {"abi": "arm64", "out_name": "../escape"}),
                                       ("run_script", {"session": 1, "path": "../etc/passwd"})))
        self.assertFalse(answers[2]["result"].get("isError"), "device_status answers without a device")
        self.assertIn("FRIDA_DEVICE", answers[2]["result"]["content"][0]["text"])
        expected = ("no device is configured", "frida's own device of this container", "FRIDA_WRITE=1",
                    "FRIDA_WRITE=1", "there is no such session", "out_name:", "'..' is not allowed")
        for index, text in enumerate(expected, start=3):
            self.assertTrue(answers[index]["result"]["isError"], index)
            self.assertIn(text, answers[index]["result"]["content"][0]["text"])
        self.offline_suite("test_frida", 25)


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

    def test_osint_mcp_offers_tools_only(self):
        Servers.check_tools_only(self, "osint-mcp")  # (a method of the other class, for any TestCase)

    def test_osint_mcp_answers_fit_what_clients_show(self):
        """subdomains of a large domain (thousands of names), wayback with up to 500 snapshots and recon_batch of ten
        domains answered far more than the 25,000 characters clients show a model: an answer is shortened to fit,
        its longest lists cut, and it says what was cut and how much."""
        from unittest import mock
        module = load("osint-mcp")
        from osint_mcp import sources

        async def many(client, domain):
            return {"domain": domain, "certs_seen": 9000,
                    "subdomains": [f"host-{n}.{domain}" for n in range(5000)]}
        with mock.patch.object(sources, "crtsh_subdomains", many):
            answer = asyncio.run(module.server.mcp.call_tool("subdomains", {"domain": "example.com"}))
        text = answer.content[0].text
        self.assertLessEqual(len(text), 24_000)
        data = json.loads(text)
        self.assertEqual(data["certs_seen"], 9000)
        self.assertEqual(data["subdomains"][0], "host-0.example.com")
        self.assertEqual(data["shortened"]["subdomains"], 5000 - len(data["subdomains"]))
        self.assertIn("24,000", data["note"])
        small = {"domain": "example.com", "subdomains": ["a.example.com"]}
        self.assertEqual(module.bounded(small), small)  # an answer that fits is left as it is

    def test_osint_mcp_dns_over_tcp_behind_tor(self):
        """Behind sandbox-ai's Tor profile (SANDBOX_AI_TOR=1) no UDP passes, and tor's DNSPort, where port 53 is sent,
        answers A, AAAA and PTR only: dns_lookup, email_security and the DNS parts of recon_domain and
        compare_domains got no MX, TXT, NS, SOA or CAA. There every lookup goes over TCP - through tor's TransPort and
        an exit - to public resolvers (TOR_RESOLVERS) or the nameserver a call names, with longer timeouts; without
        Tor upstream's resolver is unchanged. No network: the queries are answered here."""
        from unittest import mock
        import dns.asyncquery
        import dns.asyncresolver
        from osint_mcp import sources
        original = dns.asyncresolver.Resolver
        with mock.patch.dict(os.environ):
            os.environ.pop("SANDBOX_AI_TOR", None)
            load("osint-mcp")
            self.assertIs(dns.asyncresolver.Resolver, original)
        asked = []

        async def tcp(request, where, timeout=None, port=53, *args, **kwargs):
            asked.append(("tcp", where, port, timeout))
            return dns_answer(request)

        async def udp(request, where, *args, **kwargs):
            asked.append(("udp", where, None, None))
            raise OSError("no UDP behind Tor")

        with mock.patch.dict(os.environ, {"SANDBOX_AI_TOR": "1"}), \
                mock.patch.object(dns.asyncresolver, "Resolver", original), \
                mock.patch.object(dns.asyncquery, "tcp", tcp), mock.patch.object(dns.asyncquery, "udp", udp):
            module = load("osint-mcp")
            self.assertIs(dns.asyncresolver.Resolver, module.TorResolver)
            records = asyncio.run(sources.dns_records("example.com"))["records"]
            txt = asyncio.run(sources.txt_records("_dmarc.example.com"))
            ptr = asyncio.run(sources.reverse_dns("1.1.1.1"))
            tor_resolvers = len(asked)
            chosen = asyncio.run(sources.dns_records("example.com", ["MX"], "8.8.4.4"))["records"]
            resolver = dns.asyncresolver.Resolver()
            resolver.timeout, resolver.lifetime = 2, 5.0  # upstream sets its own: Tor's are the least
            self.assertEqual((resolver.timeout, resolver.lifetime), (module.TOR_DNS_TIMEOUT, module.TOR_DNS_LIFETIME))
            self.assertEqual(resolver.nameservers, list(module.TOR_RESOLVERS))
        self.assertIs(dns.asyncresolver.Resolver, original)
        for kind in ("A", "AAAA", "MX", "NS", "TXT", "SOA", "CAA"):
            expected = [value.strip('"') for value in DNS_RECORDS[kind]] if kind == "TXT" else DNS_RECORDS[kind]
            self.assertEqual(records[kind], sorted(expected), kind)
        self.assertNotIn("CNAME", records)  # an empty answer, not "<timeout>" or "<unavailable>"
        self.assertEqual((txt, ptr, chosen), (["v=spf1 -all"], ["one.one.one.one"], {"MX": DNS_RECORDS["MX"]}))
        self.assertEqual({(kind, where in module.TOR_RESOLVERS, port) for kind, where, port, _ in asked[:tor_resolvers]},
                         {("tcp", True, 53)})
        self.assertEqual(asked[tor_resolvers:], [("tcp", "8.8.4.4", 53, asked[-1][3])])  # the one the call names
        self.assertTrue(all(timeout > 5 for *_, timeout in asked), asked)  # Tor's timeout, not upstream's 5 s

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



def axross_installed():
    try:
        return (importlib.util.find_spec("axross_headless_mcp") is not None
                and importlib.util.find_spec("paramiko") is not None)
    except ImportError:
        return False


AXROSS_BOOT = """
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("axross_server", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.WORK, module.CONFIG, module.SSH, module.HOME = json.loads(sys.argv[2])
sys.exit(module.main([]))
"""


class AxrossSftp:
    """An SFTP server on 127.0.0.1 for the axross tests (paramiko's server side): one user, a password or one
    public key, the files of ROOT; no commands (exec refused)."""

    def __init__(self, root, user="tester", password="pw-axross-7", public_key=None):
        import paramiko
        self.paramiko, self.root, self.user, self.password, self.public_key = paramiko, root, user, password, public_key
        self.host_key = paramiko.ECDSAKey.generate()
        self.logins = []
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(4)
        self.sock.settimeout(0.3)
        self.port = self.sock.getsockname()[1]
        self.stopping = threading.Event()
        threading.Thread(target=self._accept, daemon=True).start()

    def known_hosts_line(self):
        return f"[127.0.0.1]:{self.port} {self.host_key.get_name()} {self.host_key.get_base64()}\n"

    def close(self):
        self.stopping.set()

    def _interface(self):
        paramiko, outer = self.paramiko, self

        def real(path):
            return os.path.join(outer.root, os.path.normpath("/" + (path or "/")).lstrip("/"))

        def failed(exc):
            return paramiko.SFTPServer.convert_errno(exc.errno) if getattr(exc, "errno", None) else \
                paramiko.sftp.SFTP_FAILURE

        class Handle(paramiko.SFTPHandle):
            def stat(self):
                return paramiko.SFTPAttributes.from_stat(os.fstat(self.readfile.fileno()))

        class Sftp(paramiko.SFTPServerInterface):
            def canonicalize(self, path):
                return os.path.normpath("/" + (path or "/")) if path not in ("", ".") else "/"

            def list_folder(self, path):
                try:
                    found = []
                    for name in os.listdir(real(path)):
                        attr = paramiko.SFTPAttributes.from_stat(os.lstat(os.path.join(real(path), name)))
                        attr.filename = name
                        found.append(attr)
                    return found
                except OSError as exc:
                    return failed(exc)

            def stat(self, path):
                try:
                    return paramiko.SFTPAttributes.from_stat(os.stat(real(path)))
                except OSError as exc:
                    return failed(exc)

            def lstat(self, path):
                try:
                    return paramiko.SFTPAttributes.from_stat(os.lstat(real(path)))
                except OSError as exc:
                    return failed(exc)

            def open(self, path, flags, attr):
                try:
                    fd = os.open(real(path), flags, 0o644)
                except OSError as exc:
                    return failed(exc)
                writing = flags & (os.O_WRONLY | os.O_RDWR)
                handle = Handle(flags)
                handle.readfile = handle.writefile = os.fdopen(fd, ("ab" if flags & os.O_APPEND else "r+b")
                                                               if writing else "rb")
                return handle

            def remove(self, path):
                try:
                    os.remove(real(path))
                except OSError as exc:
                    return failed(exc)
                return paramiko.sftp.SFTP_OK

            def rename(self, old, new):
                try:
                    os.rename(real(old), real(new))
                except OSError as exc:
                    return failed(exc)
                return paramiko.sftp.SFTP_OK

            posix_rename = rename

            def mkdir(self, path, attr):
                try:
                    os.mkdir(real(path))
                except OSError as exc:
                    return failed(exc)
                return paramiko.sftp.SFTP_OK

            def rmdir(self, path):
                try:
                    os.rmdir(real(path))
                except OSError as exc:
                    return failed(exc)
                return paramiko.sftp.SFTP_OK

            def chattr(self, path, attr):
                return paramiko.sftp.SFTP_OK

        return Sftp

    def _accept(self):
        paramiko, outer = self.paramiko, self

        class Server(paramiko.ServerInterface):
            def check_auth_password(self, username, password):
                outer.logins.append(("password", username, password))
                ok = outer.password and username == outer.user and password == outer.password
                return paramiko.AUTH_SUCCESSFUL if ok else paramiko.AUTH_FAILED

            def check_auth_publickey(self, username, key):
                outer.logins.append(("publickey", username, key.get_base64()))
                ok = outer.public_key is not None and username == outer.user and \
                    key.get_base64() == outer.public_key.get_base64()
                return paramiko.AUTH_SUCCESSFUL if ok else paramiko.AUTH_FAILED

            def get_allowed_auths(self, username):
                return "password,publickey"

            def check_channel_request(self, kind, chanid):
                return paramiko.OPEN_SUCCEEDED if kind == "session" else \
                    paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

        sftp = self._interface()
        while not self.stopping.is_set():
            try:
                conn, _ = self.sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            transport = paramiko.Transport(conn)
            transport.add_server_key(self.host_key)
            transport.set_subsystem_handler("sftp", paramiko.SFTPServer, sftp)
            try:
                transport.start_server(server=Server())
            except (paramiko.SSHException, EOFError, OSError):
                transport.close()
        self.sock.close()


@unittest.skipUnless(axross_installed(), "axross-headless-mcp runs from its own lock: inside its image, or after "
                                         "pip install --require-hashes -r servers/axross/requirements.txt")
class Axross(unittest.TestCase):
    """axross-headless-mcp behind servers/axross/src/server.py, started as the image starts it (the folders re-pointed
    to temporary ones): the tools it offers with and without AXROSS_WRITE, what stays refused whatever the
    environment says, the root, links out of it and secret files, and SFTP profiles against a local server (no
    network beyond 127.0.0.1: CI runs it inside the image with none)."""

    SERVER = ROOT / "servers/axross/src/server.py"

    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix="axross-test-"))
        self.addCleanup(shutil.rmtree, self.base, True)
        self.work, self.config, self.ssh, self.home = (self.base / n for n in ("work", "config", "ssh", "home"))
        for folder in (self.work, self.config, self.ssh):
            folder.mkdir()
        (self.work / "docs").mkdir()
        (self.work / "docs/a.txt").write_text("hello axross\n")
        (self.work / "escape").symlink_to("/etc")
        (self.work / ".env").write_text("TOKEN=not-for-the-agent\n")

    def session(self, *calls, env=None, profiles=None):
        """(initialize, tools/list, [each call's answer], stderr) of one stdio session."""
        if profiles is not None:
            (self.config / "profiles.json").write_text(json.dumps(profiles))
        paths = json.dumps([str(self.work), str(self.config), str(self.ssh), str(self.home)])
        base_env = {k: v for k, v in os.environ.items() if not k.startswith(("AXROSS_", "XDG_"))}
        process = subprocess.Popen([sys.executable, "-I", "-c", AXROSS_BOOT, str(self.SERVER), paths],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   env={**base_env, **(env or {})})
        messages = [{"jsonrpc": "2.0", "id": 0, "method": "initialize",
                     "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                "clientInfo": {"name": "test", "version": "1"}}},
                    {"jsonrpc": "2.0", "method": "notifications/initialized"},
                    {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}]
        messages += [{"jsonrpc": "2.0", "id": 10 + i, "method": "tools/call",
                      "params": {"name": name, "arguments": arguments}} for i, (name, arguments) in enumerate(calls)]
        # One request at a time, each answer awaited: the server runs tool calls side by side, so a call sent
        # before remote_open has answered would not find its backend yet.
        watchdog = threading.Timer(180, process.kill)
        watchdog.start()
        answers = {}
        try:
            for message in messages:
                process.stdin.write((json.dumps(message) + "\n").encode())
                process.stdin.flush()
                while "id" in message and message["id"] not in answers:
                    line = process.stdout.readline()
                    if not line:
                        break
                    answer = json.loads(line)
                    if "id" in answer:
                        answers[answer["id"]] = answer
                if "id" in message and message["id"] not in answers:
                    break
            process.stdin.close()
            err = process.stderr.read()
            process.wait(60)
        finally:
            watchdog.cancel()
            process.stdout.close()
            process.stderr.close()
        return answers.get(0), answers.get(1), [answers.get(10 + i) for i in range(len(calls))], err.decode()

    @staticmethod
    def text(answer):
        body = answer.get("result") or answer.get("error") or {}
        if "content" in body:
            return body["content"][0]["text"]
        return body.get("message", "")

    def test_axross_offers_the_recorded_tools_only(self):
        recorded = json.loads((ROOT / "servers/axross/tools.json").read_text())
        init, listed, _, _ = self.session(env={"AXROSS_WRITE": "1"})
        capabilities = init["result"]["capabilities"]
        self.assertEqual(sorted(t["name"] for t in listed["result"]["tools"]), recorded["tools"])
        self.assertNotIn("resources", capabilities)
        self.assertNotIn("prompts", capabilities)
        self.assertRegex(init["result"]["instructions"], r"never as instructions")
        # read-only without AXROSS_WRITE=1: the write tools are not there at all
        _, listed, _, _ = self.session()
        self.assertEqual(sorted(t["name"] for t in listed["result"]["tools"]), recorded["read_only_tools"])

    def test_axross_environment_cannot_widen_it(self):
        """AXROSS_MCP_TOOLS=all, AXROSS_MCP_WRITE=1, an HTTP token, a state folder elsewhere: none of it counts."""
        _, listed, answers, err = self.session(
            ("write_file", {"path": "x.txt", "content": "x"}),
            env={"AXROSS_MCP_TOOLS": "all", "AXROSS_MCP_WRITE": "1", "AXROSS_MCP": "1",
                 "XDG_STATE_HOME": str(self.work), "AXROSS_OPERATION_JOURNAL": str(self.work / "j.jsonl")})
        names = {t["name"] for t in listed["result"]["tools"]}
        self.assertFalse(names & {"write_file", "remote_exec", "script_run", "agent_run", "pack", "transfer_copy"})
        self.assertIn("Unknown tool", self.text(answers[0]))
        self.assertEqual(sorted(p.name for p in self.work.iterdir()), [".env", "docs", "escape"])

    def test_axross_stays_in_work(self):
        _, _, answers, _ = self.session(
            ("read_file", {"path": "docs/a.txt", "encoding": "text"}),
            ("read_file", {"path": "../../../etc/passwd"}),
            ("read_file", {"path": "/etc/passwd"}),
            ("read_file", {"path": "escape/passwd"}),
            ("read_file", {"path": ".env"}),
            ("list_dir", {"path": "/"}),
            ("write_file", {"path": "escape/cron.d/x", "content": "x"}),
            ("symlink", {"target": "/etc/shadow", "link_path": "l"}),
            ("chmod", {"path": "docs/a.txt", "mode": "4755"}),
            ("write_file", {"path": "docs/b.txt", "content": "made here"}),
            env={"AXROSS_WRITE": "1"})
        self.assertIn("hello axross", self.text(answers[0]))
        for index in (1, 2, 5):
            self.assertIn("escapes the configured MCP root", self.text(answers[index]), index)
        self.assertIn("via symlink", self.text(answers[3]))
        self.assertIn("credentials, keys or secrets", self.text(answers[4]))
        self.assertIn("via symlink", self.text(answers[6]))
        self.assertIn("refused", self.text(answers[7]))
        self.assertIn("setuid", self.text(answers[8]))
        self.assertEqual((self.work / "docs/b.txt").read_text(), "made here")
        self.assertFalse((self.work / "l").exists())

    def test_axross_reviewed_modules_only(self):
        """A module of the package nobody reviewed for the image does not import, and REVIEWED is reviewed.sha256."""
        module = load("axross")
        listed = (ROOT / "servers/axross/reviewed.sha256").read_text().split("\n")
        files = {line.split("  ", 1)[1] for line in listed if line}
        named = set()
        for path in files:
            parts = path.split("/")
            if parts[:2] != ["axross_headless_mcp", "_ax"] or len(parts) < 4:
                continue
            name = ".".join(parts[2:]).removesuffix(".py").removesuffix(".__init__")
            named.add(name)
        self.assertEqual(named, set(module.REVIEWED))
        guard = module.ReviewedOnly()
        for name in ("core.scripting", "core.agent", "core.mcp_http", "core.smb_client", "core.self_update",
                     "resources.scripts.port_scan", "core.cred_attack"):
            with self.assertRaises(ImportError, msg=name):
                guard.find_spec(name)
        self.assertIsNone(guard.find_spec("core.mcp_server"))
        self.assertIsNone(guard.find_spec("paramiko"))

    def test_axross_passwords_are_read_once_and_checked(self):
        module = load("axross")
        environ = {"AXROSS_PASSWORDS": json.dumps({"box": "s3cret", "box:proxy": "p"})}
        self.assertEqual(module.take_passwords(environ), {"box": "s3cret", "box:proxy": "p"})
        self.assertNotIn("AXROSS_PASSWORDS", environ)
        for bad in ("s3cret", '["s3cret"]', '{"box": 7}', '{"": "x"}'):
            with self.assertRaises(ValueError) as caught:
                module.take_passwords({"AXROSS_PASSWORDS": bad})
            self.assertNotIn("s3cret", str(caught.exception))
        _, listed, _, err = self.session(env={"AXROSS_PASSWORDS": "s3cret-not-json"})
        self.assertIsNone(listed)
        self.assertIn("AXROSS_PASSWORDS is not JSON", err)
        self.assertNotIn("s3cret-not-json", err)

    def profile(self, name, sftp, **fields):
        return {name: {"name": name, "protocol": "sftp", "host": "127.0.0.1", "port": sftp.port,
                       "username": "tester", **fields}}

    def test_axross_opens_an_sftp_profile(self):
        remote = self.base / "remote"
        (remote / "data").mkdir(parents=True)
        (remote / "data/r.txt").write_text("remote file\n")
        sftp = AxrossSftp(str(remote))
        self.addCleanup(sftp.close)
        (self.ssh / "known_hosts").write_text(sftp.known_hosts_line())
        password = "pw-axross-7"
        _, _, answers, err = self.session(
            ("remote_profiles", {}),
            ("remote_open", {"profile": "box"}),
            ("list_dir", {"backend": "profile:box", "path": "/data"}),
            ("read_file", {"backend": "profile:box", "path": "/data/r.txt", "encoding": "text"}),
            ("write_file", {"backend": "profile:box", "path": "/data/w.txt", "content": "written"}),
            ("write_file", {"backend": "profile:box", "path": "/data/../w.txt", "content": "x"}),
            ("remote_close", {"backend": "profile:box"}),
            env={"AXROSS_WRITE": "1", "AXROSS_PASSWORDS": json.dumps({"box": password})},
            profiles=self.profile("box", sftp, auth_type="password", store_password=True))
        self.assertIn('"openable": true', self.text(answers[0]))
        self.assertIn('"backend": "profile:box"', self.text(answers[1]))
        self.assertIn("r.txt", self.text(answers[2]))
        self.assertIn("remote file", self.text(answers[3]))
        self.assertEqual((remote / "data/w.txt").read_text(), "written")
        self.assertIn("'..'", self.text(answers[5]))
        self.assertIn('"closed": true', self.text(answers[6]))
        self.assertIn(("password", "tester", password), sftp.logins)
        everything = json.dumps(answers) + err + "".join(
            p.read_text(errors="replace") for p in self.home.rglob("*") if p.is_file() and not p.is_symlink())
        self.assertNotIn(password, everything)

    def test_axross_refuses_an_unknown_host_key(self):
        remote = self.base / "remote"
        remote.mkdir()
        sftp = AxrossSftp(str(remote))
        self.addCleanup(sftp.close)
        _, _, answers, _ = self.session(
            ("remote_open", {"profile": "box"}),
            env={"AXROSS_PASSWORDS": json.dumps({"box": "pw-axross-7"})},
            profiles=self.profile("box", sftp, auth_type="password", store_password=True))
        self.assertIn("is not trusted yet", self.text(answers[0]))
        self.assertEqual(sftp.logins, [], "no password is sent to a host whose key is not known")
        self.assertFalse((self.ssh / "known_hosts").exists(), "nothing is trusted on first use")

    def test_axross_key_files_come_from_ssh(self):
        import paramiko
        key = paramiko.ECDSAKey.generate()
        remote = self.base / "remote"
        remote.mkdir()
        (remote / "k.txt").write_text("by key\n")
        sftp = AxrossSftp(str(remote), password=None, public_key=key)
        self.addCleanup(sftp.close)
        (self.ssh / "known_hosts").write_text(sftp.known_hosts_line())
        key.write_private_key_file(str(self.ssh / "id_axross_test"))
        profiles = {**self.profile("keybox", sftp, auth_type="key", key_file="/home/alice/.ssh/id_axross_test"),
                    **self.profile("nokey", sftp, auth_type="key", key_file="/home/alice/.ssh/id_missing")}
        _, _, answers, _ = self.session(
            ("remote_open", {"profile": "keybox"}),
            ("read_file", {"backend": "profile:keybox", "path": "/k.txt", "encoding": "text"}),
            ("remote_open", {"profile": "nokey"}),
            profiles=profiles)
        self.assertIn('"backend": "profile:keybox"', self.text(answers[0]))
        self.assertIn("by key", self.text(answers[1]))
        self.assertIn("there is no id_missing in the folder mounted at /ssh", self.text(answers[2]))

    def test_axross_opens_sftp_profiles_only(self):
        profiles = {
            "share": {"name": "share", "protocol": "smb", "host": "192.0.2.5", "username": "u", "store_password": True},
            "jump": {"name": "jump", "protocol": "sftp", "host": "192.0.2.6", "username": "u", "auth_type": "key",
                     "key_file": "id", "proxy_command": "ssh -W %h:%p bastion"},
            "socks": {"name": "socks", "protocol": "sftp", "host": "192.0.2.7", "username": "u", "auth_type": "key",
                      "key_file": "id", "proxy_type": "socks5", "proxy_host": "192.0.2.8", "proxy_port": 1080},
            "agent": {"name": "agent", "protocol": "sftp", "host": "192.0.2.9", "username": "u", "auth_type": "agent"},
        }
        _, _, answers, _ = self.session(
            ("remote_profiles", {}), ("remote_open", {"profile": "share"}), ("remote_open", {"profile": "jump"}),
            ("remote_open", {"profile": "socks"}), ("remote_open", {"profile": "agent"}),
            env={"AXROSS_PASSWORDS": json.dumps({"share": "x"})}, profiles=profiles)
        listing = json.loads(self.text(answers[0]))["profiles"]
        self.assertEqual([p["openable"] for p in listing], [False] * 4)
        self.assertIn("SFTP profiles only", self.text(answers[1]))
        self.assertIn("ProxyCommand", self.text(answers[2]))
        self.assertIn("proxy", self.text(answers[3]))
        self.assertIn("SSH agent", self.text(answers[4]))


if __name__ == "__main__":
    unittest.main()
