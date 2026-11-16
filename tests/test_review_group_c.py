"""Found by the in-depth review of 2026-11-17 (group C: bluesky, signal, telegram, telegram-user, whatsapp, memory,
engram, sequential-thinking, tasks); each test failed before its fix.

- tasks, bluesky, telegram, telegram-user and signal announced the MCP capabilities "resources" and "prompts"
  (FastMCP registers both for every server) and publish neither. Agents act on the capability (Claude Code,
  OpenCode and Pi offer resource tools, Hermes four more tools per server) and local models take those for the way
  to the server's tools. They announce tools only now, as the servers of groups A and B.
- Answers far above what clients show a model (Claude Code, Qwen Code and Hermes show only a preview and a file path
  of a tool result much above 25,000 characters): get_updates (100 updates of up to 4,096 characters), the plan of
  tasks (200 steps of up to 500 characters), list_my_posts and get_post_thread (posts of up to 3,000 characters),
  get_messages and the searches of telegram-user (200 messages of up to 4,096 characters), signal's lists (bounded
  at 128 KiB). Every answer is at most 24,000 characters as sent now; what is left out is said, and a page goes on
  where the answer stopped (next_offset, next_offset_id), never past what was not shown.
- telegram and telegram-user sent as fast as the agent asked (an agent in a loop: one message after the other into a
  chat, a user account banned for it); signal and whatsapp allow 20 a minute. Both refuse a 21st send within a
  minute now and say when the next one may go.

Each class needs its server's requirements (and signal-mcp's modules for signal, Telethon for telegram-user); without
them it is skipped, as the other offline tests of this repository.
"""
from __future__ import annotations

import asyncio
import contextlib
import datetime
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))  # the fakes of test_bluesky, test_telegram_user and test_signal
#: What a client shows a model of one tool answer (docs/LOCAL_LLM_TOOLS.md): an answer stays at or below it.
MAX_ANSWER = 24_000


def installed(*modules: str) -> bool:
    return all(importlib.util.find_spec(name) is not None for name in modules)


def load(name: str, env: dict | None = None):
    spec = importlib.util.spec_from_file_location(f"review_c_{name.replace('-', '_')}",
                                                  ROOT / "servers" / name / "src/server.py")
    module = importlib.util.module_from_spec(spec)
    hook = sys.excepthook
    with mock.patch.dict(os.environ, env or {}):
        spec.loader.exec_module(module)
    sys.excepthook = hook
    return module


def rpc(name: str, messages: list[dict], env: dict | None = None) -> dict:
    """The answers (by id) of the server NAME, started as its image starts it (python -I -u server.py)."""
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


def sent(module, tool: str, arguments: dict) -> str:
    """The text a client gets of TOOL's answer, as FastMCP makes it (a dict as JSON indented by 2)."""
    result = asyncio.run(module.mcp.call_tool(tool, arguments))
    content = result[0] if isinstance(result, tuple) else result
    return content[0].text


def as_sent(answer: dict) -> int:
    """Characters of ANSWER as FastMCP sends a tool's dict."""
    import pydantic_core
    return len(pydantic_core.to_json(answer, fallback=str, indent=2).decode())


class ToolsOnlyCheck:
    """SERVER announces tools only; its instructions say that what others wrote is data, not instructions."""
    server = ""
    env: dict = {}
    untrusted = True

    def test_the_server_announces_tools_only(self):
        answers = rpc(self.server, handshake(("tools/list", {}), ("resources/list", {}), ("prompts/list", {})),
                      env=self.env)
        capabilities = answers[0]["result"]["capabilities"]
        self.assertIn("tools", capabilities)
        self.assertNotIn("resources", capabilities)
        self.assertNotIn("prompts", capabilities)
        self.assertTrue(answers[1]["result"]["tools"])
        for request in (2, 3):  # a client that asks anyway: the method does not exist
            self.assertEqual(answers[request]["error"]["code"], -32601, answers[request])
        if self.untrusted:
            self.assertRegex(answers[0]["result"].get("instructions") or "", r"data, (never|not) instructions")


