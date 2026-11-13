#!/usr/bin/env python3
"""YouTube MCP server (sandbox-ai-mcp): publish a video an agent made to the user's YouTube channel through
the YouTube Data API v3, without the agent ever seeing the user's Google credentials.

Tools (all but list_my_videos WRITE to the channel; sandbox-ai's approvals should ask for each call):
    - upload_video: a video file of /upload, resumable upload (videos.insert), private or unlisted
    - set_thumbnail: a JPEG or PNG of /upload as a video's thumbnail (thumbnails.set)
    - upload_captions: an SRT or WebVTT file of /upload as a caption track (captions.insert)
    - update_metadata: only the given fields of a video (videos.list, then videos.update)
    - list_my_videos: the channel's latest uploads with their state (read-only)

Credentials: YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET (a Desktop OAuth client) and YOUTUBE_REFRESH_TOKEN
(made once on the host with authorize.py) come from the environment of this server's container only. The
server refreshes its access token at oauth2.googleapis.com itself and keeps it in memory; no tool answer
and no log line carries a token, the client secret or an upload session (every text is redacted).
Requests go to oauth2.googleapis.com and www.googleapis.com only (checked before each request, the
upload session's address too), over HTTPS, without redirects; HTTPS_PROXY is honoured.

Files are read only below /upload (a folder the user mounts read-only): every part of the path is
opened without following links, and only regular files of the server's own user with one name are
taken - no links, devices, pipes, hidden names or other users' files. Every field is checked against
YouTube's limits before anything is sent; answers are size-bounded. Public videos only with
YOUTUBE_ALLOW_PUBLIC=1.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
import secrets
import stat
import sys
import time
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/youtube/v3/"
UPLOAD_API = "https://www.googleapis.com/upload/youtube/v3/"
#: The only hosts a request goes to (checked before each one, the upload session's address included).
HOSTS = frozenset({"oauth2.googleapis.com", "www.googleapis.com"})
UPLOAD_ROOT = "/upload"

SCOPE = "https://www.googleapis.com/auth/"
UPLOAD = SCOPE + "youtube.upload"
READONLY = SCOPE + "youtube.readonly"
FORCE_SSL = SCOPE + "youtube.force-ssl"
FULL = SCOPE + "youtube"
PARTNER = SCOPE + "youtubepartner"
#: Which granted scope lets a tool do its calls (Google's scope lists of videos.insert, thumbnails.set,
#: captions.insert, videos.list + videos.update, channels/playlistItems/videos.list), and which one
#: authorize.py asks for to get it: least privilege - youtube.upload alone covers the upload and the thumbnail.
TOOL_SCOPES = {
    "upload_video": ({UPLOAD, FULL, FORCE_SSL, PARTNER}, "upload"),
    "set_thumbnail": ({UPLOAD, FULL, FORCE_SSL, PARTNER}, "upload"),
    "upload_captions": ({FORCE_SSL, PARTNER}, "force-ssl"),
    "update_metadata": ({FORCE_SSL, FULL, PARTNER}, "force-ssl"),
    "list_my_videos": ({READONLY, FORCE_SSL, FULL, PARTNER}, "readonly"),
}
#: videos.list, which the public guard of set_thumbnail and upload_captions needs (youtube.upload alone cannot read).
READ_STATUS = "reading the video's privacy"
TOOL_SCOPES[READ_STATUS] = ({READONLY, FORCE_SSL, FULL, PARTNER}, "readonly")
#: Units of the API project's daily quota (10,000 by default) each call costs, as Google's quota table lists them.
QUOTA = {"videos.insert": 1600, "thumbnails.set": 50, "captions.insert": 400, "videos.update": 50,
         "videos.list": 1, "channels.list": 1, "playlistItems.list": 1}

TIMEOUT = httpx.Timeout(60.0, connect=30.0, write=300.0)
MAX_ANSWER = 4 << 20            # bytes of one answer of Google's
MAX_TEXT = 300                  # characters of a text of Google's in an answer (titles, error messages)
CHUNK = 32 * (256 << 10)        # 8 MiB per PUT of the resumable upload: a multiple of 256 KiB, as Google requires
RETRIES = 8                     # failed tries in a row (5xx, 429, a broken connection) before an upload gives up
MAX_UPLOAD_MB_DEFAULT = 4096
MAX_UPLOAD_MB = 256 * 1024      # YouTube takes at most 256 GB (or 12 hours) per video
MAX_THUMBNAIL = 2 << 20         # thumbnails.set: at most 2 MB
MAX_CAPTIONS = 5 << 20

VIDEO_TYPES = {".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime", ".3gp": "video/3gpp",
               ".webm": "video/webm", ".mkv": "video/x-matroska", ".avi": "video/x-msvideo",
               ".mpg": "video/mpeg", ".mpeg": "video/mpeg", ".wmv": "video/x-ms-wmv", ".flv": "video/x-flv"}
IMAGE_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
CAPTION_TYPES = {".srt": "application/x-subrip", ".vtt": "text/vtt"}
PRIVACY = ("private", "unlisted", "public")
VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")
CATEGORY = re.compile(r"[1-9][0-9]{0,2}")
LANGUAGE = re.compile(r"[a-z]{2,3}(?:-[A-Za-z0-9]{1,8}){0,3}")
SRT_TIMING = re.compile(r"^\d{1,2}:\d{2}:\d{2}[,.]\d{3} --> \d{1,2}:\d{2}:\d{2}[,.]\d{3}", re.M)
TIMESTAMP = re.compile(r"(?:(\d{1,2}):([0-5]\d)|(\d{1,3})):([0-5]\d)")
RANGE = re.compile(r"bytes=0-(\d+)")
UNVERIFIED = ("Videos uploaded through the API by a Google Cloud project that has not passed Google's audit "
              "(every new project) are locked to private, whatever privacy was asked, until the project passes "
              "it (https://support.google.com/youtube/contact/yt_api_form).")

# --- secrets: in no answer and no log line ----------------------------------------------------------------------
#: Shapes of Google credentials, also when they are not this server's own: access tokens, refresh tokens, client
#: secrets, a Bearer header, the id of a resumable upload session (whoever has it can write into the upload).
SECRET_SHAPES = re.compile(r"ya29\.[A-Za-z0-9._~+/=-]+|1//[A-Za-z0-9._~+/=-]{10,}|GOCSPX-[A-Za-z0-9_-]+"
                           r"|(?i:bearer)\s+[A-Za-z0-9._~+/=-]+|upload_id=[^&\s\"'<>]+")
_tokens: set[str] = set()   # access tokens and upload sessions this process was given (to redact them; never logged)


def _secret_values() -> list[str]:
    values = [os.environ.get("YOUTUBE_CLIENT_SECRET", "").strip(), os.environ.get("YOUTUBE_REFRESH_TOKEN", "").strip(),
              *_tokens]
    return sorted((value for value in values if len(value) >= 8), key=len, reverse=True)


def redact(text: str) -> str:
    """*text* without the client secret, the refresh token, any access token and any upload session."""
    for value in _secret_values():
        text = text.replace(value, "<secret>")
    return SECRET_SHAPES.sub("<secret>", text)


def scrub(value):
    """*value* (an answer) with every text redacted."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [scrub(v) for v in value]
    return value


