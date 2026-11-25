"""The onion-search server (servers/onion-search), offline: it refuses without a Tor profile before any name is looked
up; behind one, each engine's name must resolve into Tor's range for onion services before a connection; only the two
engines' onion hosts are ever asked (redirects included); Ahmia's form token is taken from its front page; the result
pages (Ahmia's tor_results.html, DuckDuckGo's HTML results) become data - .onion URLs only from Ahmia, no ads, no
script links, texts bounded; one engine failing does not hide the other. Requests go to a stand-in transport."""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
from pathlib import Path
import socket
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
FOLDER = ROOT / "servers" / "onion-search"
FIXTURES = ROOT / "tests" / "fixtures"
TOR = {"SANDBOX_AI_TOR": "1", "SANDBOX_AI_TOR_VIRTUAL_NETWORK": "10.192.0.0/10"}

try:
    import httpx
    import mcp  # noqa: F401
    from mcp.server.fastmcp.exceptions import ToolError
except ImportError:
    httpx = mcp = None
    ToolError = Exception


def load():
    spec = importlib.util.spec_from_file_location("server_onion_search_test", FOLDER / "src" / "server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(coro):
    return asyncio.run(coro)


@unittest.skipIf(mcp is None, "the server's requirements are not installed")
class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load()

    def setUp(self):
        self.lookups, self.requests = [], []
        self.answers = {}

        async def resolve(host, port):
            self.lookups.append(host)
            return self.answers.get(host, ["10.192.0.5"])
        patcher = mock.patch.object(self.m, "resolve", resolve)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tor(self, values=TOR):
        patcher = mock.patch.dict(os.environ, values)
        patcher.start()
        self.addCleanup(patcher.stop)
        for key in TOR:
            if key not in values:
                os.environ.pop(key, None)

    def serve(self, handler):
        def recording(request):
            self.requests.append(request)
            return handler(request)
        transport = httpx.MockTransport(recording)
        real = self.m.client

        def client():
            made = real()
            return httpx.AsyncClient(transport=transport, headers=made.headers, follow_redirects=False)
        patcher = mock.patch.object(self.m, "client", client)
        patcher.start()
        self.addCleanup(patcher.stop)

    def refused(self, coro) -> str:
        with self.assertRaises(ToolError) as caught:
            run(coro)
        return str(caught.exception)


def engines(request):
    host, path = request.url.host, request.url.path
    if host == "juhanurmihxlp77nkq76byazcldy2hlmovfu2epvl5ankdibsot4csyd.onion":
        if path == "/":
            return httpx.Response(200, text=(FIXTURES / "ahmia-front.html").read_text())
        if path == "/search/":
            return httpx.Response(200, text=(FIXTURES / "ahmia-results.html").read_text())
    if host == "duckduckgogg42xjoc72x3sjasowoarfbgcmvfimaftt6twagswzczad.onion" and path == "/html/":
        return httpx.Response(200, text=(FIXTURES / "duckduckgo.html").read_text())
    return httpx.Response(404)


class WithoutTor(Base):
    def test_nothing_is_looked_up_or_sent_without_a_tor_profile(self):
        self.tor({})
        self.serve(lambda request: self.fail("nothing is sent"))
        for engine in ("ahmia", "duckduckgo", "both"):
            text = self.refused(self.m.search_onion("privacy forum", engine=engine))
            self.assertIn("works only behind a Tor profile (start it with --vpn TOR_PROFILE)", text)
        self.assertEqual(self.lookups, [])
        status = run(self.m.onion_status())
        self.assertFalse(status["behind_tor"])
        self.assertIn("not behind a Tor profile", status["note"])
        self.assertIn("check: not behind a Tor profile", self.refused(self.m.onion_status(check=True)))

    def test_a_tor_profile_without_its_range_is_refused_too(self):
        for network in ("", "bogus", "192.168.0.0/16", "10.192.0.1/10"):
            with self.subTest(network=network):
                self.tor({"SANDBOX_AI_TOR": "1", "SANDBOX_AI_TOR_VIRTUAL_NETWORK": network})
                self.assertIn("not told Tor's address range", self.refused(self.m.search_onion("x")))
        self.assertEqual(self.lookups, [])


class BehindTor(Base):
    def setUp(self):
        super().setUp()
        self.tor()

    def test_ahmia_with_its_form_token(self):
        self.serve(engines)
        out = run(self.m.search_onion("privacy  forum"))
        self.assertEqual(out["query"], "privacy forum")
        ahmia = out["engines"][0]
        self.assertEqual((ahmia["engine"], ahmia["count"], ahmia["total"]), ("ahmia", 2, 3))
        first = ahmia["results"][0]
        self.assertEqual(first["title"], "Privacy & Security Forum")
        self.assertEqual(first["url"], "http://abcdefghijklmnopqrstuvwxyz234567abcdefghijklmnopqrstuvwx.onion/forum/")
        self.assertEqual(first["onion"], "abcdefghijklmnopqrstuvwxyz234567abcdefghijklmnopqrstuvwx.onion")
        self.assertEqual(first["last_seen"], "2026-11-20T10:00:00")
        self.assertNotIn("javascript", json.dumps(out))
        search = self.requests[-1]
        self.assertEqual(search.url.path, "/search/")
        self.assertEqual(dict(search.url.params), {"q": "privacy forum", "1a2b3c": "d4e5f6"})
        self.assertNotIn("not_this", str(search.url))
        self.assertEqual(set(self.lookups), {self.m.AHMIA})
        self.assertIn("Gecko", search.headers["User-Agent"])

    def test_duckduckgo_and_both(self):
        self.serve(engines)
        out = run(self.m.search_onion("example", engine="both", max_results=5))
        ddg = out["engines"][1]
        self.assertEqual(ddg["engine"], "duckduckgo")
        self.assertEqual(ddg["results"][0]["url"], "https://example.com/")
        self.assertNotIn("Ad", [r["title"] for r in ddg["results"]])
        post = [r for r in self.requests if r.url.host == self.m.DUCKDUCKGO][0]
        self.assertEqual((post.method, post.url.scheme, post.content), ("POST", "https", b"q=example"))
        self.assertEqual(set(self.lookups), {self.m.AHMIA, self.m.DUCKDUCKGO})

    def test_a_name_outside_tors_range_is_never_connected(self):
        self.answers[self.m.AHMIA] = ["93.184.215.14"]
        self.serve(lambda request: self.fail("no connection"))
        text = self.refused(self.m.search_onion("x"))
        self.assertIn("outside Tor's range for onion services (10.192.0.0/10): the connection would not go through "
                      "Tor", text)
        self.answers[self.m.AHMIA] = ["10.192.0.5", "fd00::1"]
        self.assertIn("outside Tor's range", self.refused(self.m.search_onion("x")))

        async def failing(host, port):
            raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
        with mock.patch.object(self.m, "resolve", failing):
            self.assertIn("the name lookup through Tor failed", self.refused(self.m.search_onion("x")))

    def test_redirects_stay_with_the_engine(self):
        def handler(request):
            if request.url.host == self.m.AHMIA and request.url.path == "/":
                return httpx.Response(302, headers={"Location": "http://example.org/"})
            return engines(request)
        self.serve(handler)
        self.assertIn("ahmia: refused: example.org is not one of this server's engines",
                      self.refused(self.m.search_onion("x")))

    def test_one_engine_failing_does_not_hide_the_other(self):
        def handler(request):
            if request.url.host == self.m.DUCKDUCKGO:
                return httpx.Response(202)
            return engines(request)
        self.serve(handler)
        out = run(self.m.search_onion("x", engine="both"))
        self.assertEqual(out["engines"][1], {"engine": "duckduckgo", "error": f"{self.m.DUCKDUCKGO} answered HTTP 202",
                                             "results": [], "count": 0})
        self.assertEqual(out["engines"][0]["count"], 2)

    def test_ahmia_without_its_token_and_bad_arguments(self):
        self.serve(lambda request: httpx.Response(200, text="<html>changed</html>"))
        self.assertIn("no search form token", self.refused(self.m.search_onion("x")))
        for kwargs, expected in (({"query": ""}, "query:"), ({"query": "x" * 101}, "query:"),
                                 ({"query": " ".join("w" * 11)}, "at most 10 words"),
                                 ({"query": "x", "engine": "google"}, "engine:"),
                                 ({"query": "x", "max_results": 51}, "max_results")):
            with self.subTest(kwargs=kwargs):
                self.assertIn(expected, self.refused(self.m.search_onion(**kwargs)))

    def test_status_and_its_check(self):
        self.serve(engines)
        status = run(self.m.onion_status(check=True))
        self.assertTrue(status["behind_tor"])
        self.assertEqual(status["tor_network"], "10.192.0.0/10")
        self.assertEqual([e["reachable"] for e in status["engines"]], [True, False])
        self.assertIn("answered HTTP 404", status["engines"][1]["error"])


class Parsers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load() if mcp is not None else None

    @unittest.skipIf(mcp is None, "the server's requirements are not installed")
    def test_targets(self):
        self.assertEqual(self.m.ahmia_target("/search/redirect?search_term=x&redirect_url=http://a.onion/b"),
                         "http://a.onion/b")
        for bad in ("/search/redirect?redirect_url=https://example.org/", "/search/redirect?redirect_url=file:///x",
                    "javascript:alert(1)", "http://[::1"):
            self.assertEqual(self.m.ahmia_target(bad), "", bad)
        self.assertEqual(self.m.ddg_target("/l/?uddg=https%3A%2F%2Fexample.org%2F"), "https://example.org/")
        self.assertEqual(self.m.ddg_target(f"https://{self.m.DUCKDUCKGO}/settings"), "")
        self.assertEqual(self.m.ddg_target("//duckduckgo.com/y.js?ad=1"), "")


class Packaging(unittest.TestCase):
    def test_the_entry(self):
        entry = json.loads((FOLDER / "server.json").read_text())
        self.assertEqual(entry["network"], "full")
        self.assertEqual(entry["tor"]["support"], "yes")
        self.assertIn("only behind a Tor profile", entry["notes"])
        source = (FOLDER / "src" / "server.py").read_text()
        self.assertIn('AHMIA = "juhanurmihxlp77nkq76byazcldy2hlmovfu2epvl5ankdibsot4csyd.onion"', source)
        self.assertIn('DUCKDUCKGO = "duckduckgogg42xjoc72x3sjasowoarfbgcmvfimaftt6twagswzczad.onion"', source)
        self.assertIn("trust_env=False", source)


if __name__ == "__main__":
    unittest.main()