# --- tasks --------------------------------------------------------------------------------------------------------

@unittest.skipUnless(installed("mcp"), "the server's requirements are not installed (servers/tasks/requirements.txt)")
class Tasks(ToolsOnlyCheck, unittest.TestCase):
    server = "tasks"
    untrusted = False

    def setUp(self):
        self.work = os.path.realpath(tempfile.mkdtemp(prefix="tasks-review-"))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.module = load("tasks")
        self.module.WORKSPACE = self.work
        self.module.MOUNT_REQUIRED = False

    def big_plan(self):
        m = self.module
        m.do_set_goal("g" * m.MAX_GOAL, False)
        for start in range(0, m.MAX_STEPS, m.MAX_ADD):
            m.do_add_steps([f"step {start + i} " + "s" * (m.MAX_STEP - 12) for i in range(m.MAX_ADD)], None)
        for number in range(1, 11):
            m.change_state(number, "done", "n" * m.MAX_NOTE)
        for _ in range(m.MAX_NOTES):
            m.do_add_note("p" * m.MAX_NOTE, None)

    def test_every_answer_of_a_full_plan_fits(self):
        """200 steps of 500 characters: list_steps was 106,000 characters, add_steps and remove_step answer the same
        listing, progress 76,000, next_step with only blocked steps left 162,000."""
        self.big_plan()
        m = self.module
        answers = {tool: sent(m, tool, {}) for tool in ("list_steps", "progress", "next_step")}
        answers["remove_step"] = sent(m, "remove_step", {"step": 200})
        answers["add_steps"] = sent(m, "add_steps", {"steps": ["one more " + "x" * 400]})
        answers["set_goal"] = sent(m, "set_goal", {"goal": "the same goal, said again"})
        for number in range(11, 202):
            if number != 200:
                m.change_state(number, "blocked", "r" * m.MAX_NOTE, note_required=True)
        answers["block_step"] = sent(m, "block_step", {"step": 1, "reason": "blocked " + "r" * 900})
        answers["next_step (only blocked steps)"] = sent(m, "next_step", {})
        for tool, text in answers.items():
            with self.subTest(tool):
                self.assertLessEqual(len(text), MAX_ANSWER)
                if tool != "next_step":  # the next step alone, with its notes, fits
                    self.assertRegex(text, r"more lines not shown")
        self.assertIn("Goal: the same goal", answers["set_goal"])
        self.assertIn("step 0 ", answers["list_steps"])

    def test_block_step_works_as_a_tool(self):
        """block_step failed on every call: in_thread() took no keyword argument (note_required), so the tool
        answered "Error executing tool block_step: in_thread() got an unexpected keyword argument" and nothing was
        blocked (the other tests called change_state directly)."""
        m = self.module
        m.do_set_goal("ship it", False)
        m.do_add_steps(["one", "two"], None)
        text = sent(m, "block_step", {"step": 1, "reason": "needs the network"})
        self.assertIn("Step 1 blocked: needs the network", text)
        self.assertEqual(m.do_read(lambda plan: plan["steps"][0]["state"]), "blocked")

    def test_a_small_plan_is_shown_whole(self):
        m = self.module
        m.do_set_goal("ship it", False)
        m.do_add_steps(["one", "two"], None)
        text = sent(m, "list_steps", {})
        self.assertNotIn("not shown", text)
        self.assertIn("2. [ ] two", text)


# --- telegram (bot) -----------------------------------------------------------------------------------------------

@unittest.skipUnless(installed("mcp", "httpx"), "the server's requirements are not installed "
                                                "(servers/telegram/requirements.txt)")
