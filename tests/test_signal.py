"""The signal server (servers/signal), without network and without signal-cli: tools/list read-only
and with the write opt-in, refused arguments, the missing account, and - against a local stand-in
for signal-cli's JSON-RPC daemon - receiving into the local history, unread, conversations,
search, contacts, groups (without invite links), the allowed recipients of the write tools, the
size bound, no proxy for the daemon's requests, no message text in the log, and signal-cli's
command line. Needs the server's requirements and signal-mcp's modules (the image has both)."""
import asyncio
import http.server
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock
import warnings

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "servers" / "signal"
READ_TOOLS = json.loads((SERVER / "tools.json").read_text())["tools"]
WRITE_TOOLS = ["react_to_message", "send_group_message", "send_message"]
ACCOUNT = "+4915100000001"
ADA = "+4915100000002"
BOB_UUID = "0b0b0b0b-1111-4222-8333-444455556666"
GROUP = "A" * 42 + "Q="
OTHER_GROUP = "B" * 42 + "Q="
CLEAN = {"SIGNAL_WRITE": "", "SIGNAL_ALLOWED_RECIPIENTS": "", "SIGNAL_DATA_DIR": ""}

try:
    import mcp  # noqa: F401 - the server's own dependency
    import signal_mcp  # noqa: F401 - signal-mcp's modules, as the image installs them
except ImportError:
    mcp = None

# One data folder for the whole run: signal-mcp's modules take their paths from HOME when they are
# first imported, and the server points HOME at its data folder.
DATA = tempfile.TemporaryDirectory(prefix="signal-data-")
(Path(DATA.name) / ".local/share/signal-cli/data").mkdir(parents=True)
(Path(DATA.name) / ".local/share/signal-cli/data/accounts.json").write_text(
    json.dumps({"accounts": [{"path": "123", "environment": "LIVE", "number": ACCOUNT}], "version": 2}))


