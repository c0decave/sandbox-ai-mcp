#!/usr/bin/env python3
"""exec MCP server (sandbox-ai-mcp): shell commands in the project folder for agents on small local models that lose
themselves in a raw shell - a command that waits for input, never ends, or floods the context with output.

Tools:
    - run_command: one bash command in /work, with a time limit, no input, its output shortened to start and end
    - start_job, job_status, stop_job, list_jobs: long builds and servers in the background
    - run_tests: pytest, unittest, jest, vitest, go test or cargo test, only the failures returned
    - lint: pyflakes, shellcheck, JSON and YAML checks (read-only: no code of the project runs)

Every command runs as `bash -c` in its own session and process group, with stdin /dev/null, no terminal, a fixed
environment (CI=1, TERM=dumb, PAGER=cat, EDITOR=true, the yes-switches of apt, pip and npm; nothing of the server's
own environment unless EXEC_ENV_ALLOW names it) and a time limit; on the limit or stop_job, the whole process group,
its session and every descendant get SIGTERM, then SIGKILL. Output (stdout and stderr together) is read into memory,
at most the first 64 KiB and the last 256 KiB of each command (the rest is counted, never stored), and shown as its
first and last lines with an "N lines omitted" marker; ANSI colours and progress-bar redraws are removed. The start
folder must be inside /work (symbolic links resolved). No network is needed or used: the container has none.

This is not a way out of anything: the agent already has a shell of its own. The commands run in this server's
container (read-only root, no capabilities, only /work mounted, no network), with this image's tools.
"""

from __future__ import annotations

import asyncio
import ctypes
import functools
import itertools
import json
import os
import re
import selectors
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import xml.etree.ElementTree as ElementTree

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

#: The project folder (mounted writable); every start folder must lie inside it.
WORKSPACE = "/work"
#: Whether WORKSPACE must be a mount point (the image's own /work is an empty folder of the read-only root).
MOUNT_REQUIRED = True
SHELL = "/bin/bash"
COMMAND_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
#: The command runs inside this wrapper: it asks the kernel to kill it (not the server) first when memory runs out.
WRAPPER = 'echo 1000 > /proc/self/oom_score_adj 2>/dev/null; exec "$0" -c "$1"'

#: The environment of every command: never interactive, never coloured, never paged.
BASE_ENV = {
    "PATH": COMMAND_PATH, "HOME": "/tmp", "TMPDIR": "/tmp", "XDG_CACHE_HOME": "/tmp/.cache",
    "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TERM": "dumb", "COLUMNS": "120", "NO_COLOR": "1", "CI": "1",
    "PAGER": "cat", "GIT_PAGER": "cat", "MANPAGER": "cat", "SYSTEMD_PAGER": "cat",
    "EDITOR": "true", "VISUAL": "true", "GIT_EDITOR": "true", "GIT_SEQUENCE_EDITOR": "true",
    "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "/bin/false", "SSH_ASKPASS": "/bin/false",
    "GIT_SSH_COMMAND": "ssh -o BatchMode=yes",
    "DEBIAN_FRONTEND": "noninteractive", "PIP_NO_INPUT": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1",
    "npm_config_yes": "true", "npm_config_fund": "false", "npm_config_audit": "false",
    "npm_config_update_notifier": "false", "PYTHONUNBUFFERED": "1", "PYTHONDONTWRITEBYTECODE": "1",
    "CARGO_TERM_COLOR": "never", "PY_COLORS": "0",
}

HEAD_BYTES = 64 << 10           # kept of the start of a command's output
TAIL_BYTES = 256 << 10          # kept of its end; what lies between is counted, never stored
OUTPUT_LINES = 100              # lines of output shown (EXEC_OUTPUT_LINES): a quarter of the start, the rest of the end
MAX_LINE = 400                  # characters of one line shown
MAX_ANSWER = 16000              # characters of one answer at most (EXEC_OUTPUT_LINES raises it: 160 per line)
MAX_COMMAND = 16384             # characters of a command
GRACE = 2.0                     # seconds between SIGTERM and SIGKILL
EOF_GRACE = 2.0                 # seconds the output may stay open after the shell ended (a background child)
FINISHED_KEPT = 16              # ended jobs remembered for job_status
MAX_WAIT = 300                  # seconds job_status waits at most
MAX_FAILURES = 15               # failures run_tests details
FAILURE_LINES = 25              # lines of one failure's detail
MAX_PROBLEMS = 200              # problems lint lists
MAX_LINT_FILES = 2000           # files lint checks
MAX_WALK = 20000                # entries lint looks at
MAX_FILE_BYTES = 2 << 20        # a JSON or YAML file larger than this is not parsed
SKIP_DIRS = {".git", ".hg", ".svn", "node_modules", ".venv", "venv", "__pycache__", ".tox", ".nox", ".mypy_cache",
             ".pytest_cache", ".ruff_cache", "dist", "build", "target", ".tasks", ".cache", ".idea", ".gradle"}

ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[@-Z\\-_])")
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
PROMPT = re.compile(r"(\[[yYnN]/[yYnN]\]|\([yYnN]/[yYnN]\)|\(yes/no[^)]*\)|password|passphrase|press (any key|enter)"
                    r"|continue\?|proceed\?|[?:>]\s*$)", re.I)
WATCHERS = re.compile(r"(--watch\b|^\s*watch\b|\btail -[fF]\b|\bserve\b|\brun dev\b|\b(?:npm|yarn|pnpm) start\b|"
                      r"http\.server|runserver|\bnodemon\b|\bflask run\b|\buvicorn\b|\bgunicorn\b)")


class ArgumentError(ValueError):
    """A tool argument or a setting that is not accepted; the text says why and what to do."""


# --- settings -------------------------------------------------------------------------------------------------------

def setting(name: str, default: int, low: int, high: int) -> int:
    """The number of the environment variable NAME (DEFAULT when unset), between LOW and HIGH."""
    text = os.environ.get(name, "").strip()
    if not text:
        return default
    if not text.isdigit() or not low <= int(text) <= high:
        raise ArgumentError(f"{name}: a whole number from {low} to {high} (the server's setting), not {text[:20]!r}")
    return int(text)


def max_timeout() -> int:
    return setting("EXEC_MAX_TIMEOUT", 600, 1, 86400)


def default_timeout() -> int:
    return min(setting("EXEC_TIMEOUT", 120, 1, 86400), max_timeout())


def job_timeout() -> int:
    return setting("EXEC_JOB_TIMEOUT", 3600, 1, 7 * 86400)


def max_jobs() -> int:
    return setting("EXEC_MAX_JOBS", 4, 1, 32)


def output_budget() -> tuple[int, int, int]:
    """(lines shown of the start, lines shown of the end, characters at most) of one answer."""
    lines = setting("EXEC_OUTPUT_LINES", OUTPUT_LINES, 20, 2000)
    return lines // 4, lines - lines // 4, max(MAX_ANSWER, lines * 160)


def timeout_of(value, default: int | None = None) -> int:
    """The time limit of a call: VALUE seconds (1 to EXEC_MAX_TIMEOUT), or the default."""
    limit = max_timeout()
    if value is None or value == 0:
        return min(default or default_timeout(), limit)
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= limit:
        raise ArgumentError(f"timeout_seconds: a whole number of seconds from 1 to {limit} (EXEC_MAX_TIMEOUT); "
                            "for anything longer use start_job")
    return value