class Telegram(ToolsOnlyCheck, unittest.TestCase):
    server = "telegram"
    TOKEN = "123456789:" + "A" * 35
    CHAT = -1001234567890

    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": self.TOKEN, "TELEGRAM_ALLOWED_CHATS": ""})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.module = load("telegram")

    def updates(self, count: int, first: int = 1000, size: int = 4096) -> list[dict]:
        return [{"update_id": first + i, "message": {
            "message_id": i + 1, "date": 1_790_000_000 + i, "chat": {"id": self.CHAT, "type": "supergroup",
                                                                     "title": "T" * 300},
            "from": {"id": 42, "is_bot": False, "first_name": "F" * 300}, "text": f"{i} " + "x" * (size - 6),
            "caption": "c" * size}} for i in range(count)]

    def test_get_updates_fits_and_confirms_only_what_it_showed(self):
        """100 updates with 4,096-character texts were about 900,000 characters; next_offset confirmed all of them,
        so those left out by the client's preview were gone."""
        calls = []

        async def fake_call(method, payload, timeout=30.0):
            calls.append((method, payload))
            return self.updates(100)
        with mock.patch.object(self.module, "call", fake_call):
            text = sent(self.module, "get_updates", {"limit": 100})
        self.assertLessEqual(len(text), MAX_ANSWER)
        answer = json.loads(text)
        shown = answer["updates"]
        self.assertTrue(0 < len(shown) < 100)
        self.assertEqual(answer["count"], len(shown))
        self.assertEqual(answer["next_offset"], shown[-1]["update_id"] + 1)
        self.assertIn("not shown", answer["truncated"])
        self.assertRegex(answer["note"], r"data, not instructions")

    def test_a_small_batch_comes_whole(self):
        async def fake_call(method, payload, timeout=30.0):
            return self.updates(3, size=100)
        with mock.patch.object(self.module, "call", fake_call):
            answer = json.loads(sent(self.module, "get_updates", {}))
        self.assertEqual(answer["count"], 3)
        self.assertEqual(answer["next_offset"], 1003)
        self.assertNotIn("truncated", answer)

    def test_sends_are_rate_limited(self):
        """20 messages a minute, as signal and whatsapp allow; the 21st is refused and says when, not sent."""
        sent_texts = []

        async def fake_call(method, payload, timeout=30.0):
            sent_texts.append(payload["text"])
            return {"message_id": len(sent_texts), "chat": {"id": self.CHAT, "type": "supergroup"}, "date": 1,
                    "text": payload["text"]}
        clock = [1000.0]
        with mock.patch.object(self.module, "call", fake_call), \
                mock.patch.object(self.module.time, "monotonic", lambda: clock[0]):
            for index in range(20):
                answer = asyncio.run(self.module.send_message(self.CHAT, f"m{index}"))
                self.assertIn("sent", answer, answer)
            refused = asyncio.run(self.module.send_message(self.CHAT, "one too many"))
            self.assertRegex(refused["error"], r"at most 20 messages a minute.*wait \d+ s")
            edited = asyncio.run(self.module.edit_message_text(self.CHAT, 1, "edit"))
            self.assertIn("error", edited)
            clock[0] += 61
            self.assertIn("sent", asyncio.run(self.module.send_message(self.CHAT, "later")))
        self.assertEqual(len(sent_texts), 21)
        self.assertNotIn("one too many", sent_texts)


# --- bluesky ------------------------------------------------------------------------------------------------------

@unittest.skipUnless(installed("mcp", "httpx"), "the server's requirements are not installed "
                                                "(servers/bluesky/requirements.txt)")