class RedactingFormatter(logging.Formatter):
    """Every log line, tracebacks included, without the secrets."""

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


_handler = logging.StreamHandler(sys.stderr)
_handler.setFormatter(RedactingFormatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
# force: the only handler of the process, so no line reaches stderr without the redaction.
logging.basicConfig(level=logging.INFO, handlers=[_handler], force=True)
# httpx logs every request's URL at INFO, an upload session's id with it: warnings only.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
log = logging.getLogger("youtube-mcp")
# An exception nobody caught would print its traceback straight to stderr: its type only.
sys.excepthook = lambda kind, value, tb: log.error("fatal %s", kind.__name__)

mcp = FastMCP("youtube-mcp", instructions=(
    "Publishes videos to the user's YouTube channel. Every tool but list_my_videos changes the channel: show the "
    "user what you are about to upload or change first. Videos are private unless asked otherwise; files only "
    "from /upload."))

#: Tests put a fake Google here (an httpx transport); None in use: the real network.
_transport: httpx.AsyncBaseTransport | None = None
_sleep = asyncio.sleep
_upload_running = asyncio.Lock()


class ArgumentError(ValueError):
    """A tool argument that is not accepted, or a state that cannot be used; the text says why."""


class GoogleError(RuntimeError):
    """Google refused or did not answer; the text says why (never a secret)."""


class Unreachable(GoogleError):
    """No answer from Google at all (no connection, a timeout): an upload tries again."""


# --- arguments ---------------------------------------------------------------------------------------------------

def _no_controls(value: str, name: str, newlines: bool = False) -> None:
    allowed = "\n\t" if newlines else ""
    if any((ord(c) < 32 and c not in allowed) or 0x7f <= ord(c) < 0xa0 or c in "\u2028\u2029" for c in value):
        raise ArgumentError(f"{name}: no control characters" + (" (line breaks and tabs are fine)" if newlines else ""))


def _title(value) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ArgumentError("title: 1-100 characters of text")
    value = value.strip()
    if len(value) > 100:
        raise ArgumentError(f"title: at most 100 characters (YouTube's limit), this one has {len(value)}")
    if "<" in value or ">" in value:
        raise ArgumentError("title: YouTube refuses < and > in a title")
    _no_controls(value, "title")
    return value


def _description(value) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ArgumentError("description: text of at most 5000 bytes")
    value = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if "<" in value or ">" in value:
        raise ArgumentError("description: YouTube refuses < and > in a description")
    _no_controls(value, "description", newlines=True)
    return value


def _check_description_size(value: str) -> str:
    size = len(value.encode("utf-8"))
    if size > 5000:
        raise ArgumentError(f"description: at most 5000 bytes in UTF-8 (YouTube's limit), with the chapters this one "
                            f"has {size}")
    return value


def _tags(value) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(tag, str) for tag in value):
        raise ArgumentError("tags: a list of texts")
    tags = []
    for tag in value:
        tag = tag.strip()
        if not tag:
            raise ArgumentError("tags: no empty tag")
        if any(c in tag for c in "<>,"):
            raise ArgumentError(f"tags: no < > or , in a tag ({tag[:40]!r})")
        _no_controls(tag, "tags")
        tags.append(tag)
    # YouTube's count: the characters of every tag, a tag with a space as if quoted (+2), a comma between tags.
    total = sum(len(tag) + (2 if " " in tag else 0) for tag in tags) + max(len(tags) - 1, 0)
    if total > 500:
        raise ArgumentError(f"tags: at most 500 characters together as YouTube counts them (a comma between tags, "
                            f"quotes around a tag with a space), these are {total}")
    return tags


def _category(value) -> str:
    if isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str) or not CATEGORY.fullmatch(value):
        raise ArgumentError("category_id: YouTube's category number as text, e.g. 22 (People & Blogs), "
                            "27 (Education), 28 (Science & Technology)")
    return value


def _language(value, name: str) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str) or len(value) > 35 or not LANGUAGE.fullmatch(value):
        raise ArgumentError(f"{name}: a BCP-47 language code such as en, de, en-US or pt-BR")
    return value


def _privacy(value) -> str:
    if value not in PRIVACY:
        raise ArgumentError("privacy: private (the default) or unlisted; public only when the server allows it")
    if value == "public" and not _public_allowed():
        raise ArgumentError("privacy: public needs YOUTUBE_ALLOW_PUBLIC=1 for this server (set by the user); "
                            "upload as private or unlisted and let the user publish it in YouTube Studio")
    return value


def _public_allowed() -> bool:
    return os.environ.get("YOUTUBE_ALLOW_PUBLIC", "").strip() == "1"


def _not_public(tool: str, vid: str, status) -> None:
    """Refuses a change to the video VID unless it is private or unlisted and not scheduled to become public (a
    private video with publishAt), or the user allowed public videos; an unreadable state counts as public."""
    if _public_allowed():
        return
    status = status if isinstance(status, dict) else {}
    privacy = status.get("privacyStatus")
    if privacy not in ("private", "unlisted"):
        raise ArgumentError(f"{tool}: {vid} is public (or its privacy cannot be read); changing a public video "
                            "needs YOUTUBE_ALLOW_PUBLIC=1 for this server (set by the user)")
    if status.get("publishAt"):
        raise ArgumentError(f"{tool}: {vid} is scheduled to become public ({_short(status['publishAt'], 40)}); "
                            "changing it needs YOUTUBE_ALLOW_PUBLIC=1 for this server (set by the user)")


def _flag(value, name: str, what: str) -> bool:
    if not isinstance(value, bool):
        raise ArgumentError(f"{name}: true or false - {what}")
    return value


KIDS = "required by YouTube (COPPA): true only if the video is made for children"
SYNTHETIC = ("YouTube's disclosure of altered or synthetic content: true if it shows realistic people, places or "
             "events that were made or changed with AI or other tools")


def _seconds(text: str) -> int | None:
    match = TIMESTAMP.fullmatch(text)
    if not match:
        return None
    hours, minutes, long_minutes, seconds = match.groups()
    if hours is not None:
        return int(hours) * 3600 + int(minutes) * 60 + int(seconds)
    return int(long_minutes) * 60 + int(seconds)


def _clock(seconds: int) -> str:
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours}:{minutes:02}:{seconds:02}" if hours else f"{minutes}:{seconds:02}"


