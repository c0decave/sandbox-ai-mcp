#!/usr/bin/env python3
"""code-search MCP server (sandbox-ai-mcp): find and read code by name, made for small local models that fail to
find code, read whole files and guess names.

The project is the folder mounted read-only at /work; up to three more folders mounted at /ref1, /ref2 and /ref3 are
read the same way. Nothing is ever written. A path is relative to /work or absolute under one of these folders; ".."
is refused, and every path is walked one name at a time from the folder's open descriptor (openat with O_NOFOLLOW):
a link named in a path is followed only while it stays inside its folder, and the walks over many files follow no
link at all. Only regular files are read (no devices, pipes or sockets), each at most MAX_FILE_BYTES.

Tools: find_text, find_files, outline, find_definition, find_references, read_symbol, project_map.

Outlines: Python with Python's own parser (ast: exact); JavaScript/TypeScript, Go, Rust, Java, C/C++ and shell by
line patterns and brace counting after comments and strings are blanked out (approximate, and every answer says so).
Outlines are cached per file (modification time, size, inode, change time), at most MAX_CACHED_FILES files and
MAX_CACHED_SYMBOLS symbols, for find_definition, find_references, read_symbol, project_map and find_text.

Every answer is plain text whose first line says what was found, bounded in results, lines and characters. Every
walk has a time and an entry budget; a regular expression that repeats a repeating group is refused, and any search
is stopped by a timer (SIGALRM, which also interrupts the regular expression engine).

Standard library and the MCP SDK only; no network.
"""

from __future__ import annotations

import ast
import contextlib
import difflib
import errno
import fnmatch
import logging
import os
import re
import signal
import stat as st
import sys
import threading
import time
import warnings
from typing import NamedTuple

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

WORK = "/work"
REFS = ("/ref1", "/ref2", "/ref3")
#: Each folder the server can reach (the path a tool argument names) -> where it is in this container. Tests point
#: them at temporary folders.
ROOTS: dict[str, str] = {WORK: WORK, **{ref: ref for ref in REFS}}
#: Folders the walks do not go into unless the path names them: version control, dependencies, build output, caches.
SKIP_DIRS = frozenset({
    ".git", ".hg", ".svn", ".trash", "node_modules", "bower_components", "vendor", "__pycache__", ".venv", "venv",
    ".tox", ".nox", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".cache", ".gradle", ".idea", ".next", ".nuxt",
    ".svelte-kit", ".terraform", ".eggs", "build", "dist", "target", "coverage", "htmlcov",
})
#: Generated files the walks skip: minified bundles and source maps (one huge line each).
SKIP_SUFFIXES = (".min.js", ".min.css", ".map")

MAX_PATH = 4096
MAX_FILE_BYTES = 2 << 20         # a file larger than this is not read
MAX_VISIT = 200_000              # entries one walk looks at
MAX_DIR_ENTRIES = 50_000         # entries of one folder
MAX_DEPTH = 64                   # folders below the start of a walk
MAX_LINKS = 16                   # links followed for one path
MAX_PATTERN = 500                # characters of a search pattern
MAX_RESULTS = 200                # find_text: matches one answer shows at most
DEFAULT_RESULTS = 30
MAX_COUNT = 1000                 # find_text: matches counted at most
MAX_OFFSET = 100_000
MAX_LINE_SHOWN = 160             # characters of a line in a result
MAX_MATCH_LINE = 10_000          # characters of a line a pattern is matched against
MAX_ANSWER = 24_000              # characters of any answer
MAX_OUTLINE = 300                # symbols outline shows
MAX_SYMBOL_LINES = 250           # lines read_symbol shows
MAX_SOURCE_LINE = 400            # characters of one line read_symbol shows
MAX_DEFINITIONS = 20
MAX_REFERENCES = 50
MAX_COLLECT = 2000               # find_references: occurrences collected before ranking
MAX_FILES_FOUND = 50             # find_files
MAX_FILE_HITS = 20_000           # find_files: matches collected before ranking
MAX_MAP_LINES = 200              # project_map
MAX_MAP_FILES = 25               # files project_map shows per folder
MAX_GITIGNORE_BYTES = 64 << 10
MAX_RULES = 500                  # .gitignore rules in force at once
MAX_CACHED_FILES = 20_000
MAX_CACHED_SYMBOLS = 200_000     # at most about 870 bytes each (the caps below): under 180 MiB when full
MAX_SYMBOLS_PER_FILE = 5_000
MAX_SIGNATURE = 160
MAX_NAME = 120                   # characters of a symbol's name kept (a longer one is cut)
MAX_QUAL = 240                   # characters of a qualified name kept (its end: "...Outer.Inner.name")
MAX_NESTING = 100                # containers open at once in a brace-language outline
MAX_BRACES = 100_000             # '{' in a file of a brace language outlined at all
MAX_PARSE_TOKENS = 100_000       # tokens of a file given to Python's parser (about 1 KB of memory each at worst)
MAX_GLOB_PARTS = 16              # names of a glob or .gitignore pattern (a/b/**/c: 4)
SEARCH_SECONDS = 10.0            # find_text, find_files, find_references
INDEX_SECONDS = 20.0             # find_definition, project_map: the walk and the outlines
MAP_SYMBOL_SECONDS = 8.0         # project_map: outlines of the files shown
CALL_SECONDS = 45.0              # any call (below Codex's 60 s)
PARSE_SECONDS = 5.0              # the outline of one file: given up after this (and remembered until it changes)

DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_NOCTTY | os.O_CLOEXEC