def command_env() -> dict:
    """BASE_ENV, and the server's own variables EXEC_ENV_ALLOW names (comma or space separated)."""
    env = {**BASE_ENV, "PATH": COMMAND_PATH}
    for name in re.split(r"[,\s]+", os.environ.get("EXEC_ENV_ALLOW", "").strip()):
        if not name:
            continue
        if not ENV_NAME.match(name):
            raise ArgumentError(f"EXEC_ENV_ALLOW: {name[:40]!r} is not a variable name")
        if name in os.environ:
            env[name] = os.environ[name]
    return env


# --- paths: inside /work only ---------------------------------------------------------------------------------------

def workspace_root() -> str:
    root = os.path.realpath(WORKSPACE)
    if not os.path.isdir(root) or (MOUNT_REQUIRED and not os.path.ismount(WORKSPACE)):
        raise ArgumentError(f"no folder is mounted at {WORKSPACE}: add the server with --mount "
                            f"{WORKSPACE}=PROJECT:rw (the project folder)")
    return root


def inside(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip("/") + "/")


def workspace_path(value, what: str = "cwd", *, folder: bool = True) -> str:
    """The absolute, resolved path of VALUE (relative to /work, or absolute below it); ArgumentError unless it lies
    inside /work after every symbolic link is resolved, exists, and is a folder (FOLDER) or a folder or file."""
    root = workspace_root()
    text = "" if value is None else value
    if not isinstance(text, str) or len(text) > 4096 or any(ord(c) < 32 or c == "\x7f" for c in text):
        raise ArgumentError(f"{what}: a path inside {WORKSPACE}")
    text = text.strip()
    joined = os.path.normpath(os.path.join(WORKSPACE, text)) if text else WORKSPACE
    if not inside(joined, os.path.normpath(WORKSPACE)):
        raise ArgumentError(f"{what}: {text!r} is outside {WORKSPACE}; give a folder inside it, e.g. '.' or 'src'")
    resolved = os.path.realpath(joined)
    if not inside(resolved, root):
        raise ArgumentError(f"{what}: {text!r} leads outside {WORKSPACE} through a symbolic link")
    if not os.path.exists(resolved):
        raise ArgumentError(f"{what}: {text!r} does not exist in {WORKSPACE}")
    if folder and not os.path.isdir(resolved):
        raise ArgumentError(f"{what}: {text!r} is not a folder")
    return resolved


def shown(path: str) -> str:
    """PATH as the model sees it: relative to /work ('.' for /work itself)."""
    root = os.path.realpath(WORKSPACE)
    if inside(path, root):
        rest = path[len(root):].lstrip("/")
        return rest or "."
    return path


# --- output: the start and the end, the middle counted --------------------------------------------------------------

def clean(line: str) -> str:
    """One line as a terminal would end up showing it: no colours, only the last redraw of a progress bar, no control
    characters, at most MAX_LINE characters."""
    line = ANSI.sub("", line)
    if "\r" in line:
        parts = [p for p in line.split("\r") if p.strip()]
        line = parts[-1] if parts else ""
    line = CONTROL.sub("", line).replace("\t", "    ").rstrip()
    if len(line) > MAX_LINE:
        line = line[:MAX_LINE] + f" [... {len(line) - MAX_LINE} more characters]"
    return line


def collapse(lines: list[str]) -> list[str]:
    """Runs of more than three equal lines as the line and a count."""
    out: list[str] = []
    index = 0
    while index < len(lines):
        end = index
        while end + 1 < len(lines) and lines[end + 1] == lines[index]:
            end += 1
        count = end - index + 1
        if count > 3:
            out += [lines[index], f"[... the line above {count - 1} more times]"]
        else:
            out += lines[index:end + 1]
        index = end + 1
    return out


