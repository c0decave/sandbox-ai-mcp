"""The exec server (servers/exec), offline: time limits and the kill of a command's whole process tree (its group,
a child in a session of its own, one that ignores SIGTERM), output bounded to its start and end (in memory too),
colours and progress bars removed, programs that would wait for input, no terminal, the fixed environment and its
allow-list, start folders inside /work only (also through symbolic links), background jobs (status, wait, tail, stop,
limits, time limit), run_tests with each framework's recorded report and real unittest/pytest runs, lint, the MCP
server over stdio (tools, refusals, the server's own /proc entries closed to the commands). CI runs this inside the
image too (tests/test_own_servers.py test_exec), where python3 has pytest, pyflakes and yaml and shellcheck is there."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "servers" / "exec" / "src" / "server.py"

try:
    import mcp  # noqa: F401 - the server's own dependency
except ImportError:
    mcp = None


def load():
    spec = importlib.util.spec_from_file_location("server_exec_test", SERVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def alive(marker: str) -> list[int]:
    """Processes whose command line contains MARKER."""
    found = []
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        try:
            with open(f"/proc/{name}/cmdline", "rb") as handle:
                line = handle.read().replace(b"\0", b" ").decode("utf-8", "replace")
            with open(f"/proc/{name}/stat", "rb") as handle:
                state = handle.read().decode().rsplit(")", 1)[1].split()[0]
        except OSError:
            continue
        if marker in line and state != "Z":
            found.append(int(name))
    return found


@unittest.skipIf(mcp is None, "the server's requirements are not installed (pip install --require-hashes -r "
                              "servers/exec/requirements.txt)")
@unittest.skipUnless(sys.platform.startswith("linux"), "the server runs in a Linux container")
class ExecBase(unittest.TestCase):
    def setUp(self):
        self.module = load()
        self.folder = tempfile.mkdtemp(prefix="exec-test-")
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.work = os.path.realpath(self.folder)
        self.module.WORKSPACE = self.work
        self.module.MOUNT_REQUIRED = False
        self.module.JOBS = self.module.Jobs()
        if os.environ.get("EXEC_TEST_PATH"):  # a folder with test tools the local python3 lacks (pytest, pyflakes)
            self.module.COMMAND_PATH = os.environ["EXEC_TEST_PATH"] + ":" + self.module.COMMAND_PATH
        self.addCleanup(self.module.JOBS.stop_all)
        patcher = mock.patch.dict(os.environ, {"EXEC_TIMEOUT": "", "EXEC_MAX_TIMEOUT": "", "EXEC_JOB_TIMEOUT": "",
                                               "EXEC_MAX_JOBS": "", "EXEC_ENV_ALLOW": "", "EXEC_OUTPUT_LINES": ""})
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_command(self, command, cwd="", timeout=None):
        m = self.module
        return m.answer(lambda: m.report(m.run_blocking(m.checked_command(command), m.workspace_path(cwd),
                                                         m.timeout_of(timeout))))

    def error(self, call) -> str:
        with self.assertRaises(self.module.ArgumentError) as caught:
            call()
        return str(caught.exception)

    def write(self, name, text, mode=None):
        path = Path(self.work, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text))
        if mode is not None:
            path.chmod(mode)
        return path


class Commands(ExecBase):
    def test_output_exit_code_and_stderr_together(self):
        text = self.run_command("echo out; echo err >&2; exit 3")
        self.assertTrue(text.startswith("exit 3 (failed) · "), text)
        self.assertIn("out\nerr", text)
        self.assertTrue(self.run_command("true").startswith("exit 0 · "))
        self.assertIn("(no output)", self.run_command("true"))

    def test_each_call_starts_in_the_workspace_or_its_cwd(self):
        os.mkdir(os.path.join(self.work, "sub"))
        self.assertIn(f"\n{self.work}\n", self.run_command("pwd; cd /; pwd") + "\n")
        self.assertIn(f"\n{self.work}\n", self.run_command("pwd") + "\n")
        text = self.run_command("pwd", cwd="sub")
        self.assertIn(" · in sub", text)
        self.assertIn(os.path.join(self.work, "sub"), text)
        self.assertIn(os.path.join(self.work, "sub"), self.run_command("pwd", cwd=os.path.join(self.work, "sub")))

    def test_long_output_shows_start_and_end_with_the_count_omitted(self):
        text = self.run_command("seq 1 100000")
        lines = text.split("\n")
        self.assertIn("100000 lines of output, the first and last shown", lines[0])
        self.assertEqual(lines[1:4], ["1", "2", "3"])
        self.assertEqual(lines[-1], "100000")
        self.assertIn("[... 99900 lines omitted ...]", text)
        self.assertEqual(len(lines), 1 + 25 + 1 + 75)
        self.assertLess(len(text), self.module.MAX_ANSWER)

    def test_the_number_of_lines_shown_is_a_setting(self):
        with mock.patch.dict(os.environ, {"EXEC_OUTPUT_LINES": "40"}):
            text = self.run_command("seq 1 1000")
        self.assertIn("[... 960 lines omitted ...]", text)
        with mock.patch.dict(os.environ, {"EXEC_OUTPUT_LINES": "5"}):
            self.assertIn("EXEC_OUTPUT_LINES: a whole number from 20 to 2000", self.error(lambda: self.run_command("true")))

    def test_huge_output_is_counted_not_kept(self):
        started = time.monotonic()
        command = self.module.run_blocking("head -c 30000000 /dev/zero | tr '\\0' x; echo; echo end", self.work, 60)
        self.assertLess(time.monotonic() - started, 30)
        output = command.output
        self.assertEqual(output.total, 30000000 + 1 + 4)
        self.assertLessEqual(len(output.head) + len(output.tail), self.module.HEAD_BYTES + self.module.TAIL_BYTES)
        text = self.module.report(command)
        self.assertIn("more characters]", text)
        self.assertTrue(text.endswith("end"), text[-200:])
        self.assertLess(len(text), self.module.MAX_ANSWER)

    def test_colours_progress_bars_and_repeats_are_cleaned(self):
        text = self.run_command(r"printf '\033[31mred\033[0m\n'; printf 'get 10%%\rget 50%%\rget 100%%\n'; "
                                r"for i in 1 2 3 4 5 6; do echo same; done; printf 'a\tb\001c\n'")
        self.assertIn("\nred\n", text)
        self.assertIn("\nget 100%\n", text)
        self.assertNotIn("10%", text)
        self.assertIn("same\n[... the line above 5 more times]", text)
        self.assertIn("a    bc", text)
        self.assertNotIn("\x1b", text)

    def test_stdin_is_empty_and_there_is_no_terminal(self):
        self.assertIn("got:[] status:1", self.run_command('read -r x; echo "got:[$x] status:$?"'))
        started = time.monotonic()
        self.assertIn("EOFError", self.run_command("python3 -c 'input(\"name? \")'", timeout=20))
        self.assertIn("ended", self.run_command("cat; echo ended", timeout=20))
        self.assertLess(time.monotonic() - started, 15, "nothing waited for input")
        self.assertIn("no terminal", self.run_command("test -t 0 || test -t 1 || echo no terminal; tty || true"))

    def test_the_environment_is_fixed_and_the_servers_own_is_not_passed(self):
        with mock.patch.dict(os.environ, {"EXEC_TEST_SECRET": "value-of-the-server", "EXEC_TEST_OPEN": "shared"}):
            text = self.run_command("env | sort")
            for line in ("CI=1", "TERM=dumb", "PAGER=cat", "GIT_PAGER=cat", "GIT_TERMINAL_PROMPT=0", "EDITOR=true",
                         "DEBIAN_FRONTEND=noninteractive", "PIP_NO_INPUT=1", "npm_config_yes=true", "NO_COLOR=1",
                         "HOME=/tmp", f"PATH={self.module.COMMAND_PATH}"):
                self.assertIn(line, text.split("\n"))
            self.assertNotIn("value-of-the-server", text)
            self.assertNotIn("EXEC_TEST_OPEN", text)
            with mock.patch.dict(os.environ, {"EXEC_ENV_ALLOW": "EXEC_TEST_OPEN, NOT_SET_HERE"}):
                text = self.run_command("env")
            self.assertIn("EXEC_TEST_OPEN=shared", text)
            self.assertNotIn("value-of-the-server", text)
            with mock.patch.dict(os.environ, {"EXEC_ENV_ALLOW": "BAD-NAME"}):
                self.assertIn("EXEC_ENV_ALLOW: 'BAD-NAME' is not a variable name",
                              self.error(lambda: self.run_command("env")))

    def test_the_command_is_the_first_to_go_when_memory_runs_out(self):
        self.assertIn("\n1000", self.run_command("cat /proc/self/oom_score_adj"))

    @unittest.skipUnless(shutil.which("git"), "git is not here")
    def test_git_never_pages_or_opens_an_editor(self):
        text = self.run_command("git init -q . && git -c user.name=t -c user.email=t@example.invalid commit -q "
                                "--allow-empty -m one && git log && git -c user.name=t -c user.email=t@example.invalid "
                                "commit --allow-empty; echo status:$?", timeout=60)
        self.assertIn("one", text)
        self.assertIn("status:1", text)  # the editor (true) leaves the message empty: git aborts, nothing waits


class Limits(ExecBase):
    def test_a_command_over_its_time_is_stopped_with_everything_it_started(self):
        started = time.monotonic()
        text = self.run_command("sleep 3001 & (sleep 3002 &); sleep 3003", timeout=1)
        self.assertLess(time.monotonic() - started, 8)
        self.assertTrue(text.startswith("TIMED OUT after 1.0 s: stopped, with every process it started"), text)
        self.assertIn("timeout_seconds up to 600", text)
        for marker in ("sleep 3001", "sleep 3002", "sleep 3003"):
            self.assertEqual(alive(marker), [], marker)

    def test_a_child_in_a_session_of_its_own_is_stopped_too(self):
        self.run_command("setsid sleep 3004 & sleep 3005", timeout=1)
        time.sleep(0.2)
        self.assertEqual(alive("sleep 3004"), [])
        self.assertEqual(alive("sleep 3005"), [])

    def test_sigterm_ignored_is_followed_by_sigkill(self):
        started = time.monotonic()
        text = self.run_command("trap '' TERM; sleep 3006; sleep 3006", timeout=1)
        self.assertTrue(text.startswith("TIMED OUT"), text)
        self.assertLess(time.monotonic() - started, 1 + 2 * self.module.GRACE + 2)
        self.assertEqual(alive("sleep 3006"), [])

    def test_a_process_left_in_the_background_is_stopped_when_the_command_ends(self):
        started = time.monotonic()
        text = self.run_command("sleep 3007 & echo started")
        self.assertLess(time.monotonic() - started, self.module.EOF_GRACE + 2 * self.module.GRACE + 2)
        self.assertTrue(text.startswith("exit 0"), text)
        self.assertIn("started", text)
        self.assertIn("It left processes running in the background", text)
        self.assertEqual(alive("sleep 3007"), [])

    def test_a_program_waiting_for_an_answer_gets_a_hint(self):
        text = self.run_command("printf 'Overwrite the database? [y/N] '; while :; do read -r a || sleep 0.2; done",
                                timeout=1)
        self.assertTrue(text.startswith("TIMED OUT"), text)
        self.assertIn("Overwrite the database? [y/N]", text)
        self.assertIn("seems to wait for an answer: stdin is empty here", text)
        text = self.run_command("echo serving; python3 -m http.server 0 --bind 127.0.0.1 >/dev/null 2>&1", timeout=1)
        self.assertIn("A server or watcher never ends by itself: run it with start_job", text)

    def test_signals_and_out_of_memory_are_named(self):
        self.assertIn("killed by SIGKILL - out of memory? · ", self.run_command("kill -9 $$"))
        self.assertIn("killed by SIGKILL - out of memory? (exit 137)", self.run_command("bash -c 'kill -9 $$'; exit $?"))
        self.assertIn("killed by SIGSEGV", self.run_command("bash -c 'kill -SEGV $$'"))

    def test_time_limits(self):
        m = self.module
        self.assertEqual(m.timeout_of(None), 120)
        self.assertEqual(m.timeout_of(0), 120)
        self.assertEqual(m.timeout_of(None, 300), 300)
        self.assertIn("from 1 to 600 (EXEC_MAX_TIMEOUT)", self.error(lambda: m.timeout_of(601)))
        self.assertIn("timeout_seconds", self.error(lambda: m.timeout_of(-1)))
        self.assertIn("timeout_seconds", self.error(lambda: m.timeout_of(True)))
        with mock.patch.dict(os.environ, {"EXEC_MAX_TIMEOUT": "30", "EXEC_TIMEOUT": "45"}):
            self.assertEqual(m.timeout_of(None), 30)
            self.assertEqual(m.timeout_of(None, 300), 30)
            self.assertIn("from 1 to 30", self.error(lambda: m.timeout_of(31)))
        with mock.patch.dict(os.environ, {"EXEC_TIMEOUT": "two minutes"}):
            self.assertIn("EXEC_TIMEOUT: a whole number from 1 to 86400", self.error(lambda: m.timeout_of(None)))

    def test_the_command_itself(self):
        m = self.module
        self.assertIn("command: the shell command", self.error(lambda: m.checked_command("  ")))
        self.assertIn("command: the shell command", self.error(lambda: m.checked_command(None)))
        self.assertIn("at most 16384 characters", self.error(lambda: m.checked_command("x" * 16385)))


class Paths(ExecBase):
    def test_folders_outside_the_workspace_are_refused(self):
        for value in ("..", "../", "/etc", "/", os.path.join(self.work, "..", "x"), "sub/../../etc"):
            with self.subTest(cwd=value):
                self.assertIn("is outside", self.error(lambda: self.run_command("pwd", cwd=value)))
        self.assertIn("a path inside", self.error(lambda: self.run_command("pwd", cwd="a\nb")))
        self.assertIn("does not exist", self.error(lambda: self.run_command("pwd", cwd="nothing")))
        self.write("file.txt", "x")
        self.assertIn("is not a folder", self.error(lambda: self.run_command("pwd", cwd="file.txt")))

    def test_symbolic_links_are_followed_only_inside_the_workspace(self):
        outside = tempfile.mkdtemp(prefix="exec-outside-")
        self.addCleanup(shutil.rmtree, outside, True)
        os.symlink(outside, os.path.join(self.work, "out"))
        os.symlink("/etc", os.path.join(self.work, "etc"))
        os.mkdir(os.path.join(self.work, "real"))
        os.symlink("real", os.path.join(self.work, "alias"))
        os.symlink("loop", os.path.join(self.work, "loop"))
        for value in ("out", "etc", "out/", "etc/ssl"):
            with self.subTest(cwd=value):
                self.assertIn("leads outside", self.error(lambda: self.run_command("pwd", cwd=value)))
        self.assertIn(os.path.join(self.work, "real"), self.run_command("pwd -P", cwd="alias"))
        self.assertIn("does not exist", self.error(lambda: self.run_command("pwd", cwd="loop")))

    def test_a_workspace_that_is_not_mounted_is_named(self):
        self.module.MOUNT_REQUIRED = True
        text = self.error(lambda: self.run_command("pwd"))
        self.assertIn(f"no folder is mounted at {self.work}: add the server with --mount", text)


class Jobs(ExecBase):
    def job(self, command, cwd=""):
        m = self.module
        return m.JOBS.start(m.checked_command(command), m.workspace_path(cwd))

    def status(self, ident, wait=0, tail=30):
        m = self.module
        job = m.JOBS.get(ident)
        if wait:
            job.done.wait(wait)
        return m.status_text(ident, job, tail)

    def test_start_status_wait_and_tail(self):
        ident, job = self.job("for i in 1 2 3 4 5; do echo line$i; sleep 0.2; done; echo finished")
        self.assertEqual(ident, 1)
        text = self.status(ident)
        self.assertRegex(text, r"^job 1: running for [0-9.]+ s · for i in")
        text = self.status(ident, wait=20, tail=2)
        self.assertRegex(text, r"^job 1: exit 0 after [0-9.]+ s")
        self.assertIn("output: 6 lines, the last 2:\nline5\nfinished", text)
        self.assertNotIn("line4", text)

    def test_stop_ends_the_job_and_everything_it_started(self):
        ident, job = self.job("sleep 3101 & setsid sleep 3102 & sleep 3103")
        time.sleep(0.3)
        self.assertTrue(alive("sleep 3103"))
        job.stop()
        job.done.wait(10)
        self.assertIn("stopped by stop_job", self.status(ident))
        for marker in ("sleep 3101", "sleep 3102", "sleep 3103"):
            self.assertEqual(alive(marker), [], marker)

    def test_a_job_has_a_time_limit_too(self):
        with mock.patch.dict(os.environ, {"EXEC_JOB_TIMEOUT": "1"}):
            ident, job = self.job("sleep 3104")
        job.done.wait(10)
        self.assertIn("TIMED OUT after 1.0 s", self.status(ident))
        self.assertEqual(alive("sleep 3104"), [])

    def test_the_number_of_running_jobs_is_limited(self):
        with mock.patch.dict(os.environ, {"EXEC_MAX_JOBS": "2"}):
            self.job("sleep 3105")
            self.job("sleep 3105")
            self.assertIn("2 jobs are running, the most this server runs at once (EXEC_MAX_JOBS)",
                          self.error(lambda: self.job("sleep 3105")))
            self.module.JOBS.stop_all()
            for job in self.module.JOBS.jobs.values():
                job.done.wait(10)
            self.job("true")

    def test_ended_jobs_are_forgotten_beyond_a_number(self):
        m = self.module
        for _ in range(m.FINISHED_KEPT + 3):
            ident, job = self.job("true")
            job.done.wait(10)
        self.job("true")
        self.assertLessEqual(len(m.JOBS.jobs), m.FINISHED_KEPT + 1)
        self.assertIn("there is no job 1 (jobs: ", self.error(lambda: m.JOBS.get(1)))
        self.assertIn("job_id: the number start_job returned", self.error(lambda: m.JOBS.get("1")))

    def test_list_and_a_failing_job(self):
        ident, job = self.job("echo broken >&2; exit 2")
        job.done.wait(10)
        self.assertIn("exit 2 (failed)", self.status(ident))
        self.assertIn("broken", self.status(ident))


JUNIT = """<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest" errors="1" failures="1"
skipped="1" tests="4"><testcase classname="tests.test_csv" name="test_ok" file="tests/test_csv.py" line="3"
time="0.001" /><testcase classname="tests.test_csv" name="test_quotes" file="tests/test_csv.py" line="7"
time="0.002"><failure message="AssertionError: assert 'a,b' == '&quot;a,b&quot;'">def test_quotes():
&gt;       assert write_row(["a,b"]) == '"a,b"'
E       AssertionError: assert 'a,b' == '"a,b"'

