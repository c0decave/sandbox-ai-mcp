"""The youtube server (servers/youtube), without network: a fake Google (token endpoint, resumable upload,
thumbnails, captions, videos, channels, playlist items) in place of the real one (an httpx transport): token
refresh and its errors, the resumable upload with a chunk resumed after a 503, the upload session's host
checked, thumbnails, captions, partial metadata updates, the list, every refused field and path (outside
/upload, links, devices, pipes, hard links, other users' files), the scopes, the quota, and no token, client
secret or upload session in any answer or log line. authorize.py's loopback flow with a fake browser and a fake
token endpoint. CI runs this inside the image too (tests/test_own_servers.py test_youtube)."""
from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import struct
import sys
import tempfile
import unittest
from unittest import mock
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "servers" / "youtube"

try:
    import httpx
    import mcp  # noqa: F401 - the server's own dependency
except ImportError:
    httpx = mcp = None

CLIENT_ID = "123456789012-abcdefghijklmnopqrstuvw" "xyz012345.apps.googleusercontent.com"  # (made up; split so that no scanner takes it for a real one)
CLIENT_SECRET = "GOCSPX-Ab12Cd34Ef" "56Gh78Ij90Kl12Mn34"  # (made up; split so that no scanner takes it for a real one)
REFRESH = "1//09AbCdEfGhIjKlMnOpQrStUvWxYz-0123456789_abcdefghijklmnopqrstuvwxyzABCDEFG"
ENV = {"YOUTUBE_CLIENT_ID": CLIENT_ID, "YOUTUBE_CLIENT_SECRET": CLIENT_SECRET, "YOUTUBE_REFRESH_TOKEN": REFRESH,
       "YOUTUBE_ALLOW_PUBLIC": "", "YOUTUBE_MAX_UPLOAD_MB": ""}
UPLOAD = "https://www.googleapis.com/auth/youtube.upload"
READONLY = "https://www.googleapis.com/auth/youtube.readonly"
FORCE_SSL = "https://www.googleapis.com/auth/youtube.force-ssl"
VIDEO = "AbCdEfGhIj0"
SESSION_ID = "ADPycdvSecretUploadSession0123456789"
MP4_HEAD = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom"


