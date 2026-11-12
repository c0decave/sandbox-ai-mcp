"""Onion services behind sandbox-ai's Tor profile: web-fetch, gowitness and whatweb take the addresses of the range Tor
announces (SANDBOX_AI_TOR=1, SANDBOX_AI_TOR_VIRTUAL_NETWORK) and nothing else of the local ranges, and their errors
say what applies; searxng takes a .onion instance behind Tor. Name lookups are mocked: no network, no tor.

The servers' own requirements (mcp, httpx) are not needed: when they are not installed, the modules are loaded with
stand-ins for them (only the address checks and the redirect loops run here)."""
import asyncio
import importlib.util
import ipaddress
import os
from pathlib import Path
import socket
import sys
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
TOR_ENV = {"SANDBOX_AI_TOR": "1", "SANDBOX_AI_TOR_VIRTUAL_NETWORK": "10.192.0.0/10"}
ONION = "duckduckgogg42xjoc72x3sjasowoarfbgcmvfimaftt6twagswzczad.onion"
NAMES = {ONION: ["10.192.0.5"], "other.onion": ["10.0.0.7"], "v6.onion": ["10.192.0.6", "fe80::1"],
         "lan.example.org": ["192.168.1.10"], "ten.example.org": ["10.1.2.3"], "cgnat.example.org": ["100.64.0.1"],
         "172.example.org": ["172.16.0.1"], "ula.example.org": ["fd00::1"], "mapped.example.org": ["::ffff:10.0.0.1"],
         "nat64.example.org": ["64:ff9b::7f00:1"], "sixtofour.example.org": ["2002:c0a8:101::1"],
         "public.example.org": ["93.184.215.14"], "virtual.example.org": ["10.192.1.1"]}


def stand_ins() -> dict:
    """Modules for mcp and httpx, when they are not installed: enough to import a server."""
    try:
        import httpx  # noqa: F401
        import mcp.server.fastmcp  # noqa: F401
        return {}
    except ImportError:
        pass

    class FastMCP:
        def __init__(self, *args, **kwargs):
            pass

        def tool(self, *args, **kwargs):
            return lambda function: function

        def run(self, *args, **kwargs):
            raise RuntimeError("a stand-in")

    fastmcp = types.ModuleType("mcp.server.fastmcp")
    fastmcp.FastMCP = FastMCP
    utilities = types.ModuleType("mcp.server.fastmcp.utilities")
    kinds = types.ModuleType("mcp.server.fastmcp.utilities.types")
    kinds.Image = lambda data=None, format=None: ("image", format, data)
    httpx = types.ModuleType("httpx")
    httpx.HTTPError = type("HTTPError", (Exception,), {})
    httpx.AsyncClient = None
    return {"mcp": types.ModuleType("mcp"), "mcp.server": types.ModuleType("mcp.server"), "mcp.server.fastmcp": fastmcp,
            "mcp.server.fastmcp.utilities": utilities, "mcp.server.fastmcp.utilities.types": kinds, "httpx": httpx}


