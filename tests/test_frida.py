"""The frida server (servers/frida): its own code offline, with a stand-in for frida's bindings - what it is
configured to reach (FRIDA_DEVICE, FRIDA_ADB_SERVER) and that it reaches nothing else, that frida's local device (the
processes of its own container) is never offered, the write gate (FRIDA_WRITE=1 for spawn, resume, kill,
push_server), scripts (inline or a .js file of /work: no '..', no link, size-capped) and the messages they post
(count, size, control characters), sessions, the frida-server binaries of the image (unpacked from the release files
into /out, never over an existing name), adb called only against the configured server with an empty environment,
and the answers in parts (400 lines / 24,000 characters). With the real bindings installed (the image, or `pip
install --require-hashes -r servers/frida/requirements.txt`) the version is checked against the binaries' version
and the local device is refused for real. No device is needed anywhere: nothing here talks to one. CI runs this
inside the image too (tests/test_own_servers.py test_frida)."""
from __future__ import annotations

import importlib.util
import json
import lzma
import os
from pathlib import Path
import shutil
import sys
import re
import tempfile
import types as pytypes
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "servers" / "frida" / "src" / "server.py"

try:
    import mcp  # noqa: F401 - the server's own dependency
    from mcp.server.fastmcp.exceptions import ToolError
except ImportError:
    mcp = None
    ToolError = Exception

try:
    import frida as real_frida
except ImportError:
    real_frida = None


# --- a stand-in for frida's bindings ---------------------------------------------------------------------------------

class FakeError(Exception):
    pass


class FakeScript:
    def __init__(self, session, source):
        self.session, self.source, self.handlers, self.loaded = session, source, [], False

    def on(self, event, handler):
        if event == "message":
            self.handlers.append(handler)

    def load(self):
        self.loaded = True
        for message in self.session.answers(self.source):
            for handler in self.handlers:
                handler(message, None)

    def unload(self):
        self.loaded = False


class FakeSession:
    def __init__(self, device, target, replies=None):
        self.device, self.target, self.is_detached = device, target, False
        self.replies = replies if replies is not None else {}
        self.scripts = []

    def answers(self, source):
        for key, value in self.replies.items():
            if key in source:
                return value
        return [{"type": "send", "payload": "nothing matched"}]

    def create_script(self, source):
        script = FakeScript(self, source)
        self.scripts.append(script)
        return script

    def detach(self):
        self.is_detached = True


class FakeProcess:
    def __init__(self, pid, name):
        self.pid, self.name = pid, name


class FakeApp:
    def __init__(self, identifier, name, pid=0):
        self.identifier, self.name, self.pid = identifier, name, pid


class FakeDevice:
    def __init__(self, id, name, dtype, replies=None, parameters=None):
        self.id, self.name, self.type = id, name, dtype
        self.replies = replies or {}
        self.parameters = parameters or {"os": {"id": "android", "version": "14"}, "arch": "arm64", "access": "full"}
        self.spawned, self.resumed, self.killed = [], [], []

    def query_system_parameters(self):
        return self.parameters

    def enumerate_processes(self):
        return [FakeProcess(1, "init"), FakeProcess(4242, "com.example.app"), FakeProcess(99, "zygote64")]

    def enumerate_applications(self):
        return [FakeApp("com.example.app", "Example", 4242), FakeApp("com.other.app", "Other")]

    def attach(self, target):
        return FakeSession(self, target, self.replies)

    def spawn(self, program):
        self.spawned.append(program)
        return 5151

    def resume(self, pid):
        self.resumed.append(pid)

    def kill(self, pid):
        self.killed.append(pid)


class FakeManager:
    def __init__(self):
        self.added, self.removed, self.devices = [], [], []

    def add_remote_device(self, address, **kwargs):
        self.added.append(address)
        device = FakeDevice(address, f"frida-server at {address}", "remote")
        return device

    def remove_remote_device(self, address):
        self.removed.append(address)

    def enumerate_devices(self):
        return [FakeDevice("local", "Local System", "local"), FakeDevice("socket", "Local Socket", "remote")] + \
            self.devices


