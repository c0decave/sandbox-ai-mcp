"""The cfr server (servers/cfr): its own code offline - paths (no '..', nothing outside /work, no link, no folder, pipe,
empty or oversized file), the class-file reader on the demo.jar fixture and on broken class files, archives (JAR, WAR,
a single class, not a zip, too many entries, inner classes), string search in parts, answers in parts (400 lines /
24,000 characters), CFR's command line (empty environment, the descriptor passed, only the three options a call may
switch on, never an output folder) and a stand-in CFR that hangs or prints too much - and, where CFR is at hand
(inside the image, or with SANDBOX_AI_MCP_JAVA and SANDBOX_AI_MCP_CFR_JAR), every tool with the real CFR. The folders
are temporary ones the module's ROOTS point at. CI runs this inside the image too (tests/test_own_servers.py
test_cfr)."""
from __future__ import annotations

import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import textwrap
import time
import unittest
from unittest import mock
import zipfile

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "servers" / "cfr" / "src" / "server.py"

try:
    import mcp  # noqa: F401 - the server's own dependency
    from mcp.server.fastmcp.exceptions import ToolError
except ImportError:
    mcp = None
    ToolError = Exception


def load():
    spec = importlib.util.spec_from_file_location("server_cfr_test", SERVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixtures() -> dict[str, bytes]:
    spec = importlib.util.spec_from_file_location("fixtures_cfr_test", ROOT / "scripts" / "fixtures.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {f["path"]: f["data"] for f in module.load()}


IMAGE = {"JAVA": "/usr/lib/jvm/java-21-openjdk-amd64/bin/java", "CFR_JAR": "/opt/cfr/cfr-0.152.jar"}
REAL = {"JAVA": os.environ.get("SANDBOX_AI_MCP_JAVA") or IMAGE["JAVA"],
        "CFR_JAR": os.environ.get("SANDBOX_AI_MCP_CFR_JAR") or IMAGE["CFR_JAR"]}
HAVE_CFR = os.path.isfile(REAL["JAVA"]) and os.path.isfile(REAL["CFR_JAR"])

#: A stand-in for CFR: records its arguments and environment, or hangs, or prints without end.
FAKE_CFR = textwrap.dedent("""
    import json, os, sys, time
    arguments = sys.argv[1:]
    subject = arguments[0]
    data = open(subject, "rb").read()
    if "hang" in os.path.basename(subject):
        time.sleep(60)
    if b"FLOOD" in data[:64]:
        while True:
            sys.stdout.write("x" * 65536)
    print(json.dumps({"arguments": arguments, "env": dict(os.environ), "cwd": os.getcwd(), "bytes": len(data),
                      "files": sorted(os.listdir(os.getcwd()))}))
""")


def class_file(name: str = "a/B", strings=("hello",), methods=(("run", "()V"),), fields=(("x", "I"),)) -> bytes:
    """A minimal class file (JVMS 4) with these constants and members."""
    pool: list[bytes] = []

    def utf8(text: str) -> int:
        raw = text.encode()
        pool.append(b"\x01" + struct.pack(">H", len(raw)) + raw)
        return len(pool)

    def klass(text: str) -> int:
        index = utf8(text)
        pool.append(b"\x07" + struct.pack(">H", index))
        return len(pool)

    this, sup = klass(name), klass("java/lang/Object")
    for text in strings:
        index = utf8(text)
        pool.append(b"\x08" + struct.pack(">H", index))
    members = []
    for group in (fields, methods):
        encoded = struct.pack(">H", len(group))
        for member, descriptor in group:
            encoded += struct.pack(">HHHH", 0x0001, utf8(member), utf8(descriptor), 0)
        members.append(encoded)
    body = struct.pack(">IHHH", 0xCAFEBABE, 0, 52, len(pool) + 1) + b"".join(pool)
    return body + struct.pack(">HHHH", 0x0021, this, sup, 0) + members[0] + members[1] + struct.pack(">H", 0)


def jar(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


@unittest.skipIf(mcp is None, "the server's requirements are not installed (pip install --require-hashes -r "
                              "servers/cfr/requirements.txt)")
class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load()

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="cfr-test-")
        self.work = os.path.join(self.folder, "work")
        self.scratch = os.path.join(self.folder, "scratch")
        os.makedirs(self.work)
        for name, value in (("ROOTS", {"/work": self.work}), ("SCRATCH", self.scratch)):
            patcher = mock.patch.object(self.m, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.m.INPUTS.close()
        self.addCleanup(self.m.INPUTS.close)
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
    def test_only_regular_files_in_work_are_read(self):
        self.put("libs/a.jar", jar({"a/B.class": class_file()}))
        os.symlink(os.path.join(self.work, "libs", "a.jar"), os.path.join(self.work, "link.jar"))
        os.mkfifo(os.path.join(self.work, "pipe.jar"))
        self.put("empty.jar", b"")
        for path, expected in {"../x.jar": "'..' is not allowed", "/etc/passwd": "only files in /work",
                               "link.jar": "is a link", "libs": "is a folder", "pipe.jar": "not a regular file",
                               "empty.jar": "is empty", "none.jar": "does not exist", "a\tb": "path:"}.items():
            with self.subTest(path=path):
                self.assertIn(expected, self.refused(self.m.list_classes, path))
        self.assertIn("a.B", self.m.list_classes("/work/libs/a.jar"))
        listed = self.m.list_files()
        self.assertIn("/work/libs/a.jar", listed)
        self.assertNotIn("link.jar", listed)

    def test_member_names_cannot_become_options(self):
        for bad in ("--outputdir", "-x", "a.b", "a(I)V", "a b"):
            with self.subTest(bad=bad):
                with self.assertRaises(self.m.Refused):
                    self.m.check_member(bad, "method_name")


class ClassFiles(Base):
    def test_the_fixture_classes(self):
        archive = zipfile.ZipFile(io.BytesIO(fixtures()["demo.jar"]))
        checker = self.m.ClassFile(archive.read("org/example/demo/Checker.class"))
        self.assertEqual((checker.name, checker.super, checker.major), ("org.example.demo.Checker", "java.lang.Object", 52))
        self.assertEqual([m for _, m, _ in checker.methods], ["<init>", "checkPassword", "greet", "greet", "attempts"])
        self.assertEqual([(f, d) for _, f, d in checker.fields], [("MARKER", "Ljava/lang/String;"), ("attempts", "I")])
        self.assertIn("hunter2", checker.strings())
        self.assertIn("MCPHUB-TEST-MARKER", checker.strings())

    def test_descriptors(self):
        self.assertEqual(self.m.method_text("f", "([[ILjava/lang/String;J)[Ljava/util/List;"),
                         "java.util.List[] f(int[][], java.lang.String, long)")
        self.assertEqual(self.m.method_text("g", "()V"), "void g()")
        self.assertEqual(self.m.method_text("h", "(broken"), "h(broken")
        self.assertEqual(self.m.access_text(0x0009), "public static")

    def test_broken_class_files_are_refused_quickly(self):
        good = class_file()
        cases = [b"", b"\xca\xfe\xba\xbe", good[:20], good[:-3], b"\xca\xfe\xba\xbe\x00\x00\x00\x34\xff\xff\x63",
                 b"\xca\xfe\xba\xbe\x00\x00\x00\x34\x00\x02\x01\xff\xff", b"\x00" * 64,
                 b"\xca\xfe\xba\xbe\x00\x00\x00\x34\x00\x03\x07\x00\x09\x07\x00\x01" + b"\x00" * 30]
        for data in cases:
            with self.subTest(data=data[:24]):
                started = time.monotonic()
                with self.assertRaises(self.m.Refused):
                    self.m.ClassFile(data)
                self.assertLess(time.monotonic() - started, 1)

    def test_outline_from_the_class_file(self):
        self.put("one/B.class", class_file("a/B", methods=(("run", "(I)V"), ("<init>", "()V"))))
        outline = self.m.class_outline("one/B.class")
        self.assertIn("public class a.B", outline)
        self.assertIn("public void run(int)  (I)V", outline)
        self.assertIn("public int x", outline)


class Archives(Base):
    def test_jars_wars_inner_classes_and_others(self):
        self.put("app.jar", jar({"a/B.class": class_file("a/B"), "a/B$In.class": class_file("a/B$In"),
                                 "module-info.class": b"x", "META-INF/versions/11/a/B.class": b"x",
                                 "lib/nested.jar": b"PK", "x.txt": b"t"}))
        self.put("web.war", jar({"WEB-INF/classes/w/S.class": class_file("w/S"), "WEB-INF/lib/z.jar": b"PK"}))
        self.put("not.jar", b"hello world")
        self.put("app.apk", jar({"classes.dex": b"dex\n035"}))
        listed = self.m.list_classes("app.jar")
        self.assertIn("1 classes", listed)
        self.assertIn("nested JARs", listed)
        self.assertIn("a.B$In", self.m.list_classes("app.jar", include_inner=True))
        self.assertIn("w.S", self.m.list_classes("web.war"))
        self.assertIn("neither a JAR/ZIP nor a class file", self.refused(self.m.list_classes, "not.jar"))
        self.assertIn("use the jadx server", self.m.list_classes("app.apk"))
        archive = self.m.INPUTS.get("app.jar")
        self.assertEqual(archive.top_level("a.B$In"), "a.B")
        self.assertEqual(archive.resolve("a.B.In"), "a.B$In")
        self.assertIn("similar: a.B", self.refused(self.m.decompile_class, "app.jar", "a.b"))
        with mock.patch.object(self.m, "MAX_ENTRIES", 3):
            self.m.INPUTS.close()
            self.assertIn("more than 3 entries", self.refused(self.m.list_classes, "app.jar"))

    def test_search_strings_in_parts(self):
        entries = {f"p/C{i:03}.class": class_file(f"p/C{i:03}", strings=(f"value {i}", "needle" if i % 10 == 0 else "x"))
                   for i in range(50)}
        entries["p/Bad.class"] = b"\xca\xfe\xba\xbe broken"
        self.put("many.jar", jar(entries))
        text = self.m.search_strings("many.jar", "NEEDLE", max_results=3)
        self.assertIn("3 matches of 'NEEDLE'", text)
        self.assertIn("not done: start_class=", text)
        rest = self.m.search_strings("many.jar", "needle", start_class=int(text.split("start_class=")[1].split()[0]))
        self.assertIn("2 matches", rest)
        self.assertIn("searched to the end", rest)
        self.assertIn("1 class files could not be read", text)
        self.assertIn("0 matches", self.m.search_strings("many.jar", "NEEDLE", ignore_case=False))
        self.assertIn("method 'run'", self.m.search_strings("many.jar", "run", include_names=True, max_results=1))
        with mock.patch.object(self.m, "SEARCH_SECONDS", 0):
            self.assertIn("not done: start_class=1", self.m.search_strings("many.jar", "needle"))


class TheCommandLine(Base):
    """run_cfr against a stand-in CFR (FAKE_CFR)."""

    def setUp(self):
        super().setUp()
        fake = os.path.join(self.folder, "fake_cfr.py")
        Path(fake).write_text(FAKE_CFR)
        patcher = mock.patch.object(self.m, "cfr_command", lambda folder, arguments: [sys.executable, "-I", fake]
                                    + arguments)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_fake(self, call, *args, **kwargs) -> dict:
        text = call(*args, **kwargs)
        return json.loads(text.split("\n", 1)[1].split("  ", 1)[1])

    def test_a_class_of_a_jar(self):
        self.put("app.jar", jar({"a/B.class": class_file("a/B"), "a/B$In.class": class_file("a/B$In")}))
        seen = self.run_fake(self.m.decompile_class, "app.jar", "a.B$In", rename_duplicate_members=True,
                             anti_obfuscation=True)
        arguments = seen["arguments"]
        self.assertTrue(arguments[0].startswith(self.scratch) and arguments[0].endswith("/in/app.jar"))
        self.assertEqual(arguments[1:], ["--analyseas", "JAR", "--silent", "true", "--jarfilter", "^a\\.B$",
                                         "--renamedupmembers", "true", "--antiobf", "true"])
        self.assertEqual(sorted(k for k in seen["env"] if k != "LC_CTYPE"), ["HOME", "LANG", "PATH"])
        self.assertEqual(seen["files"], [], "CFR starts in an empty folder")
        self.assertEqual(seen["bytes"], os.path.getsize(os.path.join(self.work, "app.jar")))
        self.assertEqual(os.listdir(self.scratch), [], "the scratch folder is removed after each run")

    def test_a_method_is_decompiled_from_its_class_file_with_the_jar_as_class_path(self):
        data = class_file("a/B", methods=(("run", "()V"),))
        self.put("app.jar", jar({"a/B.class": data}))
        seen = self.run_fake(self.m.decompile_method, "app.jar", "a.B", "run")
        self.assertTrue(seen["arguments"][0].endswith("/in/subject.class"))
        self.assertEqual(seen["bytes"], len(data))
        self.assertEqual(seen["arguments"][1], "--extraclasspath")
        self.assertEqual(seen["arguments"][3:], ["--silent", "true", "--methodname", "run"])
        self.assertIn("its methods: run", self.refused(self.m.decompile_method, "app.jar", "a.B", "nope"))

    def test_a_single_class_file(self):
        self.put("B.class", class_file("a/B"))
        seen = self.run_fake(self.m.decompile_class, "B.class")
        self.assertTrue(seen["arguments"][0].endswith("/in/B.class"))
        self.assertEqual(seen["arguments"][1:], ["--silent", "true"])

    def test_only_three_options_ever_reach_cfr(self):
        self.assertEqual(sorted(self.m.CFR_FLAGS), ["anti_obfuscation", "rename_duplicate_members",
                                                    "rename_illegal_identifiers"])
        self.assertEqual(sorted(flag for flag, _ in self.m.CFR_FLAGS.values()),
                         ["--antiobf", "--renamedupmembers", "--renameillegalidents"])
        source = SERVER.read_text()
        for option in ("--outputdir", "--outputpath", "--obfuscationpath", "--clobber", "--importfilter"):
            self.assertNotIn(f'"{option}"', source)
        self.assertIn("rename_duplicate_members: true or false",
                      self.refused(self.m.decompile_class, "x.jar", "a.B", rename_duplicate_members="--outputdir"))

    def test_a_run_over_its_time_or_output_limit_is_stopped(self):
        self.put("hang.class", class_file("a/Hang"))
        with mock.patch.object(self.m, "CFR_SECONDS", 1.0):
            started = time.monotonic()
            self.assertIn("took longer than 1 s and was stopped", self.refused(self.m.decompile_class, "hang.class"))
            self.assertLess(time.monotonic() - started, 10)
        flood = jar({"a/B.class": b"FLOOD" + class_file("a/B")})
        self.put("flood.jar", flood)
        archive = self.m.INPUTS.get("flood.jar")
        with mock.patch.object(self.m, "MAX_OUTPUT_BYTES", 1 << 20):
            with self.assertRaises(self.m.Refused) as caught:
                self.m.run_cfr(archive, [], class_data=b"FLOOD")
        self.assertIn("printed more than", str(caught.exception))
        self.assertEqual(os.listdir(self.scratch), [])


@unittest.skipIf(mcp is None or not HAVE_CFR, "CFR is not at hand (inside the image it is; else set "
                 "SANDBOX_AI_MCP_JAVA and SANDBOX_AI_MCP_CFR_JAR)")
class RealCfr(Base):
    def setUp(self):
        super().setUp()
        for name, value in REAL.items():
            patcher = mock.patch.object(self.m, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        data = fixtures()["demo.jar"]
        self.put("libs/demo.jar", data)
        self.put("single/Checker.class", zipfile.ZipFile(io.BytesIO(data)).read("org/example/demo/Checker.class"))

    def test_every_tool(self):
        path = "libs/demo.jar"
        self.assertIn("org.example.demo.Checker\norg.example.demo.Main", self.m.list_classes(path))
        self.assertIn("public boolean checkPassword(java.lang.String)  (Ljava/lang/String;)Z",
                      self.m.class_outline(path, "org.example.demo.Checker"))
        source = self.m.decompile_class(path, "org.example.demo.Checker$Result")
        self.assertIn("Java source of org.example.demo.Checker (CFR 0.152)", source)
        self.assertIn("public static class Result {", source)
        self.assertIn("Decompiled with CFR 0.152", source)
        self.assertIn("checker.checkPassword(input)",
                      self.m.decompile_class(path, "org.example.demo.Main", rename_illegal_identifiers=True))
        method = self.m.decompile_method(path, "org.example.demo.Checker", "greet")
        self.assertIn("(2 found, CFR 0.152)", method)
        self.assertIn('return "Hello, " + name + "!";', method)
        self.assertIn("public Checker() {", self.m.decompile_method(path, "org.example.demo.Checker", "<init>"))
        self.assertIn("org.example.demo.Checker: string 'hunter2'", self.m.search_strings(path, "HUNTER"))
        single = self.m.decompile_class("single/Checker.class")
        self.assertIn('return "hunter2".equals(candidate);', single)
        self.assertIn("++this.attempts;", self.m.decompile_method("single/Checker.class", "", "checkPassword"))
        self.assertEqual(os.listdir(self.scratch), [])

    def test_a_class_cfr_cannot_read(self):
        self.put("bad.jar", jar({"a/B.class": b"\xca\xfe\xba\xbe" + b"\x00" * 40}))
        self.assertIn("not a valid class file", self.refused(self.m.decompile_class, "bad.jar", "a.B"))


@unittest.skipIf(mcp is None, "the server's requirements are not installed")
class Server(unittest.TestCase):
    def test_tools_only_and_the_recorded_tools(self):
        import asyncio
        from mcp import types
        from mcp.server.lowlevel.server import NotificationOptions
        module = load()
        for request in (types.ListResourcesRequest, types.ListPromptsRequest, types.ReadResourceRequest):
            self.assertNotIn(request, module.mcp._mcp_server.request_handlers)
        capabilities = module.mcp._mcp_server.get_capabilities(NotificationOptions(), {})
        self.assertIsNone(capabilities.resources)
        self.assertIsNone(capabilities.prompts)
        tools = asyncio.run(module.mcp.list_tools())
        self.assertEqual(sorted(t.name for t in tools),
                         json.loads((ROOT / "servers" / "cfr" / "tools.json").read_text())["tools"])
        for tool in tools:
            self.assertTrue(tool.annotations.readOnlyHint, tool.name)


if __name__ == "__main__":
    unittest.main()
