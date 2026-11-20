"""servers/axross without its packages: the pin (tag, commit, wheel hash), the reviewed-files manifest against the
entry point's REVIEWED, the catalog entry, the recorded tools, the smoke spec and the Dockerfile's steps. What it does
when it runs is tests/test_own_servers.py's Axross (inside the image, or with servers/axross/requirements.txt)."""
import ast
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parent.parent
HERE = ROOT / "servers" / "axross"
#: The PyPI wheel of the tag v0.15.180 (commit 079769632443724b24bcf9aa3f288edbc456b9e5), byte for byte its src/.
WHEEL_SHA256 = "ab2f9b2fd8cfcfbe1f5ba5aa94267e357886c5f577d5c786f2709f9e758a3c7f"
#: What the lock may hold (paramiko and keyring with their own dependencies, axross's jsonschema and PySocks).
LOCKED = {"attrs", "axross-headless-mcp", "bcrypt", "cffi", "cryptography", "invoke", "jaraco-classes",
          "jaraco-context", "jaraco-functools", "jeepney", "jsonschema", "jsonschema-specifications", "keyring",
          "more-itertools", "paramiko", "pycparser", "pynacl", "pysocks", "pywin32-ctypes", "referencing", "rpds-py",
          "secretstorage"}


def reviewed_of_server():
    """REVIEWED of src/server.py, read from its source (nothing imported)."""
    tree = ast.parse((HERE / "src/server.py").read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "REVIEWED":
            return set(node.value.args[0].func.value.value.split())
    raise AssertionError("src/server.py has no REVIEWED")


def manifest():
    """{path: sha256} of reviewed.sha256."""
    rows = {}
    for line in (HERE / "reviewed.sha256").read_text().splitlines():
        digest, path = line.split("  ", 1)
        rows[path] = digest
    return rows


class Axross(unittest.TestCase):

    def test_the_pin_is_the_tags_wheel(self):
        self.assertEqual((HERE / "requirements.in").read_text(), "axross-headless-mcp==0.15.180\n")
        lock = (HERE / "requirements.txt").read_text()
        block = re.search(r"^axross-headless-mcp==0\.15\.180 \\\n((?:    --hash=sha256:[0-9a-f]{64}.*\n)+)", lock, re.M)
        self.assertIsNotNone(block)
        self.assertIn(WHEEL_SHA256, block.group(1))
        names = set(re.findall(r"^([a-z0-9][a-z0-9._-]*)==", lock, re.M))
        self.assertEqual(names, LOCKED)
        for name in names:
            self.assertRegex(lock, rf"(?m)^{re.escape(name)}==[^ ]+.*\\\n    --hash=sha256:[0-9a-f]{{64}}")
        provenance = (HERE / "PROVENANCE.md").read_text()
        for fact in ("v0.15.180", "079769632443724b24bcf9aa3f288edbc456b9e5", WHEEL_SHA256):
            self.assertIn(fact, provenance)

    def test_the_manifest_is_what_the_entry_point_lets_import(self):
        rows = manifest()
        self.assertEqual(len(rows), 65)
        modules = set()
        for path, digest in rows.items():
            self.assertRegex(digest, r"^[0-9a-f]{64}$")
            self.assertTrue(path.startswith("axross_headless_mcp/") and path.endswith(".py"), path)
            parts = path.split("/")
            if parts[:2] == ["axross_headless_mcp", "_ax"] and len(parts) > 3:
                modules.add(".".join(parts[2:]).removesuffix(".py").removesuffix(".__init__"))
        self.assertEqual(modules, reviewed_of_server())
        # what no review covered and the image must not hold: other backends, scripts, the agent, HTTP, updates
        for name in ("core.scripting", "core.agent", "core.mcp_http", "core.self_update", "core.cred_attack",
                     "core.smb_client", "core.reverse_serve", "core.mcp_client", "core.archive"):
            self.assertNotIn(name, modules)
        self.assertFalse([p for p in rows if "/resources/" in p or p.endswith("__main__.py")
                          and p != "axross_headless_mcp/__main__.py"])

    def test_the_recorded_tools(self):
        tools = json.loads((HERE / "tools.json").read_text())
        self.assertEqual(tools["tools"], sorted(tools["read_only_tools"] + list(tools["write_tools"])))
        self.assertEqual(sorted(tools["write_tools"]), ["bulk_copy", "chmod", "copy", "hardlink", "mkdir", "remove",
                                                        "rename", "symlink", "write_file"])
        for text in tools["write_tools"].values():
            self.assertTrue(text.startswith("WRITES: "), text)
        self.assertIn("remote_open", tools["read_only_tools"])

    def test_the_catalog_entry(self):
        entry = json.loads((HERE / "server.json").read_text())
        self.assertEqual((entry["name"], entry["network"], entry["kind"]), ("axross", "none", "oci"))
        self.assertEqual([m["target"] for m in entry["mounts"]], ["/work", "/axross", "/ssh"])
        self.assertFalse(any(m.get("required") for m in entry["mounts"]))
        env = {v["name"]: v for v in entry["env"]}
        self.assertEqual(sorted(env), ["AXROSS_MCP_REMOTE_TIMEOUT", "AXROSS_PASSWORDS", "AXROSS_WRITE"])
        self.assertTrue(env["AXROSS_PASSWORDS"]["secret"])
        self.assertFalse(env["AXROSS_WRITE"]["secret"])
        self.assertNotIn("digest", entry)
        for word in ("--allow-tcp", "--network full", "never from a prompt", "production"):
            self.assertIn(word, entry["notes"])
        catalog = json.loads((ROOT / "catalog.json").read_text())
        self.assertIn("axross", catalog["pending"])

    def test_the_smoke_spec(self):
        spec = json.loads((HERE / "smoke.json").read_text())
        tools = json.loads((HERE / "tools.json").read_text())["tools"]
        self.assertLessEqual(set(spec["expect_tools"]), set(tools))
        self.assertEqual((spec["memory"], spec["pids"], spec["tmp"], spec["network"]), ("1g", 256, "256m", "none"))
        refused = [c for c in spec["calls"] if c.get("expect_error")]
        self.assertGreaterEqual(len(refused), 6)
        self.assertEqual({c["arguments"].get("path") for c in refused if c["tool"] == "read_file"},
                         {"../etc/passwd", "escape/passwd", "docs/.env"})
        self.assertLessEqual(len(spec["calls"]), 30, "the server allows 30 calls at once, then one a second")

    def test_the_dockerfile(self):
        text = (HERE / "Dockerfile").read_text()
        for step in ("--require-hashes", "--only-binary=:all:", "pip uninstall -y -q invoke secretstorage jeepney",
                     "pip uninstall -y -q pip", "sha256sum --check --quiet --strict /opt/mcp/reviewed.sha256",
                     "comm -23 /tmp/all /tmp/keep", "cmp -s - /tmp/keep", "USER 10001:10001",
                     'ENTRYPOINT ["/opt/venv/bin/python", "-I", "-u", "/opt/mcp/server.py"]',
                     "mkdir -m 0755 /work /axross /ssh"):
            self.assertIn(step, text)
        self.assertRegex(text, r"debian:trixie-slim@sha256:[0-9a-f]{64}")


if __name__ == "__main__":
    unittest.main()