def load(name):
    with mock.patch.dict(sys.modules, stand_ins()):
        spec = importlib.util.spec_from_file_location(f"onion_{name.replace('-', '_')}",
                                                      ROOT / "servers" / name / "src/server.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


class Lookups:
    """socket.getaddrinfo from NAMES (and IP literals); the names asked are kept."""

    def __init__(self):
        self.asked = []

    def __call__(self, host, port, *args, **kwargs):
        self.asked.append(host)
        try:
            addresses = [str(ipaddress.ip_address(host))]
        except ValueError:
            if host not in NAMES:
                raise socket.gaierror(socket.EAI_NONAME, "Name or service not known") from None
            addresses = NAMES[host]
        return [(socket.AF_INET6 if ":" in a else socket.AF_INET, socket.SOCK_STREAM, 6, "",
                 (a, port, 0, 0) if ":" in a else (a, port)) for a in addresses]


class Environment:
    """The Tor variables as given (None: not set), the others of the test run unchanged."""

    def __init__(self, tor=None, network=None, private=None):
        self.values = {"SANDBOX_AI_TOR": tor, "SANDBOX_AI_TOR_VIRTUAL_NETWORK": network,
                       "ALLOW_PRIVATE_TARGETS": private}
        self.patch = mock.patch.dict(os.environ)

    def __enter__(self):
        self.patch.__enter__()
        for key, value in self.values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def __exit__(self, *exc):
        return self.patch.__exit__(*exc)


BEHIND_TOR = dict(tor="1", network="10.192.0.0/10")


class AddressChecks:
    """The checks every filtering server shares; *name* the server, *private_setting* whether it has
    ALLOW_PRIVATE_TARGETS."""
    name = None
    private_setting = False

    @classmethod
    def setUpClass(cls):
        cls.module = load(cls.name)

    def setUp(self):
        self.lookups = Lookups()
        patcher = mock.patch.object(socket, "getaddrinfo", self.lookups)
        patcher.start()
        self.addCleanup(patcher.stop)

    def refused(self, url, **env) -> str:
        with Environment(**env):
            with self.assertRaises(self.module.ArgumentError) as caught:
                self.module.check_url(url)
        return str(caught.exception)

    def taken(self, url, **env):
        with Environment(**env):
            self.assertEqual(self.module.check_url(url), url)

    def test_the_announced_range_is_taken_behind_tor(self):
        self.taken(f"http://{ONION}/", **BEHIND_TOR)
        self.taken(f"https://{ONION}:8443/a?b", **BEHIND_TOR)
        self.taken("http://10.192.0.9/", **BEHIND_TOR)  # an address of the range itself
        self.taken("http://virtual.example.org/", **BEHIND_TOR)
        self.taken("http://10.200.0.1/", tor="1", network="10.200.0.0/16")  # exactly the range announced
        self.taken("http://public.example.org/", **BEHIND_TOR)  # public addresses as before

    def test_everything_else_local_stays_refused_behind_tor(self):
        for url, words in (("http://ten.example.org/", "a local-network address"),
                           ("http://10.128.0.1/", "a local-network address"),
                           ("http://10.0.0.1/", "a local-network address"),
                           ("http://10.191.255.255/", "a local-network address"),
                           ("http://lan.example.org/", "a local-network address"),
                           ("http://172.example.org/", "a local-network address"),
                           ("http://cgnat.example.org/", "a local-network address"),
                           ("http://ula.example.org/", "a local-network address"),
                           ("http://mapped.example.org/", "(which reaches 10.0.0.1), a local-network address"),
                           ("http://sixtofour.example.org/", "(which reaches 192.168.1.1), a local-network address"),
                           ("http://nat64.example.org/", "(which reaches 127.0.0.1), a loopback address"),
                           ("http://127.0.0.1:9/", "a loopback address"),
                           ("http://[::1]/", "a loopback address"),
                           ("http://169.254.169.254/latest/meta-data/", "the cloud metadata address (link-local)"),
                           ("http://169.254.1.1/", "a link-local address"),
                           ("http://[fe80::1]/", "a link-local address"),
                           ("http://0.0.0.0/", "the unspecified address"),
                           ("http://224.0.0.1/", "a multicast address"),
                           ("http://192.0.2.1/", "a reserved or documentation address")):
            text = self.refused(url, **BEHIND_TOR)
            self.assertTrue(text.startswith("refused: "), text)
            self.assertIn(words, text, url)
            self.assertIn("not a public address", text, url)
        text = self.refused("http://ten.example.org/", **BEHIND_TOR)
        self.assertIn("behind Tor only Tor's range for onion services (10.192.0.0/10) is taken of 10.0.0.0/8", text)
        self.taken("http://10.200.0.1/", tor="1", network="10.200.0.0/16")
        self.assertIn("a local-network address", self.refused("http://10.192.0.5/", tor="1", network="10.200.0.0/16"))

    def test_an_onion_name_outside_the_range(self):
        text = self.refused("http://other.onion/", **BEHIND_TOR)
        self.assertIn("refused: other.onion resolves to 10.0.0.7, a local-network address", text)
        self.assertIn("behind Tor an onion name must resolve into Tor's range 10.192.0.0/10", text)
        text = self.refused("http://v6.onion/", **BEHIND_TOR)  # tor's IPv6 automapping: link-local, never taken
        self.assertIn("fe80::1, a link-local address", text)

    def test_local_network_wording(self):
        text = self.refused("http://lan.example.org/")
        self.assertIn("refused: lan.example.org resolves to 192.168.1.10, a local-network address", text)
        if self.private_setting:
            self.assertIn("(ALLOW_PRIVATE_TARGETS=1 allows your own LAN)", text)
            self.assertIn("not even with ALLOW_PRIVATE_TARGETS=1", self.refused("http://127.0.0.1/", private="1"))
        else:
            self.assertIn("this server never connects to local-network addresses", text)
            self.assertNotIn("ALLOW_PRIVATE_TARGETS", text)
            self.assertNotIn("ALLOW_PRIVATE_TARGETS", self.refused("http://169.254.169.254/"))

    def test_private_targets_unchanged(self):
        if not self.private_setting:
            self.skipTest("no ALLOW_PRIVATE_TARGETS here")
        for env in ({}, BEHIND_TOR):
            for url in ("http://lan.example.org/", "http://ten.example.org/", "http://10.192.0.9/",
                        "http://cgnat.example.org/", "http://ula.example.org/"):
                self.taken(url, private="1", **env)
            for url in ("http://127.0.0.1/", "http://169.254.169.254/", "http://[fe80::1]/",
                        "http://nat64.example.org/", "http://0.0.0.0/"):
                self.refused(url, private="1", **env)

    def test_behind_tor_without_a_valid_range(self):
        for network in (None, "", "10.192.0.0/33", "10.192.0.1/10", "192.168.0.0/16", "0.0.0.0/0", "fd00::/8",
                        "10.0.0.0/7", "tor"):
            text = self.refused(f"http://{ONION}/", tor="1", network=network)
            self.assertIn(f"refused: {ONION} resolves to 10.192.0.5, Tor's address for an onion service", text)
            self.assertIn("refused: 10.192.0.9 is Tor's address for an onion service",
                          self.refused("http://10.192.0.9/", tor="1", network=network))
            self.assertIn("this server was not told Tor's address range (SANDBOX_AI_TOR_VIRTUAL_NETWORK missing or "
                          "invalid: an older sandbox-ai?)", text)
            self.assertIn("Tor's address for an onion service", self.refused("http://10.192.0.9/", tor="1",
                                                                            network=network))
            self.assertIn("a loopback address", self.refused("http://127.0.0.1/", tor="1", network=network))
        text = self.refused("http://other.onion/", tor="1")  # outside tor's default range: what it is, and the range
        self.assertIn("a local-network address", text)
        self.assertIn("SANDBOX_AI_TOR_VIRTUAL_NETWORK missing or invalid", text)
        self.taken("http://10.0.0.1/", tor="1", network="10.0.0.0/8")  # the whole of 10/8 is a valid range

    def test_not_behind_tor(self):
        for env in ({}, dict(tor="0", network="10.192.0.0/10"), dict(network="10.192.0.0/10"), dict(tor="yes")):
            text = self.refused(f"http://{ONION}/", **env)
            self.assertEqual(text, f"refused: {ONION}: .onion needs a Tor profile (start the server behind one: "
                                   "--vpn TOR_PROFILE); this server does not run behind Tor")
        self.assertNotIn(ONION, self.lookups.asked)  # never sent to a resolver outside Tor
        self.assertIn(".onion needs a Tor profile", self.refused("http://abc.ONION./"))
        text = self.refused("http://virtual.example.org/")  # Tor's range without Tor: maybe a LAN, maybe Tor's
        self.assertIn("a local-network address", text)
        self.assertIn("if it is Tor's address for an onion service: .onion needs a Tor profile", text)


class WebFetch(AddressChecks, unittest.TestCase):
    name = "web-fetch"

    def fetch(self, pages, url):
        """fetch() against a stand-in httpx client: *pages* maps a URL to (status, headers, body)."""
        module = self.module

        class Response:
            def __init__(self, status, headers, body):
                self.status_code, self.headers, self.body = status, headers, body

            async def aiter_bytes(self):
                yield self.body

        class Stream:
            def __init__(self, url):
                self.response = Response(*pages[url])

            async def __aenter__(self):
                return self.response

            async def __aexit__(self, *exc):
                return False

        class Client:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            def stream(self, method, url):
                return Stream(url)

        with mock.patch.object(module.httpx, "AsyncClient", Client):
            return asyncio.run(module.fetch(url))

    def test_redirects_behind_tor(self):
        pages = {"https://public.example.org/": (302, {"location": f"http://{ONION}/page"}, b""),
                 f"http://{ONION}/page": (200, {"content-type": "text/plain"}, b"onion text"),
                 f"http://{ONION}/out": (301, {"location": "http://ten.example.org/"}, b""),
                 f"http://{ONION}/meta": (301, {"location": "http://169.254.169.254/latest/"}, b"")}
        with Environment(**BEHIND_TOR):
            self.assertEqual(self.fetch(pages, "https://public.example.org/"),
                             (f"http://{ONION}/page", "text/plain", b"onion text"))
            with self.assertRaises(self.module.ArgumentError) as caught:
                self.fetch(pages, f"http://{ONION}/out")
            self.assertIn("refused: ten.example.org resolves to 10.1.2.3, a local-network address", str(caught.exception))
            with self.assertRaises(self.module.ArgumentError) as caught:
                self.fetch(pages, f"http://{ONION}/meta")
            self.assertIn("the cloud metadata address", str(caught.exception))
        with Environment():
            with self.assertRaises(self.module.ArgumentError) as caught:
                self.fetch(pages, "https://public.example.org/")
            self.assertIn(".onion needs a Tor profile", str(caught.exception))

    def test_the_tool_answers_the_reason(self):
        with Environment():
            answer = asyncio.run(self.module.fetch_page(f"http://{ONION}/"))
        self.assertIn(".onion needs a Tor profile", answer["error"])


class Gowitness(AddressChecks, unittest.TestCase):
    name = "gowitness"
    private_setting = True

    def test_screenshot_many_refuses_before_the_first_page(self):
        with Environment():
            answer = asyncio.run(self.module.screenshot_many(["https://public.example.org/", f"http://{ONION}/"]))
        self.assertIn(".onion needs a Tor profile", answer[0]["error"])


class WhatWeb(AddressChecks, unittest.TestCase):
    name = "whatweb"
    private_setting = True

    def test_redirects_behind_tor(self):
        hops = {"https://public.example.org/": f"http://{ONION}/",
                f"http://{ONION}/": f"http://{ONION}/end", f"http://{ONION}/end": None,
                f"http://{ONION}/out": "http://lan.example.org/"}
        scanned = []

        async def scan(url, aggression):
            scanned.append(url)
            location = hops[url]
            return {"url": url, "http_status": 302 if location else 200,
                    "plugins": {"RedirectLocation": {"string": [location]}} if location else {}}

        with mock.patch.object(self.module, "scan", scan), Environment(**BEHIND_TOR):
            answer = asyncio.run(self.module.fingerprint("https://public.example.org/"))
            self.assertEqual(answer["final_url"], f"http://{ONION}/end")
            answer = asyncio.run(self.module.fingerprint(f"http://{ONION}/out"))
            self.assertIn("refused: lan.example.org resolves to 192.168.1.10, a local-network address",
                          answer["error"])
        self.assertNotIn("http://lan.example.org/", scanned)


class SearXNG(unittest.TestCase):
    """SEARXNG_URL: a .onion instance behind Tor, also with plain http; without Tor refused with the reason."""

    @classmethod
    def setUpClass(cls):
        cls.module = load("searxng")

    def test_onion_instance(self):
        with Environment(**BEHIND_TOR):
            self.assertEqual(self.module.instance(f"http://{ONION}/searx/"), f"http://{ONION}/searx")
            self.assertEqual(self.module.instance(f"https://{ONION}"), f"https://{ONION}")
        with Environment(tor="1"):
            self.assertEqual(self.module.instance(f"http://{ONION}"), f"http://{ONION}")  # no address check here
        with Environment():
            with self.assertRaises(self.module.ArgumentError) as caught:
                self.module.instance(f"http://{ONION}")
            self.assertIn(".onion needs a Tor profile (start the server behind one: --vpn TOR_PROFILE)",
                          str(caught.exception))
            with self.assertRaises(self.module.ArgumentError):
                self.module.instance("http://search.example.org")  # plain http to a name: as before
            self.assertEqual(self.module.instance("http://192.168.1.20:8888"), "http://192.168.1.20:8888")


if __name__ == "__main__":
    unittest.main()