logging.basicConfig(level=logging.WARNING, stream=sys.stderr,
                    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
log = logging.getLogger("code-search-mcp")

mcp = FastMCP("code-search-mcp", instructions=(
    "Finds and reads code in the project folder /work (read-only; more read-only folders at /ref1-/ref3 when "
    "mounted). Paths are relative to /work. Start with project_map for an overview. To find a function or class by "
    "name use find_definition, then read_symbol to read only that function or class instead of the whole file. "
    "outline lists the functions and classes of one file with line numbers; find_references shows where a name is "
    "used; find_text searches any text; find_files finds files by name. Answers are short: when one says 'more', "
    "narrow it (path, glob) or continue with offset."))


class Refused(ValueError):
    """A tool argument or a file this server does not take; the text says why and what to do instead."""


class TimeLimit(Exception):
    """A search took longer than its time limit."""


# --- arguments -----------------------------------------------------------------------------------------------------

_CONTROLS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
#: Never in an answer's line: a name or line could fake one. Line breaks of every kind (str.splitlines() breaks at
#: \x85, \u2028 and \u2029 too) and the other control characters; a tab stays.
_SHOWN_CONTROLS = re.compile(r"[\x00-\x08\x0a-\x1f\x7f\x85\u2028\u2029]")


def _int(value, name: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise Refused(f"{name}: a whole number from {low} to {high}")
    return value


def _bool(value, name: str) -> bool:
    if not isinstance(value, bool):
        raise Refused(f"{name}: true or false")
    return value


def _text(value, name: str, limit: int, example: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise Refused(f"{name}: give it, like {example}")
    if len(value) > limit or _CONTROLS.search(value):
        raise Refused(f"{name}: at most {limit} characters, no control characters")
    return value


_SYMBOL_NAME = re.compile(r"^[A-Za-z_$~][\w$]*(?:(?:\.|::|#)~?[A-Za-z_$][\w$]*)*$")


def _symbol_name(value, name: str = "name") -> tuple[str, str | None]:
    """(the last part, the dotted whole or None) of a symbol name like parse_args, App.run or App::run."""
    text = _text(value, name, 200, '"parse_args" or "App.run"').strip()
    text = re.sub(r"\(\)$", "", text)  # a model writes run() for run
    if not _SYMBOL_NAME.match(text):
        raise Refused(f"{name}: a name like parse_args, App or App.run (letters, digits, _ and $; parts joined by . "
                      "or ::); find_text searches any other text")
    parts = re.split(r"\.|::|#", text)
    return parts[-1], (".".join(parts) if len(parts) > 1 else None)


# --- paths: one name at a time from the root's descriptor, never through a link that leaves it ---------------------

def roots_shown() -> str:
    return ", ".join(r for r in ROOTS if r == WORK or os.path.isdir(ROOTS[r]))


def split_path(value, name: str = "path") -> tuple[str, list[str]]:
    """(root, names) of the path VALUE, checked without touching the file system: relative to /work or absolute
    under a root (empty, '.' and '/' are /work); no '..', no control characters."""
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise Refused(f"{name}: a path inside {WORK}, like src or src/app.py")
    path = value.strip()
    if path in ("", ".", "./", "/"):
        return WORK, []
    if len(path) > MAX_PATH or _CONTROLS.search(path):
        raise Refused(f"{name}: no control characters, at most {MAX_PATH} characters")
    if path.startswith("~"):
        raise Refused(f"{name}: ~ (a home folder) is not reachable here; paths are inside {WORK}, like src/app.py")
    if "\\" in path:
        raise Refused(f"{name}: use / between folder names, not \\ (like src/app.py)")
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
        raise Refused(f"{name}: '..' is not allowed in a path: name it from {root} down (like src/app.py)")
    for part in names:
        if len(part.encode("utf-8", "surrogatepass")) > 255:
            raise Refused(f"{name}: a name in the path is longer than 255 bytes")
    return root, names


def display(root: str, names: list[str]) -> str:
    """How a path is shown: relative below /work (src/app.py), absolute below the other folders. A control character
    in a name (a line break) is shown as ?, so that no name can start a line of its own in an answer."""
    shown = "/".join(names)
    if _SHOWN_CONTROLS.search(shown):
        shown = _SHOWN_CONTROLS.sub("?", shown)
    if root == WORK:
        return shown if names else WORK
    return root + ("/" + shown if names else "")


def _kind_text(mode: int) -> str:
    if st.S_ISDIR(mode):
        return "a folder"
    if st.S_ISLNK(mode):
        return "a symbolic link"
    if st.S_ISFIFO(mode):
        return "a named pipe (FIFO)"
    if st.S_ISSOCK(mode):
        return "a socket"
    return "a device"


class Place:
    """An open folder (DIRFD) and a NAME in it (None: the folder itself, only for a root); NAMES leads there from
    ROOT, the names actually walked (after links)."""

    def __init__(self, root: str, dirfd: int, names: list[str], name: str | None):
        self.root, self.dirfd, self.names, self.name = root, dirfd, names, name

    @property
    def parts(self) -> list[str]:
        return self.names + ([self.name] if self.name is not None else [])

    @property
    def path(self) -> str:
        return display(self.root, self.parts)

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
        raise Refused(f"no folder is mounted at {root} (the user adds it: sandbox-ai mcp add code-search --mount "
                      f"{root}=FOLDER:ro)") from None


def _link_parts(root: str, target: str) -> list[str] | None:
    """The names of an absolute link TARGET below ROOT (as this container or the tests see it), None outside."""
    for base in dict.fromkeys((root, ROOTS[root].rstrip("/") or "/")):
        if target == base or target.startswith(base + "/"):
            return [p for p in target[len(base):].split("/") if p not in ("", ".")]
    return None


def locate(value, name: str = "path") -> Place:
    """The Place of path VALUE. Each folder on the way is opened by its name in the one before (O_NOFOLLOW,
    O_DIRECTORY), so nothing swapped in meanwhile leads elsewhere. A link is followed while it stays inside its root
    ('..' of a link target goes up the folders actually walked, never above the root). The last name need not
    exist."""
    root, names = split_path(value, name)
    stack = [open_root(root)]
    walked: list[str] = []
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
                    raise Refused(f"{name}: a link on the way leads outside {root}: links out of the mounted folders "
                                  "are never followed")
                os.close(stack.pop())
                walked.pop()
                todo.pop(0)
                continue
            here = display(root, walked + [part])
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
                raise Refused(f"{name}: the folder {here} does not exist (find_files finds a file by name)")
            if st.S_ISLNK(info.st_mode):
                try:
                    target = os.readlink(part, dir_fd=stack[-1])
                except OSError:
                    target = "?"
                hops += 1
                if hops > MAX_LINKS:
                    raise Refused(f"{name}: more than {MAX_LINKS} links on the way (a loop?)")
                if target.startswith("/"):
                    inside = _link_parts(root, target)
                    if inside is None:
                        raise Refused(f"{name}: {here} is a link to {_SHOWN_CONTROLS.sub('?', target[:200])}, "
                                      f"outside {root}: links out of the mounted folders are never followed")
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
                raise Refused(f"{name}: {here} is {'a file' if st.S_ISREG(info.st_mode) else _kind_text(info.st_mode)}"
                              ", not a folder")
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
        return Place(root, dirfd, walked, todo[0] if todo else None)
    finally:
        for fd in stack:
            os.close(fd)


def _decode(data: bytes) -> str:
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    return data.decode("utf-8", "replace").replace("\r\n", "\n")


def load_text(dirfd: int, name: str, cap: int | None = None) -> tuple[str | None, os.stat_result | None, str]:
    """(text, fstat, "") of the regular file NAME in the folder DIRFD, opened without following a link and without
    blocking on a pipe; (None, fstat or None, why) for one that is not read: unreadable, special, large, binary."""
    cap = MAX_FILE_BYTES if cap is None else cap
    try:
        fd = os.open(name, READ_FLAGS, dir_fd=dirfd)
    except OSError as exc:
        return None, None, "a link" if exc.errno == errno.ELOOP else "unreadable"
    try:
        info = os.fstat(fd)
        if not st.S_ISREG(info.st_mode):
            return None, info, "not a regular file"
        if info.st_size > cap:
            return None, info, "large"
        chunks, size = [], 0
        while size <= cap:
            chunk = os.read(fd, min(1 << 20, cap + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        if size > cap:
            return None, info, "large"
    finally:
        os.close(fd)
    data = b"".join(chunks)
    if b"\0" in data[:8192]:
        return None, info, "binary"
    return _decode(data), info, ""


WHY = {"large": f"it is larger than {MAX_FILE_BYTES >> 20} MiB", "binary": "it is a binary file",
       "not a regular file": "it is not a regular file", "a link": "it is a link", "unreadable": "it cannot be read"}
NOT_READ = {"large": f"larger than {MAX_FILE_BYTES >> 20} MiB", "binary": "binary", "not a regular file": "special",
            "a link": "links", "unreadable": "unreadable"}


# --- .gitignore ------------------------------------------------------------------------------------------------------

class Glob:
    """A glob over the names of a path: * and ? within a name, [abc] a set, ** any number of folders, \\ escapes
    the next character (gitignore's rules). Each name is matched by fnmatch's translation, whose regular expressions
    do not backtrack without end (atomic groups); ** by a table over the names: linear in the names times the parts,
    whatever the pattern."""

    def __init__(self, pattern: str, ignore_case: bool = False):
        flags = re.I if ignore_case else 0
        self.parts: list[re.Pattern | None] = []
        if pattern.count("/") >= MAX_GLOB_PARTS:  # matching costs names times parts, for every entry of a walk
            raise TooManyParts(pattern)
        for part in pattern.split("/"):
            if part == "**":
                if not self.parts or self.parts[-1] is not None:
                    self.parts.append(None)
                continue
            literal = re.sub(r"\\(.)", lambda m: "[" + m.group(1) + "]" if m.group(1) not in "]!^" else
                             ("[]]" if m.group(1) == "]" else m.group(1)), part)
            self.parts.append(re.compile(fnmatch.translate(literal), flags))

    def match_name(self, name: str) -> bool:
        if len(self.parts) != 1:
            return False
        return self.parts[0] is None or self.parts[0].match(name) is not None

    def match_path(self, path: str) -> bool:
        names = path.split("/")
        count = len(names)
        ahead = [False] * count + [True]   # the parts after this one match names[j:]
        for part in reversed(self.parts):
            here = [False] * (count + 1)
            if part is None:
                seen = False
                for j in range(count, -1, -1):
                    seen = seen or ahead[j]
                    here[j] = seen
            else:
                for j in range(count):
                    here[j] = ahead[j + 1] and part.match(names[j]) is not None
            ahead = here
        return ahead[0]


class TooManyParts(ValueError):
    """A glob of more than MAX_GLOB_PARTS names."""


class Rule(NamedTuple):
    base: str              # the folder of the .gitignore, relative to the root ("" for the root)
    glob: Glob
    negate: bool
    dir_only: bool
    anchored: bool         # matched against the path below BASE, else against the name


def parse_gitignore(text: str, base: str, limit: int = MAX_RULES) -> list[Rule]:
    rules: list[Rule] = []
    if limit <= 0:
        return rules
    for raw in text.split("\n"):
        line = raw.rstrip("\r")
        if not line or line.startswith("#"):
            continue
        # trailing spaces are cut unless escaped ("a\\ " keeps one): in one step, not one space at a time
        kept = line.rstrip(" ")
        line = kept + " " if kept.endswith("\\") and len(kept) < len(line) else kept
        negate = line.startswith("!")
        if negate or line.startswith("\\!") or line.startswith("\\#"):
            line = line[1:]
        dir_only = line.endswith("/")
        line = line.rstrip("/")
        if not line or len(line) > 1000:
            continue
        anchored = "/" in line
        line = line.lstrip("/")
        try:
            glob = Glob(line)
        except (re.error, TooManyParts):
            continue
        rules.append(Rule(base, glob, negate, dir_only, anchored))
        if len(rules) >= limit:
            break
    return rules


def read_gitignore(dirfd: int, base: str, limit: int = MAX_RULES) -> list[Rule]:
    text, _, _ = load_text(dirfd, ".gitignore", MAX_GITIGNORE_BYTES)
    return parse_gitignore(text, base, limit) if text else []


def ignored(rules, rel: str, name: str, is_dir: bool) -> bool:
    """Whether the .gitignore RULES leave out REL (relative to the root; NAME its last part): the last match wins."""
    result = False
    for rule in rules:
        if rule.dir_only and not is_dir:
            continue
        if result != rule.negate:  # this rule cannot change the outcome
            continue
        if rule.base:
            if not rel.startswith(rule.base + "/"):
                continue
            sub = rel[len(rule.base) + 1:]
        else:
            sub = rel
        if rule.glob.match_path(sub) if rule.anchored else rule.glob.match_name(name):
            result = not rule.negate
    return result


# --- walking -------------------------------------------------------------------------------------------------------

class Budget:
    """The entries and seconds a walk may take; STOPPED says why it ended early."""

    def __init__(self, seconds: float):
        self.seconds = seconds
        self.deadline = time.monotonic() + seconds
        self.visited = 0
        self.ticks = 0
        self.stopped: str | None = None

    def take(self, entries: int) -> bool:
        """Count the ENTRIES of a folder just listed; False once more than MAX_VISIT were listed."""
        self.visited += entries
        if self.visited > MAX_VISIT and self.stopped is None:
            self.stopped = f"looked at {MAX_VISIT} entries"
        return self.stopped is None

    def tick(self) -> bool:
        """False once the walk is to stop (checks the clock at every entry: one entry can cost much, as under the
        maximum of .gitignore rules)."""
        self.ticks += 1
        return not self.expired()

    def expired(self) -> bool:
        if self.stopped is None and time.monotonic() > self.deadline:
            self.stopped = f"took longer than {self.seconds:g} s"
        return self.stopped is not None


class Scope:
    """Where a walk starts: a folder (FILE None) or one FILE in the folder DIRFD; NAMES lead to that folder from
    ROOT; RULES are the .gitignore rules of the folders above it."""

    def __init__(self, root: str, names: list[str], dirfd: int, file: str | None, rules: list[Rule]):
        self.root, self.names, self.dirfd, self.file, self.rules = root, names, dirfd, file, rules

    @property
    def rel(self) -> str:
        return "/".join(self.names)

    @property
    def shown(self) -> str:
        return display(self.root, self.names + ([self.file] if self.file else []))

    def close(self) -> None:
        if self.dirfd >= 0:
            os.close(self.dirfd)
            self.dirfd = -1

    def __enter__(self) -> Scope:
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def _ancestor_rules(root: str, names: list[str]) -> list[Rule]:
    """The .gitignore rules of the root and of every folder between it and ROOT/NAMES (not of that folder itself:
    the walk reads it)."""
    rules: list[Rule] = []
    fd = open_root(root)
    try:
        for k in range(len(names)):
            rules += read_gitignore(fd, "/".join(names[:k]), MAX_RULES - len(rules))
            try:
                sub = os.open(names[k], DIR_FLAGS, dir_fd=fd)
            except OSError:
                break
            os.close(fd)
            fd = sub
    finally:
        os.close(fd)
    return rules[:MAX_RULES]


def open_scope(value, name: str = "path", *, folder: bool = False) -> Scope:
    """The Scope of path VALUE: an existing folder, or (unless FOLDER) a regular file."""
    with locate(value, name) as place:
        if place.name is None:
            return Scope(place.root, place.names, os.dup(place.dirfd), None, [])
        info = place.lstat()
        if info is None:
            raise Refused(f"{name}: {place.path} does not exist (find_files finds a file by name)")
        if st.S_ISDIR(info.st_mode):
            try:
                fd = os.open(place.name, DIR_FLAGS, dir_fd=place.dirfd)
            except OSError as exc:
                raise Refused(f"{name}: {place.path} cannot be opened ({exc.strerror})") from None
            try:
                rules = _ancestor_rules(place.root, place.parts)
            except BaseException:
                os.close(fd)
                raise
            return Scope(place.root, place.parts, fd, None, rules)
        if not st.S_ISREG(info.st_mode):
            raise Refused(f"{name}: {place.path} is {_kind_text(info.st_mode)}: only regular files are read")
        if folder:
            raise Refused(f"{name}: {place.path} is a file; give a folder (or leave path empty for the whole "
                          "project)")
        return Scope(place.root, place.names, os.dup(place.dirfd), place.name, [])


class Item(NamedTuple):
    dirfd: int             # the open folder the entry is in (valid until the walk goes on)
    name: str
    rel: str               # relative to the root
    is_dir: bool
    depth: int             # 0: directly in the start folder
    entry: os.DirEntry | None


def walk(scope: Scope, budget: Budget, *, dirs: bool = False, skipped: set | None = None):
    """Regular files (and with DIRS folders) below SCOPE in name order; no link followed, no device, pipe or
    socket; SKIP_DIRS and what .gitignore leaves out are not entered (their names into SKIPPED)."""
    if scope.file is not None:
        yield Item(scope.dirfd, scope.file, "/".join(scope.names + [scope.file]), False, 0, None)
        return
    yield from _walk_dir(scope.dirfd, scope.rel, list(scope.rules), 0, budget, dirs, skipped)


def _walk_dir(fd: int, rel: str, rules: list[Rule], depth: int, budget: Budget, dirs: bool, skipped: set | None):
    entries = []
    try:
        with os.scandir(fd) as found:
            for entry in found:
                entries.append(entry)
                if len(entries) >= MAX_DIR_ENTRIES:
                    break
    except OSError:
        return
    if not budget.take(len(entries)):
        return
    entries.sort(key=lambda e: e.name)
    if any(entry.name == ".gitignore" for entry in entries) and len(rules) < MAX_RULES:
        rules = rules + read_gitignore(fd, rel, MAX_RULES - len(rules))
    for entry in entries:
        if not budget.tick():
            return
        name = entry.name
        child = f"{rel}/{name}" if rel else name
        try:
            is_dir = entry.is_dir(follow_symlinks=False)
            is_file = not is_dir and entry.is_file(follow_symlinks=False)
        except OSError:
            continue
        if is_dir:
            if name in SKIP_DIRS or name.endswith(".egg-info"):
                if skipped is not None:
                    skipped.add(name)
                continue
            if rules and ignored(rules, child, name, True):
                continue
            if dirs:
                yield Item(fd, name, child, True, depth, entry)
            if depth + 1 >= MAX_DEPTH:
                continue
            try:
                sub = os.open(name, DIR_FLAGS, dir_fd=fd)
            except OSError:
                continue
            try:
                yield from _walk_dir(sub, child, rules, depth + 1, budget, dirs, skipped)
            finally:
                os.close(sub)
            if budget.stopped:
                return
        elif is_file:
            if rules and ignored(rules, child, name, False):
                continue
            yield Item(fd, name, child, False, depth, entry)


def item_stat(item: Item) -> os.stat_result:
    if item.entry is not None:
        return item.entry.stat(follow_symlinks=False)
    return os.stat(item.name, dir_fd=item.dirfd, follow_symlinks=False)


def skipped_note(skipped: set) -> str:
    if not skipped:
        return ""
    names = sorted(_SHOWN_CONTROLS.sub("?", name) for name in skipped)
    more = f" and {len(names) - 6} more" if len(names) > 6 else ""
    return (f"not searched: {', '.join(names[:6])}{more} (dependencies, build output, caches: name one in path to "
            "search it)")


class Timer:
    """What time_limit yields: FIRED once its own limit (not an enclosing one) stopped the block."""
    fired = False


@contextlib.contextmanager
def time_limit(seconds: float):
    """TimeLimit raised in the block after SECONDS (a timer signal, which also stops a regular expression that
    backtracks without end). Outside the main thread no timer: the walks check the clock themselves."""
    timer = Timer()
    if threading.current_thread() is not threading.main_thread():
        yield timer
        return
    outer, _ = signal.getitimer(signal.ITIMER_REAL)
    if outer and outer <= seconds:
        yield timer  # an enclosing limit ends first: it stays in charge
        return
    started = time.monotonic()

    def fire(signum, frame):
        timer.fired = True
        raise TimeLimit()

    previous = signal.signal(signal.SIGALRM, fire)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield timer
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
        if outer:  # the enclosing limit goes on with what it has left
            signal.setitimer(signal.ITIMER_REAL, max(outer - (time.monotonic() - started), 0.001))


# --- outlines ------------------------------------------------------------------------------------------------------

LANGUAGES = {
    ".py": "python", ".pyi": "python", ".pyw": "python",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".mts": "typescript", ".cts": "typescript",
    ".go": "go", ".rs": "rust", ".java": "java",
    ".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp", ".cxx": "cpp", ".c++": "cpp", ".hpp": "cpp", ".hh": "cpp",
    ".hxx": "cpp", ".h++": "cpp", ".ino": "cpp",
    ".sh": "shell", ".bash": "shell", ".zsh": "shell", ".ksh": "shell", ".bats": "shell",
}
LANGUAGE_NAMES = {"python": "Python", "javascript": "JavaScript", "typescript": "TypeScript", "go": "Go",
                  "rust": "Rust", "java": "Java", "c": "C", "cpp": "C++", "shell": "shell"}
HEADERS = (".h", ".hpp", ".hh", ".hxx", ".h++")
_SHEBANG = re.compile(r"^#!\s*\S*?(?:/env(?:\s+-\S+)*\s+)?\S*?\b(?P<p>python[0-9.]*|bash|sh|zsh|ksh|dash)\b")
#: Kinds that hold others (methods inside), kinds whose inside counts as top level, kinds never shown.
CLASSLIKE = frozenset({"class", "struct", "interface", "trait", "enum", "record", "union", "impl", "object"})
TRANSPARENT = frozenset({"namespace", "module", "extern"})
HIDDEN = frozenset({"extern"})
TYPELIKE = frozenset({"class", "struct", "interface", "trait", "enum", "record", "union", "type"})
CONTAINERS = frozenset({"impl", "namespace", "module", "extern", "const", "var", "macro"})
APPROXIMATE = "approximate: found by line patterns and brace counting, not a compiler"


def language_of(name: str, text: str | None = None) -> str | None:
    """The outline language of a file NAME (by its suffix; a file without one by its #! line in TEXT)."""
    dot = name.rfind(".")
    if dot > 0:
        return LANGUAGES.get(name[dot:].lower())
    if text is None or not text.startswith("#!"):
        return None
    found = _SHEBANG.match(text[:200])
    if not found:
        return None
    return "python" if found.group("p").startswith("python") else "shell"


class Symbol(NamedTuple):
    kind: str              # class, struct, interface, trait, enum, record, union, type, function, method, const,
                           # var, macro, namespace, module, impl
    name: str
    qual: str              # with its containers: App.run
    line: int              # the declaration's line (1-based)
    end: int               # its last line
    top: int               # its first line with decorators, annotations and the comment above it
    depth: int             # containers around it
    sig: str               # the declaration, one line


class Outline(NamedTuple):
    lang: str
    exact: bool
    symbols: tuple
    lines: int
    note: str


def _comments_above(lines: list[str], top: int, markers: tuple[str, ...]) -> int:
    """TOP (1-based) moved up over the comment, decorator or annotation lines right above it (at most 30)."""
    first = top
    while first > 1 and top - first < 30:
        text = lines[first - 2].strip()
        if not text or not text.startswith(markers) or text.startswith("#!"):
            break
        first -= 1
    return first


def _short(text: str, limit: int = MAX_SIGNATURE) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 3] + "..."


_CONSTANT = re.compile(r"^_*[A-Z][A-Z0-9_]*$")


def _name(name: str) -> str:
    """A symbol's name as kept: at most MAX_NAME characters (no one asks for a longer one: arguments take 200)."""
    return name if len(name) <= MAX_NAME else name[:MAX_NAME]


def _qual(parts: list[str]) -> str:
    """The qualified name of PARTS as kept: its end, at most MAX_QUAL characters. Without the bound, one long class
    name repeated in each of 5,000 methods (or classes nested 2,000 deep) took gigabytes."""
    qual = ".".join(parts[-MAX_NESTING:])
    return qual if len(qual) <= MAX_QUAL else "..." + qual[-(MAX_QUAL - 3):]


def outline_python(text: str) -> list[Symbol]:
    """Python's own parser: exact."""
    with warnings.catch_warnings():  # an invalid escape in a string is the file's business, not stderr's
        warnings.simplefilter("ignore")
        tree = ast.parse(text)
    lines = text.split("\n")
    out: list[Symbol] = []
    alias = getattr(ast, "TypeAlias", None)
    try_star = getattr(ast, "TryStar", None)
    blocks = tuple(t for t in (ast.If, ast.Try, try_star, ast.With, ast.AsyncWith) if t is not None)

    def signature(node) -> str:
        first = lines[node.lineno - 1].strip() if node.lineno - 1 < len(lines) else node.name
        try:
            if isinstance(node, ast.ClassDef):
                bases = [ast.unparse(b) for b in node.bases] + [ast.unparse(k) for k in node.keywords]
                return _short(f"class {node.name}" + (f"({', '.join(bases)})" if bases else ""))
            head = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
            returns = f" -> {ast.unparse(node.returns)}" if node.returns is not None else ""
            return _short(f"{head} {node.name}({ast.unparse(node.args)}){returns}")
        except (RecursionError, ValueError, AttributeError):
            return _short(first)

    def visit(body, parents: list[str], depth: int, in_class: bool) -> None:
        for node in body:
            if len(out) >= MAX_SYMBOLS_PER_FILE:
                return
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                is_class = isinstance(node, ast.ClassDef)
                kind = "class" if is_class else "method" if in_class else "function"
                top = min([node.lineno] + [d.lineno for d in node.decorator_list])
                name = _name(node.name)
                out.append(Symbol(kind, name, _qual(parents + [name]), node.lineno,
                                  node.end_lineno or node.lineno, _comments_above(lines, top, ("#",)), depth,
                                  signature(node)))
                if depth < 8:
                    visit(node.body, parents + [name], depth + 1, is_class)
            elif isinstance(node, blocks):
                for field in ("body", "orelse", "finalbody"):
                    visit(getattr(node, field, None) or [], parents, depth, in_class)
                for handler in getattr(node, "handlers", None) or []:
                    visit(handler.body, parents, depth, in_class)
            elif depth == 0 and isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name) and _CONSTANT.match(target.id):
                        name = _name(target.id)
                        out.append(Symbol("const", name, name, node.lineno, node.end_lineno or node.lineno,
                                          node.lineno, 0, _short(lines[node.lineno - 1].strip())))
            elif alias is not None and isinstance(node, alias) and isinstance(node.name, ast.Name):
                out.append(Symbol("type", _name(node.name.id), _qual(parents + [_name(node.name.id)]), node.lineno,
                                  node.end_lineno or node.lineno, node.lineno, depth,
                                  _short(lines[node.lineno - 1].strip())))

    visit(tree.body, [], 0, False)
    return out


_PY_DEF = re.compile(r"^(?P<i>[ \t]*)(?P<a>async[ \t]+)?(?P<k>def|class)[ \t]+(?P<n>[A-Za-z_]\w*)")


def outline_python_lines(text: str) -> list[Symbol]:
    """Python by indentation, for a file Python's parser refuses: approximate."""
    lines = text.split("\n")
    out: list[Symbol] = []
    open_: list[list] = []   # [indent, index in out, qual, is_class]
    last_code = 0

    def close(upto: int) -> None:
        while open_ and open_[-1][0] >= upto:
            _, index, _, _ = open_.pop()
            out[index] = out[index]._replace(end=max(out[index].line, last_code))

    for number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" \t"))
        close(indent)
        found = _PY_DEF.match(line)
        if found and len(out) < MAX_SYMBOLS_PER_FILE:
            is_class = found.group("k") == "class"
            in_class = bool(open_) and open_[-1][3]
            name = _name(found.group("n"))
            qual = _qual([o[2] for o in open_[-1:]] + [name])
            kind = "class" if is_class else "method" if in_class else "function"
            out.append(Symbol(kind, name, qual, number, number, _comments_above(lines, number, ("#", "@")),
                              len(open_), _short(stripped.rstrip(":"))))
            open_.append([indent, len(out) - 1, qual, is_class])
        last_code = number
    close(-1)
    return out


# Brace languages: comments and strings blanked out (same length, line breaks kept), then line patterns.

_LINE_C = r"//[^\n]*"
#: Repeats of an alternation are possessive (*+, Python 3.11+): an ordinary one makes the engine keep about 120 bytes
#: per repetition, 230 MiB for a 2 MiB comment or string; none of these tokens ever needs to give characters back.
_BLOCK_C = r"/\*(?:[^*]|\*(?!/))*+(?:\*/|\Z)"
_DQ = r'"(?:[^"\\\n]|\\.)*+"?'
_SQ = r"'(?:[^'\\\n]|\\.)*+'?"
_JS_REGEX = (r"(?:(?<=[=(,:;!&|?{}\[\n])|(?<![\s\S]))[ \t]*/(?![/*])"
             r"(?:[^/\\\n\[]|\\.|\[(?:[^\]\\\n]|\\.){0,100}\]){1,300}/")
TOKENS = {
    "c": re.compile("|".join([_LINE_C, _BLOCK_C,
                              r'R"(?P<d>[^()\\\s"]{0,16})\((?:[^)]|\)(?!(?P=d)"))*+(?:\)(?P=d)"|\Z)', _DQ, _SQ])),
    "java": re.compile("|".join([_LINE_C, _BLOCK_C, r'"""(?:[^"\\]|\\[\s\S]|"(?!""))*+(?:"""|\Z)', _DQ, _SQ])),
    "go": re.compile("|".join([_LINE_C, _BLOCK_C, r"`[^`]*`?", _DQ, _SQ])),
    "rust": re.compile("|".join([_LINE_C, _BLOCK_C,
                                 r'(?<!\w)b?r(?P<h>#{0,8})"(?:[^"]|"(?!(?P=h)))*+(?:"(?P=h)|\Z)',
                                 r'(?<!\w)b?"(?:[^"\\]|\\[\s\S])*+"?',
                                 r"(?<!\w)b?'(?:[^'\\\n]|\\(?:u\{[0-9a-fA-F]{1,6}\}|x[0-9a-fA-F]{2}|.))'"])),
    "javascript": re.compile("|".join([_LINE_C, _BLOCK_C, r"`(?:[^`\\]|\\[\s\S])*+`?", _DQ, _SQ, _JS_REGEX])),
    "shell": re.compile("|".join([
        r"(?<![^\s;|&()])#[^\n]*", r"\$\{[^}\n]*\}", r"'[^']*'?", r'"(?:[^"\\]|\\[\s\S])*+"?'])),
}
TOKENS["cpp"] = TOKENS["c"]
TOKENS["typescript"] = TOKENS["javascript"]
_NOT_NEWLINE = re.compile(r"[^\n]")
_PREPROCESSOR = re.compile(r"^[ \t]*#(?:[^\n\\]|\\[\s\S])*+", re.M)
_SH_OPEN = re.compile(r"(?<=[^\s;)(&|])\{|\{(?=[^\s;])")
_SH_CLOSE = re.compile(r"(?<=[^\s;&])\}|\}(?=[^\s;)|&<>])")
_BRACE = re.compile(r"[{}]")


def _blank(match) -> str:
    text = match.group()
    inner = _NOT_NEWLINE.sub(" ", text)
    if len(text) >= 2 and text[0] in "\"'`":
        return text[0] + inner[1:-1] + text[-1]
    return inner


_HEREDOC = re.compile(r"(?<!<)<<(?P<tabs>-?)[ \t]*(?P<q>['\"]?)(?P<w>[A-Za-z_]\w*)(?P=q)")


def _blank_heredocs(text: str) -> str:
    """Shell TEXT with the lines of each here-document (cat <<EOF ... EOF) replaced by spaces: one pass, line by
    line (approximate: a << in a string or an arithmetic expression may be taken for one)."""
    out = []
    word, tabs = None, False
    for line in text.split("\n"):
        if word is not None:
            if (line.lstrip("\t") if tabs else line).rstrip() == word:
                word = None
                out.append(line)
            else:
                out.append(" " * len(line))
            continue
        out.append(line)
        found = _HEREDOC.search(line)
        if found and "((" not in line[:found.start()] and "#" not in line[:found.start()]:
            word, tabs = found.group("w"), bool(found.group("tabs"))
    return "\n".join(out)


def clean(text: str, lang: str) -> str:
    """TEXT with comments and string contents replaced by spaces (same length, same lines)."""
    if lang == "shell":
        text = _blank_heredocs(text)
    cleaned = TOKENS[lang].sub(_blank, text)
    if lang in ("c", "cpp"):  # braces of #define and #if lines are not the code's
        cleaned = _PREPROCESSOR.sub(lambda m: m.group().replace("{", " ").replace("}", " "), cleaned)
    elif lang == "shell":     # only { and } that stand as words group commands (not {a,b} or ${x})
        cleaned = "\n".join(_SH_CLOSE.sub(" ", _SH_OPEN.sub(" ", line)) for line in cleaned.split("\n"))
    return cleaned


class _Rule(NamedTuple):
    regex: re.Pattern
    kind: str | None       # None: from the group k
    where: str             # any, top, class, cfunc
    flags: int


BODY = 1          # only with a body
ARROW = 2         # JavaScript: only when the statement has => or function
MACRO = 4         # C: a #define and its continued lines
ANON = 8          # C: typedef struct { ... } NAME;
CTOR = 16         # Java: a constructor (named as its class)
I = r"[A-Za-z_$][\w$]*"


def _r(pattern: str, kind: str | None, where: str, flags: int = 0) -> _Rule:
    return _Rule(re.compile(pattern), kind, where, flags)


_JS_MODS = r"(?:(?:export|default|declare|abstract)\s+)*"
_JS_MEMBER = r"(?:(?:public|private|protected|static|readonly|abstract|override|async|declare|accessor|get|set)\s+)*"
_RS_VIS = r"(?:pub(?:\s*\([^)]{0,100}\))?\s+)?"
_J_ANN = r"(?:@[\w.]+(?:\([^()]{0,200}\))?\s+)*"
_J_MODS = (r"(?:(?:public|protected|private|static|abstract|final|sealed|non-sealed|strictfp|synchronized|native|"
           r"default|transient|volatile)\s+)*")
_C_KEYWORDS = (r"if|for|while|switch|return|else|do|case|sizeof|catch|new|delete|throw|typedef|using|goto|"
               r"static_assert|decltype|alignof|co_return|co_await|co_yield|default|public|private|protected")
RULES = {
    "javascript": (
        _r(rf"^{_JS_MODS}class\s+(?P<n>{I})", "class", "any"),
        _r(rf"^{_JS_MODS}interface\s+(?P<n>{I})", "interface", "any"),
        _r(rf"^{_JS_MODS}(?:const\s+)?enum\s+(?P<n>{I})", "enum", "any"),
        _r(rf"^{_JS_MODS}(?:namespace|module)\s+(?P<n>{I}(?:\.{I})*)\s*\{{", "namespace", "top"),
        _r(rf"^{_JS_MODS}type\s+(?P<n>{I})\s*(?:<[^=]{{0,200}}>)?\s*=", "type", "any"),
        _r(rf"^{_JS_MODS}(?:async\s+)?function\b\s*\*?\s*(?P<n>{I})", "function", "any"),
        _r(rf"^{_JS_MODS}(?:const|let|var)\s+(?P<n>{I})\s*(?::[^=]{{0,200}})?=\s*(?:async\b\s*)?"
           rf"(?:function\b|{I}\s*=>|\()", "function", "any", ARROW),
        _r(r"^(?:export\s+)?const\s+(?P<n>_*[A-Z][A-Z0-9_]*)\b", "const", "top"),
        _r(rf"^{_JS_MEMBER}\*?\s*(?P<n>#?{I})\s*\??\s*(?:<[^()]{{0,200}}>)?\s*\(", "method", "class"),
        _r(rf"^{_JS_MEMBER}(?P<n>#?{I})\s*(?::[^=]{{0,200}})?=\s*(?:async\b\s*)?(?:\(|{I}\s*=>)", "method", "class",
           ARROW),
    ),
    "go": (
        _r(rf"^func\s*\(\s*(?:{I}\s+)?\*?\s*(?P<r>{I})(?:\s*\[[^\]]{{0,100}}\])?\s*\)\s*(?P<n>{I})", "method", "top"),
        _r(rf"^func\s+(?P<n>{I})", "function", "top"),
        _r(rf"^type\s+(?P<n>{I})(?:\s*\[[^\]]{{0,200}}\])?\s+(?P<k>struct|interface)\b", None, "top"),
        _r(rf"^type\s+(?P<n>{I})\b(?!\s*\()", "type", "top"),
        _r(rf"^(?:const|var)\s+(?P<n>{I})\b", "const", "top"),
    ),
    "rust": (
        _r(rf"^{_RS_VIS}(?:default\s+)?(?:const\s+)?(?:async\s+)?(?:unsafe\s+)?(?:extern\s+(?:\"[^\"]*\"\s+)?)?"
           rf"fn\s+(?P<n>{I})", "function", "any"),
        _r(rf"^{_RS_VIS}struct\s+(?P<n>{I})", "struct", "any"),
        _r(rf"^{_RS_VIS}enum\s+(?P<n>{I})", "enum", "any"),
        _r(rf"^{_RS_VIS}union\s+(?P<n>{I})", "union", "any"),
        _r(rf"^{_RS_VIS}(?:unsafe\s+)?(?:auto\s+)?trait\s+(?P<n>{I})", "trait", "any"),
        _r(rf"^{_RS_VIS}type\s+(?P<n>{I})", "type", "any"),
        _r(rf"^{_RS_VIS}mod\s+(?P<n>{I})", "module", "any"),
        _r(rf"^{_RS_VIS}(?:const|static)\s+(?:mut\s+)?(?P<n>{I})\s*:", "const", "any"),
        _r(rf"^macro_rules!\s*(?P<n>{I})", "macro", "any"),
        _r(r"^(?:unsafe\s+)?impl\b(?P<rest>.*)", "impl", "any"),
    ),
    "java": (
        _r(rf"^{_J_ANN}{_J_MODS}(?P<k>class|interface|enum|record|@interface)\s+(?P<n>{I})", None, "any"),
        _r(rf"^{_J_ANN}{_J_MODS}(?:<[^()]{{0,200}}>\s+)?(?P<t>[\w$.]+(?:<[^()]{{0,200}}>)?(?:\[\])*)\s+"
           rf"(?P<n>{I})\s*\(", "method", "class"),
        _r(rf"^{_J_ANN}{_J_MODS}(?:<[^()]{{0,200}}>\s+)?(?P<n>{I})\s*\(", "method", "class", CTOR),
    ),
    "c": (
        _r(r"^#\s*define\s+(?P<n>[A-Za-z_]\w*)", "macro", "any", MACRO),
        _r(rf"^(?:inline\s+)?namespace(?:\s+(?P<n>{I}(?:::{I})*))?\s*(?:\{{|$)", "namespace", "top"),
        _r(r'^extern\s*"[^"]*"\s*(?:\{|$)', "extern", "top"),
        _r(rf"^(?:template\s*<[^;{{]{{0,300}}>\s*)?(?:typedef\s+)?(?P<k>struct|class|union|enum(?:\s+class|\s+struct)?)"
           rf"\s+(?:(?:alignas\s*\([^)]{{0,100}}\)|\[\[[^\]]{{0,100}}\]\]|__attribute__\s*\(\([^)]{{0,200}}\)\)|"
           rf"[A-Z_][A-Z0-9_]*)\s+)*(?P<n>{I})\s*(?:final\b\s*)?(?=$|\{{|:(?!:))", None, "any"),
        _r(r"^typedef\s+(?P<k>struct|union|enum)\b[^;{(]{0,200}\{?\s*$", None, "any", ANON),
        _r(rf"^(?!(?:{_C_KEYWORDS})\b)(?P<pre>[\w:*&<>,~\s\[\]]{{0,300}}?[\s*&>])?"
           rf"(?P<n>~?{I}(?:\s*::\s*~?{I})*|operator\s*(?:\(\)|[^\s(]{{1,3}}))\s*\(", "function", "cfunc", BODY),
    ),
    "shell": (
        _r(r"^function\s+(?P<n>[\w.:@+-]+)\s*(?:\(\s*\))?", "function", "any"),
        _r(r"^(?P<n>[\w.:@+-]+)\s*\(\s*\)", "function", "any"),
    ),
}
RULES["typescript"] = RULES["javascript"]
RULES["cpp"] = RULES["c"]
_JS_NOT_NAMES = frozenset({"if", "for", "while", "switch", "catch", "return", "function", "new", "typeof", "await",
                           "yield", "super", "else", "do", "try", "with", "delete", "void", "throw", "case",
                           "extends", "implements"})
_JAVA_NOT_TYPES = frozenset({"return", "new", "throw", "else", "yield", "case", "assert", "throws"})
_GO_GROUP = re.compile(r"^(?P<g>type|const|var)\s*\(\s*$")
_GO_ITEM = re.compile(rf"^(?P<n>{I})\b(?:\s*\[[^\]]{{0,200}}\])?(?:\s+(?P<k>struct|interface)\b)?")
_TYPEDEF_NAME = re.compile(rf"\}}\s*(?P<n>{I})\s*[;,\[]")
_CONTINUES_AFTER = (",", "=", "(", "|", "&", ":", "+", "=>", "->")
_CONTINUES_BEFORE = {
    "c": ("{", ":", "->", "const", "noexcept", "override", "final", "requires", "throw"),
    "java": ("{", "throws", "extends", "implements", "permits"),
    "rust": ("{", "where", "->"),
    "javascript": ("{", "extends", "implements", ":", "=>", "|", "&"),
    "go": ("{",),
    "shell": ("{",),
}
_CONTINUES_BEFORE["cpp"] = _CONTINUES_BEFORE["c"]
_CONTINUES_BEFORE["typescript"] = _CONTINUES_BEFORE["javascript"]
COMMENT_MARKERS = {"shell": ("#",)}
C_LIKE_MARKERS = ("//", "/*", "*", "#[", "@", "template", "[[")


class _Open(NamedTuple):
    kind: str
    name: str
    close: int             # 0-based line of its closing brace
    body_depth: int
    hidden: bool


def _braces(lines: list[str]) -> tuple[list[int], dict]:
    """(the brace depth at the start of each line, {(line, column) of a '{': (line, column) of its '}'}; an open
    one: the end of the last line)."""
    depth_at = [0] * len(lines)
    close_of: dict[tuple[int, int], tuple[int, int]] = {}
    stack: list[tuple[int, int]] = []
    for i, line in enumerate(lines):
        depth_at[i] = len(stack)
        if "{" not in line and "}" not in line:
            continue
        for found in _BRACE.finditer(line):
            if found.group() == "{":
                stack.append((i, found.start()))
            elif stack:
                close_of[stack.pop()] = (i, found.start())
    for opened in stack:
        close_of[opened] = (len(lines) - 1, len(lines[-1]))
    return depth_at, close_of


def _continues(lines: list[str], j: int, lang: str) -> bool:
    """Whether the declaration on line J goes on in the next line (a signature over lines, a brace on its own)."""
    text = lines[j].rstrip()
    if text.endswith(_CONTINUES_AFTER) or (lang == "rust" and text.split()[-1:] == ["where"]):
        return True
    for k in range(j + 1, min(j + 3, len(lines))):
        text = lines[k].strip()
        if text:
            return text.startswith(_CONTINUES_BEFORE[lang])
    return False


def _body(lines: list[str], i: int, col: int, lang: str) -> tuple[bool, int, int]:
    """(True, line, column) of the '{' that opens the body of the declaration starting at LINES[I][COL:], or (False,
    line, column) where it ends without one (';', a '}' of the block around it, or its last line)."""
    parens = 0
    j, start = i, col
    while j < len(lines) and j < i + 12:
        line = lines[j]
        for k in range(start, min(len(line), start + 600)):
            ch = line[k]
            if ch in "([":
                parens += 1
            elif ch in ")]":
                parens = max(0, parens - 1)
            elif parens == 0:
                if ch == "{":
                    return True, j, k
                if ch in ";}":
                    return False, j, k
        if parens == 0 and not _continues(lines, j, lang):
            return False, j, len(line)
        j, start = j + 1, 0
    j = min(j, len(lines) - 1)
    return False, j, len(lines[j])


def _signature(orig: list[str], i: int, col: int, end_line: int, end_col: int) -> str:
    if end_line == i:
        return _short(orig[i][col:end_col])
    parts = [orig[i][col:]] + [orig[x] for x in range(i + 1, end_line)] + [orig[end_line][:end_col]]
    return _short(" ".join(parts))


def _impl_name(rest: str) -> str:
    """The type an impl block is for: impl<T> Display for Point<T> -> Point."""
    rest = rest.strip()
    if rest.startswith("<"):
        depth = 0
        for k, ch in enumerate(rest):
            depth += {"<": 1, ">": -1}.get(ch, 0)
            if depth == 0:
                rest = rest[k + 1:]
                break
    head = re.split(r"\{|\bwhere\b", rest, maxsplit=1)[0]
    parts = re.split(r"\sfor\s", f" {head} ", maxsplit=1)
    head = parts[1] if len(parts) == 2 else head
    found = re.match(r"\s*(?:&\s*(?:'\w+\s+)?(?:mut\s+)?)?(?:dyn\s+)?([\w:]+)", head)
    return found.group(1).split("::")[-1] if found and found.group(1) else "?"


def _where_ok(where: str, ctx: _Open | None, depth: int) -> bool:
    if where == "any":
        return True
    top = (ctx is None and depth == 0) or (ctx is not None and ctx.kind in TRANSPARENT and depth == ctx.body_depth)
    if where == "top":
        return top
    in_class = ctx is not None and ctx.kind in CLASSLIKE and depth == ctx.body_depth
    return in_class if where == "class" else top or in_class


def outline_braces(text: str, lang: str, header: bool = False) -> list[Symbol]:
    """The declarations of a brace language: approximate."""
    orig = text.split("\n")
    lines = clean(text, lang).split("\n")
    depth_at, close_of = _braces(lines)
    rules = RULES[lang]
    markers = COMMENT_MARKERS.get(lang, C_LIKE_MARKERS)
    out: list[Symbol] = []
    stack: list[_Open] = []
    go_group: str | None = None
    i = 0
    while i < len(lines) and len(out) < MAX_SYMBOLS_PER_FILE:
        while stack and stack[-1].close < i:
            stack.pop()
        line = lines[i]
        stripped = line.lstrip()
        if not stripped:
            i += 1
            continue
        indent = len(line) - len(stripped)
        text_ = stripped[:400]
        depth = depth_at[i]
        ctx = stack[-1] if stack else None
        if lang == "go" and depth == 0 and ctx is None:
            if go_group is None:
                grouped = _GO_GROUP.match(text_)
                if grouped:
                    go_group = grouped.group("g")
                    i += 1
                    continue
            elif text_.startswith(")"):
                go_group = None
                i += 1
                continue
            else:
                item = _GO_ITEM.match(text_)
                if item:
                    kind = item.group("k") or ("type" if go_group == "type" else "const")
                    has_body, bl, bc = _body(lines, i, indent + item.start("n"), lang)
                    end = close_of.get((bl, bc), (bl, 0))[0] if has_body else bl
                    out.append(Symbol(kind, _name(item.group("n")), _name(item.group("n")), i + 1, end + 1,
                                      _comments_above(orig, i + 1, markers), 0,
                                      _signature(orig, i, indent, bl, bc if has_body else len(orig[bl]))))
                    i = end + 1 if has_body else i + 1
                    continue
                i += 1
                continue
        for rule in rules:
            found = rule.regex.match(text_)
            if not found or not _where_ok(rule.where, ctx, depth):
                continue
            kind = rule.kind or found.group("k").split()[0].lstrip("@")
            names = found.groupdict()
            name = names.get("n")
            if rule.flags & CTOR and (ctx is None or name != ctx.name):
                continue
            if lang == "java" and names.get("t") in _JAVA_NOT_TYPES:
                continue
            if lang in ("javascript", "typescript") and name in _JS_NOT_NAMES:
                continue
            if rule.flags & ARROW:
                statement = line[indent + found.start():] + (lines[i + 1] if i + 1 < len(lines) else "")
                if "=>" not in statement and "function" not in statement:
                    continue
            start_col = indent + (found.start("n") if name else found.start())
            if rule.flags & MACRO:
                end = i
                while end + 1 < len(orig) and orig[end].rstrip().endswith("\\") and end - i < 200:
                    end += 1
                has_body, bl, bc = False, i, len(orig[i])
            else:
                has_body, bl, bc = _body(lines, i, start_col, lang)
                end, end_col = close_of.get((bl, bc), (bl, 0)) if has_body else (bl, 0)
            if rule.flags & BODY and not has_body and not (header or (ctx is not None and ctx.kind in CLASSLIKE)):
                continue
            if rule.flags & ANON:
                if not has_body:
                    continue
                named = _TYPEDEF_NAME.match(lines[end], end_col, end_col + 400)  # right after its own '}'
                if not named:
                    continue
                name = named.group("n")
            hidden = kind in HIDDEN or (kind == "namespace" and not name)
            if kind == "impl":
                name = _impl_name(names.get("rest") or "")
            qual_parts = [o.name for o in stack if not o.hidden]
            if name and ("::" in name):
                pieces = [p.strip() for p in name.split("::")]
                name = pieces[-1]
                qual_parts += pieces[:-1]
                if kind == "function":
                    kind = "method"
            if kind == "function" and ctx is not None and ctx.kind in CLASSLIKE:
                kind = "method"
            if names.get("r"):  # a Go method: its receiver's type
                qual_parts = [names["r"]]
            name = _name(name or "")
            if not hidden:
                sig_col = indent
                if lang in ("c", "cpp") and kind in ("function", "method") and not names.get("pre") and i > 0:
                    previous = orig[i - 1].strip()  # GNU style: the return type on the line before
                    if previous and re.match(r"^[\w\s*&:<>,]+$", previous) and not previous.endswith((";", ")")):
                        sig = _short(previous + " " + _signature(orig, i, sig_col, bl, bc))
                    else:
                        sig = _signature(orig, i, sig_col, bl, bc)
                else:
                    sig = _signature(orig, i, sig_col, bl, bc)
                if rule.flags & ANON:
                    sig = _short(f"{sig} {{...}} {name}")
                out.append(Symbol(kind, name, _qual(qual_parts + [name]), i + 1, end + 1,
                                  _comments_above(orig, i + 1, markers), len([o for o in stack if not o.hidden]), sig))
            if has_body and len(stack) < MAX_NESTING:  # deeper ones are not containers: no stack without end
                body_depth = depth_at[bl] + lines[bl][:bc].count("{") - lines[bl][:bc].count("}") + 1
                stack.append(_Open(kind, name, end, body_depth, hidden))
            break
        i += 1
    out.sort(key=lambda s: (s.line, -s.end))
    return out


_PY_TOKEN = re.compile(r"\w+|\S|\n")


def _more_tokens(text: str, limit: int) -> bool:
    """Whether TEXT has more than LIMIT tokens (words, other characters, line ends); stops counting there."""
    for count, _ in enumerate(_PY_TOKEN.finditer(text), start=1):
        if count > limit:
            return True
    return False


def parse_outline(text: str, lang: str, name: str) -> Outline:
    lines = text.count("\n") + 1
    if lang == "python":
        # Python's parser cannot be stopped and takes about 1 KB of memory per token: "x\n" * 1,000,000 (2 MB) took
        # 1.8 GB. A file with more tokens than MAX_PARSE_TOKENS (real code: 400 KB and more) is outlined by indentation.
        if _more_tokens(text, MAX_PARSE_TOKENS):
            return Outline(lang, False, tuple(outline_python_lines(text)), lines,
                           f"approximate: more than {MAX_PARSE_TOKENS:,} tokens for Python's parser, found by "
                           "indentation")
        try:
            return Outline(lang, True, tuple(outline_python(text)), lines, "exact: Python's own parser")
        except (SyntaxError, ValueError, RecursionError, MemoryError, OverflowError):
            return Outline(lang, False, tuple(outline_python_lines(text)), lines,
                           "approximate: Python's parser refused the file (a syntax error?), found by indentation")
    if text.count("{") > MAX_BRACES:  # generated code; matching them all took 300 MB for 2 MiB of braces
        return Outline(lang, False, (), lines, f"not outlined: more than {MAX_BRACES:,} braces (generated code?)")
    return Outline(lang, False, tuple(outline_braces(text, lang, name.lower().endswith(HEADERS))), lines, APPROXIMATE)


#: (root, path) -> (fingerprint, Outline or None): the outline cache, least recently used first.
OUTLINES: dict[tuple[str, str], tuple[tuple, Outline | None]] = {}
CACHED = {"symbols": 0, "parses": 0}
CACHE_LOCK = threading.Lock()


def fingerprint(info: os.stat_result) -> tuple:
    return info.st_mtime_ns, info.st_size, info.st_ino, info.st_ctime_ns


def _remember(key, fp, outline: Outline | None) -> None:
    old = OUTLINES.pop(key, None)
    if old is not None and old[1] is not None:
        CACHED["symbols"] -= len(old[1].symbols)
    OUTLINES[key] = (fp, outline)
    if outline is not None:
        CACHED["symbols"] += len(outline.symbols)
    while len(OUTLINES) > 1 and (len(OUTLINES) > MAX_CACHED_FILES or CACHED["symbols"] > MAX_CACHED_SYMBOLS):
        oldest = next(iter(OUTLINES))
        _, dropped = OUTLINES.pop(oldest)
        if dropped is not None:
            CACHED["symbols"] -= len(dropped.symbols)


def forget(key) -> None:
    old = OUTLINES.pop(key, None)
    if old is not None and old[1] is not None:
        CACHED["symbols"] -= len(old[1].symbols)


def outline_of(root: str, rel: str, dirfd: int, name: str, info: os.stat_result | None = None,
               text: str | None = None) -> Outline | None:
    """The Outline of the file NAME in DIRFD (ROOT/REL), from the cache while its fingerprint is unchanged; None for
    a file without an outline language or one that is not read. TEXT and INFO: the file as just read."""
    if language_of(name) is None and "." in name.lstrip("."):
        return None
    key = (root, rel)
    with CACHE_LOCK:
        if info is None:
            info = os.stat(name, dir_fd=dirfd, follow_symlinks=False)
        fp = fingerprint(info)
        hit = OUTLINES.get(key)
        if hit is not None and hit[0] == fp:
            OUTLINES[key] = OUTLINES.pop(key)
            return hit[1]
        if text is None:
            text, opened, _ = load_text(dirfd, name)
            if text is None:
                forget(key)
                return None
            fp = fingerprint(opened)
        lang = language_of(name, text)
        outline = None
        if lang is not None:
            CACHED["parses"] += 1
            timer = None
            try:
                with time_limit(PARSE_SECONDS) as timer:
                    outline = parse_outline(text, lang, name)
            except TimeLimit:
                if timer is None or not timer.fired:
                    raise  # the call's or the search's limit, not this file's: nothing is remembered
                # A file made to stall an outline is given up once and remembered until it changes; before, every
                # find_definition and project_map reached it again and ran into the call's limit without an answer.
                outline = Outline(lang, False, (), text.count("\n") + 1,
                                  f"not outlined: it took longer than {PARSE_SECONDS:g} s; find_text searches it")
        _remember(key, fp, outline)
        return outline


def enclosing(outline: Outline | None, line: int) -> Symbol | None:
    """The innermost symbol whose lines hold LINE (not the declaration line itself)."""
    if outline is None:
        return None
    best = None
    for symbol in outline.symbols:
        if symbol.line > line:
            break
        if symbol.line < line <= symbol.end and symbol.kind not in ("const", "var", "macro"):
            best = symbol
    return best


_FUNCTION_WORDS = re.compile(r"\b(?:def|fn|func|function)\b")


def label(symbol: Symbol) -> str:
    """The symbol as one line: its declaration, with its kind in front when the declaration does not say it."""
    head = symbol.sig[:60]
    if re.search(rf"\b{symbol.kind}\b", head) or (symbol.kind in ("function", "method") and
                                                   _FUNCTION_WORDS.search(head)):
        return symbol.sig
    return f"{symbol.kind} {symbol.sig}"


def index(scope: Scope, seconds: float) -> tuple[list[tuple[str, Outline]], Budget, set]:
    """(display path, Outline) of every file with an outline language below SCOPE, the walk's Budget, the folders
    not entered. Unchanged files come from the cache; after a complete walk the cache forgets the files of SCOPE
    that are gone."""
    budget = Budget(seconds)
    found: list[tuple[str, Outline]] = []
    seen: set[tuple[str, str]] = set()
    skipped: set[str] = set()
    symbols = 0
    walker = walk(scope, budget, skipped=skipped)
    try:
        for item in walker:
            if item.name.endswith(SKIP_SUFFIXES):
                continue
            if language_of(item.name) is None and "." in item.name.lstrip("."):
                continue
            try:
                info = item_stat(item)
            except OSError:
                continue
            seen.add((scope.root, item.rel))
            outline = outline_of(scope.root, item.rel, item.dirfd, item.name, info)
            if outline is not None:
                found.append((display(scope.root, item.rel.split("/")), outline))
                symbols += len(outline.symbols)
                if len(found) >= MAX_CACHED_FILES or symbols >= MAX_CACHED_SYMBOLS:
                    budget.stopped = (f"one call indexes at most {MAX_CACHED_FILES} files and {MAX_CACHED_SYMBOLS} "
                                      "symbols")
                    break
            if budget.expired():
                break
    finally:
        walker.close()
    if not budget.stopped and scope.file is None:
        prefix = scope.rel + "/" if scope.rel else ""
        with CACHE_LOCK:
            for key in [k for k in OUTLINES if k[0] == scope.root and k[1].startswith(prefix) and k not in seen]:
                forget(key)
    return found, budget, skipped


def index_note(budget: Budget, files: int) -> str:
    if not budget.stopped:
        return ""
    if budget.stopped.startswith("one call indexes"):
        return f"the index is incomplete ({budget.stopped}, {files} files read): narrow it with path"
    return (f"the index is incomplete ({budget.stopped}, {files} files read): call again to go on (unchanged files "
            "are cached) or narrow it with path")


# --- answers -------------------------------------------------------------------------------------------------------

def _cap(text: str) -> str:
    if len(text) <= MAX_ANSWER:
        return text
    cut = text.rfind("\n", 0, MAX_ANSWER - 200)
    return text[:cut if cut > 0 else MAX_ANSWER - 200] + \
        f"\n... (the answer was cut at {MAX_ANSWER} characters: narrow it with path, glob or a longer name)"


def utf8(text: str) -> str:
    """TEXT as it can be sent: a file or link name that is not UTF-8 comes from the file system with surrogate
    escapes (or an argument with lone surrogates), which no JSON answer can carry - each becomes '?'."""
    return text.encode("utf-8", "replace").decode("utf-8")


def answer(work) -> str:
    """WORK()'s text, bounded; a refusal as the tool's error, saying why and what to do instead. Either is UTF-8: a
    lone surrogate in an answer would make the SDK fail to serialize it and end the server."""
    try:
        with time_limit(CALL_SECONDS):
            return utf8(_cap(work()))
    except Refused as exc:
        raise ToolError(utf8(str(exc))) from None
    except TimeLimit:
        raise ToolError(f"this took longer than {CALL_SECONDS:g} s and was stopped: narrow it (path, glob)") from None
    except OSError as exc:
        raise ToolError(f"the file system refused: {exc.strerror or type(exc).__name__}") from None
    except Exception as exc:  # noqa: BLE001 - reported by type, not hidden
        log.error("unexpected %s", type(exc).__name__)
        raise ToolError(f"internal error ({type(exc).__name__})") from None


def _line_shown(line: str, column: int = 0) -> str:
    if _SHOWN_CONTROLS.search(line):
        line = _SHOWN_CONTROLS.sub("?", line)
    line = line.strip() if column == 0 else line
    if column:
        lead = len(line) - len(line.lstrip())
        line, column = line.lstrip(), max(0, column - lead)
    if len(line) <= MAX_LINE_SHOWN:
        return line
    start = max(0, min(column - MAX_LINE_SHOWN // 3, len(line) - MAX_LINE_SHOWN))
    return ("..." if start else "") + line[start:start + MAX_LINE_SHOWN] + "..."


def _size(n: int) -> str:
    if n < 1024:
        return f"{n}B"
    if n < 1 << 20:
        return f"{n / 1024:.1f}K"
    return f"{n / (1 << 20):.1f}M"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "es" if word.endswith(("ch", "s")) else "s")


_NESTED_REPEAT = re.compile(r"\((?:[^()\\]|\\.)*?(?:[*+]|\{\d*,\d*\})(?:[^()\\]|\\.)*\)(?:[*+]|\{\d*,\d*\})")


def matcher(pattern: str, regex: bool, ignore_case: bool) -> re.Pattern:
    flags = re.M | (re.I if ignore_case else 0)
    if not regex:
        return re.compile(re.escape(pattern), flags)
    if _NESTED_REPEAT.search(pattern):
        raise Refused("pattern: a group that repeats inside a repeat, like (a+)+ or (\\w+\\s?)*, can take forever: "
                      "simplify it (like a+ or [\\w\\s]+), or search plain text with regex=false")
    try:
        return re.compile(pattern, flags)
    except (re.error, RecursionError, OverflowError) as exc:
        raise Refused(f"pattern: not a valid regular expression ({exc}); regex=false searches the text as written") \
            from None


def _expand_braces(pattern: str) -> list[str]:
    found = re.search(r"\{([^{}]*)\}", pattern)
    if not found:
        return [pattern]
    return [pattern[:found.start()] + choice + pattern[found.end():] for choice in found.group(1).split(",")][:20]


def file_globs(value, name: str = "glob") -> list[tuple[Glob, bool]]:
    """(regex, matched against the path below the start folder rather than the name) of a glob argument: "*.py",
    "src/**/*.ts", "*.{ts,tsx}", "*.ts, *.tsx"."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return []
    text = _text(value, name, 300, '"*.py"').strip()
    if text.startswith("/"):
        raise Refused(f"{name}: a pattern below the folder searched, like *.py or src/**/*.ts (not an absolute path; "
                      "path names the folder)")
    out = []
    for piece in re.split(r"[\s,]+(?![^{]*\})", text):
        piece = piece.strip().removeprefix("./")
        if not piece:
            continue
        if ".." in piece.split("/"):
            raise Refused(f"{name}: '..' is not allowed")
        for expanded in _expand_braces(piece):
            try:
                out.append((Glob(expanded, ignore_case=True), "/" in expanded))
            except TooManyParts:
                raise Refused(f"{name}: at most {MAX_GLOB_PARTS} folder levels in a pattern (like src/**/*.ts); "
                              "path names the folder to start from") from None
    return out[:40]


def glob_ok(globs, item: Item, scope: Scope) -> bool:
    if not globs:
        return True
    below = item.rel[len(scope.rel) + 1:] if scope.rel else item.rel
    return any(glob.match_path(below) if by_path else glob.match_name(item.name) for glob, by_path in globs)


READS = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)


# --- tools -----------------------------------------------------------------------------------------------------------

@mcp.tool(annotations=READS, structured_output=False)
def find_text(pattern: str, path: str = "", regex: bool = False, ignore_case: bool = False, glob: str = "",
              max_results: int = DEFAULT_RESULTS, offset: int = 0) -> str:
    """Search the project's files for text, line by line; answers file, line number, the line and the function it is
    in. Skips binary files, .gitignore'd files and folders like node_modules or build.

    Args:
        pattern: the text to find, e.g. "parse_args" or "TODO" (a regular expression with regex=true)
        path: folder or file to search, relative to /work (default: the whole project)
        regex: true to read pattern as a Python regular expression
        ignore_case: true to ignore upper/lower case
        glob: only these files, e.g. "*.py", "src/**/*.ts" or "*.{ts,tsx}"
        max_results: matches to show (default 30, at most 200)
        offset: skip this many matches (to see the next ones)
    """
    def work() -> str:
        if not isinstance(pattern, str) or not pattern or len(pattern) > MAX_PATTERN or "\0" in pattern or \
                "\n" in pattern:
            raise Refused(f"pattern: the text to find, one line of at most {MAX_PATTERN} characters")
        found_by = matcher(pattern, _bool(regex, "regex"), _bool(ignore_case, "ignore_case"))
        limit = _int(max_results, "max_results", 1, MAX_RESULTS)
        skip = _int(offset, "offset", 0, MAX_OFFSET)
        globs = file_globs(glob)
        shown: list[tuple[str, int, str, int, Outline | None]] = []
        total = files = searched = 0
        not_read: dict[str, int] = {}
        skipped: set[str] = set()
        stopped = None
        with open_scope(path) as scope:
            budget = Budget(SEARCH_SECONDS)
            walker = walk(scope, budget, skipped=skipped)
            try:
                with time_limit(SEARCH_SECONDS):
                    for item in walker:
                        if scope.file is None and (item.name.endswith(SKIP_SUFFIXES) or
                                                   not glob_ok(globs, item, scope)):
                            continue
                        text, info, why = load_text(item.dirfd, item.name)
                        if text is None:
                            not_read[why] = not_read.get(why, 0) + 1
                            continue
                        searched += 1
                        # The whole file at once only for plain text (a literal: no repeat). A regular expression
                        # is matched line by line, each to MAX_MATCH_LINE characters: the engine looks for the
                        # timer's signal only now and then, and a single repeat (.*x) over a one-line file of
                        # 2 MiB held it off for minutes, far past every limit, with the server blocked.
                        if not regex and not found_by.search(text):
                            continue
                        where = display(scope.root, item.rel.split("/"))
                        outline = None
                        had = False
                        for number, line in enumerate(text.split("\n"), start=1):
                            hit = found_by.search(line, 0, MAX_MATCH_LINE)
                            if not hit:
                                continue
                            if not had:
                                files, had = files + 1, True
                            total += 1
                            if skip < total <= skip + limit:
                                if outline is None:
                                    outline = outline_of(scope.root, item.rel, item.dirfd, item.name, info, text) \
                                        or False
                                shown.append((where, number, line, hit.start(), outline or None))
                            if total >= MAX_COUNT:
                                break
                        if total >= MAX_COUNT:
                            stopped = f"counted {MAX_COUNT} matches"
                            break
            except TimeLimit:
                stopped = f"stopped after {SEARCH_SECONDS:g} s"
            finally:
                walker.close()
            stopped = stopped or (budget.stopped and f"stopped: {budget.stopped}")
            what = f"{pattern!r}" + (" (regular expression)" if regex else "") + \
                (" ignoring case" if ignore_case else "")
            if not total:
                lines = [f"no match for {what} in {_plural(searched, 'file')} searched under {scope.shown}"]
                if not ignore_case:
                    lines.append("try ignore_case=true, a shorter pattern, or find_definition for a name")
                if not regex and re.search(r"\\[wdsbS]|\.[*+]|\(\?|\[\^", pattern):
                    lines.append("the pattern looks like a regular expression: set regex=true")
            else:
                more = "+" if stopped else ""
                lines = [f"{total}{more} matches of {what} in {files}{more} files under {scope.shown}"
                         + (f"; showing {skip + 1}-{skip + len(shown)}" if shown else
                            f"; offset {skip} is past the last one")]
                last = None
                for where, number, line, column, outline in shown:
                    if where != last:
                        lines.append(where)
                        last = where
                    around = enclosing(outline, number)
                    inside = f" (in {around.qual})" if around else ""
                    lines.append(f"  {number}{inside}: {_line_shown(line, column)}")
                rest = total - skip - len(shown)
                if rest > 0:
                    lines.append(f"{rest}{more} more: offset={skip + len(shown)} shows the next ones, or narrow it "
                                 "with path or glob")
            if stopped:
                lines.append(f"the search {stopped}; results may be incomplete: narrow it with path or glob")
            if not_read:
                lines.append("not read: " + ", ".join(f"{n} {NOT_READ.get(why, why)}"
                                                      for why, n in sorted(not_read.items())))
            note = skipped_note(skipped)
            if note:
                lines.append(note)
            return "\n".join(lines)
    return answer(work)


@mcp.tool(annotations=READS, structured_output=False)
def find_files(name_or_glob: str, path: str = "") -> str:
    """Find files and folders by name: part of a name ("config" finds app_config.py) or a glob ("*.test.ts",
    "src/**/models/*.py"). Best matches first, at most 50.

    Args:
        name_or_glob: a name or part of one, or a glob with * ? [ ] and **
        path: folder to search, relative to /work (default: the whole project)
    """
    def work() -> str:
        query = _text(name_or_glob, "name_or_glob", 300, '"config" or "*.py"').strip().removeprefix(WORK + "/")
        globbing = any(c in query for c in "*?[{")
        globs = file_globs(query, "name_or_glob") if globbing else []
        wanted = query.strip("/").removeprefix("./")
        low = wanted.lower()
        hits: list[tuple[int, int, str, bool, int]] = []
        names: dict[str, None] = {}
        count = 0
        skipped: set[str] = set()
        with open_scope(path, folder=True) as scope:
            budget = Budget(SEARCH_SECONDS)
            walker = walk(scope, budget, dirs=True, skipped=skipped)
            for item in walker:
                below = item.rel[len(scope.rel) + 1:] if scope.rel else item.rel
                name = item.name
                rank = None
                if globbing:
                    if any(glob.match_path(below) if by_path else glob.match_name(name) for glob, by_path in globs):
                        rank = 0
                elif "/" in wanted:
                    lower = below.lower()
                    rank = 0 if below == wanted else 1 if lower.endswith("/" + low) or lower == low else \
                        5 if low in lower else None
                else:
                    lower = name.lower()
                    rank = 0 if name == wanted else 1 if lower == low else \
                        2 if lower.split(".")[0] == low else 3 if lower.startswith(low) else \
                        4 if low in lower else None
                if rank is None:
                    if len(names) < 50_000:
                        names.setdefault(name, None)
                    continue
                count += 1
                if len(hits) < MAX_FILE_HITS:
                    try:
                        size = 0 if item.is_dir else item_stat(item).st_size
                    except OSError:
                        size = 0
                    hits.append((rank, below.count("/"), display(scope.root, item.rel.split("/")), item.is_dir, size))
            walker.close()
            hits.sort(key=lambda h: (h[0], h[3], h[1], h[2]))
            if not hits:
                lines = [f"no file or folder named like {query!r} under {scope.shown}"]
                close = difflib.get_close_matches(wanted, list(names)[:20_000], n=6, cutoff=0.6) if not globbing \
                    else []
                if close:
                    lines.append("similar names: " + ", ".join(_SHOWN_CONTROLS.sub("?", c) for c in close))
                elif not globbing:
                    lines.append("try a shorter part of the name, or a glob like *name*")
            else:
                lines = [f"{count}{'+' if budget.stopped else ''} found for {query!r} under {scope.shown}"
                         + (f"; the best {MAX_FILES_FOUND}" if count > MAX_FILES_FOUND else "")]
                for _, _, where, is_dir, size in hits[:MAX_FILES_FOUND]:
                    lines.append(f"{where}/" if is_dir else f"{where}  {_size(size)}")
                if count > MAX_FILES_FOUND:
                    lines.append(f"{count - MAX_FILES_FOUND} more: use a longer name, a glob or path")
            if budget.stopped:
                lines.append(f"the search stopped early ({budget.stopped}): narrow it with path")
            note = skipped_note(skipped)
            if note:
                lines.append(note)
            return "\n".join(lines)
    return answer(work)


def _file_outline(path, name: str = "path") -> tuple[Scope, str, Outline]:
    """(scope of the file, its text, its Outline) of a code file the caller names (the caller closes the scope)."""
    scope = open_scope(path, name)
    try:
        if scope.file is None:
            raise Refused(f"{name}: {scope.shown} is a folder; name a file (project_map shows the files, "
                          "find_definition finds the file of a function or class)")
        text, info, why = load_text(scope.dirfd, scope.file)
        if text is None:
            raise Refused(f"{name}: {scope.shown} is not read: {WHY.get(why, why)}")
        outline = outline_of(scope.root, "/".join(scope.names + [scope.file]), scope.dirfd, scope.file, info, text)
        if outline is None:
            raise Refused(f"{name}: no outline for {scope.shown}: outlines are made for Python, JavaScript, "
                          "TypeScript, Go, Rust, Java, C, C++ and shell files; find_text searches any file")
        return scope, text, outline
    except BaseException:
        scope.close()
        raise


@mcp.tool(annotations=READS, structured_output=False)
def outline(path: str) -> str:
    """List the classes, functions and methods of one file with their line numbers and signatures, without reading
    the whole file. Python is exact; JS/TS, Go, Rust, Java, C/C++ and shell are approximate.

    Args:
        path: the file, relative to /work, e.g. "src/app.py"
    """
    def work() -> str:
        scope, _, found = _file_outline(path)
        with scope:
            # constants and macros of the top level on one line, by name: they would crowd out the functions
            constants = [s for s in found.symbols if s.depth == 0 and s.kind in ("const", "var", "macro")]
            symbols = [s for s in found.symbols if not (s.depth == 0 and s.kind in ("const", "var", "macro"))]
            lines = [f"{scope.shown}: {LANGUAGE_NAMES[found.lang]}, {_plural(len(found.symbols), 'symbol')}, "
                     f"{found.lines} lines ({found.note})"]
            if constants:
                names = ", ".join(f"{s.name} ({s.line})" for s in constants[:40])
                lines.append(f"constants: {names}" + (f" and {len(constants) - 40} more" if len(constants) > 40
                                                      else ""))
            if not found.symbols:
                lines.append("no classes or functions found")
            width = len(str(found.lines))
            for symbol in symbols[:MAX_OUTLINE]:
                where = f"{symbol.line}-{symbol.end}" if symbol.end > symbol.line else str(symbol.line)
                lines.append(f"{where:>{2 * width + 1}}  {'  ' * symbol.depth}{label(symbol)}")
            if len(symbols) > MAX_OUTLINE:
                lines.append(f"{len(symbols) - MAX_OUTLINE} more not shown: find_definition finds one by name")
            if found.symbols:
                lines.append(f'read_symbol(path="{scope.shown}", name="...") shows the source of one')
            return "\n".join(lines)
    return answer(work)


KINDS = {
    "class": TYPELIKE, "type": TYPELIKE, "struct": {"struct", "class", "record"}, "interface": {"interface", "trait"},
    "trait": {"trait", "interface"}, "enum": {"enum"}, "record": {"record"}, "union": {"union"},
    "function": {"function", "method"}, "func": {"function", "method"}, "def": {"function", "method"},
    "fn": {"function", "method"}, "method": {"method"},
    "const": {"const", "var"}, "constant": {"const", "var"}, "variable": {"const", "var"}, "var": {"const", "var"},
    "macro": {"macro"}, "module": {"module", "namespace"}, "namespace": {"module", "namespace"},
}


def _kinds(value) -> frozenset | None:
    if value is None or (isinstance(value, str) and value.strip().lower() in ("", "any", "all")):
        return None
    if not isinstance(value, str) or value.strip().lower() not in KINDS:
        raise Refused("kind: one of class, function, method, type, interface, struct, enum, const, macro, module "
                      "(or empty for any)")
    return frozenset(KINDS[value.strip().lower()])


def _kind_order(kind: str) -> int:
    if kind in TYPELIKE or kind in ("function", "method"):
        return 0
    return 1 if kind in ("const", "var", "macro") else 2


def _is_test(where: str) -> bool:
    return bool(re.search(r"(?:^|/)(?:tests?|__tests__|spec|testdata)(?:/|$)|(?:^|/)test_|_test\.|\.test\.|\.spec\.",
                          where))


def _definition_rank(symbol: Symbol, want: str, qual: str | None) -> int | None:
    """0 exact, 1 another case; None no match. QUAL: a dotted name (App.run) that must end the symbol's."""
    if symbol.kind in ("impl",) or symbol.kind in HIDDEN:
        return None
    if qual is not None:
        if symbol.qual == qual or symbol.qual.endswith("." + qual):
            return 0
        low = qual.lower()
        return 1 if symbol.qual.lower() == low or symbol.qual.lower().endswith("." + low) else None
    if symbol.name == want:
        return 0
    return 1 if symbol.name.lower() == want.lower() else None


@mcp.tool(annotations=READS, structured_output=False)
def find_definition(name: str, kind: str = "", path: str = "") -> str:
    """Find where a function, class, method, type or constant is defined, by its name, across the project.
    Exact matches first. Then read_symbol shows its source.

    Args:
        name: the name, e.g. "parse_args", "UserService" or "UserService.save"
        kind: only this kind: class, function, method, type, const (default: any)
        path: folder to search, relative to /work (default: the whole project)
    """
    def work() -> str:
        want, qual = _symbol_name(name)
        kinds = _kinds(kind)
        with open_scope(path, folder=True) as scope:
            files, budget, skipped = index(scope, INDEX_SECONDS)
            found = []
            for where, outline_ in files:
                for symbol in outline_.symbols:
                    rank = _definition_rank(symbol, want, qual)
                    if rank is None or (kinds is not None and symbol.kind not in kinds):
                        continue
                    found.append((rank, _kind_order(symbol.kind), _is_test(where), where.count("/"), where,
                                  symbol.line, symbol, outline_.exact))
            found.sort(key=lambda f: f[:6])
            lines = []
            if found:
                lines.append(f"{_plural(len(found), 'definition')} of {name.strip()!r} in {len(files)} code files "
                             f"under {scope.shown}" + (f"; the first {MAX_DEFINITIONS}" if len(found) > MAX_DEFINITIONS
                                                       else ""))
                for rank, _, _, _, where, _, symbol, exact in found[:MAX_DEFINITIONS]:
                    lines_ = f"{symbol.line}-{symbol.end}" if symbol.end > symbol.line else f"{symbol.line}"
                    extra = [] if rank == 0 else ["other case"]
                    if not exact:
                        extra.append("approximate")
                    tail = f"  ({', '.join(extra)})" if extra else ""
                    lines.append(f"{where}:{lines_}  {symbol.qual if symbol.qual != symbol.name else ''}"
                                 f"{' - ' if symbol.qual != symbol.name else ''}{label(symbol)}{tail}")
                first = found[0]
                lines.append(f'read_symbol(path="{first[4]}", name="{first[6].qual}") shows its source; '
                             "find_references shows where it is used")
            else:
                lines.append(f"no definition of {name.strip()!r}" + (f" ({kind.strip()})" if kinds else "")
                             + f" in {len(files)} code files under {scope.shown}")
                lines.extend(_similar(files, want, kinds))
                lines.append("find_text searches all text (comments, strings, other files)")
            note = index_note(budget, len(files))
            if note:
                lines.append(note)
            note = skipped_note(skipped)
            if note:
                lines.append(note)
            return "\n".join(lines)
    return answer(work)


def _similar(files: list[tuple[str, Outline]], want: str, kinds) -> list[str]:
    """Lines naming symbols whose names are like WANT: containing it, then close spellings."""
    low = want.lower()
    containing: list[tuple[int, str, str, Symbol]] = []
    names: dict[str, tuple[str, Symbol]] = {}
    for where, outline_ in files:
        for symbol in outline_.symbols:
            if symbol.kind in ("impl",) or symbol.kind in HIDDEN or (kinds is not None and symbol.kind not in kinds):
                continue
            if len(names) < 100_000:
                names.setdefault(symbol.name, (where, symbol))
            if low in symbol.name.lower() and len(containing) < 1000:
                containing.append((len(symbol.name), where, symbol.qual, symbol))
    containing.sort(key=lambda c: (c[0], c[1], c[3].line))
    picked = [(where, symbol) for _, where, _, symbol in containing[:8]]
    if len(picked) < 8:
        for close in difflib.get_close_matches(want, list(names)[:50_000], n=8 - len(picked), cutoff=0.6):
            if all(close != symbol.name for _, symbol in picked):
                picked.append(names[close])
    if not picked:
        return []
    return ["similar names:"] + [f"  {where}:{symbol.line}  {label(symbol)}" for where, symbol in picked]


@mcp.tool(annotations=READS, structured_output=False)
def find_references(name: str, path: str = "") -> str:
    """Find where a name is used: its definitions first, then every line that uses it (whole word, exact case
    first), with the function each use is in. At most 50.

    Args:
        name: the name, e.g. "parse_args" or "UserService.save" (uses are found by the last part)
        path: folder or file to search, relative to /work (default: the whole project)
    """
    def work() -> str:
        want, qual = _symbol_name(name)
        any_case = re.compile(rf"(?<![\w$]){re.escape(want)}(?![\w$])", re.I)
        exact = re.compile(rf"(?<![\w$]){re.escape(want)}(?![\w$])")
        groups: list[list] = [[], [], [], []]   # definitions, uses in code, uses elsewhere, other case
        total = files = 0
        skipped: set[str] = set()
        stopped = None
        with open_scope(path) as scope:
            budget = Budget(SEARCH_SECONDS)
            walker = walk(scope, budget, skipped=skipped)
            try:
                with time_limit(SEARCH_SECONDS):
                    for item in walker:
                        if scope.file is None and item.name.endswith(SKIP_SUFFIXES):
                            continue
                        text, info, _ = load_text(item.dirfd, item.name)
                        if text is None or not any_case.search(text):
                            continue
                        files += 1
                        where = display(scope.root, item.rel.split("/"))
                        found = outline_of(scope.root, item.rel, item.dirfd, item.name, info, text)
                        defined = set()
                        if found is not None:
                            for symbol in found.symbols:
                                rank = _definition_rank(symbol, want, qual)
                                if rank is not None:
                                    groups[0].append((rank, where, symbol.line, label(symbol), None, found))
                                    defined.add(symbol.line)
                        for number, line in enumerate(text.split("\n"), start=1):
                            if number in defined:
                                continue
                            hit = any_case.search(line, 0, MAX_MATCH_LINE)
                            if not hit:
                                continue
                            same = exact.search(line, 0, MAX_MATCH_LINE)
                            group = groups[1 if found is not None else 2] if same else groups[3]
                            group.append((0, where, number, line, (same or hit).start(), found))
                            total += 1
                            if total >= MAX_COLLECT:
                                break
                        if total >= MAX_COLLECT:
                            stopped = f"collected {MAX_COLLECT} uses"
                            break
            except TimeLimit:
                stopped = f"stopped after {SEARCH_SECONDS:g} s"
            finally:
                walker.close()
            stopped = stopped or (budget.stopped and f"stopped: {budget.stopped}")
            groups[0].sort(key=lambda d: (d[0], _is_test(d[1]), d[1], d[2]))
            shown = 0
            lines = [f"{name.strip()!r}: {_plural(len(groups[0]), 'definition')}, "
                     f"{_plural(len(groups[1]) + len(groups[2]), 'use')} (exact case)"
                     + (f", {len(groups[3])} in another case" if groups[3] else "")
                     + f" in {_plural(files, 'file')} under {scope.shown}"]
            remaining: dict[str, int] = {}
            titles = ("definitions:", "uses:", "uses in other files (docs, configs, ...):", "in another case:")
            for index_, (title, group) in enumerate(zip(titles, groups)):
                if not group:
                    continue
                if shown >= MAX_REFERENCES:
                    for entry in group:
                        remaining[entry[1]] = remaining.get(entry[1], 0) + 1
                    continue
                lines.append(title)
                for entry in group:
                    if shown >= MAX_REFERENCES:
                        remaining[entry[1]] = remaining.get(entry[1], 0) + 1
                        continue
                    shown += 1
                    rank, where, number, text_, column, found = entry
                    if index_ == 0:
                        lines.append(f"  {where}:{number}  {text_}" + ("  (other case)" if rank else ""))
                    else:
                        around = enclosing(found, number)
                        inside = f" (in {around.qual})" if around else ""
                        lines.append(f"  {where}:{number}{inside}: {_line_shown(text_, column)}")
            if remaining:
                worst = sorted(remaining.items(), key=lambda r: (-r[1], r[0]))
                listed = ", ".join(f"{where} ({n})" for where, n in worst[:8])
                lines.append(f"{sum(remaining.values())} more not shown: {listed}"
                             + (" ..." if len(worst) > 8 else "") + "; narrow it with path (a folder or one file)")
            if not shown:
                lines.append("not found: find_text with ignore_case=true or a part of the name searches wider")
            if qual:
                lines.append(f"uses are lines with the word {want}; which {want} each one means is not checked")
            if stopped:
                lines.append(f"the search {stopped}; results may be incomplete: narrow it with path")
            note = skipped_note(skipped)
            if note:
                lines.append(note)
            return "\n".join(lines)
    return answer(work)


@mcp.tool(annotations=READS, structured_output=False)
def read_symbol(path: str, name: str) -> str:
    """Read the source of one function, method or class with line numbers, instead of the whole file.

    Args:
        path: the file, relative to /work, e.g. "src/app.py"
        name: the function or class, e.g. "parse_args" or "App.run" (a method with its class)
    """
    def work() -> str:
        want, qual = _symbol_name(name)
        scope, text, found = _file_outline(path)
        with scope:
            full = qual or want
            ranked = []
            for symbol in found.symbols:
                if symbol.kind in HIDDEN:
                    continue
                if symbol.qual == full:
                    rank = 0
                elif symbol.qual.endswith("." + full):
                    rank = 1
                elif qual is None and symbol.name == want:
                    rank = 2
                elif symbol.qual.lower() == full.lower() or symbol.qual.lower().endswith("." + full.lower()):
                    rank = 3
                else:
                    continue
                ranked.append((rank, symbol.kind == "impl", symbol.line, symbol))
            if not ranked:
                names = list(dict.fromkeys(s.qual for s in found.symbols if s.kind not in HIDDEN))
                close = difflib.get_close_matches(full, names, n=5, cutoff=0.5)
                hint = f"; similar: {', '.join(close)}" if close else ""
                shown_names = ", ".join(names[:40]) + (" ..." if len(names) > 40 else "")
                raise Refused(f"name: no {full} in {scope.shown}{hint}. It has: {shown_names or 'no symbols'}")
            ranked.sort(key=lambda r: r[:3])
            symbol = ranked[0][3]
            lines_ = text.split("\n")
            first, last = symbol.top, min(symbol.end, len(lines_))
            width = len(str(last))
            note = "" if found.exact else f"; {APPROXIMATE}: check where it ends"
            out = [f"{scope.shown}:{first}-{last}  {symbol.kind} {symbol.qual} "
                   f"({LANGUAGE_NAMES[found.lang]}{note})"]
            stop = min(last, first + MAX_SYMBOL_LINES - 1)
            for number in range(first, stop + 1):
                line = lines_[number - 1]
                if _SHOWN_CONTROLS.search(line):
                    line = _SHOWN_CONTROLS.sub("?", line)
                if len(line) > MAX_SOURCE_LINE:
                    line = line[:MAX_SOURCE_LINE] + " ..."
                out.append(f"{number:>{width}}| {line}")
            if stop < last:
                inner = [s for s in found.symbols if s.line > stop and s.end <= last and s.depth == symbol.depth + 1]
                parts = ", ".join(s.qual for s in inner[:12])
                out.append(f"... lines {stop + 1}-{last} not shown ({last - first + 1} lines in all)"
                           + (f"; read_symbol with name {parts} shows one" if parts else
                              "; outline lists its parts"))
            others = [r[3] for r in ranked[1:6]]
            if others:
                out.append("also matching: " + ", ".join(f"{s.qual} ({s.kind}, line {s.line})" for s in others)
                           + " - name it as shown")
            return "\n".join(out)
    return answer(work)


class _Folder:
    __slots__ = ("files", "dirs", "count")

    def __init__(self) -> None:
        self.files: list[tuple[str, int, str]] = []
        self.dirs: list[str] = []
        self.count = 0


def _top_names(found: Outline | None) -> str:
    """The names of a file's top-level classes and functions (those directly in a namespace or module count)."""
    if found is None:
        return ""
    spaces = {s.qual for s in found.symbols if s.kind in ("namespace", "module")}
    names = list(dict.fromkeys(s.name for s in found.symbols if s.kind not in CONTAINERS and s.name and (
        s.depth == 0 or s.qual.rpartition(".")[0] in spaces)))
    return ", ".join(names[:6]) + (f" +{len(names) - 6}" if len(names) > 6 else "")


@mcp.tool(annotations=READS, structured_output=False)
def project_map(depth: int = 2, path: str = "") -> str:
    """Show the project as a compact tree: folders with their file counts, files with their size and main classes
    and functions. Start here to get an overview.

    Args:
        depth: folder levels to show (1-6, default 2)
        path: folder to show, relative to /work (default: the whole project)
    """
    def work() -> str:
        levels = _int(depth, "depth", 1, 6)
        skipped: set[str] = set()
        folders: dict[str, _Folder] = {"": _Folder()}
        files = dirs = 0
        with open_scope(path, folder=True) as scope:
            budget = Budget(INDEX_SECONDS)
            symbols_until = time.monotonic() + MAP_SYMBOL_SECONDS
            symbols_cut = False
            base = len(scope.names)
            walker = walk(scope, budget, dirs=True, skipped=skipped)
            for item in walker:
                local = item.rel.split("/")[base:]
                parent = "/".join(local[:-1])
                if item.is_dir:
                    dirs += 1
                    if len(local) <= levels:
                        folders["/".join(local)] = _Folder()
                        folders[parent].dirs.append(local[-1])
                    continue
                files += 1
                for k in range(min(len(local) - 1, levels) + 1):
                    folders["/".join(local[:k])].count += 1
                if len(local) > levels:
                    continue
                try:
                    info = item_stat(item)
                except OSError:
                    continue
                names = ""
                if not item.name.endswith(SKIP_SUFFIXES) and (language_of(item.name) is not None or
                                                              "." not in item.name.lstrip(".")):
                    if time.monotonic() < symbols_until:
                        names = _top_names(outline_of(scope.root, item.rel, item.dirfd, item.name, info))
                    else:
                        symbols_cut = True
                folders[parent].files.append((local[-1], info.st_size, names))
            walker.close()
            lines = [f"{scope.shown}: {_plural(files, 'file')} in {_plural(dirs, 'folder')}"
                     + (f" (counting stopped: {budget.stopped})" if budget.stopped else "")
                     + "; after a file: its size and main classes/functions (Python exact, others approximate)"]
            cut = False

            def render(local: str, indent: int) -> None:
                nonlocal cut
                folder = folders[local]
                for name in folder.dirs:
                    if len(lines) >= MAX_MAP_LINES:
                        cut = True
                        return
                    child = f"{local}/{name}" if local else name
                    inner = folders.get(child)
                    lines.append(f"{'  ' * indent}{_SHOWN_CONTROLS.sub('?', name)}/  "
                                 f"({_plural(inner.count if inner else 0, 'file')})")
                    if inner is not None and child.count("/") + 1 < levels:
                        render(child, indent + 1)
                for name, size, names in folder.files[:MAX_MAP_FILES]:
                    if len(lines) >= MAX_MAP_LINES:
                        cut = True
                        return
                    lines.append(f"{'  ' * indent}{_SHOWN_CONTROLS.sub('?', name)}  {_size(size)}"
                                 + (f"  {names}" if names else ""))
                if len(folder.files) > MAX_MAP_FILES and len(lines) < MAX_MAP_LINES:
                    lines.append(f"{'  ' * indent}... {len(folder.files) - MAX_MAP_FILES} more files "
                                 "(find_files or project_map with this folder as path)")

            render("", 0)
            if cut:
                lines.append(f"... the map was cut at {MAX_MAP_LINES} lines: give a folder as path, or a smaller depth")
            if symbols_cut:
                lines.append(f"some files are shown without their classes/functions (more than "
                             f"{MAP_SYMBOL_SECONDS:g} s): outline shows those of one file")
            note = skipped_note(skipped)
            if note:
                lines.append(note.replace("not searched", "not shown"))
            return "\n".join(lines)
    return answer(work)


if __name__ == "__main__":
    # An exception nobody caught would print its traceback (with paths) to stderr: its type only.
    sys.excepthook = lambda kind, value, tb: log.error("fatal %s", kind.__name__)
    mcp.run("stdio")