class Output:
    """A command's output: the first HEAD_BYTES and the last TAIL_BYTES kept, every byte and line counted."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.head = bytearray()
        self.tail = bytearray()
        self.total = 0
        self.newlines = 0
        self.trimmed = False
        self.last = b""

    def feed(self, chunk: bytes) -> None:
        with self.lock:
            self.total += len(chunk)
            self.newlines += chunk.count(b"\n")
            self.last = chunk[-1:]
            room = HEAD_BYTES - len(self.head)
            if room > 0:
                self.head += chunk[:room]
                chunk = chunk[room:]
            if chunk:
                self.tail += chunk
                if len(self.tail) > TAIL_BYTES:
                    del self.tail[:len(self.tail) - TAIL_BYTES]
                    self.trimmed = True

    def lines(self) -> tuple[list[str], list[str] | None, int]:
        """(first lines, last lines or None when the first are all of it, number of lines in all)."""
        with self.lock:
            total = self.newlines + (1 if self.total and self.last != b"\n" else 0)
            if not self.trimmed:
                text = bytes(self.head + self.tail).decode("utf-8", "replace")
                every = text.split("\n")
                if text.endswith("\n"):
                    every.pop()
                return [clean(line) for line in every], None, total
            head = bytes(self.head).decode("utf-8", "replace").split("\n")
            tail = bytes(self.tail).decode("utf-8", "replace").split("\n")[1:]    # the first one began earlier
            if tail and tail[-1] == "":
                tail.pop()
            runs_on = head.pop()                                                   # the last one runs on
            cleaned = [clean(line) for line in head]
            if runs_on.strip():
                cleaned.append(clean(runs_on) + " [... the line goes on]")
            return cleaned, [clean(line) for line in tail], total

    def raw(self) -> str:
        """What is kept, uncleaned, for a parser: all of it, or the start and the end around a line break."""
        with self.lock:
            if not self.trimmed:
                return bytes(self.head + self.tail).decode("utf-8", "replace")
            return bytes(self.head).decode("utf-8", "replace") + "\n" + bytes(self.tail).decode("utf-8", "replace")

    def render(self, first: int, last: int, limit: int = MAX_ANSWER) -> tuple[str, int, int]:
        """(text, number of lines, number of lines omitted): the first FIRST and the last LAST lines, at most LIMIT
        characters."""
        head, tail, total = self.lines()
        if tail is None:
            if len(head) <= first + last:
                shown_head, shown_tail = head, []
            else:
                shown_head, shown_tail = head[:first], head[-last:] if last else []
        else:
            shown_head, shown_tail = head[:first], tail[-last:] if last else []
        omitted = max(0, total - len(shown_head) - len(shown_tail))
        while True:
            parts = collapse(shown_head)
            if omitted:
                parts.append(f"[... {omitted} lines omitted ...]")
            parts += collapse(shown_tail)
            text = "\n".join(parts)
            if len(text) <= limit or (not shown_head and not shown_tail):
                return text[:limit], total, omitted
            # too long for one answer: give up lines next to the gap, of the start first
            if len(shown_head) > len(shown_tail) // 3 and shown_head:
                shown_head = shown_head[:-1]
            else:
                shown_tail = shown_tail[1:]
            omitted += 1

    def last_lines(self, count: int) -> tuple[str, int]:
        """(the last COUNT lines, number of lines in all)."""
        head, tail, total = self.lines()
        lines = (head if tail is None else tail)[-count:] if count else []
        text = "\n".join(collapse(lines))
        return text[-MAX_ANSWER:], total


# --- processes: a session of their own, killed as a whole -----------------------------------------------------------

def proc_table() -> dict[int, tuple[int, int, int, str]]:
    """{pid: (ppid, process group, session, state)} of every process this server can see (Linux /proc)."""
    table = {}
    try:
        names = os.listdir("/proc")
    except OSError:
        return table
    for name in names:
        if not name.isdigit():
            continue
        try:
            with open(f"/proc/{name}/stat", "rb") as handle:
                data = handle.read().decode("ascii", "replace")
        except OSError:
            continue
        fields = data[data.rfind(")") + 2:].split()
        if len(fields) >= 4:
            table[int(name)] = (int(fields[1]), int(fields[2]), int(fields[3]), fields[0])
    return table


def members(leader: int) -> set[int]:
    """The processes of a command whose shell is LEADER: its session, its process group, and every descendant (also
    one that started a session of its own), never this server. Zombies are left out: they are gone already."""
    table = proc_table()
    found = {pid for pid, (_, group, session, _) in table.items() if session == leader or group == leader}
    found.add(leader)
    children: dict[int, list[int]] = {}
    for pid, (parent, _, _, _) in table.items():
        children.setdefault(parent, []).append(pid)
    queue = list(found)
    while queue:
        for child in children.get(queue.pop(), []):
            if child not in found:
                found.add(child)
                queue.append(child)
    me = os.getpid()
    return {pid for pid in found if pid != me and pid in table and table[pid][3] != "Z"}


class Command:
    """One command: started at once, its output read by a thread, ended by run_to_end (in a thread)."""

    def __init__(self, command: str, cwd: str, limit: int) -> None:
        self.command, self.cwd, self.limit = command, cwd, limit
        self.output = Output()
        self.started = time.monotonic()
        self.ended: float | None = None
        self.timed_out = self.stopped = self.leftover = False
        self.done = threading.Event()
        self.eof = threading.Event()
        self.stop_reading = threading.Event()
        self.popen = subprocess.Popen(
            [SHELL, "-c", WRAPPER, SHELL, command], cwd=cwd, env=command_env(), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True, close_fds=True)
        self.reader = threading.Thread(target=self._read, name=f"exec-read-{self.popen.pid}", daemon=True)
        self.reader.start()

    def _read(self) -> None:
        stream = self.popen.stdout
        selector = selectors.DefaultSelector()
        selector.register(stream, selectors.EVENT_READ)
        try:
            while not self.stop_reading.is_set():
                if not selector.select(0.2):
                    continue
                chunk = os.read(stream.fileno(), 65536)
                if not chunk:
                    break
                self.output.feed(chunk)
        except OSError:
            pass
        finally:
            selector.close()
            stream.close()
            self.eof.set()

    def run_to_end(self) -> None:
        """Wait until the command ends or its time is up (then stop it), and until its output is closed."""
        try:
            try:
                self.popen.wait(timeout=max(0.0, self.started + self.limit - time.monotonic()))
            except subprocess.TimeoutExpired:
                if not self.stopped:
                    self.timed_out = True
                self.kill()
            if not self.eof.wait(EOF_GRACE):
                # the shell ended, a process it left in the background still holds the output: it goes too
                self.leftover = True
                self.kill()
                if not self.eof.wait(GRACE):
                    self.stop_reading.set()
                    self.eof.wait(1.0)
        finally:
            self.ended = time.monotonic()
            self.done.set()

    def kill(self) -> None:
        """SIGTERM to every process of the command, SIGKILL after GRACE seconds to what is left."""
        leader = self.popen.pid
        for sig, wait in ((signal.SIGTERM, GRACE), (signal.SIGKILL, GRACE)):
            targets = members(leader) - ({leader} if self.popen.poll() is not None else set())
            if not targets and self.popen.poll() is not None:
                break
            try:
                os.killpg(leader, sig)
            except (ProcessLookupError, PermissionError):
                pass
            for pid in targets:
                try:
                    os.kill(pid, sig)
                except (ProcessLookupError, PermissionError):
                    pass
            deadline = time.monotonic() + wait
            while time.monotonic() < deadline:
                if self.popen.poll() is not None and not (members(leader) - {leader}):
                    return
                time.sleep(0.05)
        try:
            self.popen.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            pass

    def stop(self) -> None:
        self.stopped = True
        self.kill()

    def seconds(self) -> float:
        return (self.ended or time.monotonic()) - self.started


def duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f} s"
    minutes, rest = divmod(int(seconds), 60)
    if minutes < 60:
        return f"{minutes} min {rest} s"
    return f"{minutes // 60} h {minutes % 60} min"


def ending(command: Command) -> str:
    """How COMMAND ended, for the model."""
    code = command.popen.returncode
    if command.timed_out:
        return f"TIMED OUT after {duration(command.limit)}: stopped, with every process it started"
    if command.stopped:
        return "stopped by stop_job"
    if code is None:
        return "still running"
    if code < 0 or 128 < code <= 128 + 64:
        number = -code if code < 0 else code - 128
        try:
            name = signal.Signals(number).name
        except ValueError:
            name = f"signal {number}"
        hint = " - out of memory?" if number == signal.SIGKILL else ""
        return f"killed by {name}{hint}" + (f" (exit {code})" if code > 0 else "")
    return f"exit {code}" + ("" if code == 0 else " (failed)")


def hints(command: Command, text: str) -> list[str]:
    notes = []
    if command.timed_out:
        last = next((line for line in reversed(text.splitlines()) if line.strip()), "")
        if PROMPT.search(last):
            notes.append("It seems to wait for an answer: stdin is empty here. Use the program's non-interactive "
                         "switch (--yes, -y, --non-interactive, --no-input) or pipe the answer in (yes | ...).")
        if WATCHERS.search(command.command):
            notes.append("A server or watcher never ends by itself: run it with start_job, then job_status.")
        notes.append(f"If it just needs longer: timeout_seconds up to {max_timeout()}, or start_job for anything "
                     "longer.")
    if command.leftover:
        notes.append("It left processes running in the background; they were stopped when it ended. Use start_job "
                     "for something that should keep running.")
    return notes


def report(command: Command) -> str:
    text, total, omitted = command.output.render(*output_budget())
    head = f"{ending(command)} · {duration(command.seconds())}"
    if shown(command.cwd) != ".":
        head += f" · in {shown(command.cwd)}"
    if omitted:
        head += f" · {total} lines of output, the first and last shown"
    body = text if text.strip() else "(no output)"
    notes = hints(command, text)
    return "\n".join([head, body] + [f"Note: {note}" for note in notes])


# --- jobs ------------------------------------------------------------------------------------------------------------

class Jobs:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.jobs: dict[int, Command] = {}
        self.ids = itertools.count(1)
        self.running_foreground = 0

    def running(self) -> list[int]:
        return [ident for ident, job in self.jobs.items() if not job.done.is_set()]

    def start(self, command: str, cwd: str) -> tuple[int, Command]:
        with self.lock:
            busy = len(self.running())
            if busy >= max_jobs():
                raise ArgumentError(f"{busy} jobs are running, the most this server runs at once (EXEC_MAX_JOBS): "
                                    "stop one with stop_job, or wait for one with job_status")
            job = Command(command, cwd, job_timeout())
            ident = next(self.ids)
            self.jobs[ident] = job
            ended = [i for i, j in self.jobs.items() if j.done.is_set()]
            for old in ended[:max(0, len(ended) - FINISHED_KEPT)]:
                del self.jobs[old]
        threading.Thread(target=job.run_to_end, name=f"exec-job-{ident}", daemon=True).start()
        return ident, job

    def get(self, ident) -> Command:
        if isinstance(ident, bool) or not isinstance(ident, int):
            raise ArgumentError("job_id: the number start_job returned")
        with self.lock:
            job = self.jobs.get(ident)
        if job is None:
            known = ", ".join(str(i) for i in sorted(self.jobs)) or "none"
            raise ArgumentError(f"job_id: there is no job {ident} (jobs: {known}; list_jobs shows them)")
        return job

    def enter_foreground(self) -> None:
        with self.lock:
            if self.running_foreground >= max_jobs():
                raise ArgumentError(f"{self.running_foreground} commands are running already (EXEC_MAX_JOBS): wait "
                                    "for them to end")
            self.running_foreground += 1

    def leave_foreground(self) -> None:
        with self.lock:
            self.running_foreground -= 1

    def stop_all(self) -> None:
        with self.lock:
            jobs = list(self.jobs.values())
        for job in jobs:
            if not job.done.is_set():
                job.stop()


JOBS = Jobs()


def checked_command(command) -> str:
    if not isinstance(command, str) or not command.strip():
        raise ArgumentError("command: the shell command to run, e.g. 'ls -la' or 'make test'")
    if len(command) > MAX_COMMAND or "\x00" in command:
        raise ArgumentError(f"command: at most {MAX_COMMAND} characters; put a longer script into a file first")
    return command


def run_blocking(command: str, cwd: str, limit: int) -> Command:
    JOBS.enter_foreground()
    try:
        started = Command(command, cwd, limit)
        started.run_to_end()
        return started
    finally:
        JOBS.leave_foreground()


def run_argv(argv: list[str], cwd: str, limit: int) -> Command:
    """ARGV (no shell parsing of its words) through the same runner as a command."""
    return run_blocking(" ".join(shell_quote(word) for word in argv), cwd, limit)


def shell_quote(word: str) -> str:
    if word and re.fullmatch(r"[A-Za-z0-9_@%+=:,./-]+", word):
        return word
    return "'" + word.replace("'", "'\"'\"'") + "'"


# --- run_tests -------------------------------------------------------------------------------------------------------

FRAMEWORKS = ("auto", "pytest", "unittest", "jest", "vitest", "go", "cargo")


@functools.lru_cache(maxsize=None)
def has_python_module(module: str) -> bool:
    python = shutil.which("python3", path=COMMAND_PATH)
    if not python:
        return False
    try:
        return subprocess.run([python, "-I", "-c", f"import {module}"], stdin=subprocess.DEVNULL,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30,
                              env=command_env()).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def read_small(path: str, limit: int = 1 << 20) -> str:
    try:
        with open(path, "rb") as handle:
            return handle.read(limit).decode("utf-8", "replace")
    except OSError:
        return ""


def package_json(folder: str) -> dict:
    try:
        data = json.loads(read_small(os.path.join(folder, "package.json")) or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def python_tests_present(folder: str) -> bool:
    for base, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        if base[len(folder):].count(os.sep) > 3:
            dirs[:] = []
        if any(re.fullmatch(r"(test_.*|.*_test)\.py", name) for name in files):
            return True
    return False


def detect_framework(folder: str) -> str:
    """The test framework of the project in FOLDER, or ArgumentError saying what was looked for."""
    package = package_json(folder)
    if package:
        deps = {}
        for key in ("dependencies", "devDependencies"):
            if isinstance(package.get(key), dict):
                deps.update(package[key])
        scripts = package.get("scripts") if isinstance(package.get("scripts"), dict) else {}
        script = str(scripts.get("test", ""))
        if "vitest" in deps or "vitest" in script:
            return "vitest"
        if "jest" in deps or "jest" in script or "jest" in package:
            return "jest"
    if os.path.isfile(os.path.join(folder, "go.mod")):
        return "go"
    if os.path.isfile(os.path.join(folder, "Cargo.toml")):
        return "cargo"
    config = {name: read_small(os.path.join(folder, name)) for name in ("pytest.ini", "pyproject.toml", "setup.cfg",
                                                                        "tox.ini", "conftest.py")}
    if config["pytest.ini"] or config["conftest.py"] or "[tool.pytest" in config["pyproject.toml"] \
            or "[tool:pytest]" in config["setup.cfg"] or "[pytest]" in config["tox.ini"]:
        return "pytest"
    if python_tests_present(folder):
        return "pytest" if has_python_module("pytest") else "unittest"
    raise ArgumentError(f"no tests found in {shown(folder)}: looked for package.json (jest, vitest), go.mod, "
                        "Cargo.toml, pytest configuration and test_*.py files. Name the framework, or give path: the "
                        "project's folder")


def node_tool(folder: str, name: str) -> str:
    """The project's own NAME of node_modules/.bin (jest, vitest), as a path; ArgumentError when it is not there."""
    candidate = os.path.join(folder, "node_modules", ".bin", name)
    if not os.path.exists(candidate):
        raise ArgumentError(f"{name} is not installed in the project ({shown(folder)}/node_modules/.bin/{name}); this "
                            "container has no network, so install it from the agent's own shell first")
    if not inside(os.path.realpath(candidate), os.path.realpath(WORKSPACE)):
        raise ArgumentError(f"{shown(folder)}/node_modules/.bin/{name} leads outside {WORKSPACE}")
    if not shutil.which("node", path=COMMAND_PATH):
        raise ArgumentError(f"{name} needs node, which this container does not have")
    return candidate


