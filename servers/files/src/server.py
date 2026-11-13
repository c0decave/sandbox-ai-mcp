#!/usr/bin/env python3
"""files MCP server (sandbox-ai-mcp): read and write the files of an agent's workspace reliably, made for
small local models that get file writes wrong.

The workspace is the folder mounted at /work (written only when mounted read-write); up to three more folders
mounted at /ref1, /ref2 and /ref3 are only ever read. Nothing outside these folders is reachable: a path is
relative to /work or absolute under one of them, ".." is refused, and every path is walked one name at a time
from the folder's open descriptor (openat with O_NOFOLLOW): a symbolic link is followed only by the read tools
and only while it stays inside its folder; the write tools follow none. Only regular files are read or written
(no devices, pipes or sockets), at most FILES_MAX_BYTES per call.

Tools:
    reads:  read_file, list_dir, glob, search, stat, diff, checksum
    writes: write_file, write_markdown, edit_file, insert_lines, delete_lines, append_file, apply_patch,
            move, copy, mkdir, delete

Every write is atomic (a temporary file in the same folder, fsync, rename; the folder fsynced), keeps the
file's permissions, line endings and byte order mark, and never replaces a file that changed since it was read
(expected_sha256, and the file must still be the one that was read). An existing file is replaced only with
expected_sha256 or overwrite=true: no blind clobbering. Every write answers with what changed (lines added and
removed, the new sha256). delete moves into /work/.trash (FILES_TRASH=0: deletes). FILES_READONLY=1 refuses every
write. write_markdown repairs what local models typically get wrong in Markdown and reports each repair.

Standard library and the MCP SDK only; no network.
"""

from __future__ import annotations

import contextlib
import difflib
import errno
import fnmatch
import hashlib
import json
import logging
import os
import re
import secrets
import shutil
import signal
import stat as st
import sys
import threading
import time
import unicodedata
from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

WORK = "/work"
REFS = ("/ref1", "/ref2", "/ref3")
#: Each folder the server can reach (the path a tool argument names) -> where it is in this container. Only WORK is
#: ever written. Tests point them at temporary folders.
ROOTS: dict[str, str] = {WORK: WORK, **{ref: ref for ref in REFS}}
TRASH = ".trash"
#: Folders no write goes into: git's own (hooks would run on the host) and the trash (only delete fills it).
PROTECTED = (".git",)
#: Folders glob, search and list_dir do not descend into unless the path names them.
SKIP_DIRS = frozenset({".git", TRASH, "node_modules", "__pycache__", ".venv"})
MARKDOWN_SUFFIXES = (".md", ".markdown", ".mdx", ".mkd", ".mdown")

MAX_BYTES_DEFAULT = 8 << 20     # FILES_MAX_BYTES: bytes one call reads or writes
MAX_BYTES_LIMIT = 256 << 20
MAX_PATH = 4096
MAX_READ_LINES = 1000           # lines of one read_file answer
MAX_READ_CHARS = 60_000         # characters of one read_file answer
MAX_ENTRIES = 500               # entries of list_dir, results of glob
MAX_VISIT = 200_000             # entries glob and search look at
MAX_RESULTS = 200               # search matches
MAX_LINE_SHOWN = 300            # characters of a search match's line
MAX_DIFF_LINES = 400
MAX_DIFF_CHARS = 40_000
MAX_PREVIEW = 12                # lines of the preview after an edit
MAX_COPY_BYTES = 1 << 30
MAX_COPY_ENTRIES = 10_000
MAX_LINKS = 16                  # links followed for one path
TIME_LIMIT = 20.0               # seconds of glob, search, diff
CALL_LIMIT = 120.0              # seconds of any call
MAX_NOTES = 40

DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_NOCTTY | os.O_CLOEXEC
BOM = b"\xef\xbb\xbf"
_old_umask = os.umask(0o022)
os.umask(_old_umask)
UMASK = _old_umask