def fake_frida() -> pytypes.ModuleType:
    """A module that looks like frida's bindings to the server (the errors it catches, the device manager)."""
    module = pytypes.ModuleType("frida")
    module.__version__ = "17.25.2"
    names = ("FridaError", "ServerNotRunningError", "TransportError", "InvalidArgumentError",
             "PermissionDeniedError", "ProcessNotFoundError", "NotSupportedError")
    module.FridaError = type("FridaError", (Exception,), {})
    for name in names[1:]:
        setattr(module, name, type(name, (module.FridaError,), {}))
    manager = FakeManager()
    module.get_device_manager = lambda: manager
    module.manager = manager
    return module


def load(device: str = "", adb_server: str = "", write: bool = False, frida_module=None):
    """The server module, loaded with that configuration and frida's bindings replaced."""
    environment = {"FRIDA_DEVICE": device, "FRIDA_ADB_SERVER": adb_server, "FRIDA_WRITE": "1" if write else ""}
    module = frida_module or fake_frida()
    with mock.patch.dict(os.environ, environment, clear=False), \
            mock.patch.dict(sys.modules, {"frida": module}):
        spec = importlib.util.spec_from_file_location(f"server_frida_test_{id(module)}", SERVER)
        loaded = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(loaded)
    return loaded


@unittest.skipIf(mcp is None, "the server's requirements are not installed (pip install --require-hashes -r "
                              "servers/frida/requirements.txt)")