def require_program(name: str, framework: str) -> str:
    found = shutil.which(name, path=COMMAND_PATH)
    if not found:
        raise ArgumentError(f"{framework} needs {name}, which this container does not have (it has: "
                            + ", ".join(available_tools()) + "); run the tests from the agent's own shell")
    return found


def available_tools() -> list[str]:
    return [name for name in ("bash", "git", "make", "python3", "pytest", "node", "go", "cargo", "shellcheck")
            if (name == "pytest" and has_python_module("pytest")) or shutil.which(name, path=COMMAND_PATH)]


def test_selection(tests) -> list[str]:
    if tests is None or tests == "":
        return []
    if not isinstance(tests, str) or len(tests) > 2000 or any(ord(c) < 32 and c not in " \t" for c in tests):
        raise ArgumentError("tests: test files, folders or names separated by spaces")
    words = tests.split()
    for word in words:
        if word.startswith("-"):
            raise ArgumentError(f"tests: {word!r} looks like an option; run_tests takes test names only (use "
                                "run_command for the test command with options)")
    return words


def cut_lines(text: str, count: int = FAILURE_LINES) -> list[str]:
    lines = [clean(line) for line in text.strip("\n").splitlines()]
    lines = [line for line in lines if line.strip()] if len(lines) > count else lines
    if len(lines) > count:
        lines = lines[:5] + [f"[... {len(lines) - count + 5} lines omitted ...]"] + lines[-(count - 5):]
    return lines