def _chapters(value) -> list[str]:
    """The chapter lines for the description ("0:00 Intro"), checked as YouTube needs them to show chapters: the
    first at 0:00, at least three, in order, each at least 10 seconds long."""
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 100:
        raise ArgumentError("chapters: a list of at most 100 {\"start\": \"0:00\", \"title\": \"Intro\"} "
                            "(or \"0:00 Intro\")")
    rows = []
    for index, item in enumerate(value):
        if isinstance(item, str):
            start, _, title = item.strip().partition(" ")
        elif isinstance(item, dict) and set(item) <= {"start", "title"}:
            start, title = item.get("start"), item.get("title")
        else:
            raise ArgumentError(f"chapters[{index}]: {{\"start\": \"M:SS\", \"title\": \"...\"}} or \"M:SS title\"")
        seconds = _seconds(start.strip()) if isinstance(start, str) else None
        if seconds is None:
            raise ArgumentError(f"chapters[{index}]: start is M:SS or H:MM:SS, like 0:00, 1:30 or 1:02:03")
        if not isinstance(title, str) or not title.strip() or len(title.strip()) > 100:
            raise ArgumentError(f"chapters[{index}]: a title of 1-100 characters")
        title = title.strip().lstrip("-–—: ").strip() or title.strip()
        if "<" in title or ">" in title:
            raise ArgumentError(f"chapters[{index}]: YouTube refuses < and > in the description")
        _no_controls(title, f"chapters[{index}]")
        rows.append((seconds, title))
    if len(rows) < 3:
        raise ArgumentError("chapters: at least 3 (YouTube shows chapters only then)")
    if rows[0][0] != 0:
        raise ArgumentError("chapters: the first starts at 0:00")
    for (before, _), (after, title) in zip(rows, rows[1:]):
        if after - before < 10:
            raise ArgumentError(f"chapters: each is at least 10 seconds long, the one before {_clock(after)} "
                                f"{title[:40]!r} is {after - before} s")
    return [f"{_clock(seconds)} {title}" for seconds, title in rows]


def _with_chapters(description: str, lines: list[str]) -> str:
    if not lines:
        return _check_description_size(description)
    return _check_description_size((description + "\n\n" if description else "") + "\n".join(lines))


def _video_id(value) -> str:
    if not isinstance(value, str) or not VIDEO_ID.fullmatch(value):
        raise ArgumentError("video_id: the 11-character id of a video (as in https://youtu.be/ID)")
    return value


def _int(value, name: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ArgumentError(f"{name}: an integer from {low} to {high}")
    return value


def max_upload() -> int:
    """The largest video upload_video takes, in bytes (YOUTUBE_MAX_UPLOAD_MB, default 4096 MiB)."""
    text = os.environ.get("YOUTUBE_MAX_UPLOAD_MB", "").strip()
    if not text:
        return MAX_UPLOAD_MB_DEFAULT << 20
    if not text.isdigit() or not 1 <= int(text) <= MAX_UPLOAD_MB:
        raise ArgumentError(f"YOUTUBE_MAX_UPLOAD_MB: a number of MiB from 1 to {MAX_UPLOAD_MB}")
    return int(text) << 20


# --- files: only below /upload -----------------------------------------------------------------------------------

def _upload_parts(value, name: str, types: dict) -> list[str]:
    """The path's parts below /upload, checked without touching the file system."""
    root = UPLOAD_ROOT.rstrip("/")
    if not isinstance(value, str) or not value or len(value) > 4096 or "\0" in value:
        raise ArgumentError(f"{name}: the path of a file under {root}")
    _no_controls(value, name)
    if not value.startswith(root + "/"):
        raise ArgumentError(f"{name}: only files under {root} (the folder the user mounted for uploads), "
                            f"as an absolute path like {root}/video.mp4")
    parts = [part for part in value[len(root) + 1:].split("/") if part]
    if not parts or any(part in (".", "..") for part in parts):
        raise ArgumentError(f"{name}: only files under {root}, without . or .. in the path")
    if any(part.startswith(".") for part in parts):
        raise ArgumentError(f"{name}: hidden files and folders (a name starting with .) are not uploaded")
    suffix = os.path.splitext(parts[-1])[1].lower()
    if suffix not in types:
        raise ArgumentError(f"{name}: a {', '.join(sorted(types))} file")
    return parts


def _open_upload(parts: list[str], name: str, limit: int) -> tuple[int, int]:
    """(descriptor, size) of the regular file /upload/PARTS: each folder on the way opened without following a
    link, the file only if it is a regular file of this server's own user with a single name, at most LIMIT
    bytes and not empty. The caller closes the descriptor."""
    root = UPLOAD_ROOT.rstrip("/")
    shown = root + "/" + "/".join(parts)
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        folder = os.open(root, flags | os.O_DIRECTORY)
    except OSError:
        raise ArgumentError(f"{name}: no folder is mounted at {root} (the user adds it with "
                            f"--mount {root}=DIR:ro; a link there is not followed)") from None
    try:
        for part in parts[:-1]:
            try:
                inner = os.open(part, flags | os.O_DIRECTORY, dir_fd=folder)
            except OSError:
                raise ArgumentError(f"{name}: {shown}: {part} is not a folder (links are not followed)") from None
            os.close(folder)
            folder = inner
        try:
            before = os.stat(parts[-1], dir_fd=folder, follow_symlinks=False)
        except OSError:
            raise ArgumentError(f"{name}: {shown} does not exist") from None
        if not stat.S_ISREG(before.st_mode):
            kind = "a link" if stat.S_ISLNK(before.st_mode) else "a folder" if stat.S_ISDIR(before.st_mode) \
                else "a device, pipe or socket"
            raise ArgumentError(f"{name}: {shown} is {kind}, not a regular file (only regular files are uploaded)")
        try:
            fd = os.open(parts[-1], flags | os.O_NONBLOCK | os.O_NOCTTY, dir_fd=folder)
        except OSError as exc:
            raise ArgumentError(f"{name}: {shown} cannot be read ({exc.strerror})") from None
    finally:
        os.close(folder)
    try:
        info = os.fstat(fd)
        if (info.st_dev, info.st_ino) != (before.st_dev, before.st_ino) or not stat.S_ISREG(info.st_mode):
            raise ArgumentError(f"{name}: {shown} changed while it was opened")
        if info.st_uid != os.geteuid():
            raise ArgumentError(f"{name}: {shown} belongs to another user (only the user's own files are uploaded)")
        if info.st_nlink != 1:
            raise ArgumentError(f"{name}: {shown} has {info.st_nlink} names (hard links): only a file with one "
                                "name is uploaded")
        if info.st_size == 0:
            raise ArgumentError(f"{name}: {shown} is empty")
        if info.st_size > limit:
            raise ArgumentError(f"{name}: {shown} has {info.st_size} bytes, more than the {limit} this takes")
        return fd, info.st_size
    except BaseException:
        os.close(fd)
        raise


def _head(fd: int, size: int = 64) -> bytes:
    return os.pread(fd, size, 0)


def _looks_like_video(head: bytes) -> bool:
    return (head[4:8] in (b"ftyp", b"moov", b"mdat", b"wide", b"free", b"skip")  # MP4, MOV, 3GP
            or head.startswith(b"\x1a\x45\xdf\xa3")                              # Matroska, WebM
            or (head.startswith(b"RIFF") and head[8:12] == b"AVI ")
            or head.startswith((b"\x00\x00\x01\xba", b"\x00\x00\x01\xb3"))      # MPEG program / video stream
            or head.startswith(b"\x30\x26\xb2\x75\x8e\x66\xcf\x11")              # ASF (WMV)
            or head.startswith(b"FLV\x01"))


def _image_size(data: bytes) -> tuple[str, int, int] | None:
    """(MIME type, width, height) of a PNG or JPEG, None for anything else."""
    if data.startswith(b"\x89PNG\r\n\x1a\n") and data[12:16] == b"IHDR" and len(data) >= 24:
        return "image/png", int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    if not data.startswith(b"\xff\xd8\xff"):
        return None
    index = 2
    while index + 9 < len(data):
        if data[index] != 0xFF:
            return None
        marker = data[index + 1]
        if marker == 0xFF:
            index += 1
            continue
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            index += 2
            continue
        length = int.from_bytes(data[index + 2:index + 4], "big")
        if length < 2:
            return None
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            return "image/jpeg", int.from_bytes(data[index + 7:index + 9], "big"), \
                int.from_bytes(data[index + 5:index + 7], "big")
        index += 2 + length
    return None


def _read_all(fd: int, size: int) -> bytes:
    data = os.pread(fd, size + 1, 0)
    if len(data) != size:
        raise ArgumentError("the file changed while it was read")
    return data


# --- Google: credentials and requests ----------------------------------------------------------------------------

def credentials() -> tuple[str, str, str]:
    """(client id, client secret, refresh token) from the environment, checked for their shape; named, never
    quoted, when missing or malformed."""
    names = ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN")
    values = [os.environ.get(name, "").strip() for name in names]
    missing = [name for name, value in zip(names, values) if not value]
    if missing:
        raise ArgumentError("no YouTube credentials: set YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET and "
                            f"YOUTUBE_REFRESH_TOKEN for this server (missing: {', '.join(missing)}; the user makes "
                            "the refresh token once on the host with authorize.py)")
    client_id, client_secret, refresh_token = values
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,200}\.apps\.googleusercontent\.com", client_id):
        raise ArgumentError("YOUTUBE_CLIENT_ID is not an OAuth client id (NUMBER-TEXT.apps.googleusercontent.com)")
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", client_secret):
        raise ArgumentError("YOUTUBE_CLIENT_SECRET is not shaped like an OAuth client secret")
    if not re.fullmatch(r"[A-Za-z0-9._~+/=-]{20,2048}", refresh_token):
        raise ArgumentError("YOUTUBE_REFRESH_TOKEN is not shaped like a refresh token")
    return client_id, client_secret, refresh_token


