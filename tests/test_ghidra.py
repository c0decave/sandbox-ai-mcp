"""The ghidra server (servers/ghidra): its Python half offline - paths (no '..', nothing outside /work, no link, no
folder, pipe, empty or oversized file), arguments (function names and addresses, Ghidra's language ids), answers in
parts (400 lines / 24,000 characters), the JVM's command line (empty environment, Ghidra's class loader, the scratch
folders, no option from an argument), the bridge protocol against a stand-in JVM (still importing, a timeout that
stops it, running out of memory, a refusal) - and, where Ghidra is at hand (inside the image, or with
SANDBOX_AI_MCP_JAVA, SANDBOX_AI_MCP_GHIDRA and SANDBOX_AI_MCP_GHIDRA_MODULE), every tool against the hello and
firmware.bin fixtures with the real Ghidra. The folders are temporary ones the module's ROOTS point at."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import textwrap
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
FOLDER = ROOT / "servers" / "ghidra"
SERVER = FOLDER / "src" / "server.py"

try:
    import mcp  # noqa: F401 - the server's own dependency
    from mcp.server.fastmcp.exceptions import ToolError
except ImportError:
    mcp = None
    ToolError = Exception


def load():
    spec = importlib.util.spec_from_file_location("server_ghidra_test", SERVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixtures() -> dict[str, bytes]:
    spec = importlib.util.spec_from_file_location("fixtures_ghidra_test", ROOT / "scripts" / "fixtures.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {f["path"]: f["data"] for f in module.load()}


#: The real Ghidra: the image's paths, or the ones these variables name (an unpacked release and a built module).
IMAGE = {"JAVA": "/opt/java/bin/java", "GHIDRA": "/opt/ghidra", "MODULE_DIR": "/opt/mcp/ghidra-module"}
REAL = {"JAVA": os.environ.get("SANDBOX_AI_MCP_JAVA") or IMAGE["JAVA"],
        "GHIDRA": os.environ.get("SANDBOX_AI_MCP_GHIDRA") or IMAGE["GHIDRA"],
        "MODULE_DIR": os.environ.get("SANDBOX_AI_MCP_GHIDRA_MODULE") or IMAGE["MODULE_DIR"]}
HAVE_GHIDRA = os.path.isfile(REAL["JAVA"]) and \
    os.path.isfile(os.path.join(REAL["GHIDRA"], "Ghidra/Framework/Utility/lib/Utility.jar")) and \
    os.path.isfile(os.path.join(REAL["MODULE_DIR"], "lib", "sandbox-ai-mcp-ghidra.jar"))

#: A stand-in for the JVM: speaks the bridge's protocol; what it does is chosen by the name of the file it is given.
FAKE_JVM = textwrap.dedent("""
    import json, os, sys, time
    link, name, seconds = sys.argv[1:4]
    options = sys.argv[4:]
    mode = os.path.basename(link).split(".")[0]
    data = open(link, "rb").read()
    if mode == "slow":
        time.sleep(3)
    if mode == "oom":
        sys.exit(3)
    if mode == "broken":
        print(json.dumps({"id": 0, "ok": False, "error": "Ghidra could not import the file: bad"}), flush=True)
        sys.exit(0)
    print(json.dumps({"id": 0, "ok": True, "result": {"ghidra": "fake", "format": "ELF", "language": "x86:LE:64:default",
                      "processor": "x86", "endian": "little", "pointer_bits": 64, "compiler": "gcc",
                      "image_base": "00100000", "sha256": "ab", "functions": 2, "thunks": 0, "imports": 1,
                      "entry_points": 1, "strings": 1, "blocks": [], "entries": ["00101000 main"],
                      "analysis_ms": 5, "analysis_note": "", "bytes": len(data), "seconds": seconds,
                      "options": options}}), flush=True)
    for line in sys.stdin:
        request = json.loads(line)
        op = request["op"]
        if op == "decompile":
            if mode == "hang":
                time.sleep(60)
            result = {"function": "main", "entry": "00101000", "signature": "int main(void)",
                      "code": "\\n".join(f"line {i}" for i in range(1, 1001))}
        elif op == "functions":
            items = [[f"{0x101000 + i:08x}", f"f{i}", 10, False] for i in range(1000)]
            start = request["offset"]
            result = {"total": 1000, "offset": start, "items": items[start:start + request["max"]]}
        elif op == "env":
            result = dict(os.environ)
        else:
            print(json.dumps({"id": request["id"], "ok": False, "error": "no function x"}), flush=True)
            continue
        print(json.dumps({"id": request["id"], "ok": True, "result": result}), flush=True)