tests/test_csv.py:9: AssertionError</failure></testcase><testcase classname="tests.test_csv" name="test_skip"
file="tests/test_csv.py" line="11" time="0"><skipped type="pytest.skip" message="later">later</skipped></testcase>
<testcase classname="tests.test_broken" name="tests.test_broken" time="0"><error message="collection failure">
ImportError while importing test module 'tests/test_broken.py'.
E   ModuleNotFoundError: No module named 'missing'</error></testcase></testsuite></testsuites>"""

UNITTEST = """..F.E
======================================================================
ERROR: test_load (test_cfg.Config.test_load)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/work/test_cfg.py", line 9, in test_load
    load("x")
NameError: name 'load' is not defined

======================================================================
FAIL: test_sum (test_cfg.Config.test_sum)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/work/test_cfg.py", line 6, in test_sum
    self.assertEqual(1 + 1, 3)
AssertionError: 2 != 3

----------------------------------------------------------------------
Ran 5 tests in 0.002s

FAILED (failures=1, errors=1)
"""

JEST = {"numFailedTests": 1, "numPassedTests": 7, "numPendingTests": 1, "numTodoTests": 0,
        "numRuntimeErrorTestSuites": 1, "testResults": [
            {"name": "/work/src/sum.test.js", "status": "failed", "message": "", "assertionResults": [
                {"ancestorTitles": ["sum"], "title": "adds", "fullName": "sum adds", "status": "passed",
                 "failureMessages": []},
                {"ancestorTitles": ["sum"], "title": "adds negatives", "fullName": "sum adds negatives",
                 "status": "failed", "location": {"line": 12, "column": 5},
                 "failureMessages": ["Error: expect(received).toBe(expected)\n\nExpected: -3\nReceived: 3\n"
                                     "    at Object.<anonymous> (/work/src/sum.test.js:13:22)"]}]},
            {"name": "/work/src/broken.test.js", "status": "failed",
             "message": "SyntaxError: Unexpected token (3:4)", "assertionResults": []}]}

GO = "\n".join(json.dumps(event) for event in [
    {"Action": "start", "Package": "example.com/calc"},
    {"Action": "run", "Package": "example.com/calc", "Test": "TestAdd"},
    {"Action": "output", "Package": "example.com/calc", "Test": "TestAdd", "Output": "=== RUN   TestAdd\n"},
    {"Action": "pass", "Package": "example.com/calc", "Test": "TestAdd"},
    {"Action": "run", "Package": "example.com/calc", "Test": "TestDiv"},
    {"Action": "output", "Package": "example.com/calc", "Test": "TestDiv",
     "Output": "    calc_test.go:14: Div(1, 0) = 0, want an error\n"},
    {"Action": "fail", "Package": "example.com/calc", "Test": "TestDiv"},
    {"Action": "skip", "Package": "example.com/calc", "Test": "TestLater"},
    {"Action": "fail", "Package": "example.com/calc"},
    {"ImportPath": "example.com/broken", "Action": "build-output", "Output": "broken/x.go:3:1: syntax error\n"},
    {"ImportPath": "example.com/broken", "Action": "build-fail"},
    {"Action": "fail", "Package": "example.com/broken"}])

CARGO = """   Compiling calc v0.1.0 (/work)
running 3 tests
test tests::adds ... ok
test tests::divides ... FAILED
test tests::later ... ignored

