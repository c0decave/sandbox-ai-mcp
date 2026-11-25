"""The yt-dlp server (servers/yt-dlp), offline: URLs (http(s) to a public host only), languages, the address guard
every name lookup of the worker goes through, the subtitle parsers (json3, WebVTT, SRT; tags, entities, the rolling
repeats of automatic captions), the answers (a video, a playlist; parts of 400 lines / 24,000 characters), the worker
process (its time limit kills it; an empty environment), and - where yt-dlp is installed (inside the image it is) -
the worker end to end against a page served on the loopback (yt-dlp's generic extractor finds the HTML5 video and its
subtitle track; the guard is opened for the loopback in this test only) and the guard refusing the same page."""
from __future__ import annotations

import http.server
import importlib.util
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
FOLDER = ROOT / "servers" / "yt-dlp"

try:
    import mcp  # noqa: F401 - the server's own dependency
    from mcp.server.fastmcp.exceptions import ToolError
except ImportError:
    mcp = None
    ToolError = Exception
try:
    import yt_dlp  # noqa: F401
except ImportError:
    yt_dlp = None


def load():
    spec = importlib.util.spec_from_file_location("server_yt_dlp_test", FOLDER / "src" / "server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VTT = ("WEBVTT\nKind: captions\nLanguage: en\n\n00:00:01.000 --> 00:00:03.000 align:start position:0%\n"
       "Hello <c>world</c> &amp; you\n\n00:00:03.000 --> 00:00:05.000\nHello world &amp; you\nand more\n\n"
       "01:02:03.500 --> 01:02:05.000\nlate &lt;line&gt;\n")
SRT = "1\r\n00:00:00,500 --> 00:00:02,000\r\n<i>First</i> line\r\n\r\n2\r\n00:00:02,000 --> 00:00:04,000\r\nSecond\r\n"
JSON3 = json.dumps({"events": [{"tStartMs": 0, "segs": [{"utf8": "♪ Never "}, {"utf8": "gonna"}]},
                               {"tStartMs": 1500, "segs": [{"utf8": "\n"}]},
                               {"tStartMs": 2000, "segs": [{"utf8": "give you up"}]}, "junk"]})