def _checked_url(url: str) -> str:
    """URL, if it is HTTPS to one of Google's API hosts on port 443 (else nothing is sent)."""
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in HOSTS or parts.port not in (None, 443) \
            or parts.username is not None or parts.password is not None:
        raise GoogleError(f"refused to send a request to {parts.scheme}://{parts.hostname}: only "
                          f"{', '.join(sorted(HOSTS))} over HTTPS")
    return url


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=_transport, timeout=TIMEOUT, follow_redirects=False, trust_env=True,
                             headers={"User-Agent": "sandbox-ai-mcp youtube"})


async def _send(client: httpx.AsyncClient, method: str, url: str, *, headers=None, content=None,
                params=None) -> tuple[int, httpx.Headers, bytes]:
    """(status, headers, body) of one request to Google, the body at most MAX_ANSWER bytes."""
    _checked_url(url)
    async with client.stream(method, url, headers=headers, content=content, params=params) as response:
        body = bytearray()
        async for chunk in response.aiter_bytes():
            body += chunk
            if len(body) > MAX_ANSWER:
                raise GoogleError(f"Google's answer is larger than {MAX_ANSWER >> 20} MiB")
        return response.status_code, response.headers, bytes(body)


def _json(body: bytes) -> dict:
    try:
        data = json.loads(body)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _short(value, limit: int = MAX_TEXT) -> str:
    text = value if isinstance(value, str) else ""
    return text if len(text) <= limit else text[:limit] + "..."


REASONS = {
    "quotaExceeded": "the API project's daily YouTube quota is used up (10,000 units a day unless Google granted "
                     "more; videos.insert costs about 1600, captions.insert 400, thumbnails.set and videos.update "
                     "50, a list 1): it is reset at midnight Pacific Time, or ask Google for more in the Cloud "
                     "console",
    "uploadLimitExceeded": "the channel has reached YouTube's upload limit for now: try again later (a day)",
    "rateLimitExceeded": "YouTube's rate limit: retry in a minute",
    "userRateLimitExceeded": "YouTube's rate limit: retry in a minute",
    "insufficientPermissions": "the refresh token lacks the scope this needs: run authorize.py again with the "
                               "scope the tool names",
    "ACCESS_TOKEN_SCOPE_INSUFFICIENT": "the refresh token lacks the scope this needs: run authorize.py again with "
                                       "the scope the tool names",
    "youtubeSignupRequired": "the Google account has no YouTube channel yet: create one at youtube.com first",
    "forbidden": "YouTube refused this for the account (for a thumbnail: custom thumbnails need a channel verified "
                 "by phone, https://www.youtube.com/verify)",
    "videoNotFound": "no such video on this channel",
    "invalidTitle": "YouTube refused the title",
    "invalidDescription": "YouTube refused the description",
    "invalidTags": "YouTube refused the tags",
    "invalidCategoryId": "YouTube does not know this category_id",
    "invalidVideoMetadata": "YouTube refused the video's metadata",
    "mediaBodyRequired": "YouTube got no file",
    "invalidImage": "YouTube refused the image",
    "invalidMetadata": "YouTube refused the caption track's metadata",
    "contentRequired": "YouTube got no caption file",
    "captionExists": "the video has a caption track of this language and name already",
    "invalidCaptionFormat": "YouTube could not read the caption file",
}


def explain(status: int, body: bytes, what: str) -> str:
    """Why Google refused WHAT, from its error answer (reason codes named; Google's own text bounded)."""
    error = _json(body).get("error")
    reasons, message = [], ""
    if isinstance(error, dict):
        message = _short(error.get("message"))
        for item in error.get("errors") or []:
            if isinstance(item, dict) and isinstance(item.get("reason"), str):
                reasons.append(item["reason"][:60])
        for detail in error.get("details") or []:
            if isinstance(detail, dict) and isinstance(detail.get("reason"), str):
                reasons.append(detail["reason"][:60])
        reasons = list(dict.fromkeys(reasons))[:5]
    elif isinstance(error, str):
        message = _short(error)
    known = next((REASONS[reason] for reason in reasons if reason in REASONS), None)
    text = f"{what}: YouTube answered HTTP {status}"
    if reasons:
        text += f" ({', '.join(reasons)})"
    if known:
        text += f": {known}"
    elif message:
        text += f": {message}"
    return text


