"""The smali server (servers/smali): its own code offline - paths (no '..', nothing outside /work and /out, no link,
no folder, pipe, empty or oversized file), arguments that would become options, the names it may write in /out,
answers in parts (400 lines / 24,000 characters), the command lines of baksmali, smali, apktool, zipalign, keytool and
apksigner against stand-ins (empty environment, the checked descriptor passed, the DEX entry behind the path, only
the apktool flags a call may set, the time and output limits, the scratch folder removed, the throwaway keystore gone
with it) - and, where the tools are at hand (inside the image, or with SANDBOX_AI_MCP_JAVA, _BAKSMALI_CLASSPATH,
_SMALI_CLASSPATH, _APKTOOL_JAR, _APKTOOL_AAPT2, _APKTOOL_FRAMEWORK, _APKSIGNER_CLASSPATH, _ZIPALIGN, _KEYTOOL), every tool
on the fixtures demo.apk and demo-res.apk with the real baksmali 3.0.10, smali 3.0.10, apktool 3.0.3, zipalign and
apksigner. The folders are temporary ones the module's ROOTS point at. CI runs this inside the image too
(tests/test_own_servers.py test_smali)."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
import textwrap
import unittest
from unittest import mock
import zipfile

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "servers" / "smali" / "src" / "server.py"

try:
    import mcp  # noqa: F401 - the server's own dependency
    from mcp.server.fastmcp.exceptions import ToolError
except ImportError:
    mcp = None
    ToolError = Exception


def load():
    spec = importlib.util.spec_from_file_location("server_smali_test", SERVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixtures() -> dict[str, bytes]:
    spec = importlib.util.spec_from_file_location("fixtures_smali_test", ROOT / "scripts" / "fixtures.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {f["path"]: f["data"] for f in module.load()}


#: What the image has; the environment points the tests at a checkout's own tools.
IMAGE = {"JAVA": "/usr/lib/jvm/java-21-openjdk-amd64/bin/java",
         "KEYTOOL": "/usr/lib/jvm/java-21-openjdk-amd64/bin/keytool",
         "BAKSMALI_CLASSPATH": ":".join(f"/opt/smali/{jar}.jar" for jar in (
             "smali-baksmali-3.0.10", "smali-dexlib2-3.0.10", "smali-util-3.0.10", "guava-31.1-android",
             "jcommander-1.85", "jsr305-3.0.2", "failureaccess-1.0.1",
             "listenablefuture-9999.0-empty-to-avoid-conflict-with-guava", "checker-qual-3.12.0",
             "error_prone_annotations-2.11.0", "j2objc-annotations-1.3")),
         "SMALI_CLASSPATH": ":".join(f"/opt/smali/{jar}.jar" for jar in (
             "smali-3.0.10", "smali-dexlib2-3.0.10", "antlr-3.5.2", "smali-util-3.0.10", "antlr-runtime-3.5.2",
             "jcommander-1.85", "stringtemplate-3.2.1", "guava-31.1-android", "jsr305-3.0.2", "ST4-4.0.8",
             "antlr-2.7.7", "failureaccess-1.0.1", "listenablefuture-9999.0-empty-to-avoid-conflict-with-guava",
             "checker-qual-3.12.0", "error_prone_annotations-2.11.0", "j2objc-annotations-1.3")),
         "APKTOOL_JAR": "/opt/apktool/apktool_3.0.3.jar",
         "APKTOOL_AAPT2": "/opt/apktool/aapt2",
         "APKTOOL_FRAMEWORK": "/opt/apktool/framework",
         "APKSIGNER_CLASSPATH": "/usr/share/java/apksigner-35.0.2.jar:/usr/share/java/apksig-0.9.jar",
         "ZIPALIGN": "/usr/bin/zipalign"}
REAL = {name: os.environ.get(f"SANDBOX_AI_MCP_{name}") or value for name, value in IMAGE.items()}
HAVE_TOOLS = all(os.path.exists(part) for name in REAL for part in REAL[name].split(":"))

#: A stand-in for a JVM or a tool: records its arguments, environment and working folder, or hangs, or floods stdout.
FAKE_TOOL = textwrap.dedent("""
    import json, os, sys, time
    arguments = sys.argv[1:]
    subject = [a for a in arguments if a.startswith("/") and "/in/" in a]
    read = {}
    for path in subject:
        base = path.split("/in/", 1)[1].split("/")[0]
        real = path.split("/in/")[0] + "/in/" + base
        try:
            read[base] = len(open(real, "rb").read()) if os.path.isfile(real) else sorted(os.listdir(real))
        except OSError as exc:
            read[base] = f"error {exc.errno}"
    if "hang" in " ".join(arguments):
        time.sleep(60)
    if "flood" in " ".join(arguments):
        while True:
            sys.stdout.write("x" * 65536)
    if "list" in arguments and "classes" in arguments:
        print("Lorg/example/Demo;")
        print("Lorg/example/Other;")
    out = [a for i, a in enumerate(arguments) if i and arguments[i - 1] in ("-o", "--out", "--output")]
    for path in out:
        if path.endswith((".dex", ".apk", ".p12")):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "wb").write(b"PK\\x03\\x04made-by-the-stand-in")
        else:
            os.makedirs(os.path.join(path, "org", "example"), exist_ok=True)
            open(os.path.join(path, "org", "example", "Demo.smali"), "w").write(
                ".class public Lorg/example/Demo;\\n.super Ljava/lang/Object;\\n")
    print(json.dumps({"arguments": arguments, "env": dict(os.environ), "cwd": os.getcwd(), "read": read,
                      "files": sorted(os.listdir(os.getcwd()))}))
