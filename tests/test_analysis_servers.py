"""The file-analysis servers (radare2, capa, binwalk) and what every server of this repository must
look like: no network, input read-only, pinned images and sources, a smoke spec that calls the tool
with a fixture whose SHA-256 is pinned - and, with SANDBOX_AI_CHECKOUT, that sandbox-ai's own reader
makes of each entry exactly what the catalog says."""
from __future__ import annotations

import hashlib
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
#: Servers that keep an agent's memory in a folder the user mounts writable at /data.
BRAINS = ("engram", "memory")


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
                for tool in spec.get("expect_tools", []) + [c["tool"] for c in spec.get("calls", [])
                                                            if not c.get("absent")]:
                    self.assertIn(tool, tools, f"{name}: {tool} is not in tools.json")
                # "absent": a refused call of a tool the server must not have (a cloud tool, a file reader)
                for call in spec.get("calls", []):
                    if call.get("absent"):
                        self.assertNotIn(call["tool"], tools, f"{name}: {call['tool']} is offered")
                        self.assertTrue(call.get("expect_error"), f"{name}: {call['tool']} must be refused")

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
                mounted = {mount["target"] for mount in spec.get("mounts", []) if mount.get("host") == "${FIXTURES}"}
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


class Radare2(unittest.TestCase):
    """r2mcp built from the reviewed commit with this repository's patch: open_file takes no URI under -s, no
    command it builds has a second line; started with -s /work, -g none, no prompts and exactly tools.json."""

    FOLDER = ROOT / "servers" / "radare2"
    PATCH = "0001-open-file-refuses-uris-commands-stay-one-line.patch"

    def setUp(self):
        self.dockerfile = (self.FOLDER / "Dockerfile").read_text()
        self.provenance = (self.FOLDER / "PROVENANCE.md").read_text()
        self.entrypoint = json.loads(re.search(r"^ENTRYPOINT (\[.*?\])$", self.dockerfile.replace("\\\n", ""),
                                               re.M | re.S).group(1))

    def test_the_patch_changes_only_r2api_and_is_applied_and_checked(self):
        self.assertEqual(sorted(path.name for path in (self.FOLDER / "patches").iterdir()), [self.PATCH])
        text = (self.FOLDER / "patches" / self.PATCH).read_text()
        self.assertEqual(set(re.findall(r"^\+\+\+ b/(\S+)$", text, re.M)), {"src/r2api.inc.c"})
        self.assertIn("+\tif (is_uri && R_STR_ISNOTEMPTY (ss->sandbox)) {", text)
        self.assertIn('+\tchar fchars[] = "|>`\\n\\r";', text)
        digest = hashlib.sha256((self.FOLDER / "patches" / self.PATCH).read_bytes()).hexdigest()
        self.assertIn(digest, self.provenance, "PROVENANCE.md names another SHA-256")
        self.assertIn('for p in /patches/*.patch; do patch -p1 --forward --fuzz=0 --no-backup-if-mismatch < "$p" '
                      '|| exit 1; done', self.dockerfile)
        patched = re.search(r'echo "([0-9a-f]{64})  src/r2api.inc.c" \| sha256sum --check --strict', self.dockerfile)
        self.assertTrue(patched, "the patched file is checked by SHA-256")
        self.assertIn(patched.group(1), self.provenance)

    def test_the_entrypoint_offers_exactly_the_reviewed_tools(self):
        self.assertEqual(self.entrypoint[:6], ["/opt/radare2/bin/r2mcp", "-s", "/work", "-g", "none", "-N"])
        rest = self.entrypoint[6:]
        self.assertEqual(rest[0::2], ["-e"] * (len(rest) // 2))
        tools = read_json("servers", "radare2", "tools.json")["tools"]
        self.assertEqual(rest[1::2], tools)
        self.assertEqual(len(tools), 32, "one page of tools/list (r2mcp lists 32 per page)")
        for flag in ("-r", "-p", "-H", "-u", "-S", "-L", "-X", "-c", "-l", "-P"):
            self.assertNotIn(flag, self.entrypoint, f"{flag} widens what the server does")
        for tool in ("sql", "search", "hexdump", "get_pid", "dump_registers", "run_command"):
            self.assertNotIn(tool, tools)

    def test_the_smoke_spec_refuses_a_uri(self):
        refused = [call["arguments"]["file_path"] for call in read_json("servers", "radare2", "smoke.json")["calls"]
                   if call.get("expect_error")]
        self.assertEqual(refused, ["/etc/passwd", "nocache:///etc/passwd"])


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
        self.assertIn(limits, self.entry["notes"])  # (for a sandbox-ai before 0.1.94)
        self.assertIn(limits, (ROOT / "servers" / "playwright" / "PROVENANCE.md").read_text())
        # Chromium's profile, cache, shared memory and screenshots are in /tmp: 64m crashed it.
        self.assertEqual((self.spec["tmp"], self.spec["cpus"]), ("768m", 2))
        self.assertIn("a 768m /tmp", self.entry["description"])
        # What its smoke runs had is what sandbox-ai's mcp add applies (rootfs.json's "limits", made from smoke.json).
        rootfs = json.loads((ROOT / "rootfs.json").read_text())
        self.assertEqual(rootfs["limits"]["playwright"], {"memory": "2g", "cpus": 2, "pids": 512, "tmp": "768m"})

    def test_the_smoke_run_fills_memory_and_tmp_as_real_pages_do(self):
        """A data: page of a few bytes passed while every real page crashed the browser (a 64m /tmp): the smoke run
        builds a page of several MB with large canvases and takes a screenshot."""
        tools = [call["tool"] for call in self.spec["calls"]]
        self.assertIn("browser_take_screenshot", tools)
        heavy = next(call for call in self.spec["calls"] if call.get("expect") == "40000 rows")
        self.assertIn("4000", heavy["arguments"]["function"])

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


class Gowitness(unittest.TestCase):
    """gowitness built from its pinned commit with only the chromedp scan path; Debian's Chromium; the limits."""

    REMOVED = ("cmd/report.go", "cmd/report_convert.go", "cmd/report_generate.go", "cmd/report_list.go",
               "cmd/report_merge.go", "cmd/report_migrate.go", "cmd/report_server.go", "pkg/writers/db.go",
               "pkg/runner/drivers/go-rod.go", "pkg/runner/drivers/restricted_ports.go")

    def setUp(self):
        self.entry = read_json("servers", "gowitness", "server.json")
        self.spec = read_json("servers", "gowitness", "smoke.json")
        self.dockerfile = (ROOT / "servers" / "gowitness" / "Dockerfile").read_text()
        self.provenance = (ROOT / "servers" / "gowitness" / "PROVENANCE.md").read_text()
        self.patch = (ROOT / "servers" / "gowitness" / "gowitness-chromedp-only.patch").read_text()

    def test_the_smoke_run_has_the_limits_the_entry_tells_users_to_add(self):
        self.assertEqual((self.entry["network"], self.spec["network"]), ("full", "full"))
        self.assertEqual((self.spec["memory"], self.spec["pids"], self.spec["tmp"]), ("2g", 512, "768m"))
        limits = f"--memory {self.spec['memory']} --pids {self.spec['pids']}"
        for where, text in (("description", self.entry["description"]), ("notes", self.entry["notes"]),
                            ("PROVENANCE.md", self.provenance)):
            self.assertTrue(limits in text and "/tmp of 768m" in text, f"{where} does not name the limits")

    def test_the_release_and_the_pins_are_in_the_provenance(self):
        for arg in ("GOWITNESS_COMMIT", "GOWITNESS_VERSION", "CHROMIUM_VERSION"):
            value = re.search(rf"^ARG {arg}=(\S+)$", self.dockerfile, re.M)
            self.assertTrue(value, f"{arg} is not pinned")
            self.assertIn(value.group(1), self.provenance, f"{arg} is not in PROVENANCE.md")
        self.assertRegex(self.dockerfile, r"ARG GOWITNESS_COMMIT=[0-9a-f]{40}\n")
        self.assertRegex(self.dockerfile, r"ARG GOLANG_IMAGE=\S+@sha256:[0-9a-f]{64}\n")
        self.assertEqual((ROOT / "servers" / "gowitness" / "requirements.txt").read_bytes(),
                         (ROOT / "servers" / "web-fetch" / "requirements.txt").read_bytes())

    def test_only_the_scan_path_is_built(self):
        for name in self.REMOVED:
            self.assertIn(name, self.dockerfile, f"{name} is not removed")
        for named in ("cmd/report*.go", "pkg/writers/db.go", "pkg/runner/drivers/go-rod.go", "restricted_ports.go",
                      "image_formats.go"):
            self.assertTrue(named in self.provenance, f"PROVENANCE.md does not name {named}")
        changed = sorted(set(re.findall(r"^\+\+\+ b/(\S+)$", self.patch, re.M)))
        self.assertEqual(changed, ["cmd/scan.go", "pkg/runner/drivers/chromedp.go",
                                   "pkg/runner/drivers/image_formats.go"])
        self.assertIn('-\t\t\tchromedp.Flag("explicitly-allowed-ports", restrictedPorts()),', self.patch)
        self.assertIn('+\t_ "image/png"', self.patch)
        self.assertIn("go-rod|ysmood", self.dockerfile)  # the build fails if they are linked
        self.assertIn('ENTRYPOINT ["/usr/bin/tini", "-s", "--", "/opt/venv/bin/python", "-I", "-u"', self.dockerfile)

    def test_the_smoke_spec_screenshots_and_refuses(self):
        refused = [call for call in self.spec["calls"] if call.get("expect_error")]
        self.assertEqual(len(refused), 4)  # a file URL, the metadata address, loopback, .onion without Tor
        self.assertTrue(any("image/png" in call["expect"] for call in self.spec["calls"]))


class WhatWeb(unittest.TestCase):
    """WhatWeb from its pinned commit on Debian's Ruby; aggression 4 is never offered."""

    def test_pinned_and_in_the_provenance(self):
        dockerfile = (ROOT / "servers" / "whatweb" / "Dockerfile").read_text()
        provenance = (ROOT / "servers" / "whatweb" / "PROVENANCE.md").read_text()
        commit = re.search(r"^ARG WHATWEB_COMMIT=([0-9a-f]{40})$", dockerfile, re.M).group(1)
        self.assertIn(commit, provenance)
        for package in ("ruby3.3=3.3.13-0+deb13u1", "libruby3.3=3.3.13-0+deb13u1", "ruby-addressable=2.8.7-2",
                        "ruby-public-suffix=6.0.1-1"):
            self.assertIn(package, dockerfile)
            self.assertIn(package, provenance)
        self.assertEqual((ROOT / "servers" / "whatweb" / "requirements.txt").read_bytes(),
                         (ROOT / "servers" / "web-fetch" / "requirements.txt").read_bytes())

    def test_no_aggression_4_and_no_passthrough(self):
        spec = read_json("servers", "whatweb", "smoke.json")
        for call in spec["calls"]:
            if call["arguments"].get("aggression") == 4:
                self.assertTrue(call.get("expect_error"))
        source = (ROOT / "servers" / "whatweb" / "src" / "server.py").read_text()
        self.assertIn('"--follow-redirect=never"', source)
        self.assertIn('"--", url]', source)
        for option in ("--custom-plugin", "--grep", "--plugins", "--input-file", "--proxy", "--header"):
            self.assertNotIn(f'"{option}', source)


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


class BrainServers(unittest.TestCase):
    """The memory servers ("brains"): no network, the memory only in a writable /data the user mounts (one folder per
    case), a smoke run that writes, searches and reads back in a fresh folder of its own."""

    def test_no_network_and_the_memory_folder_is_required_and_writable(self):
        for name in BRAINS:
            with self.subTest(server=name):
                entry = read_json("servers", name, "server.json")
                spec = read_json("servers", name, "smoke.json")
                self.assertEqual((entry["network"], spec["network"]), ("none", "none"))
                self.assertEqual(entry.get("hosts", []), [])
                self.assertEqual(entry["category"], "Memory")
                mount, = entry["mounts"]
                self.assertEqual((mount["target"], mount["required"]), ("/data", True))
                self.assertIn("--mount /data=", mount["description"])
                self.assertIn("one folder per", (mount["description"] + entry["notes"]).lower())
                self.assertFalse(any(v.get("secret") or v.get("required") for v in entry.get("env", [])))
                self.assertEqual(spec["mounts"], [{"target": "/data", "fresh": True, "writable": True}])

    def test_the_smoke_run_writes_searches_and_reads_back_and_is_refused_the_rest(self):
        for name in BRAINS:
            with self.subTest(server=name):
                calls = read_json("servers", name, "smoke.json")["calls"]
                real = [c for c in calls if not c.get("expect_error")]
                refused = [c for c in calls if c.get("expect_error")]
                self.assertGreaterEqual(len(real), 3, "write, search, read back")
                self.assertGreaterEqual(len(refused), 3)
                self.assertTrue([c for c in refused if c.get("absent")], "a tool that must not exist is refused")

    def test_the_final_image_runs_without_a_package_manager_or_network_tools(self):
        for name in BRAINS:
            with self.subTest(server=name):
                text = (ROOT / "servers" / name / "Dockerfile").read_text()
                final = text[[m.start() for m in re.finditer(r"^FROM ", text, re.M)][-1]:]
                final = re.sub(r"(?m)^#.*$", "", final)
                self.assertNotIn("apt-get install", final)
                self.assertNotRegex(final, r"\b(npm|git|curl|wget)\b(?!-)")
                self.assertIn("mkdir -m 0755 /data", final)


class Memory(unittest.TestCase):
    """The official Knowledge Graph memory server: the npm release and its three packages by integrity, the graph
    fixed to /data/memory.jsonl, no code generation from strings."""

    def setUp(self):
        self.folder = ROOT / "servers" / "memory"
        self.dockerfile = (self.folder / "Dockerfile").read_text()
        self.provenance = (self.folder / "PROVENANCE.md").read_text()
        self.lock = read_json("servers", "memory", "package-lock.json")

    def test_the_lock_has_the_server_and_its_three_packages_by_integrity(self):
        packages = {path.removeprefix("node_modules/"): entry for path, entry in self.lock["packages"].items() if path}
        self.assertEqual({name: entry["version"] for name, entry in packages.items()},
                         {"@modelcontextprotocol/server-memory": "2.0.1", "@modelcontextprotocol/server": "2.4.0",
                          "@modelcontextprotocol/core": "2.4.0", "zod": "4.6.7"})
        for name, entry in packages.items():
            self.assertTrue(entry["resolved"].startswith("https://registry.npmjs.org/"), name)
            self.assertRegex(entry["integrity"], r"^sha512-[A-Za-z0-9+/]{86}==$", name)
            self.assertIn(entry["integrity"][:15], self.provenance, f"{name}: its integrity is not in PROVENANCE.md")
        self.assertEqual(read_json("servers", "memory", "package.json")["dependencies"],
                         {"@modelcontextprotocol/server-memory": "2.0.1"})

    def test_install_runs_no_scripts_and_the_reviewed_files_are_checked(self):
        self.assertIn("npm ci --omit=dev --ignore-scripts", self.dockerfile)
        for digest in re.findall(r'echo "([0-9a-f]{64})  node_modules/', self.dockerfile):
            self.assertIn(digest, self.provenance)
        self.assertEqual(len(re.findall(r'echo "([0-9a-f]{64})  node_modules/', self.dockerfile)), 2)
        self.assertIn("194cc86e3ae6400958555bd4116849d822d69263", self.provenance)
        node = re.search(r"^ARG NODE_IMAGE=\S+@(sha256:[0-9a-f]{64})$", self.dockerfile, re.M)
        self.assertTrue(node)
        self.assertIn(node.group(1), self.provenance)

    def test_the_graph_is_fixed_to_data_and_no_code_is_generated(self):
        self.assertRegex(self.dockerfile, r"(?m)^ENV .*MEMORY_FILE_PATH=/data/memory\.jsonl")
        self.assertIn('"--disallow-code-generation-from-strings"', self.dockerfile)
        entry = read_json("servers", "memory", "server.json")
        self.assertNotIn("env", entry, "no variable can move the graph out of /data")

    def test_nine_tools(self):
        self.assertEqual(read_json("servers", "memory", "tools.json")["tools"],
                         ["add_observations", "create_entities", "create_relations", "delete_entities",
                          "delete_observations", "delete_relations", "open_nodes", "read_graph", "search_nodes"])


class Engram(unittest.TestCase):
    """Engram's MCP server only: our entry point inside Engram's module, linking internal/mcp and internal/store,
    every linked Engram file the reviewed one, one project per memory folder, no folder arguments."""

    def setUp(self):
        self.folder = ROOT / "servers" / "engram"
        self.dockerfile = (self.folder / "Dockerfile").read_text()
        self.provenance = (self.folder / "PROVENANCE.md").read_text()
        self.main = (self.folder / "src" / "main.go").read_text()
        self.main_test = (self.folder / "src" / "main_test.go").read_text()

    def test_the_release_commit_and_every_reviewed_file_are_pinned(self):
        commit = re.search(r"^ARG ENGRAM_COMMIT=([0-9a-f]{40})$", self.dockerfile, re.M).group(1)
        self.assertIn(commit, self.provenance)
        lines = (self.folder / "engram-files.sha256").read_text().splitlines()
        self.assertGreater(len(lines), 50)
        for line in lines:
            digest, path = line.split("  ")
            self.assertRegex(digest, r"^[0-9a-f]{64}$")
            self.assertRegex(path, r"^(internal/[a-z/]+/[a-z0-9_]+\.go|go\.mod|go\.sum|LICENSE)$")
            self.assertNotRegex(path, r"_test\.go$|_windows\.go$|_darwin\.go$")
            self.assertIn(digest, self.provenance, f"{path}: its SHA-256 is not in PROVENANCE.md")
        packages = {path.rsplit("/", 1)[0] for _, path in (line.split("  ") for line in lines) if "/" in path}
        self.assertEqual(packages, {"internal/agentops", "internal/cloud/constants", "internal/command",
                                    "internal/diagnostic", "internal/hostbind", "internal/identityfile",
                                    "internal/mcp", "internal/project", "internal/store", "internal/timeutil"})
        for package in packages:  # the build compares the linked packages with this list
            self.assertIn(package, self.dockerfile)
        self.assertIn("sha256sum --check --strict --quiet /tmp/engram-files.sha256", self.dockerfile)
        self.assertIn("go mod verify", self.dockerfile)
        self.assertIn("go test -count=1 ./cmd/sandbox-ai-mcp", self.dockerfile)

    def test_only_the_mcp_server_of_engram_is_linked(self):
        imports = re.search(r"^import \((.*?)^\)", self.main, re.M | re.S).group(1)
        engram = re.findall(r'"github\.com/Gentleman-Programming/engram/v3/([^"]+)"', imports)
        self.assertEqual(sorted(engram), ["internal/mcp", "internal/store"])
        for forbidden in ('"os/exec"', '"net"', '"net/http"', '"plugin"', '"unsafe"'):
            self.assertNotIn(forbidden, imports)
        self.assertIn('engram.ResolveTools("agent")', self.main)
        self.assertIn("store.FallbackConfig(dataDir)", self.main, "Engram's limits: an empty Config stores nothing")
        self.assertIn('dataDir        = "/data"', self.main)

    def test_the_tools_are_the_agent_profile_and_no_tool_takes_a_folder(self):
        tools = read_json("servers", "engram", "tools.json")["tools"]
        listed = re.search(r"var agentTools = \[\]string\{(.*?)\}", self.main_test, re.S).group(1)
        self.assertEqual(tools, sorted(re.findall(r'"([a-z_]+)"', listed)))
        self.assertEqual(len(tools), 23)
        for admin in ("mem_delete", "mem_merge_projects", "mem_stats", "mem_timeline"):
            self.assertNotIn(admin, tools)
        self.assertIn('"mem_session_start":   {"directory"}', self.main)
        self.assertIn('"mem_current_project": {"directory", "cwd"}', self.main)
        refused = {c["tool"]: c["expect"] for c in read_json("servers", "engram", "smoke.json")["calls"]
                   if c.get("expect_error")}
        self.assertEqual(refused["mem_session_start"], "directory: not offered here")
        self.assertEqual(refused["mem_current_project"], "cwd: not offered here")

    def test_no_git_in_the_image_and_a_path_without_writable_folders(self):
        final = self.dockerfile[[m.start() for m in re.finditer(r"^FROM ", self.dockerfile, re.M)][-1]:]
        self.assertRegex(final, r"(?m)^ENV .*PATH=/usr/local/bin:/usr/bin:/bin\b")
        self.assertNotIn("git", re.sub(r"(?m)^#.*$", "", final).replace("github.com", ""))
        self.assertIn('ENTRYPOINT ["/usr/local/bin/engram-mcp"]', final)


class BasicMemoryLeftOut(unittest.TestCase):
    def test_it_is_not_packaged_and_the_readme_says_why(self):
        self.assertFalse((ROOT / "servers" / "basic-memory").exists())
        self.assertFalse((ROOT / "candidates" / "basic-memory").exists())
        readme = (ROOT / "README.md").read_text()
        section = readme[readme.index("## Not in the catalog, and why"):readme.index("## Using them in sandbox-ai")]
        self.assertIn("**Basic Memory**", section)
        self.assertIn("docs/CANDIDATES.md#basic-memory", section)


class Signal(unittest.TestCase):
    """The Signal account server: the account only in a writable /data, read-only by default, signal-cli's and
    the JRE's release files and signal-mcp's commit pinned, its reviewed modules listed by SHA-256."""

    def setUp(self):
        self.folder = ROOT / "servers" / "signal"
        self.entry = read_json("servers", "signal", "server.json")
        self.spec = read_json("servers", "signal", "smoke.json")
        self.dockerfile = (self.folder / "Dockerfile").read_text()
        self.provenance = (self.folder / "PROVENANCE.md").read_text()

    def test_the_account_folder_is_required_and_nothing_secret_is_in_the_environment(self):
        self.assertEqual(self.entry["mounts"], [{"target": "/data", "description": self.entry["mounts"][0]["description"],
                                                 "required": True}])
        self.assertIn("--mount /data=DIR:rw", self.entry["notes"])
        self.assertEqual([v["name"] for v in self.entry["env"]], ["SIGNAL_WRITE", "SIGNAL_ALLOWED_RECIPIENTS"])
        self.assertFalse(any(v["secret"] or v["required"] for v in self.entry["env"]))
        mount, = self.spec["mounts"]
        self.assertEqual((mount["target"], mount.get("writable", False)), ("/data", False))  # refused: read-only

    def test_the_smoke_run_has_the_limits_the_entry_tells_users_to_add(self):
        self.assertEqual((self.entry["network"], self.spec["network"]), ("full", "full"))
        self.assertEqual((self.spec["memory"], self.spec["pids"]), ("1g", 256))
        limits = f"--memory {self.spec['memory']} --pids {self.spec['pids']}"
        for text in (self.entry["description"], self.entry["notes"], self.provenance):
            self.assertIn(limits, text)

    def test_read_only_by_default(self):
        self.assertEqual(read_json("servers", "signal", "tools.json")["tools"],
                         ["get_conversation", "get_status", "get_unread", "list_contacts", "list_conversations",
                          "list_groups", "receive_messages", "search_messages"])
        server = (self.folder / "src" / "server.py").read_text()
        self.assertIn('WRITE = _flag("SIGNAL_WRITE")', server)
        for tool in ("send_message", "send_group_message", "react_to_message"):
            self.assertRegex(server, rf"@offered\(WRITE\)\nasync def {tool}\(")
        self.assertNotRegex(server, r"\b(shell=True|os\.system|eval|exec)\(")

    def test_every_pin_is_in_the_provenance(self):
        for arg in ("SIGNAL_MCP_COMMIT", "SIGNAL_CLI_SHA256", "TEMURIN_SHA256"):
            value = re.search(rf"^ARG {arg}=([0-9a-f]{{40,64}})$", self.dockerfile, re.M)
            self.assertTrue(value, f"{arg} is not pinned")
            self.assertIn(value.group(1), self.provenance, f"{arg} is not in PROVENANCE.md")
        for url in re.findall(r"^ARG \w+_URL=(\S+)$", self.dockerfile, re.M):
            self.assertTrue(url.startswith("https://github.com/"), url)
        prepare = (self.folder / "prepare.py").read_text()
        for digest in re.findall(r'"([0-9a-f]{64})"', prepare):
            self.assertIn(digest, self.provenance)
        for line in (self.folder / "signal-mcp-files.sha256").read_text().splitlines():
            digest, path = line.split()
            self.assertRegex(digest, r"^[0-9a-f]{64}$")
            self.assertRegex(path, r"^src/signal_mcp/[a-z_]+\.py$")
            self.assertIn(path.removeprefix("src/signal_mcp/"), self.provenance)
        listed = [line.split()[1] for line in (self.folder / "signal-mcp-files.sha256").read_text().splitlines()]
        self.assertNotIn("src/signal_mcp/server.py", listed)  # upstream's own MCP server is not shipped


class WhatsApp(unittest.TestCase):
    """whatsapp-mcp built from the reviewed commit with this repository's patches: read-only unless
    WHATSAPP_WRITE=1, no pairing or logout tools, files sent only from /send, the session only in /data."""

    FOLDER = ROOT / "servers" / "whatsapp"
    READ_TOOLS = ["get_chat", "get_contact", "get_media", "get_message_context", "list_accounts", "list_chats",
                  "list_messages", "list_recent", "request_history", "search_contacts", "search_messages",
                  "session_status"]
    WRITE_TOOLS = ["send_message", "send_media", "send_location", "send_poll", "react", "edit_message",
                   "delete_message", "mark_read", "send_presence", "check_whatsapp", "create_group", "update_group",
                   "update_group_participants", "group_invite_link", "preview_group_link", "join_group",
                   "list_join_requests", "handle_join_requests", "leave_group", "link_to_community", "update_chat",
                   "get_profile", "set_about", "blocklist", "privacy_settings", "session_pair", "session_logout"]
    #: patch -> the upstream files it may change
    PATCHES = {
        "0001-read-only-unless-whatsapp-write.patch": {"crates/wa-mcp/src/main.rs", "crates/wa-mcp/src/mcp/mod.rs"},
        "0002-bridge-stderr-logs-send-folder-media-limit.patch": {"bridge/main.go", "bridge/manage.go",
                                                                "bridge/media.go", "bridge/send.go"},
        "0003-store-sender-checks.patch": {"crates/wa-mcp/src/store.rs"},
        "0004-durations-in-range.patch": {"crates/wa-mcp/src/dates.rs"},
        "0005-private-account-folder.patch": {"crates/wa-mcp/src/lock.rs"},
    }

    def setUp(self):
        self.entry = read_json("servers", "whatsapp", "server.json")
        self.spec = read_json("servers", "whatsapp", "smoke.json")
        self.dockerfile = (self.FOLDER / "Dockerfile").read_text()
        self.provenance = (self.FOLDER / "PROVENANCE.md").read_text()

    def patch(self, name: str) -> str:
        return (self.FOLDER / "patches" / name).read_text()

    def test_read_only_unless_whatsapp_write(self):
        self.assertEqual(read_json("servers", "whatsapp", "tools.json")["tools"], self.READ_TOOLS)
        self.assertEqual(len(self.READ_TOOLS) + len(self.WRITE_TOOLS), 39, "upstream offers 39 tools")
        write = {var["name"]: var for var in self.entry["env"]}["WHATSAPP_WRITE"]
        self.assertFalse(write["required"])
        self.assertNotIn("WHATSAPP_WRITE", self.spec.get("env", {}))
        gate = self.patch("0001-read-only-unless-whatsapp-write.patch")
        self.assertIn('matches!(std::env::var("WHATSAPP_WRITE").as_deref(), Ok("1"))', gate)
        for tool in ("session_pair", "session_logout"):
            self.assertIn(f'tools.remove_route("{tool}");', gate, f"{tool} is never offered")
            self.assertIn(tool, self.entry["description"] + self.provenance)

    def test_the_patches_change_only_their_files_and_are_applied_in_order(self):
        found = sorted(path.name for path in (self.FOLDER / "patches").iterdir())
        self.assertEqual(found, sorted(self.PATCHES))
        for name, files in self.PATCHES.items():
            with self.subTest(patch=name):
                text = self.patch(name)
                touched = set(re.findall(r"^\+\+\+ b/(\S+)$", text, re.M))
                self.assertEqual(touched, files)
                self.assertEqual(set(re.findall(r"^--- a/(\S+)$", text, re.M)), files, "no file is added or removed")
                self.assertIn(name, self.provenance)
                digest = hashlib.sha256((self.FOLDER / "patches" / name).read_bytes()).hexdigest()
                self.assertIn(digest, self.provenance, f"{name}: PROVENANCE.md names another SHA-256")
        self.assertIn('for patch in /patches/*.patch; do git apply --verbose "$patch" || exit 1; done', self.dockerfile)

    def test_files_are_sent_only_from_the_send_folder_and_downloads_are_capped(self):
        bridge = self.patch("0002-bridge-stderr-logs-send-folder-media-limit.patch")
        self.assertIn('os.Getenv("WA_SEND_DIR")', bridge)
        self.assertIn("path, err := b.sendable(req.Path)", bridge)
        self.assertIn("path, err := b.sendable(op.SetPhotoPath)", bridge)
        self.assertIn('os.Getenv("WHATSAPP_MEDIA_MB")', bridge)
        # libsignal's default logger would print on stdout, the frame channel
        self.assertIn("signallog.Setup(&libsignalLog)", bridge)
        final = self.dockerfile[[m.start() for m in re.finditer(r"^FROM ", self.dockerfile, re.M)][-1]:]
        env = re.search(r"^ENV ((?:[^\n]*\\\n)*[^\n]*)$", final, re.M).group(1)
        for setting in ("WA_DATA_DIR=/data", "WA_SEND_DIR=/send", "WA_BRIDGE=/usr/local/bin/wa-bridge"):
            self.assertIn(setting, env.split())
        self.assertIn("if to.Server == types.BroadcastServer {", bridge)

    def test_the_session_lives_only_in_the_mounted_folder(self):
        mounts = {mount["target"]: mount for mount in self.entry["mounts"]}
        self.assertEqual(sorted(mounts), ["/data", "/send"])
        self.assertIn("--mount /data=DIR:rw", mounts["/data"]["description"])
        self.assertIn("--mount /send=DIR:ro", mounts["/send"]["description"])
        self.assertFalse(any(mount.get("required") for mount in mounts.values()),
                         "without /data the server starts and has no account")
        self.assertFalse(any(var["secret"] for var in self.entry["env"]), "the session is a folder, not a variable")
        self.assertIn("install -d -o 10001 -g 10001 -m 0700 /data", self.dockerfile)
        self.assertRegex(self.dockerfile, r'(?m)^ENTRYPOINT \["/usr/local/bin/wa-mcp"\]\nCMD \["serve"\]$')
        self.assertIn("0o700", self.patch("0005-private-account-folder.patch"))

    def test_the_smoke_run_needs_no_account_and_no_network(self):
        self.assertEqual(self.entry["network"], "full")
        self.assertEqual(self.spec["network"], "none")
        self.assertFalse(self.spec.get("mounts"))
        for call in self.spec["calls"]:
            self.assertIn(call["tool"], self.READ_TOOLS)
        self.assertEqual([c["tool"] for c in self.spec["calls"] if not c.get("expect_error")], ["list_accounts"])

    def test_the_sources_and_tools_are_pinned_and_in_the_provenance(self):
        commit = re.search(r"^ARG WA_MCP_COMMIT=([0-9a-f]{40})$", self.dockerfile, re.M).group(1)
        self.assertIn(commit, self.provenance)
        for image in ("GOLANG_IMAGE", "RUST_IMAGE", "DEBIAN_IMAGE"):
            digest = re.search(rf"^ARG {image}=\S+@(sha256:[0-9a-f]{{64}})$", self.dockerfile, re.M).group(1)
            self.assertIn(digest, self.provenance, f"{image} is not in PROVENANCE.md")
        protoc = re.search(r"--checksum=(sha256:[0-9a-f]{64})", self.dockerfile).group(1)
        self.assertIn(protoc, self.provenance)
        # the contract's Go code is generated again from the reviewed bridge.proto, never taken from upstream
        self.assertIn("rm -rf /src/.git /src/bridge/pb/bridge.pb.go", self.dockerfile)
        self.assertIn("--go_out=pb", self.dockerfile)
        self.assertIn("cargo build --release --locked --offline --bin wa-mcp", self.dockerfile)
        self.assertIn("go mod download && go mod verify", self.dockerfile)


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
        # The published rootfs archives were made from the real digests: none fits these made-up ones.
        digests["rootfs"] = {}
        (root / "digests.json").write_text(json.dumps(digests, indent=2) + "\n")
        (root / "rootfs.json").write_text(json.dumps({"version": 1, "rootfs": {}}, indent=2) + "\n")
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
