"""The tasks server (servers/tasks), offline: a plan kept in /work/.tasks that survives the server (a new process reads
what the old one wrote), the readable PLAN.md beside it, next_step and progress, every bound, a plan changed by hand
refused and left as it is, links and files in the way refused, a read-only workspace, many processes and threads
changing one plan at once without losing a change, and the MCP server over stdio. CI runs this inside the image too
(tests/test_own_servers.py test_tasks)."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "servers" / "tasks" / "src" / "server.py"

try:
    import mcp  # noqa: F401 - the server's own dependency
except ImportError:
    mcp = None


def load(workspace):
    spec = importlib.util.spec_from_file_location("server_tasks_test", SERVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.WORKSPACE = workspace
    module.MOUNT_REQUIRED = False
    return module


@unittest.skipIf(mcp is None, "the server's requirements are not installed (pip install --require-hashes -r "
                              "servers/tasks/requirements.txt)")
class Plan(unittest.TestCase):
    def setUp(self):
        self.work = os.path.realpath(tempfile.mkdtemp(prefix="tasks-test-"))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.module = load(self.work)

    def error(self, call) -> str:
        with self.assertRaises(self.module.ArgumentError) as caught:
            call()
        return str(caught.exception)

    def plan(self) -> dict:
        return json.loads(Path(self.work, ".tasks", "plan.json").read_text())

    def test_no_plan_yet(self):
        m = self.module
        self.assertIn("No plan yet. Call set_goal", m.do_read(m.next_text))
        self.assertIn("No plan yet", m.do_read(m.compact))
        self.assertIn("No plan yet", m.do_read(m.progress_text))
        self.assertFalse(os.path.exists(os.path.join(self.work, ".tasks")), "reading writes nothing")

    def test_a_plan_from_goal_to_done(self):
        m = self.module
        text = m.do_set_goal("CSV export quotes fields with commas; all tests pass", False)
        self.assertIn("Goal set.", text)
        self.assertIn("Next: add_steps", text)
        text = m.do_add_steps(["find where rows are written", "add quoting", "run the tests"], None)
        self.assertIn("Added steps 1, 2, 3.", text)
        self.assertIn("1. [ ] find where rows are written\n2. [ ] add quoting\n3. [ ] run the tests", text)
        self.assertIn("Next step 1: find where rows are written", m.do_read(m.next_text))
        self.assertIn("Call start_step(1) when you begin", m.do_read(m.next_text))
        text = m.change_state(1, "doing", "grep for csv.writer")
        self.assertIn("Step 1 is in progress", text)
        self.assertIn("Continue with step 1", m.do_read(m.next_text))
        self.assertIn("note (", m.do_read(m.next_text))
        m.do_add_note("tests need PYTHONPATH=src", None)
        text = m.change_state(1, "done", "rows are written in export.py write_row")
        self.assertIn("Step 1 done.", text)
        self.assertIn("Next step 2: add quoting", text)
        self.assertIn("Done before: 1. find where rows are written  -- rows are written in export.py write_row", text)
        self.assertIn("After that: 3. run the tests", text)
        self.assertIn("Notes to keep in mind (newest last):\n  - tests need PYTHONPATH=src", text)
        text = m.change_state(2, "blocked", "needs the csv module's quoting rules", note_required=True)
        self.assertIn("Step 2 blocked: needs the csv module's quoting rules", text)
        self.assertIn("Next step 3: run the tests", text)
        self.assertIn("Blocked: 2", text)
        m.change_state(3, "done", "")
        text = m.do_read(m.next_text)
        self.assertIn("Only blocked steps are left:\n  2. add quoting  -- blocked: needs the csv module's quoting rules",
                      text)
        m.change_state(2, "doing", "found them")
        text = m.change_state(2, "done", "QUOTE_MINIMAL")
        self.assertIn("All steps are done. Check that the goal is really met", text)
        text = m.do_read(m.progress_text)
        self.assertIn("Progress: 3 of 3 steps done", text)
        self.assertIn("Done:\n  1. find where rows are written  -- rows are written in export.py write_row", text)

    def test_the_plan_survives_the_server_and_the_human_can_read_it(self):
        m = self.module
        m.do_set_goal("ship 1.0", False)
        m.do_add_steps("1. write the changelog\n- [ ] tag the release\n* publish", None)
        m.change_state(1, "done", "CHANGELOG.md has 1.0")
        again = load(self.work)
        self.assertIn("Next step 2: tag the release", again.do_read(again.next_text))
        self.assertIn("Done before: 1. write the changelog  -- CHANGELOG.md has 1.0", again.do_read(again.next_text))
        view = Path(self.work, ".tasks", "PLAN.md").read_text()
        self.assertIn("**Goal:** ship 1.0", view)
        self.assertIn("- [x] 1. write the changelog\n  - ", view)
        self.assertIn("- [ ] 3. publish", view)
        self.assertIn("changes here are overwritten", view)
        self.assertEqual(sorted(os.listdir(os.path.join(self.work, ".tasks"))), [".lock", "PLAN.md", "plan.json"],
                         "no temporary file is left")
        self.assertEqual([s["state"] for s in self.plan()["steps"]], ["done", "todo", "todo"])

    def test_steps_inserted_removed_and_numbered_for_good(self):
        m = self.module
        m.do_add_steps(["a", "b", "c"], None)
        text = m.do_add_steps(["a2"], 1)
        self.assertIn("Added step 4.", text)
        self.assertIn("1. [ ] a\n4. [ ] a2\n2. [ ] b", text)
        m.do_add_steps(["first"], 0)
        self.assertEqual([s["text"] for s in self.plan()["steps"]], ["first", "a", "a2", "b", "c"])
        self.assertIn("Step 2 removed: b", m.do_remove_step(2))
        m.do_add_steps(["d"], None)
        self.assertEqual([s["id"] for s in self.plan()["steps"]], [5, 1, 4, 3, 6], "a number is never given twice")
        self.assertIn("there is no step 2 (steps: 5, 1, 4, 3, 6;", self.error(lambda: m.change_state(2, "done", "")))
        self.assertIn("step: the step's number", self.error(lambda: m.change_state("2", "done", "")))

    def test_a_new_goal_keeps_or_clears_the_steps(self):
        m = self.module
        m.do_set_goal("old goal", False)
        m.do_add_steps(["x"], None)
        m.do_set_goal("new goal", False)
        self.assertEqual(len(self.plan()["steps"]), 1)
        self.assertIn("Goal changed from: old goal", self.plan()["notes"][-1]["text"])
        self.assertIn("1 old steps removed.", m.do_set_goal("newer goal", True))
        self.assertEqual(self.plan()["steps"], [])

    def test_bounds(self):
        m = self.module
        self.assertIn("goal: must not be empty", self.error(lambda: m.do_set_goal("  ", False)))
        self.assertIn("goal: at most 2000 characters", self.error(lambda: m.do_set_goal("g" * 2001, False)))
        self.assertIn("steps: at most 500 characters", self.error(lambda: m.do_add_steps(["s" * 501], None)))
        self.assertIn("steps: at most 50 in one call", self.error(lambda: m.do_add_steps(["s"] * 51, None)))
        self.assertIn("steps: give at least one step", self.error(lambda: m.do_add_steps(["", " "], None)))
        self.assertIn("steps: a list of short texts", self.error(lambda: m.do_add_steps(7, None)))
        for _ in range(4):
            m.do_add_steps(["s"] * 50, None)
        self.assertIn("more than 200 steps", self.error(lambda: m.do_add_steps(["s"], None)))
        self.assertIn("text: at most 1000 characters", self.error(lambda: m.do_add_note("n" * 1001, None)))
        self.assertIn("reason: must not be empty",
                      self.error(lambda: m.change_state(1, "blocked", "", note_required=True)))
        for index in range(m.MAX_STEP_NOTES + 3):
            m.do_add_note(f"step note {index}", 1)
        notes = self.plan()["steps"][0]["notes"]
        self.assertEqual(len(notes), m.MAX_STEP_NOTES)
        self.assertEqual(notes[-1]["text"], f"step note {m.MAX_STEP_NOTES + 2}")
        for index in range(m.MAX_NOTES + 5):
            m.do_add_note(f"note {index}", None)
        plan = self.plan()
        self.assertEqual((len(plan["notes"]), plan["dropped_notes"]), (m.MAX_NOTES, 5))
        self.assertEqual(plan["notes"][0]["text"], "note 5")
        self.assertIn("(5 older notes were dropped)", Path(self.work, ".tasks", "PLAN.md").read_text())
        self.assertEqual(m.checked_text("a\x07b", "x", 10), "ab")

    def test_a_plan_changed_by_hand_is_refused_and_kept(self):
        m = self.module
        m.do_add_steps(["a"], None)
        path = Path(self.work, ".tasks", "plan.json")
        for broken in ("{not json", json.dumps({"version": 2}), json.dumps({"version": 1, "steps": [{"id": 1}]}),
                       json.dumps({"version": 1, "steps": [{"id": 1, "state": "todo"}, {"id": 1, "state": "todo"}]})):
            with self.subTest(plan=broken):
                path.write_text(broken)
                self.assertIn("is not a plan this server can read", self.error(lambda: m.do_add_steps(["b"], None)))
                self.assertIn("move it away to start a new plan", self.error(lambda: m.do_read(m.next_text)))
                self.assertEqual(path.read_text(), broken, "never overwritten")
        path.write_text(json.dumps({"version": 1, "goal": "by hand", "steps": [{"id": 3, "state": "todo",
                                                                               "text": "hand-made"}]}))
        self.assertIn("Added step 4.", m.do_add_steps(["b"], None))

    def test_links_and_files_in_the_way_are_refused(self):
        m = self.module
        outside = tempfile.mkdtemp(prefix="tasks-outside-")
        self.addCleanup(shutil.rmtree, outside, True)
        os.symlink(outside, os.path.join(self.work, ".tasks"))
        self.assertIn(".tasks is not a folder (a file or a symbolic link?)",
                      self.error(lambda: m.do_set_goal("g", False)))
        self.assertEqual(os.listdir(outside), [])
        os.unlink(os.path.join(self.work, ".tasks"))
        Path(self.work, ".tasks").write_text("a file")
        self.assertIn(".tasks is not a folder", self.error(lambda: m.do_set_goal("g", False)))
        os.unlink(os.path.join(self.work, ".tasks"))
        os.mkdir(os.path.join(self.work, ".tasks"))
        Path(outside, "plan.json").write_text(json.dumps({"version": 1, "goal": "elsewhere"}))
        os.symlink(os.path.join(outside, "plan.json"), os.path.join(self.work, ".tasks", "plan.json"))
        self.assertIn("plan.json cannot be read (a symbolic link?)", self.error(lambda: m.do_read(m.next_text)))
        self.assertIn("plan.json cannot be read", self.error(lambda: m.do_set_goal("g", False)))

    def test_a_workspace_that_cannot_be_written(self):
        os.chmod(self.work, 0o555)
        self.addCleanup(os.chmod, self.work, 0o755)
        if os.access(self.work, os.W_OK):
            self.skipTest("this user writes into a read-only folder anyway (root with CAP_DAC_OVERRIDE)")
        m = self.module
        self.assertIn("mount the project writable", self.error(lambda: m.do_set_goal("g", False)))
        self.assertIn("No plan yet", m.do_read(m.next_text))

    def test_a_workspace_that_is_not_mounted_is_named(self):
        self.module.MOUNT_REQUIRED = True
        self.assertIn(f"no folder is mounted at {self.work}: add the server with --mount",
                      self.error(lambda: self.module.do_read(self.module.next_text)))

    def test_many_processes_and_threads_change_one_plan(self):
        script = ("import importlib.util, sys\n"
                  "spec = importlib.util.spec_from_file_location('t', sys.argv[1])\n"
                  "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
                  "m.WORKSPACE = sys.argv[2]; m.MOUNT_REQUIRED = False\n"
                  "for i in range(8):\n"
                  "    m.do_add_steps([f'{sys.argv[3]}-{i}'], None)\n"
                  "    m.do_add_note(f'{sys.argv[3]} note {i}', None)\n")
        processes = [subprocess.Popen([sys.executable, "-I", "-c", script, str(SERVER), self.work, f"p{n}"])
                     for n in range(6)]
        errors = []

        def thread_work(name):
            try:
                for i in range(8):
                    self.module.do_add_steps([f"{name}-{i}"], None)
            except Exception as error:  # noqa: BLE001 - reported below
                errors.append(error)

        threads = [threading.Thread(target=thread_work, args=(f"t{n}",)) for n in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(120)
        for process in processes:
            self.assertEqual(process.wait(120), 0)
        self.assertEqual(errors, [])
        plan = self.plan()
        expected = [f"p{n}-{i}" for n in range(6) for i in range(8)] + [f"t{n}-{i}" for n in range(4) for i in range(8)]
        self.assertEqual(sorted(step["text"] for step in plan["steps"]), sorted(expected))
        self.assertEqual(sorted(step["id"] for step in plan["steps"]), list(range(1, 81)))
        self.assertEqual(len(plan["notes"]), 48)
        self.assertEqual(sorted(os.listdir(os.path.join(self.work, ".tasks"))), [".lock", "PLAN.md", "plan.json"])


@unittest.skipIf(mcp is None, "the server's requirements are not installed")
class OverStdio(unittest.TestCase):
    def rpc(self, calls, workspace):
        launcher = ("import importlib.util, sys\n"
                    "spec = importlib.util.spec_from_file_location('server', sys.argv[1])\n"
                    "module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)\n"
                    "module.WORKSPACE = sys.argv[2]; module.MOUNT_REQUIRED = False\n"
                    "module.mcp.run('stdio')\n")
        messages = [{"jsonrpc": "2.0", "id": 0, "method": "initialize",
                     "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                "clientInfo": {"name": "test", "version": "1"}}},
                    {"jsonrpc": "2.0", "method": "notifications/initialized"},
                    {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}]
        messages += [{"jsonrpc": "2.0", "id": index, "method": "tools/call", "params": {"name": tool, "arguments": args}}
                     for index, (tool, args) in enumerate(calls, start=2)]
        process = subprocess.Popen([sys.executable, "-I", "-c", launcher, str(SERVER), workspace],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        answers = {}
        try:
            for message in messages:
                process.stdin.write(json.dumps(message) + "\n")
                process.stdin.flush()
                if "id" not in message:
                    continue
                while message["id"] not in answers:
                    line = process.stdout.readline()
                    if not line:
                        raise AssertionError("the server ended without answering")
                    answer = json.loads(line)
                    if "id" in answer:
                        answers[answer["id"]] = answer
        finally:
            process.stdin.close()
            process.wait(60)
            process.stdout.close()
        return answers

    def test_tools_and_a_session(self):
        work = os.path.realpath(tempfile.mkdtemp(prefix="tasks-stdio-"))
        self.addCleanup(shutil.rmtree, work, True)
        answers = self.rpc([("set_goal", {"goal": "the parser accepts empty lines"}),
                            ("add_steps", {"steps": ["write a failing test", "fix the parser"]}),
                            ("add_steps", {"steps": "1. run all tests\n2. tell the user"}),
                            ("start_step", {"step": 1}),
                            ("complete_step", {"step": 1, "note": "test_empty_lines fails as expected"}),
                            ("block_step", {"step": 2}),
                            ("complete_step", {"step": 99}),
                            ("next_step", {}),
                            ("progress", {}),
                            ("list_steps", {})], work)
        tools = answers[1]["result"]["tools"]
        recorded = json.loads((ROOT / "servers" / "tasks" / "tools.json").read_text())
        self.assertEqual(sorted(t["name"] for t in tools), recorded["tools"])
        for tool in tools:
            self.assertLess(len(tool["description"]), 700, tool["name"])
            self.assertEqual(tool["annotations"]["readOnlyHint"], tool["name"] not in recorded["write_tools"])
            self.assertNotIn("outputSchema", tool)
        self.assertIn("next_step", answers[0]["result"]["instructions"])

        def text(index):
            return answers[index]["result"]["content"][0]["text"]

        self.assertIn("Goal set.", text(2))
        self.assertIn("Added steps 3, 4.", text(4))
        self.assertIn("3. [ ] run all tests\n4. [ ] tell the user", text(4))
        self.assertIn("Step 1 is in progress", text(5))
        self.assertIn("Next step 2: fix the parser", text(6))
        self.assertTrue(answers[7]["result"]["isError"])  # block_step needs its reason
        self.assertIn("reason", text(7))
        self.assertTrue(answers[8]["result"]["isError"])
        self.assertIn("there is no step 99", text(8))
        self.assertIn("Next step 2: fix the parser", text(9))
        self.assertIn("Done:\n  1. write a failing test  -- test_empty_lines fails as expected", text(10))
        self.assertIn("Progress: 1 of 4 steps done", text(11))
        self.assertTrue(Path(work, ".tasks", "PLAN.md").is_file())


if __name__ == "__main__":
    unittest.main()
