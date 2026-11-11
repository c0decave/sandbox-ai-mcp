"""The file-analysis servers (radare2, capa, binwalk) and what every server of this repository must
look like: no network, input read-only, pinned images and sources, a smoke spec that calls the tool
with a fixture whose SHA-256 is pinned - and, with SANDBOX_AI_CHECKOUT, that sandbox-ai's own reader
makes of each entry exactly what the catalog says."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
#: Servers that analyse a file the user holds: no network, input mounted read-only.
FILE_ANALYSIS = ("binwalk", "capa", "radare2")


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fixtures = load("fixtures")
make_catalog = load("make_catalog")


def servers() -> list[str]:
    return sorted(path.parent.name for path in (ROOT / "servers").glob("*/server.json"))


def read_json(*parts: str):
    return json.loads(Path(ROOT, *parts).read_text(encoding="utf-8"))


class Fixtures(unittest.TestCase):
    def test_the_binary_fixtures_match_their_pinned_sha256(self):
        found = fixtures.load()
        self.assertEqual(sorted(f["path"] for f in found), ["caps", "firmware.bin", "hello"])
        for fixture in found:
            self.assertLess(fixture["size"], 1 << 20, f"{fixture['path']} should stay a small fixture")

    def test_a_changed_fixture_is_refused(self):
        document = read_json("tests/fixtures/analysis-files.json")
        document["files"][0]["sha256"] = "0" * 64
        with tempfile.TemporaryDirectory() as folder:
            spec = Path(folder, "analysis-files.json")
            spec.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(fixtures.FixtureProblem):
                fixtures.load(spec)
            self.assertEqual(fixtures.main(["--spec", str(spec), "--check"]), 1)
            self.assertEqual(list(Path(folder).iterdir()), [spec], "nothing is written when a pin fails")

    def test_the_fixtures_are_written_without_an_executable_bit(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(fixtures.main(["--out", folder]), 0)
            for path in Path(folder).iterdir():
                self.assertFalse(path.stat().st_mode & 0o111, f"{path.name} is analysed, never executed")


class EveryServer(unittest.TestCase):
    def test_the_folders_are_complete(self):
        for name in servers():
            with self.subTest(server=name):
                folder = ROOT / "servers" / name
                for required in ("Dockerfile", "server.json", "smoke.json", "tools.json", "PROVENANCE.md"):
                    self.assertTrue((folder / required).is_file(), f"{name}: {required} is missing")
                self.assertTrue(any((folder / "LICENSES").glob("*")), f"{name}: LICENSES/ is empty")

    def test_the_base_image_is_pinned_by_digest(self):
        for name in servers():
            with self.subTest(server=name):
                text = (ROOT / "servers" / name / "Dockerfile").read_text()
                images = re.findall(r"^\s*(?:ARG\s+\w*IMAGE=|FROM\s+)(\S+)", text, re.M)
                named = [image for image in images if not image.startswith("${")]
                self.assertTrue(named, f"{name}: no base image")
                for image in named:
                    self.assertRegex(image, r"@sha256:[0-9a-f]{64}$",
                                     f"{name}: {image} is not pinned by digest")
                # Sources fetched during the build are pinned by commit, never by tag or branch.
                for value in re.findall(r"^\s*ARG\s+\w*(?:COMMIT|REF)=(\S+)", text, re.M):
                    self.assertRegex(value, r"^[0-9a-f]{40}$", f"{name}: {value} is not a commit ID")
                self.assertNotRegex(text, r"git (?:clone|checkout) .*(?:--branch|-b) ",
                                    f"{name}: a branch is not a pin")

    def test_the_final_stage_pins_its_debian_packages_and_runs_as_a_user(self):
        for name in servers():
            with self.subTest(server=name):
                text = (ROOT / "servers" / name / "Dockerfile").read_text()
                final = text[[m.start() for m in re.finditer(r"^FROM ", text, re.M)][-1]:]
                for install in re.findall(r"apt-get install[^\n]*(?:\\\n[^\n]*)*", final):
                    for package in re.findall(r"(?<![-\w])([a-z][a-z0-9.+-]{1,40})(?==\S)|"
                                              r"(?<![-\w=/])([a-z][a-z0-9.+]{2,40})(?=[\s\\])", install):
                        unpinned = package[1]
                        if unpinned and unpinned not in ("apt", "get", "install", "y", "no", "true"):
                            self.fail(f"{name}: the final image installs {unpinned} without a version")
                self.assertRegex(final, r"(?m)^USER 10001:10001$", msg=f"{name}: the server must not run as root")

    def test_the_smoke_spec_calls_the_tools_the_server_offers(self):
        for name in servers():
            with self.subTest(server=name):
                spec = read_json("servers", name, "smoke.json")
                tools = read_json("servers", name, "tools.json")["tools"]
                self.assertEqual(spec["name"], name)
                self.assertTrue(spec.get("calls"), f"{name}: the smoke spec must call the tool "
                                                   "(sign_catalog.py refuses a run without a call)")
                for tool in spec.get("expect_tools", []) + [c["tool"] for c in spec.get("calls", [])]:
                    self.assertIn(tool, tools, f"{name}: {tool} is not in tools.json")

    def test_the_smoke_spec_mounts_only_folders_the_entry_declares(self):
        for name in servers():
            with self.subTest(server=name):
                spec = read_json("servers", name, "smoke.json")
                entry = read_json("servers", name, "server.json")
                declared = {mount["target"]: mount for mount in entry.get("mounts", [])}
                for mount in spec.get("mounts", []):
                    self.assertIn(mount["target"], declared,
                                  f"{name}: the smoke mounts {mount['target']}, the entry does not offer it")
                    if mount.get("writable"):
                        self.assertNotEqual(mount["target"], "/work",
                                            f"{name}: input is mounted read-only")
                for target, mount in declared.items():
                    if mount.get("required"):
                        self.assertIn(target, [m["target"] for m in spec.get("mounts", [])],
                                      f"{name}: the entry requires {target}, the smoke does not mount it")

    def test_the_smoke_spec_uses_the_files_the_fixtures_give(self):
        available = {f["path"] for f in fixtures.load()} | {
            path.name for path in (ROOT / "tests/fixtures").glob("*") if path.is_file()}
        for name in servers():
            with self.subTest(server=name):
                spec = read_json("servers", name, "smoke.json")
                mounted = {mount["target"] for mount in spec.get("mounts", []) if mount["host"] == "${FIXTURES}"}
                for call in spec.get("calls", []):
                    for value in call.get("arguments", {}).values():
                        if not isinstance(value, str):
                            continue
                        folder, _, file = value.rpartition("/")
                        if folder in mounted:
                            self.assertIn(file, available, f"{name}: the smoke uses {value}, which no "
                                                           "fixture provides")


class FileAnalysisServers(unittest.TestCase):
    """radare2, capa and binwalk: a file the user holds, nothing else."""

    def test_they_are_all_there(self):
        self.assertEqual([name for name in servers() if name in FILE_ANALYSIS], list(FILE_ANALYSIS))

    def test_no_network_and_no_secrets(self):
        for name in FILE_ANALYSIS:
            with self.subTest(server=name):
                entry = read_json("servers", name, "server.json")
                self.assertEqual(entry["network"], "none")
                self.assertEqual(entry.get("hosts", []), [])
                self.assertEqual(entry.get("env", []), [], f"{name} needs no variable and no secret")
                self.assertEqual(read_json("servers", name, "smoke.json").get("network", "none"), "none",
                                 f"{name}: the smoke run must have no network either")

    def test_the_input_folder_is_required_and_the_only_writable_one_is_out(self):
        for name in FILE_ANALYSIS:
            with self.subTest(server=name):
                entry = read_json("servers", name, "server.json")
                mounts = {mount["target"]: mount for mount in entry["mounts"]}
                self.assertIn("/work", mounts)
                self.assertTrue(mounts["/work"].get("required"), f"{name}: /work is where the file comes from")
                self.assertIn("read-only", mounts["/work"]["description"])
                self.assertEqual(sorted(mounts), ["/out", "/work"] if name == "binwalk" else ["/work"])
                if name == "binwalk":
                    self.assertIn("writable", mounts["/out"]["description"])
                    self.assertIn("/out", entry["notes"], "the notes must say what writes there")

    def test_the_catalog_entry_says_what_the_server_does(self):
        catalog = read_json("catalog.json")
        entries = {entry["name"]: entry for entry in catalog["entries"]}
        for name in FILE_ANALYSIS:
            with self.subTest(server=name):
                self.assertIn(name, entries)
                self.assertEqual(entries[name]["id"], f"mcp:{name}")
                self.assertEqual(entries[name]["image"], make_catalog.IMAGE_PREFIX + name)
                self.assertEqual(entries[name]["category"], "Analysis: Files")
                self.assertIn("/work", entries[name]["description"])
                # Pending until a CI run pushed it; once published, pinned by its digest.
                digest = entries[name].get("digest")
                self.assertTrue(digest is None or re.fullmatch(r"sha256:[0-9a-f]{64}", digest), digest)

    def test_the_provenance_pins_every_source(self):
        for name in FILE_ANALYSIS:
            with self.subTest(server=name):
                text = (ROOT / "servers" / name / "PROVENANCE.md").read_text()
                self.assertIn("Base image", text)
                self.assertIn("Ported from", text)
                self.assertRegex(text, r"`[0-9a-f]{40}`", f"{name}: no commit is pinned in PROVENANCE.md")
                dockerfile = (ROOT / "servers" / name / "Dockerfile").read_text()
                for commit in re.findall(r"^ARG \w*COMMIT=([0-9a-f]{40})$", dockerfile, re.M):
                    self.assertIn(commit, text, f"{name}: {commit} is built but not in PROVENANCE.md")


class Playwright(unittest.TestCase):
    """Playwright MCP with Debian's Chromium: the browser's limits, its flags and its pinned release."""

    def setUp(self):
        self.entry = read_json("servers", "playwright", "server.json")
        self.spec = read_json("servers", "playwright", "smoke.json")
        self.dockerfile = (ROOT / "servers" / "playwright" / "Dockerfile").read_text()
        self.entrypoint = json.loads(re.search(r"^ENTRYPOINT (\[.*?\])$", self.dockerfile.replace("\\\n", ""),
                                               re.M | re.S).group(1))

    def test_the_smoke_run_has_the_limits_the_entry_tells_users_to_add(self):
        self.assertEqual(self.entry["network"], "full")
        self.assertEqual(self.spec["network"], "full")
        self.assertEqual((self.spec["memory"], self.spec["pids"]), ("2g", 512))
        limits = f"--memory {self.spec['memory']} --pids {self.spec['pids']}"
        self.assertIn(limits, self.entry["description"])
        self.assertIn(limits, self.entry["notes"])
        self.assertIn(limits, (ROOT / "servers" / "playwright" / "PROVENANCE.md").read_text())

    def test_the_browser_runs_isolated_headless_and_offers_no_page_tools(self):
        for flag in ("--headless", "--isolated", "--no-sandbox", "--no-webmcp"):
            self.assertIn(flag, self.entrypoint)
        self.assertEqual(self.entrypoint[self.entrypoint.index("--executable-path") + 1], "/usr/bin/chromium")
        self.assertEqual(self.entrypoint[:3], ["/usr/bin/tini", "-s", "--"])
        for flag in ("--caps", "--allow-unrestricted-file-access", "--vision", "--port", "--host", "--extension",
                     "--cdp-endpoint", "--user-data-dir", "--shared-browser-context"):
            self.assertNotIn(flag, self.entrypoint, f"{flag} widens what the server offers")
        self.assertNotIn("--caps", self.dockerfile)

    def test_only_the_default_tools_are_recorded(self):
        tools = read_json("servers", "playwright", "tools.json")["tools"]
        self.assertEqual(len(tools), 25)
        self.assertEqual(tools, sorted(tools))
        for name in tools:
            self.assertRegex(name, r"^browser_[a-z_]+$")
        # behind --caps (storage, network, pdf, vision, devtools, testing, config): not offered here
        for name in ("browser_cookie_list", "browser_route", "browser_pdf_save", "browser_mouse_click_xy",
                     "browser_start_tracing", "browser_verify_value", "browser_get_config"):
            self.assertNotIn(name, tools)

    def test_the_smoke_spec_refuses_files_without_the_network(self):
        refused = [call for call in self.spec["calls"] if call.get("expect_error")]
        self.assertEqual([call["tool"] for call in refused], ["browser_navigate", "browser_evaluate"])
        for call in self.spec["calls"]:
            url = call["arguments"].get("url", "data:")
            self.assertTrue(url.startswith(("data:", "file:")), f"{url}: the smoke run needs no outside host")

    def test_the_release_is_pinned_and_in_the_provenance(self):
        provenance = (ROOT / "servers" / "playwright" / "PROVENANCE.md").read_text()
        commit = re.search(r"^ARG PLAYWRIGHT_MCP_COMMIT=([0-9a-f]{40})$", self.dockerfile, re.M).group(1)
        self.assertIn(commit, provenance)
        version = re.search(r"^ARG PLAYWRIGHT_VERSION=(\S+)$", self.dockerfile, re.M).group(1)
        self.assertIn(version, provenance)
        for arg in ("NODEJS_VERSION", "NPM_VERSION", "GIT_VERSION", "CHROMIUM_VERSION"):
            value = re.search(rf"^ARG {arg}=(\S+)$", self.dockerfile, re.M)
            self.assertTrue(value, f"{arg} is not pinned")
            self.assertIn(value.group(1), provenance, f"{arg} is not in PROVENANCE.md")


<<<<<<< HEAD
class OpenOsint(unittest.TestCase):
    """OpenOSINT's reviewed modules only, each pinned by SHA-256 at the pinned commit; passive tools only."""

    ACTIVE = ("search_username", "search_email", "search_domain", "search_phone", "scrape_url",
              "investigate_multi", "graph_export", "graph_neighbors", "graph_review_candidates")

    def setUp(self):
        self.folder = ROOT / "servers" / "openosint"
        self.dockerfile = (self.folder / "Dockerfile").read_text()
        self.provenance = (self.folder / "PROVENANCE.md").read_text()
        self.manifest = [line.split("  ", 1) for line in
                         (self.folder / "openosint-files.sha256").read_text().splitlines()]

    def test_only_the_reviewed_modules_go_into_the_image(self):
        self.assertEqual(len(self.manifest), 26)
        for digest, path in self.manifest:
            self.assertRegex(digest, r"^[0-9a-f]{64}$")
            self.assertRegex(path, r"^openosint/(?:tools/)?[a-z_0-9]+\.py$")
            self.assertIn(f"`{path.removeprefix('openosint/')}`", self.provenance, f"{path} is not in PROVENANCE.md")
        paths = {path for _, path in self.manifest}
        for left_out in ("mcp_server.py", "env.py", "utils.py", "agent.py", "multi_target.py", "cli.py",
                         "web_server.py", "tools/search_username.py", "tools/search_email.py",
                         "tools/search_domain.py", "tools/search_phone.py", "tools/scrape_url.py"):
            self.assertNotIn(f"openosint/{left_out}", paths)
        self.assertIn("sha256sum --check --strict", self.dockerfile)
        self.assertIn("COPY --from=source /opt/openosint/openosint /opt/venv/lib/python3.13/site-packages/openosint",
                      self.dockerfile)
        self.assertNotRegex(self.dockerfile, r"pip install[^\n]*openosint")

    def test_the_release_is_pinned_and_in_the_provenance(self):
        commit = re.search(r"^ARG OPENOSINT_COMMIT=([0-9a-f]{40})$", self.dockerfile, re.M).group(1)
        self.assertIn(commit, self.provenance)
        self.assertIn("**2.36.1**", self.provenance)
        self.assertIn("UPSTREAM_VERSION = \"2.36.1\"", (self.folder / "src" / "server.py").read_text())

    def test_passive_tools_and_optional_keys(self):
        tools = read_json("servers", "openosint", "tools.json")["tools"]
        self.assertEqual(tools, sorted(tools))
        for name in self.ACTIVE + ("search_shodan", "search_censys"):
            self.assertNotIn(name, tools)
        entry = read_json("servers", "openosint", "server.json")
        self.assertEqual(entry["network"], "full")
        self.assertNotIn("args", entry)
        for var in entry["env"]:
            self.assertFalse(var["required"], var["name"])
            self.assertEqual(var["secret"], var["name"] not in ("BRIGHTDATA_SERP_ZONE",
                                                                 "OPENOSINT_GDELT_WINDOW_HOURS"), var["name"])
        self.assertNotIn("OPENOSINT_ALLOW_ACTIVE", json.dumps(entry))
        self.assertNotIn("--allow-active", self.dockerfile)
