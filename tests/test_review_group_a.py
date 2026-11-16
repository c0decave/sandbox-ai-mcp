"""Found by the in-depth review of 2026-11-17 (group A: binwalk, capa, radare2, gowitness, whatweb, exec, code-search,
files, filesystem); each test failed before its fix.

- Every server of this repository written in Python announced the MCP capabilities "resources" (and FastMCP's also
  "prompts") and published none (binwalk and capa only their past scans, which get_scan_results and
  get_analysis_results give as well). Agents act on the capability: OpenCode, Claude Code and Pi offer the model
  resource tools for it, Hermes four more tools per server, and local models take them for the way to the server's
  tools (research-llm round 1, "the MCP-resource trap"). They announce tools only now.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent

try:
    import mcp  # noqa: F401 - the servers' own dependency
except ImportError:
    mcp = None

#: The servers of group A that run on the shared Python lock (radare2 is C, filesystem Node.js).
PYTHON_SERVERS = ("binwalk", "capa", "gowitness", "whatweb", "exec", "code-search", "files")


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"review_a_{name.replace('-', '_')}",
                                                  ROOT / "servers" / name / "src/server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rpc(name: str, messages: list[dict], env: dict | None = None) -> dict:
    """The answers (by id) of the server NAME, started as its image starts it (python -I -u server.py), to MESSAGES."""
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


@unittest.skipIf(mcp is None, "the servers' requirements are not installed (pip install --require-hashes -r "
                              "servers/files/requirements.txt)")
class ToolsOnly(unittest.TestCase):
    def test_the_servers_announce_tools_only(self):
        for name in PYTHON_SERVERS:
            with self.subTest(name):
                answers = rpc(name, handshake(("tools/list", {}), ("resources/list", {}), ("prompts/list", {})),
                              env={"MCP_INPUT_ROOTS": str(ROOT)})
                capabilities = answers[0]["result"]["capabilities"]
                self.assertNotIn("resources", capabilities)
                self.assertNotIn("prompts", capabilities)
                self.assertIn("tools", capabilities)
                self.assertTrue(answers[1]["result"]["tools"])
                for request in (2, 3):  # a client that asks anyway: the method does not exist
                    self.assertEqual(answers[request]["error"]["code"], -32601, answers[request])


if __name__ == "__main__":
    unittest.main()