def load():
    spec = importlib.util.spec_from_file_location("server_youtube_test", SERVER / "src" / "server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_authorize():
    spec = importlib.util.spec_from_file_location("youtube_authorize_test", SERVER / "src" / "authorize.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def png(width=1280, height=720, pad=200) -> bytes:
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + ihdr + b"\0" * 4 + b"\0" * pad


def jpeg(width=1280, height=720) -> bytes:
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\0" + b"\x01\x01\0\0\x01\0\x01\0\0"
    sof0 = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, height, width, 1) + b"\x01\x11\0"
    return b"\xff\xd8" + app0 + sof0 + b"\xff\xd9"


SRT = b"1\n00:00:01,000 --> 00:00:04,000\nHallo und willkommen.\n\n2\n00:00:05,000 --> 00:00:08,000\nTschuess.\n"


class FakeGoogle:
    """Google's token endpoint and the YouTube Data API v3, as far as the server uses them."""

    def __init__(self, scope=f"{UPLOAD} {READONLY} {FORCE_SSL}"):
        self.scope = scope
        self.requests: list = []          # (method, URL, headers, body) of every request
        self.tokens: list[str] = []
        self.token_error = None           # (status, JSON) the token endpoint answers instead
        self.reject_next_api = 0          # API requests answered 401 (an access token Google dropped)
        self.metadata = None              # the JSON of the upload session's start
        self.received = bytearray()
        self.size = None
        self.chunk_puts = 0
        self.fail_chunks = {}             # chunk PUT number -> (status, bytes of it kept)
        self.fail_queries = 0             # status queries answered 503
        self.query_status = None          # status every status query answers (404: the session is gone)
        self.location = f"https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&upload_id={SESSION_ID}"
        self.api_error = {}               # path -> (status, JSON) answered instead
        self.video = {"id": VIDEO, "snippet": {"title": "Old title", "description": "Old description",
                                               "tags": ["alt", "tag"], "categoryId": "27", "defaultLanguage": "de",
                                               "defaultAudioLanguage": "de", "channelId": "UCx",
                                               "thumbnails": {"default": {}}},
                      "status": {"privacyStatus": "private", "uploadStatus": "processed", "embeddable": True,
                                 "license": "youtube", "publicStatsViewable": True, "selfDeclaredMadeForKids": False,
                                 "madeForKids": False, "containsSyntheticMedia": True}}
        self.updates: list = []

    def transport(self):
        return httpx.MockTransport(self.handle)

    @staticmethod
    def json(status, data, headers=None):
        return httpx.Response(status, json=data, headers=headers)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, str(request.url), dict(request.headers), request.content))
        url = request.url
        if url.host == "oauth2.googleapis.com" and url.path == "/token":
            return self.token(request)
        if url.host != "www.googleapis.com":
            return httpx.Response(599)  # never reached: the server checks the host first
        if request.headers.get("authorization") != f"Bearer {self.tokens[-1] if self.tokens else ''}" \
                or self.reject_next_api:
            self.reject_next_api = max(self.reject_next_api - 1, 0)
            return self.json(401, {"error": {"code": 401, "message": "Invalid Credentials", "errors": [
                {"reason": "authError", "message": "Invalid Credentials"}]}})
        if url.path in self.api_error:
            return self.json(*self.api_error[url.path])
        if url.path == "/upload/youtube/v3/videos" and request.method == "POST":
            self.metadata = json.loads(request.content)
            self.size = int(request.headers["x-upload-content-length"])
            return httpx.Response(200, headers={"Location": self.location})
        if url.path == "/upload/youtube/v3/videos" and request.method == "PUT":
            return self.chunk(request)
        if url.path == "/upload/youtube/v3/thumbnails/set":
            return self.json(200, {"kind": "youtube#thumbnailSetResponse", "items": [{"default": {"url": "x"}}]})
        if url.path == "/upload/youtube/v3/captions":
            return self.json(200, {"id": "AUieDaZcaption", "snippet": {"videoId": VIDEO, "language": "de",
                                                                       "name": "Deutsch", "status": "serving"}})
        if url.path == "/youtube/v3/videos" and request.method == "GET":
            if url.params.get("part") == "status":
                known = {VIDEO: self.video["status"],
                         "ZyXwVuTsRq9": {"privacyStatus": "private", "uploadStatus": "rejected",
                                         "rejectionReason": "duplicate"}}
                return self.json(200, {"items": [{"id": vid, "status": known[vid]}
                                                 for vid in url.params.get("id", "").split(",") if vid in known]})
            found = [self.video] if url.params.get("id") == self.video["id"] else []
            return self.json(200, {"items": found})
        if url.path == "/youtube/v3/videos" and request.method == "PUT":
            body = json.loads(request.content)
            self.updates.append((url.params.get("part"), body))
            return self.json(200, {**self.video, **body})
        if url.path == "/youtube/v3/channels":
            return self.json(200, {"items": [{"id": "UCchannel", "snippet": {"title": "My channel"},
                                              "contentDetails": {"relatedPlaylists": {"uploads": "UUchannel"}}}]})
        if url.path == "/youtube/v3/playlistItems":
            return self.json(200, {"items": [
                {"snippet": {"title": "First", "publishedAt": "2026-11-01T00:00:00Z"},
                 "contentDetails": {"videoId": VIDEO, "videoPublishedAt": "2026-11-01T00:00:00Z"}},
                {"snippet": {"title": "Second"}, "contentDetails": {"videoId": "ZyXwVuTsRq9"}},
                {"snippet": {"title": "broken"}, "contentDetails": {"videoId": "../../etc"}}]})
        return self.json(404, {"error": {"code": 404, "message": f"no fake for {request.method} {url.path}"}})

    def token(self, request):
        form = urllib.parse.parse_qs(request.content.decode())
        assert request.method == "POST" and request.headers["content-type"] == "application/x-www-form-urlencoded"
        if self.token_error:
            return self.json(*self.token_error)
        assert form == {"client_id": [CLIENT_ID], "client_secret": [CLIENT_SECRET], "refresh_token": [REFRESH],
                        "grant_type": ["refresh_token"]}, form
        self.tokens.append(f"ya29.a0AfakeAccessToken{len(self.tokens) + 1:04d}xyz")
        return self.json(200, {"access_token": self.tokens[-1], "expires_in": 3599, "scope": self.scope,
                               "token_type": "Bearer"})

    def chunk(self, request):
        assert request.url.params.get("upload_id") == SESSION_ID
        done = {"id": VIDEO, "snippet": self.metadata["snippet"],
                "status": {**self.metadata["status"], "uploadStatus": "uploaded"}}
        ranged = request.headers["content-range"]
        if ranged == f"bytes */{self.size}":
            assert request.content == b""
            if self.query_status:
                return self.json(self.query_status, {"error": {"code": self.query_status, "message": "gone"}})
            if self.fail_queries:
                self.fail_queries -= 1
                return self.json(503, {"error": {"code": 503, "message": "Backend Error"}})
            if len(self.received) == self.size:
                return self.json(201, done)
            return httpx.Response(308, headers={"Range": f"bytes=0-{len(self.received) - 1}"} if self.received else {})
        start, end, total = map(int, re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", ranged).groups())
        assert total == self.size and start == len(self.received) and end - start + 1 == len(request.content)
        self.chunk_puts += 1
        if self.chunk_puts in self.fail_chunks:
            status, kept = self.fail_chunks[self.chunk_puts]
            self.received += request.content[:kept]
            return self.json(status, {"error": {"code": status, "message": "Backend Error"}})
        self.received += request.content
        if len(self.received) == self.size:
            return self.json(200, done)
        return httpx.Response(308, headers={"Range": f"bytes=0-{len(self.received) - 1}"})

    def paths(self):
        return [urllib.parse.urlsplit(url).path for _, url, _, _ in self.requests]

    def everything(self) -> str:
        return "\n".join(f"{m} {u} {h}" for m, u, h, _ in self.requests)


@unittest.skipIf(mcp is None, "the server's requirements are not installed (pip install --require-hashes -r "
                              "servers/youtube/requirements.txt)")
class WithFakeGoogle(unittest.TestCase):
    module = None

    @classmethod
    def setUpClass(cls):
        cls.module = load()

    def setUp(self):
        self.google = FakeGoogle()
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name, "upload")
        self.root.mkdir()
        m = self.module
        self.sleeps: list[float] = []

        async def no_sleep(seconds):
            self.sleeps.append(seconds)

        for name, value in (("_transport", self.google.transport()), ("UPLOAD_ROOT", str(self.root)),
                            ("AUTH", m.Auth()), ("_upload_running", asyncio.Lock()), ("_sleep", no_sleep),
                            ("CHUNK", 256 << 10)):
            patcher = mock.patch.object(m, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.dict(os.environ, ENV)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.log = io.StringIO()
        old = m._handler.setStream(self.log)
        self.addCleanup(m._handler.setStream, old)

    def call(self, tool, **arguments):
        return asyncio.run(getattr(self.module, tool)(**arguments))

    def file(self, name, data: bytes, mode=0o644) -> str:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        path.chmod(mode)
        return str(path)

    def video_file(self, name="video.mp4", size=700_000) -> tuple[str, bytes]:
        data = MP4_HEAD + bytes((i * 7) % 251 for i in range(size - len(MP4_HEAD)))
        return self.file(name, data), data

    def upload(self, path, **overrides):
        arguments = {"path": path, "title": "Mein Video", "made_for_kids": False, "contains_synthetic_media": True}
        arguments.update(overrides)
        return self.call("upload_video", **arguments)

    def assertNoSecrets(self, *texts):
        everything = "\n".join(json.dumps(t) if not isinstance(t, str) else t for t in texts)
        for secret in [CLIENT_SECRET, REFRESH, SESSION_ID, *self.google.tokens]:
            self.assertNotIn(secret, everything)
        self.assertNotIn("ya29.", everything)


class Upload(WithFakeGoogle):
    def test_resumable_upload_resumes_a_chunk_after_a_503(self):
        path, data = self.video_file()
        self.google.fail_chunks = {2: (503, 1000)}  # the second PUT fails after Google kept 1000 of its bytes
        answer = self.upload(path, description="Wie man es macht.", tags=["tutorial", "sandbox ai"],
                             category_id="27", default_language="de",
                             chapters=[{"start": "0:00", "title": "Intro"}, "0:15 Aufbau",
                                       {"start": "1:02", "title": "Ende"}])
        self.assertNotIn("error", answer, answer)
        self.assertEqual(bytes(self.google.received), data)
        self.assertEqual(answer["video_id"], VIDEO)
        self.assertEqual(answer["url"], f"https://youtu.be/{VIDEO}")
        self.assertEqual(answer["privacy"], "private")
        self.assertEqual(answer["resumed_after_errors"], 1)
        self.assertEqual(answer["bytes"], len(data))
        self.assertEqual(answer["chapters"], 3)
        self.assertIn("1600", answer["quota"])
        self.assertIn("audit", answer["note"])
        self.assertEqual(len(self.sleeps), 1)
        meta = self.google.metadata
        self.assertEqual(meta["snippet"], {"title": "Mein Video", "categoryId": "27", "tags": ["tutorial", "sandbox ai"],
                                           "description": "Wie man es macht.\n\n0:00 Intro\n0:15 Aufbau\n1:02 Ende",
                                           "defaultLanguage": "de", "defaultAudioLanguage": "de"})
        self.assertEqual(meta["status"], {"privacyStatus": "private", "selfDeclaredMadeForKids": False,
                                          "containsSyntheticMedia": True})
        start = next(r for r in self.google.requests if r[0] == "POST" and "/upload/youtube/v3/videos" in r[1])
        self.assertIn("uploadType=resumable", start[1])
        self.assertIn("part=snippet%2Cstatus", start[1])
        self.assertEqual(start[2]["x-upload-content-type"], "video/mp4")
        self.assertEqual(start[2]["x-upload-content-length"], str(len(data)))
        ranges = [r[2]["content-range"] for r in self.google.requests if r[0] == "PUT"]
        chunk = 256 << 10
        self.assertEqual(ranges, [f"bytes 0-{chunk - 1}/{len(data)}", f"bytes {chunk}-{2 * chunk - 1}/{len(data)}",
                                  f"bytes */{len(data)}",  # how much do you have? 1000 bytes of the second
                                  f"bytes {chunk + 1000}-{2 * chunk + 999}/{len(data)}",  # chunks of 256 KiB on
                                  f"bytes {2 * chunk + 1000}-{len(data) - 1}/{len(data)}"])
        self.assertEqual(len(self.google.tokens), 1, "one token for the whole upload")
        self.assertNoSecrets(answer, self.log.getvalue())
        self.assertIn("upload_video: ", self.log.getvalue())

    def test_unlisted_and_public_only_when_allowed(self):
        path, _ = self.video_file()
        refused = self.upload(path, privacy="public")
        self.assertIn("YOUTUBE_ALLOW_PUBLIC=1", refused["error"])
        self.assertEqual(self.google.requests, [], "refused before anything is sent")
        self.assertEqual(self.upload(path, privacy="unlisted")["privacy"], "unlisted")
        with mock.patch.dict(os.environ, {"YOUTUBE_ALLOW_PUBLIC": "1"}):
            self.google.received.clear()
            self.assertEqual(self.upload(path, privacy="public")["privacy"], "public")
        with mock.patch.dict(os.environ, {"YOUTUBE_ALLOW_PUBLIC": "yes"}):
            self.assertIn("error", self.upload(path, privacy="public"))

    def test_the_session_must_be_googles(self):
        path, _ = self.video_file()
        for location in ("https://evil.example/upload/youtube/v3/videos?upload_id=x",
                         "http://www.googleapis.com/upload/youtube/v3/videos?upload_id=x",
                         "https://www.googleapis.com:8443/upload/youtube/v3/videos?upload_id=x",
                         "https://www.googleapis.com/youtube/v3/videos?upload_id=x"):
            with self.subTest(location=location):
                self.google.location = location
                self.google.requests.clear()
                answer = self.upload(path)
                self.assertIn("error", answer)
                self.assertFalse(any("evil" in r[1] or r[0] == "PUT" for r in self.google.requests),
                                 "no byte and no token go to another address")

    def test_gives_up_after_the_retries(self):
        path, _ = self.video_file()
        self.google.fail_chunks = {1: (503, 0)}
        self.google.fail_queries = 100
        answer = self.upload(path)
        self.assertIn("failed 8 times in a row", answer["error"])
        self.assertIn("nothing was published", answer["error"])
        self.assertEqual(len(self.sleeps), 7)  # 8 failures, 7 waits between them
        self.assertLess(len(self.google.requests), 20)

    def test_an_expired_session(self):
        path, _ = self.video_file()
        self.google.fail_chunks = {1: (500, 0)}
        self.google.query_status = 404
        self.assertIn("upload session expired", self.upload(path)["error"])

    def test_a_broken_connection_is_resumed(self):
        path, data = self.video_file()
        transport = self.google.transport()
        broken = {"n": 0}

        async def flaky(request):
            if request.method == "PUT" and request.headers["content-range"].startswith("bytes 262144-"):
                broken["n"] += 1
                if broken["n"] == 1:
                    raise httpx.ConnectError("connection reset")
            return await transport.handle_async_request(request)

        with mock.patch.object(self.module, "_transport", httpx.MockTransport(flaky)):
            answer = self.upload(path)
        self.assertEqual(answer["resumed_after_errors"], 1, answer)
        self.assertEqual(bytes(self.google.received), data)

    def test_google_errors_are_bounded(self):
        path, _ = self.video_file()
        self.google.api_error["/upload/youtube/v3/videos"] = (400, {"error": {
            "code": 400, "message": "m" * 5000, "errors": [{"reason": f"r{i}" * 50} for i in range(500)]}})
        error = self.upload(path)["error"]
        self.assertLess(len(error), 800)
        self.assertIn("r4r4", error)
        self.assertNotIn("r5r5", error)  # five reason codes at most

    def test_quota_exceeded_is_named(self):
        path, _ = self.video_file()
        self.google.api_error["/upload/youtube/v3/videos"] = (403, {"error": {
            "code": 403, "message": "The request cannot be completed because you have exceeded your quota.",
            "errors": [{"reason": "quotaExceeded", "domain": "youtube.quota"}]}})
        error = self.upload(path)["error"]
        self.assertIn("quotaExceeded", error)
        self.assertIn("daily YouTube quota", error)
        self.assertIn("1600", error)
        self.assertIn("Pacific", error)

    def test_one_upload_at_a_time(self):
        path, _ = self.video_file()

        async def both():
            await self.module._upload_running.acquire()
            try:
                return await self.module.upload_video(path=path, title="x", made_for_kids=False,
                                                      contains_synthetic_media=False)
            finally:
                self.module._upload_running.release()

        self.assertIn("another upload is running", asyncio.run(both())["error"])

    def test_the_size_cap(self):
        path, _ = self.video_file(size=3 << 20)
        with mock.patch.dict(os.environ, {"YOUTUBE_MAX_UPLOAD_MB": "2"}):
            self.assertIn("more than the 2097152", self.upload(path)["error"])
        with mock.patch.dict(os.environ, {"YOUTUBE_MAX_UPLOAD_MB": "999999999"}):
            self.assertIn("YOUTUBE_MAX_UPLOAD_MB", self.upload(path)["error"])
        self.assertEqual(self.google.requests, [])


class Tokens(WithFakeGoogle):
    def test_refreshed_once_kept_in_memory_and_refreshed_when_expired(self):
        self.assertEqual(self.call("list_my_videos")["count"], 2)
        self.assertEqual(self.call("list_my_videos")["count"], 2)
        self.assertEqual(len(self.google.tokens), 1)
        self.module.AUTH.expires = 0
        self.call("list_my_videos")
        self.assertEqual(len(self.google.tokens), 2)

    def test_a_401_gets_a_new_token_once(self):
        self.google.reject_next_api = 1
        self.assertEqual(self.call("list_my_videos")["count"], 2)
        self.assertEqual(len(self.google.tokens), 2)
        self.google.reject_next_api = 5
        self.assertIn("refused the access token twice", self.call("list_my_videos")["error"])

    def test_refresh_errors_are_named(self):
        self.google.token_error = (400, {"error": "invalid_grant", "error_description": "Token has been expired or "
                                                                                      "revoked."})
        error = self.call("list_my_videos")["error"]
        self.assertIn("refresh token", error)
        self.assertIn("7 days", error)
        self.google.token_error = (401, {"error": "invalid_client", "error_description": "The OAuth client was not "
                                                                                       "found."})
        self.assertIn("refused the OAuth client", self.call("list_my_videos")["error"])
        self.google.token_error = (500, {"error": f"server {CLIENT_SECRET}"})
        error = self.call("list_my_videos")["error"]
        self.assertIn("HTTP 500", error)
        self.assertNoSecrets(error)

    def test_missing_and_malformed_credentials_are_named_never_shown(self):
        with mock.patch.dict(os.environ, {"YOUTUBE_REFRESH_TOKEN": ""}):
            error = self.call("list_my_videos")["error"]
        self.assertIn("missing: YOUTUBE_REFRESH_TOKEN", error)
        with mock.patch.dict(os.environ, {"YOUTUBE_CLIENT_SECRET": "short"}):
            error = self.call("list_my_videos")["error"]
        self.assertIn("YOUTUBE_CLIENT_SECRET is not", error)
        self.assertNotIn("short", error.replace("shaped", ""))
        self.assertEqual(self.google.requests, [])

    def test_scopes_least_privilege(self):
        self.google.scope = UPLOAD
        error = self.call("upload_captions", video_id=VIDEO, path=self.file("de.srt", SRT), language="de")["error"]
        self.assertIn("needs the scope youtube.force-ssl", error)
        self.assertIn("authorize.py", error)
        self.assertIn("needs the scope youtube.readonly", self.call("list_my_videos")["error"])
        self.assertNotIn("/upload/youtube/v3/captions", self.google.paths())
        self.assertNotIn("/youtube/v3/channels", self.google.paths())
        path, _ = self.video_file()
        self.assertNotIn("error", self.upload(path))  # youtube.upload is enough for an upload

    def test_errors_and_logs_never_carry_secrets(self):
        self.call("list_my_videos")
        token = self.google.tokens[-1]
        self.google.api_error["/youtube/v3/channels"] = (400, {"error": {
            "code": 400, "message": f"bad {token} {REFRESH} {CLIENT_SECRET} Bearer {token} upload_id={SESSION_ID}"}})
        error = self.call("list_my_videos")["error"]
        self.assertIn("HTTP 400", error)
        self.assertNoSecrets(error)
        self.module.log.info("token %s secret %s refresh %s session %s", token, CLIENT_SECRET, REFRESH,
                             self.google.location)
        self.module.log.info("someone else's ya29.OtherToken123 1//0OtherRefreshTokenAbc GOCSPX-other")
        logged = self.log.getvalue()
        self.assertNoSecrets(logged)
        self.assertNotIn("OtherToken", logged)
        self.assertNotIn("OtherRefresh", logged)
        self.assertNotIn("GOCSPX-other", logged)
        self.assertIn("<secret>", logged)

    def test_an_unexpected_exception_is_named_by_type_only(self):
        async def boom(*args, **kwargs):
            raise RuntimeError(f"leak {CLIENT_SECRET}")

        with mock.patch.object(self.module, "_api_json", boom):
            answer = self.call("list_my_videos")
        self.assertEqual(answer, {"error": "internal error (RuntimeError)"})
        self.assertNoSecrets(self.log.getvalue())


class Thumbnails(WithFakeGoogle):
    def test_png_and_jpeg(self):
        answer = self.call("set_thumbnail", video_id=VIDEO, path=self.file("thumb.png", png()))
        self.assertEqual(answer["thumbnail"].split(",")[0], "1280x720 image/png")
        self.assertNotIn("note", answer)
        sent = next(r for r in self.google.requests if "/thumbnails/set" in r[1])
        self.assertEqual(sent[2]["content-type"], "image/png")
        self.assertIn(f"videoId={VIDEO}", sent[1])
        self.assertEqual(sent[3], png())
        answer = self.call("set_thumbnail", video_id=VIDEO, path=self.file("thumb.jpg", jpeg(640, 360)))
        self.assertTrue(answer["thumbnail"].startswith("640x360 image/jpeg"), answer)
        self.assertIn("1280x720", answer["note"])

    def test_refused_images(self):
        self.assertIn("not a JPEG or PNG", self.call("set_thumbnail", video_id=VIDEO,
                                                     path=self.file("t.png", b"<svg/>" * 10))["error"])
        big = self.file("big.png", png(pad=2 << 20))
        self.assertIn("more than the 2097152", self.call("set_thumbnail", video_id=VIDEO, path=big)["error"])
        self.assertIn("a .jpeg, .jpg, .png file", self.call("set_thumbnail", video_id=VIDEO,
                                                            path=self.file("t.gif", b"GIF89a"))["error"])
        self.assertIn("video_id", self.call("set_thumbnail", video_id="../x", path=big)["error"])
        self.assertFalse(any("/thumbnails/set" in r[1] for r in self.google.requests))

    def test_an_unverified_channel(self):
        self.google.api_error["/upload/youtube/v3/thumbnails/set"] = (403, {"error": {
            "code": 403, "message": "The authenticated user doesnt have permissions to upload and set custom video "
                                    "thumbnails.", "errors": [{"reason": "forbidden"}]}})
        error = self.call("set_thumbnail", video_id=VIDEO, path=self.file("thumb.png", png()))["error"]
        self.assertIn("verified by phone", error)


class Captions(WithFakeGoogle):
    def test_srt_as_multipart(self):
        answer = self.call("upload_captions", video_id=VIDEO, path=self.file("de.srt", SRT), language="de",
                           name="Deutsch")
        self.assertEqual(answer["caption_id"], "AUieDaZcaption")
        self.assertIn("400", answer["quota"])
        method, url, headers, body = next(r for r in self.google.requests if "/captions" in r[1])
        self.assertEqual(method, "POST")
        self.assertIn("uploadType=multipart", url)
        boundary = re.fullmatch(r"multipart/related; boundary=(\S+)", headers["content-type"]).group(1)
        parts = body.split(f"--{boundary}".encode())
        self.assertEqual(parts[-1], b"--\r\n")
        meta = json.loads(parts[1].split(b"\r\n\r\n", 1)[1])
        self.assertEqual(meta, {"snippet": {"videoId": VIDEO, "language": "de", "name": "Deutsch", "isDraft": False}})
        self.assertIn(b"Content-Type: application/x-subrip\r\n\r\n" + SRT + b"\r\n", parts[2])

    def test_vtt_and_refused_files(self):
        vtt = b"WEBVTT\n\n00:00.000 --> 00:04.000\nHello\n"
        self.assertNotIn("error", self.call("upload_captions", video_id=VIDEO, path=self.file("en.vtt", vtt),
                                            language="en-US"))
        for name, data, expected in (("x.vtt", b"00:00.000 --> 00:04.000\n", "WEBVTT"),
                                     ("x.srt", b"just text\n", "not an SRT file"),
                                     ("y.srt", SRT.replace(b"Hallo", b"\xff\xfe"), "UTF-8"),
                                     ("z.srt", SRT + b"\0", "NUL"),
                                     ("x.txt", SRT, "a .srt, .vtt file")):
            with self.subTest(name=name):
                answer = self.call("upload_captions", video_id=VIDEO, path=self.file(name, data), language="de")
                self.assertIn(expected, answer["error"])
        self.assertIn("language", self.call("upload_captions", video_id=VIDEO, path=self.file("de.srt", SRT),
                                            language="German")["error"])
        self.assertIn("name", self.call("upload_captions", video_id=VIDEO, path=self.file("de.srt", SRT),
                                        language="de", name="n" * 151)["error"])


class UpdateMetadata(WithFakeGoogle):
    def test_only_the_given_fields_change(self):
        answer = self.call("update_metadata", video_id=VIDEO, title="Neuer Titel")
        self.assertEqual(answer["changed"], ["title"])
        part, body = self.google.updates[-1]
        self.assertEqual(part, "snippet")
        self.assertEqual(body, {"id": VIDEO, "snippet": {
            "title": "Neuer Titel", "description": "Old description", "tags": ["alt", "tag"], "categoryId": "27",
            "defaultLanguage": "de", "defaultAudioLanguage": "de"}})
        answer = self.call("update_metadata", video_id=VIDEO, privacy="unlisted", made_for_kids=False)
        part, body = self.google.updates[-1]
        self.assertEqual(part, "status")
        self.assertEqual(body["status"], {"privacyStatus": "unlisted", "embeddable": True, "license": "youtube",
                                          "publicStatsViewable": True, "selfDeclaredMadeForKids": False,
                                          "containsSyntheticMedia": True})  # publishAt only for private videos
        self.assertNotIn("snippet", body)
        self.assertEqual(answer["changed"], ["made_for_kids", "privacy"])
        self.assertIn("audit", answer["note"])
        self.call("update_metadata", video_id=VIDEO, tags=[])
        self.assertNotIn("tags", self.google.updates[-1][1]["snippet"])
        self.call("update_metadata", video_id=VIDEO, description="Neu", chapters=["0:00 A", "0:10 B", "0:20 C"])
        self.assertEqual(self.google.updates[-1][1]["snippet"]["description"], "Neu\n\n0:00 A\n0:10 B\n0:20 C")
        methods = [(r[0], urllib.parse.urlsplit(r[1]).path) for r in self.google.requests if "/youtube/v3/" in r[1]]
        self.assertEqual(methods[:2], [("GET", "/youtube/v3/videos"), ("PUT", "/youtube/v3/videos")])

    def test_refusals(self):
        self.assertIn("nothing to change", self.call("update_metadata", video_id=VIDEO)["error"])
        self.assertIn("give the description too", self.call("update_metadata", video_id=VIDEO,
                                                            chapters=["0:00 A", "0:10 B", "0:20 C"])["error"])
        self.assertIn("YOUTUBE_ALLOW_PUBLIC", self.call("update_metadata", video_id=VIDEO, privacy="public")["error"])
        self.assertIn("title", self.call("update_metadata", video_id=VIDEO, title="a < b")["error"])
        self.assertEqual(self.google.requests, [])
        self.assertIn("no video ZzZzZzZzZz0", self.call("update_metadata", video_id="ZzZzZzZzZz0", title="x")["error"])
        self.assertEqual(self.google.updates, [])

    def test_a_public_video_only_when_public_is_allowed(self):
        self.google.video["status"]["privacyStatus"] = "public"
        error = self.call("update_metadata", video_id=VIDEO, title="Renamed")["error"]
        self.assertIn("is public", error)
        self.assertIn("YOUTUBE_ALLOW_PUBLIC=1", error)
        self.assertEqual(self.google.updates, [])
        with mock.patch.dict(os.environ, {"YOUTUBE_ALLOW_PUBLIC": "1"}):
            self.assertEqual(self.call("update_metadata", video_id=VIDEO, privacy="private")["changed"], ["privacy"])


class ListMyVideos(WithFakeGoogle):
    def test_the_uploads_with_their_state(self):
        answer = self.call("list_my_videos", max_results=5)
        self.assertEqual(answer["channel"], {"id": "UCchannel", "title": "My channel"})
        self.assertEqual([v["video_id"] for v in answer["videos"]], [VIDEO, "ZyXwVuTsRq9"])  # the bad id is dropped
        self.assertEqual(answer["videos"][1]["upload_status"], "rejected")
        self.assertEqual(answer["videos"][1]["rejectionReason"], "duplicate")
        playlist = next(r for r in self.google.requests if "/playlistItems" in r[1])
        self.assertIn("playlistId=UUchannel", playlist[1])
        self.assertIn("maxResults=5", playlist[1])
        for value in (0, 51, "5", True):
            self.assertIn("max_results", self.call("list_my_videos", max_results=value)["error"])


class Fields(WithFakeGoogle):
    def refused(self, expected, **overrides):
        path, _ = self.video_file()
        answer = self.upload(path, **overrides)
        self.assertIn("error", answer, overrides)
        self.assertIn(expected, answer["error"])

    def test_youtube_limits(self):
        self.refused("at most 100 characters", title="x" * 101)
        self.refused("< and >", title="<script>")
        self.refused("title", title="   ")
        self.refused("control characters", title="a\x07b")
        self.refused("5000 bytes", description="ä" * 2501)  # 5002 bytes in UTF-8
        self.refused("< and >", description="a > b")
        self.refused("500 characters", tags=["x" * 100] * 5)  # 500 + 4 commas
        self.refused("500 characters", tags=["a b" * 82, "c" * 252])  # 246 + 2 (quoted: it has spaces) + 1 + 252
        self.refused("no < > or ,", tags=["a,b"])
        self.refused("category_id", category_id="People")
        self.refused("default_language", default_language="Deutsch")
        self.refused("privacy", privacy="friends")
        self.refused("made_for_kids", made_for_kids="no")
        self.refused("contains_synthetic_media", contains_synthetic_media=None)
        self.assertEqual(self.google.requests, [])

    def test_tags_counted_as_youtube_counts_them(self):
        path, _ = self.video_file()
        exactly = ["x" * 99] * 5  # 495 + 4 commas = 499
        self.assertNotIn("error", self.upload(path, tags=exactly))

    def test_chapters(self):
        good = ["0:00 Intro", "0:10 Teil", "1:00:00 Spaet"]
        self.assertEqual(self.module._chapters(good), ["0:00 Intro", "0:10 Teil", "1:00:00 Spaet"])
        self.assertEqual(self.module._chapters([{"start": "00:00", "title": "A"}, {"start": "75:00", "title": "B"},
                                                {"start": "1:15:10", "title": "C"}]), ["0:00 A", "1:15:00 B",
                                                                                     "1:15:10 C"])
        self.refused("first starts at 0:00", chapters=["0:05 A", "0:20 B", "0:40 C"])
        self.refused("at least 3", chapters=["0:00 A", "0:20 B"])
        self.refused("at least 10 seconds", chapters=["0:00 A", "0:09 B", "0:40 C"])
        self.refused("at least 10 seconds", chapters=["0:00 A", "0:40 B", "0:30 C"])
        self.refused("M:SS or H:MM:SS", chapters=["0:00 A", "abc B", "0:40 C"])
        self.refused("a title", chapters=["0:00 A", "0:20", "0:40 C"])
        self.refused("5000 bytes", description="x" * 4990, chapters=good)


class Paths(WithFakeGoogle):
    def refused(self, path, expected):
        answer = self.upload(path)
        self.assertIn("error", answer, path)
        self.assertIn(expected, answer["error"], path)

    def test_lexically_outside_upload(self):
        root = str(self.root)
        for path in ("/etc/passwd", "relative.mp4", f"{root}/../escape.mp4", f"{root}/./a.mp4", f"{root}",
                     f"{root}x/a.mp4", f"{root}/sub/../../a.mp4", f"{root}/a.mp4\0", 42):
            with self.subTest(path=path):
                answer = self.upload(path)
                self.assertIn("error", answer)
                self.assertTrue("only files under" in answer["error"] or "the path of a file" in answer["error"]
                                or "control characters" in answer["error"], answer)
        self.refused(f"{root}/.hidden.mp4", "hidden files")
        self.refused(f"{root}/.git/a.mp4", "hidden files")
        self.refused(f"{root}/notes.txt", "a .3gp, .avi")
        self.assertEqual(self.google.requests, [], "refused before anything is sent")

    def test_links_devices_pipes_folders_and_other_users_files(self):
        path, _ = self.video_file("sub/real.mp4")
        root = self.root
        os.symlink(path, root / "link.mp4")
        os.symlink(root / "sub", root / "linked")
        os.symlink("/etc/passwd", root / "passwd.mp4")
        os.mkfifo(root / "pipe.mp4")
        (root / "folder.mp4").mkdir()
        os.link(path, root / "second-name.mp4")
        self.file("empty.mp4", b"")
        self.file("text.mp4", b"not a video at all, just text\n" * 10)
        self.refused(str(root / "link.mp4"), "is a link, not a regular file")
        self.refused(str(root / "passwd.mp4"), "is a link")
        self.refused(str(root / "linked" / "real.mp4"), "linked is not a folder (links are not followed)")
        self.refused(str(root / "pipe.mp4"), "a device, pipe or socket")
        self.refused(str(root / "folder.mp4"), "is a folder")
        self.refused(str(root / "second-name.mp4"), "2 names (hard links)")
        self.refused(str(root / "sub" / "real.mp4"), "2 names (hard links)")
        self.refused(str(root / "missing.mp4"), "does not exist")
        self.refused(str(root / "empty.mp4"), "is empty")
        self.refused(str(root / "text.mp4"), "does not start like a video")
        os.unlink(root / "second-name.mp4")
        with mock.patch.object(self.module.os, "geteuid", return_value=os.geteuid() + 1):
            self.refused(path, "belongs to another user")
        self.assertNotIn("error", self.upload(path))

    def test_a_device(self):
        with mock.patch.object(self.module, "UPLOAD_ROOT", "/dev"):
            with self.assertRaises(self.module.ArgumentError) as caught:
                self.module._open_upload(["null"], "path", 1 << 20)
        self.assertIn("a device, pipe or socket", str(caught.exception))

    def test_no_folder_mounted(self):
        with mock.patch.object(self.module, "UPLOAD_ROOT", str(self.root / "nothing")):
            self.refused(str(self.root / "nothing" / "a.mp4"), "no folder is mounted at")

    def test_upload_itself_a_link(self):
        os.symlink(self.root, Path(self.folder.name, "uplink"))
        path, _ = self.video_file()
        with mock.patch.object(self.module, "UPLOAD_ROOT", str(Path(self.folder.name, "uplink"))):
            self.refused(str(Path(self.folder.name, "uplink", "video.mp4")), "no folder is mounted at")


class IndependentReview(WithFakeGoogle):
    """The findings of the independent review of 2026-11-13, each first shown here, then fixed."""

    def test_a_public_videos_thumbnail_and_captions_need_allow_public(self):
        self.google.video["status"]["privacyStatus"] = "public"
        thumb, captions = self.file("thumb.png", png()), self.file("de.srt", SRT)
        for tool, arguments in (("set_thumbnail", {"path": thumb}), ("upload_captions", {"path": captions,
                                                                                         "language": "de"})):
            with self.subTest(tool=tool):
                error = self.call(tool, video_id=VIDEO, **arguments).get("error", "")
                self.assertIn("is public", error)
                self.assertIn("YOUTUBE_ALLOW_PUBLIC=1", error)
        self.assertFalse(any("/thumbnails/set" in r[1] or "/captions" in r[1] for r in self.google.requests),
                         "nothing changed on a public video")
        with mock.patch.dict(os.environ, {"YOUTUBE_ALLOW_PUBLIC": "1"}):
            self.google.requests.clear()
            self.assertNotIn("error", self.call("set_thumbnail", video_id=VIDEO, path=thumb))
            self.assertNotIn("/youtube/v3/videos", self.google.paths(), "allowed: no extra read (quota)")
        self.google.video["status"]["privacyStatus"] = "private"
        self.assertNotIn("error", self.call("set_thumbnail", video_id=VIDEO, path=thumb))
        self.assertNotIn("error", self.call("upload_captions", video_id=VIDEO, path=captions, language="de"))

    def test_a_video_scheduled_to_go_public_counts_as_public(self):
        self.google.video["status"]["publishAt"] = "2026-12-01T10:00:00Z"
        for tool, arguments in (("update_metadata", {"title": "Renamed"}),
                                ("update_metadata", {"privacy": "private"}),
                                ("set_thumbnail", {"path": self.file("thumb.png", png())})):
            with self.subTest(tool=tool, arguments=arguments):
                error = self.call(tool, video_id=VIDEO, **arguments).get("error", "")
                self.assertIn("scheduled", error)
                self.assertIn("YOUTUBE_ALLOW_PUBLIC=1", error)
        self.assertEqual(self.google.updates, [])
        with mock.patch.dict(os.environ, {"YOUTUBE_ALLOW_PUBLIC": "1"}):
            self.call("update_metadata", video_id=VIDEO, privacy="unlisted")
        self.assertNotIn("publishAt", self.google.updates[-1][1]["status"], "a schedule only for a private video")

    def test_the_guard_needs_a_scope_that_reads_the_video(self):
        self.google.scope = UPLOAD
        error = self.call("set_thumbnail", video_id=VIDEO, path=self.file("thumb.png", png()))["error"]
        self.assertIn("youtube.readonly", error)
        self.assertNotIn("/upload/youtube/v3/thumbnails/set", self.google.paths())

    def test_an_unknown_video_is_refused_before_the_thumbnail(self):
        error = self.call("set_thumbnail", video_id="ZzZzZzZzZz0", path=self.file("thumb.png", png()))["error"]
        self.assertIn("no video ZzZzZzZzZz0", error)
        self.assertNotIn("/upload/youtube/v3/thumbnails/set", self.google.paths())

    def test_contains_synthetic_media_defaults_to_false(self):
        path, _ = self.video_file()
        answer = self.call("upload_video", path=path, title="x", made_for_kids=False)
        self.assertNotIn("error", answer, answer)
        self.assertIs(self.google.metadata["status"]["containsSyntheticMedia"], False)
        self.assertIn("made_for_kids", self.upload(path, made_for_kids=None)["error"])

    def test_every_refusal_of_the_token_endpoint_reads_the_same(self):
        """The smoke run's one real call expects "Google refused the" whatever Google calls a bogus client."""
        for status, code in ((401, "invalid_client"), (401, "deleted_client"), (400, "unauthorized_client"),
                             (400, "invalid_grant"), (400, "invalid_request"), (400, None), (403, "access_denied")):
            with self.subTest(code=code):
                self.google.token_error = (status, {"error": code, "error_description": "x"} if code else ["x"])
                error = self.call("list_my_videos")["error"]
                self.assertIn("Google refused the ", error)
                if code:
                    self.assertIn(code, error)
        self.google.token_error = (503, {"error": "backend"})
        error = self.call("list_my_videos")["error"]
        self.assertIn("HTTP 503", error)
        self.assertNotIn("refused", error, "a server error of Google's is not a refusal")
        spec = json.loads((SERVER / "smoke.json").read_text())
        self.assertEqual(spec["calls"][0]["expect"], "Google refused the ")

    def test_the_bare_session_id_never_reaches_an_answer(self):
        path, _ = self.video_file()
        self.google.fail_chunks = {1: (400, 0)}
        self.google.chunk = (lambda original: lambda request: (
            self.google.json(400, {"error": {"code": 400, "message": f"Upload session {SESSION_ID} is broken"}})
            if request.method == "PUT" else original(request)))(self.google.chunk)
        answer = self.upload(path)
        self.assertIn("HTTP 400", answer["error"])
        self.assertNoSecrets(answer, self.log.getvalue())

    def test_a_session_that_keeps_forgetting_bytes_is_given_up(self):
        path, data = self.video_file()
        chunk = 256 << 10
        puts = {"n": 0}

        def forgetful(request):
            # every other answer "forgets" all but the first byte: progress, then back - never finished
            puts["n"] += 1
            if puts["n"] > 400:
                raise AssertionError("still uploading after 400 requests")
            start = int(re.match(r"bytes (\d+)-", request.headers["content-range"]).group(1))
            end = 0 if puts["n"] % 2 == 0 else min(start + chunk, len(data) - 1) - 1
            return httpx.Response(308, headers={"Range": f"bytes=0-{end}"})

        self.google.chunk = forgetful
        answer = self.upload(path)
        self.assertIn("nothing was published", answer.get("error", ""), answer)
        self.assertLess(puts["n"], 100)


@unittest.skipIf(mcp is None, "the server's requirements are not installed")
class ToolList(unittest.TestCase):
    def test_tools_json_says_what_writes_and_which_scope(self):
        module = load()
        recorded = json.loads((SERVER / "tools.json").read_text())
        tools = {tool.name: tool for tool in asyncio.run(module.mcp.list_tools())}
        self.assertEqual(sorted(tools), recorded["tools"])
        for name, tool in tools.items():
            with self.subTest(tool=name):
                writes = name in recorded["write_tools"]
                self.assertEqual(tool.annotations.readOnlyHint, not writes)
                self.assertEqual(tool.description.startswith("WRITES to the user's YouTube channel"), writes)
                self.assertEqual(recorded["scopes"][name], "youtube." + module.TOOL_SCOPES[name][1])
                self.assertIn(f"Needs scope youtube.{module.TOOL_SCOPES[name][1]}", " ".join(tool.description.split()))
        self.assertEqual(recorded["read_only_tools"], ["list_my_videos"])
        required = tools["upload_video"].inputSchema["required"]
        self.assertEqual(sorted(required), ["made_for_kids", "path", "title"])
        self.assertIs(tools["upload_video"].inputSchema["properties"]["contains_synthetic_media"]["default"], False)
        self.assertEqual(tools["upload_video"].inputSchema["properties"]["privacy"]["default"], "private")


class Authorize(unittest.TestCase):
    """authorize.py: the loopback flow with a fake browser and a fake token endpoint; only the token on stdout."""

    def setUp(self):
        self.module = load_authorize()
        patcher = mock.patch.dict(os.environ, {"YOUTUBE_CLIENT_ID": CLIENT_ID, "YOUTUBE_CLIENT_SECRET": CLIENT_SECRET})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.exchanged = []

    def opener(self, request, timeout):
        self.exchanged.append((request.full_url, urllib.parse.parse_qs(request.data.decode())))
        body = json.dumps({"access_token": "ya29.x", "refresh_token": REFRESH, "scope": f"{UPLOAD} {READONLY}",
                           "expires_in": 3599}).encode()
        return contextlib.closing(io.BytesIO(body))

    @staticmethod
    def visit(url):
        direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with direct.open(url, timeout=10) as answer:
                return answer.status, answer.read().decode()
        except urllib.error.HTTPError as exc:
            return exc.code, ""

    def browser(self, state_override=None, error=None):
        seen = {}

        def open_url(url):
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
            seen.update({k: v[0] for k, v in query.items()})
            redirect = query["redirect_uri"][0]
            seen["wrong_state"] = self.visit(redirect + "?" + urllib.parse.urlencode({"state": "nope", "code": "x"}))
            seen["unicode_state"] = self.visit(redirect + "?" + urllib.parse.urlencode({"state": "\u00e4", "code": "x"}))
            seen["other_path"] = self.visit(redirect + "favicon.ico?" + urllib.parse.urlencode(
                {"state": query["state"][0], "code": "x"}))
            answer = {"state": state_override or query["state"][0]}
            answer.update({"error": error} if error else {"code": "4/0AfakeCode"})
            seen["final"] = self.visit(redirect + "?" + urllib.parse.urlencode(answer))
        return seen, open_url

    def run_main(self, argv, open_url, tty=False):
        out, err = io.StringIO(), io.StringIO()
        out.isatty = lambda: tty
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = self.module.main(argv, open_url=open_url, opener=self.opener)
            except SystemExit as exc:
                code = str(exc)
        return code, out.getvalue(), err.getvalue()

    def test_the_loopback_flow_prints_only_the_token(self):
        seen, open_url = self.browser()
        code, out, err = self.run_main([], open_url)
        self.assertEqual(code, 0, err)
        self.assertEqual(out, REFRESH + "\n")
        self.assertEqual(seen["wrong_state"][0], 404)
        self.assertEqual(seen["unicode_state"][0], 404)
        self.assertEqual(seen["other_path"][0], 404)
        self.assertEqual(seen["final"][0], 200)
        self.assertTrue(seen["redirect_uri"].startswith("http://127.0.0.1:"))
        self.assertEqual(seen["scope"], f"{UPLOAD} {READONLY}")
        self.assertEqual((seen["access_type"], seen["prompt"], seen["code_challenge_method"], seen["response_type"]),
                         ("offline", "consent", "S256", "code"))
        url, form = self.exchanged[0]
        self.assertEqual(url, "https://oauth2.googleapis.com/token")
        self.assertEqual(form["grant_type"], ["authorization_code"])
        self.assertEqual(form["code"], ["4/0AfakeCode"])
        self.assertEqual(form["redirect_uri"], [seen["redirect_uri"]])
        import base64
        import hashlib
        verifier = form["code_verifier"][0]
        self.assertGreaterEqual(len(verifier), 43)
        self.assertEqual(base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("="),
                         seen["code_challenge"])
        self.assertIn("upload: granted", err)
        self.assertNotIn(REFRESH, err)
        self.assertNotIn(CLIENT_SECRET, err)

    def test_force_ssl_on_request_and_scopes_checked(self):
        seen, open_url = self.browser()
        code, out, err = self.run_main(["--scopes", "upload,force-ssl"], open_url)
        self.assertEqual(code, 0, err)
        self.assertEqual(seen["scope"], f"{UPLOAD} {FORCE_SSL}")
        self.assertIn("force-ssl: NOT granted", err)
        code, out, _ = self.run_main(["--scopes", "youtube"], lambda url: None)
        self.assertIn("--scopes", code)
        self.assertEqual(out, "")

    def test_refuses_a_terminal_and_a_refused_consent(self):
        code, out, err = self.run_main([], lambda url: self.fail("no sign-in for a terminal"), tty=True)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("--show", err)
        _, open_url = self.browser(error="access_denied")
        code, out, _ = self.run_main([], open_url)
        self.assertIn("access_denied", code)
        self.assertEqual(out, "")

    def test_a_desktop_clients_json(self):
        with tempfile.TemporaryDirectory() as folder:
            good = Path(folder, "client.json")
            good.write_text(json.dumps({"installed": {"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET}}))
            web = Path(folder, "web.json")
            web.write_text(json.dumps({"web": {"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET}}))
            with mock.patch.dict(os.environ, {"YOUTUBE_CLIENT_ID": "", "YOUTUBE_CLIENT_SECRET": ""}):
                self.assertEqual(self.module.client_from(str(good)), (CLIENT_ID, CLIENT_SECRET))
                with self.assertRaises(SystemExit) as caught:
                    self.module.client_from(str(web))
        self.assertIn("Desktop app", str(caught.exception))
        self.assertNotIn(CLIENT_SECRET, str(caught.exception))

    def test_the_browser_never_writes_into_the_token_pipe(self):
        """--open: a browser started by webbrowser inherits standard output (Chrome writes "Opening in existing
        browser session." there, and keeps it open): it gets standard error instead, so the pipe into the secret
        store carries the token alone."""
        import subprocess

        def browser(url):
            subprocess.run(["sh", "-c", "echo browser-noise"], check=True)
            return True

        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            saved = os.dup(1), os.dup(2)
            sys.stdout.flush()
            sys.stderr.flush()
            os.dup2(out.fileno(), 1)
            os.dup2(err.fileno(), 2)
            try:
                with mock.patch.object(self.module.webbrowser, "open", browser):
                    self.module.open_browser("https://accounts.google.com/o/oauth2/v2/auth?x=1")
            finally:
                os.dup2(saved[0], 1)
                os.dup2(saved[1], 2)
                os.close(saved[0])
                os.close(saved[1])
            out.seek(0)
            err.seek(0)
            self.assertEqual(out.read(), b"")
            self.assertIn(b"browser-noise", err.read())

    def test_the_loopback_listener_is_not_shared_and_not_held(self):
        self.assertIs(self.module.LoopbackHTTPServer.allow_reuse_port, False, "no second listener on the port")
        self.assertTrue(0 < self.module.Redirect.timeout <= 30, "a connection that sends nothing is dropped")


if __name__ == "__main__":
    unittest.main()