=======
class OsintMcp(unittest.TestCase):
    """robyroro/osint-mcp from its hash-pinned wheel, started through src/server.py (the tightened address check)."""

    def setUp(self):
        self.folder = ROOT / "servers" / "osint-mcp"
        self.entry = read_json("servers", "osint-mcp", "server.json")
        self.spec = read_json("servers", "osint-mcp", "smoke.json")
        self.dockerfile = (self.folder / "Dockerfile").read_text()
        self.provenance = (self.folder / "PROVENANCE.md").read_text()

    def test_the_release_and_its_sdk_are_pinned_by_hash(self):
        lock = (self.folder / "requirements.txt").read_text()
        for pin in ("osint-mcp-server==0.3.0", "mcp==2.3.0"):
            self.assertIn(pin, (self.folder / "requirements.in").read_text())
            self.assertRegex(lock, rf"(?m)^{re.escape(pin)} \\\n    --hash=sha256:[0-9a-f]{{64}}")
            self.assertIn(pin.replace("==", " "), self.provenance.replace("==", " "))
        # the wheel's hash and the tag's commit, as reviewed
        self.assertIn("299a0c3f26c39bdf506a4493b48e033f8a83c6d68edfb48b3c92b9eeffd9c71b", lock)
        self.assertIn("299a0c3f26c39bdf506a4493b48e033f8a83c6d68edfb48b3c92b9eeffd9c71b", self.provenance)
        self.assertIn("815276a9edc554fc6aa529ee5c1f9916c204e7bf", self.provenance)
        self.assertIn("--require-hashes", self.dockerfile)
        self.assertIn("--only-binary=:all:", self.dockerfile)

    def test_it_starts_through_the_wrapper_with_the_cache_in_memory(self):
        entrypoint = json.loads(re.search(r"^ENTRYPOINT (\[.*\])$", self.dockerfile, re.M).group(1))
        self.assertEqual(entrypoint, ["/opt/venv/bin/python", "-I", "-u", "/opt/mcp/server.py"])
        self.assertIn("COPY src/server.py /opt/mcp/server.py", self.dockerfile)
        self.assertRegex(self.dockerfile, r"(?m)^\s+OSINT_MCP_CACHE_PATH=:memory:$")
        wrapper = (self.folder / "src/server.py").read_text()
        self.assertIn("network.public_ip = public_ip", wrapper)

    def test_full_network_no_secrets_and_the_smoke_refuses_local_targets(self):
        self.assertEqual((self.entry["network"], self.spec["network"]), ("full", "full"))
        self.assertEqual(self.entry.get("env", []), [], "osint-mcp needs no key")
        self.assertEqual(self.entry.get("mounts", []), [], "osint-mcp reads no files of yours")
        refused = [call for call in self.spec["calls"] if call.get("expect_error")]
        targets = json.dumps([call["arguments"] for call in refused])
        for local in ("169.254.169.254", "127.0.0.1", "10.0.0.1", ".local"):
            self.assertIn(local, targets)
        real = [call for call in self.spec["calls"] if not call.get("expect_error")]
        self.assertTrue(real, "the smoke spec must make real calls")
        for call in real:  # no API key and no target but example.com and RIPEstat's public data
            self.assertNotIn("${", json.dumps(call))