logging.basicConfig(level=logging.WARNING, stream=sys.stderr,
                    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
log = logging.getLogger("files-mcp")

mcp = FastMCP("files-mcp", instructions=(
    "Reads and writes files of the user's workspace, the folder /work (more folders, read-only: /ref1, /ref2, "
    "/ref3 when mounted; list_dir('/') shows them). Paths are relative to /work (notes/todo.md) or absolute "
    "(/work/notes/todo.md); '..' is not allowed. To change a file: read_file first, then edit_file (replace one "
    "exact piece of text) for small changes, or write_file / write_markdown for the whole file with "
    "expected_sha256 set to the sha256 read_file gave. Use write_markdown for every .md file: it repairs common "
    "Markdown mistakes and lists each repair. Every write answers with lines added/removed and the new sha256: "
    "check them. delete moves into /work/.trash."))


class Refused(ValueError):
    """A tool argument or a file this server does not take; the text says why and what to do instead."""


class TimeLimit(Exception):
    """A walk or a comparison took longer than TIME_LIMIT."""


# --- settings ------------------------------------------------------------------------------------------------------

def _flag(name: str, default: bool) -> bool:
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return default
    if value in ("1", "true", "yes", "on"):
        return True
    if value in ("0", "false", "no", "off"):
        return False
    raise Refused(f"{name} must be 1 or 0 (it is {value[:20]!r}): the user sets it")


def readonly() -> bool:
    return _flag("FILES_READONLY", False)


def trash_on() -> bool:
    return _flag("FILES_TRASH", True)


def max_bytes() -> int:
    value = os.environ.get("FILES_MAX_BYTES", "").strip()
    if not value:
        return MAX_BYTES_DEFAULT
    match = re.fullmatch(r"([0-9]{1,12})([kKmMgG]?)", value)
    if not match:
        raise Refused("FILES_MAX_BYTES must be a number of bytes (like 8388608 or 8M): the user sets it")
    number = int(match.group(1)) << {"": 0, "k": 10, "m": 20, "g": 30}[match.group(2).lower()]
    if not 1024 <= number <= MAX_BYTES_LIMIT:
        raise Refused(f"FILES_MAX_BYTES must be from 1K to {MAX_BYTES_LIMIT >> 20}M: the user sets it")
    return number


# --- arguments -----------------------------------------------------------------------------------------------------

def _controls(value: str) -> bool:
    return any(ord(c) < 32 or 0x7f <= ord(c) < 0xa0 or c in "\u2028\u2029" for c in value)


def _int(value, name: str, low: int, high: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise Refused(f"{name}: a whole number")
    if value < low or (high is not None and value > high):
        raise Refused(f"{name}: from {low}" + (f" to {high}" if high is not None else "") + f" (not {value})")
    return value


def _bool(value, name: str) -> bool:
    if not isinstance(value, bool):
        raise Refused(f"{name}: true or false")
    return value


def _text(value, name: str, *, empty: bool = True) -> str:
    if not isinstance(value, str):
        raise Refused(f"{name}: a text")
    if not empty and not value:
        raise Refused(f"{name}: must not be empty")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise Refused(f"{name}: contains characters that are not valid Unicode (lone surrogates)") from None
    return value


def _sha(value, name: str = "expected_sha256") -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not re.fullmatch(r"(?:sha256:)?[0-9a-fA-F]{64}", value.strip()):
        raise Refused(f"{name}: the 64 hex digits of the sha256 that read_file or stat gave for the file")
    return value.strip().lower().removeprefix("sha256:")


def roots_shown() -> str:
    return ", ".join(r for r in ROOTS if r == WORK or os.path.isdir(ROOTS[r]))


def split_path(value, name: str = "path") -> tuple[str, list[str]]:
    """(root, names) of the path VALUE, checked without touching the file system: relative to /work or absolute
    under a root; no '..', no control characters."""
    if not isinstance(value, str) or not value.strip():
        raise Refused(f"{name}: a path inside {WORK}, like notes/todo.md or {WORK}/notes/todo.md")
    path = value.strip()
    if len(path) > MAX_PATH or "\0" in path or _controls(path):
        raise Refused(f"{name}: no control characters, at most {MAX_PATH} characters")
    if path.startswith("~"):
        raise Refused(f"{name}: ~ (a home folder) is not reachable here; paths are inside {WORK}, like {WORK}/a.md")
    if "\\" in path:
        raise Refused(f"{name}: use / between folder names, not \\ (like docs/a.md)")
    if path.startswith("/"):
        root = next((r for r in ROOTS if path == r or path.startswith(r + "/")), None)
        if root is None:
            raise Refused(f"{name}: {path[:200]} is outside the folders this server can reach ({roots_shown()}); "
                          f"a relative path is taken inside {WORK}")
        rest = path[len(root):]
    else:
        root, rest = WORK, path
    names = [part for part in rest.split("/") if part not in ("", ".")]
    if ".." in names:
        raise Refused(f"{name}: '..' is not allowed in a path: name the file from {root} down "
                      f"(like {root}/docs/a.md)")
    for part in names:
        if len(part.encode("utf-8", "surrogatepass")) > 255:
            raise Refused(f"{name}: a name in the path is longer than 255 bytes")
    return root, names


def shown(root: str, names: list[str]) -> str:
    return root + ("/" + "/".join(names) if names else "")


def _kind(mode: int) -> str:
    if st.S_ISREG(mode):
        return "file"
    if st.S_ISDIR(mode):
        return "dir"
    if st.S_ISLNK(mode):
        return "link"
    if st.S_ISFIFO(mode):
        return "pipe"
    if st.S_ISSOCK(mode):
        return "socket"
    return "device"


def _kind_text(mode: int) -> str:
    return {"file": "a file", "dir": "a folder", "link": "a symbolic link", "pipe": "a named pipe (FIFO)",
            "socket": "a socket", "device": "a device"}[_kind(mode)]


# --- walking the folders: one name at a time, from the root's descriptor, never through a link that leaves it ------

class Place:
    """An open folder (DIRFD) and a NAME in it (None: the folder itself, only for a root); NAMES leads there from
    ROOT. LINKS lists the links followed on the way. close() closes the folder."""

    def __init__(self, root: str, dirfd: int, names: list[str], name: str | None, links: list[str]):
        self.root, self.dirfd, self.names, self.name, self.links = root, dirfd, names, name, links

    @property
    def parts(self) -> list[str]:
        return self.names + ([self.name] if self.name is not None else [])

    @property
    def path(self) -> str:
        return shown(self.root, self.parts)

    def lstat(self) -> os.stat_result | None:
        if self.name is None:
            return os.fstat(self.dirfd)
        try:
            return os.stat(self.name, dir_fd=self.dirfd, follow_symlinks=False)
        except FileNotFoundError:
            return None

    def close(self) -> None:
        if self.dirfd >= 0:
            os.close(self.dirfd)
            self.dirfd = -1

    def __enter__(self) -> Place:
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def open_root(root: str) -> int:
    try:
        return os.open(ROOTS[root], DIR_FLAGS)
    except OSError:
        hint = (f" (the user adds it: sandbox-ai mcp add files --mount {WORK}=FOLDER:rw)" if root == WORK else
                f" (the user adds it with --mount {root}=FOLDER:ro)")
        raise Refused(f"no folder is mounted at {root}{hint}") from None


def _link_parts(root: str, target: str) -> list[str] | None:
    """The names of an absolute link TARGET below ROOT (as this container or the tests see it), None outside."""
    for base in dict.fromkeys((root, ROOTS[root].rstrip("/") or "/")):
        if target == base or target.startswith(base + "/"):
            return [p for p in target[len(base):].split("/") if p not in ("", ".")]
    return None


def locate(value, name: str = "path", *, follow: bool = True, write: bool = False, keep_link: bool = False,
           create_dirs: bool = False, created: list[str] | None = None, from_trash: bool = False) -> Place:
    """The Place of path VALUE. Each folder on the way is opened by its name in the one before (O_NOFOLLOW,
    O_DIRECTORY), so nothing swapped in meanwhile leads elsewhere. With FOLLOW (the read tools) a link is
    followed while it stays inside its root ('..' of a link target goes up the folders actually walked, never
    above the root); without (the write tools) a link on the way is refused. The last name need not exist.
    KEEP_LINK: a link as the last name is the place itself (stat, delete, move), neither followed nor refused.
    WRITE: the path must be writable (writable(); FROM_TRASH: it may be in the trash, for move's source - a
    restore); CREATE_DIRS makes missing folders (their paths into CREATED)."""
    root, names = split_path(value, name)
    if write:
        writable(root, names, name, from_trash)
        follow = False
    stack = [open_root(root)]
    if write and os.fstatvfs(stack[0]).f_flag & os.ST_RDONLY:
        os.close(stack[0])
        raise Refused(f"{name}: the folder at {root} is mounted read-only (the user mounts it with "
                      f"--mount {root}=FOLDER:rw to let this server write)")
    walked: list[str] = []
    links: list[str] = []
    todo = list(names)
    hops = 0
    try:
        while todo:
            part = todo[0]
            if part in ("", "."):
                todo.pop(0)
                continue
            if part == "..":  # only from a link's target
                if len(stack) == 1:
                    raise Refused(f"{name}: {links[-1]} leads outside {root}: links out of the mounted folders "
                                  "are never followed")
                os.close(stack.pop())
                walked.pop()
                todo.pop(0)
                continue
            here = shown(root, walked + [part])
            try:
                info = os.stat(part, dir_fd=stack[-1], follow_symlinks=False)
            except FileNotFoundError:
                info = None
            except OSError as exc:
                raise Refused(f"{name}: {here} cannot be looked at ({exc.strerror})") from None
            last = len(todo) == 1
            if info is None:
                if last:
                    break
                if not create_dirs:
                    raise Refused(f"{name}: the folder {here} does not exist" +
                                  (" (create_dirs=true makes it)" if write else ""))
                try:
                    os.mkdir(part, 0o777, dir_fd=stack[-1])
                except FileExistsError:
                    pass
                except OSError as exc:
                    raise Refused(f"{name}: the folder {here} cannot be made ({exc.strerror})") from None
                if created is not None:
                    created.append(here)
                continue  # looked at again: it is a folder now, or whatever replaced it
            if st.S_ISLNK(info.st_mode) and last and keep_link:
                break
            if st.S_ISLNK(info.st_mode):
                try:
                    target = os.readlink(part, dir_fd=stack[-1])
                except OSError:
                    target = "?"
                if not follow:
                    raise Refused(f"{name}: {here} is a symbolic link (to {target[:200]}): the write tools do not "
                                  "go through links; use the path of the file or folder it points to")
                hops += 1
                if hops > MAX_LINKS:
                    raise Refused(f"{name}: more than {MAX_LINKS} links on the way (a loop?)")
                links.append(f"{here} -> {target[:200]}")
                if target.startswith("/"):
                    inside = _link_parts(root, target)
                    if inside is None:
                        raise Refused(f"{name}: {here} is a link to {target[:200]}, outside {root}: links out of "
                                      "the mounted folders are never followed")
                    while len(stack) > 1:
                        os.close(stack.pop())
                    walked = []
                    todo = inside + todo[1:]
                else:
                    todo = target.split("/") + todo[1:]
                continue
            if last:
                break
            if not st.S_ISDIR(info.st_mode):
                raise Refused(f"{name}: {here} is {_kind_text(info.st_mode)}, not a folder")
            try:
                fd = os.open(part, DIR_FLAGS, dir_fd=stack[-1])
            except OSError as exc:
                if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                    raise Refused(f"{name}: {here} changed while it was opened (now a link?): try again") from None
                raise Refused(f"{name}: {here} cannot be opened ({exc.strerror})") from None
            stack.append(fd)
            walked.append(part)
            todo.pop(0)
        dirfd = stack.pop()
        return Place(root, dirfd, walked, todo[0] if todo else None, links)
    finally:
        for fd in stack:
            os.close(fd)


def plain_name(part: str) -> str:
    """PART as a file system that folds case, compatibility forms or ignores invisible characters (HFS+, some
    network shares) may take it: NFKC, without format characters (zero-width, soft hyphen), case-folded."""
    return "".join(c for c in unicodedata.normalize("NFKC", part) if unicodedata.category(c) != "Cf").casefold()


def writable(root: str, names: list[str], name: str, from_trash: bool = False) -> None:
    """Refused unless a write tool may change ROOT/NAMES."""
    if readonly():
        raise Refused("this server is read-only (FILES_READONLY=1): it does not write, move or delete anything")
    if root != WORK:
        raise Refused(f"{name}: {root} is read-only: only {WORK} is written")
    if not names:
        raise Refused(f"{name}: {WORK} itself cannot be written, moved or deleted: name a file or folder in it")
    if plain_name(names[0]) == TRASH and not (from_trash and names[0] == TRASH and len(names) > 2):
        raise Refused(f"{name}: {WORK}/{TRASH} keeps what delete removed: it is the user's to empty or restore "
                      "from (move a file out of it to restore it)")
    for part in names:
        if plain_name(part) in PROTECTED:
            raise Refused(f"{name}: {part} is git's own folder: it changes through git, not through file writes")


def open_dir(place: Place, name: str = "path") -> int:
    """A descriptor of the folder at PLACE (the caller closes it)."""
    if place.name is None:
        return os.dup(place.dirfd)
    try:
        return os.open(place.name, DIR_FLAGS, dir_fd=place.dirfd)
    except FileNotFoundError:
        raise Refused(f"{name}: {place.path} does not exist") from None
    except OSError as exc:
        if exc.errno in (errno.ENOTDIR, errno.ELOOP):
            raise Refused(f"{name}: {place.path} is not a folder") from None
        raise Refused(f"{name}: {place.path} cannot be opened ({exc.strerror})") from None


def open_file(place: Place, name: str = "path") -> tuple[int, os.stat_result]:
    """(descriptor, fstat) of the regular file at PLACE, opened without following a link and without blocking on
    a pipe; the caller closes it."""
    if place.name is None:
        raise Refused(f"{name}: {place.path} is a folder, not a file")
    try:
        fd = os.open(place.name, READ_FLAGS, dir_fd=place.dirfd)
    except FileNotFoundError:
        raise Refused(f"{name}: {place.path} does not exist") from None
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise Refused(f"{name}: {place.path} is a symbolic link (it changed while it was opened)") from None
        if exc.errno == errno.EISDIR:
            raise Refused(f"{name}: {place.path} is a folder, not a file (list_dir shows what is in it)") from None
        info = place.lstat()
        if info is not None and not st.S_ISREG(info.st_mode):  # a socket (ENXIO), a device without a driver
            raise Refused(f"{name}: {place.path} is {_kind_text(info.st_mode)}, not a file: only regular files are "
                          "read or written") from None
        raise Refused(f"{name}: {place.path} cannot be opened ({exc.strerror})") from None
    info = os.fstat(fd)
    if not st.S_ISREG(info.st_mode):
        os.close(fd)
        hint = " (list_dir shows what is in it)" if st.S_ISDIR(info.st_mode) else \
            ": only regular files are read or written"
        raise Refused(f"{name}: {place.path} is {_kind_text(info.st_mode)}, not a file{hint}")
    return fd, info


def read_bytes(place: Place, name: str = "path", limit: int | None = None) -> tuple[bytes, os.stat_result]:
    limit = max_bytes() if limit is None else limit
    fd, info = open_file(place, name)
    try:
        if info.st_size > limit:
            raise Refused(f"{name}: {place.path} has {info.st_size} bytes, more than the {limit} one call takes "
                          "(FILES_MAX_BYTES)")
        chunks, size = [], 0
        while True:
            chunk = os.read(fd, min(1 << 20, limit + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > limit:
                raise Refused(f"{name}: {place.path} grew past the {limit} bytes one call takes (FILES_MAX_BYTES)")
        return b"".join(chunks), info
    finally:
        os.close(fd)


# --- text ------------------------------------------------------------------------------------------------------------

class Text:
    """A file's bytes as the text tools see it: TEXT with LF line breaks; how to write it back (EOL, BOM)."""

    def __init__(self, raw: bytes):
        self.raw = raw
        self.sha256 = hashlib.sha256(raw).hexdigest()
        self.bom = raw.startswith(BOM)
        body = raw[3:] if self.bom else raw
        self.binary = b"\0" in body
        try:
            decoded = body.decode("utf-8")
            self.utf8 = True
        except UnicodeDecodeError:
            decoded = body.decode("utf-8", "replace")
            self.utf8 = False
        crlf = decoded.count("\r\n")
        lf = decoded.count("\n") - crlf
        cr = decoded.count("\r") - crlf
        self.counts = {"crlf": crlf, "lf": lf, "cr": cr}
        if not crlf + lf + cr:
            self.eol = "none"
        elif crlf and not lf and not cr:
            self.eol = "crlf"
        elif cr and not lf and not crlf:
            self.eol = "cr"
        elif lf and not crlf and not cr:
            self.eol = "lf"
        else:
            self.eol = "mixed"
        self.text = decoded.replace("\r\n", "\n").replace("\r", "\n")

    @property
    def write_eol(self) -> str:
        """The line breaks a change is written with: the file's own; a mixed file gets its most common one."""
        if self.eol in ("crlf", "cr"):
            return self.eol
        if self.eol == "mixed":
            return max(("crlf", "lf", "cr"), key=lambda k: (self.counts[k], k == "lf"))
        return "lf"

    def lines(self) -> list[str]:
        return split_lines(self.text)


def split_lines(text: str) -> list[str]:
    """The lines of TEXT (LF), without the empty one after a final line break."""
    if not text:
        return []
    lines = text.split("\n")
    return lines[:-1] if lines[-1] == "" else lines


def line_count(text: str) -> int:
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def encode(text: str, eol: str, bom: bool) -> bytes:
    if eol == "crlf":
        text = text.replace("\n", "\r\n")
    elif eol == "cr":
        text = text.replace("\n", "\r")
    try:
        data = text.encode("utf-8")
    except UnicodeEncodeError:
        raise Refused("content: contains characters that are not valid Unicode (lone surrogates)") from None
    return BOM + data if bom else data


def lf(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def binary_looking(text: str) -> bool:
    if "\0" in text:
        return True
    head = text[:65536]
    odd = sum(1 for c in head if ord(c) < 32 and c not in "\t\n\r\f\v\b\x1b")
    return bool(head) and odd / len(head) > 0.05


def text_of(place: Place, name: str = "path") -> tuple[Text, os.stat_result]:
    """The UTF-8 text of the file at PLACE for a change (refused when binary or not UTF-8)."""
    raw, info = read_bytes(place, name)
    doc = Text(raw)
    if doc.binary or not doc.utf8:
        raise Refused(f"{name}: {place.path} is not UTF-8 text ({'binary' if doc.binary else 'other encoding'}): "
                      "the text tools change UTF-8 text files only")
    return doc, info


def check_expected(doc: Text | None, expected: str | None, place: Place) -> None:
    if expected is None:
        return
    if doc is None:
        raise Refused(f"expected_sha256: {place.path} does not exist (leave expected_sha256 out to create it)")
    if doc.sha256 != expected:
        raise Refused(f"expected_sha256: {place.path} changed since it was read (its sha256 is {doc.sha256} now, "
                      f"not {expected}): read_file it again and redo the change on what it holds now")


# --- comparing ---------------------------------------------------------------------------------------------------

def delta(old: list[str], new: list[str]) -> tuple[int, int, int]:
    """(lines added, lines removed, index of the first changed line)."""
    start = 0
    while start < len(old) and start < len(new) and old[start] == new[start]:
        start += 1
    end_old, end_new = len(old), len(new)
    while end_old > start and end_new > start and old[end_old - 1] == new[end_new - 1]:
        end_old -= 1
        end_new -= 1
    a, b = old[start:end_old], new[start:end_new]
    if not a or not b or len(a) > 2000 or len(b) > 2000:
        return len(b), len(a), start
    added = removed = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag in ("replace", "delete"):
            removed += i2 - i1
        if tag in ("replace", "insert"):
            added += j2 - j1
    return added, removed, start


def numbered(lines: list[str], first: int, limit: int = MAX_PREVIEW, width: int = 200) -> list[str]:
    out = [f"{first + i}\t{line[:width]}{'...' if len(line) > width else ''}" for i, line in enumerate(lines[:limit])]
    if len(lines) > limit:
        out.append(f"... {len(lines) - limit} more lines")
    return out


def unified(a: list[str], b: list[str], name_a: str, name_b: str, context: int = 3) -> tuple[str, bool]:
    out, size, cut = [], 0, False
    for line in difflib.unified_diff(a, b, name_a, name_b, n=context, lineterm=""):
        if len(out) >= MAX_DIFF_LINES or size + len(line) > MAX_DIFF_CHARS:
            cut = True
            break
        out.append(line)
        size += len(line) + 1
    return "\n".join(out), cut


@contextlib.contextmanager
def time_limit(seconds: float = TIME_LIMIT):
    """TimeLimit raised in the block after SECONDS (a timer signal, which also stops a regular expression that
    backtracks without end). Outside the main thread no timer: the walks check the clock themselves."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    outer, _ = signal.getitimer(signal.ITIMER_REAL)
    if outer and outer <= seconds:
        yield  # an enclosing limit ends first: it stays in charge
        return
    started = time.monotonic()

    def fire(signum, frame):
        raise TimeLimit()

    previous = signal.signal(signal.SIGALRM, fire)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
        if outer:  # the enclosing limit goes on with what it has left
            signal.setitimer(signal.ITIMER_REAL, max(outer - (time.monotonic() - started), 0.001))


# --- writing: atomically, never over a file that changed --------------------------------------------------------

def temp_name(name: str) -> str:
    """A new temporary name next to NAME: its first characters (at most 100 bytes, so the whole name stays far
    below the 255 bytes a name may have), a random part."""
    stem = name[:100]
    while len(stem.encode("utf-8", "surrogatepass")) > 100:
        stem = stem[:-1]
    return f".{stem}.{secrets.token_hex(6)}.files-tmp"


def commit(place: Place, data: bytes, before: os.stat_result | None, mode: int | None = None) -> None:
    """Write DATA as PLACE's file: a new temporary file in the same folder (O_EXCL, O_NOFOLLOW), written, its mode
    set, fsynced, then renamed over the name and the folder fsynced. BEFORE: the file as it was read - it must
    still be that very file (same inode, size and change time), or nothing is written; None: the name must not
    exist (link(2) refuses to replace one). MODE: the new file's permissions (default: the old file's)."""
    if len(data) > max_bytes():
        raise Refused(f"content: {len(data)} bytes, more than the {max_bytes()} one call writes (FILES_MAX_BYTES)")
    folder, name = place.dirfd, place.name
    if mode is None:
        mode = st.S_IMODE(before.st_mode) & 0o777 if before is not None else 0o666 & ~UMASK
    temp = temp_name(name)
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=folder)
    try:
        try:
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view):]
            os.fchmod(fd, mode)
            os.fsync(fd)
        finally:
            os.close(fd)
        if before is None:
            try:
                os.link(temp, name, src_dir_fd=folder, dst_dir_fd=folder, follow_symlinks=False)
            except FileExistsError:
                raise Refused(f"{place.path} appeared while it was written: read it and try again") from None
            except OSError as exc:
                if exc.errno not in (errno.EPERM, errno.EOPNOTSUPP, errno.EMLINK, errno.EXDEV):
                    raise
                # a file system without hard links: check, then rename
                if place.lstat() is not None:
                    raise Refused(f"{place.path} appeared while it was written: read it and try again") from None
                os.rename(temp, name, src_dir_fd=folder, dst_dir_fd=folder)
            else:
                os.unlink(temp, dir_fd=folder)
        else:
            now = place.lstat()
            if now is None or not st.S_ISREG(now.st_mode) or (now.st_dev, now.st_ino) != \
                    (before.st_dev, before.st_ino) or now.st_size != before.st_size or \
                    now.st_mtime_ns != before.st_mtime_ns or now.st_ctime_ns != before.st_ctime_ns:
                raise Refused(f"{place.path} changed while it was written (by someone else): nothing was written; "
                              "read it again and redo the change")
            os.rename(temp, name, src_dir_fd=folder, dst_dir_fd=folder)
        os.fsync(folder)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temp, dir_fd=folder)
        raise


def change_answer(place: Place, old: Text | None, new_text: str, data: bytes, action: str,
                  notes: list[str], preview: bool = True) -> dict:
    old_lines = old.lines() if old is not None else []
    new_lines = split_lines(new_text)
    added, removed, first = delta(old_lines, new_lines)
    answer = {"path": place.path, "action": action, "lines_added": added, "lines_removed": removed,
              "lines": len(new_lines), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    if old is not None:
        answer["previous_sha256"] = old.sha256
    if preview and action != "unchanged" and (added or removed):
        start = max(0, first - 2)
        answer["preview"] = numbered(new_lines[start:start + MAX_PREVIEW], start + 1)
    if notes:
        answer["notes"] = notes[:MAX_NOTES]
    return answer


def write_text(place: Place, old: Text | None, before: os.stat_result | None, text: str, notes: list[str],
               *, eol: str | None = None, bom: bool | None = None, preview: bool = True,
               allow_binary: bool = False) -> dict:
    """Write TEXT (LF line breaks) over OLD (None: a new file) with the file's own line breaks and BOM."""
    eol = eol or (old.write_eol if old is not None else "lf")
    bom = bom if bom is not None else (old.bom if old is not None else False)
    if not allow_binary and binary_looking(text):
        raise Refused("content: looks binary (NUL bytes or many control characters): nothing was written "
                      "(write_file with allow_binary=true if that is what the file must hold)")
    if old is not None and old.eol == "mixed":
        notes.append(f"the file had mixed line breaks ({old.counts['crlf']} CRLF, {old.counts['lf']} LF, "
                     f"{old.counts['cr']} CR): written with {eol.upper()} throughout")
    data = encode(text, eol, bom)
    if old is not None and data == old.raw:
        return change_answer(place, old, text, data, "unchanged", notes + ["the file already held exactly this"],
                             preview)
    commit(place, data, before)
    return change_answer(place, old, text, data, "replaced" if old is not None else "created", notes, preview)


def modify(path, change, expected_sha256=None, name: str = "path") -> dict:
    """Read the text file PATH, CHANGE(text, notes) -> new text, write it back (expected_sha256 checked)."""
    expected = _sha(expected_sha256)
    with locate(path, name, write=True) as place:
        info = place.lstat()
        if info is None:
            raise Refused(f"{name}: {place.path} does not exist")
        doc, before = text_of(place, name)
        check_expected(doc, expected, place)
        notes: list[str] = []
        new = change(doc.text, notes)
        return write_text(place, doc, before, new, notes)


def guarded(work):
    """The answer of WORK(), or {"error": ...} saying why it was refused."""
    try:
        with time_limit(CALL_LIMIT):
            return work()
    except Refused as exc:
        return {"error": str(exc)}
    except TimeLimit:
        return {"error": f"this took longer than {CALL_LIMIT:g} seconds and was stopped: narrow it down"}
    except OSError as exc:
        return {"error": f"the file system refused: {exc.strerror or type(exc).__name__}"}
    except Exception as exc:  # noqa: BLE001 - reported by type, not hidden
        log.error("unexpected %s", type(exc).__name__)
        return {"error": f"internal error ({type(exc).__name__})"}


READS = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
ADDS = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
CHANGES = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False)


# --- read tools ------------------------------------------------------------------------------------------------------

@mcp.tool(annotations=READS)
def read_file(path: str, start_line: int = 1, end_line: int | None = None, line_numbers: bool = False) -> dict:
    """Reads a text file. path: relative to /work (docs/a.md) or absolute (/work/docs/a.md). Returns at most 1000
    lines per call: start_line and end_line (1-based, inclusive) pick a part; next_start_line says where to go
    on. line_numbers=true puts "N<TAB>" before each line (never copy these numbers into edits). The answer's
    sha256 is the whole file's: pass it as expected_sha256 to write_file or write_markdown. Line breaks are shown
    as \\n whatever the file uses (line_endings says which; writes keep them)."""
    def work():
        first = _int(start_line, "start_line", 1)
        last = None if end_line is None else _int(end_line, "end_line", 1)
        if last is not None and last < first:
            raise Refused(f"end_line ({last}) is before start_line ({first})")
        numbers = _bool(line_numbers, "line_numbers")
        with locate(path) as place:
            raw, info = read_bytes(place)
            doc = Text(raw)
            answer = {"path": place.path, "bytes": len(raw), "sha256": doc.sha256}
            if place.links:
                answer["followed_links"] = place.links
            if doc.binary:
                answer.update(binary=True, note="a binary file: its content is not shown (checksum and stat work)")
                return answer
            lines = doc.lines()
            total = len(lines)
            answer.update(total_lines=total, line_endings=doc.eol)
            if not doc.utf8:
                answer["encoding"] = "not UTF-8: undecodable bytes are shown as U+FFFD; the edit tools refuse it"
            if doc.bom:
                answer["byte_order_mark"] = True
            if total == 0:
                answer.update(content="", start_line=1, end_line=0)
                return answer
            if first > total:
                raise Refused(f"start_line {first}: the file has {total} lines")
            wanted = min(total, last if last is not None else total)
            stop = min(wanted, first - 1 + MAX_READ_LINES)
            out, size = [], 0
            index = first - 1
            while index < stop:
                line = lines[index]
                piece = f"{index + 1}\t{line}" if numbers else line
                if size + len(piece) > MAX_READ_CHARS and out:
                    break
                if len(piece) > MAX_READ_CHARS:
                    piece = piece[:MAX_READ_CHARS]
                    answer["cut_line"] = f"line {index + 1} is longer than {MAX_READ_CHARS} characters: cut"
                out.append(piece)
                size += len(piece) + 1
                index += 1
            # each line shown with its line break, the last one of the file only if it has one
            ends = index < total or doc.text.endswith("\n")
            answer.update(start_line=first, end_line=index, content="\n".join(out) + ("\n" if ends else ""))
            if index < wanted:
                answer.update(truncated=True, next_start_line=index + 1)
            if index == total and not doc.text.endswith("\n"):
                answer["no_final_newline"] = True
            return answer
    return guarded(work)


def _entry(fd: int, name: str, path: str) -> dict:
    info = os.stat(name, dir_fd=fd, follow_symlinks=False)
    entry = {"path": path, "type": _kind(info.st_mode)}
    if st.S_ISREG(info.st_mode):
        entry["size"] = info.st_size
    elif st.S_ISLNK(info.st_mode):
        with contextlib.suppress(OSError):
            entry["target"] = os.readlink(name, dir_fd=fd)[:300]
    return entry


def _roots_listing() -> dict:
    out = []
    for root, real in ROOTS.items():
        mounted = os.path.isdir(real)
        if not mounted and root != WORK:
            continue
        item = {"path": root, "type": "dir", "mounted": mounted}
        if mounted:
            try:
                fd = os.open(real, DIR_FLAGS)
                try:
                    item["writable"] = (root == WORK and not readonly() and
                                        not os.fstatvfs(fd).f_flag & os.ST_RDONLY)
                finally:
                    os.close(fd)
            except OSError:
                item["mounted"] = False
        out.append(item)
    return {"path": "/", "entries": out, "note": f"relative paths are taken inside {WORK}"}


@mcp.tool(annotations=READS)
def list_dir(path: str = WORK, depth: int = 1) -> dict:
    """Lists a folder: each entry's path, type (file, dir, link, ...) and size. depth 1 (default) to 5 goes into
    sub-folders (never into .git, .trash, node_modules, __pycache__, .venv, and never through links). At most 500
    entries. path "/" lists the folders this server can reach and whether they are writable."""
    def work():
        levels = _int(depth, "depth", 1, 5)
        if isinstance(path, str) and path.strip() == "/":
            return _roots_listing()
        with locate(path) as place:
            fd = open_dir(place)
            entries: list[dict] = []
            truncated = False
            queue = [(fd, place.path, 1)]
            try:
                while queue and not truncated:
                    dirfd, base, level = queue.pop(0)
                    try:
                        with os.scandir(dirfd) as items:
                            names = sorted(item.name for item in items)
                        for item_name in names:
                            if len(entries) >= MAX_ENTRIES:
                                truncated = True
                                break
                            try:
                                entry = _entry(dirfd, item_name, f"{base}/{item_name}")
                            except FileNotFoundError:
                                continue
                            entries.append(entry)
                            if entry["type"] == "dir" and level < levels:
                                if item_name in SKIP_DIRS:
                                    entry["not_listed"] = True
                                    continue
                                with contextlib.suppress(OSError):
                                    queue.append((os.open(item_name, DIR_FLAGS, dir_fd=dirfd), entry["path"],
                                                  level + 1))
                    finally:
                        os.close(dirfd)
            finally:
                for dirfd, _, _ in queue:
                    os.close(dirfd)
            answer = {"path": place.path, "entries": entries, "count": len(entries)}
            if place.links:
                answer["followed_links"] = place.links
            if truncated:
                answer["truncated"] = f"only the first {MAX_ENTRIES} entries: list a sub-folder or use glob"
            return answer
    return guarded(work)


def _pattern_parts(pattern, name: str = "pattern") -> list[str]:
    if not isinstance(pattern, str) or not pattern.strip() or len(pattern) > 1000 or _controls(pattern):
        raise Refused(f"{name}: a glob pattern like **/*.md or src/*.py (at most 1000 characters)")
    parts = [p for p in pattern.strip().split("/") if p not in ("", ".")]
    if ".." in parts:
        raise Refused(f"{name}: '..' is not allowed")
    collapsed: list[str] = []
    for part in parts:
        if part == "**" and collapsed and collapsed[-1] == "**":
            continue
        collapsed.append(part)
    return collapsed


class Budget:
    def __init__(self) -> None:
        self.visited = 0
        self.deadline = time.monotonic() + TIME_LIMIT
        self.stopped: str | None = None

    def tick(self) -> bool:
        self.visited += 1
        if self.visited > MAX_VISIT:
            self.stopped = f"looked at {MAX_VISIT} entries: narrow the path or the pattern"
        elif self.visited % 256 == 0 and time.monotonic() > self.deadline:
            self.stopped = f"took longer than {TIME_LIMIT:g} seconds: narrow the path or the pattern"
        return self.stopped is None


def _glob(fd: int, comps: list[str], base: str, out: dict, budget: Budget, limit: int) -> None:
    """Paths below the folder FD (shown as BASE) matching COMPS into OUT (path -> type); links never entered."""
    if not comps or budget.stopped or len(out) >= limit:
        return
    head, rest = comps[0], comps[1:]
    try:
        with os.scandir(fd) as items:
            entries = sorted(((item.name, item.is_dir(follow_symlinks=False), item.is_symlink()) for item in items))
    except OSError:
        return
    if head == "**":
        if rest:
            _glob(fd, rest, base, out, budget, limit)
        for item_name, is_dir, _ in entries:
            if not budget.tick() or len(out) >= limit:
                return
            if not rest:
                out.setdefault(f"{base}/{item_name}", "dir" if is_dir else "other")
            if is_dir and item_name not in SKIP_DIRS:
                try:
                    sub = os.open(item_name, DIR_FLAGS, dir_fd=fd)
                except OSError:
                    continue
                try:
                    _glob(sub, comps, f"{base}/{item_name}", out, budget, limit)
                finally:
                    os.close(sub)
        return
    for item_name, is_dir, is_link in entries:
        if not budget.tick() or len(out) >= limit:
            return
        if not fnmatch.fnmatchcase(item_name, head):
            continue
        if not rest:
            out.setdefault(f"{base}/{item_name}", "dir" if is_dir else "link" if is_link else "other")
        elif is_dir:
            try:
                sub = os.open(item_name, DIR_FLAGS, dir_fd=fd)
            except OSError:
                continue
            try:
                _glob(sub, rest, f"{base}/{item_name}", out, budget, limit)
            finally:
                os.close(sub)


@mcp.tool(annotations=READS)
def glob(pattern: str, path: str = WORK) -> dict:
    """Finds files by name pattern: * and ? within a name, [abc] a set, ** any number of folders. Examples:
    "**/*.md" (every Markdown file), "src/*.py", "docs/**/README*". The pattern is taken inside path (default
    /work), or is absolute (/work/docs/*.md). Does not go into .git, .trash, node_modules, __pycache__ or .venv
    for **, nor through links. At most 500 paths, sorted."""
    def work():
        given = pattern.strip() if isinstance(pattern, str) else pattern
        if isinstance(given, str) and given.startswith("/"):
            root = next((r for r in ROOTS if given.startswith(r + "/")), None)
            if root is None:
                raise Refused(f"pattern: outside the folders this server can reach ({roots_shown()})")
            comps = _pattern_parts(given[len(root):])
            start = root
        else:
            comps = _pattern_parts(given)
            start = path
        if not comps:
            raise Refused("pattern: names no files (like **/*.md)")
        with locate(start) as place:
            fd = open_dir(place)
            found: dict[str, str] = {}
            budget = Budget()
            try:
                _glob(fd, comps, place.path, found, budget, MAX_ENTRIES + 1)
            finally:
                os.close(fd)
            paths = sorted(found)
            # a folder with a / at its end; files (and links, pipes, devices) as their path
            answer = {"pattern": pattern, "path": place.path,
                      "matches": [p + "/" if found[p] == "dir" else p for p in paths[:MAX_ENTRIES]],
                      "count": min(len(paths), MAX_ENTRIES)}
            if len(paths) > MAX_ENTRIES:
                answer["truncated"] = f"only the first {MAX_ENTRIES}: narrow the pattern"
            if budget.stopped:
                answer["stopped"] = budget.stopped
            return answer
    return guarded(work)


def _search_files(fd: int, base: str, include: str | None, budget: Budget, rel: str = ""):
    """(folder descriptor, name, shown path, relative path) of every regular file below FD; links not entered."""
    try:
        with os.scandir(fd) as items:
            entries = sorted((item.name, item.is_dir(follow_symlinks=False),
                              item.is_file(follow_symlinks=False)) for item in items)
    except OSError:
        return
    for item_name, is_dir, is_file in entries:
        if not budget.tick():
            return
        relative = f"{rel}{item_name}"
        if is_file:
            if include is None or fnmatch.fnmatchcase(item_name if "/" not in include else relative, include):
                yield fd, item_name, f"{base}/{item_name}"
        elif is_dir and item_name not in SKIP_DIRS:
            try:
                sub = os.open(item_name, DIR_FLAGS, dir_fd=fd)
            except OSError:
                continue
            try:
                yield from _search_files(sub, f"{base}/{item_name}", include, budget, relative + "/")
            finally:
                os.close(sub)


def _shown_line(line: str, column: int) -> str:
    if len(line) <= MAX_LINE_SHOWN:
        return line
    start = max(0, column - MAX_LINE_SHOWN // 3)
    return ("..." if start else "") + line[start:start + MAX_LINE_SHOWN] + "..."


@mcp.tool(annotations=READS)
def search(pattern: str, path: str = WORK, regex: bool = False, ignore_case: bool = False,
           include: str | None = None, max_results: int = 50) -> dict:
    """Searches text files for PATTERN, line by line: plain text by default, a Python regular expression with
    regex=true. path: a folder (default /work, searched with its sub-folders, not .git, .trash, node_modules,
    __pycache__, .venv) or one file. include: only files whose name matches this glob ("*.py"; with a / the path
    below the folder, "src/*.py"). Answers path, line number and the line for each match, at most max_results
    (1-200, default 50). Binary files and files over FILES_MAX_BYTES are skipped."""
    def work():
        text = _text(pattern, "pattern", empty=False)
        if len(text) > 1000:
            raise Refused("pattern: at most 1000 characters")
        flags = re.IGNORECASE if _bool(ignore_case, "ignore_case") else 0
        if _bool(regex, "regex"):
            try:
                matcher = re.compile(text, flags)
            except re.error as exc:
                raise Refused(f"pattern: not a valid regular expression ({exc}); regex=false searches plain text") \
                    from None
        else:
            matcher = re.compile(re.escape(text), flags)
        limit = _int(max_results, "max_results", 1, MAX_RESULTS)
        only = None
        if include is not None:
            only = _pattern_parts(include, "include")
            only = "/".join(only) if only else None
        cap = max_bytes()
        matches: list[dict] = []
        budget = Budget()
        files = skipped = 0
        stopped = None
        with locate(path) as place:
            info = place.lstat()
            if info is None:
                raise Refused(f"path: {place.path} does not exist")
            if st.S_ISDIR(info.st_mode):
                fd = open_dir(place)
                walker = _search_files(fd, place.path, only, budget)
            else:
                fd = -1
                walker = iter([(place.dirfd, place.name, place.path)])
            try:
                with time_limit(TIME_LIMIT):
                    for dirfd, item_name, shown_path in walker:
                        try:
                            handle = os.open(item_name, READ_FLAGS, dir_fd=dirfd)
                        except OSError:
                            skipped += 1
                            continue
                        try:
                            meta = os.fstat(handle)
                            if not st.S_ISREG(meta.st_mode) or meta.st_size > cap:
                                skipped += 1
                                continue
                            raw = b""
                            while len(raw) <= meta.st_size:
                                chunk = os.read(handle, 1 << 20)
                                if not chunk:
                                    break
                                raw += chunk
                        finally:
                            os.close(handle)
                        if b"\0" in raw[:8192]:
                            skipped += 1
                            continue
                        files += 1
                        body = raw.decode("utf-8", "replace")
                        for number, line in enumerate(lf(body).split("\n"), start=1):
                            found = matcher.search(line)
                            if found:
                                matches.append({"path": shown_path, "line": number,
                                                "text": _shown_line(line, found.start())})
                                if len(matches) > limit:
                                    break
                        if len(matches) > limit:
                            break
            except TimeLimit:
                stopped = f"stopped after {TIME_LIMIT:g} seconds: narrow the path, include or pattern"
            finally:
                if fd >= 0:
                    os.close(fd)
        answer = {"pattern": text, "path": place.path, "matches": matches[:limit], "count": min(len(matches), limit),
                  "files_searched": files}
        if len(matches) > limit:
            answer["truncated"] = f"more than {limit} matches: narrow the search or raise max_results (up to " \
                                  f"{MAX_RESULTS})"
        if skipped:
            answer["files_skipped"] = skipped
        if stopped or budget.stopped:
            answer["stopped"] = stopped or budget.stopped
        return answer
    return guarded(work)


@mcp.tool(name="stat", annotations=READS)
def stat_tool(path: str) -> dict:
    """Tells whether a path exists and what it is: type (file, dir, link, ...), size in bytes, permissions,
    modification time, a link's target; for a text file of up to FILES_MAX_BYTES also its line count and
    sha256. Never fails for a missing path: exists is false."""
    def work():
        with locate(path, keep_link=True) as place:
            info = place.lstat()
            if info is None:
                return {"path": place.path, "exists": False}
            answer = {"path": place.path, "exists": True, "type": _kind(info.st_mode),
                      "mode": oct(st.S_IMODE(info.st_mode)),
                      "modified": datetime.fromtimestamp(info.st_mtime, timezone.utc).isoformat(timespec="seconds")}
            if st.S_ISREG(info.st_mode):
                answer["size"] = info.st_size
                if info.st_nlink > 1:
                    answer["hard_links"] = info.st_nlink
                if info.st_size <= max_bytes():
                    raw, _ = read_bytes(place)
                    doc = Text(raw)
                    answer["sha256"] = doc.sha256
                    if doc.binary:
                        answer["binary"] = True
                    else:
                        answer.update(lines=line_count(doc.text), line_endings=doc.eol)
            elif st.S_ISLNK(info.st_mode):
                target = os.readlink(place.name, dir_fd=place.dirfd)
                answer["target"] = target[:300]
                try:
                    with locate(path) as followed:
                        answer["points_to"] = followed.path
                        answer["target_exists"] = followed.lstat() is not None
                except Refused as exc:
                    answer["not_followed"] = str(exc)
            elif st.S_ISDIR(info.st_mode):
                fd = open_dir(place)
                try:
                    with os.scandir(fd) as items:
                        answer["entries"] = sum(1 for _ in items)
                finally:
                    os.close(fd)
            answer["writable"] = place.root == WORK and not readonly()
            return answer
    return guarded(work)


@mcp.tool(annotations=READS)
def checksum(path: str, algorithm: str = "sha256") -> dict:
    """The checksum of a file (any size, binary too): algorithm sha256 (default), sha512, sha1 or md5."""
    def work():
        if algorithm not in ("sha256", "sha512", "sha1", "md5"):
            raise Refused("algorithm: sha256, sha512, sha1 or md5")
        digest = hashlib.new(algorithm)
        with locate(path) as place:
            fd, info = open_file(place)
            try:
                size = 0
                while True:
                    chunk = os.read(fd, 1 << 20)
                    if not chunk:
                        break
                    digest.update(chunk)
                    size += len(chunk)
            finally:
                os.close(fd)
            return {"path": place.path, "algorithm": algorithm, "checksum": digest.hexdigest(), "bytes": size}
    return guarded(work)


@mcp.tool(annotations=READS)
def diff(path_a: str, path_b: str | None = None, content: str | None = None, context_lines: int = 3) -> dict:
    """Shows the differences as a unified diff: between two text files (path_a, path_b), or between the file
    path_a and a proposed content (to see what a write would change before making it). context_lines 0-10.
    At most 400 lines of diff."""
    def work():
        context = _int(context_lines, "context_lines", 0, 10)
        if (path_b is None) == (content is None):
            raise Refused("give path_b (another file) or content (a proposed text), one of the two")
        with locate(path_a, "path_a") as place:
            if place.lstat() is None:
                a_text, a_name = "", "/dev/null"
                sha_a = None
            else:
                raw, _ = read_bytes(place, "path_a")
                doc = Text(raw)
                if doc.binary:
                    raise Refused(f"path_a: {place.path} is binary: compare checksums instead")
                a_text, a_name, sha_a = doc.text, place.path, doc.sha256
        if path_b is not None:
            with locate(path_b, "path_b") as other:
                raw, _ = read_bytes(other, "path_b")
                doc_b = Text(raw)
                if doc_b.binary:
                    raise Refused(f"path_b: {other.path} is binary: compare checksums instead")
                b_text, b_name = doc_b.text, other.path
        else:
            b_text, b_name = lf(_text(content, "content")), "proposed content"
        a_lines, b_lines = split_lines(a_text), split_lines(b_text)
        with time_limit(TIME_LIMIT):
            text, cut = unified(a_lines, b_lines, a_name, b_name, context)
        added, removed, _ = delta(a_lines, b_lines)
        answer = {"a": a_name, "b": b_name, "identical": a_text == b_text, "lines_added": added,
                  "lines_removed": removed, "diff": text}
        if sha_a:
            answer["sha256_a"] = sha_a
        if cut:
            answer["truncated"] = f"the diff is longer than {MAX_DIFF_LINES} lines: only its start is shown"
        return answer
    return guarded(work)


# --- write tools -------------------------------------------------------------------------------------------------

def _prepare_write(place: Place, expected: str | None, overwrite: bool, name: str = "path"):
    """(old text or None, its stat) of the file a whole-file write replaces, after the no-clobber checks."""
    info = place.lstat()
    if info is None:
        if expected is not None:
            check_expected(None, expected, place)
        return None, None
    if not st.S_ISREG(info.st_mode):
        raise Refused(f"{name}: {place.path} is {_kind_text(info.st_mode)}: only files are written")
    raw, before = read_bytes(place, name)
    old = Text(raw)
    if expected is None and not overwrite:
        raise Refused(f"{name}: {place.path} exists already ({line_count(old.text)} lines, sha256 {old.sha256}). "
                      "To replace it: read_file it and pass its sha256 as expected_sha256 (or overwrite=true to "
                      "replace it without looking); for a small change use edit_file")
    check_expected(old, expected, place)
    return old, before


@mcp.tool(annotations=CHANGES)
def write_file(path: str, content: str, expected_sha256: str | None = None, overwrite: bool = False,
               create_dirs: bool = False, line_endings: str = "keep", allow_binary: bool = False) -> dict:
    """WRITES the whole file PATH with CONTENT (UTF-8), atomically. A new file is created; an existing file is
    replaced only when expected_sha256 is the sha256 read_file gave for it (so nothing that changed since is
    lost) or overwrite=true. create_dirs=true makes missing folders. line_endings: keep (default: an existing
    file's CRLF and byte order mark stay), lf or crlf. Content that looks binary is refused unless
    allow_binary=true. For Markdown use write_markdown; for small changes edit_file. Answers lines added and
    removed and the new sha256."""
    def work():
        text = _text(content, "content")
        expected = _sha(expected_sha256)
        if line_endings not in ("keep", "lf", "crlf"):
            raise Refused("line_endings: keep, lf or crlf")
        made: list[str] = []
        with locate(path, write=True, create_dirs=_bool(create_dirs, "create_dirs"), created=made) as place:
            old, before = _prepare_write(place, expected, _bool(overwrite, "overwrite"))
            notes = [f"made the folder {folder}" for folder in made]
            body = lf(text)
            given = Text(text.encode("utf-8")).eol  # the line breaks the content came with
            if line_endings != "keep":
                eol = line_endings
            elif old is not None:
                eol = old.write_eol  # the file's own
                if given not in ("none", eol) and line_count(old.text) > 1:
                    notes.append(f"written with {eol.upper()} line breaks, as the file had them (the content came "
                                 f"with {given.upper()})")
            else:
                eol = "crlf" if text.count("\r\n") * 2 > body.count("\n") else "lf"
            bom = old.bom if old is not None and line_endings == "keep" else False
            if body.startswith("\ufeff"):
                body, bom = body[1:], True
            return write_text(place, old, before, body, notes, eol=eol, bom=bom, preview=False,
                              allow_binary=_bool(allow_binary, "allow_binary"))
    return guarded(work)


# --- Markdown repairs ----------------------------------------------------------------------------------------------

FENCE = re.compile(r"^(\s*)(`{3,}|~{3,})(.*)$")
ATX = re.compile(r"^( {0,3})(#{1,6})(?:[ \t]+(.*?))?[ \t]*$")
NO_SPACE_HEADING = re.compile(r"^( {0,3})(#{1,6})([^#\s].*)$")
NOT_A_HEADING = re.compile(r"^(?:!|[0-9]|(?:include|define|undef|ifn?def|if|elif|else|endif|pragma|import|error|"
                           r"warning|region|endregion|line)\b|[0-9a-fA-F]{3,8}\s*$)")
DELIMITER_ROW = re.compile(r"^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?\s*$")
#: An HTML block whose lines are raw text up to its end tag (CommonMark's HTML block type 1): never repaired.
RAW_HTML = re.compile(r"^ {0,3}<(pre|script|style|textarea)(?=[\s>]|$)", re.I)
RISKY_HTML = re.compile(r"<\s*(script|iframe|object|embed|style|form|meta|base|link)\b|\bon[a-z]{3,}\s*=\s*[\"']"
                        r"|javascript\s*:", re.I)
HTML_TAG = re.compile(r"</?[A-Za-z][A-Za-z0-9-]*(?:\s[^<>]*)?/?>")
CODE_SPAN = re.compile(r"(`+)(?:(?!\1).)+?\1")
REF_USE = re.compile(r"(?<!!)\[([^\[\]]+)\]\[([^\[\]]*)\]")
REF_DEF = re.compile(r"^ {0,3}\[([^\[\]]+)\]:\s*\S")
MARKDOWN_INFO = ("markdown", "md", "mdx", "gfm", "commonmark")


def _lines_text(numbers: list[int]) -> str:
    shown_numbers = ", ".join(str(n) for n in numbers[:15])
    return f"line {shown_numbers}" if len(numbers) == 1 else \
        f"lines {shown_numbers}" + (f" and {len(numbers) - 15} more" if len(numbers) > 15 else "")


def _columns(prefix: str) -> int:
    return len(prefix.expandtabs(4))


def _opens(match) -> tuple[str, int] | None:
    """(marker, indentation) of the code fence a FENCE match opens (None: a backtick fence with a backtick in its
    info string is no fence)."""
    if not match or (match.group(2)[0] == "`" and "`" in match.group(3)):
        return None
    return match.group(2), _columns(match.group(1))


def _closes(match, fence: tuple[str, int]) -> bool:
    """Whether the FENCE match closes the open FENCE (marker, indentation): the same character, at least as long,
    no info string, and indented at most 3 columns more than the opening (CommonMark; more is code inside it)."""
    return bool(match) and match.group(2)[0] == fence[0][0] and len(match.group(2)) >= len(fence[0]) \
        and not match.group(3).strip() and _columns(match.group(1)) <= fence[1] + 3


def _fences_balanced(lines: list[str]) -> bool:
    open_fence = None
    for line in lines:
        match = FENCE.match(line)
        if not match:
            continue
        if open_fence is None:
            open_fence = _opens(match)
        elif _closes(match, open_fence):
            open_fence = None
    return open_fence is None


def _unwrap_fence(text: str) -> tuple[str, str] | None:
    """TEXT without a code fence wrapped around all of it (```markdown ... ```), and the fence's info string."""
    lines = text.split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if len(lines) < 2:
        return None
    opening = FENCE.match(lines[0])
    closing = lines[-1].strip()
    if not opening or len(opening.group(1)) > 3:
        return None
    marker, info = opening.group(2), opening.group(3).strip().lower()
    if not closing or set(closing) != {marker[0]} or len(closing) < 3:
        # an opening ```markdown that is never closed (the end of the answer cut off): the opening line goes
        if info in MARKDOWN_INFO and _fences_balanced(lines[1:]):
            return "\n".join(lines[1:]) + "\n", f"{info}, never closed"
        return None
    inner = lines[1:-1]
    if info in MARKDOWN_INFO:
        pass
    elif info:
        return None
    elif not any(ATX.match(line) for line in inner):
        return None  # a bare fence around something that is not Markdown: a code block, kept
    if not _fences_balanced(inner):
        return None
    return "\n".join(inner) + "\n", info or "(no language)"


def _decode_escapes(text: str) -> tuple[str, dict] | None:
    """TEXT with its JSON-style escapes decoded (\\n, \\t, \\r, \\", \\\\) when it has no real line break but
    literal \\n; inline code spans (`...`) keep theirs."""
    body = text.rstrip("\n")
    if "\n" in body or "\\n" not in body:
        return None
    counts = {"\\n": 0, "\\t": 0, '\\"': 0, "\\\\": 0, "\\r": 0}

    def one(match):
        token = match.group(0)
        counts[token] += 1
        return {"\\n": "\n", "\\t": "\t", '\\"': '"', "\\\\": "\\", "\\r": ""}[token]

    out, pos = [], 0
    for span in re.finditer(r"(?<!`)`[^`\n]+`(?!`)", body):
        out.append(re.sub(r'\\[nt"\\r]', one, body[pos:span.start()]))
        out.append(span.group(0))
        pos = span.end()
    out.append(re.sub(r'\\[nt"\\r]', one, body[pos:]))
    if not counts["\\n"]:
        return None
    return "".join(out) + "\n", counts


def _without_comments(text: str, number: int) -> tuple[str, int | None]:
    """TEXT without its HTML comments, and NUMBER when a comment in it is not closed on this line (else None)."""
    kept = ""
    while True:
        start = text.find("<!--")
        if start < 0:
            return kept + text, None
        kept += text[:start]
        end = text.find("-->", start + 4)
        if end < 0:
            return kept, number
        text = text[end + 3:]


def _cells(row: str) -> int:
    row = CODE_SPAN.sub(lambda m: "x" * len(m.group(0)), row.strip()).replace("\\|", "xx")
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|"):
        row = row[:-1]
    return len(row.split("|"))


def _heading_key(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[ \t]+#+[ \t]*$", "", text or "")).strip().casefold()


def repair_markdown(content: str, title: str | None = None) -> tuple[str, list[str], list[str], dict]:
    """(repaired text with LF line breaks, the repairs made, warnings about what was left as is, structure).

    Repairs: a byte order mark; the whole text as a JSON string; CRLF and CR line breaks; literal \\n escapes in
    a text without line breaks; a code fence around all of it; trailing whitespace outside code (a hard line
    break of two spaces kept); a missing space after # in a heading; a code fence left open (closed at the end);
    the first heading repeated; blank lines at the start and end; a missing final line break; TITLE as the first
    heading. Reported, left as is: tables with differing column counts or without a delimiter row, raw HTML and
    scripts, an open HTML comment or front matter, literal \\n in a text with line breaks, heading levels skipped,
    links not closed or empty, reference links without a definition."""
    repairs: list[str] = []
    warnings: list[str] = []
    text = content
    if text.startswith("\ufeff"):
        text = text[1:]
        repairs.append("removed the byte order mark (U+FEFF) at the start")
    stripped = text.strip()
    if len(stripped) >= 2 and stripped[0] == '"' and stripped[-1] == '"':
        try:
            decoded = json.loads(stripped)
        except ValueError:
            decoded = None
        if isinstance(decoded, str) and "\n" in decoded:  # a whole document as one JSON string, not a quoted line
            text = decoded
            repairs.append("the content was a JSON string (in quotes, with escapes): decoded it")
    crlf, cr = text.count("\r\n"), text.count("\r") - text.count("\r\n")
    if crlf or cr:
        text = lf(text)
        repairs.append("line breaks normalised to LF (" + ", ".join(
            part for part in (f"{crlf} CRLF" if crlf else "", f"{cr} CR" if cr else "") if part) + ")")
    escapes = _decode_escapes(text)
    if escapes:
        text, counts = escapes
        repairs.append("the content had no line breaks but literal escape sequences: decoded " + ", ".join(
            f"{n} {token}" for token, n in counts.items() if n) + " (inline `code` kept as written)")
    unwrapped = _unwrap_fence(text)
    if unwrapped:
        text, info = unwrapped
        repairs.append(f"the whole content was wrapped in a code fence ({info}): unwrapped it")
        if not escapes:
            escapes = _decode_escapes(text)
            if escapes:
                text, counts = escapes
                repairs.append("decoded the literal escape sequences inside the fence: " + ", ".join(
                    f"{n} {token}" for token, n in counts.items() if n))

    missing_final = not text.endswith("\n")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    # front matter (--- ... --- at the very start) is left alone
    body_start = 0
    if lines and lines[0].strip() == "---":
        end = next((i for i in range(1, min(len(lines), 200)) if lines[i].strip() in ("---", "...")), None)
        if end is None:
            warnings.append("line 1 starts front matter (---) that is not closed by another --- line")
        else:
            body_start = end + 1

    out: list[str] = lines[:body_start]
    fence = None          # (marker, indentation, line number, info, indentation as written) of the open code fence
    raw_html = None       # the tag of an open <pre>, <script>, <style> or <textarea> block
    indented_code = False  # the line before is a line of an indented code block (or blank, or the start)
    comment_open = None   # line of an HTML comment not closed yet
    trailing: list[int] = []
    headings_fixed: list[int] = []
    literal_escapes: list[int] = []
    html_lines: list[int] = []
    risky: list[tuple[int, str]] = []
    headings: list[tuple[int, int, str, int]] = []   # (index in out, level, text, line number)
    code_blocks = 0
    links = 0
    ref_uses: list[tuple[int, str]] = []
    ref_defs: set[str] = set()
    unclosed_links: list[int] = []
    empty_links: list[int] = []
    for index in range(body_start, len(lines)):
        number = index + 1
        line = lines[index]
        match = FENCE.match(line)
        if fence is not None:
            if _closes(match, fence[:2]):
                fence = None
            out.append(line)
            continue
        after_blank = indented_code or index == body_start or not lines[index - 1].strip()
        indented_code = not line.strip()
        if raw_html is not None:  # raw HTML up to its end tag: nothing in it is Markdown
            if f"</{raw_html}" in line.lower():
                raw_html = None
            out.append(line)
            continue
        opening = _opens(match) if comment_open is None else None
        if opening:
            fence = (*opening, number, match.group(3).strip(), match.group(1))
            code_blocks += 1
            out.append(line.rstrip())
            continue
        if comment_open is None and line.strip() and line.startswith(("    ", "\t")) and after_blank:
            indented_code = True  # an indented code block: kept exactly as written
            out.append(line)
            continue
        raw = RAW_HTML.match(line) if comment_open is None else None
        if raw:
            risk = RISKY_HTML.search(line)
            if risk:
                risky.append((number, risk.group(0)[:30]))
            else:
                html_lines.append(number)
            if f"</{raw.group(1).lower()}" not in line.lower()[raw.end():]:
                raw_html = raw.group(1).lower()
            out.append(line)
            continue
        # outside code
        stripped_line = line.rstrip(" \t")
        if stripped_line != line:
            following = lines[index + 1] if index + 1 < len(lines) else ""
            hard_break = line.endswith("  ") and stripped_line.strip() and following.strip() and \
                not FENCE.match(following)
            if not hard_break:
                line = stripped_line
                trailing.append(number)
        if comment_open is not None:  # inside an HTML comment: nothing in it is Markdown
            if "-->" not in line:
                out.append(line)
                continue
            visible, comment_open = _without_comments(line.split("-->", 1)[1], number)
        else:
            fix = NO_SPACE_HEADING.match(line)
            if fix and not NOT_A_HEADING.match(fix.group(3)) and not re.search(r"\s#[^\s#]", fix.group(3)):
                line = f"{fix.group(1)}{fix.group(2)} {fix.group(3)}"
                headings_fixed.append(number)
            visible, comment_open = _without_comments(CODE_SPAN.sub("", line), number)
        heading = ATX.match(line) if not line.lstrip().startswith("<!--") else None
        if heading:
            headings.append((len(out), len(heading.group(2)), heading.group(3) or "", number))
        if "\\n" in visible:
            literal_escapes.append(number)
        risk = RISKY_HTML.search(visible)
        if risk:
            risky.append((number, risk.group(0)[:30]))
        elif HTML_TAG.search(visible):
            html_lines.append(number)
        links += len(re.findall(r"\]\(", visible))
        for found in re.finditer(r"\]\(", visible):
            depth, pos = 1, found.end()
            while pos < len(visible) and depth:
                depth += {"(": 1, ")": -1}.get(visible[pos], 0)
                pos += 1
            if depth:
                unclosed_links.append(number)
                break
        if re.search(r"\[[^\]]*\]\(\s*\)", visible):
            empty_links.append(number)
        definition = REF_DEF.match(line)
        if definition:
            ref_defs.add(re.sub(r"\s+", " ", definition.group(1)).strip().casefold())
        for use in REF_USE.finditer(visible):
            ref_uses.append((number, use.group(2) or use.group(1)))
        out.append(line)
    if fence is not None:
        out.append(fence[4] + fence[0])
        repairs.append(f"the code fence opened at line {fence[2]} ({fence[0]}{fence[3]}) was not closed: closed it "
                       "at the end (move the closing fence if the code ends earlier)")
    if trailing:
        repairs.append(f"removed trailing whitespace outside code on {_lines_text(trailing)}")
    if headings_fixed:
        repairs.append(f"added the missing space after # in {len(headings_fixed)} heading"
                       f"{'s' if len(headings_fixed) > 1 else ''} ({_lines_text(headings_fixed)})")

    # the first heading repeated right after itself
    if len(headings) >= 2:
        (i1, level1, text1, line1), (i2, level2, text2, line2) = headings[0], headings[1]
        between = out[i1 + 1:i2]
        if level1 == level2 and _heading_key(text1) == _heading_key(text2) and not any(x.strip() for x in between):
            gone = 1
            del out[i2]
            if between and i2 < len(out) and not out[i2].strip():
                del out[i2]  # one blank line stays between the heading and what follows
                gone = 2
            repairs.append(f"the first heading \"{text1[:80]}\" was repeated right after itself (line {line2}): "
                           "removed the repeat")
            headings.pop(1)
            headings = [(i - gone if i > i2 else i, lv, tx, ln) for i, lv, tx, ln in headings]

    # blank lines at the start (after front matter) and the end
    lead = 0
    while body_start + lead < len(out) and not out[body_start + lead].strip():
        lead += 1
    if lead:
        del out[body_start:body_start + lead]
        repairs.append(f"removed {lead} blank line{'s' if lead > 1 else ''} at the start")
        headings = [(i - lead, lv, tx, ln) for i, lv, tx, ln in headings]
    tail = 0
    while out and not out[-1].strip() and len(out) > body_start:
        out.pop()
        tail += 1
    if tail:
        repairs.append(f"removed {tail} blank line{'s' if tail > 1 else ''} at the end")

    if title is not None:
        first = out[body_start] if body_start < len(out) else ""
        first_heading = ATX.match(first)
        if first_heading and len(first_heading.group(2)) == 1:
            if _heading_key(first_heading.group(3) or "") != _heading_key(title):
                warnings.append(f"title \"{title[:80]}\" not added: the content starts with its own first heading "
                                f"\"{(first_heading.group(3) or '')[:80]}\"")
        else:
            out[body_start:body_start] = [f"# {title}", ""]
            repairs.append(f"added the title as the first heading: # {title[:80]}")
            headings = [(i + 2, lv, tx, ln) for i, lv, tx, ln in headings]
            headings.insert(0, (body_start, 1, title, 0))

    if not out[body_start:]:
        raise Refused("content: nothing left to write (empty, or only blank lines)")

    # tables (reported, never rewritten)
    tables = 0
    in_code = None
    index = 0
    table_lines: set[int] = set()
    while index < len(out):
        line = out[index]
        match = FENCE.match(line)
        if in_code is not None:
            if _closes(match, in_code):
                in_code = None
            index += 1
            continue
        if _opens(match):
            in_code = _opens(match)
            index += 1
            continue
        if "|" in line and index + 1 < len(out) and DELIMITER_ROW.match(out[index + 1]) and "|" in out[index + 1]:
            tables += 1
            columns = _cells(line)
            delimiter = _cells(out[index + 1])
            if delimiter != columns:
                warnings.append(f"table at line {index + 1}: the header has {columns} columns but the delimiter row "
                                f"under it {delimiter}: it is not rendered as a table (left as is)")
            row = index + 2
            odd = []
            while row < len(out) and out[row].strip() and "|" in out[row] and not FENCE.match(out[row]):
                count = _cells(out[row])
                if count != columns:
                    odd.append(f"{row + 1} ({count})")
                row += 1
            if odd:
                warnings.append(f"table at line {index + 1} has {columns} columns, but rows at line "
                                f"{', '.join(odd[:10])}{' ...' if len(odd) > 10 else ''} differ (left as is: "
                                "renderers pad missing cells and drop extra ones)")
            table_lines.update(range(index, row))
            index = row
            continue
        index += 1
    run: list[int] = []
    for index, line in enumerate(out + [""]):
        piped = line.strip().startswith("|") and line.strip().endswith("|") and len(line.strip()) > 1
        if piped and index not in table_lines:
            run.append(index)
            continue
        if len(run) >= 2:
            warnings.append(f"lines {run[0] + 1}-{run[-1] + 1} look like a table but have no delimiter row "
                            "(|---|---|) under the first: rendered as plain text (left as is)")
        run = []

    if comment_open is not None:
        warnings.append(f"the HTML comment (<!--) opened at line {comment_open} is not closed: it hides everything "
                        "after it (left as is)")
    for number, what in risky[:10]:
        warnings.append(f"line {number}: active HTML ({what}) - left as is; many renderers strip it, others run it")
    if html_lines:
        warnings.append(f"raw HTML on {_lines_text(html_lines)} (left as is)")
    if literal_escapes:
        warnings.append(f"a literal \\n outside code on {_lines_text(literal_escapes)} (left as is: the text has "
                        "real line breaks too)")
    previous = None
    for _, level, heading_text, number in headings:
        if previous is not None and level > previous + 1 and number:
            warnings.append(f"heading at line {number} (\"{heading_text[:60]}\") jumps from level {previous} to "
                            f"{level}")
        previous = level
    for number in unclosed_links[:10]:
        warnings.append(f"line {number}: a link's ( is not closed")
    for number in empty_links[:10]:
        warnings.append(f"line {number}: a link with an empty target []()")
    for number, label in ref_uses:
        if re.sub(r"\s+", " ", label).strip().casefold() not in ref_defs:
            warnings.append(f"line {number}: the reference link [{label[:60]}] has no definition ([{label[:60]}]: URL)")
    if not _fences_balanced(out):  # cannot happen after the repair above; kept as the final structural check
        warnings.append("the code fences are still not balanced")
    structure = {"headings": len(headings), "code_blocks": code_blocks, "tables": tables, "links": links,
                 "code_fences_balanced": _fences_balanced(out)}
    result = "\n".join(out) + "\n"
    if missing_final:
        repairs.append("added the missing line break at the end")
    return result, repairs, warnings[:MAX_NOTES], structure


@mcp.tool(annotations=CHANGES)
def write_markdown(path: str, content: str, title: str | None = None, dry_run: bool = False,
                   expected_sha256: str | None = None, overwrite: bool = False, create_dirs: bool = False) -> dict:
    """WRITES a Markdown file (.md, .markdown, .mdx), after repairing what often goes wrong and listing each repair
    in "repairs": content wrapped in a ```markdown fence, literal \\n instead of line breaks, the text as a JSON
    string, CRLF line breaks, trailing spaces, '#Heading' without a space, a code fence left open, the first
    heading repeated, a missing final line break. Problems it does not change (table columns, HTML, links) are in
    "warnings". Write the Markdown itself as content - no fence around it, real line breaks. title: the document's
    first heading (# title), added if the content does not start with it. dry_run=true writes nothing and shows
    the repairs and a diff. An existing file is replaced only with expected_sha256 (from read_file) or
    overwrite=true; its CRLF line breaks are kept."""
    def work():
        text = _text(content, "content", empty=False)
        heading = None
        if title is not None:
            heading = _text(title, "title").strip()
            if not heading or len(heading) > 200 or _controls(heading):
                raise Refused("title: one line of text, at most 200 characters (or leave it out)")
            heading = heading.lstrip("#").strip() or None
        expected = _sha(expected_sha256)
        dry = _bool(dry_run, "dry_run")
        root, names = split_path(path)
        if not names or not names[-1].lower().endswith(MARKDOWN_SUFFIXES):
            raise Refused("path: write_markdown writes Markdown files (.md, .markdown, .mdx): use write_file for "
                          "other files")
        repaired, repairs, warnings, structure = repair_markdown(text, heading)
        if dry:
            answer = {"path": shown(root, names), "dry_run": True, "repairs": repairs, "warnings": warnings,
                      "structure": structure, "lines": line_count(repaired)}
            old = None
            try:
                writable(root, names, "path")
                # as the write would go: no link on the way
                with locate(path, follow=False) as place:
                    info = place.lstat()
                    if info is not None:
                        if not st.S_ISREG(info.st_mode):
                            raise Refused(f"path: {place.path} is {_kind_text(info.st_mode)}: only files are written")
                        old = Text(read_bytes(place)[0])
            except Refused as exc:
                if "folder" in str(exc) and "does not exist" in str(exc):
                    if not _bool(create_dirs, "create_dirs"):
                        answer["needs"] = "create_dirs=true: " + str(exc)
                else:
                    answer["would_be_refused"] = str(exc)
            if old is None:
                answer["would"] = "create the file"
                change, cut = unified(split_lines(lf(text)), split_lines(repaired), "content as given", "as written")
                answer["changes_to_content"] = change or "(none: written as given)"
            else:
                answer["would"] = "replace the file" if old.text != repaired else "leave the file unchanged"
                answer["sha256_now"] = old.sha256
                if expected is None and not _bool(overwrite, "overwrite"):
                    answer["needs"] = "expected_sha256 (this sha256_now) or overwrite=true to replace it"
                elif expected is not None and expected != old.sha256:
                    answer["needs"] = "the file changed: expected_sha256 is not its sha256 now"
                change, cut = unified(old.lines(), split_lines(repaired), shown(root, names), "as written")
                answer["diff"] = change or "(none)"
            if cut:
                answer["truncated"] = "the diff is long: only its start is shown"
            return answer
        made: list[str] = []
        with locate(path, write=True, create_dirs=_bool(create_dirs, "create_dirs"), created=made) as place:
            old, before = _prepare_write(place, expected, _bool(overwrite, "overwrite"))
            notes = [f"made the folder {folder}" for folder in made]
            if old is not None and old.write_eol == "crlf":
                notes.append("written with CRLF line breaks, as the file had them")
            answer = write_text(place, old, before, repaired, notes, preview=False)
        if "error" not in answer:
            answer.update(repairs=repairs, warnings=warnings, structure=structure)
        return answer
    return guarded(work)


# --- editing -----------------------------------------------------------------------------------------------------

LINE_PREFIX = re.compile(r"^\s*(\d+)(?:\t| {1,4}|: |\| |\u2192 ?)")


def _strip_numbers(text: str) -> str | None:
    """TEXT without line-number prefixes copied from read_file (N<TAB>, "N: ", "N| "), when every line has one and
    the numbers run on; None otherwise."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
        end = "\n"
    else:
        end = ""
    matches = [LINE_PREFIX.match(line) for line in lines]
    if not lines or not all(matches):
        return None
    numbers = [int(m.group(1)) for m in matches]
    if numbers != list(range(numbers[0], numbers[0] + len(numbers))):
        return None
    return "\n".join(line[m.end():] for line, m in zip(lines, matches)) + end


def _tolerant(old: str) -> re.Pattern | None:
    """OLD's words with any whitespace between them (spaces, tabs, line breaks): what matches ignoring whitespace."""
    words = old.split()
    if not words:
        return None
    return re.compile(r"\s+".join(re.escape(w) for w in words))


def _nearest(text: str, wanted: str) -> str:
    """The place of TEXT most like WANTED's first line, numbered, for an error message."""
    lines = text.split("\n")
    first = next((line.strip() for line in wanted.split("\n") if line.strip()), "")
    if not first or len(lines) > 50_000:
        return ""
    best, score = None, 0.0
    matcher = difflib.SequenceMatcher(autojunk=False)
    matcher.set_seq2(first)
    with contextlib.suppress(TimeLimit):
        with time_limit(5):
            for index, line in enumerate(lines):
                candidate = line.strip()
                if not candidate:
                    continue
                matcher.set_seq1(candidate)
                if matcher.real_quick_ratio() <= score or matcher.quick_ratio() <= score:
                    continue
                ratio = matcher.ratio()
                if ratio > score:
                    best, score = index, ratio
    if best is None or score < 0.5:
        return ""
    start = max(0, best - 2)
    return " The most similar place is at line {} ({:.0%} alike):\n{}".format(
        best + 1, score, "\n".join(numbered(lines[start:start + 8], start + 1, 8)))


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


@mcp.tool(annotations=CHANGES)
def edit_file(path: str, old_text: str, new_text: str, replace_all: bool = False,
              expected_sha256: str | None = None) -> dict:
    """WRITES: replaces OLD_TEXT with NEW_TEXT in the file PATH. old_text must be copied exactly from the file
    (with its indentation, several lines are fine) and must occur exactly once - include more surrounding lines
    to make it unique - or set replace_all=true to replace every occurrence. If it is not found exactly, a match
    that differs only in whitespace is used when there is exactly one (the answer says so). An empty new_text
    deletes old_text. Answers the line of the change, lines added/removed, a preview and the new sha256."""
    def work():
        old = lf(_text(old_text, "old_text", empty=False))
        new = lf(_text(new_text, "new_text"))
        every = _bool(replace_all, "replace_all")
        if old == new:
            raise Refused("old_text and new_text are the same: nothing to change")
        report: dict = {}

        def change(text: str, notes: list[str]) -> str:
            nonlocal old, new
            count = text.count(old)
            if count == 0:
                plain = _strip_numbers(old)
                if plain and plain.strip() and text.count(plain):
                    old = plain
                    new = _strip_numbers(new) or new
                    notes.append("old_text had line numbers from read_file in front of its lines: matched without "
                                 "them (leave them out)")
                    count = text.count(old)
            if count == 0:
                pattern = _tolerant(old)
                found = list(pattern.finditer(text)) if pattern else []
                if len(found) == 1:
                    match = found[0]
                    indent = old[:len(old) - len(old.lstrip())]
                    if indent and new.startswith(indent):
                        new = new[len(indent):]  # the match starts at the first word: the file's indentation stays
                    report.update(match="whitespace-tolerant", line=_line_of(text, match.start()), replaced=1)
                    notes.append(f"old_text was not found exactly; one place differs only in spaces, tabs or line "
                                 f"breaks (line {report['line']}): replaced that - check the preview")
                    return text[:match.start()] + new + text[match.end():]
                if len(found) > 1:
                    raise Refused(f"old_text was not found exactly, and ignoring whitespace it matches "
                                  f"{len(found)} places ({_lines_text([_line_of(text, m.start()) for m in found])}): "
                                  "copy it exactly from read_file, with more lines around it")
                raise Refused("old_text was not found in the file (it must match exactly, including indentation; "
                              "read_file shows the current text)." + _nearest(text, old))
            positions, start = [], 0
            while True:
                index = text.find(old, start)
                if index < 0:
                    break
                positions.append(_line_of(text, index))
                start = index + len(old)
            if count > 1 and not every:
                raise Refused(f"old_text occurs {count} times ({_lines_text(positions)}): include more lines around "
                              "it so it is unique, or replace_all=true to replace all of them")
            report.update(match="exact", line=positions[0], replaced=count if every else 1)
            if every and count > 1:
                report["lines_changed_at"] = positions[:50]
            return text.replace(old, new) if every else text.replace(old, new, 1)

        answer = modify(path, change, expected_sha256)
        if "error" not in answer:
            answer.update(report)
        return answer
    return guarded(work)


def _as_lines(text: str) -> list[str]:
    body = lf(text)
    if body.endswith("\n"):
        body = body[:-1]
    return body.split("\n")


@mcp.tool(annotations=CHANGES)
def insert_lines(path: str, line: int, text: str, expected_sha256: str | None = None) -> dict:
    """WRITES: inserts TEXT as whole lines into the file PATH so that it starts at line LINE (1 = at the top;
    the file's line count + 1 = at the end); the lines from LINE on move down. Line numbers are those of
    read_file; pass its sha256 as expected_sha256 so that numbers from an older read are refused."""
    def work():
        where = _int(line, "line", 1)
        body = _text(text, "text", empty=False)

        def change(current: str, notes: list[str]) -> str:
            lines = current.split("\n")
            if current.endswith("\n"):
                lines.pop()
            elif current:
                notes.append("the file had no line break at its end: added one")
            if not current:
                lines = []
            if where > len(lines) + 1:
                raise Refused(f"line {where}: the file has {len(lines)} lines (use {len(lines) + 1} to add at the end)")
            lines[where - 1:where - 1] = _as_lines(body)
            return "\n".join(lines) + "\n"

        return modify(path, change, expected_sha256)
    return guarded(work)


@mcp.tool(annotations=CHANGES)
def delete_lines(path: str, start: int, end: int, expected_sha256: str | None = None) -> dict:
    """WRITES: deletes the lines START to END (1-based, both included) of the file PATH and answers what they
    held. Line numbers are those of read_file; pass its sha256 as expected_sha256 so that numbers from an older
    read are refused."""
    def work():
        first = _int(start, "start", 1)
        last = _int(end, "end", 1)
        if last < first:
            raise Refused(f"end ({last}) is before start ({first})")
        removed: list[str] = []

        def change(current: str, notes: list[str]) -> str:
            lines = current.split("\n")
            final = current.endswith("\n")
            if final:
                lines.pop()
            if last > len(lines):
                raise Refused(f"end {last}: the file has {len(lines)} lines")
            removed.extend(lines[first - 1:last])
            del lines[first - 1:last]
            # the new last line keeps its line break; a file that had none at its end keeps having none
            return "\n".join(lines) + ("\n" if lines and (final or last == len(lines) + len(removed)) else "")

        answer = modify(path, change, expected_sha256)
        if "error" not in answer:
            answer["deleted"] = numbered(removed, first, 40)
        return answer
    return guarded(work)


@mcp.tool(annotations=ADDS)
def append_file(path: str, text: str, create_dirs: bool = False) -> dict:
    """WRITES: adds TEXT at the end of the file PATH (created when it does not exist; create_dirs=true makes
    missing folders). When the file does not end with a line break, one is added before TEXT."""
    def work():
        body = lf(_text(text, "text", empty=False))
        made: list[str] = []
        with locate(path, write=True, create_dirs=_bool(create_dirs, "create_dirs"), created=made) as place:
            notes = [f"made the folder {folder}" for folder in made]
            info = place.lstat()
            if info is None:
                return write_text(place, None, None, body, notes + ["the file did not exist: created it"])
            if not st.S_ISREG(info.st_mode):
                raise Refused(f"path: {place.path} is {_kind_text(info.st_mode)}: only files are written")
            doc, before = text_of(place)
            current = doc.text
            if current and not current.endswith("\n") and not body.startswith("\n"):
                current += "\n"
                notes.append("the file did not end with a line break: added one before the text")
            return write_text(place, doc, before, current + body, notes)
    return guarded(work)


HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def parse_patch(patch: str) -> list[dict]:
    """The hunks of a unified diff for one file: [{"old_start", "old", "new", "header", "line"}]."""
    lines = lf(patch).split("\n")
    while lines and not lines[-1]:
        lines.pop()
    hunks: list[dict] = []
    headers = 0
    current = None
    for number, line in enumerate(lines, start=1):
        if line.startswith("--- ") and (current is None or number < len(lines) and lines[number].startswith("+++ ")):
            headers += 1
            if headers > 1:
                raise Refused(f"patch line {number}: a second file (---): apply_patch takes the diff of one file")
            current = None
            continue
        if current is None and (line.startswith(("+++ ", "diff ", "index ", "new file mode", "deleted file mode",
                                                 "similarity ", "rename ", "old mode", "new mode")) or not line):
            continue
        match = HUNK.match(line)
        if match:
            current = {"old_start": int(match.group(1)), "old_count": int(match.group(2) or 1),
                       "new_count": int(match.group(4) or 1), "old": [], "new": [], "header": line[:120],
                       "line": number, "no_newline": False, "blank_context": 0}
            hunks.append(current)
            continue
        if current is None:
            raise Refused(f"patch line {number}: expected a hunk header like '@@ -12,3 +12,4 @@', got "
                          f"{line[:80]!r}")
        if line.startswith("\\"):
            if current["new"] and current.get("last") in ("+", " "):
                current["no_newline"] = True
            continue
        mark, rest = (line[0], line[1:]) if line else (" ", "")
        if not line:
            current["blank_context"] += 1
        if mark == " ":
            current["old"].append(rest)
            current["new"].append(rest)
        elif mark == "-":
            current["old"].append(rest)
        elif mark == "+":
            current["new"].append(rest)
        else:
            raise Refused(f"patch line {number}: each line of a hunk starts with ' ' (context), '-' (removed) or '+' "
                          f"(added), not {line[:40]!r}")
        current["last"] = mark
    if not hunks:
        raise Refused("patch: no hunk (a unified diff has lines like '@@ -12,3 +12,4 @@' followed by ' ', '-' and "
                      "'+' lines)")
    return hunks


def _find(lines: list[str], block: list[str], start: int) -> list[int]:
    if not block:
        return []
    first = block[0]
    return [i for i in range(start, len(lines) - len(block) + 1)
            if lines[i] == first and lines[i:i + len(block)] == block]


@mcp.tool(annotations=CHANGES)
def apply_patch(path: str, patch: str, expected_sha256: str | None = None) -> dict:
    """WRITES: applies a unified diff (the output of diff -u or git diff, for this one file) to the file PATH.
    Every hunk's context (' ') and removed ('-') lines must match the file exactly; a hunk found at another line
    than its header says is applied there (the answer says so). If any hunk does not match, nothing is written
    and the error shows what the file has there. A diff whose hunks all start at -0,0 creates a missing file."""
    def work():
        hunks = parse_patch(_text(patch, "patch", empty=False))
        expected = _sha(expected_sha256)
        with locate(path, write=True) as place:
            info = place.lstat()
            if info is None:
                check_expected(None, expected, place)
                if any(h["old"] for h in hunks):
                    raise Refused(f"path: {place.path} does not exist (a patch that creates it has only '+' lines)")
                doc = before = None
                lines: list[str] = []
                final = True
            else:
                doc, before = text_of(place)
                check_expected(doc, expected, place)
                lines = doc.lines()
                final = doc.text.endswith("\n") or not doc.text
            notes: list[str] = []
            offset = 0
            floor = 0
            for number, hunk in enumerate(hunks, start=1):
                old, new = hunk["old"], hunk["new"]
                if (len(old), len(new)) != (hunk["old_count"], hunk["new_count"]) and \
                        (hunk["old_count"], hunk["new_count"]) != (1, 1):
                    notes.append(f"hunk {number}: its header counts ({hunk['header']}) do not match its lines "
                                 f"({len(old)} old, {len(new)} new): the lines were used")
                if hunk["blank_context"]:
                    notes.append(f"hunk {number}: {hunk['blank_context']} empty line(s) taken as empty context lines")
                if not old:  # only added lines: "-N,0" adds them after line N (0: at the top)
                    at = min(max(0, hunk["old_start"] + offset), len(lines)) if hunk["old_start"] else 0
                else:
                    want = max(0, hunk["old_start"] - 1 + offset)
                    if lines[want:want + len(old)] == old and want >= floor:
                        at = want
                    else:
                        places = _find(lines, old, floor)
                        if not places:
                            shown_at = max(0, want)
                            have = numbered(lines[shown_at:shown_at + max(len(old), 3)], shown_at + 1, 12)
                            raise Refused(
                                f"hunk {number} ({hunk['header']}) does not apply: nothing was written. It expects "
                                f"at line {want + 1}:\n" + "\n".join(numbered(old, want + 1, 12)) +
                                f"\nbut the file has there:\n" + ("\n".join(have) or "(the file ends before)") +
                                _nearest("\n".join(lines), "\n".join(old)) +
                                "\nread_file the part again and make the patch from what it holds (or use edit_file)")
                        at = min(places, key=lambda i: abs(i - want))
                        notes.append(f"hunk {number} applied at line {at + 1} (its header says "
                                     f"{hunk['old_start']})")
                lines[at:at + len(old)] = new
                offset += len(new) - len(old)
                floor = at + len(new)
                if hunk["no_newline"] and number == len(hunks):
                    final = False
            text = "\n".join(lines) + ("\n" if lines and final else "")
            answer = write_text(place, doc, before, text, notes)
            answer["hunks"] = len(hunks)
            return answer
    return guarded(work)


# --- files and folders -----------------------------------------------------------------------------------------

def destination(dst, src_name: str, create_dirs: bool, made: list[str]) -> Place:
    """Where move and copy put SRC_NAME for DST: DST itself, or SRC_NAME inside it when DST is an existing folder
    (mv's 'into the folder'; /work itself counts as one)."""
    root, names = split_path(dst, "dst")
    if not names:
        return locate(shown(root, [src_name]), "dst", write=True)
    return _target_in(locate(dst, "dst", write=True, create_dirs=create_dirs, created=made), src_name, "dst")


def _target_in(place: Place, src_name: str, name: str) -> Place:
    """PLACE, or - when it is an existing folder - the place of SRC_NAME inside it (mv's 'into the folder')."""
    info = place.lstat()
    if info is not None and st.S_ISDIR(info.st_mode):
        inner = locate(shown(place.root, place.parts + [src_name]), name, write=True)
        place.close()
        return inner
    return place


@mcp.tool(annotations=CHANGES)
def move(src: str, dst: str, overwrite: bool = False, create_dirs: bool = False) -> dict:
    """WRITES: moves or renames SRC to DST (inside /work). A DST that is an existing folder gets SRC inside it.
    An existing file at DST is replaced only with overwrite=true. A link is moved as the link itself.
    create_dirs=true makes DST's missing folders."""
    def work():
        replace = _bool(overwrite, "overwrite")
        made: list[str] = []
        with locate(src, "src", write=True, keep_link=True, from_trash=True) as source:
            info = source.lstat()
            if info is None:
                raise Refused(f"src: {source.path} does not exist")
            target = destination(dst, source.name, _bool(create_dirs, "create_dirs"), made)
            with target:
                if source.path == target.path:
                    raise Refused("src and dst are the same")
                if (target.path + "/").startswith(source.path + "/"):
                    raise Refused(f"dst: {target.path} is inside {source.path}: a folder cannot move into itself")
                there = target.lstat()
                if there is not None:
                    if st.S_ISDIR(there.st_mode):
                        raise Refused(f"dst: {target.path} is a folder already")
                    if not replace:
                        raise Refused(f"dst: {target.path} exists already (overwrite=true replaces it)")
                    if st.S_ISDIR(info.st_mode):
                        raise Refused(f"dst: {target.path} is a file; a folder does not replace a file")
                try:
                    os.rename(source.name, target.name, src_dir_fd=source.dirfd, dst_dir_fd=target.dirfd)
                except OSError as exc:
                    if exc.errno == errno.EXDEV:
                        raise Refused("src and dst are on different file systems: copy, then delete") from None
                    raise
                os.fsync(target.dirfd)
                if target.dirfd != source.dirfd:
                    os.fsync(source.dirfd)
                answer = {"moved": source.path, "to": target.path, "type": _kind(info.st_mode)}
                if there is not None:
                    answer["replaced"] = "a file was there and was replaced"
                if made:
                    answer["made_folders"] = made
                return answer
    return guarded(work)


def _copy_file(src_dir: int, src_name: str, dst_dir: int, dst_name: str, budget: list[int]) -> int:
    """Copy one regular file (no link followed) into DST_DIR as a new name; its bytes."""
    fd = os.open(src_name, READ_FLAGS, dir_fd=src_dir)
    try:
        info = os.fstat(fd)
        if not st.S_ISREG(info.st_mode):
            raise Refused(f"{src_name} is {_kind_text(info.st_mode)}")
        budget[0] += info.st_size
        if budget[0] > MAX_COPY_BYTES:
            raise Refused(f"more than {MAX_COPY_BYTES >> 20} MiB to copy: copy less at once")
        out = os.open(dst_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600,
                      dir_fd=dst_dir)
        try:
            size = 0
            while True:
                chunk = os.read(fd, 1 << 20)
                if not chunk:
                    break
                view = memoryview(chunk)
                while view:
                    view = view[os.write(out, view):]
                size += len(chunk)
            os.fchmod(out, st.S_IMODE(info.st_mode) & 0o777)
            os.fsync(out)
        finally:
            os.close(out)
        return size
    finally:
        os.close(fd)


def _copy_tree(src_fd: int, dst_fd: int, shown_src: str, budget: list[int], skipped: list[str]) -> None:
    with os.scandir(src_fd) as items:
        entries = sorted((item.name, item.is_dir(follow_symlinks=False), item.is_file(follow_symlinks=False))
                         for item in items)
    for item_name, is_dir, is_file in entries:
        budget[1] += 1
        if budget[1] > MAX_COPY_ENTRIES:
            raise Refused(f"more than {MAX_COPY_ENTRIES} entries to copy: copy less at once")
        if is_file:
            _copy_file(src_fd, item_name, dst_fd, item_name, budget)
        elif is_dir:
            os.mkdir(item_name, 0o700, dir_fd=dst_fd)
            sub_src = os.open(item_name, DIR_FLAGS, dir_fd=src_fd)
            try:
                sub_dst = os.open(item_name, DIR_FLAGS, dir_fd=dst_fd)
                try:
                    _copy_tree(sub_src, sub_dst, f"{shown_src}/{item_name}", budget, skipped)
                    os.fchmod(sub_dst, st.S_IMODE(os.fstat(sub_src).st_mode) & 0o777)
                finally:
                    os.close(sub_dst)
            finally:
                os.close(sub_src)
        else:
            skipped.append(f"{shown_src}/{item_name}")


@mcp.tool(annotations=CHANGES)
def copy(src: str, dst: str, overwrite: bool = False, create_dirs: bool = False) -> dict:
    """WRITES: copies the file or folder SRC to DST (a folder with everything in it; links, devices and pipes
    inside are left out and named). SRC may be in /work or a read-only folder; DST is in /work. A DST that is an
    existing folder gets the copy inside it. An existing file at DST is replaced only with overwrite=true. At
    most 1 GiB and 10000 entries."""
    def work():
        replace = _bool(overwrite, "overwrite")
        made: list[str] = []
        with locate(src, "src", follow=False, keep_link=True) as source:
            info = source.lstat()
            if info is None or source.name is None:
                raise Refused(f"src: {source.path} does not exist" if info is None else
                              f"src: {source.path} is a whole mounted folder: copy what is inside it")
            if st.S_ISLNK(info.st_mode):
                raise Refused(f"src: {source.path} is a symbolic link: copy the file it points to")
            if not (st.S_ISREG(info.st_mode) or st.S_ISDIR(info.st_mode)):
                raise Refused(f"src: {source.path} is {_kind_text(info.st_mode)}: only files and folders are copied")
            target = destination(dst, source.name, _bool(create_dirs, "create_dirs"), made)
            with target:
                if target.path == source.path:
                    raise Refused("src and dst are the same file: name another dst")
                if (target.path + "/").startswith(source.path + "/"):
                    raise Refused(f"dst: {target.path} is inside {source.path}")
                there = target.lstat()
                budget = [0, 0]
                skipped: list[str] = []
                if st.S_ISREG(info.st_mode):
                    if there is not None:
                        if not st.S_ISREG(there.st_mode):
                            raise Refused(f"dst: {target.path} is {_kind_text(there.st_mode)}")
                        if not replace:
                            raise Refused(f"dst: {target.path} exists already (overwrite=true replaces it)")
                    temp = temp_name(target.name)
                    try:
                        size = _copy_file(source.dirfd, source.name, target.dirfd, temp, budget)
                        if there is None:
                            os.link(temp, target.name, src_dir_fd=target.dirfd, dst_dir_fd=target.dirfd,
                                    follow_symlinks=False)
                            os.unlink(temp, dir_fd=target.dirfd)
                        else:
                            os.rename(temp, target.name, src_dir_fd=target.dirfd, dst_dir_fd=target.dirfd)
                    except BaseException:
                        with contextlib.suppress(OSError):
                            os.unlink(temp, dir_fd=target.dirfd)
                        raise
                    answer = {"copied": source.path, "to": target.path, "type": "file", "bytes": size}
                else:
                    if there is not None:
                        raise Refused(f"dst: {target.path} exists already")
                    temp = temp_name(target.name)
                    os.mkdir(temp, 0o700, dir_fd=target.dirfd)
                    try:
                        src_fd = open_dir(source, "src")
                        try:
                            dst_fd = os.open(temp, DIR_FLAGS, dir_fd=target.dirfd)
                            try:
                                _copy_tree(src_fd, dst_fd, source.path, budget, skipped)
                                os.fchmod(dst_fd, st.S_IMODE(info.st_mode) & 0o777)
                                os.fsync(dst_fd)
                            finally:
                                os.close(dst_fd)
                        finally:
                            os.close(src_fd)
                        if target.lstat() is not None:
                            raise Refused(f"dst: {target.path} appeared while copying")
                        os.rename(temp, target.name, src_dir_fd=target.dirfd, dst_dir_fd=target.dirfd)
                    except BaseException:
                        with contextlib.suppress(OSError):
                            shutil.rmtree(temp, dir_fd=target.dirfd)
                        raise
                    answer = {"copied": source.path, "to": target.path, "type": "dir", "bytes": budget[0],
                              "entries": budget[1]}
                    if skipped:
                        answer["left_out"] = skipped[:50]
                os.fsync(target.dirfd)
                if made:
                    answer["made_folders"] = made
                return answer
    return guarded(work)


@mcp.tool(annotations=ADDS)
def mkdir(path: str) -> dict:
    """WRITES: makes the folder PATH inside /work, with the folders above it that are missing. A folder that is
    there already is fine."""
    def work():
        made: list[str] = []
        with locate(path, write=True, create_dirs=True, created=made) as place:
            info = place.lstat()
            if info is not None:
                if st.S_ISDIR(info.st_mode):
                    return {"path": place.path, "action": "exists already", "made_folders": made}
                raise Refused(f"path: {place.path} is {_kind_text(info.st_mode)}, not a folder")
            os.mkdir(place.name, 0o777, dir_fd=place.dirfd)
            os.fsync(place.dirfd)
            return {"path": place.path, "action": "created", "made_folders": made + [place.path]}
    return guarded(work)


def _trash_folder(place: Place) -> tuple[int, str]:
    """A new folder in /work/.trash for one deletion (descriptor, shown path); .trash made when missing (with a
    .gitignore so git leaves it alone)."""
    root = open_root(WORK)
    try:
        try:
            os.mkdir(TRASH, 0o700, dir_fd=root)
            made = True
        except FileExistsError:
            made = False
        try:  # opened without following a link: one swapped in after the mkdir is refused, never written through
            trash = os.open(TRASH, DIR_FLAGS, dir_fd=root)
        except OSError:
            raise Refused(f"{WORK}/{TRASH} is not a folder (a link?): the user removes it, or sets FILES_TRASH=0 "
                          "to delete for real") from None
    finally:
        os.close(root)
    try:
        if made:
            with contextlib.suppress(FileExistsError):
                fd = os.open(".gitignore", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                             0o644, dir_fd=trash)
                with os.fdopen(fd, "w") as handle:
                    handle.write("# what the files MCP server's delete removed; restore with move, empty by hand\n*\n")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
        os.mkdir(stamp, 0o700, dir_fd=trash)
        fd = os.open(stamp, DIR_FLAGS, dir_fd=trash)
        folders = [stamp]
        for part in place.names:
            os.mkdir(part, 0o700, dir_fd=fd)
            inner = os.open(part, DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = inner
            folders.append(part)
        return fd, shown(WORK, [TRASH] + folders + [place.name])
    finally:
        os.close(trash)


@mcp.tool(annotations=CHANGES)
def delete(path: str, recursive: bool = False) -> dict:
    """WRITES: deletes the file, link or folder PATH inside /work. It is moved into /work/.trash (restore it with
    move), unless the user turned the trash off (FILES_TRASH=0). A folder with something in it needs
    recursive=true. A link is deleted as the link, never what it points to."""
    def work():
        deep = _bool(recursive, "recursive")
        with locate(path, write=True, keep_link=True) as place:
            info = place.lstat()
            if info is None:
                raise Refused(f"path: {place.path} does not exist")
            entries = 0
            if st.S_ISDIR(info.st_mode):
                fd = open_dir(place)
                try:
                    with os.scandir(fd) as items:
                        entries = sum(1 for _ in items)
                finally:
                    os.close(fd)
                if entries and not deep:
                    raise Refused(f"path: {place.path} is a folder with {entries} entries: recursive=true deletes it "
                                  "with everything in it")
            answer = {"deleted": place.path, "type": _kind(info.st_mode)}
            if entries:
                answer["entries"] = entries
            if trash_on():
                folder, where = _trash_folder(place)
                try:
                    try:
                        os.rename(place.name, place.name, src_dir_fd=place.dirfd, dst_dir_fd=folder)
                    except OSError as exc:
                        if exc.errno == errno.EXDEV:
                            raise Refused(f"path: {place.path} is on another file system than {WORK}/{TRASH}: it "
                                          "cannot go into the trash (FILES_TRASH=0 deletes for real)") from None
                        raise
                    os.fsync(folder)
                finally:
                    os.close(folder)
                answer.update(moved_to=where, restore=f"move(src=\"{where}\", dst=\"{place.path}\")")
            else:
                if st.S_ISDIR(info.st_mode):
                    if entries:
                        shutil.rmtree(place.name, dir_fd=place.dirfd)
                    else:
                        os.rmdir(place.name, dir_fd=place.dirfd)
                else:
                    os.unlink(place.name, dir_fd=place.dirfd)
                answer["note"] = "deleted for good (FILES_TRASH=0)"
            os.fsync(place.dirfd)
            return answer
    return guarded(work)


if __name__ == "__main__":
    # An exception nobody caught would print its traceback (with paths) to stderr: its type only.
    sys.excepthook = lambda kind, value, tb: log.error("fatal %s", kind.__name__)
    mcp.run("stdio")