""")


def apk(entries: dict[str, bytes]) -> bytes:
    import io
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


@unittest.skipIf(mcp is None, "the server's requirements are not installed (pip install --require-hashes -r "
                              "servers/smali/requirements.txt)")
class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load()

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="smali-test-")
        self.work = os.path.join(self.folder, "work")
        self.out = os.path.join(self.folder, "out")
        self.scratch = os.path.join(self.folder, "scratch")
        os.makedirs(self.work)
        os.makedirs(self.out)
        for name, value in (("ROOTS", {"/work": self.work, "/out": self.out}), ("SCRATCH", self.scratch)):
            patcher = mock.patch.object(self.m, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.m.TEXTS.texts.clear()
        self.addCleanup(self.m.TEXTS.texts.clear)
        self.addCleanup(shutil.rmtree, self.folder, True)

    def put(self, name: str, data: bytes, where=None) -> str:
        path = os.path.join(where or self.work, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(data)
        return path

    def fixture(self, name: str) -> str:
        return self.put(name, fixtures()[name])

    def refused(self, call, *args, **kwargs) -> str:
        with self.assertRaises(ToolError) as caught:
            call(*args, **kwargs)
        return str(caught.exception)

    def fake(self, name: str = "tool") -> str:
        """A stand-in for a tool, as an executable script; returns its path."""
        path = os.path.join(self.folder, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(f"#!{sys.executable}\n" + FAKE_TOOL)
        os.chmod(path, 0o755)
        return path

    def use_fakes(self) -> None:
        """Every tool replaced by the stand-in (one script, it sees its own arguments)."""
        for name in ("JAVA", "KEYTOOL", "ZIPALIGN"):
            patcher = mock.patch.object(self.m, name, self.fake(name.lower()))
            patcher.start()
            self.addCleanup(patcher.stop)

    def recorded(self, text: str) -> dict:
        """What the stand-in printed (the last JSON line)."""
        lines = [line for line in text.splitlines() if line.startswith("{")]
        self.assertTrue(lines, f"the stand-in printed no JSON: {text[:400]}")
        return json.loads(lines[-1])


class Paths(Base):
    def test_only_regular_files_in_work_and_out_are_read(self):
        self.put("apps/a.apk", apk({"classes.dex": b"dex\n035\0"}))
        os.symlink(os.path.join(self.work, "apps", "a.apk"), os.path.join(self.work, "link.apk"))
        os.mkfifo(os.path.join(self.work, "pipe.apk"))
        self.put("empty.apk", b"")
        for path, expected in {"../x.apk": "'..' is not allowed", "/etc/passwd": "only files in",
                               "link.apk": "is a link", "apps": "is a folder", "pipe.apk": "not a regular file",
                               "empty.apk": "is empty", "none.apk": "does not exist", "a\tb": "path:",
                               "~/x.apk": "'~' is not a folder here"}.items():
            with self.subTest(path=path):
                self.assertIn(expected, self.refused(self.m.list_dex, path))
        listed = self.m.list_files()
        self.assertIn("/work/apps/a.apk", listed)
        self.assertNotIn("link.apk", listed)
        self.assertIn("classes.dex", self.m.list_dex("/work/apps/a.apk"))
        self.put("plain.dex", b"dex\n035\0" + b"\0" * 64)
        self.assertIn("is a plain DEX file", self.m.list_dex("plain.dex"))

    def test_a_file_in_out_can_be_read_back(self):
        self.put("made.apk", apk({"classes.dex": b"dex\n035\0"}), where=self.out)
        self.assertIn("/out/made.apk", self.m.list_output())
        self.assertIn("classes.dex", self.m.list_dex("/out/made.apk"))

    def test_a_folder_outside_the_roots_is_refused(self):
        for folder, expected in {"/etc": "only files in", "../x": "'..' is not allowed",
                                 "nothing": "does not exist"}.items():
            with self.subTest(folder=folder):
                self.assertIn(expected, self.refused(self.m.assemble, folder, "x.dex"))
        os.makedirs(os.path.join(self.out, "real"))
        os.symlink(os.path.join(self.out, "real"), os.path.join(self.out, "link"))
        self.assertIn("is a link", self.refused(self.m.assemble, "/out/link", "x.dex"))

    def test_a_folder_of_work_is_taken_too(self):
        os.makedirs(os.path.join(self.work, "smali"))
        self.put("smali/a.smali", b".class public La;\n")
        self.use_fakes()
        self.assertIn("/out/x.dex", self.m.assemble("/work/smali", "x.dex"))


class Arguments(Base):
    def test_class_names(self):
        for given, wanted in {"org.example.demo.Checker": "org/example/demo/Checker",
                              "org/example/demo/Checker": "org/example/demo/Checker",
                              "Lorg/example/demo/Checker;": "org/example/demo/Checker",
                              "org.example.demo.Checker.smali": "org/example/demo/Checker",
                              "Outer$Inner": "Outer$Inner"}.items():
            with self.subTest(given=given):
                self.assertEqual(self.m.check_class(given), wanted)
        for bad in ("--classes", "-x", "a,b", "a b", "org/../etc", "/abs", "a//b", "a/", ""):
            with self.subTest(bad=bad):
                with self.assertRaises(self.m.Refused):
                    self.m.check_class(bad)

    def test_names_written_in_out(self):
        self.assertEqual(self.m.check_name("decoded", "out_name"), "decoded")
        for bad in ("../escape", "a/b", "/abs", ".", "..", "-o", "x" * 65, "a b", ""):
            with self.subTest(bad=bad):
                with self.assertRaises(self.m.Refused):
                    self.m.check_name(bad, "out_name")

    def test_dex_entries_cannot_become_options_or_leave_the_archive(self):
        self.assertEqual(self.m.check_dex_file("classes2.dex", "a.apk"), "classes2.dex")
        self.assertEqual(self.m.check_dex_file("", "a.apk"), "")
        for bad in ("--classes", "-o", "../classes.dex", "/etc/passwd", "a/../b"):
            with self.subTest(bad=bad):
                with self.assertRaises(self.m.Refused):
                    self.m.check_dex_file(bad, "a.apk")

    def test_api_level_and_flags(self):
        self.assertEqual(self.m.check_api(21), 21)
        for bad in (0, 99, True, "21", 1.0):
            with self.subTest(bad=bad):
                with self.assertRaises(self.m.Refused):
                    self.m.check_api(bad)
        with self.assertRaises(self.m.Refused):
            self.m._bool("true", "debug_info")

    def test_an_existing_name_in_out_is_never_overwritten(self):
        self.put("taken.dex", b"x", where=self.out)
        os.makedirs(os.path.join(self.out, "folder"))
        os.symlink("/etc/passwd", os.path.join(self.out, "pointer.dex"))
        self.use_fakes()
        os.makedirs(os.path.join(self.work, "smali"))
        self.put("smali/a.smali", b".class public La;\n")
        for name in ("taken.dex", "folder", "pointer.dex"):
            with self.subTest(name=name):
                self.assertIn("already there", self.refused(self.m.assemble, "/work/smali", name))
        self.assertEqual(sorted(os.listdir(self.out)), ["folder", "pointer.dex", "taken.dex"])

    def test_without_a_writable_out_the_write_tools_say_so(self):
        shutil.rmtree(self.out)
        self.use_fakes()
        os.makedirs(os.path.join(self.work, "smali"))
        self.put("smali/a.smali", b".class public La;\n")
        self.assertIn("/out", self.refused(self.m.assemble, "/work/smali", "x.dex"))


class CommandLines(Base):
    """Every child's command line and environment, against the stand-in."""

    def setUp(self):
        super().setUp()
        self.use_fakes()
        self.printed: list[str] = []
        original = self.m.run

        def recording(command, scratch, seconds, keep_fds=(), what="the tool"):
            text = original(command, scratch, seconds, keep_fds=keep_fds, what=what)
            self.printed.extend(line for line in text.splitlines() if line.startswith("{"))
            return text

        patcher = mock.patch.object(self.m, "run", recording)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.apk = self.fixture("demo-res.apk")

    @property
    def last(self) -> dict:
        self.assertTrue(self.printed, "no child printed anything")
        return json.loads(self.printed[-1])

    def test_baksmali_gets_the_descriptor_the_entry_and_the_api_level(self):
        text = self.m.get_smali("demo-res.apk", "org.example.Demo", dex_file="classes.dex", api_level=29,
                                debug_info=False, use_locals=True)
        self.assertIn("Lorg/example/Demo;", text)
        arguments = self.last["arguments"]
        # Google's thin jars on a class path, baksmali's main class named (their manifests name none)
        self.assertNotIn("-jar", arguments)
        self.assertEqual(arguments[arguments.index("-cp") + 1], self.m.BAKSMALI_CLASSPATH)
        self.assertEqual(arguments[arguments.index("-cp") + 2], "com.android.tools.smali.baksmali.Main")
        self.assertEqual(arguments[arguments.index("-cp") + 3], "disassemble")
        subject = arguments[arguments.index("-cp") + 4]
        self.assertTrue(subject.endswith("/in/demo-res.apk/classes.dex"), subject)
        self.assertEqual(arguments[arguments.index("-a") + 1], "29")
        self.assertEqual(arguments[arguments.index("--debug-info") + 1], "false")
        self.assertIn("--use-locals", arguments)
        self.assertEqual(arguments[arguments.index("--classes") + 1], "Lorg/example/Demo;")
        # the file the JVM read is the one that was checked, through /proc/self/fd
        self.assertEqual(self.last["read"]["demo-res.apk"], os.path.getsize(self.apk))

    def test_the_environment_is_three_variables_and_the_working_folder_is_empty(self):
        self.m.list_classes("demo-res.apk")
        recorded = self.last
        self.assertEqual(sorted(recorded["env"]), ["HOME", "LANG", "PATH"])
        self.assertEqual(recorded["env"]["PATH"], "/usr/bin:/bin")
        self.assertEqual(recorded["files"], [])
        self.assertTrue(recorded["cwd"].startswith(self.scratch), recorded["cwd"])

    def test_smali_runs_from_its_class_path_with_its_main_class(self):
        os.makedirs(os.path.join(self.out, "smali"))
        self.put("smali/A.smali", b".class public LA;\n.super Ljava/lang/Object;\n", where=self.out)
        self.assertIn("/out/a.dex", self.m.assemble("/out/smali", "a.dex", api_level=28))
        arguments = self.last["arguments"]
        self.assertNotIn("-jar", arguments)
        self.assertEqual(arguments[arguments.index("-cp") + 1:arguments.index("-cp") + 4],
                         [self.m.SMALI_CLASSPATH, "com.android.tools.smali.smali.Main", "assemble"])
        self.assertEqual(arguments[arguments.index("-a") + 1], "28")

    def test_the_class_paths_are_the_images(self):
        self.assertEqual(self.m.BAKSMALI_CLASSPATH, IMAGE["BAKSMALI_CLASSPATH"])
        self.assertEqual(self.m.SMALI_CLASSPATH, IMAGE["SMALI_CLASSPATH"])

    def test_the_scratch_folder_is_removed_after_every_call(self):
        self.m.list_classes("demo-res.apk")
        self.assertEqual(os.listdir(self.scratch), [])

    def test_apktool_decode_passes_only_the_flags_a_call_may_set(self):
        self.m.apktool_decode("demo-res.apk", "decoded", no_resources=True, no_debug_info=True)
        arguments = self.last["arguments"]
        self.assertEqual(arguments[arguments.index("-jar") + 1], self.m.APKTOOL_JAR)
        self.assertIn("--no-res", arguments)
        self.assertIn("--no-debug-info", arguments)
        self.assertNotIn("--no-src", arguments)
        self.assertEqual(arguments[arguments.index("--frame-path") + 1], self.m.APKTOOL_FRAMEWORK)
        self.assertEqual(arguments[arguments.index("--jobs") + 1], "1")
        self.assertTrue(os.path.isdir(os.path.join(self.out, "decoded")))

    def test_apktool_build_uses_the_images_aapt2_and_says_the_apk_is_unsigned(self):
        os.makedirs(os.path.join(self.out, "decoded"))
        self.put("decoded/AndroidManifest.xml", b"<manifest/>", where=self.out)
        self.assertIn("only files in /out", self.refused(self.m.apktool_build, "/work/decoded", "x.apk"))
        text = self.m.apktool_build("/out/decoded", "built.apk")
        self.assertIn("**unsigned**", text)
        self.assertIn("sign_apk", text)
        arguments = self.last["arguments"]
        self.assertEqual(arguments[arguments.index("--aapt") + 1], self.m.APKTOOL_AAPT2)
        self.assertEqual(arguments[arguments.index("--frame-path") + 1], self.m.APKTOOL_FRAMEWORK)
        self.assertTrue(arguments[-1].startswith(self.out), arguments[-1])  # the folder itself: aapt2 is a child

    def test_sign_apk_makes_a_throwaway_key_and_leaves_nothing_behind(self):
        self.put("built.apk", apk({"AndroidManifest.xml": b"<manifest/>"}), where=self.out)
        text = self.m.sign_apk("/out/built.apk", "signed.apk")
        self.assertIn("throwaway key", text)
        records = [json.loads(line) for line in self.printed]
        keytools = [record for record in records if "-genkeypair" in record["arguments"]]
        self.assertEqual(len(keytools), 1, [record["arguments"][:3] for record in records])
        arguments = keytools[0]["arguments"]
        self.assertIn("-storetype", arguments)
        self.assertEqual(arguments[arguments.index("-validity") + 1], "1")
        self.assertIn("throwaway", arguments[arguments.index("-dname") + 1])
        password = arguments[arguments.index("-storepass") + 1]
        self.assertGreaterEqual(len(password), 20, "a random password per call")
        self.assertNotIn(password, text, "the password is in no answer")
        self.assertEqual(os.listdir(self.scratch), [], "the keystore went with the scratch folder")
        self.assertTrue(os.path.isfile(os.path.join(self.out, "signed.apk")))
        # zipalign, then keytool, then apksigner twice (sign, verify)
        self.assertEqual(len([r for r in records if self.m.APKSIGNER_MAIN in r["arguments"]]), 2,
                         [r["arguments"][:3] for r in records])
        self.assertEqual(len([r for r in records if "-p" in r["arguments"] and "4" in r["arguments"]]), 1)

    def test_a_tool_that_hangs_or_floods_is_stopped(self):
        with mock.patch.object(self.m, "BAKSMALI_SECONDS", 1.0):
            self.put("hang.apk", fixtures()["demo-res.apk"])
            self.assertIn("took longer than", self.refused(self.m.list_classes, "hang.apk"))
        with mock.patch.object(self.m, "MAX_OUTPUT_BYTES", 1 << 16):
            self.put("flood.apk", fixtures()["demo-res.apk"])
            self.assertIn("printed more than", self.refused(self.m.list_classes, "flood.apk"))
        self.assertEqual(os.listdir(self.scratch), [])