class Failure:
    def __init__(self, name: str, where: str = "", detail: str = "") -> None:
        self.name, self.where, self.detail = name, where, detail


def parse_junit(text: str) -> tuple[dict, list[Failure]]:
    """(counts, failures) of a pytest JUnit XML report (junit_family xunit1: file and line of each test)."""
    root = ElementTree.fromstring(text)
    counts = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    failures = []
    for case in root.iter("testcase"):
        problem = next((child for child in case if child.tag in ("failure", "error")), None)
        if problem is not None:
            counts["failed" if problem.tag == "failure" else "errors"] += 1
            name = case.get("classname", "")
            path = case.get("file") or name.replace(".", "/") + ".py"
            test_id = f"{path}::{case.get('name', '')}" if case.get("name") else path
            where = f"{case.get('file')}:{int(case.get('line')) + 1}" if case.get("file") and \
                (case.get("line") or "").isdigit() else ""
            detail = (problem.text or "").strip() or problem.get("message", "")
            failures.append(Failure(("ERROR " if problem.tag == "error" else "FAILED ") + test_id, where, detail))
        elif any(child.tag == "skipped" for child in case):
            counts["skipped"] += 1
        else:
            counts["passed"] += 1
    return counts, failures


UNITTEST_BLOCK = re.compile(r"^={20,}\n(FAIL|ERROR): (.+?)\n-{20,}\n(.*?)(?=^={20,}\n|^-{20,}\nRan |\Z)", re.M | re.S)


def parse_unittest(text: str) -> tuple[dict, list[Failure]]:
    counts = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    failures = [Failure(f"{kind} {name.strip()}", "", body) for kind, name, body in UNITTEST_BLOCK.findall(text)]
    ran = re.search(r"^Ran (\d+) tests? in", text, re.M)
    summary = re.search(r"^(?:FAILED|OK)\b(?: \(([^)]*)\))?", text, re.M)
    if ran is None:
        raise ValueError("no unittest summary")
    fields = dict(re.findall(r"(\w+)=(\d+)", summary.group(1) or "")) if summary else {}
    counts["failed"] = int(fields.get("failures", 0)) + int(fields.get("unexpected successes", 0))
    counts["errors"] = int(fields.get("errors", 0))
    counts["skipped"] = int(fields.get("skipped", 0)) + int(fields.get("expected_failures", 0))
    counts["passed"] = max(0, int(ran.group(1)) - counts["failed"] - counts["errors"] - counts["skipped"])
    return counts, failures


def parse_jest(text: str, root: str) -> tuple[dict, list[Failure]]:
    """(counts, failures) of jest's or vitest's --json report."""
    data = json.loads(text)
    counts = {"passed": int(data.get("numPassedTests") or 0), "failed": int(data.get("numFailedTests") or 0),
              "errors": int(data.get("numRuntimeErrorTestSuites") or 0),
              "skipped": int(data.get("numPendingTests") or 0) + int(data.get("numTodoTests") or 0)}
    failures = []
    for suite in data.get("testResults") or []:
        file = shown(os.path.realpath(suite.get("name") or suite.get("testFilePath") or "")) if (
            suite.get("name") or suite.get("testFilePath")) else "?"
        cases = suite.get("assertionResults") or suite.get("testResults") or []
        failed = [case for case in cases if case.get("status") == "failed"]
        for case in failed:
            location = case.get("location") or {}
            where = f"{file}:{location['line']}" if isinstance(location, dict) and location.get("line") else file
            name = case.get("fullName") or " > ".join((case.get("ancestorTitles") or []) + [case.get("title", "")])
            failures.append(Failure(f"FAILED {file} > {name}", where, "\n".join(case.get("failureMessages") or [])))
        if suite.get("status") == "failed" and not failed:
            failures.append(Failure(f"ERROR {file} (the test file failed to run)", file,
                                    suite.get("message") or suite.get("failureMessage") or ""))
    return counts, failures


def parse_go(text: str) -> tuple[dict, list[Failure]]:
    """(counts, failures) of `go test -json` (lines that are not JSON: build errors)."""
    counts = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    output: dict[tuple[str, str], list[str]] = {}
    failed: list[tuple[str, str]] = []
    plain: list[str] = []
    for line in text.splitlines():
        if not line.startswith("{"):
            if line.strip():
                plain.append(line)
            continue
        try:
            event = json.loads(line)
        except ValueError:
            plain.append(line)
            continue
        key = (event.get("Package") or event.get("ImportPath") or "", event.get("Test") or "")
        action = event.get("Action")
        if action in ("output", "build-output"):
            output.setdefault(key, []).append((event.get("Output") or "").rstrip("\n"))
        elif action == "pass" and key[1]:
            counts["passed"] += 1
        elif action == "skip" and key[1]:
            counts["skipped"] += 1
        elif action in ("fail", "build-fail"):
            if key[1]:
                counts["failed"] += 1
                failed.append(key)
            elif not any(f[0] == key[0] for f in failed):
                counts["errors"] += 1
                failed.append(key)
    failures = [Failure(f"FAILED {package}.{test}" if test else f"ERROR {package} (did not build or failed outside a "
                        "test)", "", "\n".join(output.get((package, test), []) or plain))
                for package, test in failed]
    if not failures and plain and not any(counts.values()):
        failures.append(Failure("ERROR go test", "", "\n".join(plain)))
        counts["errors"] += 1
    return counts, failures


def parse_cargo(text: str) -> tuple[dict, list[Failure]]:
    counts = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    results = re.findall(r"^test result: \w+\. (\d+) passed; (\d+) failed; (\d+) ignored", text, re.M)
    for passed, failed, ignored in results:
        counts["passed"] += int(passed)
        counts["failed"] += int(failed)
        counts["skipped"] += int(ignored)
    sections = dict(re.findall(r"^---- (\S+) stdout ----\n(.*?)(?=^---- \S+ stdout ----\n|^failures:\n|\Z)", text,
                               re.M | re.S))
    names = re.findall(r"^test (\S+) \.\.\. FAILED", text, re.M)
    failures = [Failure(f"FAILED {name}", "", sections.get(name, "")) for name in dict.fromkeys(names)]
    if not results:
        errors = re.findall(r"^(error(?:\[E\d+\])?: .*(?:\n(?!error).*){0,6})", text, re.M)
        if errors:
            counts["errors"] += 1
            failures.append(Failure("ERROR cargo (did not compile)", "", "\n\n".join(errors[:10])))
        else:
            raise ValueError("no cargo test summary")
    return counts, failures


def output_text(command: Command) -> str:
    """What is kept of COMMAND's output, as it was written (the first and the last part when it was long), with the
    colours removed: for the parsers, which clean what they show."""
    return ANSI.sub("", command.output.raw())


def summary_line(counts: dict) -> str:
    order = ("failed", "errors", "passed", "skipped")
    parts = [f"{counts[key]} {key}" for key in order if counts.get(key)]
    return ", ".join(parts) or "no tests ran"