failures:

---- tests::divides stdout ----
thread 'tests::divides' panicked at src/lib.rs:20:9:
assertion `left == right` failed
  left: 0
 right: 1

failures:
    tests::divides

test result: FAILED. 1 passed; 1 failed; 1 ignored; 0 measured; 0 filtered out; finished in 0.00s
"""

CARGO_BUILD = """   Compiling calc v0.1.0 (/work)
error[E0425]: cannot find value `y` in this scope
 --> src/lib.rs:2:5
  |
2 |     y
  |     ^ not found in this scope

error: could not compile `calc` (lib test) due to 1 previous error
"""


class Reports(ExecBase):
    def test_pytest_junit(self):
        counts, failures = self.module.parse_junit(JUNIT)
        self.assertEqual(counts, {"passed": 1, "failed": 1, "errors": 1, "skipped": 1})
        self.assertEqual(failures[0].name, "FAILED tests/test_csv.py::test_quotes")
        self.assertEqual(failures[0].where, "tests/test_csv.py:8")
        self.assertIn("E       AssertionError: assert 'a,b' == '\"a,b\"'", failures[0].detail)
        self.assertTrue(failures[1].name.startswith("ERROR tests/test_broken.py"))
        self.assertIn("No module named 'missing'", failures[1].detail)

    def test_unittest(self):
        counts, failures = self.module.parse_unittest(UNITTEST)
        self.assertEqual(counts, {"passed": 3, "failed": 1, "errors": 1, "skipped": 0})
        self.assertEqual([f.name for f in failures], ["ERROR test_load (test_cfg.Config.test_load)",
                                                      "FAIL test_sum (test_cfg.Config.test_sum)"])
        self.assertIn("AssertionError: 2 != 3", failures[1].detail)
        self.assertNotIn("Ran 5 tests", failures[1].detail)
        with self.assertRaises(ValueError):
            self.module.parse_unittest("no summary here")

    def test_jest_and_vitest(self):
        counts, failures = self.module.parse_jest(json.dumps(JEST), self.work)
        self.assertEqual(counts, {"passed": 7, "failed": 1, "errors": 1, "skipped": 1})
        self.assertIn("sum adds negatives", failures[0].name)
        self.assertTrue(failures[0].where.endswith("sum.test.js:12"))
        self.assertIn("Expected: -3", failures[0].detail)
        self.assertIn("(the test file failed to run)", failures[1].name)
        self.assertIn("SyntaxError", failures[1].detail)

    def test_go(self):
        counts, failures = self.module.parse_go(GO)
        self.assertEqual(counts, {"passed": 1, "failed": 1, "errors": 1, "skipped": 1})
        self.assertEqual(failures[0].name, "FAILED example.com/calc.TestDiv")
        self.assertIn("want an error", failures[0].detail)
        self.assertIn("example.com/broken", failures[1].name)
        self.assertIn("syntax error", failures[1].detail)

    def test_cargo(self):
        counts, failures = self.module.parse_cargo(CARGO)
        self.assertEqual(counts, {"passed": 1, "failed": 1, "errors": 0, "skipped": 1})
        self.assertEqual(failures[0].name, "FAILED tests::divides")
        self.assertIn("left: 0", failures[0].detail)
        counts, failures = self.module.parse_cargo(CARGO_BUILD)
        self.assertEqual(counts["errors"], 1)
        self.assertIn("cannot find value `y`", failures[0].detail)

    def test_the_report_names_failures_only(self):
        m = self.module
        command = m.run_blocking("exit 1", self.work, 10)
        failures = [m.Failure(f"FAILED t.py::test_{i}", "", "\n".join(f"line {j}" for j in range(100)))
                    for i in range(20)]
        text = m.test_report("pytest", self.work, command, {"passed": 40, "failed": 20, "errors": 0, "skipped": 0},
                             failures)
        self.assertTrue(text.startswith("pytest in . (exit 1 (failed), "), text)
        self.assertIn("20 failed, 40 passed", text)
        self.assertEqual(text.count("FAILED t.py::"), m.MAX_FAILURES)
        self.assertIn("... and 5 more: t.py::test_15", text)
        self.assertIn("[... 80 lines omitted ...]", text)
        self.assertLess(len(text), m.MAX_ANSWER)

    def test_frameworks_are_found(self):
        m = self.module
        project = Path(self.work, "p")
        project.mkdir()
        self.assertIn("no tests found in p", self.error(lambda: m.detect_framework(str(project))))
        (project / "package.json").write_text(json.dumps({"devDependencies": {"jest": "29"}}))
        self.assertEqual(m.detect_framework(str(project)), "jest")
        (project / "package.json").write_text(json.dumps({"scripts": {"test": "vitest run"}}))
        self.assertEqual(m.detect_framework(str(project)), "vitest")
        (project / "package.json").write_text("[not json")
        (project / "go.mod").write_text("module x\n")
        self.assertEqual(m.detect_framework(str(project)), "go")
        (project / "go.mod").unlink()
        (project / "Cargo.toml").write_text("[package]\n")
        self.assertEqual(m.detect_framework(str(project)), "cargo")
        (project / "Cargo.toml").unlink()
        (project / "pyproject.toml").write_text("[tool.pytest.ini_options]\n")
        self.assertEqual(m.detect_framework(str(project)), "pytest")
        (project / "pyproject.toml").unlink()
        (project / "tests").mkdir()
        (project / "tests" / "test_a.py").write_text("")
        self.assertIn(m.detect_framework(str(project)), ("pytest", "unittest"))

    def test_test_selection_takes_names_not_options(self):
        m = self.module
        self.assertEqual(m.test_selection("tests/test_a.py  tests/test_b.py::test_x"),
                         ["tests/test_a.py", "tests/test_b.py::test_x"])
        self.assertIn("looks like an option", self.error(lambda: m.test_selection("-k x")))
        self.assertIn("looks like an option", self.error(lambda: m.test_selection("a --pdb")))

    def test_a_framework_the_image_lacks_is_named(self):
        m = self.module
        with mock.patch.object(m, "COMMAND_PATH", "/nonexistent"):
            text = self.error(lambda: m.run_tests_in(self.work, "go", [], 10))
        self.assertIn("go needs go, which this container does not have", text)
        text = self.error(lambda: m.run_tests_in(self.work, "jest", [], 10))
        self.assertIn("jest is not installed in the project (./node_modules/.bin/jest)", text)


class RealTests(ExecBase):
    PROJECT = {
        "calc.py": "def add(a, b):\n    return a + b\n",
        "test_calc.py": """\
            import unittest
            from calc import add

            class Calc(unittest.TestCase):
                def test_add(self):
                    self.assertEqual(add(1, 2), 3)

                def test_add_wrong(self):
                    self.assertEqual(add(2, 2), 5)

                def test_more(self):
                    self.assertEqual(add(0, 0), 0)
            """,
    }

    def setUp(self):
        super().setUp()
        for name, text in self.PROJECT.items():
            self.write(name, text)

    def test_unittest_returns_only_the_failure(self):
        text = self.module.run_tests_in(self.work, "unittest", [], 60)
        self.assertTrue(text.startswith("unittest in . (exit 1 (failed), "), text)
        self.assertIn("1 failed, 2 passed", text)
        self.assertIn("FAIL test_add_wrong (test_calc.Calc", text)
        self.assertIn("AssertionError: 4 != 5", text)
        self.assertNotIn("test_more", text)

    def test_pytest_returns_only_the_failure(self):
        if not self.module.has_python_module("pytest"):
            self.skipTest("python3 has no pytest here (the image has)")
        text = self.module.run_tests_in(self.work, "pytest", [], 120)
        self.assertTrue(text.startswith("pytest in . (exit 1 (failed), "), text)
        self.assertIn("1 failed, 2 passed", text)
        self.assertIn("FAILED test_calc.py::test_add_wrong  (test_calc.py:8)", text)
        self.assertIn("AssertionError", text)
        self.assertEqual(sorted(os.listdir(self.work)), ["calc.py", "test_calc.py"], "no cache or bytecode left")
        self.write("test_calc.py", self.PROJECT["test_calc.py"].replace("5)", "4)"))
        text = self.module.run_tests_in(self.work, "pytest", ["test_calc.py"], 120)
        self.assertIn("3 passed", text)
        self.assertIn("All tests passed.", text)

    def test_through_the_tool_with_auto(self):
        m = self.module
        text = m.answer(lambda: m.run_tests_in(m.workspace_path(""), m.detect_framework(self.work), [], 120))
        self.assertIn("test_add_wrong", text)


class Lint(ExecBase):
    def lint(self, path=""):
        m = self.module
        return m.answer(lambda: m.lint_path(m.workspace_path(path, "path", folder=False), 120))

    def test_json_yaml_python_and_shell(self):
        self.write("ok.json", '{"a": 1}\n')
        self.write("data/bad.json", '{\n  "a": 1\n  "b": 2\n}\n')
        self.write("conf/bad.yaml", "a: 1\n  b: [2\n")
        self.write("src/broken.py", "def f(:\n    pass\n")
        self.write("src/unused.py", "import os\n")
        self.write("run.sh", "#!/bin/sh\nrm $1\n")
        self.write("bin/tool", "#!/usr/bin/env bash\necho $x\n")
        self.write("node_modules/dep/bad.json", "{")
        self.write("web/app.ts", "let x: number = 1\n")
        text = self.lint()
        lines = text.split("\n")
        self.assertRegex(lines[0], r"^lint of \.: \d+ files checked \(.*json: 2.*; \d+ problems?$")
        self.assertIn("data/bad.json:3:3: [json] Expecting ',' delimiter", text)
        self.assertNotIn("node_modules/dep", text)
        self.assertIn("src/broken.py:1:", text)
        self.assertIn("Not checked: 1 JavaScript/TypeScript files (eslint runs the project's own configuration", text)
        if self.module.has_python_module("yaml"):
            self.assertIn("conf/bad.yaml:", text)
            self.assertIn("[yaml]", text)
        if self.module.has_python_module("pyflakes"):
            self.assertIn("src/unused.py:1:1: [pyflakes] 'os' imported but unused", text)
        if shutil.which("shellcheck", path=self.module.COMMAND_PATH):
            self.assertIn("run.sh:2:4: [shellcheck SC2086 info] Double quote to prevent globbing", text)
            self.assertIn("bin/tool:2:6: [shellcheck SC2086 info]", text)

    def test_one_file_links_and_nothing_found(self):
        self.write("a.json", "[1, 2,]")
        outside = tempfile.mkdtemp(prefix="exec-outside-")
        self.addCleanup(shutil.rmtree, outside, True)
        Path(outside, "secret.json").write_text("{")
        os.symlink(os.path.join(outside, "secret.json"), os.path.join(self.work, "linked.json"))
        os.symlink(outside, os.path.join(self.work, "linked-folder"))
        text = self.lint("a.json")
        self.assertIn("lint of a.json: 1 files checked (json: 1); 1 problem", text)
        self.assertIn("a.json:1:", text)
        text = self.lint()
        self.assertNotIn("secret", text)
        self.assertNotIn("linked", text)
        self.assertIn("leads outside", self.error(lambda: self.lint("linked.json")))
        os.mkdir(os.path.join(self.work, "empty"))
        self.assertIn("No Python, shell, JSON, YAML or JavaScript/TypeScript files found there.", self.lint("empty"))
        self.write("fine.json", "{}")
        self.assertIn("No problems found.", self.lint("fine.json"))

    def test_shellcheck_report(self):
        report = (f"{self.work}/x.sh:3:6: warning: foo appears unused. Verify use (or export if used externally). "
                  f"[SC2034]\n{self.work}/y.sh:1:1: note: Not following: ./lib.sh [SC1091]\nnoise\n")
        problems = self.module.parse_shellcheck(report)
        self.assertEqual(problems[1].text(), "y.sh:1:1: [shellcheck SC1091 info] Not following: ./lib.sh")
        self.assertEqual(problems[0].text(), "x.sh:3:6: [shellcheck SC2034 warning] foo appears unused. Verify use "
                                             "(or export if used externally).")
        self.assertEqual([p.text() for p in self.module.parse_flake_lines(
            f"{self.work}/a.py:2:1: 'os' imported but unused\nnoise\n", "pyflakes")],
            ["a.py:2:1: [pyflakes] 'os' imported but unused"])


def capabilities() -> int:
    with open("/proc/self/status") as handle:
        for line in handle:
            if line.startswith("CapEff:"):
                return int(line.split()[1], 16)
    return 0


@unittest.skipIf(mcp is None, "the server's requirements are not installed")
@unittest.skipUnless(sys.platform.startswith("linux"), "the server runs in a Linux container")
class OverStdio(unittest.TestCase):
    """The server as the container starts it, its WORKSPACE pointed at a temporary folder."""

    def rpc(self, calls, workspace, env=None):
        launcher = ("import importlib.util, sys\n"
                    "spec = importlib.util.spec_from_file_location('server', sys.argv[1])\n"
                    "module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)\n"
                    "module.WORKSPACE = sys.argv[2]; module.MOUNT_REQUIRED = False\n"
                    "module.main()\n")
        messages = [{"jsonrpc": "2.0", "id": 0, "method": "initialize",
                     "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                "clientInfo": {"name": "test", "version": "1"}}},
                    {"jsonrpc": "2.0", "method": "notifications/initialized"},
                    {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}]
        messages += [{"jsonrpc": "2.0", "id": index, "method": "tools/call", "params": {"name": tool, "arguments": args}}
                     for index, (tool, args) in enumerate(calls, start=2)]
        process = subprocess.Popen([sys.executable, "-I", "-c", launcher, str(SERVER), workspace],
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
                        raise AssertionError("the server ended without answering")
                    answer = json.loads(line)
                    if "id" in answer:
                        answers[answer["id"]] = answer
        finally:
            process.stdin.close()
            process.wait(60)
            process.stdout.close()
        return answers

    def test_tools_answers_and_refusals(self):
        work = os.path.realpath(tempfile.mkdtemp(prefix="exec-stdio-"))
        self.addCleanup(shutil.rmtree, work, True)
        answers = self.rpc([("run_command", {"command": "echo hello; cat /proc/$PPID/environ >/dev/null; echo $?"}),
                            ("run_command", {"command": "pwd", "cwd": "../etc"}),
                            ("start_job", {"command": "echo from-a-job"}),
                            ("job_status", {"job_id": 1, "wait_seconds": 10}),
                            ("list_jobs", {}),
                            ("stop_job", {"job_id": 7}),
                            ("lint", {}),
                            ("run_tests", {}),
                            ("run_command", {"command": "x", "timeout_seconds": 100000})], work)
        tools = answers[1]["result"]["tools"]
        recorded = json.loads((ROOT / "servers" / "exec" / "tools.json").read_text())
        self.assertEqual(sorted(t["name"] for t in tools), recorded["tools"])
        for tool in tools:
            self.assertLess(len(tool["description"]), 900, tool["name"])
            writes = tool["name"] in recorded["write_tools"]
            self.assertEqual(tool["annotations"]["readOnlyHint"], not writes, tool["name"])
            self.assertNotIn("outputSchema", tool, "text answers only")
        self.assertIn("/work", answers[0]["result"]["instructions"])

        def text(index):
            return answers[index]["result"]["content"][0]["text"]

        self.assertFalse(answers[2]["result"].get("isError"))
        self.assertIn("hello", text(2))
        if not capabilities() & (1 << 19):  # without CAP_SYS_PTRACE, as in the container
            self.assertIn("Permission denied", text(2), "the server's /proc entries are closed to its commands")
            self.assertTrue(text(2).rstrip().endswith("1"), text(2))
        self.assertTrue(answers[3]["result"]["isError"])
        self.assertIn("is outside", text(3))
        self.assertIn("job 1", text(4))
        self.assertIn("job 1: exit 0", text(5))
        self.assertIn("from-a-job", text(5))
        self.assertIn("job 1: exit 0", text(6))
        self.assertTrue(answers[7]["result"]["isError"])
        self.assertIn("there is no job 7", text(7))
        self.assertIn("No Python, shell, JSON, YAML", text(8))
        self.assertTrue(answers[9]["result"]["isError"])
        self.assertIn("no tests found in .", text(9))
        self.assertTrue(answers[10]["result"]["isError"])
        self.assertIn("timeout_seconds: a whole number of seconds from 1 to 600", text(10))


if __name__ == "__main__":
    unittest.main()
