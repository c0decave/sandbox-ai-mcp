"""servers/gitea: Gitea's own MCP server (gitea-mcp v1.13.0) behind our entry point src/main.go - what the image
builds from (the reviewed files by SHA-256, the pinned commit), what it offers (read-only by default, no file writes)
and what its smoke spec proves. The Go side (src/main_test.go) runs in the image's build."""
from __future__ import annotations

import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "servers" / "gitea"


def read_json(name: str):
    return json.loads((SERVER / name).read_text(encoding="utf-8"))


class Gitea(unittest.TestCase):
    def setUp(self):
        self.dockerfile = (SERVER / "Dockerfile").read_text(encoding="utf-8")
        self.main = (SERVER / "src" / "main.go").read_text(encoding="utf-8")
        self.main_test = (SERVER / "src" / "main_test.go").read_text(encoding="utf-8")

    def test_the_build_takes_only_reviewed_files_of_the_pinned_commit(self):
        self.assertRegex(self.dockerfile, r"(?m)^ARG GITEA_MCP_COMMIT=34ba56e9a95d3a59113a293f1263685c3986f37c$")
        self.assertIn('test "$(git -C /src rev-parse HEAD)" = "${GITEA_MCP_COMMIT}"', self.dockerfile)
        # the hashes are checked before go downloads anything (go mod download may add lines to go.sum)
        self.assertLess(self.dockerfile.index("sha256sum --check --strict --quiet /tmp/gitea-mcp-files.sha256"),
                        self.dockerfile.index("go mod download"))
        listed = [line.split("  ", 1)[1] for line in (SERVER / "gitea-mcp-files.sha256").read_text().splitlines()]
        self.assertEqual(listed, sorted(listed))
        self.assertTrue({"go.mod", "go.sum", "LICENSE"} <= set(listed))
        self.assertFalse([path for path in listed if path.startswith(("cmd/", "main.go"))],
                         "upstream's cmd package and main.go are not linked")
        packages = re.search(r"printf '%s\\n' (.*?)\\\n    \| sed", self.dockerfile, re.S).group(1).split()
        packages = [p for p in packages if p != "\\"]
        dirs = {path.rsplit("/", 1)[0] for path in listed if path.endswith(".go")}
        self.assertEqual(dirs, set(packages) - {"cmd/sandbox-ai-mcp"}, "every reviewed package has its files listed")
        self.assertIn("go test -count=1 ./cmd/sandbox-ai-mcp", self.dockerfile)
        self.assertIn("go telemetry off", self.dockerfile)

    def test_the_entry_point_refuses_what_writes_files_or_leaves_its_path(self):
        for method in ("download_job_log", "download_artifact", "download_attachment", "download_asset"):
            self.assertIn(f'"{method}"', self.main)
        self.assertIn('delete(properties, "output_path")', self.main)
        self.assertIn("flagPkg.Insecure = false", self.main)
        self.assertIn('flagPkg.ReadOnly = strings.TrimSpace(getenv("GITEA_WRITE")) != "1"', self.main)
        self.assertRegex(self.main, r"maxAnswer = 24000\b")
        self.assertNotIn("GITEA_INSECURE", self.main.split("package main", 1)[1].replace(
            "upstream's -insecure / GITEA_INSECURE", ""))

    def test_tools_json_is_the_read_only_list_the_go_test_checks(self):
        tools = read_json("tools.json")["tools"]
        self.assertEqual(tools, sorted(tools))
        self.assertEqual(len(tools), 28)
        go_list = re.search(r"var readTools = \[\]string\{(.*?)\}", self.main_test, re.S).group(1)
        self.assertEqual(re.findall(r'"([a-z_]+)"', go_list), tools)
        self.assertFalse([t for t in tools if t.endswith("_write") or t.startswith(("create_", "delete_"))])

    def test_the_entry(self):
        entry = read_json("server.json")
        self.assertEqual((entry["id"], entry["name"], entry["kind"]), ("mcp:gitea", "gitea", "oci"))
        self.assertEqual(entry["image"], "ghcr.io/c0decave/sandbox-ai-mcp-gitea")
        env = {item["name"]: item for item in entry["env"]}
        self.assertTrue(env["GITEA_HOST"]["required"])
        self.assertFalse(env["GITEA_HOST"]["secret"])
        self.assertTrue(env["GITEA_ACCESS_TOKEN"]["secret"])
        self.assertFalse(env["GITEA_WRITE"]["required"])
        self.assertEqual(entry["network"], "full")
        self.assertNotIn("hosts", entry)
        self.assertEqual(entry["tor"]["support"], "limited")
        self.assertIn("--allow-tcp", entry["notes"])
        self.assertLessEqual(len(entry["description"]), 2000)

    def test_the_smoke_spec_calls_every_tool_without_a_gitea(self):
        spec = read_json("smoke.json")
        self.assertEqual((spec["network"], spec["env"]), ("none", {"GITEA_HOST": "http://127.0.0.1:9"}))
        called = {call["tool"] for call in spec["calls"] if not call.get("absent")}
        self.assertEqual(called, set(read_json("tools.json")["tools"]))
        for call in spec["calls"]:
            if call["tool"] != "get_gitea_mcp_server_version":
                self.assertTrue(call.get("expect_error"), call)
        expects = " ".join(call["expect"] for call in spec["calls"])
        for refused in ("download_job_log is not offered", "download_asset is not offered",
                        "output_path is not offered", 'owner ".." is not a name'):
            self.assertIn(refused, expects)
        absent = [call for call in spec["calls"] if call.get("absent")]
        self.assertEqual([call["tool"] for call in absent], ["issue_write"])


if __name__ == "__main__":
    unittest.main()