class Auth:
    """The access token, refreshed with the refresh token at oauth2.googleapis.com and kept in memory only."""

    def __init__(self) -> None:
        self.token: str | None = None
        self.expires = 0.0
        self.scopes: frozenset[str] | None = None
        self.lock = asyncio.Lock()

    def forget(self) -> None:
        self.token = None

    async def access_token(self, client: httpx.AsyncClient) -> str:
        async with self.lock:
            if self.token and time.monotonic() < self.expires:
                return self.token
            client_id, client_secret, refresh_token = credentials()
            form = urlencode({"client_id": client_id, "client_secret": client_secret,
                              "refresh_token": refresh_token, "grant_type": "refresh_token"}).encode()
            try:
                status, _, body = await _send(client, "POST", TOKEN_URL, content=form,
                                              headers={"Content-Type": "application/x-www-form-urlencoded",
                                                       "Accept": "application/json"})
            except httpx.HTTPError as exc:
                raise Unreachable(f"Google's token endpoint not reachable ({type(exc).__name__})") from None
            data = _json(body)
            if status != 200:
                code = data.get("error") if isinstance(data.get("error"), str) else ""
                if code == "invalid_grant":
                    raise GoogleError("Google refused the refresh token (invalid_grant: expired or revoked; an OAuth "
                                      "app still in Testing gets refresh tokens that expire after 7 days): run "
                                      "authorize.py again on the host and update YOUTUBE_REFRESH_TOKEN")
                if code in ("invalid_client", "unauthorized_client", "deleted_client"):
                    raise GoogleError(f"Google refused the OAuth client ({code}): check YOUTUBE_CLIENT_ID and "
                                      "YOUTUBE_CLIENT_SECRET (a Desktop app client of the project)")
                named = f", {_short(re.sub(r'[^A-Za-z0-9_.-]', '?', code), 60)}" if code else ""
                if 400 <= status < 500:
                    raise GoogleError(f"Google refused the token request (HTTP {status}{named})")
                raise GoogleError(f"Google's token endpoint answered HTTP {status}{named}")
            token = data.get("access_token")
            if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9._~+/=-]{10,4096}", token):
                raise GoogleError("Google's token endpoint answered without a usable access token")
            lifetime = data.get("expires_in")
            lifetime = lifetime if isinstance(lifetime, int) and not isinstance(lifetime, bool) else 3600
            _tokens.add(token)
            self.token = token
            self.expires = time.monotonic() + max(min(lifetime, 3600) - 120, 30)
            if isinstance(data.get("scope"), str):
                self.scopes = frozenset(data["scope"].split())
            return token

    async def headers(self, client: httpx.AsyncClient, tool: str, need: str | None = None) -> dict:
        token = await self.access_token(client)
        for key in (tool, need) if need else (tool,):  # the tool's own scope first, then that of the read before it
            accepted, name = TOOL_SCOPES[key]
            if self.scopes is not None and not self.scopes & accepted:
                granted = ", ".join(sorted(s.removeprefix(SCOPE) for s in self.scopes)) or "none"
                why = f" for {key} first (YOUTUBE_ALLOW_PUBLIC=1 skips that)" if key == need else ""
                raise GoogleError(f"{tool} needs the scope youtube.{name}{why} (https://www.googleapis.com/auth/"
                                  f"youtube.{name}); the refresh token has {granted}: run authorize.py again with "
                                  f"--scopes including {name} and update YOUTUBE_REFRESH_TOKEN")
        return {"Authorization": f"Bearer {token}"}


AUTH = Auth()


async def _api(client: httpx.AsyncClient, tool: str, method: str, url: str, *, headers=None, content=None,
               params=None, need: str | None = None) -> tuple[int, httpx.Headers, bytes]:
    """One authorized request; a 401 drops the access token and is tried once more with a new one."""
    for attempt in (1, 2):
        auth = await AUTH.headers(client, tool, need)
        try:
            status, answer_headers, body = await _send(client, method, url, headers={**(headers or {}), **auth},
                                                       content=content, params=params)
        except httpx.HTTPError as exc:
            raise Unreachable(f"YouTube not reachable ({type(exc).__name__})") from None
        if status == 401 and attempt == 1:
            AUTH.forget()
            continue
        return status, answer_headers, body
    raise AssertionError("unreachable")


async def _api_json(client, tool: str, method: str, url: str, what: str, **kwargs) -> dict:
    status, _, body = await _api(client, tool, method, url, **kwargs)
    if not 200 <= status < 300:
        if status == 401:
            raise GoogleError(f"{what}: YouTube refused the access token twice (HTTP 401): run authorize.py again")
        raise GoogleError(explain(status, body, what))
    data = _json(body)
    if not data and body.strip():
        raise GoogleError(f"{what}: YouTube did not answer JSON")
    return data


# --- upload_video: the resumable upload protocol -----------------------------------------------------------------

def _session_url(location: str | None) -> str:
    """The upload session's address from the Location header, only on Google's upload path."""
    if not location:
        raise GoogleError("YouTube gave no upload session (no Location header)")
    _checked_url(location)
    if not urlsplit(location).path.startswith("/upload/youtube/v3/videos"):
        raise GoogleError("YouTube's upload session is not on its upload path: refused")
    # whoever has the session can write into the upload: redacted also where Google names it without upload_id=
    _tokens.add(location)
    _tokens.update(value for value in parse_qs(urlsplit(location).query).get("upload_id", []) if len(value) >= 8)
    return location


def _received(headers: httpx.Headers, size: int) -> int:
    """How many bytes the session has, from a 308's Range header (none: 0)."""
    value = headers.get("range")
    if not value:
        return 0
    match = RANGE.fullmatch(value.strip())
    if not match or int(match.group(1)) >= size:
        raise GoogleError("YouTube answered an upload status that does not fit the file")
    return int(match.group(1)) + 1


async def _backoff(failures: int) -> None:
    await _sleep(min(2 ** failures, 64) + random.random())


async def _start_session(client, metadata: dict, size: int, mime: str) -> str:
    url = UPLOAD_API + "videos?" + urlencode({"uploadType": "resumable", "part": ",".join(metadata)})
    body = json.dumps(metadata).encode("utf-8")
    headers = {"Content-Type": "application/json; charset=UTF-8", "X-Upload-Content-Length": str(size),
               "X-Upload-Content-Type": mime}
    for failures in range(1, RETRIES + 1):
        try:
            status, answer_headers, answer = await _api(client, "upload_video", "POST", url, headers=headers,
                                                        content=body)
        except Unreachable:
            if failures == RETRIES:
                raise
            await _backoff(failures)
            continue
        if status == 200:
            return _session_url(answer_headers.get("location"))
        if status in (429, 500, 502, 503, 504) and failures < RETRIES:
            await _backoff(failures)
            continue
        raise GoogleError(explain(status, answer, "upload_video (starting the upload)"))
    raise GoogleError("upload_video: YouTube did not start the upload")