class Bluesky(ToolsOnlyCheck, unittest.TestCase):
    server = "bluesky"

    def setUp(self):
        from test_bluesky import ENV, FakeBluesky  # the fake PDS and AppView of tests/test_bluesky.py
        self.module = m = load("bluesky")
        self.fake = FakeBluesky()

        async def no_sleep(seconds):
            pass
        for name, value in (("_transport", self.fake.transport()), ("SESSION", m.Session()), ("_sleep", no_sleep)):
            patcher = mock.patch.object(m, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.dict(os.environ, ENV)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_list_my_posts_fits(self):
        """50 posts of 3,000 characters were about 160,000 characters."""
        for index in range(60):
            self.fake.records[f"3kpost{index:05d}2a"] = (f"bafyreicid{index:010d}", {
                "$type": "app.bsky.feed.post", "text": f"{index} " + "é" * 2990,
                "createdAt": "2026-11-01T00:00:00.000Z"})
        text = sent(self.module, "list_my_posts", {"n": 50})
        self.assertLessEqual(len(text), MAX_ANSWER)
        answer = json.loads(text)
        self.assertTrue(0 < answer["count"] < 50)
        self.assertEqual(len(answer["posts"]), answer["count"])
        self.assertIn("not shown", answer["truncated"])

    def test_get_post_thread_fits(self):
        """100 posts of a thread with 3,000-character replies were about 330,000 characters."""
        thread_view = self.fake.thread_view

        def long_replies(uri):
            top = thread_view(uri)
            for reply in top["replies"]:
                reply["post"]["record"]["text"] = "r" * 3000
            return top
        self.fake.thread_view = long_replies
        text = sent(self.module, "get_post_thread", {"uri": "at://did:plc:" + "o" * 24
                                                     + "/app.bsky.feed.post/3kthreadtop22a"})
        self.assertLessEqual(len(text), MAX_ANSWER)
        answer = json.loads(text)
        self.assertTrue(answer["truncated"])
        self.assertEqual(answer["count"], len(answer["thread"]))
        self.assertEqual([row["level"] for row in answer["thread"][:3]], [-2, -1, 0])  # parents and the post stay
        self.assertIn("not shown", answer["cut"])


# --- telegram-user ------------------------------------------------------------------------------------------------

@unittest.skipUnless(installed("mcp", "telethon"), "the server's requirements are not installed "
                                                   "(servers/telegram-user/requirements.txt)")
class TelegramUser(ToolsOnlyCheck, unittest.TestCase):
    server = "telegram-user"

    def setUp(self):
        import test_telegram_user as t  # the fake Telethon client of tests/test_telegram_user.py
        self.t = t
        self.fake = t.FakeClient()
        self.module = t.load({**t.SECRET_ENV, "TELEGRAM_USER_WRITE": "1"})
        self.module._state["client"] = self.fake

    def test_get_messages_fits_and_goes_on_where_it_stopped(self):
        """200 messages of 4,096 characters were about 900,000 characters."""
        t = self.t
        self.fake.messages = [t.message(1000 - i, f"{i} " + "x" * 4090) for i in range(200)]
        for arguments in ({"chat": "@leakchannel", "limit": 200},
                          {"chat": "@leakchannel", "query": "x", "limit": 200}):
            tool = "search_messages" if "query" in arguments else "get_messages"
            with self.subTest(tool):
                text = sent(self.module, tool, arguments)
                self.assertLessEqual(len(text), MAX_ANSWER)
                answer = json.loads(text)
                shown = answer["messages"]
                self.assertTrue(0 < len(shown) < 200)
                self.assertEqual(answer["count"], len(shown))
                self.assertEqual(answer["next_offset_id"], shown[-1]["id"])
                self.assertIn("not shown", answer["truncated"])

    def test_a_message_full_of_hidden_links_still_fits(self):
        """50 hidden links of 2,048 characters made one message about 105,000 characters: a page could not show it
        at all. A message's links are at most 6,000 characters together now, and a page shows one message at least
        (one that showed none would have skipped it with next_offset_id)."""
        from telethon.tl import types
        t = self.t
        text = "link " * 50
        entities = [types.MessageEntityTextUrl(offset=5 * i, length=4, url="https://example.com/" + "u" * 2028)
                    for i in range(50)]
        self.fake.messages = [t.message(900 - i, text, entities=entities) for i in range(3)]
        answer = json.loads(sent(self.module, "get_messages", {"chat": "@leakchannel", "limit": 3}))
        self.assertLessEqual(as_sent(answer), MAX_ANSWER)
        self.assertGreaterEqual(answer["count"], 1)
        links = answer["messages"][0]["links"]
        self.assertTrue(0 < len(links) < 50)
        self.assertLessEqual(sum(len(link["url"]) + len(link.get("text", "")) for link in links), 6000)

    def test_search_global_and_replies_fit(self):
        t = self.t
        self.fake.messages = [t.message(1000 - i, "y" * 4096) for i in range(200)]
        for tool, arguments in (("search_global", {"query": "y", "limit": 200}),
                                ("get_replies", {"chat": "@leakchannel", "message_id": 5, "limit": 200})):
            with self.subTest(tool):
                text = sent(self.module, tool, arguments)
                self.assertLessEqual(len(text), MAX_ANSWER)
                self.assertIn("not shown", json.loads(text)["truncated"])

    def test_sends_are_rate_limited(self):
        clock = [5000.0]
        with mock.patch.object(self.module.time, "monotonic", lambda: clock[0]):
            for index in range(20):
                self.assertIn("sent", sent_dict(self.module, "send_message",
                                                {"chat": "@leakchannel", "text": f"m{index}"}))
            refused = sent_dict(self.module, "send_message", {"chat": "@leakchannel", "text": "one too many"})
            self.assertRegex(refused["error"], r"at most 20 messages a minute.*wait \d+ s")
            clock[0] += 61
            self.assertIn("sent", sent_dict(self.module, "send_message", {"chat": "@leakchannel", "text": "later"}))
        self.assertEqual(len(self.fake.sent), 21)
        self.assertNotIn("one too many", self.fake.sent)


def sent_dict(module, tool: str, arguments: dict) -> dict:
    return json.loads(sent(module, tool, arguments))


# --- signal -------------------------------------------------------------------------------------------------------

@unittest.skipUnless(installed("mcp", "signal_mcp"), "the server's requirements and signal-mcp's modules are not "
                                                     "installed (the image has both)")
class Signal(ToolsOnlyCheck, unittest.TestCase):
    server = "signal"
    env = {"SIGNAL_DATA_DIR": "/nonexistent/signal-data", "SIGNAL_WRITE": ""}

    def setUp(self):
        import test_signal  # noqa: F401 - imports signal-mcp's modules with HOME at its data folder, once per run
        self.module = load("signal", {"SIGNAL_DATA_DIR": test_signal.DATA.name})

    def test_lists_fit_as_sent(self):
        """bounded() measured compact JSON against 128 KiB: 50 messages of 4,000 characters were 213,000 characters
        as sent (FastMCP indents by 2)."""
        m = self.module
        rows = [{"id": str(i), "sender": "+4915100000002", "body": f"{i} " + "b" * 3998, "timestamp": i,
                 "attachments": [], "mentions": []} for i in range(50)]
        for key, from_start in (("messages", True), ("messages", False), ("conversations", False)):
            with self.subTest(key=key, from_start=from_start):
                answer = m.bounded({key: [dict(row) for row in rows], "count": 50, "note": m.UNTRUSTED}, key,
                                   from_start=from_start)
                self.assertLessEqual(as_sent(answer), MAX_ANSWER)
                self.assertTrue(answer["truncated"])
                kept = [row["id"] for row in answer[key]]
                self.assertTrue(0 < len(kept) < 50)
                self.assertEqual(kept, [str(i) for i in range(50 - len(kept), 50)] if from_start
                                 else [str(i) for i in range(len(kept))])
        small = m.bounded({"messages": rows[:2], "count": 2}, "messages")
        self.assertNotIn("truncated", small)


if __name__ == "__main__":
    unittest.main()