class Answers(Base):
    def test_parts_of_400_lines_and_24000_characters(self):
        text = "\n".join(f"line {number}" for number in range(1, 1001))
        first = self.m.page("smali of X", text, 1, "get_smali")
        self.assertIn("lines 1-400 of 1000", first)
        self.assertIn("start_line=401", first)
        self.assertLessEqual(len(first), self.m.MAX_CHARS + 200)
        last = self.m.page("smali of X", text, 801, "get_smali")
        self.assertIn("lines 801-1000 of 1000", last)
        self.assertNotIn("more:", last)
        with self.assertRaises(self.m.Refused):
            self.m.page("smali of X", text, 1001, "get_smali")
        wide = "\n".join("x" * 3000 for _ in range(10))
        self.assertIn("[line cut at 2000 characters]", self.m.page("x", wide, 1, "x"))

    def test_control_characters_of_the_input_never_reach_an_answer(self):
        self.assertNotIn("‮", self.m.shown("a‮b"))
        self.assertNotIn("\x00", self.m.shown("a\x00b"))
        self.assertIn("?", self.m.page("t itle", "a‮b", 1, "x"))

    def test_lists_have_an_offset(self):
        items = [f"org.example.C{number}" for number in range(500)]
        text = self.m.listing("classes of x", items, 0, "classes")
        self.assertIn("500 classes, 1-300 shown", text)
        self.assertIn("offset=300", text)
        with self.assertRaises(self.m.Refused):
            self.m.listing("classes of x", items, 501, "classes")