async def _resumable_upload(client, fd: int, size: int, metadata: dict, mime: str) -> tuple[dict, int]:
    """(the video resource, how often the upload was resumed after an error) after sending the file in CHUNK
    pieces. After a 5xx, 429 or a broken connection the session is asked how much it has ("bytes */SIZE") and the
    upload goes on from there; RETRIES failures in a row (or as many answers without progress) give up."""
    session = await _start_session(client, metadata, size, mime)
    offset, failures, stalls, resumed, check_first = 0, 0, 0, 0, False
    # A session that takes bytes and then "forgets" them again (a Range lower than before) would otherwise be fed
    # for ever: at most twice the file plus a resent piece per allowed failure goes out.
    sent, budget = 0, 2 * size + 2 * RETRIES * CHUNK
    started = time.monotonic()
    while True:
        try:
            if check_first:
                status, headers, body = await _api(client, "upload_video", "PUT", session, content=b"",
                                                   headers={"Content-Range": f"bytes */{size}"})
            else:
                length = min(CHUNK, size - offset)
                if sent + length > budget:
                    raise GoogleError(f"upload_video: {sent} bytes sent for a file of {size} and YouTube has still not "
                                      "taken it (it took fewer bytes than sent again and again): try again later - "
                                      "nothing was published")
                sent += length
                piece = await asyncio.to_thread(os.pread, fd, length, offset)
                if len(piece) != length:
                    raise ArgumentError("path: the file changed while it was uploaded (nothing was published)")
                status, headers, body = await _api(client, "upload_video", "PUT", session, content=piece,
                                                   headers={"Content-Type": mime, "Content-Range":
                                                            f"bytes {offset}-{offset + length - 1}/{size}"})
        except Unreachable:
            status, headers, body = 0, httpx.Headers(), b""
        if status in (200, 201):
            data = _json(body)
            if not isinstance(data.get("id"), str):
                raise GoogleError("upload_video: YouTube finished the upload without a video id")
            return data, resumed
        if status == 308:
            received = _received(headers, size)
            if check_first:
                resumed += 1
            elif received <= offset:
                stalls += 1
                if stalls >= RETRIES:
                    raise GoogleError(f"upload_video: YouTube took no more bytes {RETRIES} times in a row after "
                                      f"{offset} of {size}: try again later - nothing was published")
            if received > offset:
                failures = stalls = 0
            offset, check_first = received, False
            log.info("upload_video: %d of %d bytes (%d%%) after %.0f s", offset, size, offset * 100 // size,
                     time.monotonic() - started)
            continue
        if status in (404, 410):
            raise GoogleError(f"upload_video: YouTube's upload session expired or is gone (HTTP {status}): call "
                              "upload_video again - nothing was published")
        if status in (0, 429, 500, 502, 503, 504):
            failures += 1
            last = "no connection" if status == 0 else f"HTTP {status}"
            if failures >= RETRIES:
                raise GoogleError(f"upload_video: YouTube failed {RETRIES} times in a row (last: {last}) after "
                                  f"{offset} of {size} bytes: try again later - nothing was published")
            log.info("upload_video: %s, retry %d of %d", last, failures, RETRIES - 1)
            await _backoff(failures)
            check_first = True
            continue
        if status == 401:
            raise GoogleError("upload_video: YouTube refused the access token twice (HTTP 401): run authorize.py "
                              "again")
        raise GoogleError(explain(status, body, "upload_video"))


def _video_answer(data: dict) -> dict:
    snippet = data.get("snippet") if isinstance(data.get("snippet"), dict) else {}
    status = data.get("status") if isinstance(data.get("status"), dict) else {}
    video_id = data.get("id") if isinstance(data.get("id"), str) and VIDEO_ID.fullmatch(data["id"]) else None
    out = {"video_id": video_id, "title": _short(snippet.get("title")),
           "privacy": _short(status.get("privacyStatus"), 20), "upload_status": _short(status.get("uploadStatus"), 20)}
    if video_id:
        out["url"] = f"https://youtu.be/{video_id}"
        out["studio"] = f"https://studio.youtube.com/video/{video_id}/edit"
    for key, name in (("selfDeclaredMadeForKids", "made_for_kids"), ("containsSyntheticMedia",
                                                                      "contains_synthetic_media")):
        if isinstance(status.get(key), bool):
            out[name] = status[key]
    for key in ("rejectionReason", "failureReason"):
        if isinstance(status.get(key), str):
            out[key] = _short(status[key], 60)
    return out


async def _guarded(work):
    """The answer of WORK (redacted), or {"error": ...} naming why it failed - never a secret."""
    try:
        return scrub(await work)
    except (ArgumentError, GoogleError) as exc:
        return {"error": redact(str(exc))}
    except Exception as exc:  # noqa: BLE001 - an exception's text could hold a secret
        log.error("unexpected %s", type(exc).__name__)
        return {"error": f"internal error ({type(exc).__name__})"}


WRITES = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)
CHANGES = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=True)
READS = ToolAnnotations(readOnlyHint=True, openWorldHint=True)


@mcp.tool(annotations=WRITES)
async def upload_video(path: str, title: str, made_for_kids: bool, description: str = "",
                       tags: list[str] | None = None, category_id: str | int = "22", privacy: str = "private",
                       default_language: str | None = None, chapters: list[str | dict[str, str]] | None = None,
                       contains_synthetic_media: bool = False) -> dict:
    """WRITES to the user's YouTube channel: uploads the video file PATH (under /upload: .mp4, .mov, .webm, .mkv,
    ...) as a new video. privacy: private (default) or unlisted (public only if the server allows it).
    made_for_kids is required: YouTube's audience setting (COPPA). contains_synthetic_media (default false) is
    YouTube's disclosure of realistic altered or synthetic content: set it true when the video shows realistic
    people, places or events made or changed with AI or other tools. title 1-100 characters, description up to
    5000 bytes, no < or > in either; tags up to 500 characters together; category_id as text (22 People & Blogs,
    27 Education, 28 Science & Technology); default_language a BCP-47 code (the language of title, description
    and speech); chapters [{"start": "0:00", "title": "Intro"}, ...] are added to the description (first at 0:00,
    at least 3, each 10 s or longer). Costs about 1600 of the project's 10,000 daily quota units. Needs scope
    youtube.upload."""
    async def work():
        parts = _upload_parts(path, "path", VIDEO_TYPES)
        snippet = {"title": _title(title), "categoryId": _category(category_id)}
        lines = _chapters(chapters)
        text = _with_chapters(_description(description), lines)
        if text:
            snippet["description"] = text
        tag_list = _tags(tags)
        if tag_list:
            snippet["tags"] = tag_list
        language = _language(default_language, "default_language")
        if language:
            snippet["defaultLanguage"] = snippet["defaultAudioLanguage"] = language
        status = {"privacyStatus": _privacy(privacy),
                  "selfDeclaredMadeForKids": _flag(made_for_kids, "made_for_kids", KIDS),
                  "containsSyntheticMedia": _flag(contains_synthetic_media, "contains_synthetic_media", SYNTHETIC)}
        limit = max_upload()
        credentials()
        if _upload_running.locked():
            raise ArgumentError("upload_video: another upload is running in this connection: wait for it")
        async with _upload_running:
            fd, size = _open_upload(parts, "path", limit)
            try:
                if not _looks_like_video(_head(fd)):
                    raise ArgumentError("path: the file does not start like a video (MP4, MOV, WebM, Matroska, AVI, "
                                        "MPEG, WMV or FLV)")
                mime = VIDEO_TYPES[os.path.splitext(parts[-1])[1].lower()]
                log.info("upload_video: %d bytes, %s", size, status["privacyStatus"])
                async with _client() as client:
                    data, resumed = await _resumable_upload(client, fd, size, {"snippet": snippet, "status": status},
                                                           mime)
            finally:
                os.close(fd)
        answer = _video_answer(data)
        answer.update(bytes=size, resumed_after_errors=resumed, chapters=len(lines),
                      quota=f"videos.insert costs about {QUOTA['videos.insert']} of the project's daily quota "
                            "(10,000 units unless Google granted more)",
                      note=UNVERIFIED + " YouTube processes the video for a while before it plays; list_my_videos "
                           "shows its state.")
        return answer
    return await _guarded(work())


