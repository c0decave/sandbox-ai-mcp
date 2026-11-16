"""Found by the in-depth review of 2026-11-17 (group A: binwalk, capa, radare2, gowitness, whatweb, exec, code-search,
files, filesystem); each test failed before its fix.

- Every server of this repository written in Python announced the MCP capabilities "resources" (and FastMCP's also
  "prompts") and published none (binwalk and capa only their past scans, which get_scan_results and
  get_analysis_results give as well). Agents act on the capability: OpenCode, Claude Code and Pi offer the model
  resource tools for it, Hermes four more tools per server, and local models take them for the way to the server's
  tools (research-llm round 1, "the MCP-resource trap"). They announce tools only now.
- binwalk and capa (the FuzzingLabs servers): a call's time limit ended the wait, not binwalk or capa - the program
  and the extractors binwalk started ran on, as many as the agent started; an extraction into the writable /out (a
  folder of the user's computer) had no size limit, so a small archive that unpacks to gigabytes filled the user's
  disk; capa wrote each report into the container's /tmp (64 MiB) and never read it again, so after a few large
  reports every analysis failed; everything binwalk or capa printed was kept in memory for each of 100 results; a
  refused call came back as an ordinary answer (isError false).
- files: an answer above 25,000 characters reaches the model of Claude Code, Qwen Code or Hermes only as a short
  preview and a file path (docs/LOCAL_LLM_TOOLS.md, "Answer sizes"). read_file was cut for that, but counted the
  characters of the content, not of the answer the client gets (JSON: every line break, quote and backslash takes
  two), and list_dir (500 entries: 58,000), glob, search (max_results 200: 70,000) and diff (40,000) were not cut at
  all. Every answer stays within 24,000 characters as sent now and says how to get the rest.
- gowitness and whatweb: what a site returns was bounded per field, not per answer - a page with 50 requests of long
  URLs, many headers and console messages, five of them in screenshot_many, or a page that makes WhatWeb's plugins
  match many strings, gave answers far above what clients show. The longest lists are cut now until the answer fits
  (counts keeps the full numbers).
- whatweb: a redirect's Location (or meta refresh) longer than 500 characters was cut to 500 like any value a site
  returns, and the server then followed (and checked) the cut URL.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent

try:
    import mcp  # noqa: F401 - the servers' own dependency
except ImportError:
    mcp = None

#: The servers of group A that run on the shared Python lock (radare2 is C, filesystem Node.js).
PYTHON_SERVERS = ("binwalk", "capa", "gowitness", "whatweb", "exec", "code-search", "files")


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"review_a_{name.replace('-', '_')}",
                                                  ROOT / "servers" / name / "src/server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rpc(name: str, messages: list[dict], env: dict | None = None) -> dict:
    """The answers (by id) of the server NAME, started as its image starts it (python -I -u server.py), to MESSAGES."""
    process = subprocess.Popen([sys.executable, "-I", "-u", str(ROOT / "servers" / name / "src/server.py")],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                               env={**os.environ, **(env or {})})
    answers: dict = {}
    try:
        for message in messages:
            process.stdin.write(json.dumps(message) + "\n")
            process.stdin.flush()
            if "id" not in message:
                continue
            while message["id"] not in answers:
                line = process.stdout.readline()
                if not line:
                    raise AssertionError(f"{name} ended without answering {message['method']}")
                answer = json.loads(line)
                if "id" in answer:
                    answers[answer["id"]] = answer
    finally:
        process.stdin.close()
        process.stdout.close()
        process.wait(60)
    return answers


def handshake(*requests: tuple[str, dict]) -> list[dict]:
    messages = [{"jsonrpc": "2.0", "id": 0, "method": "initialize",
                 "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                            "clientInfo": {"name": "review", "version": "1"}}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"}]
    for index, (method, params) in enumerate(requests, start=1):
        messages.append({"jsonrpc": "2.0", "id": index, "method": method, "params": params})
    return messages


@unittest.skipIf(mcp is None, "the servers' requirements are not installed (pip install --require-hashes -r "
                              "servers/files/requirements.txt)")
class ToolsOnly(unittest.TestCase):
    def test_the_servers_announce_tools_only(self):
        for name in PYTHON_SERVERS:
            with self.subTest(name):
                answers = rpc(name, handshake(("tools/list", {}), ("resources/list", {}), ("prompts/list", {})),
                              env={"MCP_INPUT_ROOTS": str(ROOT)})
                capabilities = answers[0]["result"]["capabilities"]
                self.assertNotIn("resources", capabilities)
                self.assertNotIn("prompts", capabilities)
                self.assertIn("tools", capabilities)
                self.assertTrue(answers[1]["result"]["tools"])
                for request in (2, 3):  # a client that asks anyway: the method does not exist
                    self.assertEqual(answers[request]["error"]["code"], -32601, answers[request])



def alive(marker: str) -> list[int]:
    """Processes (not zombies) whose command line contains MARKER."""
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


class FakeTools(unittest.TestCase):
    """A folder of stand-in programs (binwalk, capa, xxd) on PATH and an input folder with a file to analyse."""

    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="review-a-")
        self.addCleanup(shutil.rmtree, self.base, True)
        self.bin = os.path.join(self.base, "bin")
        self.work = os.path.join(self.base, "work")
        self.out = os.path.join(self.base, "out")
        for folder in (self.bin, self.work, self.out):
            os.mkdir(folder)
        Path(self.work, "fw.bin").write_bytes(b"\x00" * 64)
        # a number of seconds no other process sleeps: `sleep MARKER` finds the stand-ins' children
        self.marker = f"{3000 + os.getpid() % 1000}.{time.monotonic_ns() % 10**9:09d}"
        self.addCleanup(self.kill_leftovers)

    def kill_leftovers(self):
        for pid in alive(self.marker) + alive(self.bin):
            try:
                os.kill(pid, 9)
            except ProcessLookupError:
                pass

    def tool(self, name: str, script: str) -> None:
        path = Path(self.bin, name)
        path.write_text("#!/bin/sh\n" + script.replace("MARKER", self.marker))
        path.chmod(0o755)

    def environment(self) -> dict:
        return {"PATH": self.bin + ":" + os.environ.get("PATH", "/usr/bin:/bin"), "MCP_INPUT_ROOTS": self.work}

    def module(self, name: str):
        with mock.patch.dict(os.environ, {**self.environment(), "BINWALK_OUTPUT_DIR": self.out,
                                          "CAPA_OUTPUT_DIR": self.out}):
            module = load(name)
        patcher = mock.patch.dict(os.environ, self.environment())
        patcher.start()
        self.addCleanup(patcher.stop)
        return module

    def call(self, module, tool: str, arguments: dict) -> dict:
        contents = asyncio.run(module.call_tool(tool, arguments))
        return json.loads(contents[0].text)


@unittest.skipIf(mcp is None, "the servers' requirements are not installed")
@unittest.skipUnless(sys.platform.startswith("linux"), "the servers run in a Linux container")
class Binwalk(FakeTools):
    def test_the_time_limit_stops_binwalk_and_what_it_started(self):
        # binwalk -e starts extractors (7z, unsquashfs, ...): on the time limit all of them go, not only the wait
        self.tool("binwalk", "sleep MARKER &\nsleep MARKER\n")
        m = self.module("binwalk")
        started = time.monotonic()
        answer = self.call(m, "binwalk_scan", {"filepath": "fw.bin", "timeout": 1})
        self.assertEqual(answer["status"], "timeout")
        self.assertLess(time.monotonic() - started, 20)
        deadline = time.monotonic() + 5
        while alive("sleep " + self.marker) and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertEqual(alive("sleep " + self.marker), [])

    def test_an_extraction_that_grows_past_its_limit_is_stopped(self):
        # a small archive that unpacks to gigabytes must not fill the user's /out
        self.tool("binwalk", 'while [ "$1" != "-C" ]; do shift; done\nmkdir -p "$2"\n'
                             'while true; do head -c 1048576 /dev/zero >> "$2/bomb"; sleep 0.05; done\n')
        m = self.module("binwalk")
        with mock.patch.object(m, "OUT_DIR", Path(self.out)), mock.patch.dict(os.environ,
                                                                              {"BINWALK_MAX_EXTRACT": "4M"}):
            answer = self.call(m, "binwalk_extract", {"filepath": "fw.bin", "timeout": 60})
        self.assertEqual(answer["status"], "stopped", answer)
        self.assertIn("4 MiB", answer["error"])
        self.assertLess(sum(f.stat().st_size for f in Path(self.out).rglob("*") if f.is_file()), 64 << 20)
        self.assertEqual(alive(self.bin), [])

    def test_output_that_is_not_utf8_and_huge_output_are_taken(self):
        self.tool("binwalk", "printf '\\nDECIMAL       HEXADECIMAL     DESCRIPTION\\n'\n"
                             "printf '0             0x0             Zip archive data, name: \\377\\376.txt\\n'\n"
                             "head -c 20000000 /dev/zero | tr '\\0' 'x'\n")
        m = self.module("binwalk")
        answer = self.call(m, "binwalk_scan", {"filepath": "fw.bin"})
        self.assertEqual(answer["status"], "completed", answer.get("error"))
        self.assertEqual(answer["signatures"][0]["offset"], 0)
        self.assertIn("\ufffd", answer["signatures"][0]["description"])
        kept = m.scan_results[answer["scan_id"]]
        self.assertLessEqual(len(kept.raw_output), m.MAX_KEPT_OUTPUT)

    def test_a_refused_call_is_an_error(self):
        answers = rpc("binwalk", handshake(("tools/call", {"name": "binwalk_scan",
                                                           "arguments": {"filepath": "/etc/passwd"}}),
                                           ("tools/call", {"name": "get_scan_results",
                                                           "arguments": {"scan_id": "nope"}})),
                      env=self.environment())
        for index in (1, 2):
            self.assertTrue(answers[index]["result"]["isError"], answers[index])
        self.assertIn("only paths under", answers[1]["result"]["content"][0]["text"])


@unittest.skipIf(mcp is None, "the servers' requirements are not installed")
@unittest.skipUnless(sys.platform.startswith("linux"), "the servers run in a Linux container")
class Capa(FakeTools):
    REPORT = json.dumps({"rules": {"create TCP socket": {"meta": {"namespace": "communication/socket/tcp",
                                                                   "scope": "basic block", "attack": [],
                                                                   "mbc": [{"objective": "Communication",
                                                                            "id": "C0001.011"}]}}}})

    def test_no_report_is_left_in_tmp(self):
        # each report used to stay in the container's /tmp (64 MiB): after a few large ones every analysis failed
        Path(self.bin, "report.json").write_text(self.REPORT)
        self.tool("capa", f"cat {self.bin}/report.json\n")
        m = self.module("capa")
        for _ in range(3):
            answer = self.call(m, "capa_analyze", {"filepath": "fw.bin"})
            self.assertEqual(answer["status"], "completed", answer.get("error"))
            self.assertEqual(answer["capabilities"][0]["name"], "create TCP socket")
        self.assertEqual(os.listdir(self.out), [])
        self.assertIsNone(m.scan_results[answer["scan_id"]].raw_output)

    def test_the_time_limit_stops_capa(self):
        self.tool("capa", "sleep MARKER &\nsleep MARKER\n")
        m = self.module("capa")
        answer = self.call(m, "capa_analyze", {"filepath": "fw.bin", "timeout": 1})
        self.assertEqual(answer["status"], "timeout")
        deadline = time.monotonic() + 5
        while alive("sleep " + self.marker) and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertEqual(alive("sleep " + self.marker), [])

    def test_a_long_failure_is_cut_and_a_refused_call_is_an_error(self):
        self.tool("capa", "head -c 3000000 /dev/zero | tr '\\0' 'e' >&2\nexit 1\n")
        m = self.module("capa")
        answer = self.call(m, "capa_analyze", {"filepath": "fw.bin"})
        self.assertEqual(answer["status"], "failed")
        self.assertLessEqual(len(answer["error"]), 5000)
        answers = rpc("capa", handshake(("tools/call", {"name": "capa_analyze", "arguments": {"filepath": "/etc/passwd"}}),
                                        ("tools/call", {"name": "get_analysis_results", "arguments": {"scan_id": "x"}})),
                      env=self.environment())
        for index in (1, 2):
            self.assertTrue(answers[index]["result"]["isError"], answers[index])



@unittest.skipIf(mcp is None, "the servers' requirements are not installed")
class FilesAnswers(unittest.TestCase):
    """What the client gets of files' answers: FastMCP's text of the returned dict."""

    LIMIT = 25_000

    @classmethod
    def setUpClass(cls):
        cls.m = load("files")

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="review-a-files-")
        self.addCleanup(shutil.rmtree, self.work, True)
        patcher = mock.patch.object(self.m, "ROOTS", {"/work": self.work})
        patcher.start()
        self.addCleanup(patcher.stop)
        env = mock.patch.dict(os.environ, {"FILES_READONLY": "", "FILES_MAX_BYTES": "", "FILES_TRASH": ""})
        env.start()
        self.addCleanup(env.stop)

    def sent(self, tool: str, arguments: dict) -> tuple[str, dict]:
        """(the text the client gets, the answer)."""
        result = asyncio.run(self.m.mcp.call_tool(tool, arguments))
        contents = result[0] if isinstance(result, tuple) else result
        text = contents[0].text
        return text, json.loads(text)

    def many_files(self, count: int = 600) -> None:
        os.mkdir(os.path.join(self.work, "d"))
        for index in range(count):
            Path(self.work, "d", f"a_file_with_a_fairly_long_descriptive_name_{index:04d}.txt").write_text(
                'needle "quoted" ' * 30 + "\n")

    def test_listings_and_searches_fit_what_clients_show(self):
        self.many_files()
        for tool, arguments, key in (("list_dir", {"path": "d"}, "entries"), ("list_dir", {"depth": 3}, "entries"),
                                     ("glob", {"pattern": "**/*.txt"}, "matches"),
                                     ("search", {"pattern": "needle", "max_results": 200}, "matches")):
            with self.subTest(tool=tool, arguments=arguments):
                text, answer = self.sent(tool, arguments)
                self.assertLessEqual(len(text), self.LIMIT)
                self.assertTrue(answer[key])
                self.assertEqual(answer["count"], len(answer[key]))
                self.assertIn("truncated", answer)

    def test_a_long_diff_fits(self):
        Path(self.work, "a.txt").write_text("".join(f'line "{i}" \\ old {"x" * 80}\n' for i in range(3000)))
        text, answer = self.sent("diff", {"path_a": "a.txt", "content": "".join(f"new {i}\n" for i in range(3000))})
        self.assertLessEqual(len(text), self.LIMIT)
        self.assertIn("truncated", answer)
        self.assertTrue(answer["diff"].startswith("--- /work/a.txt"))

    def test_read_file_counts_what_is_sent(self):
        # JSON doubles quotes, backslashes, tabs and line breaks: a JSON file read in parts, every part fits
        Path(self.work, "data.json").write_text("".join(f'  "key_{i:05d}": "a \\"quoted\\" value\\t{i:09d} x",\n'
                                                       for i in range(3000)))
        lines, start = [], 1
        while True:
            text, answer = self.sent("read_file", {"path": "data.json", "start_line": start, "line_numbers": True})
            self.assertLessEqual(len(text), self.LIMIT)
            lines += [line.split("\t", 1)[1] for line in answer["content"].splitlines()]
            if "next_start_line" not in answer:
                break
            self.assertEqual(answer["next_start_line"], answer["end_line"] + 1)
            start = answer["next_start_line"]
        self.assertEqual("\n".join(lines) + "\n", Path(self.work, "data.json").read_text())
        # one line longer than an answer: cut so that the answer fits
        Path(self.work, "one.txt").write_text('"' * 40_000 + "\n")
        text, answer = self.sent("read_file", {"path": "one.txt"})
        self.assertLessEqual(len(text), self.LIMIT)
        self.assertIn("cut_line", answer)



def text_of(result) -> str:
    """The text part of a tool's result (FastMCP's contents, or (contents, structured))."""
    contents = result[0] if isinstance(result, tuple) else result
    return "\n".join(content.text for content in contents if getattr(content, "type", "") == "text")


@unittest.skipIf(mcp is None, "the servers' requirements are not installed")
class WebAnswers(unittest.TestCase):
    LIMIT = 25_000

    def big_page(self, index: int = 0) -> dict:
        """gowitness's record of a busy page: long URLs, many headers, cookies and console messages."""
        return {"url": f"https://site{index}.example/", "final_url": f"https://site{index}.example/", "response_code": 200,
                "title": "T" * 600, "headers": [{"key": f"X-H{i}", "value": "v" * 1200} for i in range(80)],
                "technologies": [{"value": f"Tech{i}"} for i in range(150)],
                "cookies": [{"name": f"c{i}", "domain": "d" * 250, "path": "/"} for i in range(80)],
                "console": [{"type": "log", "value": "m" * 600} for i in range(30)],
                "network": [{"url": f"https://cdn.example/{i}/" + "p" * 600, "status_code": 200, "mime_type": "text/js",
                             "remote_ip": "192.0.2.1"} for i in range(80)],
                "tls": {"protocol": "TLS 1.3", "san_list": [{"value": "s" * 300} for _ in range(60)]}}

    def test_gowitness_answers_fit(self):
        m = load("gowitness")

        async def witness(url, opts):
            return m.summary(self.big_page(len(url))), None

        with mock.patch.object(m, "witness", witness), mock.patch.object(m, "check_url", lambda url: url):
            one = text_of(asyncio.run(m.mcp.call_tool("screenshot", {"url": "https://a.example/"})))
            many = text_of(asyncio.run(m.mcp.call_tool("screenshot_many", {
                "urls": [f"https://{'a' * i}.example/" for i in range(1, 6)]})))
        for text in (one, many):
            self.assertLessEqual(len(text), self.LIMIT)
        found = json.loads(one)
        self.assertEqual(found["counts"]["network"], 80)
        self.assertLess(len(found["network"]), 50)
        self.assertIn("cut", found["lists_cut"])
        self.assertEqual(len(json.loads(many)["results"]), 5)

    def test_whatweb_answers_fit(self):
        m = load("whatweb")
        target = {"target": "https://a.example/", "http_status": 200,
                  "plugins": {f"Plugin{i:03d}": {field: ["x" * 600] * 25 for field in ("string", "version", "module")}
                              for i in range(250)}}

        async def scan(url, aggression):
            return m.summarize(target)

        with mock.patch.object(m, "scan", scan), mock.patch.object(m, "check_url", lambda url: url):
            text = text_of(asyncio.run(m.mcp.call_tool("fingerprint", {"url": "https://a.example/"})))
        self.assertLessEqual(len(text), self.LIMIT)
        found = json.loads(text)
        self.assertTrue(found["targets"][0]["plugins"])
        self.assertIn("cut", found["values_cut"])


    def test_whatweb_follows_a_long_redirect_as_given(self):
        m = load("whatweb")
        location = "https://b.example/" + "p" * 1500
        target = m.summarize({"target": "https://a.example/", "http_status": 301,
                              "plugins": {"RedirectLocation": {"string": [location]}, "Title": {"string": ["x" * 900]}}})
        self.assertEqual(m.next_hop("https://a.example/", target), location)
        self.assertEqual(len(target["plugins"]["Title"]["string"][0]), m.MAX_VALUE)


if __name__ == "__main__":
    unittest.main()