>>>>>>> feat/osint-mcp


@unittest.skipUnless(os.environ.get("SANDBOX_AI_CHECKOUT"), "SANDBOX_AI_CHECKOUT names a sandbox-ai checkout")
class SandboxAiAgrees(unittest.TestCase):
    """What this repository writes and what `sandbox-ai mcp add` accepts must be the same thing."""

    def setUp(self):
        self.checkout = Path(os.environ["SANDBOX_AI_CHECKOUT"]).resolve()

    def sandbox_ai_mcp(self):
        spec = importlib.util.spec_from_file_location("sandbox_ai_mcp_for_tests", self.checkout / "sandbox/mcp.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_the_committed_catalog_is_read_by_sandbox_ai(self):
        self.assertEqual(make_catalog.main(["--root", str(ROOT), "--check", "--allow-pending",
                                            "--sandbox-ai", str(self.checkout)]), 0)

    def test_a_fully_pinned_catalog_becomes_definitions_sandbox_ai_accepts(self):
        """With digests (as after a CI run) every entry, mounts and all, must become a definition."""
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        root = tmp / "repo"
        shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns(".git", "__pycache__", "candidates",
                                                                  "sandbox-ai"))
        digest = "sha256:" + "ab" * 32
        digests = json.loads((root / "digests.json").read_text())
        digests["images"] = {name: digest for name in digests["images"]}
        (root / "digests.json").write_text(json.dumps(digests, indent=2) + "\n")
        self.assertEqual(make_catalog.main(["--root", str(root)]), 0)
        self.assertEqual(make_catalog.main(["--root", str(root), "--check", "--sandbox-ai", str(self.checkout)]), 0)
        mcp = self.sandbox_ai_mcp()
        entries = mcp.read_catalog(str(root / "catalog.json"))
        for name in FILE_ANALYSIS:
            entry = next(e for e in entries if e["name"] == name)
            definition = mcp.definition_from_entry(entry, mounts=[f"/work={tmp}:ro"])
            self.assertEqual(definition["network"], "none")
            self.assertEqual(definition["image"], f"{make_catalog.IMAGE_PREFIX}{name}@{digest}")
            self.assertEqual(definition["mounts"], [{"target": "/work", "host": str(tmp), "mode": "ro"}])
            command = mcp.image_command(definition)
            self.assertIn("--network=none", command)
            self.assertIn(f"--volume={tmp}:/work:ro", command)
            self.assertIn("--read-only", command)
            with self.assertRaises(ValueError):  # the folder is required: no server without it
                mcp.definition_from_entry(entry)

    def test_the_smoke_limits_are_a_definition_sandbox_ai_takes(self):
        """A spec's memory and pids go into the definition as `mcp add --memory --pids` puts them there."""
        smoke = load("smoke_test")
        mcp = self.sandbox_ai_mcp()
        for name in servers():
            with self.subTest(server=name):
                resources = smoke.limits(read_json("servers", name, "smoke.json"))
                definition = mcp.validated_image({"image": f"{make_catalog.IMAGE_PREFIX}{name}@sha256:{'ab' * 32}",
                                                  "network": "full", **resources}, name)
                command = mcp.image_command(definition)
                self.assertIn(f"--memory={resources.get('memory', '512m')}", command)
                self.assertIn(f"--pids-limit={resources.get('pids', 128)}", command)

    def test_the_smoke_run_line_is_sandbox_ais(self):
        smoke = load("smoke_test")
        mcp = self.sandbox_ai_mcp()
        missing = [flag for flag in mcp.RUN_FLAGS if flag not in smoke.RUN_FLAGS]
        self.assertEqual(missing, [], "scripts/smoke_test.py no longer starts servers as sandbox-ai does")
        extra = [flag for flag in smoke.RUN_FLAGS if flag not in mcp.RUN_FLAGS]
        self.assertEqual(sorted(extra), ["--memory=512m", "--pids-limit=128"],
                         "sandbox-ai adds exactly the limits per definition")


if __name__ == "__main__":
    unittest.main()