@mcp.tool(annotations=CHANGES)
async def set_thumbnail(video_id: str, path: str) -> dict:
    """WRITES to the user's YouTube channel: makes the image PATH (under /upload, JPEG or PNG, at most 2 MB;
    1280x720 recommended, at least 640 wide) the thumbnail of the video VIDEO_ID; a public video only if the
    server allows public videos. Custom thumbnails need a channel verified by phone. Costs 50 quota units (and 1
    to read the video's privacy first). Needs scope youtube.upload (and youtube.readonly for that read)."""
    async def work():
        vid = _video_id(video_id)
        parts = _upload_parts(path, "path", IMAGE_TYPES)
        credentials()
        fd, size = _open_upload(parts, "path", MAX_THUMBNAIL)
        try:
            data = _read_all(fd, size)
        finally:
            os.close(fd)
        found = _image_size(data)
        if found is None:
            raise ArgumentError("path: not a JPEG or PNG image")
        mime, width, height = found
        url = UPLOAD_API + "thumbnails/set?" + urlencode({"videoId": vid, "uploadType": "media"})
        async with _client() as client:
            await _refuse_public(client, "set_thumbnail", vid)
            await _api_json(client, "set_thumbnail", "POST", url, "set_thumbnail", content=data,
                            headers={"Content-Type": mime})
        answer = {"video_id": vid, "thumbnail": f"{width}x{height} {mime}, {size} bytes",
                  "quota": f"thumbnails.set costs {QUOTA['thumbnails.set']} units"}
        if (width, height) != (1280, 720):
            answer["note"] = "YouTube recommends 1280x720 (16:9, at least 640 wide)"
        return answer
    return await _guarded(work())


async def _refuse_public(client, tool: str, vid: str) -> None:
    """Reads the privacy of the video VID (videos.list, 1 unit) and refuses a change to a public one (or one
    scheduled to become public) unless the user allowed public videos; an unknown video is refused too."""
    if _public_allowed():
        return
    found = await _api_json(client, tool, "GET", API + "videos", f"{tool} ({READ_STATUS})",
                            params={"part": "status", "id": vid}, need=READ_STATUS)
    items = found.get("items") if isinstance(found.get("items"), list) else []
    current = items[0] if items and isinstance(items[0], dict) else None
    if current is None or current.get("id") != vid:
        raise GoogleError(f"{tool}: no video {vid} on this channel")
    _not_public(tool, vid, current.get("status"))


def _caption_text(data: bytes, suffix: str) -> None:
    if b"\0" in data:
        raise ArgumentError("path: a caption file is text, this one has NUL bytes")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ArgumentError("path: a caption file in UTF-8") from None
    if suffix == ".vtt" and not text.startswith("WEBVTT"):
        raise ArgumentError("path: a WebVTT file starts with WEBVTT")
    if suffix == ".srt" and not SRT_TIMING.search(text.replace("\r\n", "\n")):
        raise ArgumentError("path: not an SRT file (no line like 00:00:01,000 --> 00:00:04,000)")


@mcp.tool(annotations=WRITES)
async def upload_captions(video_id: str, path: str, language: str, name: str = "") -> dict:
    """WRITES to the user's YouTube channel: adds the caption file PATH (under /upload, .srt or .vtt in UTF-8, at
    most 5 MiB) to the video VIDEO_ID as a track of LANGUAGE (BCP-47: en, de, en-US), NAME optional (up to 150
    characters, shown beside the language); a public video only if the server allows public videos. Costs 400
    quota units (and 1 to read the video's privacy first). Needs scope youtube.force-ssl."""
    async def work():
        vid = _video_id(video_id)
        parts = _upload_parts(path, "path", CAPTION_TYPES)
        lang = _language(language, "language")
        if not lang:
            raise ArgumentError("language: a BCP-47 language code such as en, de, en-US or pt-BR")
        if not isinstance(name, str) or len(name.strip()) > 150:
            raise ArgumentError("name: at most 150 characters")
        track = name.strip()
        _no_controls(track, "name")
        credentials()
        fd, size = _open_upload(parts, "path", MAX_CAPTIONS)
        try:
            data = _read_all(fd, size)
        finally:
            os.close(fd)
        suffix = os.path.splitext(parts[-1])[1].lower()
        _caption_text(data, suffix)
        meta = json.dumps({"snippet": {"videoId": vid, "language": lang, "name": track, "isDraft": False}}).encode()
        boundary = "sandbox-ai-mcp-" + secrets.token_hex(16)
        if boundary.encode() in data:
            raise ArgumentError("path: the caption file contains the multipart boundary; try again")
        body = b"".join((f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode(), meta,
                         f"\r\n--{boundary}\r\nContent-Type: {CAPTION_TYPES[suffix]}\r\n\r\n".encode(), data,
                         f"\r\n--{boundary}--\r\n".encode()))
        url = UPLOAD_API + "captions?" + urlencode({"part": "snippet", "uploadType": "multipart"})
        async with _client() as client:
            await _refuse_public(client, "upload_captions", vid)
            answer = await _api_json(client, "upload_captions", "POST", url, "upload_captions", content=body,
                                     headers={"Content-Type": f"multipart/related; boundary={boundary}"})
        snippet = answer.get("snippet") if isinstance(answer.get("snippet"), dict) else {}
        return {"video_id": vid, "caption_id": _short(answer.get("id"), 100),
                "language": _short(snippet.get("language"), 35),
                "name": _short(snippet.get("name"), 150), "status": _short(snippet.get("status"), 20),
                "bytes": size, "quota": f"captions.insert costs {QUOTA['captions.insert']} units"}
    return await _guarded(work())


SNIPPET_KEYS = ("title", "description", "tags", "categoryId", "defaultLanguage", "defaultAudioLanguage")
STATUS_KEYS = ("privacyStatus", "embeddable", "license", "publicStatsViewable", "publishAt", "selfDeclaredMadeForKids",
               "containsSyntheticMedia")


