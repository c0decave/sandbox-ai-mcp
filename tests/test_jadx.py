"""The jadx server (servers/jadx): its Python half offline - paths (no '..', nothing outside /work, no link, no folder,
pipe, empty or oversized file), arguments, answers in parts (400 lines / 24,000 characters), the JVM's command line
(empty environment, the descriptor passed, no option from an argument), the bridge protocol against a stand-in JVM
(still loading, a timeout that stops it, running out of memory, a refusal) - and, where jadx is at hand (inside the
image, or with SANDBOX_AI_MCP_JAVA, SANDBOX_AI_MCP_JADX_JAR and SANDBOX_AI_MCP_JADX_BRIDGE), every tool against the
demo.apk and demo.jar fixtures with the real jadx. The folders are temporary ones the module's ROOTS point at.
CI runs this inside the image too (tests/test_own_servers.py test_jadx)."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import textwrap
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "servers" / "jadx" / "src" / "server.py"

try:
    import mcp  # noqa: F401 - the server's own dependency
    from mcp.server.fastmcp.exceptions import ToolError
except ImportError:
    mcp = None
    ToolError = Exception


def load():
    spec = importlib.util.spec_from_file_location("server_jadx_test", SERVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixtures() -> dict[str, bytes]:
    spec = importlib.util.spec_from_file_location("fixtures_jadx_test", ROOT / "scripts" / "fixtures.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {f["path"]: f["data"] for f in module.load()}


#: The real jadx: the image's paths, or the ones these variables name (a checkout with jadx and a compiled bridge).
IMAGE = {"JAVA": "/usr/lib/jvm/java-21-openjdk-amd64/bin/java", "JADX_JAR": "/opt/jadx/lib/jadx-1.5.6-all.jar",
         "BRIDGE_DIR": "/opt/mcp/bridge"}
REAL = {"JAVA": os.environ.get("SANDBOX_AI_MCP_JAVA") or IMAGE["JAVA"],
        "JADX_JAR": os.environ.get("SANDBOX_AI_MCP_JADX_JAR") or IMAGE["JADX_JAR"],
        "BRIDGE_DIR": os.environ.get("SANDBOX_AI_MCP_JADX_BRIDGE") or IMAGE["BRIDGE_DIR"]}
HAVE_JADX = os.path.isfile(REAL["JAVA"]) and os.path.isfile(REAL["JADX_JAR"]) and \
    os.path.isfile(os.path.join(REAL["BRIDGE_DIR"], "JadxBridge.class"))

#: A stand-in for the JVM: speaks the bridge's protocol; what it does is chosen by the name of the file it is given.
FAKE_JVM = textwrap.dedent("""
    import json, os, sys, time
    link = sys.argv[-1]
    mode = os.path.basename(link).split(".")[0]
    data = open(link, "rb").read()
    if mode == "slow":
        time.sleep(3)
    if mode == "oom":
        sys.exit(3)
    if mode == "broken":
        print(json.dumps({"id": 0, "ok": False, "error": "jadx could not load the file: bad"}), flush=True)
        sys.exit(0)
    print(json.dumps({"id": 0, "ok": True, "result": {"classes": 1, "classes_with_inner": 1, "packages": 1,
                      "resources": 0, "manifest": None, "errors": 0, "jadx": "fake", "bytes": len(data)}}),
          flush=True)
    for line in sys.stdin:
        request = json.loads(line)
        if request["op"] == "classes":
            result = [["a.b.Foo", "a.b.Foo"], ["a.b.Foo2", "a.b.Foo2"]]
        elif request["op"] == "source":
            if mode == "hang":
                time.sleep(60)
            result = {"class": request["class"], "code": "\\n".join(f"line {i}" for i in range(1, 1001))}
        elif request["op"] == "env":
            result = dict(os.environ)
        else:
            print(json.dumps({"id": request["id"], "ok": False, "error": "no class x"}), flush=True)
            continue
        print(json.dumps({"id": request["id"], "ok": True, "result": result}), flush=True)