def test_report(framework: str, folder: str, command: Command, counts: dict, failures: list[Failure]) -> str:
    head = f"{framework} in {shown(folder)} ({ending(command)}, {duration(command.seconds())}): {summary_line(counts)}"
    lines = [head]
    if command.timed_out:
        lines.append(f"Note: the tests were stopped after {duration(command.limit)}; results are incomplete. Give "
                     "tests: a file or folder, or timeout_seconds.")
    if not failures:
        if counts.get("passed") and not counts.get("failed") and not counts.get("errors") and \
                command.popen.returncode == 0:
            lines.append("All tests passed.")
        return "\n".join(lines)
    for failure in failures[:MAX_FAILURES]:
        lines.append("")
        lines.append(failure.name + (f"  ({failure.where})" if failure.where and failure.where not in failure.name
                                     else ""))
        lines += ["    " + line for line in cut_lines(failure.detail)]
    if len(failures) > MAX_FAILURES:
        rest = failures[MAX_FAILURES:]
        lines.append("")
        lines.append(f"... and {len(rest)} more: " + ", ".join(f.name.split(" ", 1)[-1] for f in rest[:30])
                     + (" ..." if len(rest) > 30 else ""))
    text = "\n".join(lines)
    return text if len(text) <= MAX_ANSWER else text[:MAX_ANSWER - 60] + "\n[... the rest of the report omitted]"


def raw_report(framework: str, folder: str, command: Command, why: str) -> str:
    return (f"{framework} in {shown(folder)} ({ending(command)}, {duration(command.seconds())}): {why}; its output:\n"
            + (command.output.render(*output_budget())[0] or "(no output)"))


def run_tests_in(folder: str, framework: str, tests: list[str], limit: int) -> str:
    report_file = None
    try:
        if framework in ("pytest", "jest", "vitest"):
            handle, report_file = tempfile.mkstemp(prefix="exec-tests-", suffix=".xml" if framework == "pytest"
                                                   else ".json", dir="/tmp" if os.path.isdir("/tmp") else None)
            os.close(handle)
            os.unlink(report_file)
        if framework == "pytest":
            argv = [require_program("python3", framework), "-m", "pytest", "-q", "-rfE", "--tb=short", "--no-header",
                    "-p", "no:cacheprovider", "--color=no", "-o", "junit_family=xunit1",
                    f"--junitxml={report_file}", *tests]
        elif framework == "unittest":
            python = require_program("python3", framework)
            argv = [python, "-m", "unittest", *tests] if tests else [python, "-m", "unittest", "discover"]
        elif framework == "jest":
            argv = [node_tool(folder, "jest"), "--ci", "--json", f"--outputFile={report_file}", "--color=false",
                    "--watchAll=false", *tests]
        elif framework == "vitest":
            argv = [node_tool(folder, "vitest"), "run", "--reporter=json", f"--outputFile={report_file}", *tests]
        elif framework == "go":
            argv = [require_program("go", framework), "test", "-json", *(tests or ["./..."])]
        else:
            argv = [require_program("cargo", framework), "test", "--no-fail-fast", "--color", "never", *tests]
        if framework == "pytest" and not has_python_module("pytest"):
            raise ArgumentError("pytest is not installed in this container's python3; use framework: unittest")
        command = run_argv(argv, folder, limit)
        if command.popen.returncode == 5 and framework == "pytest":
            return f"pytest in {shown(folder)}: no tests were collected (pytest exit 5)"
        try:
            if framework == "pytest":
                counts, failures = parse_junit(read_small(report_file, 16 << 20))
            elif framework == "unittest":
                counts, failures = parse_unittest(output_text(command))
            elif framework in ("jest", "vitest"):
                counts, failures = parse_jest(read_small(report_file, 16 << 20), folder)
            elif framework == "go":
                counts, failures = parse_go(output_text(command))
            else:
                counts, failures = parse_cargo(output_text(command))
        except (ValueError, ElementTree.ParseError, KeyError, TypeError, AttributeError):
            return raw_report(framework, folder, command, "its report could not be read")
        if not failures and command.popen.returncode not in (0, None) and not command.timed_out:
            return raw_report(framework, folder, command, f"{summary_line(counts)}, but it failed")
        return test_report(framework, folder, command, counts, failures)
    finally:
        if report_file and os.path.exists(report_file):
            os.unlink(report_file)


# --- lint ------------------------------------------------------------------------------------------------------------

#: Run by the image's own python3 (-I: nothing of /work is imported): parse each file given, print one JSON object
#: per problem. Nothing of a file is executed (yaml.safe_load builds no objects, compile() runs nothing).
CHECKER = r"""
import json, sys
kind = sys.argv[1]
for path in sys.argv[2:]:
    try:
        with open(path, 'rb') as handle:
            data = handle.read()
        if kind == 'json':
            json.loads(data.decode('utf-8-sig'))
        elif kind == 'yaml':
            import yaml
            for _ in yaml.safe_load_all(data):
                pass
        else:
            compile(data, path, 'exec', dont_inherit=True)
    except (ValueError, SyntaxError, RecursionError, MemoryError) as error:
        line = getattr(error, 'lineno', None)
        column = getattr(error, 'colno', None) or getattr(error, 'offset', None)
        mark = getattr(error, 'problem_mark', None)
        if mark is not None:
            line, column = mark.line + 1, mark.column + 1
        message = getattr(error, 'msg', None) or getattr(error, 'problem', None) or str(error)
        print(json.dumps({'file': path, 'line': line or 1, 'column': column or 1, 'message': str(message)}))
    except Exception as error:
        message = getattr(error, 'problem', None) or str(error) or type(error).__name__
        mark = getattr(error, 'problem_mark', None)
        line, column = (mark.line + 1, mark.column + 1) if mark is not None else (1, 1)
        print(json.dumps({'file': path, 'line': line, 'column': column, 'message': str(message)}))
"""

SHELL_NAMES = re.compile(rb"^#!\s*(?:/usr)?/bin/(?:env\s+)?(?:ba|da|k|)sh\b")
LINT_KINDS = {".py": "python", ".pyi": "python", ".sh": "shell", ".bash": "shell", ".json": "json",
              ".yaml": "yaml", ".yml": "yaml", ".js": "js", ".jsx": "js", ".mjs": "js", ".cjs": "js",
              ".ts": "js", ".tsx": "js", ".mts": "js", ".cts": "js"}


def lint_files(target: str) -> tuple[dict[str, list[str]], bool]:
    """({kind: [paths]}, cut short?) of the files below TARGET (or TARGET itself): no links followed, the usual
    folders of tools and dependencies skipped."""
    found: dict[str, list[str]] = {}
    seen = 0
    cut = False

    def add(path: str) -> None:
        nonlocal cut
        kind = LINT_KINDS.get(os.path.splitext(path)[1].lower())
        if kind is None and not os.path.splitext(path)[1]:
            try:
                with open(path, "rb") as handle:
                    kind = "shell" if SHELL_NAMES.match(handle.read(64)) else None
            except OSError:
                kind = None
        if kind:
            if sum(len(v) for v in found.values()) >= MAX_LINT_FILES:
                cut = True
                return
            found.setdefault(kind, []).append(path)

    if os.path.isfile(target):
        add(target)
        return found, cut
    for base, dirs, files in os.walk(target):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not os.path.islink(os.path.join(base, d)))
        for name in sorted(files):
            seen += 1
            if seen > MAX_WALK:
                return found, True
            path = os.path.join(base, name)
            if os.path.islink(path) or not os.path.isfile(path):
                continue
            add(path)
    return found, cut