def rpc(calls, env=None, timeout=60):
    """initialize, tools/list and tools/call of each (tool, arguments) over stdio; (answers by id, stderr)."""
    messages = [{"jsonrpc": "2.0", "id": 0, "method": "initialize",
                 "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                            "clientInfo": {"name": "test", "version": "1"}}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}]
    for index, (tool, arguments) in enumerate(calls, start=2):
        messages.append({"jsonrpc": "2.0", "id": index, "method": "tools/call",
                         "params": {"name": tool, "arguments": arguments}})
    process = subprocess.Popen([sys.executable, "-I", "-u", str(SERVER / "src/server.py")], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                               env={**os.environ, **CLEAN, "SIGNAL_DATA_DIR": "/nonexistent/signal-data",
                                    **(env or {})})
    answers = {}
    try:
        for message in messages:
            process.stdin.write(json.dumps(message) + "\n")
            process.stdin.flush()
            while "id" in message and message["id"] not in answers:
                line = process.stdout.readline()
                if not line:
                    raise AssertionError(f"the server ended without answering {message['method']}")
                answer = json.loads(line)
                if "id" in answer:
                    answers[answer["id"]] = answer
    finally:
        process.stdin.close()
        _, stderr = process.communicate(timeout=timeout)
    return answers, stderr


def result(answer):
    content = answer["result"]["structuredContent"] if "structuredContent" in answer["result"] else \
        json.loads(answer["result"]["content"][0]["text"])
    return content.get("result", content)


def load(env=None):
    """servers/signal/src/server.py as a fresh module, imported under *env* with the test's data folder."""
    spec = importlib.util.spec_from_file_location("signal_server", SERVER / "src/server.py")
    module = importlib.util.module_from_spec(spec)
    hook = sys.excepthook
    with mock.patch.dict(os.environ, {**CLEAN, "SIGNAL_DATA_DIR": DATA.name, **(env or {})}):
        spec.loader.exec_module(module)
    sys.excepthook = hook
    return module


# --- a stand-in for signal-cli's JSON-RPC daemon ------------------------------------------------

def envelope(source, timestamp, **data):
    return {"envelope": {"source": source, "sourceNumber": source if source.startswith("+") else None,
                         "sourceUuid": BOB_UUID, "timestamp": timestamp, **data}, "account": ACCOUNT}


INBOX = [
    envelope(ADA, 1790000000000, dataMessage={
        "timestamp": 1790000000000, "message": "Hello from Ada", "attachments": [
            {"contentType": "image/jpeg", "filename": "cat.jpg", "id": "../../.local/share/signal-cli/x", "size": 7}]}),
    envelope(BOB_UUID, 1790000001000, dataMessage={"timestamp": 1790000001000, "message": "In the group",
                                                   "groupInfo": {"groupId": GROUP, "type": "DELIVER"}}),
    envelope(ACCOUNT, 1790000002000, syncMessage={"sentMessage": {
        "timestamp": 1790000002000, "message": "Sent from my phone", "destination": ADA}}),
    envelope(ADA, 1790000003000, receiptMessage={"type": "DELIVERY", "timestamps": [1]}),
    envelope(ADA, 1790000004000, dataMessage={"timestamp": 1790000004000, "editMessage": {
        "targetSentTimestamp": 1790000000000, "dataMessage": {"message": "Hello from Ada (edited)"}}}),
]


class FakeDaemon(http.server.BaseHTTPRequestHandler):
    requests: list = []
    inbox: list = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeDaemon.requests.append((self.path, request["method"], request.get("params")))
        method, params = request["method"], request.get("params") or {}
        if method == "version":
            result = {"version": "0.14.9"}
        elif method == "listContacts":
            result = [{"number": ADA, "uuid": "ada-uuid", "name": "Ada Lovelace", "profile": {"givenName": "Ada"}},
                      {"number": None, "uuid": BOB_UUID, "name": "", "profile": {"givenName": "Bob"}}]
        elif method == "listGroups":
            result = [{"id": GROUP, "name": "Lab", "groupInviteLink": "https://signal.group/#secret",
                       "members": [{"uuid": f"u{i}", "number": None} for i in range(150)], "admins": []}]
        elif method == "receive":
            result, FakeDaemon.inbox = FakeDaemon.inbox, []
        elif method in ("send", "sendReaction"):
            result = {"timestamp": 1790000009000, "results": [{"type": "SUCCESS"}]}
        else:
            self.send_error(404)
            return
        body = json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@unittest.skipIf(mcp is None, "the server's requirements and signal-mcp's modules are not installed")
class ToolList(unittest.TestCase):
    def test_read_only_by_default_and_no_account(self):
        answers, stderr = rpc([("get_status", {}), ("get_unread", {"limit": 201}), ("receive_messages", {}),
                               ("send_message", {"recipient": ADA, "message": "x"})])
        self.assertIn("serverInfo", answers[0]["result"])
        self.assertEqual(sorted(t["name"] for t in answers[1]["result"]["tools"]), READ_TOOLS)
        status = result(answers[2])
        self.assertFalse(status["linked"])
        self.assertIn("no Signal account: no folder mounted at /nonexistent/signal-data", status["problem"])
        self.assertIn("--link", status["problem"])
        self.assertIn("limit: an integer from 1 to 200", result(answers[3])["error"])  # arguments first
        self.assertIn("no Signal account", result(answers[4])["error"])
        self.assertTrue(answers[5]["result"].get("isError"))  # not offered at all
        self.assertIn("no Signal account; the tools refuse until then", stderr)

    def test_write_tools_only_with_the_opt_in(self):
        answers, _ = rpc([], env={"SIGNAL_WRITE": "1"})
        self.assertEqual(sorted(t["name"] for t in answers[1]["result"]["tools"]), sorted(READ_TOOLS + WRITE_TOOLS))
        for value in ("true", "yes", "0", " "):
            answers, _ = rpc([], env={"SIGNAL_WRITE": value})
            self.assertEqual(sorted(t["name"] for t in answers[1]["result"]["tools"]), READ_TOOLS, value)

    def test_refused_arguments(self):
        module = load({"SIGNAL_WRITE": "1"})
        cases = [
            ("get_conversation", ("+49x",), "conversation: a phone number"),
            ("get_conversation", (ADA, 0), "limit: an integer from 1 to 200"),
            ("get_conversation", (ADA, 10, -1), "offset"),
            ("get_conversation", (ADA, 10, 0, "last week"), "since: a date"),
            ("search_messages", ("a\nb",), "query: 1-256 characters"),
            ("search_messages", ("x", "bob"), "sender: a phone number"),
            ("receive_messages", (61,), "timeout: an integer from 1 to 60"),
            ("receive_messages", (5, 0), "max_messages"),
            ("get_unread", (10, "yes"), "receive: true or false"),
            ("list_contacts", ("x" * 101,), "search: 1-100"),
            ("send_message", ("hi", ADA, "alice.42"), "exactly one of recipient"),
            ("send_message", ("hi", "", "alice"), "username: a Signal username"),
            ("send_message", ("x" * 4001, ADA), "message: 1-4000"),
            ("send_message", ("a\x00b", ADA), "message: 1-4000"),
            ("send_message", ("hi", ADA, "", True, "+49x", 5), "quote_author"),
            ("send_message", ("hi", ADA, "", True, ADA, -5), "quote_timestamp"),
            ("send_group_message", ("not-a-group", "hi"), "group_id: a group id"),
            ("react_to_message", (ADA, 1, "ok", ADA), "emoji: one emoji"),
            ("react_to_message", (ADA, 1, "\U0001F44D", ADA, GROUP), "exactly one of recipient"),
        ]
        for tool, args, expected in cases:
            with self.subTest(tool=tool, args=args):
                answer = asyncio.run(getattr(module, tool)(*args))
                self.assertIn(expected, answer["error"])


@unittest.skipIf(mcp is None, "the server's requirements and signal-mcp's modules are not installed")
class WithFakeDaemon(unittest.TestCase):
    env = {}

    @classmethod
    def setUpClass(cls):
        cls.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeDaemon)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def setUp(self):
        # signal-mcp's history keeps one SQLite connection per thread; the worker threads of each test's
        # event loop end with theirs open.
        warnings.filterwarnings("ignore", category=ResourceWarning)
        self.module = load(self.env)
        self.module.store.clear_store()
        FakeDaemon.requests, FakeDaemon.inbox = [], [json.loads(json.dumps(e)) for e in INBOX]
        self.log = io.StringIO()
        self.module._handler.setStream(self.log)
        environment = mock.patch.dict(os.environ, {**CLEAN, "SIGNAL_DATA_DIR": DATA.name, **self.env,
                                                   "HTTP_PROXY": "http://127.0.0.1:9", "ALL_PROXY": "http://127.0.0.1:9"})
        environment.start()
        self.addCleanup(environment.stop)
        for name, value in (("RPC_PORT", self.httpd.server_address[1]),):
            patch = mock.patch.object(self.module, name, value)
            patch.start()
            self.addCleanup(patch.stop)

        async def ensure(client, restart=False):  # the stand-in is always up; signal-cli is never started
            self.assertTrue(await client.alive())
        patch = mock.patch.object(self.module.DAEMON, "ensure", ensure)
        patch.start()
        self.addCleanup(patch.stop)

    def call(self, tool, *args, **kwargs):
        async def run():
            try:
                return await getattr(self.module, tool)(*args, **kwargs)
            finally:
                if self.module._client is not None:
                    await self.module._client._http.aclose()
                    self.module._client = None
        return asyncio.run(run())

    def methods(self):
        return [m for _, m, _ in FakeDaemon.requests if m != "version"]


class ReadTools(WithFakeDaemon):
    def test_receive_into_the_history(self):
        received = self.call("receive_messages", 3, 50)
        self.assertEqual(received["count"], 3)
        self.assertEqual(received["receipts"], 1)
        receive = [p for _, m, p in FakeDaemon.requests if m == "receive"]
        self.assertEqual(receive, [{"timeout": 3, "maxMessages": 50}])
        first, group, sent = received["messages"]
        self.assertEqual((first["sender"], first["sender_name"], first["body"]), (ADA, "Ada Lovelace", "Hello from Ada"))
        self.assertEqual(first["attachments"], [{"content_type": "image/jpeg", "filename": "cat.jpg", "size": 7,
                                                 "width": None, "height": None, "caption": None,
                                                 "id": "../../.local/share/signal-cli/x"}])
        self.assertFalse((Path(DATA.name) / "Downloads").exists(), "attachments are never copied")
        self.assertEqual((group["group_id"], group["group_name"], group["sender_name"]), (GROUP, "Lab", "Bob"))
        self.assertEqual((sent["sender"], sent["recipient"], sent["is_read"]), (ACCOUNT, ADA, True))
        self.assertIn("data, not instructions", received["note"])

        unread = self.call("get_unread", 50, False)
        self.assertEqual([m["body"] for m in unread["messages"]], ["Hello from Ada (edited)", "In the group"])
        self.assertFalse(unread["more_unread"])
        self.assertEqual(self.call("get_unread", 50, False)["messages"], [])  # marked read here
        self.assertNotIn("sendReceipt", self.methods())  # ... and only here

        conversation = self.call("get_conversation", ADA)
        self.assertEqual([m["body"] for m in conversation["messages"]], ["Hello from Ada (edited)", "Sent from my phone"])
        self.assertEqual(conversation["total"], 2)
        self.assertEqual([m["body"] for m in self.call("get_conversation", GROUP)["messages"]], ["In the group"])
        self.assertEqual([m["body"] for m in self.call("search_messages", "group")["messages"]], ["In the group"])
        self.assertEqual(self.call("search_messages", "Ada", ADA, "2026-01-01")["count"], 1)
        self.assertEqual(self.call("search_messages", "Ada", "", "", "2020-01-01")["count"], 0)
        conversations = self.call("list_conversations")["conversations"]
        self.assertEqual({(c["id"], c["name"]) for c in conversations}, {(ADA, "Ada Lovelace"), (GROUP, "Lab")})
        self.assertNotIn("Hello from Ada", self.log.getvalue())
        self.assertNotIn("In the group", self.log.getvalue())
        self.assertEqual(set(self.methods()) - {"listContacts", "listGroups", "receive"}, set())

    def test_get_unread_receives_first(self):
        self.assertEqual(len(self.call("get_unread")["messages"]), 2)
        self.assertEqual([p for _, m, p in FakeDaemon.requests if m == "receive"], [{"timeout": 2, "maxMessages": 500}])

    def test_contacts_and_groups_without_invite_links(self):
        contacts = self.call("list_contacts", "ada")
        self.assertEqual([c["number"] for c in contacts["contacts"]], [ADA])
        groups = self.call("list_groups")["groups"]
        self.assertEqual(groups[0]["name"], "Lab")
        self.assertNotIn("invite_link", groups[0])
        self.assertNotIn("signal.group", json.dumps(groups))
        self.assertEqual((len(groups[0]["members"]), groups[0]["members_left_out"]), (100, 50))

    def test_status(self):
        status = self.call("get_status")
        self.assertEqual((status["linked"], status["account"]), (True, ACCOUNT))
        self.assertTrue(status["write_tools"].startswith("off"))
        self.assertNotIn("allowed_recipients", status)
        self.assertEqual(self.methods(), [])  # nothing asked of signal-cli

    def test_the_answer_is_bounded(self):
        FakeDaemon.inbox = [envelope(ADA, 1790000100000 + i, dataMessage={
            "timestamp": 1790000100000 + i, "message": f"{i:04d}" + "x" * 9000}) for i in range(60)]
        received = self.call("receive_messages", 1, 500)
        self.assertTrue(received["truncated"])
        self.assertLessEqual(len(json.dumps(received, ensure_ascii=False)), self.module.MAX_ANSWER)
        self.assertEqual(received["messages"][-1]["body"][:4], "0059")  # the newest are kept
        self.assertTrue(received["messages"][-1]["body"].endswith(" [...]"))
        self.assertEqual(len(received["messages"][-1]["body"]), self.module.MAX_BODY + 6)

    def test_write_tools_refuse_when_off(self):
        self.assertIn("write tools are off", self.call("send_message", "hi", ADA)["error"])
        self.assertIn("write tools are off", self.call("send_group_message", GROUP, "hi")["error"])
        self.assertIn("write tools are off", self.call("react_to_message", ADA, 1, "\U0001F44D", ADA)["error"])
        self.assertEqual(FakeDaemon.requests, [])


class WriteTools(WithFakeDaemon):
    env = {"SIGNAL_WRITE": "1", "SIGNAL_ALLOWED_RECIPIENTS": f"{ADA}, {GROUP}, Alice.42"}

    def sends(self):
        return [p for _, m, p in FakeDaemon.requests if m in ("send", "sendReaction")]

    def test_allowed_recipients(self):
        self.assertEqual(self.call("send_message", "**hi**", ADA, "", True),
                         {"sent": True, "timestamp": 1790000009000, "recipient": ADA})
        self.assertIn("sent", self.call("send_message", "hi", "", "alice.42"))
        self.assertIn("sent", self.call("send_group_message", GROUP, "hi all"))
        self.assertIn("reaction", self.call("react_to_message", BOB_UUID, 1790000001000, "\U0001F44D", "", GROUP))
        self.assertEqual(self.call("send_message", "hi", "+4915100000009"),
                         {"error": "+4915100000009 is not in SIGNAL_ALLOWED_RECIPIENTS"})
        self.assertIn("not in SIGNAL_ALLOWED_RECIPIENTS", self.call("send_group_message", OTHER_GROUP, "hi")["error"])
        self.assertEqual(self.sends(), [
            {"recipient": [ADA], "message": "hi", "textStyle": ["0:2:BOLD"]},
            {"username": ["alice.42"], "message": "hi"},
            {"groupId": GROUP, "message": "hi all"},
            {"emoji": "\U0001F44D", "targetAuthor": BOB_UUID, "targetTimestamp": 1790000001000, "remove": False,
             "groupId": GROUP}])
        status = self.call("get_status")
        self.assertEqual((status["write_tools"], status["allowed_recipients"]), ("on", sorted([ADA, GROUP, "alice.42"])))

    def test_a_reply_quotes_the_stored_text(self):
        self.call("receive_messages", 1, 10)
        self.call("send_message", "yes", ADA, "", False, ADA, 1790000000000)
        self.assertEqual(self.sends()[-1], {"recipient": [ADA], "message": "yes", "quoteAuthor": ADA,
                                            "quoteTimestamp": 1790000000000, "quoteMessage": "Hello from Ada (edited)"})

    def test_a_broken_list_refuses_every_write(self):
        with mock.patch.dict(os.environ, {"SIGNAL_ALLOWED_RECIPIENTS": f"{ADA},somebody"}):
            for tool, args in (("send_message", ("hi", ADA)), ("send_group_message", (GROUP, "hi")),
                               ("react_to_message", (ADA, 1, "\U0001F44D", ADA))):
                self.assertIn("SIGNAL_ALLOWED_RECIPIENTS: comma-separated", self.call(tool, *args)["error"])
        self.assertEqual(FakeDaemon.requests, [])

    def test_every_recipient_without_a_list(self):
        with mock.patch.dict(os.environ, {"SIGNAL_ALLOWED_RECIPIENTS": ""}):
            self.assertIn("sent", self.call("send_message", "hi", "+4915100000009"))


@unittest.skipIf(mcp is None, "the server's requirements and signal-mcp's modules are not installed")
class SignalCli(unittest.TestCase):
    def test_the_daemon_command_line(self):
        module = load()
        with tempfile.TemporaryDirectory() as home:
            Path(home, "classpath").write_text("/opt/signal-cli/lib/a.jar\n/opt/signal-cli/lib/b.jar\n")
            with mock.patch.object(module, "SIGNAL_CLI_HOME", Path(home)):
                argv = module.DAEMON.argv(ACCOUNT)
        self.assertEqual(argv[0], "/opt/java/bin/java")
        self.assertIn("-XX:-UsePerfData", argv)
        self.assertEqual(argv[argv.index("-cp") + 1], "/opt/signal-cli/lib/a.jar:/opt/signal-cli/lib/b.jar")
        main = argv.index("org.asamk.signal.Main")
        self.assertEqual(argv[main + 1:], [
            "--config", f"{DATA.name}/.local/share/signal-cli", "--scrub-log", "-a", ACCOUNT, "daemon",
            "--http", "127.0.0.1:7583", "--receive-mode", "manual", "--no-receive-stdout", "--ignore-attachments",
            "--ignore-stories", "--ignore-avatars", "--ignore-stickers"])

    def test_the_daemon_is_started_waited_for_and_stopped(self):
        """With a stand-in for java: started once, used while it answers, its log kept for the error only."""
        module = load()
        with tempfile.TemporaryDirectory() as folder:
            port = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeDaemon)
            free = port.server_address[1]
            port.server_close()
            fake = Path(folder, "fake_signal_cli.py")
            fake.write_text(
                "import http.server, json, sys\n"
                "print('INFO signal-cli starting for +49<scrubbed>', file=sys.stderr, flush=True)\n"
                "if sys.argv[1] == 'fail':\n"
                "    print('ERROR Config file is in use by another instance', file=sys.stderr); sys.exit(3)\n"
                "class H(http.server.BaseHTTPRequestHandler):\n"
                "    def log_message(self, *a): pass\n"
                "    def do_POST(self):\n"
                "        r = json.loads(self.rfile.read(int(self.headers['Content-Length'])))\n"
                "        b = json.dumps({'jsonrpc': '2.0', 'id': r['id'], 'result': {}}).encode()\n"
                "        self.send_response(200); self.send_header('Content-Length', str(len(b))); self.end_headers()\n"
                "        self.wfile.write(b)\n"
                "http.server.HTTPServer(('127.0.0.1', int(sys.argv[1])), H).serve_forever()\n")
            mode = [str(free)]
            with mock.patch.object(module, "RPC_PORT", free), \
                    mock.patch.object(module.Daemon, "argv", lambda self, account: [sys.executable, "-I", str(fake), *mode]):
                async def run():
                    client = module.Client(ACCOUNT)
                    try:
                        await client.ensure_daemon()
                        first = module.DAEMON.process
                        self.assertTrue(module.DAEMON.running())
                        await client.ensure_daemon()  # up: not started again
                        self.assertIs(module.DAEMON.process, first)
                        module.DAEMON.stop()
                        self.assertIsNone(module.DAEMON.process)
                        self.assertIsNotNone(first.poll())
                        mode[:] = ["fail"]
                        with self.assertRaises(module.SignalError) as raised:
                            await client.ensure_daemon()
                        self.assertIn("signal-cli ended", str(raised.exception))
                        self.assertIn("Config file is in use", str(raised.exception))
                    finally:
                        module.DAEMON.stop()
                        await client._http.aclose()
                asyncio.run(run())

    def test_link_checks_its_name_and_the_folder(self):
        module = load({"SIGNAL_DATA_DIR": "/nonexistent/signal-data"})
        with mock.patch.object(module.os, "execv") as execv, mock.patch("sys.stderr", io.StringIO()) as err:
            self.assertEqual(module.main(["--link", "a;b"]), 2)
            self.assertEqual(module.main(["--link", "laptop"]), 2)
            self.assertIn("run it with -v DIR:/nonexistent/signal-data:rw", err.getvalue())
        execv.assert_not_called()
        module = load()
        with tempfile.TemporaryDirectory() as home:
            Path(home, "classpath").write_text("/x.jar\n")
            with mock.patch.object(module, "SIGNAL_CLI_HOME", Path(home)), \
                    mock.patch.object(module.os, "execv") as execv, mock.patch("sys.stderr", io.StringIO()):
                module.main(["--link", "my", "laptop"])
        argv = execv.call_args[0][1]
        self.assertEqual(argv[-3:], ["link", "-n", "my laptop"])


if __name__ == "__main__":
    unittest.main()
