"""servers/lsp-*: our own MCP bridge to a language server (src/server.py, the same file in every lsp-* image) - over
stdio against a stand-in language server (tests/fixtures/fake_lsp.py): tools only, the six read-only tools, positions
(1-based characters <-> LSP's UTF-16), symbol names as positions, files only inside the project (symbolic links
resolved), the two diagnostics publications, bounded answers, and that nothing but reading is ever asked of the
language server. The real language servers (pyright, gopls) are in the images' smoke specs."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
LSP_SERVERS = ("lsp-go", "lsp-python")
FAKE = ROOT / "tests" / "fixtures" / "fake_lsp.py"
TOOLS = ["definition", "diagnostics", "document_symbols", "hover", "references", "workspace_symbols"]

try:
    import mcp  # noqa: F401
except ImportError:  # the server's requirements are not installed
    mcp = None
if mcp is not None:
    from test_own_servers import rpc, session


def answer(message):
    return json.loads(message["result"]["content"][0]["text"])


class Shared(unittest.TestCase):
    def test_every_lsp_image_has_the_same_bridge(self):
        texts = {name: (ROOT / "servers" / name / "src" / "server.py").read_text() for name in LSP_SERVERS}
        self.assertEqual(len(set(texts.values())), 1, "servers/lsp-*/src/server.py differ")
        for name in LSP_SERVERS:
            folder = ROOT / "servers" / name
            self.assertEqual(json.loads((folder / "tools.json").read_text())["tools"], TOOLS)
            self.assertEqual((folder / "requirements.txt").read_text(),
                             (ROOT / "servers" / "osv" / "requirements.txt").read_text(),
                             "the MCP SDK lock of servers/osv, reviewed there")
            entry = json.loads((folder / "server.json").read_text())
            self.assertEqual(entry["network"], "none")
            self.assertEqual([m["target"] for m in entry["mounts"] if m.get("required")], ["/work"])
            language = name.split("-", 1)[1]
            dockerfile = (folder / "Dockerfile").read_text()
            self.assertIn(f'"/opt/mcp/server.py", "{language}"]', dockerfile)

    def test_the_bridge_asks_only_for_reading(self):
        text = (ROOT / "servers" / "lsp-python" / "src" / "server.py").read_text()
        methods = set(__import__("re").findall(r'"((?:textDocument|workspace)/[A-Za-z]+)"', text))
        self.assertEqual(methods, {"textDocument/definition", "textDocument/references", "textDocument/hover",
                                   "textDocument/documentSymbol", "workspace/symbol", "textDocument/didOpen",
                                   "textDocument/didChange", "textDocument/publishDiagnostics",
                                   "workspace/configuration", "workspace/workspaceFolders"})


@unittest.skipIf(mcp is None, "the servers' requirements are not installed (servers/lsp-python/requirements.txt)")
class Bridge(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.mount = Path(self.folder.name) / "work"
        (self.mount / "pkg").mkdir(parents=True)
        (self.mount / "a.py").write_text("x = 1\nprint(x)  # BUG here\n\nd = {'ä😀': 1}; y = d\n")
        (self.mount / "pkg" / "b.py").write_text("class Thing:\n    def run(self):\n        pass\n")
        (self.mount / "notes.txt").write_text("not python\n")
        (self.mount / "escape.py").symlink_to("/etc/hostname")
        self.log = Path(self.folder.name) / "lsp.log"
        self.env = {"LSP_MOUNT": str(self.mount), "LSP_NODE": sys.executable, "LSP_PYRIGHT": str(FAKE),
                    "FAKE_LSP_LOG": str(self.log), "LSP_DIAGNOSTICS_WAIT": "5"}

    def call(self, *calls, env=None):
        answers = rpc("lsp-python", session(*calls), env={**self.env, **(env or {})})
        return answers, [answer(answers[i]) for i in range(2, 2 + len(calls))]

    def run_bridge(self, *calls, env=None):
        # src/server.py takes its language as its argument: the shared helper runs it without one (python)
        return self.call(*calls, env=env)

    def test_tools_only_and_the_six_tools(self):
        answers = rpc("lsp-python", session() + [{"jsonrpc": "2.0", "id": 9, "method": "resources/list"},
                                                  {"jsonrpc": "2.0", "id": 10, "method": "prompts/list"}],
                      env=self.env)
        self.assertEqual(sorted(answers[0]["result"]["capabilities"]), ["experimental", "tools"])
        self.assertEqual(sorted(t["name"] for t in answers[1]["result"]["tools"]), TOOLS)
        self.assertIn("error", answers[9])
        self.assertIn("error", answers[10])

    def test_positions_symbols_and_locations(self):
        _, found = self.run_bridge(
            ("definition", {"file": "a.py", "line": 2, "symbol": "x"}),
            ("hover", {"file": "a.py", "line": 4, "symbol": "y"}),
            ("definition", {"file": "a.py", "line": 4, "column": 18}),
            ("references", {"file": "pkg/b.py", "line": 1, "symbol": "Thing"}),
            ("document_symbols", {"file": "pkg/b.py"}),
            ("workspace_symbols", {"query": "total"}))
        self.assertEqual(found[0]["locations"][0], {"file": "a.py", "line": 1, "column": 6, "text": "x = 1"})
        self.assertEqual(found[0]["locations"][1], {"file": "/usr/lib/python3/os.py", "line": 10, "column": 5},
                         "a location outside the project: no text of it")
        # "y" is the 16th character of line 4; the emoji before it is two UTF-16 units: LSP gets 16, not 15
        self.assertEqual(found[1]["hover"], "fake hover at character 16")
        self.assertEqual(found[2]["locations"][0]["column"], 6, "past the end of the line it lands in: its end")
        self.assertEqual((found[3]["count"], len(found[3]["locations"])), (151, 100))
        self.assertIn("51 more", found[3]["more"])
        self.assertEqual(found[4]["symbols"], [{"name": "Thing", "kind": "class", "line": 1},
                                              {"name": "run", "kind": "method", "line": 2, "in": "Thing"}])
        self.assertEqual(found[5]["symbols"], [{"name": "total", "kind": "function", "file": "a.py", "line": 5,
                                                "in": "mod"}], "the project's symbols only")
        methods = set(self.log.read_text().split())
        self.assertLessEqual(methods, {"initialize", "initialized", "textDocument/didOpen", "textDocument/definition",
                                       "textDocument/hover", "textDocument/references",
                                       "textDocument/documentSymbol", "workspace/symbol"})

    def test_diagnostics_wait_for_the_last_publication(self):
        _, found = self.run_bridge(("diagnostics", {"file": "a.py"}))
        self.assertEqual(found[0]["diagnostics"], [{"line": 2, "column": 13, "severity": "error",
                                                    "message": "a bug in line 2", "source": "fake", "code": "bug"}])

    def test_files_only_inside_the_project(self):
        _, found = self.run_bridge(
            ("definition", {"file": "../outside.py", "line": 1, "column": 1}),
            ("definition", {"file": "/etc/passwd", "line": 1, "column": 1}),
            ("definition", {"file": "escape.py", "line": 1, "column": 1}),
            ("hover", {"file": "notes.txt", "line": 1, "column": 1}),
            ("hover", {"file": "missing.py", "line": 1, "column": 1}),
            ("hover", {"file": "a.py", "line": 0, "column": 1}),
            ("hover", {"file": "a.py", "line": 1, "column": 99}),
            ("hover", {"file": "a.py", "line": 1, "symbol": "nothere"}),
            ("workspace_symbols", {"query": "a\nb"}))
        self.assertIn("outside the project", found[0]["error"])
        self.assertIn("outside the project", found[1]["error"])
        self.assertIn("outside the project", found[2]["error"], "a symbolic link is resolved first")
        self.assertIn("reads .py, .pyi files", found[3]["error"])
        self.assertIn("is not a file of the project", found[4]["error"])
        self.assertIn("line: 1 to 5", found[5]["error"])
        self.assertIn("column: 1 to 6", found[6]["error"])
        self.assertIn("is not in line 1", found[7]["error"])
        self.assertIn("query:", found[8]["error"])

    def test_lsp_root_narrows_the_project_and_stays_below_the_mount(self):
        _, found = self.run_bridge(("document_symbols", {"file": "b.py"}), env={"LSP_ROOT": "pkg"})
        self.assertEqual(found[0]["file"], "b.py")
        _, found = self.run_bridge(("document_symbols", {"file": "b.py"}), env={"LSP_ROOT": "/etc"})
        self.assertIn("is not at or below", found[0]["error"])

    def test_bounded(self):
        module = __import__("importlib").util
        spec = module.spec_from_file_location("lsp_bridge", ROOT / "servers" / "lsp-python" / "src" / "server.py")
        bridge = module.module_from_spec(spec)
        argv, sys.argv = sys.argv, ["server.py", "python"]
        try:
            spec.loader.exec_module(bridge)
        finally:
            sys.argv = argv
        big = bridge.bounded({"locations": [{"file": "f" * 100, "line": i} for i in range(2000)]})
        self.assertLessEqual(len(json.dumps(big, indent=2)), bridge.MAX_ANSWER)
        self.assertIn("cut", big)
        self.assertEqual(bridge.column_to_lsp("a😀b", 3), 3)
        self.assertEqual(bridge.lsp_to_column("a😀b", 3), 3)


if __name__ == "__main__":
    unittest.main()