class Problem:
    def __init__(self, path: str, line, column, tool: str, message: str) -> None:
        self.path, self.tool, self.message = path, tool, message
        self.line = int(line) if str(line).isdigit() else 1
        self.column = int(column) if str(column).isdigit() else 1

    def text(self) -> str:
        return clean(f"{shown(self.path)}:{self.line}:{self.column}: [{self.tool}] {self.message}")


def chunks(paths: list[str], size: int = 200):
    for start in range(0, len(paths), size):
        yield paths[start:start + size]


def run_quiet(argv: list[str], cwd: str, limit: int) -> tuple[int, str]:
    command = run_argv(argv, cwd, limit)
    if command.timed_out:
        raise ArgumentError(f"{os.path.basename(argv[0])} did not finish within {limit} s; lint a smaller path")
    return command.popen.returncode, output_text(command)


def parse_flake_lines(text: str, tool: str) -> list[Problem]:
    """`path:line:col: message` lines (pyflakes, ruff's concise format)."""
    problems = []
    for line in text.splitlines():
        match = re.match(r"^(.+?):(\d+):(\d+):? (.+)$", line)
        if match:
            problems.append(Problem(match.group(1), match.group(2), match.group(3), tool, match.group(4)))
    return problems


def checker_problems(text: str, tool: str) -> list[Problem]:
    """The problems CHECKER printed (one JSON object per line)."""
    problems = []
    for line in text.splitlines():
        if line.startswith("{"):
            try:
                item = json.loads(line)
            except ValueError:
                continue
            problems.append(Problem(str(item.get("file", "?")), item.get("line", 1), item.get("column", 1), tool,
                                    str(item.get("message", ""))))
    return problems


def parse_shellcheck(text: str) -> list[Problem]:
    """shellcheck's gcc format: `path:line:col: level: message [SCcode]`."""
    problems = []
    for line in text.splitlines():
        match = re.match(r"^(.+?):(\d+):(\d+): (\w+): (.*?)(?: \[SC(\d+)\])?$", line)
        if match:
            level = {"note": "info"}.get(match.group(4), match.group(4))
            code = f" SC{match.group(6)}" if match.group(6) else ""
            problems.append(Problem(match.group(1), match.group(2), match.group(3), f"shellcheck{code} {level}",
                                    match.group(5)))
    return problems


def lint_path(target: str, limit: int) -> str:
    root = os.path.realpath(WORKSPACE)
    files, cut = lint_files(target)
    problems: list[Problem] = []
    ran: dict[str, int] = {}
    skipped: list[str] = []
    python = shutil.which("python3", path=COMMAND_PATH)
    deadline = time.monotonic() + limit

    def left() -> int:
        remaining = int(deadline - time.monotonic())
        if remaining < 1:
            raise ArgumentError(f"lint did not finish within {limit} s; lint a smaller path")
        return remaining

    if files.get("python"):
        ruff = shutil.which("ruff", path=COMMAND_PATH)
        if ruff:
            for part in chunks(files["python"]):
                _, text = run_quiet([ruff, "check", "--output-format=concise", "--no-cache", "--no-fix", *part], root,
                                    left())
                problems += parse_flake_lines(text, "ruff")
            ran["ruff"] = len(files["python"])
        elif python and has_python_module("pyflakes"):
            for part in chunks(files["python"]):
                _, text = run_quiet([python, "-I", "-m", "pyflakes", *part], root, left())
                problems += parse_flake_lines(text, "pyflakes")
            ran["pyflakes"] = len(files["python"])
        elif python:
            for part in chunks(files["python"]):
                _, text = run_quiet([python, "-I", "-c", CHECKER, "python", *part], root, left())
                problems += checker_problems(text, "python syntax")
            ran["python syntax"] = len(files["python"])
    if files.get("shell"):
        shellcheck = shutil.which("shellcheck", path=COMMAND_PATH)
        if shellcheck:
            for part in chunks(files["shell"]):
                _, text = run_quiet([shellcheck, "--format=gcc", "--color=never", *part], root, left())
                problems += parse_shellcheck(text)
            ran["shellcheck"] = len(files["shell"])
        else:
            skipped.append(f"{len(files['shell'])} shell scripts (no shellcheck here)")
    for kind in ("json", "yaml"):
        paths = [p for p in files.get(kind, []) if os.path.getsize(p) <= MAX_FILE_BYTES]
        if len(paths) < len(files.get(kind, [])):
            skipped.append(f"{len(files[kind]) - len(paths)} {kind.upper()} files over {MAX_FILE_BYTES >> 20} MiB")
        if not paths:
            continue
        if not python or (kind == "yaml" and not has_python_module("yaml")):
            skipped.append(f"{len(paths)} {kind.upper()} files (no parser here)")
            continue
        for part in chunks(paths):
            _, text = run_quiet([python, "-I", "-c", CHECKER, kind, *part], root, left())
            problems += checker_problems(text, kind)
        ran[kind] = len(paths)
    if files.get("js"):
        # eslint loads the project's configuration, which is code: lint runs nothing of the project.
        skipped.append(f"{len(files['js'])} JavaScript/TypeScript files (eslint runs the project's own configuration, "
                       "so lint leaves it out; run it with run_command: node_modules/.bin/eslint --format unix .)")
    checked = sum(ran.values())
    head = f"lint of {shown(target)}: {checked} files checked"
    if ran:
        head += " (" + ", ".join(f"{tool}: {count}" for tool, count in ran.items()) + ")"
    head += f"; {len(problems)} problem{'s' if len(problems) != 1 else ''}"
    lines = [head]
    lines += [problem.text() for problem in problems[:MAX_PROBLEMS]]
    if len(problems) > MAX_PROBLEMS:
        lines.append(f"[... {len(problems) - MAX_PROBLEMS} more problems; lint a smaller path]")
    if cut:
        lines.append(f"Note: only the first {MAX_LINT_FILES} files were checked; lint a smaller path for the rest.")
    for item in skipped:
        lines.append(f"Not checked: {item}.")
    if not files:
        lines.append("No Python, shell, JSON, YAML or JavaScript/TypeScript files found there.")
    elif not problems and checked:
        lines.append("No problems found.")
    text = "\n".join(lines)
    return text if len(text) <= MAX_ANSWER else text[:MAX_ANSWER - 50] + "\n[... the rest omitted]"


# --- the MCP server --------------------------------------------------------------------------------------------------

mcp = FastMCP("exec-mcp", instructions=(
    "Runs commands for you in the project folder /work, safely: every command has a time limit, never waits for "
    "input (stdin is empty), and long output is shortened to its first and last lines. Paths are relative to /work. "
    "Use run_command for commands that end within a few minutes; start_job and job_status for long builds, servers "
    "and watchers; run_tests to see only the failing tests; lint to find mistakes without running anything. The "
    "commands run in this server's container: it has bash, coreutils, git, make, python3 with pytest, node, "
    "shellcheck - and no network."))

WRITES = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False)
STOPS = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False)
READS = ToolAnnotations(readOnlyHint=True, openWorldHint=False)


def answer(function, *args) -> str:
    """FUNCTION(*ARGS), an ArgumentError as the tool's error."""
    try:
        return function(*args)
    except ArgumentError:
        raise
    except OSError as error:
        raise ArgumentError(f"{error.strerror or error}") from None


