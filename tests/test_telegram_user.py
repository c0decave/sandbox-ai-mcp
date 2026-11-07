"""The telegram-user server (servers/telegram-user), without network: tools/list read-only and with
the write opt-in, refused arguments, limits, flood waits, the allowed chats of the write tools, the
missing and malformed secrets, and the secrets in no answer and no log line - against a fake
Telethon client injected in place of the real one. login.py with a fake client too."""
import asyncio
import base64
import contextlib
import datetime
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "servers" / "telegram-user"

try:
    import mcp  # noqa: F401 - the server's own dependencies
    import telethon  # noqa: F401
    from telethon import errors
    from telethon.tl import functions, types
except ImportError:
    mcp = None

API_ID = "98765431"
API_HASH = "0f1e2d3c4b5a69788796a5b4c3d2e1f0"
SESSION = "1" + base64.urlsafe_b64encode(bytes((i * 7 + 3) % 256 for i in range(263))).decode()
SECRET_ENV = {"TELEGRAM_API_ID": API_ID, "TELEGRAM_API_HASH": API_HASH, "TELEGRAM_SESSION": SESSION}
CLEAN = {"TELEGRAM_API_ID": "", "TELEGRAM_API_HASH": "", "TELEGRAM_SESSION": "", "TELEGRAM_USER_WRITE": "",
         "TELEGRAM_USER_ALLOWED_CHATS": "", "TELEGRAM_USER_DOWNLOAD_MB": "", "TELEGRAM_MTPROXY": ""}
READ_TOOLS = json.loads((SERVER / "tools.json").read_text())["tools"]
WRITE_TOOLS = ["join_channel", "leave_channel", "mark_read", "send_message"]
WHEN = datetime.datetime(2026, 10, 1, 12, 0, tzinfo=datetime.timezone.utc)


def rpc(calls, env=None, timeout=60):
    """initialize, tools/list and tools/call of each (tool, arguments) over stdio; (answers by id,
    everything the server wrote to stdout and stderr)."""
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
                               env={**os.environ, **CLEAN, **(env or {})})
    answers, lines = {}, []
    try:
        for message in messages:
            process.stdin.write(json.dumps(message) + "\n")
            process.stdin.flush()
            while "id" in message and message["id"] not in answers:
                line = process.stdout.readline()
                if not line:
                    raise AssertionError(f"the server ended without answering {message['method']}")
                lines.append(line)
                answer = json.loads(line)
                if "id" in answer:
                    answers[answer["id"]] = answer
    finally:
        process.stdin.close()
        rest, stderr = process.communicate(timeout=timeout)
    return answers, "".join(lines) + rest, stderr


def result(answer):
    content = answer["result"]["structuredContent"] if "structuredContent" in answer["result"] else \
        json.loads(answer["result"]["content"][0]["text"])
    return content.get("result", content)