class ToolsOnly(Base):
    def test_no_resources_or_prompts_and_every_tool_is_annotated(self):
        import asyncio
        handlers = self.m.mcp._mcp_server.request_handlers
        from mcp import types as mcp_types
        for request in (mcp_types.ListResourcesRequest, mcp_types.ListPromptsRequest, mcp_types.GetPromptRequest):
            self.assertNotIn(request, handlers)
        tools = asyncio.run(self.m.mcp.list_tools())
        names = sorted(tool.name for tool in tools)
        self.assertEqual(names, json.loads((ROOT / "servers" / "smali" / "tools.json").read_text())["tools"])
        reads = sorted(tool.name for tool in tools if tool.annotations and tool.annotations.readOnlyHint)
        self.assertEqual(reads, json.loads((ROOT / "servers" / "smali" / "tools.json").read_text())["read_only_tools"])
        for tool in tools:
            self.assertFalse(tool.annotations.openWorldHint, tool.name)
            self.assertTrue(tool.description and len(tool.description) > 40, tool.name)


@unittest.skipUnless(HAVE_TOOLS, "the real tools are not here (SANDBOX_AI_MCP_JAVA, _BAKSMALI_CLASSPATH, "
                                 "_SMALI_CLASSPATH, "
                                 "_APKTOOL_JAR, _APKTOOL_AAPT2, _APKTOOL_FRAMEWORK, _APKSIGNER_CLASSPATH, "
                                 "_ZIPALIGN, _KEYTOOL)")
