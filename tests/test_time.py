"""servers/time: the official mcp-server-time 2026.10.28 behind src/server.py, natively - handshake, tools only, the
two tools, the local zone, hostile arguments refused with short answers. Runs from the server's own lock (mcp 2.x):
inside its image, or after pip install --require-hashes -r servers/time/requirements.txt."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
FOLDER = ROOT / "servers" / "time"


def installed():
    try:
        return importlib.util.find_spec("mcp_server_time") is not None
    except (ImportError, ValueError):
        return False


if installed():
    from test_own_servers import result, rpc, session  # noqa: F401


def text(answer):
    return answer["result"]["content"][0]["text"]


@unittest.skipUnless(installed(), "time runs from its own lock (mcp 2.x): inside its image, or after "
                                  "pip install --require-hashes -r servers/time/requirements.txt")
class Time(unittest.TestCase):
    def test_tools_only_and_the_local_zone(self):
        answers = rpc("time", session() + [{"jsonrpc": "2.0", "id": 9, "method": "resources/list"},
                                           {"jsonrpc": "2.0", "id": 10, "method": "prompts/list"}],
                      env={"LOCAL_TIMEZONE": "Europe/Berlin"})
        self.assertEqual(sorted(answers[0]["result"]["capabilities"]), ["tools"])
        self.assertEqual(answers[0]["result"]["serverInfo"]["version"], "2026.10.28")
        tools = answers[1]["result"]["tools"]
        self.assertEqual(sorted(t["name"] for t in tools), json.loads((FOLDER / "tools.json").read_text())["tools"])
        self.assertEqual(answers[9]["error"]["code"], -32601)
        self.assertEqual(answers[10]["error"]["code"], -32601)
        self.assertIn("Use 'Europe/Berlin' as local timezone", json.dumps(tools))
        # without LOCAL_TIMEZONE: what tzlocal finds (TZ, /etc/localtime), else UTC - never an error
        answers = rpc("time", session(), env={"LOCAL_TIMEZONE": "", "TZ": "Asia/Tokyo"})
        self.assertIn("Use 'Asia/Tokyo' as local timezone", json.dumps(answers[1]["result"]["tools"]))

    def test_a_bad_local_zone_ends_the_server_with_one_line(self):
        for bad in ("Mars/Base", "../../etc/passwd", "x" * 500):
            process = subprocess.run([sys.executable, "-I", "-u", str(FOLDER / "src/server.py")], input="",
                                     capture_output=True, text=True, timeout=60,
                                     env={**os.environ, "LOCAL_TIMEZONE": bad})
            self.assertNotEqual(process.returncode, 0)
            self.assertIn("invalid LOCAL_TIMEZONE", process.stderr)
            self.assertLess(len(process.stderr), 200)
            self.assertEqual(process.stdout, "")

    def test_the_two_tools(self):
        answers = rpc("time", session(
            ("get_current_time", {"timezone": "Asia/Kathmandu"}),
            ("convert_time", {"source_timezone": "UTC", "time": "12:00", "target_timezone": "Asia/Kolkata"}),
            ("convert_time", {"source_timezone": "Europe/Berlin", "time": "08:15", "target_timezone": "UTC"})))
        now = answers[2]["result"]["structuredContent"]
        self.assertEqual(now["timezone"], "Asia/Kathmandu")
        self.assertTrue(now["datetime"].endswith("+05:45"))
        converted = answers[3]["result"]["structuredContent"]
        self.assertEqual(converted["time_difference"], "+5.5h")
        self.assertTrue(converted["target"]["datetime"].endswith("T17:30:00+05:30"))
        self.assertIn(answers[4]["result"]["structuredContent"]["time_difference"], ("-1.0h", "-2.0h"))

    def test_hostile_arguments_are_refused_briefly(self):
        calls = [("get_current_time", {"timezone": "../../../etc/passwd"}),
                 ("get_current_time", {"timezone": "/usr/share/zoneinfo/UTC"}),
                 ("get_current_time", {"timezone": "America"}),           # a folder of the database
                 ("get_current_time", {"timezone": "europe/berlin"}),     # not an exact key
                 ("get_current_time", {"timezone": ""}),
                 ("get_current_time", {"timezone": "A" * 200_000}),
                 ("get_current_time", {"timezone": "UTC\x00"}),
                 ("get_current_time", {"timezone": list(range(50_000))}),
                 ("convert_time", {"source_timezone": "UTC", "time": "1" * 100_000, "target_timezone": "UTC"}),
                 ("convert_time", {"source_timezone": "UTC", "time": "25:61", "target_timezone": "UTC"}),
                 ("convert_time", {"source_timezone": "Europe/Berlin", "time": "12:00", "target_timezone": "x" * 65})]
        answers = rpc("time", session(*calls))
        for index, call in enumerate(calls, start=2):
            answer = answers[index]["result"]
            self.assertTrue(answer["isError"], call)
            self.assertLess(len(text(answers[index])), 600, call)
            self.assertNotIn("/usr/", text(answers[index]), call)
        self.assertIn("must be an IANA timezone name", text(answers[2]))
        self.assertIn("No time zone found with key America", text(answers[4]))
        self.assertIn("europe/berlin", text(answers[5]))
        self.assertIn("Invalid time format", text(answers[10]))
        self.assertIn("Invalid time format", text(answers[11]))
        unknown = rpc("time", session(("read_file", {"path": "/etc/passwd"})))[2]
        self.assertEqual(unknown["error"]["code"], -32602)

    def test_the_wrapper_checks(self):
        module = _load()
        for good in ("UTC", "Europe/Berlin", "America/Argentina/Buenos_Aires", "Etc/GMT+5", "America/Port-au-Prince"):
            self.assertEqual(module.checked_zone("timezone", good), good)
        for bad in ("", ".", "..", "a/../b", "/UTC", "UTC/", "a//b", "a b", "a/b/c/d/e", "x" * 65, None, 5):
            with self.assertRaises(Exception, msg=repr(bad)):
                module.checked_zone("timezone", bad)


def _load():
    spec = importlib.util.spec_from_file_location("server_time", FOLDER / "src/server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    unittest.main()