""")


@unittest.skipIf(mcp is None, "the server's requirements are not installed (pip install --require-hashes -r "
                              "servers/jadx/requirements.txt)")
class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load()

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="jadx-test-")
        self.work = os.path.join(self.folder, "work")
        self.scratch = os.path.join(self.folder, "scratch")
        os.makedirs(os.path.join(self.work, "apps"))
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
        self.put("apps/a.apk", b"PK\x03\x04")
        fd, shown, info = self.m.open_input("apps/a.apk")
        os.close(fd)
        self.assertEqual(shown, "/work/apps/a.apk")
        fd, shown, _ = self.m.open_input("/work/apps/./a.apk")
        os.close(fd)
        self.assertEqual(shown, "/work/apps/a.apk")
        cases = {"../etc/passwd": "'..' is not allowed", "/etc/passwd": "only files in /work",
                 "apps/../../x": "'..' is not allowed", "~/x.apk": "'~' is not a folder", "": "name a file",
                 "/work": "name a file", "apps": "is a folder", "apps/none.apk": "does not exist",
                 "a\nb": "path:", "/work-x/a.apk": "only files in /work"}
        for path, expected in cases.items():
            with self.subTest(path=path):
                with self.assertRaises(self.m.Refused) as caught:
                    self.m.open_input(path)
                self.assertIn(expected, str(caught.exception))

    def test_links_are_never_followed(self):
        outside = os.path.join(self.folder, "secret.apk")
        Path(outside).write_bytes(b"PK secret")
        os.symlink(outside, os.path.join(self.work, "link.apk"))
        os.symlink("apps", os.path.join(self.work, "linkdir"))
        self.put("apps/real.apk", b"PK")
        os.symlink("real.apk", os.path.join(self.work, "apps", "inside.apk"))
        for path in ("link.apk", "linkdir/real.apk", "apps/inside.apk"):
            with self.subTest(path=path):
                with self.assertRaises(self.m.Refused) as caught:
                    self.m.open_input(path)
                self.assertIn("is a link; links are not followed", str(caught.exception))

    def test_pipes_empty_and_oversized_files_are_refused(self):
        os.mkfifo(os.path.join(self.work, "pipe.apk"))
        self.put("empty.apk", b"")
        self.put("big.apk", b"x" * 2048)
        started = time.monotonic()
        with self.assertRaises(self.m.Refused) as caught:
            self.m.open_input("pipe.apk")
        self.assertIn("not a regular file", str(caught.exception))
        self.assertLess(time.monotonic() - started, 2, "a pipe never blocks the open")
        with self.assertRaises(self.m.Refused) as caught:
            self.m.open_input("empty.apk")
        self.assertIn("is empty", str(caught.exception))
        with mock.patch.object(self.m, "MAX_INPUT_BYTES", 1024):
            with self.assertRaises(self.m.Refused) as caught:
                self.m.open_input("big.apk")
        self.assertIn("larger than", str(caught.exception))

    def test_list_files_shows_inputs_and_follows_no_link(self):
        self.put("apps/a.apk", b"PK")
        self.put("apps/deep/b.dex", b"dex")
        self.put("notes.txt", b"x")
        self.put(".hidden/c.jar", b"PK")
        os.symlink(self.folder, os.path.join(self.work, "up"))
        text = self.m.list_files()
        self.assertIn("/work/apps/a.apk  2 bytes", text)
        self.assertIn("/work/apps/deep/b.dex", text)
        self.assertNotIn("notes.txt", text)
        self.assertIn("1 other files not shown", text)
        self.assertNotIn("/work/up", text)
        self.assertNotIn("c.jar", text)
        self.assertIn("/work/notes.txt", self.m.list_files(show_all=True))
        self.assertIn("/work/apps/a.apk", self.m.list_files(folder="apps"))
        self.assertIn("is a link", self.refused(self.m.list_files, folder="up"))
        self.assertIn("'..' is not allowed", self.refused(self.m.list_files, folder=".."))


class Arguments(Base):
    def test_class_names_in_every_spelling(self):
        for given in ("org.example.Foo", "org/example/Foo", "Lorg/example/Foo;", "org.example.Foo.java",
                      " org.example.Foo "):
            self.assertEqual(self.m.check_class(given), "org.example.Foo")
        self.assertEqual(self.m.check_class("a.B$C"), "a.B$C")
        for bad in ("", "a b", "a..b", ".a", "a(", "x" * 1025, 5, "a\nb"):
            with self.subTest(bad=bad):
                with self.assertRaises(self.m.Refused):
                    self.m.check_class(bad)

    def test_member_names_and_signatures(self):
        self.assertEqual(self.m.check_member("onCreate", "method_name"), "onCreate")
        self.assertEqual(self.m.check_member("<init>", "method_name"), "<init>")
        for bad in ("a.b", "a(I)V", "--outputdir", "-x", "a b", "<x>", ""):
            with self.subTest(bad=bad):
                with self.assertRaises(self.m.Refused):
                    self.m.check_member(bad, "method_name")
        self.assertEqual(self.m.check_signature("a(Ljava/lang/String;)Z"), "a(Ljava/lang/String;)Z")
        self.assertEqual(self.m.check_signature(""), "")
        for bad in ("a", "a()", "a b()V", "(I)V"):
            with self.subTest(bad=bad):
                with self.assertRaises(self.m.Refused):
                    self.m.check_signature(bad)

    def test_numbers_and_switches(self):
        for call, kwargs, expected in (
                (self.m.get_class_source, {"path": "a.apk", "class_name": "a.B", "start_line": 0}, "start_line"),
                (self.m.list_classes, {"path": "a.apk", "offset": -1}, "offset"),
                (self.m.search_code, {"path": "a.apk", "text": "x", "max_results": 201}, "max_results"),
                (self.m.search_code, {"path": "a.apk", "text": "x", "ignore_case": "yes"}, "ignore_case"),
                (self.m.search_code, {"path": "a.apk", "text": ""}, "text:"),
                (self.m.find_usages, {"path": "a.apk", "class_name": "a.B", "method_name": "x", "field_name": "y"},
                 "not both")):
            with self.subTest(call=call.__name__, kwargs=kwargs):
                self.assertIn(expected, self.refused(call, **kwargs))


class Answers(Base):
    def test_a_part_is_at_most_400_lines_and_24000_characters(self):
        text = "\n".join(f"line {i}" for i in range(1, 1001))
        first = self.m.page("T", text, 1, "tool")
        self.assertTrue(first.startswith("T: lines 1-400 of 1000 (more: tool start_line=401)"))
        self.assertEqual(len(first.splitlines()), 401)
        last = self.m.page("T", text, 801, "tool")
        self.assertIn("lines 801-1000 of 1000", last)
        self.assertNotIn("more:", last)
        wide = "\n".join("x" * 1000 for _ in range(100))
        part = self.m.page("W", wide, 1, "tool")
        self.assertLessEqual(len(part), self.m.MAX_CHARS + 200)
        self.assertIn("more: tool start_line=24", part)
        self.assertIn("start_line: T has 1000 lines", str(self.catch(self.m.page, "T", text, 1001, "tool")))
        huge = self.m.page("H", "y" * 100_000, 1, "tool")
        self.assertIn("[line cut at 2000 characters]", huge)

    def catch(self, call, *args):
        try:
            call(*args)
        except self.m.Refused as exc:
            return exc
        self.fail("not refused")

    def test_shown_lines_cannot_fake_answer_lines(self):
        self.assertEqual(self.m.shown("a\rb\x1bc d‮e"), "a?b?c?d?e")

    def test_lists_come_in_parts(self):
        items = [f"item{i}" for i in range(700)]
        text = self.m.listing("L", items, 0, "things")
        self.assertTrue(text.startswith("L: 700 things, 1-300 shown (more: offset=300)"))
        self.assertIn("1-300", text)
        self.assertIn("601-700 shown", self.m.listing("L", items, 600, "things"))

    def test_the_manifest_summary(self):
        manifest = ('<manifest package="com.x" android:versionName="2.1"><uses-sdk android:minSdkVersion="24"/>'
                    '<uses-permission android:name="android.permission.CAMERA"/><application>'
                    '<activity android:name="com.x.Main"><intent-filter><action android:name="android.intent.action.MAIN"/>'
                    '<category android:name="android.intent.category.LAUNCHER"/></intent-filter></activity>'
                    '<service android:name="com.x.S"/></application></manifest>')
        lines = self.m.manifest_summary(manifest)
        self.assertEqual(lines, ["app package: com.x, version 2.1", "minSdkVersion 24",
                                 "permissions (1): android.permission.CAMERA", "components: 1 activity, 1 service",
                                 "launcher activity: com.x.Main"])


class TheJvm(Base):
    def test_the_command_line_has_no_argument_of_a_call(self):
        command = self.m.jvm_command("/tmp/x/in/app.apk", "/tmp/x/tmp")
        self.assertEqual(command[0], self.m.JAVA)
        self.assertEqual(command[-3:], [f"{self.m.JADX_JAR}:{self.m.BRIDGE_DIR}", "JadxBridge", "/tmp/x/in/app.apk"])
        for flag in ("-XX:+ExitOnOutOfMemoryError", "-XX:+DisableAttachMechanism", "-XX:-UsePerfData",
                     "-XX:+UseSerialGC", "-Djava.io.tmpdir=/tmp/x/tmp", "-Djava.awt.headless=true"):
            self.assertIn(flag, command)
        self.assertFalse([part for part in command if part.startswith(("-javaagent", "-agent", "-Xdebug", "-jdwp"))])

    def test_the_heap_follows_the_memory_limit(self):
        limit = os.path.join(self.folder, "memory.max")
        Path(limit).write_text(str(2 << 30) + "\n")
        with mock.patch.object(self.m, "CGROUP_MEMORY", limit):
            self.assertEqual(self.m.heap_mb(), int((2 << 30) * 0.7) // (1 << 20) - 64)
            Path(limit).write_text("max\n")
            self.assertEqual(self.m.heap_mb(), self.m.DEFAULT_HEAP_MB)
        with mock.patch.object(self.m, "CGROUP_MEMORY", os.path.join(self.folder, "none")):
            self.assertEqual(self.m.heap_mb(), self.m.DEFAULT_HEAP_MB)

    def test_link_names_are_plain(self):
        self.assertEqual(self.m.link_name("/work/My App (1).apk"), "My_App__1_.apk")
        self.assertEqual(self.m.link_name("/work/../x"), "x")
        self.assertEqual(self.m.link_name("/work/a.b.XAPK"), "a_b.xapk")
        self.assertEqual(self.m.link_name("/work/.apk"), "input.apk")


class Bridge(Base):
    """The protocol against a stand-in JVM (FAKE_JVM): the descriptor, the environment, the states."""

    def setUp(self):
        super().setUp()
        fake = os.path.join(self.folder, "fake_jvm.py")
        Path(fake).write_text(FAKE_JVM)
        patcher = mock.patch.object(self.m, "jvm_command", lambda link, tmp: [sys.executable, "-I", fake, link])
        patcher.start()
        self.addCleanup(patcher.stop)

    def bridge(self, name: str, data: bytes = b"PK data"):
        self.put(name, data)
        return self.m.SESSION.get(name)

    def test_the_jvm_reads_the_opened_descriptor_with_an_empty_environment(self):
        bridge = self.bridge("good.apk", b"PK 12345")
        self.assertEqual(bridge.ready(10)["bytes"], 8, "the JVM read the very file through /proc/self/fd")
        self.assertEqual(os.readlink(bridge.link), f"/proc/self/fd/{bridge.fd}")
        env = bridge.request("env")
        self.assertEqual(sorted(k for k in env if k not in ("LC_CTYPE",)), ["HOME", "LANG", "PATH"])
        self.assertTrue(env["HOME"].startswith(self.scratch))
        self.assertIn("1 classes", self.m.open_file("good.apk"))
        self.assertIs(self.m.SESSION.get("good.apk"), bridge, "the same file stays loaded")

    def test_another_file_replaces_the_loaded_one_and_its_scratch_folder_goes(self):
        first = self.bridge("good.apk")
        first.ready(10)
        folder = first.folder
        second = self.bridge("other.apk")
        self.assertIsNot(first, second)
        self.assertFalse(os.path.exists(folder))
        self.assertIsNotNone(first.process.poll())

    def test_a_changed_file_is_loaded_again(self):
        first = self.bridge("good.apk", b"PK 1")
        first.ready(10)
        time.sleep(0.01)
        self.put("good.apk", b"PK 12")
        second = self.m.SESSION.get("good.apk")
        self.assertIsNot(first, second)
        self.assertEqual(second.ready(10)["bytes"], 5)

    def test_still_loading_says_so_and_a_later_call_gets_it(self):
        self.put("slow.apk", b"PK")
        with mock.patch.object(self.m, "WAIT_FOR_LOAD", 0.3):
            text = self.m.open_file("slow.apk")
        self.assertIn("still loading /work/slow.apk", text)
        self.assertIn("call the tool again", text)
        self.assertIn("1 classes", self.m.open_file("slow.apk"))

    def test_a_call_over_its_time_limit_stops_the_jvm_and_the_next_call_loads_again(self):
        bridge = self.bridge("hang.apk")
        bridge.ready(10)
        with mock.patch.object(self.m, "CALL_SECONDS", 1.0):
            text = self.refused(self.m.get_class_source, "hang.apk", "a.b.Foo")
        self.assertIn("took longer than 1 s and was stopped", text)
        self.assertIsNotNone(bridge.process.poll())
        self.assertIsNot(self.m.SESSION.get("hang.apk"), bridge)

    def test_out_of_memory_and_a_failed_load_are_said(self):
        self.put("oom.apk", b"PK")
        self.assertIn("ran out of memory", self.refused(self.m.open_file, "oom.apk"))
        self.put("broken.apk", b"PK")
        self.assertIn("jadx could not load the file: bad", self.refused(self.m.open_file, "broken.apk"))

    def test_parts_unknown_classes_and_refusals(self):
        self.bridge("good.apk").ready(10)
        text = self.m.get_class_source("good.apk", "a.b.Foo")
        self.assertIn("lines 1-400 of 1000 (more: get_class_source class_name='a.b.Foo' start_line=401)", text)
        self.assertIn("1000  line 1000", self.m.get_class_source("good.apk", "a.b.Foo", start_line=801))
        self.assertIn("similar: a.b.Foo", self.refused(self.m.get_class_source, "good.apk", "a.b.Fooo"))
        self.assertIn("no class x", self.refused(self.m.get_smali, "good.apk", "a.b.Foo"))
        self.assertIn("a.b.Foo\na.b.Foo2", self.m.list_classes("good.apk"))
        self.assertIn("a.b  2 classes", self.m.list_packages("good.apk"))


@unittest.skipIf(mcp is None or not HAVE_JADX, "jadx is not at hand (inside the image it is; else set "
                 "SANDBOX_AI_MCP_JAVA, SANDBOX_AI_MCP_JADX_JAR and SANDBOX_AI_MCP_JADX_BRIDGE)")
class RealJadx(Base):
    """Every tool with jadx 1.5.6 on the fixtures (built from tests/fixtures/java-demo)."""

    def setUp(self):
        super().setUp()
        for name, value in REAL.items():
            patcher = mock.patch.object(self.m, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        data = fixtures()
        self.put("apps/demo.apk", data["demo.apk"])
        self.put("apps/demo.jar", data["demo.jar"])

    def loaded(self, path: str) -> str:
        deadline = time.monotonic() + 120
        while True:
            text = self.m.open_file(path)
            if "still loading" not in text or time.monotonic() > deadline:
                return text

    def test_an_apk(self):
        apk = "apps/demo.apk"
        summary = self.loaded(apk)
        for expected in ("loaded with jadx 1.5.6: 2 classes (3 with inner classes) in 1 packages",
                         "app package: org.example.demo, version 1.0", "android.permission.INTERNET",
                         "launcher activity: org.example.demo.Main"):
            self.assertIn(expected, summary)
        outline = self.m.class_outline(apk, "org/example/demo/Checker")
        self.assertIn("public boolean checkPassword(java.lang.String) signature: checkPassword(Ljava/lang/String;)Z",
                      outline)
        self.assertIn("inner classes: org.example.demo.Checker.Result", outline)
        self.assertIn("inner class of org.example.demo.Checker", self.m.class_outline(apk, "org.example.demo.Checker$Result"))
        source = self.m.get_class_source(apk, "org.example.demo.Checker")
        self.assertIn('public static final String MARKER = "MCPHUB-TEST-MARKER";', source)
        method = self.m.get_method_source(apk, "org.example.demo.Checker", "greet")
        self.assertIn("(2 found)", method)
        self.assertIn('return "Hello, " + str + "!";', method)
        one = self.m.get_method_source(apk, "org.example.demo.Checker", "greet", signature="greet()Ljava/lang/String;")
        self.assertIn("(1 found)", one)
        self.assertIn("its methods: <init>()V", self.refused(self.m.get_method_source, apk, "org.example.demo.Checker",
                                                             "nope"))
        self.assertIn("invoke-virtual {v0, p0}, Lorg/example/demo/Checker;->checkPassword(Ljava/lang/String;)Z",
                      self.m.get_smali(apk, "org.example.demo.Main"))
        self.assertIn("method org.example.demo.Main.main([Ljava/lang/String;)V",
                      self.m.find_usages(apk, "org.example.demo.Checker", method_name="checkPassword"))
        self.assertIn("class org.example.demo.Main", self.m.find_usages(apk, "org.example.demo.Checker"))
        self.assertIn("method org.example.demo.Checker.checkPassword(Ljava/lang/String;)Z",
                      self.m.find_usages(apk, "org.example.demo.Checker", field_name="attempts"))
        self.assertIn('org.example.demo.Checker:10: return "hunter2".equals(str);',
                      self.m.search_code(apk, "HUNTER2", ignore_case=True))
        self.assertIn("0 matches", self.m.search_code(apk, "HUNTER2"))
        self.assertIn("0 matches", self.m.search_code(apk, "hunter2", package="org.other"))
        self.assertIn("field org.example.demo.Checker.attempts : int", self.m.search_names(apk, "ATTEMPT"))
        manifest = self.m.get_manifest(apk)
        self.assertIn('android:name="android.intent.category.LAUNCHER"', manifest)
        resources = self.m.list_resources(apk)
        self.assertIn("assets/config.json  json, 76 bytes", resources)
        self.assertIn('"marker": "MCPHUB-TEST-MARKER"', self.m.get_resource(apk, "assets/config.json"))
        self.assertIn("binary, 2,208 bytes", self.m.get_resource(apk, "classes.dex"))
        self.assertIn("no resource nope", self.refused(self.m.get_resource, apk, "nope"))
        self.assertTrue(os.listdir(self.scratch), "the JVM's scratch folder is below SCRATCH")

    def test_a_jar_and_switching_files(self):
        self.loaded("apps/demo.apk")
        summary = self.loaded("apps/demo.jar")
        self.assertIn("no AndroidManifest.xml", summary)
        self.assertIn("checker.checkPassword(", self.m.get_class_source("apps/demo.jar", "org.example.demo.Main"))
        self.assertIn(".method public checkPassword(Ljava/lang/String;)Z",
                      self.m.get_smali("apps/demo.jar", "org.example.demo.Checker"))
        self.assertIn("has no AndroidManifest.xml", self.refused(self.m.get_manifest, "apps/demo.jar"))
        self.m.SESSION.close()
        self.assertEqual(os.listdir(self.scratch), [], "closing removes the scratch folder")

    def test_a_file_jadx_cannot_read(self):
        self.put("apps/garbage.apk", b"PK\x03\x04 not really a zip" * 10)
        text = self.refused(self.loaded, "apps/garbage.apk")
        self.assertIn("jadx could not load the file", text)
        self.assertIn("/work/apps/garbage.apk", text)
        self.assertNotIn(self.scratch, text, "the scratch folder is not named")


@unittest.skipIf(mcp is None, "the server's requirements are not installed")
class Server(unittest.TestCase):
    def test_tools_only_and_the_recorded_tools(self):
        module = load()
        from mcp import types
        handlers = module.mcp._mcp_server.request_handlers
        for request in (types.ListResourcesRequest, types.ListPromptsRequest, types.ReadResourceRequest):
            self.assertNotIn(request, handlers)
        from mcp.server.lowlevel.server import NotificationOptions
        capabilities = module.mcp._mcp_server.get_capabilities(NotificationOptions(), {})
        self.assertIsNone(capabilities.resources)
        self.assertIsNone(capabilities.prompts)
        recorded = json.loads((ROOT / "servers" / "jadx" / "tools.json").read_text())
        import asyncio
        tools = asyncio.run(module.mcp.list_tools())
        self.assertEqual(sorted(t.name for t in tools), recorded["tools"])
        for tool in tools:
            self.assertTrue(tool.annotations.readOnlyHint, tool.name)
            self.assertFalse(tool.annotations.openWorldHint, tool.name)


if __name__ == "__main__":
    unittest.main()
