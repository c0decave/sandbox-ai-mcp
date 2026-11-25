"""The maigret server (servers/maigret): our own username checker on maigret 0.6.6's site database, offline - the
database (engines applied as maigret applies them, the entries this server leaves out and why), the verdicts of the
three check types and the error pages (maigret 0.6.6's checking.py and error_detection.py), usernames (URL-encoded, no
path of them), the host check (public addresses only, redirects included), requests against a stand-in transport
(methods, payloads, headers, redirects, the body bound), the call's deadline and paging, the tools' answers. With the
image's /opt/maigret/data.json at hand (CI runs this inside the image) the real database is loaded too."""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
from pathlib import Path
import re
import socket
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
FOLDER = ROOT / "servers" / "maigret"
FIXTURE = ROOT / "tests" / "fixtures" / "maigret-data.json"
IMAGE_DATA = "/opt/maigret/data.json"

try:
    import httpx
    import mcp  # noqa: F401 - the server's own dependency
    from mcp.server.fastmcp.exceptions import ToolError
except ImportError:
    httpx = mcp = None
    ToolError = Exception


def load():
    spec = importlib.util.spec_from_file_location("server_maigret_test", FOLDER / "src" / "server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(coro):
    return asyncio.run(coro)


@unittest.skipIf(mcp is None, "the server's requirements are not installed (pip install --require-hashes -r "
                              "servers/maigret/requirements.txt)")
class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load()

    def setUp(self):
        for name, value in (("DATA", str(FIXTURE)), ("_DB", None)):
            patcher = mock.patch.object(self.m, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.requests = []

    def site(self, name):
        return self.m.database().by_name[name.lower()]

    def serve(self, handler, check_host=None):
        """The server's HTTP client goes to HANDLER (a stand-in transport); every host passes the host check."""
        def recording(request):
            self.requests.append(request)
            return handler(request)
        transport = httpx.MockTransport(recording)

        def client():
            return httpx.AsyncClient(transport=transport, follow_redirects=False,
                                     timeout=httpx.Timeout(self.m.SITE_SECONDS, connect=6.0))
        for name, value in (("client", client), ("check_host", check_host or (lambda url: _none()))):
            patcher = mock.patch.object(self.m, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def refused(self, coro_or_call, *args, **kwargs) -> str:
        with self.assertRaises(ToolError) as caught:
            result = coro_or_call(*args, **kwargs)
            if asyncio.iscoroutine(result):
                run(result)
        return str(caught.exception)


async def _none():
    return None


class TheDatabase(Base):
    def test_engines_are_applied_as_maigret_applies_them(self):
        forum = self.site("ForumSite")
        self.assertEqual(forum.url, "{urlMain}/members/?username={username}")
        self.assertEqual(forum.check_type, "message")
        self.assertEqual(forum.absence, ["No such member"])
        self.assertEqual(forum.errors, {"Too busy": "Server busy", "Maintenance": "Down for maintenance"})
        self.assertEqual(forum.profile_url("alice"), "http://forum.test/members/?username=alice")
        self.assertEqual(forum.why_not, "")

    def test_what_is_left_out_and_why(self):
        reasons = {name: self.site(name).why_not for name in ("DisabledSite", "CookieSite", "ActivationSite",
                                                              "TlsSite", "OnionSite", "IdSite")}
        self.assertEqual(reasons, {"DisabledSite": "disabled in maigret's database",
                                   "CookieSite": "its request carries a cookie or token of the site",
                                   "ActivationSite": "needs maigret's activation (tokens fetched from the site)",
                                   "TlsSite": "behind a bot protection a plain client cannot pass (tls_fingerprint)",
                                   "OnionSite": "a tor entry", "IdSite": "takes a gaia_id, not a username"})
        ranked = [s.name for s in self.m.database().checkable([])]
        self.assertEqual(ranked, ["StatusSite", "MessageSite", "ProbeSite", "RedirectSite", "PostSite", "ForumSite"])
        self.assertEqual([s.name for s in self.m.database().checkable(["coding"])],
                         ["StatusSite", "ProbeSite", "PostSite"])

    def test_usernames_are_one_url_segment(self):
        for bad in ("../admin", "a/b", "a?b", "a b", "", "-x", "x" * 65, "a\nb", 5, "a#b", "a%2f"):
            with self.subTest(bad=bad):
                with self.assertRaises(self.m.Refused):
                    self.m.check_username(bad)
        self.assertEqual(self.m.check_username(" alice.b-c_1 "), "alice.b-c_1")
        self.assertEqual(self.m.check_username("Jürgen"), "Jürgen")
        self.assertEqual(self.site("StatusSite").profile_url("Jürgen"), "http://status.test/u/J%C3%BCrgen")
        self.assertFalse(self.site("ProbeSite").accepts("Alice1"))

    @unittest.skipUnless(os.path.isfile(IMAGE_DATA), "maigret's data.json is in the image only")
    def test_the_real_database(self):
        with mock.patch.object(self.m, "DATA", IMAGE_DATA), mock.patch.object(self.m, "_DB", None):
            db = self.m.database()
            self.assertEqual(len(db.sites), 5897)
            self.assertGreater(len(db.checkable([])), 4900)
            self.assertLess(db.checkable([]).index(db.by_name["github"]), 10, "ranked by maigret's alexaRank")
            github = db.by_name["github"]
            self.assertEqual(github.probe_url("blue"), "https://api.github.com/users/blue")
            self.assertEqual(db.by_name["twitter"].why_not, "needs maigret's activation (tokens fetched from the site)")


class Verdicts(Base):
    def test_the_three_check_types(self):
        status, message, redirect = self.site("StatusSite"), self.site("MessageSite"), self.site("RedirectSite")
        self.assertEqual(self.m.judge(status, "a", "", 200)[0], "found")
        self.assertEqual(self.m.judge(status, "a", "", 404)[0], "not found")
        self.assertEqual(self.m.judge(message, "a", '{"user_name": "a"}', 200)[0], "found")
        self.assertEqual(self.m.judge(message, "a", '{"user_name": "a"} User not found', 200),
                         ("not found", "the page says 'User not found'"))
        self.assertEqual(self.m.judge(message, "a", "<html>nothing</html>", 200)[0], "not found")
        self.assertEqual(self.m.judge(redirect, "a", "<html>", 200)[0], "found")
        self.assertEqual(self.m.judge(redirect, "a", "", 302)[0], "not found")
        # no presence marks: any page; a non-ASCII name must appear in it
        forum_like = self.site("RedirectSite")
        self.assertEqual(self.m.judge(forum_like, "Jürgen", "<html>someone else</html>", 200)[0], "not found")
        self.assertEqual(self.m.judge(forum_like, "Jürgen", "<html>Jürgen</html>", 200)[0], "found")

    def test_error_pages_are_no_evidence(self):
        forum, status = self.site("ForumSite"), self.site("StatusSite")
        self.assertEqual(self.m.error_page(forum, "Too busy now", 200), "Site-specific: Server busy")
        self.assertEqual(self.m.error_page(status, "<title>Just a moment...</title>", 200),
                         "Bot protection: Cloudflare challenge page")
        for code, text in ((403, "Access denied: 403 status code"), (401, "Login required: 401 status code"),
                           (429, "Rate limited: 429 status code"), (999, "Access denied: 999 status code"),
                           (503, "Server: 503 status code")):
            self.assertEqual(self.m.error_page(status, "", code), text)
        self.assertIsNone(self.m.error_page(status, "fine", 404))
        self.assertEqual(len(self.m.COMMON_ERRORS), 23, "maigret 0.6.6's errors.py COMMON_ERRORS, all of them")


class HostCheck(Base):
    def lookups(self, *addresses):
        async def resolve(host, port):
            if not addresses:
                raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
            return list(addresses)
        return mock.patch.object(self.m, "resolve", resolve)

    def check(self, url, *addresses):
        with self.lookups(*addresses):
            return run(self.m.check_host(url))

    def test_only_public_addresses(self):
        self.assertIsNone(self.check("https://example.org/x", "93.184.215.14"))
        for address in ("127.0.0.1", "10.0.0.1", "192.168.1.1", "169.254.169.254", "::1", "fd00::1", "100.64.0.1",
                        "::ffff:10.0.0.1"):
            with self.subTest(address=address):
                self.assertIn("non-public address", self.check("https://example.org/", "93.184.215.14", address))
        self.assertIn("IP address", self.check("http://10.0.0.1/", "10.0.0.1"))
        self.assertIn("not a public name", self.check("http://x.onion/", "10.192.0.1"))
        self.assertIn("not an http(s) address", self.check("ftp://example.org/", "93.184.215.14"))
        self.assertIn("name lookup failed", self.check("https://nowhere.example/"))


class Requests(Base):
    def test_the_probe_url_the_method_and_the_headers(self):
        self.serve(lambda request: httpx.Response(200, text="{}"))
        verdict = run(self.m.check(self.m.client(), self.site("ProbeSite"), "alice"))
        self.assertEqual((verdict.status, verdict.url), ("found", "http://probe.test/alice"))
        request = self.requests[-1]
        self.assertEqual(str(request.url), "http://api.probe.test/users/alice")
        self.assertEqual(request.method, "GET")
        self.assertEqual(request.headers["User-Agent"], self.m.USER_AGENT)
        self.assertNotIn("cookie", {k.lower() for k in request.headers})

    def test_a_post_payload_carries_the_name_as_maigret_formats_it(self):
        self.serve(lambda request: httpx.Response(200, text='{"name": "alice"}'))
        verdict = run(self.m.check(self.m.client(), self.site("PostSite"), "alice"))
        self.assertEqual(verdict.status, "found")
        request = self.requests[-1]
        self.assertEqual(request.method, "POST")
        self.assertEqual(json.loads(request.content), {"query": '{ user(name: "alice") }'})

    def test_redirects_are_followed_and_checked_except_for_response_url(self):
        def handler(request):
            if request.url.path.startswith("/u/"):
                return httpx.Response(302, headers={"Location": "http://status.test/final"})
            return httpx.Response(200, text="ok")
        seen = []

        async def check_host(url):
            seen.append(url)
            return "refused: status.test resolves to a non-public address" if url.endswith("/final") else None
        self.serve(handler, check_host)
        verdict = run(self.m.check(self.m.client(), self.site("StatusSite"), "alice"))
        self.assertEqual((verdict.status, verdict.detail),
                         ("error", "refused: status.test resolves to a non-public address"))
        self.assertEqual(seen, ["http://status.test/u/alice", "http://status.test/final"])
        self.serve(lambda request: httpx.Response(302, headers={"Location": "http://redirect.test/"}))
        verdict = run(self.m.check(self.m.client(), self.site("RedirectSite"), "alice"))
        self.assertEqual((verdict.status, verdict.http_status), ("not found", 302))

    def test_endless_redirects_and_broken_connections(self):
        self.serve(lambda request: httpx.Response(302, headers={"Location": str(request.url) + "x"}))
        self.assertEqual(run(self.m.check(self.m.client(), self.site("StatusSite"), "alice")).detail,
                         "more than 5 redirects")

        def refuse(request):
            raise httpx.ConnectError("refused", request=request)
        self.serve(refuse)
        self.assertEqual(run(self.m.check(self.m.client(), self.site("StatusSite"), "alice")).detail,
                         "could not connect")

    def test_the_body_is_read_up_to_its_bound(self):
        self.serve(lambda request: httpx.Response(200, content=b"x" * (3 << 20) + b'"user_name":'))
        verdict = run(self.m.check(self.m.client(), self.site("MessageSite"), "alice"))
        self.assertEqual(verdict.status, "not found", "a mark beyond 2 MiB is not read")


class Tools(Base):
    def test_search_username_pages_and_reports(self):
        def handler(request):
            host = request.url.host
            if host == "status.test":
                return httpx.Response(200, text="profile")
            if host == "message.test":
                return httpx.Response(200, text="User not found")
            if host == "redirect.test":
                return httpx.Response(429, text="slow down")
            return httpx.Response(404, text="null")
        self.serve(handler)
        text = run(self.m.search_username("alice", limit=4))
        self.assertTrue(text.startswith("'alice' on sites 1-4 of 6: 1 found, 2 not found, 1 could not be checked"),
                        text)
        self.assertIn("StatusSite: http://status.test/u/alice  [coding]", text)
        self.assertIn("Rate limited (1): RedirectSite", text)
        self.assertIn("next: search_username with offset=4", text)
        last = run(self.m.search_username("alice", offset=4))
        self.assertIn("on sites 5-6 of 6", last)
        self.assertNotIn("next:", last)
        self.assertIn("on sites 1-2 of 2 (tags: forum)", run(self.m.search_username("alice", tags="forum")))
        self.assertIn("offset: there are 6 sites", self.refused(self.m.search_username, "alice", offset=6))
        self.assertIn("limit: a whole number from 1 to 200", self.refused(self.m.search_username, "alice", limit=201))
        self.assertIn("tags: unknown nope", self.refused(self.m.search_username, "alice", tags="nope"))
        self.assertIn("username:", self.refused(self.m.search_username, "../x"))

    def test_the_call_keeps_its_deadline(self):
        async def slow(request):
            await asyncio.sleep(5)
            return httpx.Response(200)
        self.serve(slow)
        with mock.patch.object(self.m, "CALL_SECONDS", 1.5):
            text = run(self.m.search_username("alice"))
        self.assertIn("6 not reached within 1.5 s", text)

    def test_check_site_says_why(self):
        self.serve(lambda request: httpx.Response(200, text='{"user_name": 1}'))
        text = run(self.m.check_site("alice", "messagesite"))
        self.assertIn("MessageSite: found - the page has the profile's marks", text)
        self.assertIn("how it is judged: message; profile marks ['\"user_name\":']", text)
        self.assertIn("not checked by this server: needs maigret's activation",
                      self.refused(self.m.check_site, "alice", "ActivationSite"))
        self.assertIn("similar: StatusSite", self.refused(self.m.check_site, "alice", "Status"))
        self.assertIn("does not allow such a username", run(self.m.check_site("Alice1", "ProbeSite")))

    def test_list_sites_and_tags_send_nothing(self):
        self.serve(lambda request: self.fail("nothing is sent"))
        text = self.m.list_sites()
        self.assertTrue(text.startswith("12 sites in maigret 0.6.6's database (6 checked by this server)"))
        self.assertIn("CookieSite  http://cookie.test/  unranked  [social]  not checked: its request carries", text)
        self.assertIn("StatusSite  http://status.test/  #5  [coding]", self.m.list_sites(tag="coding"))
        self.assertIn("matching 'redir'", self.m.list_sites(name_filter="REDIR"))
        tags = self.m.list_tags()
        self.assertIn("6 of 12 sites are checked by this server", tags)
        self.assertIn("coding (3)", tags)
        self.assertIn("countries: de (1)", tags)
        self.assertEqual(self.requests, [])


class Packaging(unittest.TestCase):
    dockerfile = (FOLDER / "Dockerfile").read_text()

    def test_only_the_database_of_the_pinned_wheel_ships(self):
        for pin in ("ARG MAIGRET_SHA256=f382e7174d202a8002b2ac3ce3cde7c11900c506399dd6110f57b9256c4181c7",
                    "ARG DATA_SHA256=ef6ca66efa174209c10205ff86f7e975b591128681710639fdc786ff05e662da",
                    "ADD --checksum=sha256:${MAIGRET_SHA256} ${MAIGRET_URL}",
                    "unzip -q maigret.whl maigret/resources/data.json",
                    "COPY --from=data /build/maigret/resources/data.json /opt/maigret/data.json"):
            self.assertIn(pin, self.dockerfile)
        final = self.dockerfile[self.dockerfile.index("# --- the server ---"):]
        self.assertNotIn("maigret.whl", final)
        self.assertEqual(self.dockerfile.count("ef6ca66efa174209c10205ff86f7e975b591128681710639fdc786ff05e662da"), 2)
        self.assertIn('ENTRYPOINT ["/usr/bin/tini", "-s", "--", "/opt/venv/bin/python", "-I", "-u", '
                      '"/opt/mcp/server.py"]', self.dockerfile)
        self.assertEqual((FOLDER / "requirements.txt").read_text(),
                         (ROOT / "servers" / "jadx" / "requirements.txt").read_text())

    def test_the_entry_and_the_smoke_spec(self):
        entry = json.loads((FOLDER / "server.json").read_text())
        self.assertEqual(entry["network"], "full")
        self.assertEqual(entry["tor"]["support"], "yes")
        tools = json.loads((FOLDER / "tools.json").read_text())["tools"]
        spec = json.loads((FOLDER / "smoke.json").read_text())
        called = {c["tool"] for c in spec["calls"] if not c.get("expect_error")}
        self.assertEqual(sorted(called | set(spec.get("not_smoked", {}))), sorted(tools))

    def test_no_code_of_maigret_runs(self):
        source = (FOLDER / "src" / "server.py").read_text()
        imported = set(re.findall(r"^(?:import|from) ([\w.]+)", source, re.M))
        self.assertEqual(imported, {"__future__", "asyncio", "ipaddress", "json", "logging", "os", "re", "socket", "sys",
                                    "time", "urllib.parse", "httpx", "mcp", "mcp.server.fastmcp",
                                    "mcp.server.fastmcp.exceptions", "mcp.types"})
        for absent in ("exec(", "eval(", "db_meta", "raw.githubusercontent", "open(DATA, \"w"):
            self.assertNotIn(absent, source)

if __name__ == "__main__":
    unittest.main()