""")


@unittest.skipIf(mcp is None, "the server's requirements are not installed (pip install --require-hashes -r "
                              "servers/ghidra/requirements.txt)")
class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load()

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="ghidra-test-")
        self.work = os.path.join(self.folder, "work")
        self.scratch = os.path.join(self.folder, "scratch")
        os.makedirs(os.path.join(self.work, "bin"))
        for name, value in (("ROOTS", {"/work": self.work}), ("SCRATCH", self.scratch)):
            patcher = mock.patch.object(self.m, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.m.SESSION.close()
        self.addCleanup(self.m.SESSION.close)
        self.addCleanup(shutil.rmtree, self.folder, True)

    def put(self, name: str, data: bytes) -> str:
        path = os.path.join(self.work, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(data)
        return path

    def refused(self, call, *args, **kwargs) -> str:
        with self.assertRaises(ToolError) as caught:
            call(*args, **kwargs)
        return str(caught.exception)


class Paths(Base):
    def test_only_regular_files_in_work_are_opened(self):
        self.put("bin/app", b"\x7fELF")
        fd, shown, _ = self.m.open_input("bin/app")
        os.close(fd)
        self.assertEqual(shown, "/work/bin/app")
        fd, shown, _ = self.m.open_input("/work/bin/./app")
        os.close(fd)
        self.assertEqual(shown, "/work/bin/app")
        cases = {"../etc/passwd": "'..' is not allowed", "/etc/passwd": "only files in /work",
                 "bin/../../x": "'..' is not allowed", "~/x": "'~' is not a folder", "": "name a file",
                 "/work": "name a file", "bin": "is a folder", "bin/none": "does not exist",
                 "a\nb": "path:", "/work-x/a": "only files in /work"}
        for path, expected in cases.items():
            with self.subTest(path=path):
                with self.assertRaises(self.m.Refused) as caught:
                    self.m.open_input(path)
                self.assertIn(expected, str(caught.exception))

    def test_links_are_never_followed(self):
        outside = os.path.join(self.folder, "secret")
        Path(outside).write_bytes(b"secret")
        os.symlink(outside, os.path.join(self.work, "link"))
        os.symlink("bin", os.path.join(self.work, "linkdir"))
        self.put("bin/real", b"\x7fELF")
        os.symlink("real", os.path.join(self.work, "bin", "inside"))
        for path in ("link", "linkdir/real", "bin/inside"):
            with self.subTest(path=path):
                with self.assertRaises(self.m.Refused) as caught:
                    self.m.open_input(path)
                self.assertIn("is a link; links are not followed", str(caught.exception))

    def test_pipes_empty_and_oversized_files_are_refused(self):
        os.mkfifo(os.path.join(self.work, "pipe"))
        self.put("empty", b"")
        self.put("big", b"x" * 2048)
        started = time.monotonic()
        with self.assertRaises(self.m.Refused) as caught:
            self.m.open_input("pipe")
        self.assertIn("not a regular file", str(caught.exception))
        self.assertLess(time.monotonic() - started, 2, "a pipe never blocks the open")
        with self.assertRaises(self.m.Refused) as caught:
            self.m.open_input("empty")
        self.assertIn("is empty", str(caught.exception))
        with mock.patch.object(self.m, "MAX_INPUT_BYTES", 1024):
            with self.assertRaises(self.m.Refused) as caught:
                self.m.open_input("big")
        self.assertIn("larger than", str(caught.exception))

    def test_list_files_shows_every_file_and_follows_no_link(self):
        self.put("bin/app", b"\x7fELF")
        self.put("bin/deep/fw.bin", b"fw")
        self.put(".hidden/x", b"x")
        os.symlink(self.folder, os.path.join(self.work, "up"))
        text = self.m.list_files()
        self.assertIn("/work/bin/app  4 bytes", text)
        self.assertIn("/work/bin/deep/fw.bin  2 bytes", text)
        self.assertNotIn("/work/up", text)
        self.assertNotIn("hidden", text)
        self.assertIn("/work/bin/app", self.m.list_files(folder="bin"))
        self.assertIn("is a link", self.refused(self.m.list_files, folder="up"))
        self.assertIn("'..' is not allowed", self.refused(self.m.list_files, folder=".."))


class Arguments(Base):
    def test_functions_and_targets(self):
        for good in ("main", "FUN_00401000", "0x401000", "Foo::bar", "operator<<", "ram:00401000", "std::vector<int>"):
            self.assertEqual(self.m.check_symbol(f" {good} ", "function", "main"), good)
        for bad in ("", "a b", "a\tb", "x" * 1025, 5, "a\nb", None):
            with self.subTest(bad=bad):
                with self.assertRaises(self.m.Refused):
                    self.m.check_symbol(bad, "function", "main")

    def test_languages_are_ghidra_ids_and_never_options(self):
        self.assertEqual(self.m.check_language("ARM:LE:32:v8", ""), ("ARM:LE:32:v8", ""))
        self.assertEqual(self.m.check_language("MIPS:BE:32:default", "default"), ("MIPS:BE:32:default", "default"))
        self.assertEqual(self.m.check_language("", ""), ("", ""))
        for language, compiler in (("ARM", ""), ("-Dx=y:LE:32:v8", ""), ("ARM:XE:32:v8", ""), ("ARM:LE:32:v8 x", ""),
                                   ("ARM:LE:32:v8", "-x"), ("", "gcc"), ("ARM:LE:32:v8", "a b")):
            with self.subTest(language=language, compiler=compiler):
                with self.assertRaises(self.m.Refused):
                    self.m.check_language(language, compiler)

    def test_numbers_and_switches(self):
        for call, kwargs, expected in (
                (self.m.decompile_function, {"path": "a", "function": "main", "start_line": 0}, "start_line"),
                (self.m.list_functions, {"path": "a", "offset": -1}, "offset"),
                (self.m.list_functions, {"path": "a", "include_thunks": "yes"}, "include_thunks"),
                (self.m.list_strings, {"path": "a", "min_length": 0}, "min_length"),
                (self.m.find_references, {"path": "a", "target": ""}, "target:"),
                (self.m.open_file, {"path": "a", "compiler": "gcc"}, "only together with language")):
            with self.subTest(call=call.__name__, kwargs=kwargs):
                self.assertIn(expected, self.refused(call, **kwargs))

    def test_the_analysis_limit(self):
        for value, expected in (("", 300), ("60", 60), ("29", 300), ("3601", 300), ("x", 300), ("3600", 3600)):
            with mock.patch.dict(os.environ, {"GHIDRA_ANALYSIS_SECONDS": value}):
                self.assertEqual(self.m.analysis_seconds(), expected)


class Answers(Base):
    def test_a_part_is_at_most_400_lines_and_24000_characters(self):
        text = "\n".join(f"line {i}" for i in range(1, 1001))
        first = self.m.page("T", text, 1, "tool")
        self.assertTrue(first.startswith("T: lines 1-400 of 1000 (more: tool start_line=401)"))
        self.assertEqual(len(first.splitlines()), 401)
        self.assertNotIn("more:", self.m.page("T", text, 801, "tool"))
        part = self.m.page("W", "\n".join("x" * 1000 for _ in range(100)), 1, "tool")
        self.assertLessEqual(len(part), self.m.MAX_CHARS + 200)
        self.assertIn("[line cut at 2000 characters]", self.m.page("H", "y" * 100_000, 1, "tool"))

    def test_shown_lines_cannot_fake_answer_lines(self):
        self.assertEqual(self.m.shown("a\rb\x1bc\u2028d\u202ee"), "a?b?c?d?e")

    def test_lists_come_in_parts_within_the_bound(self):
        items = [[f"{i:08x}", "n" * 200] for i in range(300)]
        text = self.m.listing("L", {"total": 1000, "offset": 0, "items": items}, lambda i: f"{i[0]} {i[1]}",
                              "things", "tool")
        self.assertLessEqual(len(text), self.m.MAX_CHARS)
        self.assertRegex(text, r"^L: 1000 things, 1-\d+ shown \(more: tool offset=\d+\)")
        self.assertIn("offset: there are only 5 things",
                      self.refused(lambda: self.m.answer(lambda: self.m.listing(
                          "L", {"total": 5, "offset": 9, "items": []}, str, "things", "tool"))))


class TheJvm(Base):
    def test_the_command_line_has_no_argument_of_a_call(self):
        command = self.m.jvm_command("/tmp/x/in/app", "app", "/tmp/x")
        self.assertEqual(command[0], self.m.JAVA)
        self.assertEqual(command[-7:-3], ["-cp", f"{self.m.GHIDRA}/Ghidra/Framework/Utility/lib/Utility.jar",
                                          "ghidra.Ghidra", "GhidraBridge"])
        self.assertEqual(command[-3:], ["/tmp/x/in/app", "app", "300"])
        for flag in ("-XX:+ExitOnOutOfMemoryError", "-XX:+DisableAttachMechanism", "-XX:-UsePerfData",
                     "-XX:+UseSerialGC", "-Djava.io.tmpdir=/tmp/x/tmp", "-Duser.home=/tmp/x/tmp",
                     "-Dapplication.settingsdir=/tmp/x/settings", "-Dapplication.cachedir=/tmp/x/cache",
                     "-Dapplication.tempdir=/tmp/x/tmp", "-Djava.awt.headless=true", "-Dcpu.core.limit=2",
                     "-Djava.system.class.loader=ghidra.GhidraClassLoader",
                     f"-Dghidra.external.modules={self.m.MODULE_DIR}"):
            self.assertIn(flag, command)
        self.assertFalse([part for part in command if part.startswith(("-javaagent", "-agent", "-Xdebug", "-jdwp"))])
        with_language = self.m.jvm_command("/tmp/x/in/fw", "fw", "/tmp/x", ("ARM:LE:32:v8", "default"))
        self.assertEqual(with_language[-5:], ["/tmp/x/in/fw", "fw", "300", "ARM:LE:32:v8", "default"])
        self.assertEqual(with_language.index("ghidra.Ghidra") + 1, with_language.index("GhidraBridge"),
                         "everything of a call comes after the main class: arguments of the bridge, never of the JVM")

    def test_the_heap_follows_the_memory_limit(self):
        limit = os.path.join(self.folder, "memory.max")
        Path(limit).write_text(str(3 << 30) + "\n")
        with mock.patch.object(self.m, "CGROUP_MEMORY", limit):
            self.assertEqual(self.m.heap_mb(), int((3 << 30) * 0.6) // (1 << 20) - 64)
            Path(limit).write_text("max\n")
            self.assertEqual(self.m.heap_mb(), self.m.DEFAULT_HEAP_MB)
        with mock.patch.object(self.m, "CGROUP_MEMORY", os.path.join(self.folder, "none")):
            self.assertEqual(self.m.heap_mb(), self.m.DEFAULT_HEAP_MB)

    def test_link_names_are_plain(self):
        self.assertEqual(self.m.link_name("/work/My App (1).exe"), "My_App__1_.exe")
        self.assertEqual(self.m.link_name("/work/../x"), "x")
        self.assertEqual(self.m.link_name("/work/libc.so.6"), "libc_so.6")
        self.assertEqual(self.m.link_name("/work/.bin"), "input.bin")
        self.assertEqual(self.m.link_name("/work/-Dx=y"), "-Dx_y")


class Bridge(Base):
    """The protocol against a stand-in JVM (FAKE_JVM): the descriptor, the environment, the states."""

    def setUp(self):
        super().setUp()
        fake = os.path.join(self.folder, "fake_jvm.py")
        Path(fake).write_text(FAKE_JVM)
        real = self.m.jvm_command

        def command(link, name, folder, options=("", "")):
            full = real(link, name, folder, options)
            return [sys.executable, "-I", fake] + full[full.index("GhidraBridge") + 1:]
        patcher = mock.patch.object(self.m, "jvm_command", command)
        patcher.start()
        self.addCleanup(patcher.stop)

    def bridge(self, name: str, data: bytes = b"\x7fELF data"):
        self.put(name, data)
        return self.m.SESSION.get(name)

    def test_the_jvm_reads_the_opened_descriptor_with_an_empty_environment(self):
        bridge = self.bridge("good", b"\x7fELF 1234")
        self.assertEqual(bridge.ready(10)["bytes"], 9, "the JVM read the very file through /proc/self/fd")
        self.assertEqual(os.readlink(bridge.link), f"/proc/self/fd/{bridge.fd}")
        env = bridge.request("env")
        self.assertEqual(sorted(k for k in env if k not in ("LC_CTYPE",)), ["HOME", "LANG", "PATH"])
        self.assertTrue(env["HOME"].startswith(self.scratch))
        for sub in ("in", "tmp", "settings", "cache"):
            self.assertTrue(os.path.isdir(os.path.join(bridge.folder, sub)))
        summary = self.m.open_file("good")
        self.assertIn("2 functions (0 of them thunks), 1 imported symbols", summary)
        self.assertIn("language x86:LE:64:default", summary)
        self.assertIs(self.m.SESSION.get("good"), bridge, "the same file stays imported")

    def test_a_language_imports_again_and_other_tools_keep_it(self):
        first = self.bridge("fw")
        first.ready(10)
        self.m.open_file("fw", language="ARM:LE:32:v8")
        second = self.m.SESSION.bridge
        self.assertIsNot(first, second)
        self.assertEqual(second.options, ("ARM:LE:32:v8", ""))
        self.assertEqual(second.ready(10)["options"], ["ARM:LE:32:v8"])
        self.m.list_functions("fw")
        self.assertIs(self.m.SESSION.bridge, second, "a tool without language keeps the file as it was opened")

    def test_another_file_replaces_the_imported_one_and_its_scratch_folder_goes(self):
        first = self.bridge("good")
        first.ready(10)
        folder = first.folder
        second = self.bridge("other")
        self.assertIsNot(first, second)
        self.assertFalse(os.path.exists(folder))
        self.assertIsNotNone(first.process.poll())

    def test_a_changed_file_is_imported_again(self):
        first = self.bridge("good", b"\x7fELF1")
        first.ready(10)
        time.sleep(0.01)
        self.put("good", b"\x7fELF12")
        second = self.m.SESSION.get("good")
        self.assertIsNot(first, second)
        self.assertEqual(second.ready(10)["bytes"], 6)

    def test_still_importing_says_so_and_a_later_call_gets_it(self):
        self.put("slow", b"\x7fELF")
        with mock.patch.object(self.m, "WAIT_FOR_LOAD", 0.3):
            text = self.m.open_file("slow")
        self.assertIn("still importing and analysing /work/slow", text)
        self.assertIn("call the tool again", text)
        self.assertIn("imported with Ghidra fake", self.m.open_file("slow"))

    def test_a_call_over_its_time_limit_stops_the_jvm_and_the_next_call_imports_again(self):
        bridge = self.bridge("hang")
        bridge.ready(10)
        with mock.patch.object(self.m, "CALL_SECONDS", 1.0):
            text = self.refused(self.m.decompile_function, "hang", "main")
        self.assertIn("took longer than 1 s and was stopped", text)
        self.assertIsNotNone(bridge.process.poll())
        self.assertIsNot(self.m.SESSION.get("hang"), bridge)

    def test_out_of_memory_and_a_failed_import_are_said(self):
        self.put("oom", b"\x7fELF")
        self.assertIn("ran out of memory", self.refused(self.m.open_file, "oom"))
        self.put("broken", b"\x7fELF")
        self.assertIn("Ghidra could not import the file: bad", self.refused(self.m.open_file, "broken"))

    def test_parts_and_refusals(self):
        self.bridge("good").ready(10)
        text = self.m.decompile_function("good", "main")
        self.assertIn("lines 1-400 of 1000 (more: decompile_function function='main' start_line=401)", text)
        self.assertIn("1000  line 1000", self.m.decompile_function("good", "main", start_line=801))
        self.assertIn("no function x", self.refused(self.m.disassemble_function, "good", "main"))
        listed = self.m.list_functions("good")
        self.assertTrue(listed.startswith("functions of /work/good: 1000 functions, 1-300 shown (more: "
                                          "list_functions with the same arguments and offset=300)"))
        self.assertIn("001013e7  f999  10 bytes", self.m.list_functions("good", offset=900))


class Packaging(unittest.TestCase):
    """The image: Ghidra and the JREs by SHA-256, the bridge compiled in a build stage, what is cut out of Ghidra."""

    dockerfile = (FOLDER / "Dockerfile").read_text()

    def test_the_downloads_are_pinned(self):
        for pin in ("ARG GHIDRA_SHA256=2c2cd776db3c1f6a097ba418922378ac3649cadd5e844a6f5f088ae628a7be67",
                    "ARG TEMURIN_JDK_SHA256=68982529869257d0ee6b824ec5aa270ff8b118bb438670da0b97ebdab178d7fb",
                    "ARG TEMURIN_JRE_SHA256=6fac98f0c8202efc3135a9e9e42aa61963ec42d1c5cbb40caf231e7b14a24ef6",
                    "ADD --checksum=sha256:${GHIDRA_SHA256} ${GHIDRA_URL}",
                    "ADD --checksum=sha256:${TEMURIN_JDK_SHA256} ${TEMURIN_JDK_URL}",
                    "ADD --checksum=sha256:${TEMURIN_JRE_SHA256} ${TEMURIN_JRE_URL}"):
            self.assertIn(pin, self.dockerfile)
        self.assertIn("Ghidra_12.2_build/ghidra_12.2_PUBLIC_20261016.zip", self.dockerfile)
        # the JRE is servers/signal's, reviewed there
        self.assertIn("ARG TEMURIN_SHA256=6fac98f0c8202efc3135a9e9e42aa61963ec42d1c5cbb40caf231e7b14a24ef6",
                      (ROOT / "servers" / "signal" / "Dockerfile").read_text())

    def test_the_jdk_and_the_build_tools_do_not_ship(self):
        final = self.dockerfile[self.dockerfile.index("# --- the server ---"):]
        for build_only in ("TEMURIN_JDK", "/build/jdk", "javac", "unzip"):
            self.assertNotIn(build_only, final)
        self.assertIn("javac --release 25 -Xlint:all,-path,-classfile -Werror", self.dockerfile)

    def test_what_is_cut_out_of_ghidra(self):
        for gone in ("/opt/ghidra/Ghidra/Debug", "/opt/ghidra/Ghidra/Features/GhidraServer",
                     "/opt/ghidra/Ghidra/Features/BSim", "/opt/ghidra/Ghidra/Features/PyGhidra",
                     "/opt/ghidra/Ghidra/Features/GhidraGo", "/opt/ghidra/Extensions", "/opt/ghidra/server"):
            self.assertIn(gone, self.dockerfile)

    def test_the_entrypoint_and_the_limits(self):
        self.assertIn('ENTRYPOINT ["/usr/bin/tini", "-s", "--", "/opt/venv/bin/python", "-I", "-u", '
                      '"/opt/mcp/server.py"]', self.dockerfile)
        spec = json.loads((FOLDER / "smoke.json").read_text())
        self.assertEqual((spec["memory"], spec["pids"], spec["tmp"]), ("3g", 512, "768m"))
        entry = json.loads((FOLDER / "server.json").read_text())
        self.assertIn("3g memory, 512 processes and a 768m /tmp", entry["notes"])
        self.assertEqual(entry["network"], "none")

    def test_every_tool_is_smoked_and_the_lock_is_the_shared_one(self):
        tools = json.loads((FOLDER / "tools.json").read_text())["tools"]
        spec = json.loads((FOLDER / "smoke.json").read_text())
        called = {call["tool"] for call in spec["calls"] if not call.get("expect_error")}
        self.assertEqual(sorted(called), sorted(tools))
        self.assertNotIn("not_smoked", spec)
        lock = (FOLDER / "requirements.txt").read_text()
        self.assertEqual(lock, (ROOT / "servers" / "jadx" / "requirements.txt").read_text())

    def test_the_bridge_speaks_only_its_operations(self):
        bridge = re.sub(r"//[^\n]*", "", (FOLDER / "src" / "GhidraBridge.java").read_text())
        ops = sorted(re.findall(r'case "([a-z]+)":', bridge))
        self.assertEqual(ops, ["calls", "decompile", "disassemble", "exports", "functions", "imports", "info",
                               "strings", "xrefs"])
        for absent in ("ProcessBuilder", "Runtime.getRuntime", "java.net", "Socket", "GhidraScript", "save(",
                       "createProject", "setName(", "FileOutputStream(new File", "System.load"):
            self.assertNotIn(absent, bridge)


@unittest.skipIf(mcp is None or not HAVE_GHIDRA, "Ghidra is not at hand (inside the image it is; else set "
                 "SANDBOX_AI_MCP_JAVA, SANDBOX_AI_MCP_GHIDRA and SANDBOX_AI_MCP_GHIDRA_MODULE)")
class RealGhidra(Base):
    """Every tool with Ghidra 12.2 on the fixtures."""

    def setUp(self):
        super().setUp()
        for name, value in REAL.items():
            patcher = mock.patch.object(self.m, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        data = fixtures()
        self.put("bin/hello", data["hello"])
        self.put("fw/firmware.bin", data["firmware.bin"])

    def opened(self, path: str, **kwargs) -> str:
        deadline = time.monotonic() + 300
        while True:
            text = self.m.open_file(path, **kwargs)
            if "still importing" not in text or time.monotonic() > deadline:
                return text

    def test_an_elf(self):
        path = "bin/hello"
        summary = self.opened(path)
        for expected in ("format: Executable and Linking Format (ELF); language x86:LE:64:default",
                         "entry points: 00101070 _start, 00101176 main", ".text  00101070-001011c0  337 bytes  r-x"):
            self.assertIn(expected, summary)
        self.assertIn("00101159  check_password  29 bytes", self.m.list_functions(path, name_filter="CHECK"))
        self.assertIn("(thunk)", self.m.list_functions(path, include_thunks=True))
        self.assertIn('puts("access granted");', self.m.decompile_function(path, "main"))
        self.assertIn("C of main at 00101176", self.m.decompile_function(path, "0x101180"))
        self.assertIn("; <EXTERNAL>::strcmp", self.m.disassemble_function(path, "check_password"))
        self.assertIn("00101159  check_password  (function)", self.m.function_calls(path, "main"))
        self.assertIn("in check_password", self.m.find_references(path, "strcmp"))
        self.assertIn("<EXTERNAL>!puts  (function)", self.m.list_imports(path))
        self.assertIn("00101176  main  (function)", self.m.list_exports(path))
        self.assertIn('"hunter2"', self.m.list_strings(path, text_filter="hunt"))
        self.assertIn("no function nope", self.refused(self.m.decompile_function, path, "nope"))
        self.assertIn("no function contains", self.refused(self.m.decompile_function, path, "0x100000"))
        self.assertIn("nothing is named or at", self.refused(self.m.find_references, path, "zzz_none"))

    def test_raw_firmware_needs_a_language(self):
        path = "fw/firmware.bin"
        self.assertIn("does not recognise the format", self.refused(self.opened, path))
        self.assertIn("format: Raw Binary; language ARM:LE:32:v8", self.opened(path, language="ARM:LE:32:v8"))
        self.assertIn("00000000  Reset  4 bytes", self.m.list_functions(path))
        self.assertIn("those of ARM: ARM:BE:32:Cortex", self.refused(self.opened, path, language="ARM:LE:32:nosuch"))


if __name__ == "__main__":
    unittest.main()