class Base(unittest.TestCase):
    DEVICE = "192.168.1.33:27042"

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="frida-test-")
        self.work = os.path.join(self.folder, "work")
        self.out = os.path.join(self.folder, "out")
        self.binaries = os.path.join(self.folder, "binaries")
        self.scratch = os.path.join(self.folder, "scratch")
        os.makedirs(self.work)
        os.makedirs(self.out)
        self.addCleanup(shutil.rmtree, self.folder, True)

    def server(self, **kwargs):
        module = load(**kwargs)
        for name, value in (("ROOTS", {"/work": self.work, "/out": self.out}), ("BINARIES", self.binaries),
                            ("SCRATCH", self.scratch)):
            patcher = mock.patch.object(module, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(module.DEVICES.close)
        return module

    def binary(self, platform: str, abi: str, kind: str, payload: bytes = b"ELF-stand-in") -> str:
        """A stand-in release file (xz, as Frida publishes them) in the image's binary folder."""
        name = f"frida-{kind}-17.25.2-{platform}-{abi}" + (".so" if kind == "gadget" else "") + ".xz"
        path = os.path.join(self.binaries, platform, abi, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(lzma.compress(payload))
        return path

    def put(self, name: str, text: str) -> str:
        path = os.path.join(self.work, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def refused(self, call, *args, **kwargs) -> str:
        with self.assertRaises(ToolError) as caught:
            call(*args, **kwargs)
        return str(caught.exception)


class Configuration(Base):
    def test_without_a_device_every_device_tool_says_what_to_configure(self):
        module = self.server()
        for call, args in ((module.list_devices, ()), (module.list_processes, ()), (module.list_applications, ()),
                           (module.attach, ("com.example.app",))):
            with self.subTest(call=call.__name__):
                text = self.refused(call, *args)
                self.assertIn("no device is configured", text)
                self.assertIn("FRIDA_DEVICE", text)
                self.assertIn("--allow-tcp", text)
                self.assertIn("not reachable from this container", text)
        status = module.device_status()
        self.assertIn("FRIDA_DEVICE: not set", status)
        self.assertIn("FRIDA_ADB_SERVER: not set", status)
        self.assertIn("FRIDA_WRITE: not set", status)

    def test_the_configured_device_is_the_only_address_it_connects_to(self):
        module = self.server(device=self.DEVICE)
        text = module.list_devices()
        self.assertIn(self.DEVICE, text)
        self.assertEqual(module.frida.manager.added, [self.DEVICE], "one add_remote_device, with that address")
        module.list_processes()
        self.assertEqual(module.frida.manager.added, [self.DEVICE], "the device is kept, not added again")

    def test_fridas_local_device_is_never_offered_or_used(self):
        module = self.server(device=self.DEVICE, adb_server="192.168.1.10:5037")
        listed = module.list_devices()
        self.assertNotIn("Local System", listed)
        self.assertNotIn("local", listed.split("\n")[0])
        for name in ("local", "socket", "barebone"):
            with self.subTest(device=name):
                text = self.refused(module.list_processes, name)
                self.assertIn("frida's own device of this container", text)
        self.assertIn("never offered", module.device_status())

    def test_a_bad_endpoint_is_refused_before_anything_connects(self):
        for value in ("192.168.1.33", "192.168.1.33:0", "192.168.1.33:70000", "a b:1", "http://x:1"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    load().endpoint(value, "FRIDA_DEVICE")
        module = self.server(device="192.168.1.33")   # a value changed in the definition by hand
        self.assertIn("FRIDA_DEVICE must be HOST:PORT", self.refused(module.list_devices))

    def test_the_adb_server_is_the_one_configured_and_frida_is_told_about_it(self):
        module = self.server(adb_server="192.168.1.10:5037")
        self.assertEqual(module.ADB_ENV, {"ANDROID_ADB_SERVER_ADDRESS": "192.168.1.10",
                                          "ANDROID_ADB_SERVER_PORT": "5037"},
                         "frida and adb are told about the configured adb server, and about no other")
        calls = []
        with mock.patch.object(module.subprocess, "run",
                               lambda *args, **kwargs: calls.append((args, kwargs)) or mock.Mock(
                                   returncode=0, stdout=b"arm64-v8a\n", stderr=b"")):
            module.adb(["shell", "getprop", "ro.product.cpu.abi"], serial="emulator-5554")
        (command,), keywords = calls[0]
        self.assertEqual(command[:7], [module.ADB, "-H", "192.168.1.10", "-P", "5037", "-s", "emulator-5554"])
        self.assertEqual(sorted(keywords["env"]), ["ANDROID_ADB_SERVER_ADDRESS", "ANDROID_ADB_SERVER_PORT", "HOME",
                                                   "LANG", "PATH"])
        self.assertTrue(keywords["start_new_session"])
        self.assertEqual(keywords["stdin"], module.subprocess.DEVNULL)
        self.assertGreater(keywords["timeout"], 0)

    def test_without_an_adb_server_the_adb_tools_say_so(self):
        module = self.server(device=self.DEVICE, write=True)
        text = self.refused(module.push_server)
        self.assertIn("FRIDA_ADB_SERVER", text)
        self.assertIn("export_server", text)
        with self.assertRaises(module.Refused):
            module.adb(["shell", "true"])


class WriteGate(Base):
    def test_spawn_resume_kill_and_push_need_the_gate(self):
        module = self.server(device=self.DEVICE)
        for call, args in ((module.spawn, ("com.example.app",)), (module.resume, (5151,)), (module.kill, (4242,)),
                           (module.push_server, ())):
            with self.subTest(call=call.__name__):
                text = self.refused(call, *args)
                self.assertIn("FRIDA_WRITE=1", text)
        self.assertIn("the device is only read", module.device_status())

    def test_with_the_gate_they_work_and_say_what_they_did(self):
        module = self.server(device=self.DEVICE, write=True)
        text = module.spawn("com.example.app")
        self.assertIn("held before its first instruction", text)
        self.assertIn("pid 5151", text)
        self.assertIn("session 1", text)
        self.assertIn("runs now", module.resume(5151))
        self.assertIn("was stopped", module.kill(4242))
        device = module.DEVICES.remote_device()
        self.assertEqual(module.frida.manager.added, [self.DEVICE])
        self.assertIn("spawn, resume, kill and push_server are allowed", module.device_status())

    def test_a_program_cannot_be_an_option_or_a_path_with_dots(self):
        module = self.server(device=self.DEVICE, write=True)
        for bad in ("--help", "../etc/passwd", "a b", "x" * 300, ""):
            with self.subTest(bad=bad):
                self.assertIn("program", self.refused(module.spawn, bad))


class Sessions(Base):
    def setUp(self):
        super().setUp()
        self.module = self.server(device=self.DEVICE)

    def test_attach_run_script_and_detach(self):
        text = self.module.attach("com.example.app")
        self.assertIn("session 1: attached to com.example.app", text)
        self.assertIn("session 1: com.example.app", self.module.list_sessions())
        answers = self.module.run_script(1, script="send('hello from the app')", seconds=1)
        self.assertIn("nothing matched", answers)
        self.assertIn("the script stays loaded", answers)
        self.assertIn("session 1 ended", self.module.detach(1))
        self.assertIn("there is no such session", self.refused(self.module.run_script, 1, "send(1)"))

    def test_a_script_comes_from_the_call_or_from_work_but_not_both(self):
        self.module.attach("com.example.app")
        self.put("hooks.js", "send('from the file')\n")
        self.assertIn("/work/hooks.js loaded", self.module.run_script(1, path="hooks.js", seconds=1))
        self.assertIn("not both and not neither", self.refused(self.module.run_script, 1, "send(1)", "hooks.js"))
        self.assertIn("not both and not neither", self.refused(self.module.run_script, 1))

    def test_a_script_file_outside_work_or_a_link_is_refused(self):
        self.module.attach("com.example.app")
        os.symlink("/etc/passwd", os.path.join(self.work, "link.js"))
        self.put("big.js", "x" * (self.module.MAX_SCRIPT_BYTES + 10))
        self.put("empty.js", "")
        self.put("notes.txt", "send(1)")
        for path, expected in {"../etc/passwd": "'..' is not allowed", "/etc/passwd": "only files in /work",
                               "link.js": "is a link", "big.js": "larger than", "empty.js": "is empty",
                               "notes.txt": "a script is a .js file", "none.js": "does not exist"}.items():
            with self.subTest(path=path):
                self.assertIn(expected, self.refused(self.module.run_script, 1, path=path))
        self.assertIn("larger than", self.refused(self.module.run_script, 1,
                                                  "x" * (self.module.MAX_SCRIPT_BYTES + 1)))
        self.assertIn("/work/hooks.js", self.module.run_script(1, path="/work/hooks.js", seconds=1)
                      if os.path.exists(os.path.join(self.work, "hooks.js")) else "/work/hooks.js")

    def test_messages_are_counted_capped_and_filtered(self):
        device = self.module.DEVICES.remote_device()
        device.replies = {"many": [{"type": "send", "payload": f"message {n}"} for n in range(500)],
                          "nasty": [{"type": "send", "payload": "a‮b\x00c"},
                                    {"type": "send", "payload": "y" * 9000},
                                    {"type": "error", "description": "ReferenceError: x is not defined",
                                     "stack": "at <anonymous>"},
                                    {"type": "send", "payload": {"a": [1, 2]}}],
                          }
        number, _ = self.module.DEVICES.attach(device, "com.example.app")
        text = self.module.run_script(number, script="many", seconds=1, max_messages=5)
        self.assertIn("5 messages", text)
        self.assertIn("the limit was reached", text)
        self.assertLessEqual(len(text), self.module.MAX_CHARS + 500)
        text = self.module.run_script(number, script="nasty", seconds=1)
        self.assertNotIn("‮", text)
        self.assertNotIn("\x00", text)
        self.assertIn("?", text)
        self.assertIn("error: ReferenceError", text)
        self.assertIn('{"a": [1, 2]}', text)
        numbered = [line for line in text.split("\n") if re.match(r"^\s*\d+  ", line)]
        self.assertTrue(numbered)
        self.assertTrue(all(len(line) <= self.module.MAX_LINE_CHARS + 60 for line in numbered), max(
            (len(line) for line in numbered), default=0))

    def test_seconds_and_max_messages_are_bounded(self):
        self.module.attach("com.example.app")
        for arguments, expected in (({"seconds": 0}, "seconds"), ({"seconds": 999}, "seconds"),
                                    ({"max_messages": 0}, "max_messages"),
                                    ({"max_messages": 9999}, "max_messages")):
            with self.subTest(arguments=arguments):
                self.assertIn(expected, self.refused(self.module.run_script, 1, "send(1)", **arguments))

    def test_only_a_few_sessions_at_once(self):
        device = self.module.DEVICES.remote_device()
        for _ in range(self.module.MAX_SESSIONS):
            self.module.DEVICES.attach(device, "com.example.app")
        self.assertIn("sessions are open already", self.refused(self.module.attach, "com.example.app"))

    def test_modules_and_exports_come_from_our_own_expression(self):
        device = self.module.DEVICES.remote_device()
        device.replies = {"enumerateModules": [{"type": "send", "payload": [
            ["libssl.so", "0x7f00", 4096, "/system/lib64/libssl.so"],
            ["libc.so", "0x7f10", 8192, "/system/lib64/libc.so"]]}],
            "enumerateExports": [{"type": "send", "payload": [["function", "SSL_read", "0x7f20"]]}]}
        number, _ = self.module.DEVICES.attach(device, "com.example.app")
        text = self.module.enumerate_modules(number)
        self.assertIn("libssl.so", text)
        self.assertIn("/system/lib64/libc.so", text)
        self.assertIn("libssl.so", self.module.enumerate_modules(number, name_filter="ssl"))
        self.assertNotIn("libc.so", self.module.enumerate_modules(number, name_filter="ssl"))
        self.assertIn("SSL_read", self.module.enumerate_exports(number, "libssl.so"))
        for bad in ("../../etc", "lib ssl", "a;b", "x" * 200):
            with self.subTest(bad=bad):
                self.assertIn("module", self.refused(self.module.enumerate_exports, number, bad))
        # the module name reaches the script as JSON, never as text spliced into code
        session = self.module.DEVICES.session(number)["session"]
        self.assertIn('Module.enumerateExports("libssl.so")', session.scripts[-1].source)

    def test_a_process_that_does_not_answer_is_not_waited_for(self):
        device = self.module.DEVICES.remote_device()
        device.replies = {"enumerateModules": []}
        number, _ = self.module.DEVICES.attach(device, "com.example.app")
        with mock.patch.object(self.module, "CALL_SECONDS", 0.2):
            self.assertIn("did not answer", self.refused(self.module.enumerate_modules, number))


class Binaries(Base):
    def test_list_abis_shows_what_the_image_has(self):
        module = self.server()
        for abi in ("arm", "arm64", "x86", "x86_64"):
            self.binary("android", abi, "server")
            self.binary("android", abi, "gadget")
        self.binary("linux", "x86_64", "server")
        text = module.list_abis()
        self.assertIn("android/arm64  frida-server", text)
        self.assertIn("android/x86  frida-gadget", text)
        self.assertIn("linux/x86_64  frida-server", text)
        self.assertIn("9 binaries", text)
        self.assertIn("frida 17.25.2", text)

    def test_export_server_unpacks_the_release_file_into_out(self):
        module = self.server()
        self.binary("android", "arm64", "server", b"\x7fELF-the-real-one")
        text = module.export_server("arm64", "frida-server-arm64")
        self.assertIn("/out/frida-server-arm64", text)
        made = os.path.join(self.out, "frida-server-arm64")
        with open(made, "rb") as handle:
            self.assertEqual(handle.read(), b"\x7fELF-the-real-one")
        self.assertEqual(oct(os.stat(made).st_mode)[-3:], "755")
        self.assertIn("already there", self.refused(module.export_server, "arm64", "frida-server-arm64"))
        self.assertIn("adb push", text)

    def test_export_server_refuses_what_the_image_does_not_have_and_bad_names(self):
        module = self.server()
        self.binary("android", "arm64", "server")
        self.assertIn("the image has no", self.refused(module.export_server, "x86", "x"))
        for abi in ("../etc", "arm64;", "mips", ""):
            with self.subTest(abi=abi):
                self.assertIn("abi", self.refused(module.export_server, abi, "x"))
        for name in ("../escape", "a/b", "/abs", "."):
            with self.subTest(name=name):
                self.assertIn("out_name", self.refused(module.export_server, "arm64", name))
        self.assertIn("platform", self.refused(module.export_server, "arm64", "x", platform="windows"))
        self.assertIn("kind", self.refused(module.export_server, "arm64", "x", kind="agent"))

    def test_without_a_writable_out_export_server_says_so(self):
        module = self.server()
        self.binary("android", "arm64", "server")
        shutil.rmtree(self.out)
        self.assertIn("/out", self.refused(module.export_server, "arm64", "x"))

    def test_push_server_pushes_the_abi_the_device_reports(self):
        module = self.server(adb_server="192.168.1.10:5037", write=True)
        self.binary("android", "arm64", "server", b"\x7fELF-arm64")
        usb = FakeDevice("emulator-5554", "Android Emulator", "usb")
        with mock.patch.object(module.DEVICES, "usb_devices", lambda: [usb]):
            calls = []

            def fake_adb(arguments, serial="", seconds=module.ADB_SECONDS):
                calls.append((arguments, serial))
                return "arm64-v8a\n" if arguments[:2] == ["shell", "getprop"] else ""

            with mock.patch.object(module, "adb", fake_adb):
                text = module.push_server()
        self.assertIn("pushed to /data/local/tmp/frida-server-17.25.2-arm64", text)
        self.assertIn("arm64-v8a -> arm64", text)
        self.assertIn("started as root", text)
        self.assertEqual([arguments[0] for arguments, _ in calls], ["shell", "push", "shell", "shell"])
        self.assertTrue(all(serial == "emulator-5554" for _, serial in calls))
        pushed = [arguments for arguments, _ in calls if arguments[0] == "push"][0]
        self.assertTrue(pushed[1].startswith(self.scratch), pushed[1])
        self.assertEqual(pushed[2], "/data/local/tmp/frida-server-17.25.2-arm64")
        self.assertEqual(os.listdir(self.scratch), [], "the unpacked binary went with the scratch folder")

    def test_push_server_refuses_a_folder_outside_the_devices_data_folders(self):
        module = self.server(adb_server="192.168.1.10:5037", write=True)
        usb = FakeDevice("emulator-5554", "Android Emulator", "usb")
        with mock.patch.object(module.DEVICES, "usb_devices", lambda: [usb]):
            for folder in ("/system/bin", "../data", "/data/../system", "/etc"):
                with self.subTest(folder=folder):
                    self.assertIn("target_folder", self.refused(module.push_server, target_folder=folder))

    def test_an_unknown_abi_of_the_device_is_said_plainly(self):
        module = self.server(adb_server="192.168.1.10:5037", write=True)
        with self.assertRaises(module.Refused) as caught:
            module.abi_for("mips64")
        self.assertIn("no frida-server for", str(caught.exception))
        self.assertEqual(module.abi_for("armeabi-v7a"), "arm")
        self.assertEqual(module.abi_for("arm64-v8a"), "arm64")

    def test_a_release_file_that_unpacks_to_too_much_is_stopped(self):
        module = self.server()
        self.binary("android", "arm64", "server", b"\0" * 4096)
        with mock.patch.object(module, "MAX_BINARY_BYTES", 1024):
            self.assertIn("unpacks to more than", self.refused(module.export_server, "arm64", "x"))
        self.assertFalse(os.path.exists(os.path.join(self.out, "x")) and os.path.getsize(
            os.path.join(self.out, "x")) > 1024)


class Answers(Base):
    def test_parts_of_400_lines_and_24000_characters(self):
        module = self.server()
        text = "\n".join(f"line {number}" for number in range(1, 1001))
        first = module.page("messages", text, 1, "run_script")
        self.assertIn("lines 1-400 of 1000", first)
        self.assertIn("start_line=401", first)
        with self.assertRaises(module.Refused):
            module.page("messages", text, 1001, "run_script")

    def test_lists_have_an_offset(self):
        module = self.server(device=self.DEVICE)
        text = module.listing("processes", [f"process {n}" for n in range(500)], 0, "processes")
        self.assertIn("500 processes, 1-300 shown", text)
        self.assertIn("offset=300", text)
        self.assertIn("processes on", module.list_processes())
        self.assertIn("com.example.app", module.list_processes(name_filter="example"))
        self.assertNotIn("zygote64", module.list_processes(name_filter="example"))
        self.assertIn("com.example.app  Example  pid 4242", module.list_applications(only_running=True))
        self.assertNotIn("com.other.app", module.list_applications(only_running=True))

    def test_tools_only_and_the_annotations_match_tools_json(self):
        import asyncio
        module = self.server()
        from mcp import types as mcp_types
        for request in (mcp_types.ListResourcesRequest, mcp_types.ListPromptsRequest, mcp_types.GetPromptRequest):
            self.assertNotIn(request, module.mcp._mcp_server.request_handlers)
        declared = json.loads((ROOT / "servers" / "frida" / "tools.json").read_text())
        tools = asyncio.run(module.mcp.list_tools())
        self.assertEqual(sorted(tool.name for tool in tools), declared["tools"])
        self.assertEqual(sorted(tool.name for tool in tools if tool.annotations and tool.annotations.readOnlyHint),
                         declared["read_only_tools"])
        for tool in tools:
            self.assertTrue(tool.description and len(tool.description) > 40, tool.name)
        changing = sorted(tool.name for tool in tools if tool.annotations and tool.annotations.destructiveHint)
        self.assertEqual(changing, ["kill", "push_server", "resume", "spawn"])


@unittest.skipUnless(real_frida is not None, "frida's own bindings are not installed")
class WithTheRealBindings(Base):
    """The bindings as the image has them: the version the binaries need, and the local device refused for real."""

    def test_the_bindings_have_the_version_the_binaries_in_the_image_have(self):
        module = load(frida_module=real_frida)
        self.assertEqual(real_frida.__version__, module.FRIDA_VERSION,
                         "frida's client and its frida-server must be the same version")
        dockerfile = (ROOT / "servers" / "frida" / "Dockerfile").read_text()
        self.assertIn(f"frida=={module.FRIDA_VERSION}", (ROOT / "servers" / "frida" / "requirements.in").read_text())
        self.assertEqual(dockerfile.count(f"/releases/download/{module.FRIDA_VERSION}/"), 12,
                         "every binary comes from the release of that very version")

    def test_the_local_device_of_this_container_is_never_reachable_through_a_tool(self):
        module = self.server(frida_module=real_frida)
        listed = self.refused(module.list_devices)   # nothing configured: no device at all
        self.assertIn("no device is configured", listed)
        for name in ("local", "socket", "barebone"):
            with self.subTest(device=name):
                # refused by name, before anything is reached - also when no device is configured
                self.assertIn("frida's own device of this container", self.refused(module.list_processes, name))
        # with a device configured, the names of frida's own devices are refused by name
        module = self.server(device=self.DEVICE, frida_module=real_frida)
        with mock.patch.object(module.DEVICES, "remote_device",
                               lambda: FakeDevice(self.DEVICE, "remote", "remote")):
            for name in ("local", "socket", "barebone"):
                self.assertIn("frida's own device of this container",
                              self.refused(module.list_processes, name))

    def test_the_real_errors_frida_raises_are_the_ones_the_server_catches(self):
        """frida 17 has no common base class (every error comes straight from Exception, and there is no
        frida.FridaError): the server gathers the ones the bindings have, and every error it names must be among
        them."""
        module = load(frida_module=real_frida)
        self.assertFalse(hasattr(real_frida, "FridaError"), "if frida adds a base class, catch that instead")
        found = {error.__name__ for error in module.FRIDA_ERRORS}
        for name in ("ServerNotRunningError", "TransportError", "InvalidArgumentError", "PermissionDeniedError",
                     "ProcessNotFoundError", "NotSupportedError", "TimedOutError", "ProtocolError"):
            with self.subTest(error=name):
                self.assertIn(name, found)
                self.assertIs(module.frida_error(name), getattr(real_frida, name))
        self.assertTrue(issubclass(module.frida_error("SomethingFridaDoesNotHave"), Exception))


if __name__ == "__main__":
    unittest.main()