class WithTheRealTools(Base):
    """Every tool against baksmali 3.0.10, smali 3.0.10, apktool 3.0.3, zipalign and apksigner."""

    def setUp(self):
        super().setUp()
        for name, value in REAL.items():
            patcher = mock.patch.object(self.m, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.fixture("demo.apk")
        self.fixture("demo-res.apk")

    def test_list_dex_and_list_classes(self):
        self.assertIn("classes.dex", self.m.list_dex("demo-res.apk"))
        classes = self.m.list_classes("demo-res.apk")
        self.assertIn("org.example.demo.Checker", classes)
        self.assertIn("org.example.demo.Main", classes)
        self.assertIn("org.example.demo.Checker", self.m.list_classes("demo-res.apk", dex_file="classes.dex"))
        self.assertIn("org.example.demo.Checker$Result",
                      self.m.list_classes("demo.apk", package="org.example", name_filter="result"))
        self.assertIn("no class org.example.demo.Chekcer", self.refused(self.m.get_smali, "demo.apk",
                                                                        "org.example.demo.Chekcer"))
        self.assertIn("similar: org.example.demo.Checker", self.refused(self.m.get_smali, "demo.apk",
                                                                        "org.example.demo.Chekcer"))

    def test_get_smali_of_one_class_in_parts(self):
        text = self.m.get_smali("demo.apk", "org.example.demo.Checker")
        self.assertIn(".class public Lorg/example/demo/Checker;", text)
        self.assertIn('const-string', text)
        self.assertIn("hunter2", text)
        self.assertIn(".method public checkPassword(Ljava/lang/String;)Z", text)
        self.assertIn("lines 1-", text)
        without = self.m.get_smali("demo.apk", "org.example.demo.Checker", debug_info=False)
        self.assertNotIn(".line", without)
        locals_text = self.m.get_smali("demo.apk", "org.example.demo.Checker", use_locals=True)
        self.assertIn(".locals", locals_text)

    def test_search_smali_finds_strings_and_calls(self):
        text = self.m.search_smali("demo.apk", "hunter2")
        self.assertIn("org.example.demo.Checker:", text)
        self.assertIn("searched to the end", text)
        self.assertIn("org.example.demo.Main:", self.m.search_smali("demo.apk", "checkPassword"))
        self.assertIn("no classes from 99", self.m.search_smali("demo.apk", "hunter2", start_class=99))
        one = self.m.search_smali("demo.apk", "const-string", max_results=1)
        self.assertEqual(len([line for line in one.splitlines() if ":" in line and line.startswith("org.")]), 1)

    def test_disassemble_and_assemble_round_trip(self):
        text = self.m.disassemble("demo-res.apk", "smali")
        self.assertIn("3 smali files", text)
        self.assertTrue(os.path.isfile(os.path.join(self.out, "smali", "org", "example", "demo", "Checker.smali")))
        built = self.m.assemble("/out/smali", "again.dex")
        self.assertIn("/out/again.dex", built)
        self.assertIn("not an app", built)
        dex = os.path.join(self.out, "again.dex")
        with open(dex, "rb") as handle:
            self.assertEqual(handle.read(4), b"dex\n")
        self.assertIn("org.example.demo.Checker", self.m.list_classes("/out/again.dex"))
        only = self.m.disassemble("demo.apk", "one", classes="org.example.demo.Main")
        self.assertIn("1 smali files", only)

    def test_apktool_decode_build_and_sign(self):
        decoded = self.m.apktool_decode("demo-res.apk", "decoded")
        self.assertIn("/out/decoded", decoded)
        for name in ("AndroidManifest.xml", "apktool.yml"):
            self.assertTrue(os.path.isfile(os.path.join(self.out, "decoded", name)), name)
        with open(os.path.join(self.out, "decoded", "AndroidManifest.xml"), encoding="utf-8") as handle:
            manifest = handle.read()
        self.assertIn("org.example.demo", manifest)
        self.assertTrue(os.path.isfile(os.path.join(self.out, "decoded", "res", "values", "strings.xml")))
        self.assertTrue(os.path.isfile(os.path.join(self.out, "decoded", "smali", "org", "example", "demo",
                                                    "Checker.smali")))
        built = self.m.apktool_build("/out/decoded", "rebuilt.apk")
        self.assertIn("**unsigned**", built)
        with zipfile.ZipFile(os.path.join(self.out, "rebuilt.apk")) as archive:
            names = archive.namelist()
        self.assertIn("classes.dex", names)
        self.assertIn("AndroidManifest.xml", names)
        self.assertFalse([name for name in names if name.startswith("META-INF/") and name.endswith(".RSA")])
        signed = self.m.sign_apk("/out/rebuilt.apk", "signed.apk")
        self.assertIn("throwaway", signed)
        self.assertIn("certificate", signed.lower())
        with zipfile.ZipFile(os.path.join(self.out, "signed.apk")) as archive:
            names = archive.namelist()
        self.assertTrue([name for name in names if name.startswith("META-INF/")], names)
        self.assertIn("already there", self.refused(self.m.sign_apk, "/out/rebuilt.apk", "signed.apk"))

    def test_only_manifest_and_a_broken_input(self):
        self.assertIn("/out/manifest", self.m.apktool_decode("demo-res.apk", "manifest", only_manifest=True))
        self.assertTrue(os.path.isfile(os.path.join(self.out, "manifest", "AndroidManifest.xml")))
        self.assertFalse(os.path.isdir(os.path.join(self.out, "manifest", "res")))
        self.put("broken.apk", b"PK\x03\x04" + b"\x00" * 200)
        self.assertTrue(self.refused(self.m.list_classes, "broken.apk"))
        self.put("text.apk", b"not an archive at all")
        self.assertIn("neither a zip", self.refused(self.m.list_dex, "text.apk"))


if __name__ == "__main__":
    unittest.main()