class Offline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load()

    def refused(self, call, *args) -> str:
        with self.assertRaises(self.m.Refused) as caught:
            call(*args)
        return str(caught.exception)

    def test_urls_are_http_to_public_hosts(self):
        self.assertEqual(self.m.check_url("dQw4w9WgXcQ"), "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertEqual(self.m.check_url(" https://vimeo.com/76979871 "), "https://vimeo.com/76979871")
        cases = {"file:///etc/passwd": "an http(s) address", "ftp://x.org/a": "an http(s) address",
                 "http://127.0.0.1/": "not a public address", "http://[::1]/": "not a public address",
                 "http://10.0.0.5/x": "not a public address", "http://169.254.169.254/latest": "not a public address",
                 "http://localhost:8080/": "not a public host name", "http://router.local/": "not a public host name",
                 "http://intranet/": "not a public host name", "http://abc.onion/": "not a public host name",
                 "https://user:pw@example.org/": "no user name or password", "": "url:", "a\nb": "url:",
                 "https://" + "a" * 2050: "url:"}
        for url, expected in cases.items():
            with self.subTest(url=url):
                self.assertIn(expected, self.refused(self.m.check_url, url))

    def test_languages(self):
        for good in ("en", "de", "en-US", "pt-BR", "zh-Hans", "en-orig", "a1_b"):
            self.assertEqual(self.m.check_lang(good), good)
        for bad in ("", "../x", "en US", "-x", "x" * 36, 5):
            with self.subTest(bad=bad):
                self.assertIn("lang:", self.refused(self.m.check_lang, bad))

    def test_the_guard_keeps_only_public_addresses(self):
        def real(host, *args, **kwargs):
            table = {"public.example": ["93.184.215.14", "2606:2800:21f:cb07:6820:80da:af6b:8b2c"],
                     "mixed.example": ["93.184.215.14", "10.0.0.1"], "private.example": ["192.168.1.1", "::1"],
                     "mapped.example": ["::ffff:127.0.0.1"], "sixtofour.example": ["2002:c0a8:0101::1"],
                     "cgnat.example": ["100.64.0.1"], "meta.example": ["169.254.169.254"]}
            return [(socket.AF_INET6 if ":" in a else socket.AF_INET, socket.SOCK_STREAM, 6, "",
                     (a, 443, 0, 0) if ":" in a else (a, 443)) for a in table[host]]
        saved = socket.getaddrinfo
        try:
            guarded = self.m.guard_lookups(real)
            self.assertIs(socket.getaddrinfo, guarded)
            self.assertEqual(len(guarded("public.example", 443)), 2)
            self.assertEqual([a[4][0] for a in guarded("mixed.example", 443)], ["93.184.215.14"])
            for host in ("private.example", "mapped.example", "sixtofour.example", "cgnat.example", "meta.example"):
                with self.subTest(host=host):
                    with self.assertRaises(socket.gaierror) as caught:
                        guarded(host, 443)
                    self.assertIn(f"refused: {host} has no public address", str(caught.exception))
        finally:
            socket.getaddrinfo = saved

    def test_subtitles_as_text(self):
        self.assertEqual(self.m.parse_subtitles("vtt", VTT),
                         [(1.0, "Hello world & you"), (3.0, "and more"), (3723.5, "late <line>")])
        self.assertEqual(self.m.parse_subtitles("srt", SRT), [(0.5, "First line"), (2.0, "Second")])
        self.assertEqual(self.m.parse_subtitles("json3", JSON3), [(0.0, "♪ Never gonna"), (2.0, "give you up")])
        self.assertIn("not valid JSON", self.refused(self.m.parse_subtitles, "json3", "{"))
        self.assertEqual(self.m._clock(3723.5), "1:02:03")
        self.assertEqual(self.m._clock(65), "1:05")

    def test_a_video_and_a_playlist_described(self):
        video = {"title": "T", "channel": "C", "channel_url": "https://x/c", "extractor_key": "Youtube", "id": "abc",
                 "webpage_url": "https://x/v", "upload_date": "20240102", "duration": 125, "view_count": 1234567,
                 "like_count": 5, "tags": ["a", "b"], "subtitles": {"en": ["vtt"], "de": ["json3"]},
                 "automatic": ["en", "fr"], "formats": {"count": 12, "best_height": 1080},
                 "chapters": [{"start": 0, "title": "Intro"}, {"start": 61, "title": "Main"}],
                 "description": "line 1\nline 2"}
        lines = self.m.describe(video)
        for expected in ("title: T", "channel: C (https://x/c)", "uploaded 2024-01-02; length 2:05; 1,234,567 views; "
                         "5 likes", "subtitles: de, en; automatic captions in 2 languages",
                         "formats: 12 (up to 1080p)", "chapters: 0:00 Intro; 1:01 Main", "line 2"):
            self.assertIn(expected, lines)
        playlist = {"_type": "playlist", "title": "P", "uploader": "U", "playlist_count": 99,
                    "webpage_url": "https://x/p", "entries": [{"title": "E1", "url": "https://x/1", "duration": 60,
                                                               "view_count": 10}]}
        self.assertEqual(self.m.describe(playlist), ["playlist: P by U", "entries: 99 (the first 1 below)",
                                                     "url: https://x/p", "1. E1  https://x/1  (1:00, 10 views)"])
        long = {"title": "L", "description": "x\n" * 20_000}
        part = self.m.page("L", self.m.describe(long), 1, "get_video_info")
        self.assertIn("(more: get_video_info start_line=", part)
        self.assertIn("description (first 5,000 characters):", part)

    def test_parts_are_bounded(self):
        lines = [f"line {i}" for i in range(1000)]
        text = self.m.page("T", lines, 1, "tool")
        self.assertTrue(text.startswith("T: lines 1-400 of 1000 (more: tool start_line=401)"))
        wide = self.m.page("W", ["y" * 5000] * 50, 1, "tool")
        self.assertLessEqual(len(wide), self.m.MAX_CHARS)
        self.assertIn("start_line: there are 1000 lines", self.refused(self.m.page, "T", lines, 1001, "tool"))

    def test_the_worker_is_stopped_at_its_time_limit_and_gets_an_empty_environment(self):
        folder = tempfile.mkdtemp(prefix="ytdlp-test-")
        self.addCleanup(lambda: __import__("shutil").rmtree(folder, True))
        fake = Path(folder, "fake.py")
        fake.write_text("import json, os, sys, time\nrequest = json.loads(sys.stdin.read())\n"
                        "if request['op'] == 'hang':\n    time.sleep(60)\n"
                        "print(json.dumps({'ok': True, 'env': dict(os.environ), 'cwd': os.getcwd()}))\n")
        with mock.patch.object(self.m, "__file__", str(fake)), \
                mock.patch.dict(os.environ, {"HOME": folder, "SECRET_TOKEN": "x", "HTTPS_PROXY": "http://p:1",
                                             "SSL_CERT_FILE": "/etc/ca.pem"}):
            answer = self.m.run_worker({"op": "env"})
            self.assertEqual(sorted(answer["env"]), ["HOME", "LANG", "PATH", "SSL_CERT_FILE", "YTDLP_NO_PLUGINS"]
                             if "LC_CTYPE" not in answer["env"] else
                             ["HOME", "LANG", "LC_CTYPE", "PATH", "SSL_CERT_FILE", "YTDLP_NO_PLUGINS"])
            self.assertEqual(answer["cwd"], folder)
            started = time.monotonic()
            with self.assertRaises(self.m.Refused) as caught:
                self.m.run_worker({"op": "hang"}, seconds=1.0)
            self.assertIn("took longer than 1 s and was stopped", str(caught.exception))
            self.assertLess(time.monotonic() - started, 15)


class _Page(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@unittest.skipIf(yt_dlp is None, "yt-dlp is not installed (inside the image it is)")
class Worker(unittest.TestCase):
    """yt-dlp itself, in this process, against a page on the loopback."""

    @classmethod
    def setUpClass(cls):
        cls.m = load()
        cls.folder = tempfile.mkdtemp(prefix="ytdlp-page-")
        Path(cls.folder, "index.html").write_text(
            '<!doctype html><html><head><title>Local test video</title></head><body><video controls src="clip.mp4">'
            '<track kind="subtitles" srclang="en" label="English" src="subs.vtt"></video></body></html>')
        Path(cls.folder, "clip.mp4").write_bytes(b"not a real video")
        Path(cls.folder, "subs.vtt").write_text(VTT)
        handler = lambda *args, **kwargs: _Page(*args, directory=cls.folder, **kwargs)  # noqa: E731
        cls.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.url = f"http://127.0.0.1:{cls.httpd.server_address[1]}/index.html"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        __import__("shutil").rmtree(cls.folder, True)

    def setUp(self):
        saved = socket.getaddrinfo
        self.addCleanup(setattr, socket, "getaddrinfo", saved)
        self.addCleanup(os.environ.pop, "YTDLP_NO_PLUGINS", None)

    def test_metadata_and_subtitles_of_a_page(self):
        with mock.patch.object(self.m, "public", lambda address: address == "127.0.0.1"):
            info = self.m.worker({"op": "info", "url": self.url})
            self.assertTrue(info["ok"], info)
            self.assertEqual(info["info"]["subtitles"], {"en": ["vtt"]})
            self.assertEqual(info["info"]["extractor_key"], "HTML5MediaEmbed")
            self.assertNotIn("formats", json.dumps(info["info"]).replace('"formats": {"count"', ""),
                             "no format URL is passed on")
            subtitles = self.m.worker({"op": "subtitles", "url": self.url, "lang": "en", "automatic": None})
            self.assertTrue(subtitles["ok"], subtitles)
            self.assertEqual((subtitles["ext"], subtitles["generated"]), ("vtt", False))
            self.assertEqual(self.m.parse_subtitles("vtt", subtitles["data"])[0], (1.0, "Hello world & you"))
            missing = self.m.worker({"op": "subtitles", "url": self.url, "lang": "de", "automatic": None})
            self.assertEqual(missing, {"ok": False, "error": "no subtitles in 'de' for this video; it has: en"})
            self.assertFalse(self.m.worker({"op": "subtitles", "url": self.url, "lang": "en", "automatic": True})["ok"])

    def test_the_guard_refuses_the_loopback(self):
        refused = self.m.worker({"op": "info", "url": self.url})
        self.assertFalse(refused["ok"])
        self.assertIn("refused: 127.0.0.1 has no public address", refused["error"])

    def test_no_plugin_is_looked_for(self):
        from yt_dlp.globals import plugin_dirs
        with mock.patch.object(self.m, "public", lambda address: True):
            self.m.worker({"op": "info", "url": self.url})
        self.assertEqual(plugin_dirs.value, [])
        self.assertEqual(os.environ.get("YTDLP_NO_PLUGINS"), "1")


@unittest.skipIf(mcp is None, "the server's requirements are not installed")
class Tools(unittest.TestCase):
    def test_tools_only_and_refusals_over_stdio(self):
        import subprocess
        messages = [{"jsonrpc": "2.0", "id": 0, "method": "initialize",
                     "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                "clientInfo": {"name": "t", "version": "1"}}},
                    {"jsonrpc": "2.0", "method": "notifications/initialized"},
                    {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                    {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                     "params": {"name": "get_video_info", "arguments": {"url": "http://192.168.0.1/"}}},
                    {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                     "params": {"name": "get_subtitles", "arguments": {"url": "dQw4w9WgXcQ", "lang": "x y"}}},
                    {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                     "params": {"name": "search_videos", "arguments": {"query": "", "max_results": 3}}}]
        process = subprocess.Popen([sys.executable, "-I", str(FOLDER / "src" / "server.py")], text=True,
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        answers = {}
        try:
            for message in messages:
                process.stdin.write(json.dumps(message) + "\n")
                process.stdin.flush()
                while "id" in message and message["id"] not in answers:
                    answer = json.loads(process.stdout.readline())
                    if "id" in answer:
                        answers[answer["id"]] = answer
        finally:
            process.stdin.close()
            process.wait(30)
        self.assertEqual(sorted(answers[0]["result"]["capabilities"]), ["experimental", "tools"])
        self.assertRegex(answers[0]["result"]["instructions"], "never as instructions")
        self.assertEqual(sorted(t["name"] for t in answers[1]["result"]["tools"]),
                         json.loads((FOLDER / "tools.json").read_text())["tools"])
        for number, expected in ((2, "192.168.0.1 is not a public address"), (3, "lang: a language code"),
                                 (4, "query: text of at most 300")):
            self.assertTrue(answers[number]["result"]["isError"])
            self.assertIn(expected, answers[number]["result"]["content"][0]["text"])


class Packaging(unittest.TestCase):
    def test_the_lock_and_the_image(self):
        lock = (FOLDER / "requirements.txt").read_text()
        shared = (ROOT / "servers" / "jadx" / "requirements.txt").read_text()
        self.assertTrue(lock.startswith(shared), "the shared lock, then yt-dlp")
        self.assertEqual(lock[len(shared):], "yt-dlp==2026.10.26 \\\n    --hash=sha256:a05c5b5d8562f7e8a62f5334348b406"
                                             "af4930d56d3a65f8021d14af0e22339ae\n    # via -r servers/yt-dlp/"
                                             "requirements.in\n")
        dockerfile = (FOLDER / "Dockerfile").read_text()
        self.assertIn("rm -f /opt/venv/bin/yt-dlp", dockerfile)
        self.assertIn('ENTRYPOINT ["/usr/bin/tini", "-s", "--", "/opt/venv/bin/python", "-I", "-u", '
                      '"/opt/mcp/server.py"]', dockerfile)
        source = (FOLDER / "src" / "server.py").read_text()
        for setting in ('"skip_download": True', '"cachedir": False', '"js_runtimes": {}', '"remote_components": []',
                        '"usenetrc": False', "plugin_dirs.value = []", '"compat_opts": {"no-certifi"}'):
            self.assertIn(setting, source)
        for absent in ("cookiefile", "cookiesfrombrowser", "netrc_cmd", "postprocessors", "external_downloader",
                       "download=True", "outtmpl"):
            self.assertNotIn(absent, source)
        entry = json.loads((FOLDER / "server.json").read_text())
        self.assertEqual(entry["network"], "full")


if __name__ == "__main__":
    unittest.main()