@mcp.tool(annotations=WRITES, structured_output=False)
async def run_command(command: str, cwd: str = "", timeout_seconds: int | None = None) -> str:
    """Run a bash command in the project folder /work and get its exit code and output.

    Each call starts fresh in /work (or cwd): cd and variables do not carry over, so chain with && in one command.
    Nothing can wait for input (stdin is empty): use --yes / -y style switches. Stopped after timeout_seconds
    (default 120). Long output is shortened to its first and last lines. For servers, watchers or anything that runs
    longer, use start_job.

    Args:
        command: the shell command, e.g. "ls -la", "make", "git status", "python3 script.py"
        cwd: folder to run in, relative to /work (default: /work itself)
        timeout_seconds: stop the command after this many seconds (default 120)
    """
    def run() -> str:
        text = checked_command(command)
        folder = workspace_path(cwd)
        return report(run_blocking(text, folder, timeout_of(timeout_seconds)))
    return await asyncio.to_thread(answer, run)


@mcp.tool(annotations=WRITES, structured_output=False)
async def start_job(command: str, cwd: str = "") -> str:
    """Start a long command in the background (a build, a dev server, a watcher) and get its job id at once.

    Then call job_status to see its output and whether it ended, and stop_job to end it.

    Args:
        command: the shell command, e.g. "npm run dev" or "make all"
        cwd: folder to run in, relative to /work (default: /work itself)
    """
    def start() -> str:
        text = checked_command(command)
        folder = workspace_path(cwd)
        ident, job = JOBS.start(text, folder)
        job.done.wait(1.0)  # one that fails at once says so now
        where = f" in {shown(folder)}" if shown(folder) != "." else ""
        if job.done.is_set():
            return f"job {ident} ended already{where}: " + report(job)
        return (f"job {ident} started{where} (stopped after {duration(job.limit)} at the latest). "
                f"Check it with job_status(job_id={ident}, wait_seconds=30); end it with stop_job(job_id={ident}).")
    return await asyncio.to_thread(answer, start)


def status_text(ident: int, job: Command, tail_lines: int) -> str:
    text, total = job.output.last_lines(tail_lines)
    where = f" in {shown(job.cwd)}" if shown(job.cwd) != "." else ""
    state = (f"running for {duration(job.seconds())}" if not job.done.is_set()
             else f"{ending(job)} after {duration(job.seconds())}")
    cmd = job.command if len(job.command) <= 200 else job.command[:200] + " ..."
    lines = [f"job {ident}: {state}{where} · {cmd}"]
    if total:
        lines.append(f"output: {total} lines" + (f", the last {min(tail_lines, total)}:" if tail_lines else ""))
        if text:
            lines.append(text)
    else:
        lines.append("output: none yet")
    if job.done.is_set():
        lines += [f"Note: {note}" for note in hints(job, text)]
    return "\n".join(lines)


@mcp.tool(annotations=READS, structured_output=False)
async def job_status(job_id: int, wait_seconds: int = 0, tail_lines: int = 30) -> str:
    """Show a background job: running or ended, its exit code, and its last output lines.

    Args:
        job_id: the number start_job returned
        wait_seconds: wait up to this many seconds for the job to end first (0: answer at once; at most 300)
        tail_lines: how many of its last output lines to show (default 30, at most 300)
    """
    def status() -> str:
        if isinstance(wait_seconds, bool) or not isinstance(wait_seconds, int) or not 0 <= wait_seconds <= MAX_WAIT:
            raise ArgumentError(f"wait_seconds: 0 to {MAX_WAIT}")
        if isinstance(tail_lines, bool) or not isinstance(tail_lines, int) or not 0 <= tail_lines <= 300:
            raise ArgumentError("tail_lines: 0 to 300")
        job = JOBS.get(job_id)
        if wait_seconds:
            job.done.wait(wait_seconds)
        return status_text(job_id, job, tail_lines)
    return await asyncio.to_thread(answer, status)


@mcp.tool(annotations=STOPS, structured_output=False)
async def stop_job(job_id: int) -> str:
    """Stop a background job and every process it started.

    Args:
        job_id: the number start_job returned
    """
    def stop() -> str:
        job = JOBS.get(job_id)
        if not job.done.is_set():
            job.stop()
            job.done.wait(GRACE * 3 + EOF_GRACE)
        return status_text(job_id, job, 20)
    return await asyncio.to_thread(answer, stop)


@mcp.tool(annotations=READS, structured_output=False)
async def list_jobs() -> str:
    """List the background jobs of this session with their state."""
    def listing() -> str:
        with JOBS.lock:
            jobs = sorted(JOBS.jobs.items())
        if not jobs:
            return "no jobs (start_job starts one)"
        lines = []
        for ident, job in jobs:
            state = "running" if not job.done.is_set() else ending(job)
            cmd = job.command if len(job.command) <= 80 else job.command[:80] + " ..."
            lines.append(f"job {ident}: {state} · {duration(job.seconds())} · {cmd}")
        return "\n".join(lines)
    return await asyncio.to_thread(answer, listing)


@mcp.tool(annotations=WRITES, structured_output=False)
async def run_tests(path: str = "", framework: str = "auto", tests: str = "",
                    timeout_seconds: int | None = None) -> str:
    """Run the project's tests and get only the failures, compactly (test name, place, short message).

    Args:
        path: the project folder, relative to /work (default: /work itself)
        framework: auto (default: finds pytest, unittest, jest, vitest, go or cargo), or one of these
        tests: only these tests, separated by spaces: files, folders or names (default: all)
        timeout_seconds: stop the tests after this many seconds (default 300 or the server's limit)
    """
    def run() -> str:
        folder = workspace_path(path, "path")
        if framework not in FRAMEWORKS:
            raise ArgumentError(f"framework: one of {', '.join(FRAMEWORKS)}")
        chosen = detect_framework(folder) if framework == "auto" else framework
        return run_tests_in(folder, chosen, test_selection(tests), timeout_of(timeout_seconds, 300))
    return await asyncio.to_thread(answer, run)


@mcp.tool(annotations=READS, structured_output=False)
async def lint(path: str = "", timeout_seconds: int | None = None) -> str:
    """Check files for mistakes without running them: Python (pyflakes), shell scripts (shellcheck), JSON, YAML.

    One line per problem: file:line:column: [tool] message. Reads files only; nothing of the project runs.

    Args:
        path: a file or folder, relative to /work (default: all of /work)
        timeout_seconds: give up after this many seconds (default 120)
    """
    def check() -> str:
        target = workspace_path(path, "path", folder=False)
        return lint_path(target, timeout_of(timeout_seconds))
    return await asyncio.to_thread(answer, check)


def harden() -> None:
    """Make this process non-dumpable: commands run as the same user, but cannot open its /proc entries (its stdin
    and stdout are the MCP connection), read its memory or ptrace it. Linux only; a failure is logged."""
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(4, 0, 0, 0, 0) != 0:  # PR_SET_DUMPABLE
            raise OSError(ctypes.get_errno(), "prctl(PR_SET_DUMPABLE) failed")
    except (OSError, AttributeError) as error:
        print(f"exec-mcp: could not make the server non-dumpable: {error}", file=sys.stderr)


def main() -> None:
    harden()
    try:
        mcp.run("stdio")
    finally:
        JOBS.stop_all()


if __name__ == "__main__":
    main()