@mcp.tool(annotations=CHANGES)
async def update_metadata(video_id: str, title: str | None = None, description: str | None = None,
                          tags: list[str] | None = None, category_id: str | int | None = None,
                          privacy: str | None = None,
                          made_for_kids: bool | None = None, contains_synthetic_media: bool | None = None,
                          default_language: str | None = None,
                          chapters: list[str | dict[str, str]] | None = None) -> dict:
    """WRITES to the user's YouTube channel: changes only the given fields of the video VIDEO_ID (the others stay
    as they are; the same rules as upload_video). chapters need the description too (they are added to it); tags
    [] removes the tags. privacy private or unlisted; making a video public, or changing one that is public or
    scheduled to become public, only if the server allows public videos. Costs 51 quota units. Needs scope
    youtube.force-ssl."""
    async def work():
        vid = _video_id(video_id)
        snippet, status = {}, {}
        if title is not None:
            snippet["title"] = _title(title)
        if chapters is not None and description is None:
            raise ArgumentError("chapters: give the description too (the chapters are added to it)")
        if description is not None:
            snippet["description"] = _with_chapters(_description(description), _chapters(chapters))
        if tags is not None:
            snippet["tags"] = _tags(tags)
        if category_id is not None:
            snippet["categoryId"] = _category(category_id)
        if default_language is not None:
            language = _language(default_language, "default_language")
            snippet["defaultLanguage"] = snippet["defaultAudioLanguage"] = language
        if privacy is not None:
            status["privacyStatus"] = _privacy(privacy)
        if made_for_kids is not None:
            status["selfDeclaredMadeForKids"] = _flag(made_for_kids, "made_for_kids", KIDS)
        if contains_synthetic_media is not None:
            status["containsSyntheticMedia"] = _flag(contains_synthetic_media, "contains_synthetic_media", SYNTHETIC)
        if not snippet and not status:
            raise ArgumentError("update_metadata: nothing to change (give at least one field)")
        credentials()
        async with _client() as client:
            found = await _api_json(client, "update_metadata", "GET", API + "videos", "update_metadata (reading the "
                                    "video)", params={"part": "snippet,status", "id": vid})
            items = found.get("items") if isinstance(found.get("items"), list) else []
            current = items[0] if items and isinstance(items[0], dict) else None
            if current is None or current.get("id") != vid:
                raise GoogleError(f"update_metadata: no video {vid} on this channel")
            _not_public("update_metadata", vid, current.get("status"))
            body, parts = {"id": vid}, []
            if snippet:
                now = current.get("snippet") if isinstance(current.get("snippet"), dict) else {}
                merged = {key: now[key] for key in SNIPPET_KEYS if key in now}
                merged.update(snippet)
                for key in ("defaultLanguage", "defaultAudioLanguage"):
                    if merged.get(key) is None:
                        merged.pop(key, None)
                if not merged.get("tags"):
                    merged.pop("tags", None)
                body["snippet"], parts = merged, parts + ["snippet"]
            if status:
                now = current.get("status") if isinstance(current.get("status"), dict) else {}
                merged = {key: now[key] for key in STATUS_KEYS if key in now}
                merged.update(status)
                if merged.get("privacyStatus") != "private":
                    merged.pop("publishAt", None)  # a scheduled publication exists only for a private video
                body["status"], parts = merged, parts + ["status"]
            updated = await _api_json(client, "update_metadata", "PUT", API + "videos?" + urlencode(
                {"part": ",".join(parts)}), "update_metadata", content=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json; charset=UTF-8"})
        answer = _video_answer({**updated, "id": updated.get("id", vid)})
        answer["changed"] = sorted({"title": "title", "description": "description", "tags": "tags",
                                    "categoryId": "category_id", "defaultLanguage": "default_language"}[key]
                                   for key in snippet if key != "defaultAudioLanguage") + sorted(
            {"privacyStatus": "privacy", "selfDeclaredMadeForKids": "made_for_kids",
             "containsSyntheticMedia": "contains_synthetic_media"}[key] for key in status)
        answer["quota"] = (f"videos.list {QUOTA['videos.list']} + videos.update {QUOTA['videos.update']} units")
        if status.get("privacyStatus") in ("unlisted", "public"):
            answer["note"] = UNVERIFIED
        return answer
    return await _guarded(work())


@mcp.tool(annotations=READS)
async def list_my_videos(max_results: int = 10) -> dict:
    """Read-only: the channel's latest uploads (newest first, 1-50): id, title, when, privacy, upload state
    (uploaded, processed, rejected, failed) and why YouTube rejected one. Costs 3 quota units. Needs scope
    youtube.readonly (or youtube.force-ssl)."""
    async def work():
        count = _int(max_results, "max_results", 1, 50)
        credentials()
        async with _client() as client:
            channels = await _api_json(client, "list_my_videos", "GET", API + "channels", "list_my_videos",
                                       params={"part": "snippet,contentDetails", "mine": "true"})
            items = channels.get("items") if isinstance(channels.get("items"), list) else []
            channel = items[0] if items and isinstance(items[0], dict) else None
            if channel is None:
                raise GoogleError("list_my_videos: the Google account has no YouTube channel")
            uploads = ((channel.get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads")
            if not isinstance(uploads, str) or not re.fullmatch(r"[A-Za-z0-9_-]{2,64}", uploads):
                raise GoogleError("list_my_videos: YouTube named no uploads playlist for the channel")
            page = await _api_json(client, "list_my_videos", "GET", API + "playlistItems", "list_my_videos",
                                   params={"part": "snippet,contentDetails,status", "playlistId": uploads,
                                           "maxResults": str(count)})
            rows = []
            for item in (page.get("items") if isinstance(page.get("items"), list) else [])[:count]:
                if not isinstance(item, dict):
                    continue
                details = item.get("contentDetails") if isinstance(item.get("contentDetails"), dict) else {}
                snippet = item.get("snippet") if isinstance(item.get("snippet"), dict) else {}
                vid = details.get("videoId")
                if isinstance(vid, str) and VIDEO_ID.fullmatch(vid):
                    rows.append({"video_id": vid, "title": _short(snippet.get("title")),
                                 "published": _short(details.get("videoPublishedAt") or snippet.get("publishedAt"), 40),
                                 "url": f"https://youtu.be/{vid}"})
            if rows:
                states = await _api_json(client, "list_my_videos", "GET", API + "videos", "list_my_videos",
                                         params={"part": "status", "id": ",".join(r["video_id"] for r in rows),
                                                 "maxResults": str(count)})
                by_id = {v.get("id"): v.get("status") for v in states.get("items") or []
                         if isinstance(v, dict) and isinstance(v.get("status"), dict)}
                for row in rows:
                    state = by_id.get(row["video_id"]) or {}
                    row["privacy"] = _short(state.get("privacyStatus"), 20)
                    row["upload_status"] = _short(state.get("uploadStatus"), 20)
                    for key in ("rejectionReason", "failureReason"):
                        if isinstance(state.get(key), str):
                            row[key] = _short(state[key], 60)
        snippet = channel.get("snippet") if isinstance(channel.get("snippet"), dict) else {}
        return {"channel": {"id": _short(channel.get("id"), 64), "title": _short(snippet.get("title"))},
                "videos": rows, "count": len(rows), "quota": "3 units (channels, playlistItems, videos.list)"}
    return await _guarded(work())


if __name__ == "__main__":
    mcp.run("stdio")