def load(env=None, downloads=False, name="server"):
    """servers/telegram-user/src/NAME.py as a fresh module, imported under *env*."""
    spec = importlib.util.spec_from_file_location(f"telegram_user_{name}", SERVER / "src" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    hook = sys.excepthook
    with mock.patch.dict(os.environ, {**CLEAN, **(env or {})}), contextlib.ExitStack() as stack:
        if downloads:
            stack.enter_context(mock.patch("os.access", return_value=True))
            stack.enter_context(mock.patch("os.path.isdir", return_value=True))
        spec.loader.exec_module(module)
    sys.excepthook = hook
    return module


def tool_names(module):
    return sorted(t.name for t in asyncio.run(module.mcp.list_tools()))


# --- a fake Telethon client ---------------------------------------------------------------------

def channel(id=1234567890, username="leakchannel", **kw):
    return types.Channel(id=id, title=kw.pop("title", "Leaks"), photo=types.ChatPhotoEmpty(), date=WHEN,
                         access_hash=11, broadcast=True, username=username, participants_count=5000, **kw)


def user(id=42, username="ada_lovelace", **kw):
    return types.User(id=id, access_hash=22, first_name="Ada", last_name="L", username=username, **kw)


def message(id, text="", when=WHEN, peer=None, **kw):
    return types.Message(id=id, peer_id=peer or types.PeerChannel(1234567890), date=when, message=text, **kw)


class FakeClient:
    """What the server uses of a TelegramClient, recorded; no network."""

    def __init__(self):
        self.channel, self.other, self.user = channel(), channel(id=1987654321, username="otherchannel"), user()
        self.hidden = channel(id=1777777777, username=None, title="Known only from the dialogs")
        self.me = types.User(id=1, is_self=True, first_name="Inv", username="investigator", phone="491701234567")
        self.messages, self.calls, self.sent, self.dialogs_loaded, self.fail = [], [], [], False, None
        self.downloads = b""

    def _maybe_fail(self):
        if self.fail is not None:
            raise self.fail

    async def get_me(self):
        self._maybe_fail()
        return self.me

    async def get_entity(self, value):
        self.calls.append(("get_entity", value))
        self._maybe_fail()
        known = {"leakchannel": self.channel, -1001234567890: self.channel, "otherchannel": self.other,
                 -1001987654321: self.other, "ada_lovelace": self.user, 42: self.user}
        if self.dialogs_loaded:
            known[-1001777777777] = self.hidden
        if value in known:
            return known[value]
        if isinstance(value, str):
            raise ValueError(f'No user has "{value}" as username')
        raise ValueError(f"Could not find the input entity for {value}")

    async def get_dialogs(self, limit=None):
        self.calls.append(("get_dialogs", limit))
        self.dialogs_loaded = True
        return []

    async def iter_messages(self, entity, limit=None, **options):
        self.calls.append(("iter_messages", entity, limit, options))
        self._maybe_fail()
        for item in self.messages[:limit]:
            yield item

    async def iter_dialogs(self, limit=None, archived=None):
        self.calls.append(("iter_dialogs", limit, archived))
        if False:
            yield

    async def get_messages(self, entity, ids=None):
        self.calls.append(("get_messages", entity, ids))
        return next((m for m in self.messages if m.id == ids), None)

    async def download_media(self, item, file=None):
        self.calls.append(("download_media", item.id))
        for start in range(0, len(self.downloads), 4):
            file.write(self.downloads[start:start + 4])
        return file

    async def send_message(self, entity, text, **options):
        self.calls.append(("send_message", entity, text, options))
        self.sent.append(text)
        return message(500, text, peer=types.PeerChannel(entity.id))

    async def send_read_acknowledge(self, entity, max_id=None):
        self.calls.append(("send_read_acknowledge", entity, max_id))

    async def __call__(self, request):
        self.calls.append(("request", type(request).__name__))
        self._maybe_fail()
        if isinstance(request, functions.contacts.SearchRequest):
            return types.contacts.Found(my_results=[types.PeerUser(42)], results=[types.PeerChannel(1234567890)],
                                        chats=[self.channel], users=[self.user])
        if isinstance(request, functions.messages.CheckChatInviteRequest):
            return types.ChatInvite(title="Secret group", photo=types.PhotoEmpty(id=1), participants_count=12,
                                    color=0, megagroup=True, about="invite only")
        if isinstance(request, functions.channels.GetFullChannelRequest):
            full = types.ChannelFull(id=1234567890, about="We publish leaks", read_inbox_max_id=0,
                                     read_outbox_max_id=0, unread_count=0, chat_photo=types.PhotoEmpty(id=1),
                                     notify_settings=types.PeerNotifySettings(), bot_info=[], pts=1,
                                     participants_count=5000, linked_chat_id=1555555555)
            return types.messages.ChatFull(full_chat=full, chats=[self.channel, channel(id=1555555555, username="leakchat",
                                                                                         title="Leaks chat")], users=[])
        return types.Updates(updates=[], users=[], chats=[self.other], date=WHEN, seq=0)

    async def disconnect(self):
        self.calls.append(("disconnect",))


@unittest.skipIf(mcp is None, "the server's requirements are not installed (mcp, telethon)")
class ToolList(unittest.TestCase):
    def test_read_only_by_default_and_missing_secrets(self):
        answers, stdout, stderr = rpc([("get_me", {}), ("get_messages", {"chat": "durov", "limit": 201}),
                                       ("send_message", {"chat": "durov", "text": "x"})])
        self.assertIn("serverInfo", answers[0]["result"])
        self.assertEqual(sorted(t["name"] for t in answers[1]["result"]["tools"]), READ_TOOLS)
        self.assertEqual(result(answers[2])["error"],
                         "no Telegram account: set TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_SESSION for this "
                         "server (api_id and api_hash from https://my.telegram.org, the session printed by login.py)")
        self.assertIn("limit: an integer from 1 to 200", result(answers[3])["error"])  # arguments before secrets
        self.assertTrue(answers[4]["result"].get("isError"))  # not offered at all
        self.assertIn("TELEGRAM_SESSION", stderr)  # said when it starts
        self.assertIn("write tools off", stderr)

    def test_write_tools_only_with_the_opt_in(self):
        answers, _, _ = rpc([], env={"TELEGRAM_USER_WRITE": "1"})
        self.assertEqual(sorted(t["name"] for t in answers[1]["result"]["tools"]), sorted(READ_TOOLS + WRITE_TOOLS))
        for value in ("true", "yes", "0", " "):
            answers, _, _ = rpc([], env={"TELEGRAM_USER_WRITE": value})
            self.assertEqual(sorted(t["name"] for t in answers[1]["result"]["tools"]), READ_TOOLS, value)

    def test_malformed_secrets_are_named_never_shown(self):
        bad_session = "1" + "A" * 20 + "notasession"
        answers, stdout, stderr = rpc([("get_me", {})], env={**SECRET_ENV, "TELEGRAM_SESSION": bad_session})
        self.assertEqual(result(answers[2])["error"],
                         "TELEGRAM_SESSION: not a Telethon StringSession (login.py prints one)")
        answers, stdout2, stderr2 = rpc([("get_me", {})], env={**SECRET_ENV, "TELEGRAM_API_HASH": "xyz" * 11})
        self.assertIn("TELEGRAM_API_HASH: the 32 hex digits", result(answers[2])["error"])
        everything = stdout + stderr + stdout2 + stderr2
        for value in (bad_session, "xyz" * 11, SESSION, API_HASH):
            self.assertNotIn(value, everything)

    def test_download_only_with_a_writable_out(self):
        self.assertNotIn("download_media", tool_names(load()))
        self.assertEqual(tool_names(load(downloads=True)), sorted(READ_TOOLS + ["download_media"]))
        self.assertEqual(tool_names(load({"TELEGRAM_USER_WRITE": "1"}, downloads=True)),
                         sorted(READ_TOOLS + WRITE_TOOLS + ["download_media"]))


@unittest.skipIf(mcp is None, "the server's requirements are not installed (mcp, telethon)")
class WithFakeClient(unittest.TestCase):
    env = {}

    def setUp(self):
        self.module = load({**SECRET_ENV, **self.env})
        self.fake = FakeClient()
        self.log = io.StringIO()
        self.module._handler.setStream(self.log)
        self.answers = []
        environment = mock.patch.dict(os.environ, {**CLEAN, **SECRET_ENV, **self.env})
        environment.start()
        self.addCleanup(environment.stop)

        async def connect(creds):
            self.assertEqual(creds, (int(API_ID), API_HASH, SESSION))
            return self.fake
        patch = mock.patch.object(self.module, "connect", connect)
        patch.start()
        self.addCleanup(patch.stop)

    def call(self, tool, *args, **kwargs):
        answer = asyncio.run(getattr(self.module, tool)(*args, **kwargs))
        self.answers.append(answer)
        return answer

    def assert_no_secret_anywhere(self):
        everything = json.dumps(self.answers, ensure_ascii=False) + self.log.getvalue()
        for value in (SESSION, SESSION[1:60], API_HASH, API_ID, "491701234567"):
            self.assertNotIn(value, everything)


class ReadTools(WithFakeClient):
    def test_get_me_without_phone(self):
        me = self.call("get_me")
        self.assertEqual(me["account"], {"id": 1, "username": "investigator", "name": "Inv"})
        self.assertTrue(me["write_tools"].startswith("off"))
        self.assertTrue(me["downloads"].startswith("off"))
        self.assert_no_secret_anywhere()

    def test_messages_limits_options_and_format(self):
        self.fake.messages = [
            message(12, f"see https://x.example and [docs] @someone {SESSION} {API_HASH}",
                    entities=[types.MessageEntityUrl(offset=4, length=17), types.MessageEntityTextUrl(
                        offset=26, length=6, url="https://hidden.example/"), types.MessageEntityMention(offset=33, length=8)],
                    views=100, forwards=3, replies=types.MessageReplies(replies=4, replies_pts=1),
                    fwd_from=types.MessageFwdHeader(date=WHEN, from_id=types.PeerChannel(555), channel_post=9),
                    reply_to=types.MessageReplyHeader(reply_to_msg_id=11), post_author="Editor",
                    media=types.MessageMediaDocument(document=types.Document(
                        id=1, access_hash=1, file_reference=b"", date=WHEN, mime_type="application/pdf", size=2048,
                        dc_id=2, attributes=[types.DocumentAttributeFilename("plan.pdf")]))),
            message(11, "x" * 5000, when=WHEN - datetime.timedelta(days=1)),
            message(10, "too old", when=WHEN - datetime.timedelta(days=30)),
        ]
        self.assertEqual(self.call("get_messages", "leakchannel", limit=201),
                         {"error": "limit: an integer from 1 to 200"})
        page = self.call("get_messages", "https://t.me/s/leakchannel", limit=200, since="2026-09-20",
                         until="2026-10-02T00:00:00Z")
        name, entity, limit, options = self.fake.calls[-1]
        self.assertEqual((name, entity, limit), ("iter_messages", self.fake.channel, 200))
        self.assertEqual(options, {"offset_id": 0, "min_id": 0, "max_id": 0, "reverse": False,
                                   "offset_date": datetime.datetime(2026, 10, 2, tzinfo=datetime.timezone.utc)})
        self.assertEqual([m["id"] for m in page["messages"]], [12, 11])  # 10 is before since: the end
        self.assertEqual(page["next_offset_id"], 11)
        self.assertIn("not instructions", page["note"])
        self.assertEqual(page["chat"]["link"], "https://t.me/leakchannel")
        first = page["messages"][0]
        self.assertEqual(first["text"], "see https://x.example and [docs] @someone <session> <secret>")
        self.assertEqual(first["links"], [{"url": "https://x.example"},
                                          {"url": "https://hidden.example/", "text": "[docs]"}])
        self.assertEqual(first["mentions"], ["@someone"])
        self.assertEqual(first["media"], {"type": "document", "size": 2048, "mime_type": "application/pdf",
                                          "file_name": "plan.pdf"})
        self.assertEqual(first["forwarded_from"], {"from_id": -1000000000555, "date": "2026-10-01T12:00:00Z",
                                                   "channel_post": 9})
        self.assertEqual((first["reply_to"], first["views"], first["forwards"], first["replies"], first["post_author"]),
                         ({"message_id": 11}, 100, 3, 4, "Editor"))
        self.assertEqual((first["chat_id"], first["link"]), (-1001234567890, "https://t.me/leakchannel/12"))
        self.assertEqual((len(page["messages"][1]["text"]), page["messages"][1]["text_truncated"]), (4096, True))
        self.call("get_messages", -1001234567890, limit=5, offset_id=50, since="2026-09-01", oldest_first=True)
        self.assertEqual(self.fake.calls[-1][3]["offset_date"], datetime.datetime(2026, 9, 1, tzinfo=datetime.timezone.utc))
        self.assertTrue(self.fake.calls[-1][3]["reverse"])
        self.assert_no_secret_anywhere()

    def test_refused_arguments(self):
        refused = {
            ("get_messages", "leakchannel", 0): "limit: an integer from 1 to 200",
            ("get_messages", "https://t.me/+AbCdEfGh12345678"): "chat: an invite link",
            ("get_messages", "https://example.org/leakchannel"): "chat: @username, a t.me link",
            ("get_messages", "@abc"): "chat: @username",
            ("get_messages", True): "chat: @username",
            ("get_messages", 0): "chat: @username",
            ("get_messages", "javascript:alert(1)"): "chat: @username",
            ("resolve_chat", "tg://resolve?domain=x"): "chat: @username",
            ("check_invite", "leakchannel"): "link: an invite link",
            ("search_chats", "a\x00b"): "query: 1-256 characters",
            ("search_chats", "x" * 257): "query: 1-256 characters",
            ("search_chats", "leaks", 101): "limit: an integer from 1 to 100",
            ("list_dialogs", 201): "limit: an integer from 1 to 200",
            ("search_global", "x", 500): "limit: an integer from 1 to 200",
            ("get_replies", "leakchannel", 0): "message_id: an integer from 1",
        }
        for (tool, *args), expected in refused.items():
            self.assertIn(expected, self.call(tool, *args).get("error", ""), (tool, args))
        for kwargs, expected in (({"since": "2026-10-02", "until": "2026-10-01"}, "since: earlier than until"),
                                 ({"since": "last week"}, "since: a date like"),
                                 ({"until": "1999-01-01"}, "until: a date between 2013 and 2100"),
                                 ({"min_id": 5, "max_id": 5}, "min_id: smaller than max_id"),
                                 ({"offset_id": -1}, "offset_id: an integer"),
                                 ({"oldest_first": "yes"}, "oldest_first: true or false")):
            self.assertIn(expected, self.call("get_messages", "leakchannel", **kwargs)["error"], kwargs)
        self.assertEqual(self.fake.calls, [])  # refused before anything was asked

    def test_resolve_search_info_invite(self):
        self.assertEqual(self.call("resolve_chat", "@leakchannel")["chat"],
                         {"id": -1001234567890, "type": "channel", "title": "Leaks", "participants_count": 5000,
                          "date": "2026-10-01T12:00:00Z", "username": "leakchannel",
                          "link": "https://t.me/leakchannel"})
        found = self.call("search_chats", "leaks", 10)
        self.assertEqual([r["id"] for r in found["my_results"]], [42])
        self.assertEqual([r["id"] for r in found["results"]], [-1001234567890])
        info = self.call("get_chat_info", "t.me/leakchannel")
        self.assertEqual(info["info"], {"about": "We publish leaks", "participants_count": 5000,
                                        "linked_chat_id": -1001555555555})
        self.assertEqual(info["linked_chat"]["username"], "leakchat")
        invite = self.call("check_invite", "https://t.me/joinchat/AbCdEfGh12345678")
        self.assertEqual(invite, {"member": False, "invite": {"title": "Secret group", "about": "invite only",
                                                               "participants_count": 12, "type": "supergroup"},
                                  "note": invite["note"]})
        self.assertNotIn(("request", "ImportChatInviteRequest"), self.fake.calls)  # looked at, not joined

    def test_unknown_id_loads_the_dialogs_once(self):
        self.assertEqual(self.call("resolve_chat", "https://t.me/c/1777777777/5")["chat"]["title"], "Known only from the dialogs")
        self.assertIn("is not known to this session", self.call("resolve_chat", -1001888888888)["error"])
        self.assertEqual([c for c in self.fake.calls if c[0] == "get_dialogs"], [("get_dialogs", 500)])
        self.assertIn('No user has "nobodyhere" as username', self.call("resolve_chat", "nobodyhere")["error"])

    def test_flood_wait_is_answered_not_retried(self):
        self.fake.fail = errors.FloodWaitError(request=None, capture=37)
        answer = self.call("get_messages", "leakchannel", limit=10)
        self.assertEqual(answer["retry_after"], 37)
        self.assertIn("Telegram flood wait: 37 s", answer["error"])
        self.assertIn("not retried", answer["error"])
        self.assertEqual(len([c for c in self.fake.calls if c[0] == "iter_messages"]), 0)  # get_entity failed first
        self.fake.fail = None
        self.fake.messages = [message(1, "x")]

        async def flooding(entity, limit=None, **options):
            self.fake.calls.append(("iter_messages", entity, limit, options))
            raise errors.SlowModeWaitError(request=None, capture=5)
            yield
        self.fake.iter_messages = flooding
        answer = self.call("search_messages", "leakchannel", "leak")
        self.assertEqual((answer["retry_after"], len([c for c in self.fake.calls if c[0] == "iter_messages"])), (5, 1))

    def test_errors_never_carry_secrets(self):
        for failure in (RuntimeError(f"boom {SESSION} {API_HASH}"), ValueError(f"bad {SESSION}"),
                        errors.RPCError(request=None, message=f"WEIRD {API_HASH}", code=400),
                        ConnectionError(f"to 149.154.167.51 {SESSION}")):
            self.module._state["client"] = None
            self.fake.fail = failure
            answer = self.call("resolve_chat", "leakchannel")
            self.assertIn("error", answer)
        self.assertEqual(self.answers[0], {"error": "internal error (RuntimeError)"})
        self.assertEqual(self.answers[3], {"error": "Telegram not reachable (ConnectionError)"})
        self.module.log.error("a line with %s %s %s", SESSION, API_HASH, API_ID)
        self.module.log.warning("a session-shaped text %s", "1" + "Q" * 351 + "=")
        self.assertIn("a line with <session> <secret> <api_id>", self.log.getvalue())
        self.assertIn("a session-shaped text <session>", self.log.getvalue())
        self.assert_no_secret_anywhere()

    def test_a_revoked_session_drops_the_client(self):
        self.assertEqual(self.call("get_me")["account"]["id"], 1)
        self.fake.fail = errors.AuthKeyUnregisteredError(request=None)
        self.assertIn("log in again with login.py", self.call("get_me")["error"])
        self.assertIsNone(self.module._state["client"])

    def test_write_tools_refuse_when_off(self):
        for tool, args in (("_send_message", ("leakchannel", "hi", 0, False)), ("_join_channel", ("leakchannel",)),
                           ("_leave_channel", ("leakchannel",)), ("_mark_read", ("leakchannel", 0))):
            answer = asyncio.run(self.module._guarded(getattr(self.module, tool)(*args)))
            self.assertEqual(answer, {"error": "write tools are off (TELEGRAM_USER_WRITE=1 turns them on)"})
        self.assertEqual(self.fake.sent, [])


class Connect(unittest.TestCase):
    @unittest.skipIf(mcp is None, "the server's requirements are not installed (mcp, telethon)")
    def test_client_options_in_memory_session_no_file(self):
        module = load(SECRET_ENV)
        made = []

        class Recorder:
            authorized = True

            def __init__(self, session, api_id, api_hash, **options):
                made.append((session, api_id, api_hash, options))
                self.parse_mode, self.disconnected = "md", False

            async def connect(self):
                pass

            async def is_user_authorized(self):
                return self.authorized

            async def get_me(self):
                return types.User(id=1, is_self=True)

            async def disconnect(self):
                self.disconnected = True

        with tempfile.TemporaryDirectory() as folder, contextlib.chdir(folder), \
                mock.patch.dict(os.environ, {**CLEAN, **SECRET_ENV}), mock.patch.object(module, "TelegramClient", Recorder):
            client = asyncio.run(module.connect(module.credentials()))
            self.assertEqual(os.listdir(folder), [])  # no .session file
        session, api_id, api_hash, options = made[0]
        self.assertIsInstance(session, module.StringSession)
        self.assertEqual((api_id, api_hash), (int(API_ID), API_HASH))
        self.assertEqual(options["flood_sleep_threshold"], 0)  # Telethon never sleeps through a flood wait
        self.assertEqual((options["receive_updates"], options["device_model"]), (False, "sandbox-ai-mcp"))
        self.assertNotIn("proxy", options)
        self.assertIsNone(client.parse_mode)  # plain text: no Markdown surprises

        Recorder.authorized = False
        with mock.patch.object(module, "TelegramClient", Recorder), self.assertRaises(module.ArgumentError) as caught:
            asyncio.run(module.connect((int(API_ID), API_HASH, SESSION)))
        self.assertIn("not logged in", str(caught.exception))
        with mock.patch.dict(os.environ, {"TELEGRAM_MTPROXY": "proxy.example:443:dd" + "ab" * 16}):
            options = module.mtproxy()
            self.assertEqual(options["proxy"], ("proxy.example", 443, "dd" + "ab" * 16))
            self.assertIn("<secret>", module.redact("ab" * 16))
        for bad in ("proxy.example:443:ee" + "ab" * 16, "proxy.example:0:" + "ab" * 16, "http://x:1:" + "ab" * 16):
            with mock.patch.dict(os.environ, {"TELEGRAM_MTPROXY": bad}), self.assertRaises(module.ArgumentError):
                module.mtproxy()


class WriteTools(WithFakeClient):
    env = {"TELEGRAM_USER_WRITE": "1", "TELEGRAM_USER_ALLOWED_CHATS": "-1001234567890, @Ada_Lovelace"}

    def test_allowed_chats(self):
        sent = self.call("send_message", "leakchannel", "hello", silent=True)
        self.assertEqual(sent["sent"]["text"], "hello")
        options = [c for c in self.fake.calls if c[0] == "send_message"][0][3]
        self.assertEqual(options, {"reply_to": None, "silent": True, "link_preview": False, "parse_mode": None})
        self.assertEqual(self.call("send_message", "otherchannel", "hello"),
                         {"error": "chat -1001987654321 is not in TELEGRAM_USER_ALLOWED_CHATS"})
        self.assertIn("sent", self.call("send_message", "@ada_lovelace", "hi"))  # allowed by @username
        self.assertEqual(self.fake.sent, ["hello", "hi"])
        self.assertIn("cannot be checked against TELEGRAM_USER_ALLOWED_CHATS",
                      self.call("join_channel", "https://t.me/+AbCdEfGh12345678")["error"])
        self.assertIn("not in TELEGRAM_USER_ALLOWED_CHATS", self.call("join_channel", "otherchannel")["error"])
        self.assertEqual(self.call("join_channel", "leakchannel")["joined"]["id"], -1001234567890)
        self.assertIn("not a conversation with a user", self.call("leave_channel", "ada_lovelace")["error"])
        self.assertEqual(self.call("leave_channel", "leakchannel")["left"]["id"], -1001234567890)
        self.assertEqual(self.call("mark_read", "leakchannel", 12)["up_to"], 12)
        self.assertIn("text: 1-4096", self.call("send_message", "leakchannel", "x" * 4097)["error"])
        self.assertIn("text: 1-4096", self.call("send_message", "leakchannel", "a\x00b")["error"])
        requests = [c[1] for c in self.fake.calls if c[0] == "request"]
        self.assertEqual(requests, ["JoinChannelRequest", "LeaveChannelRequest"])
        me = self.call("get_me")
        self.assertEqual((me["write_tools"], me["allowed_chats"]), ("on", [-1001234567890, "@ada_lovelace"]))
        self.assert_no_secret_anywhere()

    def test_a_broken_list_refuses_every_write(self):
        with mock.patch.dict(os.environ, {"TELEGRAM_USER_ALLOWED_CHATS": "leakchannel,-100x"}):
            for tool, args in (("send_message", ("leakchannel", "x")), ("join_channel", ("leakchannel",)),
                               ("leave_channel", ("leakchannel",)), ("mark_read", ("leakchannel",))):
                self.assertIn("TELEGRAM_USER_ALLOWED_CHATS: comma-separated", self.call(tool, *args)["error"])
        self.assertEqual(self.fake.calls, [])

    def test_invite_links_without_a_list(self):
        with mock.patch.dict(os.environ, {"TELEGRAM_USER_ALLOWED_CHATS": ""}):
            self.assertEqual(self.call("join_channel", "https://t.me/+AbCdEfGh12345678")["joined"]["id"], -1001987654321)
            self.assertIn("sent", self.call("send_message", "otherchannel", "hello"))


class Downloads(WithFakeClient):
    def setUp(self):
        super().setUp()
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.out = Path(folder.name)
        patch = mock.patch.object(self.module, "OUT_DIR", self.out)
        patch.start()
        self.addCleanup(patch.stop)

    def document(self, id, size):
        return message(id, "", media=types.MessageMediaDocument(document=types.Document(
            id=id, access_hash=1, file_reference=b"", date=WHEN, mime_type="image/png", size=size, dc_id=2,
            attributes=[types.DocumentAttributeFilename("../../etc/passwd.png")])))

    def test_download_into_out(self):
        self.fake.messages = [self.document(5, 10), self.document(6, 2 << 20), self.document(7, 10), message(8, "text")]
        self.fake.downloads = b"0123456789"
        saved = self.call("download_media", "leakchannel", 5)
        path = self.out / "telegram-user" / "-1001234567890_5.png"
        self.assertEqual(saved, {"path": str(path), "size": 10, "sha256": hashlib.sha256(b"0123456789").hexdigest(),
                                 "mime_type": "image/png", "file_name_in_telegram": "../../etc/passwd.png",
                                 "type": "document"})
        self.assertEqual(path.read_bytes(), b"0123456789")
        self.assertIn("exists already", self.call("download_media", "leakchannel", 5)["error"])
        with mock.patch.dict(os.environ, {"TELEGRAM_USER_DOWNLOAD_MB": "1"}):
            self.assertIn("more than 1 MiB", self.call("download_media", "leakchannel", 6)["error"])
            self.fake.downloads = b"x" * ((1 << 20) + 1)  # Telegram said 10 bytes, sends more
            self.assertIn("larger than 1 MiB", self.call("download_media", "leakchannel", 7)["error"])
            self.assertFalse((self.out / "telegram-user" / "-1001234567890_7.png").exists())  # removed
        self.assertIn("no photo or document", self.call("download_media", "leakchannel", 8)["error"])
        self.assertIn("no message 9", self.call("download_media", "leakchannel", 9)["error"])
        self.assertEqual([c[1] for c in self.fake.calls if c[0] == "download_media"], [5, 7])
        with mock.patch.object(self.module, "OUT_DIR", self.out / "missing"):
            self.assertIn("mount a writable /out", self.call("download_media", "leakchannel", 5)["error"])


@unittest.skipIf(mcp is None, "the server's requirements are not installed (mcp, telethon)")
class Login(unittest.TestCase):
    def run_login(self, argv, tty=False, stdin="+4917012345678\n12345\n"):
        login = load(name="login")
        asked = []

        class Fake:
            def __init__(self, session, api_id, api_hash, **options):
                self.session, self.options = session, options
                asked.append(("client", type(session).__name__, api_id, options["device_model"]))

            async def start(self, phone, code_callback, password):
                asked.extend([("phone", phone()), ("code", code_callback()), ("password", password())])
                print("Signed in successfully as Inv")  # as Telethon does, to stdout

            async def get_me(self):
                return types.User(id=1, first_name="Inv", is_self=True)

            async def disconnect(self):
                pass

        class Out(io.StringIO):
            def isatty(self):
                return tty

        out, err = Out(), io.StringIO()
        with tempfile.TemporaryDirectory() as folder, contextlib.chdir(folder), \
                mock.patch.object(login, "TelegramClient", Fake), \
                mock.patch.object(login.StringSession, "save", lambda self: SESSION), \
                mock.patch.object(login.getpass, "getpass", lambda prompt, stream=None: "two-step"), \
                mock.patch.dict(os.environ, {**CLEAN, "TELEGRAM_API_ID": API_ID, "TELEGRAM_API_HASH": API_HASH}), \
                mock.patch.object(sys, "stdin", io.StringIO(stdin)), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = login.main(argv)
            files = os.listdir(folder)
        return code, out.getvalue(), err.getvalue(), asked, files

    def test_only_the_session_on_stdout_and_no_file(self):
        code, out, err, asked, files = self.run_login([])
        self.assertEqual((code, out, files), (0, SESSION + "\n", []))
        self.assertEqual(asked, [("client", "StringSession", int(API_ID), "sandbox-ai-mcp"),
                                 ("phone", "+4917012345678"), ("code", "12345"), ("password", "two-step")])
        self.assertIn("Signed in successfully", err)
        self.assertIn("Phone number", err)
        self.assertNotIn(SESSION, err)

    def test_refuses_a_terminal_without_show(self):
        code, out, err, asked, _ = self.run_login([], tty=True)
        self.assertEqual((code, out, asked), (2, "", []))
        self.assertIn("sandbox-ai secrets set TELEGRAM_SESSION", err)
        code, out, _, _, _ = self.run_login(["--show"], tty=True)
        self.assertEqual((code, out), (0, SESSION + "\n"))


if __name__ == "__main__":
    unittest.main()
