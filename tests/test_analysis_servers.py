"""The file-analysis servers (radare2, capa, binwalk) and what every server of this repository must
look like: no network, input read-only, pinned images and sources, a smoke spec that calls the tool
with a fixture whose SHA-256 is pinned - and, with SANDBOX_AI_CHECKOUT, that sandbox-ai's own reader
makes of each entry exactly what the catalog says."""
from __future__ import annotations

import ast
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
#: Servers that analyse a file the user holds: no network, input mounted read-only.
FILE_ANALYSIS = ("binwalk", "capa", "radare2")
#: Servers that keep an agent's memory in a folder the user mounts writable at /data.
BRAINS = ("engram", "memory")
#: Servers that work in the agent's own project folder, which they need writable at /work (run commands in it, keep a
#: plan in it): the only ones that may mount /work writable.
WORKSPACE_SERVERS = ("exec", "tasks")


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


def final_stage(name: str) -> str:
    """The final stage of servers/NAME/Dockerfile (from its last FROM)."""
    text = (ROOT / "servers" / name / "Dockerfile").read_text()
    return text[[m.start() for m in re.finditer(r"^FROM ", text, re.M)][-1]:]


def final_command(name: str) -> list:
    """ENTRYPOINT + CMD of the final stage (exec form), as the image runs it and scripts/rootfs.py records it."""
    final = final_stage(name).replace("\\\n", "")
    words = []
    for key in ("ENTRYPOINT", "CMD"):
        found = re.findall(rf"(?ms)^{key} (\[.*?\])$", final)
        if found:
            words += json.loads(found[-1])
    return words


def sandbox_ai_module(name: str):
    """sandbox/NAME.py of the sandbox-ai checkout SANDBOX_AI_CHECKOUT names, or None without one."""
    checkout = os.environ.get("SANDBOX_AI_CHECKOUT")
    if not checkout:
        return None
    spec = importlib.util.spec_from_file_location(f"sandbox_ai_{name}_for_test",
                                                  Path(checkout, "sandbox", f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Fixtures(unittest.TestCase):
    def test_the_binary_fixtures_match_their_pinned_sha256(self):
        found = fixtures.load()
        self.assertEqual(sorted(f["path"] for f in found),
                         ["caps", "demo-res.apk", "demo.apk", "demo.jar", "firmware.bin", "hello", "sales.parquet",
                          "sample.docx", "sample.epub", "sample.pdf", "sample.pptx", "sample.xlsx", "shop.duckdb",
                          "shop.sqlite"])
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

    def test_every_image_brings_its_own_init(self):
        """Podman's --init is the HOST's catatonit: a host without it (Debian's and Ubuntu's podman do not pull it in)
        starts an image only when the image has an init of its own as its ENTRYPOINT (sandbox-ai's hostinit.image_init)
        or the server is its own PID 1 by its entry ("pid1": "server", exec). Debian's tini, pinned, with -s (it reaps
        also where it is not PID 1: under Podman's --init and Bubblewrap)."""
        for name in servers():
            with self.subTest(server=name):
                entrypoint = final_command(name)
                if read_json("servers", name, "server.json").get("pid1") == "server":
                    self.assertNotEqual(entrypoint[0], "/usr/bin/tini", f"{name}: is PID 1 itself")
                    continue
                self.assertEqual(entrypoint[:3], ["/usr/bin/tini", "-s", "--"], f"{name}: no init of its own")
                final = final_stage(name)
                self.assertRegex(final, r"apt-get install -y --no-install-recommends (?:[^\n]*\\\n)*[^\n]*"
                                        r"\btini=0\.19\.0-3\+b8\b", f"{name}: Debian's tini, pinned, in the final image")
        hostinit = sandbox_ai_module("hostinit")
        if hostinit is not None:
            for name in servers():
                with self.subTest(server=name, check="sandbox-ai's hostinit.image_init"):
                    if read_json("servers", name, "server.json").get("pid1") == "server":
                        continue
                    self.assertEqual(hostinit.image_init(final_command(name)), "tini",
                                     f"{name}: sandbox-ai would want the host's init for it")

    def test_the_bubblewrap_form_takes_the_entrypoint(self):
        """The rootfs.json entry of each image runs ENTRYPOINT + CMD as sandbox-ai's mcp_rootfs.validated takes it: an
        absolute program, at most 32 words (radare2's 70 words of flags are in r2mcp-run), a numeric user that is
        not root."""
        for name in servers():
            with self.subTest(server=name):
                entrypoint = final_command(name)
                self.assertTrue(entrypoint[0].startswith("/"), f"{name}: {entrypoint[0]} is not absolute")
                self.assertLessEqual(len(entrypoint), 32, f"{name}: the Bubblewrap form takes at most 32 words")
                self.assertTrue(all(word and "\0" not in word and len(word) < 4096 for word in entrypoint))
        rootfs = sandbox_ai_module("mcp_rootfs")
        if rootfs is not None:
            for name in servers():
                with self.subTest(server=name, check="sandbox-ai's mcp_rootfs.validated"):
                    sha = "0" * 64
                    rootfs.validated({"path": str(rootfs.rootfs_dir(sha)), "sha256": sha,
                                      "entrypoint": final_command(name), "user": 10001, "workdir": "/tmp",
                                      "env": {}}, name)

    def test_every_image_with_network_has_an_etc_hosts(self):
        """An image has no /etc/hosts of its own (Podman and Docker mount one at run time; `podman export`, which makes
        the Bubblewrap form, has none): sandbox-ai's Bubblewrap form binds an allowlist server's pinned hosts onto
        /etc/hosts, which a read-only root without the file refuses, and WhatWeb's Ruby resolver reads it before every
        lookup ("No such file or directory - /etc/hosts" under Bubblewrap). Every image with network has one: the
        file hosts beside its Dockerfile (a COPY, not a RUN: a build mounts its own /etc/hosts over the image's)."""
        expected = "127.0.0.1\tlocalhost\n::1\tlocalhost ip6-localhost ip6-loopback\n"
        for name in servers():
            with self.subTest(server=name):
                if read_json("servers", name, "server.json").get("network", "none") == "none":
                    self.assertFalse((ROOT / "servers" / name / "hosts").exists(), f"{name}: has no network")
                    continue
                self.assertEqual((ROOT / "servers" / name / "hosts").read_text(), expected)
                self.assertRegex(final_stage(name), r"(?m)^COPY hosts /etc/hosts$")

    def test_every_tool_is_smoked_or_says_why_not(self):
        """Every tool of tools.json is called by the smoke spec, or named in its "not_smoked" with the reason (it
        needs an account or a key, sends or changes something outside, needs a device or a network CI does not give
        this server): a tool added without either fails here."""
        for name in servers():
            with self.subTest(server=name):
                spec = read_json("servers", name, "smoke.json")
                tools = read_json("servers", name, "tools.json")["tools"]
                called = {call["tool"] for call in spec.get("calls", []) if not call.get("absent")}
                why = spec.get("not_smoked", {})
                self.assertIsInstance(why, dict, f"{name}: not_smoked maps a tool to the reason")
                for tool, reason in why.items():
                    self.assertIn(tool, tools, f"{name}: not_smoked names {tool}, which it does not offer")
                    self.assertNotIn(tool, called, f"{name}: {tool} is called and named in not_smoked")
                    self.assertIsInstance(reason, str)
                    self.assertGreaterEqual(len(reason.strip()), 12, f"{name}: {tool}: say why it is not smoked")
                neither = sorted(set(tools) - called - set(why))
                self.assertEqual(neither, [], f"{name}: neither called by the smoke spec nor in its not_smoked")

    def test_the_smoke_spec_mounts_only_folders_the_entry_declares(self):
        for name in servers():
            with self.subTest(server=name):
                spec = read_json("servers", name, "smoke.json")
                entry = read_json("servers", name, "server.json")
                declared = {mount["target"]: mount for mount in entry.get("mounts", [])}
                for mount in spec.get("mounts", []):
                    self.assertIn(mount["target"], declared,
                                  f"{name}: the smoke mounts {mount['target']}, the entry does not offer it")
                    # the analysis servers read their input from /work; files, filesystem, exec, tasks and axross (with
                    # AXROSS_WRITE=1) write /work by design
                    if mount.get("writable") and name not in WORKSPACE_SERVERS and name not in ("files", "filesystem",
                                                                                                "axross"):
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


class JavaDecompilers(unittest.TestCase):
    """jadx and cfr: our own server code (the MCP SDK and the standard library) driving a pinned upstream release in a
    JVM - jadx 1.5.6's jar and CFR 0.152's jar by SHA-256, Debian's OpenJDK 21 by version; the input read-only at
    /work, no network, no variable, the limits the JVM needs recorded where sandbox-ai reads them."""

    JADX_ZIP = "545ea2be9c242511bc145755cf4bda2485ade42966e096f8b4d3da2a230e8974"
    JADX_JAR = "fe3e12c45acf75f92369685fd02d1d7a7323385dc725680a9b98a0dac0ea554b"
    CFR_JAR = "f686e8f3ded377d7bc87d216a90e9e9512df4156e75b06c655a16648ae8765b2"
    JDK = "21.0.13.1+2-1~deb13u1"

    def read(self, name, *parts):
        return (ROOT / "servers" / name).joinpath(*parts).read_text()

    def test_no_network_no_secret_and_the_input_read_only(self):
        for name in ("jadx", "cfr"):
            with self.subTest(server=name):
                entry = read_json("servers", name, "server.json")
                spec = read_json("servers", name, "smoke.json")
                self.assertEqual((entry["network"], spec["network"]), ("none", "none"))
                self.assertNotIn("hosts", entry)
                self.assertNotIn("env", entry)
                self.assertEqual(entry["category"], "Analysis: Files")
                self.assertEqual([m["target"] for m in entry["mounts"]], ["/work"])
                self.assertTrue(entry["mounts"][0]["required"])
                self.assertIn(":ro", entry["mounts"][0]["description"])
                self.assertEqual(spec["mounts"], [{"host": "${FIXTURES}", "target": "/work"}])
                tools = read_json("servers", name, "tools.json")
                self.assertEqual(tools["tools"], tools["read_only_tools"])
                called = {call["tool"] for call in spec["calls"] if not call.get("expect_error")}
                self.assertEqual(called, set(tools["tools"]), "every tool is called for real")
                self.assertTrue([call for call in spec["calls"] if call.get("expect_error")])
                provenance = self.read(name, "PROVENANCE.md")
                for tool in tools["tools"]:
                    self.assertIn(f"`{tool}`", provenance)

    def test_the_limits_the_jvm_needs_are_where_sandbox_ai_reads_them(self):
        jadx, cfr = read_json("servers", "jadx", "smoke.json"), read_json("servers", "cfr", "smoke.json")
        self.assertEqual((jadx["memory"], jadx["pids"], jadx["tmp"]), ("2g", 256, "256m"))
        self.assertEqual(cfr["memory"], "1g")
        self.assertIn("2g memory, 256 processes and a 256m /tmp", read_json("servers", "jadx", "server.json")["notes"])
        self.assertIn("Needs 1g memory", read_json("servers", "cfr", "server.json")["notes"])

    def test_the_releases_are_pinned_by_sha256_and_in_the_provenance(self):
        jadx, cfr = self.read("jadx", "Dockerfile"), self.read("cfr", "Dockerfile")
        self.assertIn("ARG JADX_URL=https://github.com/skylot/jadx/releases/download/v1.5.6/jadx-1.5.6.zip", jadx)
        self.assertIn(f"ARG JADX_SHA256={self.JADX_ZIP}", jadx)
        self.assertIn("ADD --checksum=sha256:${JADX_SHA256} ${JADX_URL}", jadx)
        self.assertIn(f"ARG JADX_JAR_SHA256={self.JADX_JAR}", jadx)
        self.assertEqual(jadx.count(self.JADX_JAR), 2, "the jar is checked where it is unpacked and in the image")
        self.assertIn("ARG CFR_URL=https://github.com/leibnitz27/cfr/releases/download/0.152/cfr-0.152.jar", cfr)
        self.assertIn(f"ARG CFR_SHA256={self.CFR_JAR}", cfr)
        self.assertIn("ADD --checksum=sha256:${CFR_SHA256} ${CFR_URL}", cfr)
        for name, text, pins in (("jadx", jadx, (self.JADX_ZIP, self.JADX_JAR)), ("cfr", cfr, (self.CFR_JAR,))):
            with self.subTest(server=name):
                self.assertIn(f"openjdk-21-jre-headless={self.JDK}", text)
                provenance = self.read(name, "PROVENANCE.md")
                for pin in pins + (self.JDK,):
                    self.assertIn(pin, provenance)
        self.assertIn(f"openjdk-21-jdk-headless={self.JDK}", jadx, "the bridge is compiled with the same JDK")
        # the JDK's JRE pinned beside it in the build stage: apt's solver otherwise picks the newer JRE of
        # trixie-security and refuses the pinned JDK (CI, 2026-11-21)
        build_stage = jadx[:jadx.index("\nFROM ${DEBIAN_IMAGE}\n", jadx.index("FROM ${DEBIAN_IMAGE} AS"))]
        self.assertIn(f"openjdk-21-jdk-headless={self.JDK} openjdk-21-jre-headless={self.JDK}", build_stage)
        # CFR prints its version on stderr: the check reads both
        self.assertIn('cfr-0.152.jar --version 2>&1', cfr)
        self.assertIn("javac --release 21 -Xlint:all -Werror", jadx)

    def test_our_code_only_and_the_shared_lock(self):
        for name in ("jadx", "cfr"):
            with self.subTest(server=name):
                folder = ROOT / "servers" / name
                self.assertEqual((folder / "requirements.txt").read_bytes().replace(f"servers/{name}/".encode(), b""),
                                 (ROOT / "servers" / "web-fetch" / "requirements.txt").read_bytes().replace(
                                     b"servers/web-fetch/", b""))
                self.assertEqual((folder / "requirements.in").read_text(), "mcp==1.30.0\n")
                source = (folder / "src" / "server.py").read_text()
                imports = set(re.findall(r"^(?:import|from) ([A-Za-z_.]+)", source, re.M))
                self.assertEqual({i for i in imports if i.split(".")[0] == "mcp"},
                                 {"mcp", "mcp.server.fastmcp", "mcp.server.fastmcp.exceptions", "mcp.types"})
                self.assertFalse({i.split(".")[0] for i in imports} & {"socket", "urllib", "http", "ssl", "requests",
                                                                        "httpx", "ctypes", "pickle", "importlib"})
                self.assertNotRegex(source, r"https?://", "no request anywhere")
                for word in ("eval(", "exec(", "os.system", "shell=True", "os.environ", "getenv", "follow_symlinks=True",
                             "os.chmod", "os.chown", "os.rename", "os.replace"):
                    self.assertNotIn(word, source)
                # the one place a process starts: the JVM, with an empty environment and only the input's descriptor
                self.assertEqual(source.count("subprocess.Popen("), 1)
                self.assertEqual(len(re.findall(r'env=\{"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": ', source)), 1)
                self.assertIn('os.symlink(f"/proc/self/fd/{', source)
                self.assertIn("start_new_session=True", source)
                self.assertIn("DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW", source)
                self.assertIn("READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK", source)
                self.assertIn("MAX_LINES = 400", source)
                self.assertIn("MAX_CHARS = 24_000", source)
                self.assertIn("mcp._mcp_server.request_handlers.pop(_request, None)", source, "tools only")

    def test_the_bridge_loads_only_the_named_plugins_and_writes_nothing(self):
        bridge = self.read("jadx", "src", "JadxBridge.java")
        self.assertIn("args.setPluginLoader(new JadxPluginLoader() {", bridge)
        self.assertIn("System.setOut(System.err);", bridge)
        self.assertIn(".setLevel(ch.qos.logback.classic.Level.OFF);", bridge)
        for word in ("java.net.", "ProcessBuilder", "Runtime.getRuntime", "FileWriter", "Files.write", ".save(",
                     "saveSources", "saveResources", "JadxExternalPluginsLoader", "JadxBasePluginLoader",
                     "RenameMappingsPlugin", "JavaConvertPlugin", "System.getenv", "ScriptEngine"):
            self.assertNotIn(word, bridge)
        plugins = re.findall(r"new (\w+Plugin)\(\)", bridge)
        self.assertEqual(plugins, ["DexInputPlugin", "JavaInputPlugin", "SmaliInputPlugin", "XApkInputPlugin",
                                   "ApkmInputPlugin", "ApksInputPlugin", "AabInputPlugin", "KotlinMetadataPlugin",
                                   "KotlinSmapPlugin"])

    def test_cfr_gets_only_its_three_options_from_a_call(self):
        source = self.read("cfr", "src", "server.py")
        flags = set(re.findall(r'"(--[a-z]+)"', source))
        self.assertEqual(flags, {"--renamedupmembers", "--renameillegalidents", "--antiobf", "--jarfilter",
                                 "--methodname", "--extraclasspath", "--analyseas", "--silent"})


class AndroidTools(unittest.TestCase):
    """smali (servers/smali): our own server code driving pinned upstream releases in a JVM - Google's own
    smali/baksmali 3.0.10 jars from Google's Maven repository and the runtime dependencies their POMs name from Maven
    Central, each by URL and SHA-256 (the published checksums checked), apktool 3.0.3 by the SHA-256 GitHub
    publishes, apktool's own aapt2 and framework taken out of its jar by SHA-256, Debian's zipalign and apksigner by
    version; the apps read-only at /work, everything written in /out, no network, no variable, a throwaway signing
    key per call, the limits the JVM needs where sandbox-ai reads them."""

    GOOGLE = "https://dl.google.com/dl/android/maven2"
    CENTRAL = "https://repo1.maven.org/maven2"
    #: coordinate -> (the Dockerfile's ARG prefix, SHA-256): Google's four jars and exactly the runtime dependencies
    #: their POMs name (compile and runtime scope, transitively, nearest wins), resolved from the POMs 2026-11-22.
    SMALI_JARS = {
        "com.android.tools.smali:smali:3.0.10":
            ("SMALI", "b54c34f7a1b769b1e637f8a26909c68f399c273f3e5cde3e308e91107c135305"),
        "com.android.tools.smali:smali-baksmali:3.0.10":
            ("BAKSMALI", "7d6578dfe5c44f1984b64268e91834432b0942d49e08186a501039dd92b58213"),
        "com.android.tools.smali:smali-dexlib2:3.0.10":
            ("DEXLIB2", "688dee6a46962a4dd1774b64be926534b0b6504bfd5d5c9f89c0f5af284f50c1"),
        "com.android.tools.smali:smali-util:3.0.10":
            ("SMALI_UTIL", "cc2ef8349765644e4b15371f2c9f77d69b5412a094a38fe5fd992a124b7322fe"),
        "com.google.guava:guava:31.1-android":
            ("GUAVA", "32ac2ed709d96d278b5d2e3e5cea178fa4939939c525fb647532f013308db309"),
        "com.google.guava:failureaccess:1.0.1":
            ("FAILUREACCESS", "a171ee4c734dd2da837e4b16be9df4661afab72a41adaf31eb84dfdaf936ca26"),
        "com.google.guava:listenablefuture:9999.0-empty-to-avoid-conflict-with-guava":
            ("LISTENABLEFUTURE", "b372a037d4230aa57fbeffdef30fd6123f9c0c2db85d0aced00c91b974f33f99"),
        "com.google.code.findbugs:jsr305:3.0.2":
            ("JSR305", "766ad2a0783f2687962c8ad74ceecc38a28b9f72a2d085ee438b7813e928d0c7"),
        "org.checkerframework:checker-qual:3.12.0":
            ("CHECKER_QUAL", "ff10785ac2a357ec5de9c293cb982a2cbb605c0309ea4cc1cb9b9bc6dbe7f3cb"),
        "com.google.errorprone:error_prone_annotations:2.11.0":
            ("ERROR_PRONE", "721cb91842b46fa056847d104d5225c8b8e1e8b62263b993051e1e5a0137b7ec"),
        "com.google.j2objc:j2objc-annotations:1.3":
            ("J2OBJC", "21af30c92267bd6122c0e0b4d20cccb6641a37eaf956c6540ec471d584e64a7b"),
        "org.jcommander:jcommander:1.85":
            ("JCOMMANDER", "fa7552d2831a2b20778d86851d093edca68fbc0a77f792b6223110e4fae67a70"),
        "org.antlr:antlr:3.5.2":
            ("ANTLR3", "5ac36c2acfb0a0f3d37dafe20b5b570f2643e2d000c648d44503c2738be643df"),
        "org.antlr:antlr-runtime:3.5.2":
            ("ANTLR3_RUNTIME", "ce3fc8ecb10f39e9a3cddcbb2ce350d272d9cd3d0b1e18e6fe73c3b9389c8734"),
        "org.antlr:ST4:4.0.8":
            ("ST4", "58caabc40c9f74b0b5993fd868e0f64a50c0759094e6a251aaafad98edfc7a3b"),
        "org.antlr:stringtemplate:3.2.1":
            ("STRINGTEMPLATE", "f66ce72e965e5301cb0f020e54d2ba6ad76feb91b3cbfc30dbbf00c06a6df6d7"),
        "antlr:antlr:2.7.7":
            ("ANTLR2", "88fbda4b912596b9f56e8e12e580cc954bacfb51776ecfddd3e18fc1cf56dc4c"),
    }
    #: The class path of each tool: its jar first, then its POM's runtime closure in Maven's order.
    BAKSMALI_CLASSPATH = ["smali-baksmali-3.0.10", "smali-dexlib2-3.0.10", "smali-util-3.0.10", "guava-31.1-android",
                          "jcommander-1.85", "jsr305-3.0.2", "failureaccess-1.0.1",
                          "listenablefuture-9999.0-empty-to-avoid-conflict-with-guava", "checker-qual-3.12.0",
                          "error_prone_annotations-2.11.0", "j2objc-annotations-1.3"]
    SMALI_CLASSPATH = ["smali-3.0.10", "smali-dexlib2-3.0.10", "antlr-3.5.2", "smali-util-3.0.10",
                       "antlr-runtime-3.5.2", "jcommander-1.85", "stringtemplate-3.2.1", "guava-31.1-android",
                       "jsr305-3.0.2", "ST4-4.0.8", "antlr-2.7.7", "failureaccess-1.0.1",
                       "listenablefuture-9999.0-empty-to-avoid-conflict-with-guava", "checker-qual-3.12.0",
                       "error_prone_annotations-2.11.0", "j2objc-annotations-1.3"]
    APKTOOL_JAR = "dbf930b076c6b9be08d57c449cacefc3bdd6b71ebd59b3066fc0e1f5b14f9423"
    APKTOOL_AAPT2 = "df312db814c018019b2b79a993b041b738d7b76f4a8f28da25bc874a026368cc"
    APKTOOL_FRAMEWORK = "5dd984016ed5a5eb0eef866e2c6e8cd352e1427828ec23adb18005cf5648f3d7"
    JDK = "21.0.13.1+2-1~deb13u1"
    #: The upstream commit the jars are built from (google/smali's main head, "Version 3.0.10").
    SMALI_COMMIT = "7a325fc45dc02d0e428da5b54685e5887903efca"

    def read(self, *parts):
        return (ROOT / "servers" / "smali").joinpath(*parts).read_text()

    def test_no_network_no_secret_the_apps_read_only_and_out_writable(self):
        entry = read_json("servers", "smali", "server.json")
        spec = read_json("servers", "smali", "smoke.json")
        self.assertEqual((entry["network"], spec["network"]), ("none", "none"))
        self.assertNotIn("hosts", entry)
        self.assertNotIn("env", entry)
        self.assertEqual(entry["category"], "Analysis: Files")
        self.assertEqual([m["target"] for m in entry["mounts"]], ["/work", "/out"])
        work, out = entry["mounts"]
        self.assertTrue(work["required"])
        self.assertIn(":ro", work["description"])
        self.assertIn(":rw", out["description"])
        self.assertEqual(spec["mounts"][0], {"host": "${FIXTURES}", "target": "/work"})
        self.assertEqual(spec["mounts"][1], {"target": "/out", "fresh": True, "writable": True})

    def test_every_tool_is_called_for_real_and_refusals_are_tested(self):
        spec = read_json("servers", "smali", "smoke.json")
        tools = read_json("servers", "smali", "tools.json")
        called = {call["tool"] for call in spec["calls"] if not call.get("expect_error")}
        self.assertEqual(called, set(tools["tools"]), "every tool is called for real")
        self.assertGreaterEqual(len([c for c in spec["calls"] if c.get("expect_error")]), 5)
        self.assertEqual(sorted(tools["read_only_tools"]),
                         ["get_smali", "list_classes", "list_dex", "list_files", "list_output", "search_smali"])
        self.assertTrue(set(tools["read_only_tools"]) < set(tools["tools"]), "the write tools are not read-only")
        provenance = self.read("PROVENANCE.md")
        for tool in tools["tools"]:
            self.assertIn(f"`{tool}`", provenance)

    def test_the_limits_the_jvm_needs_are_where_sandbox_ai_reads_them(self):
        spec = read_json("servers", "smali", "smoke.json")
        self.assertEqual((spec["memory"], spec["pids"], spec["tmp"]), ("2g", 256, "512m"))
        self.assertIn("2g memory, 256 processes and a 512m /tmp", read_json("servers", "smali", "server.json")["notes"])

    def test_the_releases_are_pinned_by_sha256_and_in_the_provenance(self):
        dockerfile, provenance = self.read("Dockerfile"), self.read("PROVENANCE.md")
        for coordinate, (prefix, pin) in self.SMALI_JARS.items():
            with self.subTest(jar=coordinate):
                group, artifact, version = coordinate.split(":")
                repository = self.GOOGLE if group == "com.android.tools.smali" else self.CENTRAL
                url = f"{repository}/{group.replace('.', '/')}/{artifact}/{version}/{artifact}-{version}.jar"
                self.assertIn(f"ARG {prefix}_URL={url}\n", dockerfile)
                self.assertIn(f"ARG {prefix}_SHA256={pin}\n", dockerfile)
                self.assertIn(f"ADD --checksum=sha256:${{{prefix}_SHA256}} ${{{prefix}_URL}} "
                              f"/build/smali/{artifact}-{version}.jar\n", dockerfile)
                self.assertIn(pin, provenance)
                self.assertIn(f"`{coordinate}`", provenance)
        self.assertIn("https://github.com/iBotPeaches/Apktool/releases/download/v3.0.3/apktool_3.0.3.jar", dockerfile)
        self.assertIn(f"ARG APKTOOL_SHA256={self.APKTOOL_JAR}", dockerfile)
        self.assertIn(self.APKTOOL_JAR, provenance)
        # Google's own jars only: nothing of baksmali/smali's fat release jars is left
        for source in (dockerfile, self.read("src", "server.py"), self.read("maven-central.json")):
            self.assertNotIn("fat-release", source)
            self.assertNotIn("github.com/baksmali", source)
        # the two files taken out of apktool's jar are checked where they are unpacked
        for pin in (self.APKTOOL_AAPT2, self.APKTOOL_FRAMEWORK):
            self.assertIn(pin, dockerfile)
            self.assertIn(pin, provenance)
        self.assertIn("sha256sum --check --strict", dockerfile)
        self.assertIn(self.SMALI_COMMIT, provenance, "the upstream commit the jars are built from")
        for version in (f"openjdk-21-jre-headless={self.JDK}", "zipalign=1:10.0.0+r36-1.1",
                        "libapksig-java=35.0.2-1", "apksigner=35.0.2-1"):
            self.assertIn(version, dockerfile)
            self.assertIn(version.split("=")[0], provenance)
        self.assertIn(self.JDK, provenance)
        # nothing is unpacked or downloaded while the server runs
        self.assertIn("--aapt", self.read("src", "server.py"))
        self.assertIn("/opt/apktool/framework", self.read("src", "server.py"))

    def test_baksmali_and_smali_run_from_class_paths_of_the_shipped_jars(self):
        dockerfile, source = self.read("Dockerfile"), self.read("src", "server.py")
        for name, jars, main in (("BAKSMALI", self.BAKSMALI_CLASSPATH, "com.android.tools.smali.baksmali.Main"),
                                 ("SMALI", self.SMALI_CLASSPATH, "com.android.tools.smali.smali.Main")):
            with self.subTest(tool=name):
                class_path = ":".join(f"/opt/smali/{jar}.jar" for jar in jars)
                prefix = re.escape(f'{name}_CLASSPATH = ":".join(f"/opt/smali/{{jar}}.jar" for jar in (')
                found = re.search(rf"^{prefix}(.*?)\)\)$", source, re.M | re.S)
                self.assertIsNotNone(found, f"{name}_CLASSPATH")
                self.assertEqual(list(ast.literal_eval(f"({found.group(1)})")), jars)
                self.assertIn(f'{name}_MAIN = "{main}"', source)
                # the image's build-time check runs the very class path and main class the server does
                self.assertIn(f"ARG {name}_CLASSPATH={class_path}\n", dockerfile)
                self.assertIn(f'-cp "${{{name}_CLASSPATH}}" {main} --version', dockerfile)
        shipped = {f"{c.split(':')[1]}-{c.split(':')[2]}" for c in self.SMALI_JARS}
        self.assertEqual(set(self.BAKSMALI_CLASSPATH) | set(self.SMALI_CLASSPATH), shipped)
        spec = read_json("servers", "smali", "maven-central.json")
        self.assertEqual(sorted(jar["coordinate"] for jar in spec["jars"]), sorted(self.SMALI_JARS))

    def test_every_bundled_library_has_its_licence(self):
        licences = {path.name for path in (ROOT / "servers" / "smali" / "LICENSES").iterdir()}
        for name in ("smali-baksmali-LICENSE.txt", "guava-failureaccess-listenablefuture-Apache-2.0.txt",
                     "jsr305-Apache-2.0.txt", "checker-qual-MIT.txt", "error-prone-annotations-Apache-2.0.txt",
                     "j2objc-annotations-Apache-2.0.txt", "jcommander-Apache-2.0.txt",
                     "antlr3-antlr-runtime-ST4-stringtemplate-BSD-3-Clause.txt", "antlr2-public-domain.txt"):
            self.assertIn(name, licences)
        entry = read_json("servers", "smali", "server.json")
        for licence in ("BSD-3-Clause", "Apache-2.0", "MIT", "public domain"):
            self.assertIn(licence, entry["license"])

    def test_our_code_only_and_the_shared_lock(self):
        folder = ROOT / "servers" / "smali"
        self.assertEqual((folder / "requirements.txt").read_bytes().replace(b"servers/smali/", b""),
                         (ROOT / "servers" / "web-fetch" / "requirements.txt").read_bytes().replace(
                             b"servers/web-fetch/", b""))
        self.assertEqual((folder / "requirements.in").read_text(), "mcp==1.30.0\n")
        source = (folder / "src" / "server.py").read_text()
        imports = set(re.findall(r"^(?:import|from) ([A-Za-z_.]+)", source, re.M))
        self.assertEqual({i for i in imports if i.split(".")[0] == "mcp"},
                         {"mcp", "mcp.server.fastmcp", "mcp.server.fastmcp.exceptions", "mcp.types"})
        self.assertFalse({i.split(".")[0] for i in imports} & {"socket", "urllib", "http", "ssl", "requests",
                                                               "httpx", "ctypes", "pickle", "importlib"})
        self.assertNotRegex(source, r"https?://", "no request anywhere")
        for word in ("eval(", "exec(", "os.system", "shell=True", "os.environ", "getenv", "follow_symlinks=True",
                     "os.chmod", "os.chown"):
            self.assertNotIn(word, source)
        # the one place a process starts: with an empty environment and only the checked descriptor
        self.assertEqual(source.count("subprocess.Popen("), 1)
        self.assertEqual(len(re.findall(r'env=\{"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8",', source)), 1)
        self.assertIn('os.symlink(f"/proc/self/fd/{', source)
        self.assertIn("start_new_session=True", source)
        self.assertIn("DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW", source)
        self.assertIn("READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK", source)
        self.assertIn("MAX_LINES = 400", source)
        self.assertIn("MAX_CHARS = 24_000", source)
        self.assertIn("mcp._mcp_server.request_handlers.pop(_request, None)", source, "tools only")

    def test_apktool_gets_only_the_flags_a_call_may_set(self):
        source = self.read("src", "server.py")
        flags = set(re.findall(r'"(--[a-z0-9-]+)"', source))
        self.assertEqual(flags, {"--no-res", "--no-src", "--only-manifest", "--no-debug-info", "--keep-broken-res",
                                 "--debuggable", "--net-sec-conf", "--copy-original", "--aapt", "--frame-path",
                                 "--jobs", "--force", "--output", "--classes", "--debug-info", "--use-locals",
                                 "--verbose", "--out", "--ks", "--ks-pass", "--ks-key-alias", "--key-pass",
                                 "--v1-signing-enabled", "--v2-signing-enabled", "--v3-signing-enabled",
                                 "--print-certs"})
        for never in ("--lib", "--frame-tag", "--outputdir", "--no-apk", "--ks-key-alias-pass"):
            self.assertNotIn(f'"{never}"', source)

    def test_the_signing_key_is_a_throwaway_one_and_never_leaves_the_scratch_folder(self):
        source = self.read("src", "server.py")
        self.assertIn("-genkeypair", source)
        self.assertIn("secrets.token_urlsafe(24)", source)
        self.assertIn('"-validity", "1"', source)
        self.assertIn("throwaway", source)
        self.assertIn("scratch.close()   # the keystore and the password go with it", source)
        for never in ("KEYSTORE", "SANDBOX_AI_KEY", "release-key", "--ks-pass env:", "--ks-pass file:"):
            self.assertNotIn(never, source)


class FridaServer(unittest.TestCase):
    """frida (servers/frida): our own server code on frida's own bindings, one pinned version for the client and for
    every frida-server/frida-gadget in the image (each the release file, by the SHA-256 GitHub publishes); it reaches
    only the endpoints the human configures, writes only /out, and nothing on a device without FRIDA_WRITE=1."""

    VERSION = "17.25.2"
    #: Frida publishes a server and a gadget per ABI; the image carries every Android one and Linux x86_64/arm64.
    BINARIES = {("android", "arm"), ("android", "arm64"), ("android", "x86"), ("android", "x86_64"),
                ("linux", "x86_64"), ("linux", "arm64")}

    def read(self, *parts):
        return (ROOT / "servers" / "frida").joinpath(*parts).read_text()

    def test_the_client_and_every_binary_are_the_same_pinned_version(self):
        dockerfile = self.read("Dockerfile")
        self.assertIn(f"frida=={self.VERSION}", self.read("requirements.in"))
        self.assertIn(f"frida=={self.VERSION} \\", self.read("requirements.txt"))
        locked = self.read("requirements.txt").split(f"frida=={self.VERSION}")[1].split("# via")[0]
        self.assertEqual(len(re.findall(r"--hash=sha256:[0-9a-f]{64}", locked)), 2, "the two linux x86_64 wheels")
        self.assertIn(f"assert frida.__version__ == '{self.VERSION}'", dockerfile)
        for platform, abi in sorted(self.BINARIES):
            for kind, suffix in (("server", ".xz"), ("gadget", ".so.xz")):
                name = f"frida-{kind}-{self.VERSION}-{platform}-{abi}{suffix}"
                with self.subTest(binary=name):
                    self.assertIn(f"/releases/download/{self.VERSION}/{name}", dockerfile)
                    self.assertIn(f"/opt/frida/{platform}/{abi}/{name}", dockerfile)
        self.assertEqual(len(re.findall(r"^ADD --checksum=sha256:\$\{[A-Z0-9_]+\} ", dockerfile, re.M)),
                         2 * len(self.BINARIES), "every binary by the digest GitHub publishes")
        self.assertEqual(len(set(re.findall(r"^ARG ([A-Z0-9_]+_SHA256)=[0-9a-f]{64}$", dockerfile, re.M))),
                         2 * len(self.BINARIES), "one ARG per binary, no name used twice")
        self.assertIn(self.VERSION, self.read("PROVENANCE.md"))
        for digest in re.findall(r"^ARG [A-Z0-9_]+_SHA256=([0-9a-f]{64})$", dockerfile, re.M):
            self.assertIn(digest, self.read("PROVENANCE.md"), "every digest is in PROVENANCE.md")
        self.assertIn(f'FRIDA_VERSION = "{self.VERSION}"', self.read("src", "server.py"))

    def test_the_binaries_stay_packed_and_nothing_in_the_image_is_executable(self):
        dockerfile = self.read("Dockerfile")
        # files lose every x bit, folders keep theirs (X): "a-x" alone made /opt/frida/android untraversable for the
        # server's user, and list_abis found 0 binaries in CI (2026-11-21)
        self.assertIn("chmod -R a-x,a+rX /opt/frida", dockerfile)
        self.assertNotIn("chmod -R a-x,a+r /opt/frida", dockerfile)
        self.assertNotIn("unxz", dockerfile)
        # and the server's own user sees every binary the image adds before the image ships
        added = len(re.findall(r"^ADD --checksum=sha256:\S+ https://github\.com/frida/frida/releases/download/\S+ "
                               r"/opt/frida/(?:android|linux)/[a-z0-9_]+/frida-(?:server|gadget)-\S+\.xz$", dockerfile, re.M))
        self.assertEqual(added, 12)
        after_user = dockerfile[dockerfile.index("USER 10001:10001"):]
        self.assertRegex(after_user, r"RUN /opt/venv/bin/python -c .*glob\.glob\('/opt/frida/\*/\*/\*\.xz'\).*"
                                     rf"== {added}, found")
        self.assertIn("lzma.open", self.read("src", "server.py"))

    def test_it_reaches_only_what_the_human_configured(self):
        entry = read_json("servers", "frida", "server.json")
        self.assertEqual(entry["network"], "full")
        self.assertNotIn("hosts", entry)
        self.assertEqual([var["name"] for var in entry["env"]],
                         ["FRIDA_DEVICE", "FRIDA_ADB_SERVER", "FRIDA_WRITE"])
        for var in entry["env"]:
            self.assertFalse(var["secret"], var["name"])
            self.assertFalse(var["required"], var["name"])
        self.assertIn("--allow-tcp", entry["notes"])
        self.assertIn("NOT reachable from an MCP server's container", entry["notes"])
        self.assertEqual(entry["tor"]["support"], "limited")
        source = self.read("src", "server.py")
        # the only places a connection is made: the configured frida-server, and adb against the configured server
        self.assertEqual(source.count("add_remote_device("), 1)
        self.assertEqual(source.count("subprocess.run("), 1)
        self.assertIn('[ADB, "-H", host, "-P", str(port)]', source)
        self.assertNotIn("get_usb_device(", source)
        self.assertNotIn("get_local_device(", source)
        for word in ("urllib", "requests", "httpx", "socket.", "eval(", "exec(", "shell=True"):
            self.assertNotIn(word, source)

    def test_fridas_local_device_is_never_offered(self):
        source = self.read("src", "server.py")
        self.assertIn('if wanted in ("local", "barebone", "socket"):', source)
        self.assertIn('device.type == "usb"', source)
        self.assertIn("never offered", source)
        # list_devices only ever shows the configured remote device and the adb server's USB devices
        self.assertIn("def all_devices(self)", source)
        self.assertRegex(source, r'def usb_devices\(self\)(?:.|\n)*?device\.type == "usb"')

    def test_nothing_on_a_device_changes_without_the_write_gate(self):
        source = self.read("src", "server.py")
        tools = read_json("servers", "frida", "tools.json")
        self.assertEqual(sorted(set(tools["tools"]) - set(tools["read_only_tools"])),
                         ["attach", "detach", "export_server", "kill", "push_server", "resume", "run_script",
                          "spawn"])
        for tool in ("spawn", "resume", "kill", "push_server"):
            self.assertIn(f'write_allowed("{tool}")', source)
        self.assertIn('os.environ.get("FRIDA_WRITE", "")', source)

    def test_the_limits_and_folders_are_where_sandbox_ai_reads_them(self):
        entry = read_json("servers", "frida", "server.json")
        spec = read_json("servers", "frida", "smoke.json")
        self.assertEqual([m["target"] for m in entry["mounts"]], ["/work", "/out"])
        self.assertIn(":ro", entry["mounts"][0]["description"])
        self.assertIn(":rw", entry["mounts"][1]["description"])
        self.assertEqual((spec["memory"], spec["pids"]), ("2g", 512))
        self.assertIn("2g memory and 512 processes", entry["notes"])
        # the smoke run has no device: every call that needs one must be a refused call
        needs_device = {"list_devices", "list_processes", "list_applications", "attach", "spawn", "resume", "kill",
                        "push_server", "run_script", "enumerate_modules", "enumerate_exports", "detach"}
        for call in spec["calls"]:
            if call["tool"] in needs_device:
                self.assertTrue(call.get("expect_error"), call["tool"])
        self.assertGreaterEqual(len([c for c in spec["calls"] if c.get("expect_error")]), 6)
        provenance = self.read("PROVENANCE.md")
        for tool in tools_of("frida"):
            self.assertIn(f"`{tool}`", provenance)


def tools_of(name):
    return read_json("servers", name, "tools.json")["tools"]


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

    TOOLS_ONLY = "0002-tools-only.patch"

    def test_the_patch_changes_only_r2api_and_is_applied_and_checked(self):
        self.assertEqual(sorted(path.name for path in (self.FOLDER / "patches").iterdir()), [self.PATCH, self.TOOLS_ONLY])
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

    def test_tools_only(self):
        """r2mcp 1.9.0 announces the prompts and resources capabilities whatever it has: -N loads no prompt, and
        resources/list is always empty. Agents then offer a model resource tools, which local models took for the way
        to the server's tools. Patch 0002 announces prompts only when they are loaded and no resources; both patched
        files are checked by SHA-256, and the image build refuses an initialize answer with either capability."""
        text = (self.FOLDER / "patches" / self.TOOLS_ONLY).read_text()
        self.assertEqual(set(re.findall(r"^\+\+\+ b/(\S+)$", text, re.M)), {"src/main.c", "src/r2mcp.c"})
        self.assertIn("+\t\t.capabilities = { .tools = true, .prompts = load_prompts, .resources = false },", text)
        self.assertIn("+\tif (ss->capabilities.prompts) {", text)
        self.assertIn("+\tif (ss->capabilities.resources) {", text)
        digest = hashlib.sha256((self.FOLDER / "patches" / self.TOOLS_ONLY).read_bytes()).hexdigest()
        self.assertIn(digest, self.provenance, "PROVENANCE.md names another SHA-256")
        for name in ("src/r2mcp.c", "src/main.c"):
            patched = re.search(r'echo "([0-9a-f]{64})  %s" \| sha256sum --check --strict' % re.escape(name),
                                self.dockerfile)
            self.assertTrue(patched, f"the patched {name} is checked by SHA-256")
            self.assertIn(patched.group(1), self.provenance)
        check = re.search(r"(?ms)^# tools only: .*?\n(RUN .*?[^\\])\n", self.dockerfile)
        self.assertTrue(check, "the image build checks the initialize answer")
        for text in ('"method":"initialize"', "grep -q '\"tools\"'", "! grep -q '\"resources\"'",
                     "! grep -q '\"prompts\"'", "-s /work -g none -N"):
            self.assertIn(text, check.group(1))

    def test_the_entrypoint_offers_exactly_the_reviewed_tools(self):
        # r2mcp-run holds the flags (70 words; the Bubblewrap form takes at most 32 of an ENTRYPOINT), under tini
        self.assertEqual(self.entrypoint, ["/usr/bin/tini", "-s", "--", "/opt/radare2/bin/r2mcp-run"])
        self.assertIn("COPY r2mcp-run /opt/radare2/bin/r2mcp-run\n", self.dockerfile)
        self.assertIn("chmod 0755 /opt/radare2/bin/r2mcp-run", self.dockerfile)
        script = (self.FOLDER / "r2mcp-run").read_text()
        self.assertTrue(script.startswith("#!/bin/sh\n"))
        command = [line for line in script.replace("\\\n", " ").splitlines() if not line.startswith("#")]
        self.assertEqual(len(command), 1, "one command, nothing else runs")
        words = command[0].split()
        self.assertEqual(words[0], "exec", "r2mcp replaces the shell")
        self.assertNotRegex(command[0], r"[$`;|&<>\"'*?]", "no expansion (no \"$@\": nothing a run line adds "
                                                         "reaches r2mcp), no second command")
        self.entrypoint = words[1:]
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
        calls = read_json("servers", "radare2", "smoke.json")["calls"]
        refused = [call["arguments"]["file_path"] for call in calls
                   if call["tool"] == "open_file" and call.get("expect_error")]
        self.assertEqual(refused, ["/etc/passwd", "nocache:///etc/passwd"])
        # close_file closes the open file; after the refused opens it finds none open: neither opened anything
        # (in one connection; r2mcp answers any tool but open_file without a file with this JSON-RPC error).
        self.assertEqual([(call["tool"], call["expect"], bool(call.get("expect_error"))) for call in calls[-4:]],
                         [("close_file", "File closed successfully.", False),
                          ("open_file", "Failed to open file", True), ("open_file", "Failed to open file", True),
                          ("close_file", "Use the open_file method before calling any other method", True)])

    def test_the_smoke_spec_expects_radare2s_own_prototype(self):
        """Before set_function_prototype, the one radare2's analysis gives: strcmp's argument on the parameter."""
        prototypes = [call["expect"] for call in read_json("servers", "radare2", "smoke.json")["calls"]
                      if call["tool"] == "get_function_prototype"]
        self.assertEqual(prototypes, ["void sym.check_password (const char *s1);",
                                      "int check_password (const char *input);"])


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
        for package in ("ruby3.3=3.3.14-0+deb13u1", "libruby3.3=3.3.14-0+deb13u1", "ruby-addressable=2.8.7-2",
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


class Files(unittest.TestCase):
    """The workspace file server: our own code on the shared lock, the standard library only, no network, /work the
    only folder written (tests/test_files.py has the server's own tests)."""

    def setUp(self):
        self.folder = ROOT / "servers" / "files"
        self.entry = read_json("servers", "files", "server.json")
        self.spec = read_json("servers", "files", "smoke.json")
        self.source = (self.folder / "src" / "server.py").read_text()

    def test_the_shared_lock_and_the_standard_library_only(self):
        self.assertEqual((self.folder / "requirements.txt").read_bytes().replace(b"servers/files/", b""),
                         (ROOT / "servers" / "web-fetch" / "requirements.txt").read_bytes().replace(
                             b"servers/web-fetch/", b""))
        self.assertEqual((self.folder / "requirements.in").read_text(), "mcp==1.30.0\n")
        self.assertIn("COPY src/server.py /opt/mcp/server.py", (self.folder / "Dockerfile").read_text())
        imports = set(re.findall(r"^(?:import ([a-z_.]+)(?: as \w+)?|from ([a-z_.]+) import .*)$", self.source, re.M))
        imports = {a or b for a, b in imports}
        self.assertEqual(imports - {"__future__", "contextlib", "difflib", "errno", "fnmatch", "hashlib", "json",
                                    "logging", "os", "re", "secrets", "shutil", "signal", "stat", "sys", "threading",
                                    "time", "unicodedata", "datetime"}, {"mcp.server.fastmcp", "mcp.types"})
        for word in ("subprocess", "import socket", "socket.", "urllib", "eval(", "exec(", "pickle", "ctypes", "os.system",
                     "os.chown", "follow_symlinks=True", "os.path.realpath"):
            self.assertNotIn(word, self.source, word)

    def test_no_network_and_the_folders(self):
        self.assertEqual((self.entry["network"], self.spec["network"]), ("none", "none"))
        self.assertNotIn("hosts", self.entry)
        mounts = {m["target"]: m for m in self.entry["mounts"]}
        self.assertEqual(list(mounts), ["/work", "/ref1", "/ref2", "/ref3"])
        self.assertTrue(mounts["/work"].get("required"))
        self.assertIn('WORK = "/work"', self.source)
        self.assertIn('REFS = ("/ref1", "/ref2", "/ref3")', self.source)
        for target in ("/ref1", "/ref2", "/ref3"):
            self.assertIn("read-only", mounts[target]["description"])
        self.assertEqual({var["name"] for var in self.entry["env"]}, {"FILES_READONLY", "FILES_MAX_BYTES", "FILES_TRASH"})
        self.assertFalse(any(var["secret"] for var in self.entry["env"]))

    def test_the_smoke_run_writes_repairs_and_refuses(self):
        refused = " ".join(call["expect"] for call in self.spec["calls"] if call.get("expect_error"))
        for expected in ("'..' is not allowed", "never followed", "outside the folders", "exists already"):
            self.assertIn(expected, refused)
        self.assertEqual([m["target"] for m in self.spec["mounts"]], ["/work"])
        self.assertIn({"path": "escape", "symlink": "/etc"}, self.spec["mounts"][0]["seed"])
        written = {call["tool"] for call in self.spec["calls"] if not call.get("expect_error")}
        self.assertTrue({"write_markdown", "edit_file", "read_file", "delete"} <= written)
        tools = read_json("servers", "files", "tools.json")
        provenance = (self.folder / "PROVENANCE.md").read_text()
        for tool in tools["tools"]:
            self.assertIn(f"`{tool}`", provenance)


class CodeSearch(unittest.TestCase):
    """The code search server: our own code on the shared lock, the standard library besides the MCP SDK, no network,
    the project read-only at /work, nothing written (tests/test_code_search.py has the server's own tests)."""

    def setUp(self):
        self.folder = ROOT / "servers" / "code-search"
        self.entry = read_json("servers", "code-search", "server.json")
        self.spec = read_json("servers", "code-search", "smoke.json")
        self.source = (self.folder / "src" / "server.py").read_text()

    def test_the_shared_lock_and_the_standard_library_only(self):
        self.assertEqual((self.folder / "requirements.txt").read_bytes().replace(b"servers/code-search/", b""),
                         (ROOT / "servers" / "web-fetch" / "requirements.txt").read_bytes().replace(
                             b"servers/web-fetch/", b""))
        self.assertEqual((self.folder / "requirements.in").read_text(), "mcp==1.30.0\n")
        self.assertIn("COPY src/server.py /opt/mcp/server.py", (self.folder / "Dockerfile").read_text())
        self.assertEqual(sorted(p.name for p in (self.folder / "src").iterdir() if p.name != "__pycache__"),
                         ["server.py"])
        imports = set(re.findall(r"^(?:import|from) ([A-Za-z_.]+)", self.source, re.M))
        self.assertEqual(imports - {"__future__", "ast", "contextlib", "difflib", "errno", "fnmatch", "logging", "os",
                                    "re", "signal", "stat", "sys", "threading", "time", "typing", "warnings"},
                         {"mcp.server.fastmcp", "mcp.server.fastmcp.exceptions", "mcp.types"})
        self.assertNotRegex(self.source, r"https?://", "no request anywhere")

    def test_nothing_is_written_executed_or_followed_out(self):
        for word in ("subprocess", "import socket", "socket.", "urllib", "eval(", "exec(", "compile(", "pickle", "ctypes", "os.system",
                     "os.write", "O_WRONLY", "O_RDWR", "O_CREAT", "os.mkdir", "os.makedirs", "os.remove", "os.unlink",
                     "os.rename", "os.replace", "os.rmdir", "shutil", "open(", "follow_symlinks=True",
                     "os.path.realpath", "os.chmod", "os.chown"):
            hits = [line for line in self.source.splitlines() if word in line and "os.open(" not in line
                    and "re.compile(" not in line]
            self.assertEqual(hits, [], word)
        self.assertIn("DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW", self.source)
        self.assertIn("READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK", self.source)

    def test_no_network_and_the_folders_read_only(self):
        self.assertEqual((self.entry["network"], self.spec["network"]), ("none", "none"))
        self.assertNotIn("hosts", self.entry)
        self.assertNotIn("env", self.entry)
        mounts = {m["target"]: m for m in self.entry["mounts"]}
        self.assertEqual(list(mounts), ["/work", "/ref1", "/ref2", "/ref3"])
        self.assertTrue(mounts["/work"].get("required"))
        for mount in mounts.values():
            self.assertIn(":ro", mount["description"])
            self.assertIn("read-only", mount["description"])
        self.assertIn('WORK = "/work"', self.source)
        self.assertIn('REFS = ("/ref1", "/ref2", "/ref3")', self.source)
        self.assertEqual([m["target"] for m in self.spec["mounts"]], ["/work"])
        self.assertNotIn("writable", self.spec["mounts"][0], "even the smoke run mounts the project read-only")

    def test_the_smoke_run_finds_reads_and_refuses(self):
        refused = " ".join(call["expect"] for call in self.spec["calls"] if call.get("expect_error"))
        for expected in ("'..' is not allowed", "never followed", "outside the folders", "can take forever"):
            self.assertIn(expected, refused)
        self.assertIn({"path": "escape", "symlink": "/etc"}, self.spec["mounts"][0]["seed"])
        tools = read_json("servers", "code-search", "tools.json")
        self.assertEqual(tools["tools"], tools["read_only_tools"])
        self.assertEqual({call["tool"] for call in self.spec["calls"] if not call.get("expect_error")},
                         set(tools["tools"]), "every tool is called for real")
        provenance = (self.folder / "PROVENANCE.md").read_text()
        for tool in tools["tools"]:
            self.assertIn(f"`{tool}`", provenance)


class YouTube(unittest.TestCase):
    """The upload server: our own code on the shared lock, Google's two API hosts and nothing else, /upload read-only
    and optional, a smoke run without an account (tests/test_youtube.py has the server's own tests)."""

    def setUp(self):
        self.folder = ROOT / "servers" / "youtube"
        self.entry = read_json("servers", "youtube", "server.json")
        self.spec = read_json("servers", "youtube", "smoke.json")

    def test_the_shared_lock_and_no_other_package(self):
        self.assertEqual((self.folder / "requirements.txt").read_bytes().replace(b"servers/youtube/", b""),
                         (ROOT / "servers" / "web-fetch" / "requirements.txt").read_bytes().replace(
                             b"servers/web-fetch/", b""))
        self.assertEqual((self.folder / "requirements.in").read_text(), "mcp==1.30.0\n")
        dockerfile = (self.folder / "Dockerfile").read_text()
        self.assertIn("COPY src/server.py src/authorize.py /opt/mcp/", dockerfile)
        imports = set(re.findall(r"^(?:import|from) ([a-z_.]+)", (self.folder / "src" / "server.py").read_text(), re.M))
        self.assertEqual(imports - {"__future__", "asyncio", "json", "logging", "os", "random", "re", "secrets", "stat",
                                    "sys", "time", "urllib.parse"}, {"httpx", "mcp.server.fastmcp", "mcp.types"})
        helper = set(re.findall(r"^(?:import|from) ([a-z_.]+)", (self.folder / "src" / "authorize.py").read_text(),
                                re.M))
        self.assertFalse({name for name in helper if name.split(".")[0] in ("httpx", "mcp", "requests", "google")},
                         "authorize.py runs on the host with the standard library only")

    def test_only_googles_api_hosts(self):
        hosts = ["oauth2.googleapis.com:443", "www.googleapis.com:443"]
        self.assertEqual((self.entry["network"], self.entry["hosts"]), ("allowlist", hosts))
        self.assertEqual((self.spec["network"], self.spec["hosts"]), ("allowlist", hosts))
        source = (self.folder / "src" / "server.py").read_text()
        contacted = set(re.findall(r"https://([a-z0-9.-]+)", source))
        self.assertEqual(contacted - {"www.googleapis.com", "oauth2.googleapis.com"},
                         {"youtu.be", "studio.youtube.com", "support.google.com", "www.youtube.com"},
                         "links in answers only: requests go to the two API hosts (HOSTS, checked per request)")
        self.assertIn('HOSTS = frozenset({"oauth2.googleapis.com", "www.googleapis.com"})', source)
        self.assertIn("follow_redirects=False", source)
        helper = (self.folder / "src" / "authorize.py").read_text()
        self.assertEqual(set(re.findall(r"https://([a-z0-9.-]+)", helper)) - {"www.googleapis.com"},
                         {"accounts.google.com", "oauth2.googleapis.com", "myaccount.google.com"})
        self.assertIn('HTTPServer(("127.0.0.1", port)', helper)

    def test_the_secrets_and_the_upload_folder(self):
        env = {var["name"]: var for var in self.entry["env"]}
        for name in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"):
            self.assertTrue(env[name]["secret"] and env[name]["required"], name)
        self.assertFalse(env["YOUTUBE_ALLOW_PUBLIC"]["secret"] or env["YOUTUBE_ALLOW_PUBLIC"]["required"])
        self.assertEqual([m["target"] for m in self.entry["mounts"]], ["/upload"])
        self.assertIn("read-only", self.entry["mounts"][0]["description"])
        self.assertFalse(self.entry["mounts"][0].get("required"), "list_my_videos and update_metadata need no files")
        for value in self.spec["env"].values():
            self.assertIn("smoke", value, "the smoke run has no account: placeholders only")

    def test_the_smoke_spec_refuses_without_an_account(self):
        refused = {call["expect"] for call in self.spec["calls"] if call.get("expect_error")}
        self.assertEqual(len(refused), len(self.spec["calls"]))
        for expected in ("only files under /upload", "public needs YOUTUBE_ALLOW_PUBLIC=1", "made_for_kids",
                         "Google refused the ", "no folder is mounted at /upload"):
            self.assertTrue(any(expected in text for text in refused), expected)
        provenance = (self.folder / "PROVENANCE.md").read_text()
        for tool in read_json("servers", "youtube", "tools.json")["tools"]:
            self.assertIn(f"`{tool}`", provenance)


class WorkspaceServers(unittest.TestCase):
    """exec and tasks: our own code on the shared lock, the standard library besides the MCP SDK, no network, the
    project folder writable at /work and nothing else (tests/test_exec.py and tests/test_tasks.py test the servers)."""

    STDLIB = {"__future__", "asyncio", "contextlib", "ctypes", "fcntl", "functools", "itertools", "json", "os", "re",
              "secrets", "selectors", "shutil", "signal", "stat", "subprocess", "sys", "tempfile", "threading", "time",
              "xml.etree.ElementTree"}

    def test_the_shared_lock_and_no_other_package(self):
        for name in WORKSPACE_SERVERS:
            with self.subTest(server=name):
                folder = ROOT / "servers" / name
                self.assertEqual((folder / "requirements.txt").read_bytes().replace(f"servers/{name}/".encode(), b""),
                                 (ROOT / "servers" / "web-fetch" / "requirements.txt").read_bytes().replace(
                                     b"servers/web-fetch/", b""))
                self.assertEqual((folder / "requirements.in").read_text(), "mcp==1.30.0\n")
                self.assertIn("COPY src/server.py /opt/mcp/server.py", (folder / "Dockerfile").read_text())
                source = (folder / "src" / "server.py").read_text()
                imports = set(re.findall(r"^(?:import|from) ([A-Za-z_.]+)", source, re.M))
                self.assertEqual(imports - self.STDLIB, {"mcp.server.fastmcp", "mcp.types"})
                self.assertNotRegex(source, r"https?://", "no request anywhere")

    def test_no_network_and_the_project_folder_writable(self):
        for name in WORKSPACE_SERVERS:
            with self.subTest(server=name):
                entry = read_json("servers", name, "server.json")
                spec = read_json("servers", name, "smoke.json")
                self.assertEqual((entry["network"], spec["network"]), ("none", "none"))
                self.assertNotIn("hosts", entry)
                self.assertEqual([(m["target"], m["required"]) for m in entry["mounts"]], [("/work", True)])
                self.assertIn("writable", entry["mounts"][0]["description"])
                self.assertEqual(spec["mounts"], [{"target": "/work", "fresh": True, "writable": True}])
                self.assertFalse([v for v in entry.get("env", []) if v["secret"] or v["required"]],
                                 "no secret, nothing required")
                recorded = read_json("servers", name, "tools.json")
                self.assertEqual(sorted(recorded["tools"]), sorted(list(recorded["write_tools"])
                                                                   + recorded["read_only_tools"]))
                provenance = (ROOT / "servers" / name / "PROVENANCE.md").read_text()
                for tool in recorded["tools"]:
                    self.assertIn(f"`{tool}`", provenance)

    def test_exec_gets_the_limits_its_commands_need_and_pins_its_tools(self):
        spec = read_json("servers", "exec", "smoke.json")
        self.assertEqual({key: spec[key] for key in ("memory", "pids", "tmp")}, {"memory": "2g", "pids": 512,
                                                                              "tmp": "512m"})
        dockerfile = (ROOT / "servers" / "exec" / "Dockerfile").read_text()
        for package in ("git=", "make=", "procps=", "python3-pytest=", "python3-pyflakes=", "python3-yaml=",
                        "shellcheck=", "nodejs="):
            self.assertIn(package, dockerfile)
        self.assertNotIn("npm=", dockerfile)
        refused = {call["expect"] for call in spec["calls"] if call.get("expect_error")}
        for expected in ("is outside /work", "leads outside /work through a symbolic link"):
            self.assertTrue(any(expected in text for text in refused), expected)
        texts = {call["expect"] for call in spec["calls"]}
        for expected in ("TIMED OUT after", "lines omitted", "Permission denied", "FAILED test_calc.py::test_wrong"):
            self.assertTrue(any(expected in text for text in texts), expected)
class Bluesky(unittest.TestCase):
    """The posting server: our own code on the shared lock, the PDS and Bluesky's public AppView and nothing else,
    read-only unless BLUESKY_WRITE=1, /upload read-only and optional, a smoke run without an account
    (tests/test_bluesky.py has the server's own tests)."""

    def setUp(self):
        self.folder = ROOT / "servers" / "bluesky"
        self.entry = read_json("servers", "bluesky", "server.json")
        self.spec = read_json("servers", "bluesky", "smoke.json")
        self.tools = read_json("servers", "bluesky", "tools.json")

    def test_the_shared_lock_and_no_other_package(self):
        self.assertEqual((self.folder / "requirements.txt").read_bytes().replace(b"servers/bluesky/", b""),
                         (ROOT / "servers" / "web-fetch" / "requirements.txt").read_bytes().replace(
                             b"servers/web-fetch/", b""))
        self.assertEqual((self.folder / "requirements.in").read_text(), "mcp==1.30.0\n")
        self.assertIn("COPY src/server.py /opt/mcp/", (self.folder / "Dockerfile").read_text())
        self.assertEqual(sorted(p.name for p in (self.folder / "src").iterdir() if p.name != "__pycache__"), ["server.py"])
        imports = set(re.findall(r"^(?:import|from) ([a-z0-9_.]+)", (self.folder / "src" / "server.py").read_text(), re.M))
        self.assertEqual(imports - {"__future__", "asyncio", "base64", "collections", "datetime", "json", "logging",
                                    "os", "random", "re", "stat", "sys", "time", "unicodedata", "urllib.parse"},
                         {"httpx", "mcp.server.fastmcp", "mcp.types"})

    def test_only_the_pds_and_the_public_appview(self):
        hosts = ["bsky.social:443", "public.api.bsky.app:443"]
        self.assertEqual((self.entry["network"], self.entry["hosts"]), ("allowlist", hosts))
        self.assertEqual((self.spec["network"], self.spec["hosts"]), ("allowlist", hosts))
        source = (self.folder / "src" / "server.py").read_text()
        self.assertEqual(set(re.findall(r"https://([a-z0-9-]+(?:\.[a-z0-9-]+)+)", source)) - {"bsky.social", "public.api.bsky.app"},
                         {"bsky.app"}, "links in answers only: requests go to the PDS and the AppView (checked per "
                                       "request)")
        self.assertIn('DEFAULT_PDS = "https://bsky.social"', source)
        self.assertIn('APPVIEW_HOST = "public.api.bsky.app"', source)
        self.assertIn("follow_redirects=False", source)

    def test_the_secret_the_write_switch_and_the_upload_folder(self):
        env = {var["name"]: var for var in self.entry["env"]}
        self.assertTrue(env["BLUESKY_APP_PASSWORD"]["secret"] and env["BLUESKY_APP_PASSWORD"]["required"])
        self.assertTrue(env["BLUESKY_HANDLE"]["required"])
        self.assertFalse(env["BLUESKY_HANDLE"]["secret"], "a handle is public")
        for name in ("BLUESKY_WRITE", "BLUESKY_PDS"):
            self.assertFalse(env[name]["secret"] or env[name]["required"], name)
        self.assertEqual([m["target"] for m in self.entry["mounts"]], ["/upload"])
        self.assertIn("read-only", self.entry["mounts"][0]["description"])
        self.assertFalse(self.entry["mounts"][0].get("required"), "text posts and reads need no files")
        self.assertEqual(self.tools["write_switch"], "BLUESKY_WRITE")
        self.assertEqual(sorted(self.tools["write_tools"]), ["delete_post", "post", "thread"])
        self.assertEqual(sorted([*self.tools["write_tools"], *self.tools["read_only_tools"]]), self.tools["tools"])
        rules = self.tools["recommended_rules"]["mcp"]
        self.assertEqual(next(r for r in rules if r["decision"] == "ask")["tool"], ["post", "thread", "delete_post"])

    def test_the_smoke_spec_refuses_without_an_account(self):
        for value in self.spec["env"].values():
            self.assertIn("smoke", value.replace("-", ""), "the smoke run has no account: placeholders only")
        self.assertTrue(self.spec["env"]["BLUESKY_HANDLE"].endswith(".example"), "a name no one can register")
        self.assertNotIn("BLUESKY_WRITE", self.spec["env"], "the write switch stays off in the smoke run")
        refused = [call["expect"] for call in self.spec["calls"] if call.get("expect_error")]
        self.assertEqual(len(refused), len(self.spec["calls"]))
        real = [call for call in self.spec["calls"] if call["expect"] == "Bluesky refused the sign-in"]
        self.assertEqual(len(real), 1, "one call reaches the real service")
        for expected in ("writing is off", "only files under /upload", "without . or .. in the path",
                         "alt text is required", "at most 300 graphemes"):
            self.assertTrue(any(expected in text for text in refused), expected)
        provenance = (self.folder / "PROVENANCE.md").read_text()
        for tool in self.tools["tools"]:
            self.assertIn(f"`{tool}`", provenance)


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
        self.assertEqual(entrypoint, ["/usr/bin/tini", "-s", "--", "/opt/venv/bin/python", "-I", "-u",
                                      "/opt/mcp/server.py"])
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
                # the one package installed: Debian's tini, the image's init
                installs = re.findall(r"apt-get install -y --no-install-recommends ([^\\\n]*)", final)
                self.assertEqual([i.strip() for i in installs], ["tini=0.19.0-3+b8"])
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


class SequentialThinking(unittest.TestCase):
    """The official sequential-thinking server: the npm release and its packages by integrity, yargs (declared, never
    imported) removed, thought logging off, no network, no files, no code generation from strings."""

    def setUp(self):
        self.folder = ROOT / "servers" / "sequential-thinking"
        self.dockerfile = (self.folder / "Dockerfile").read_text()
        self.provenance = (self.folder / "PROVENANCE.md").read_text()
        self.lock = read_json("servers", "sequential-thinking", "package-lock.json")
        self.entry = read_json("servers", "sequential-thinking", "server.json")

    def test_the_lock_pins_every_package_by_integrity_and_the_sdk_is_memorys(self):
        packages = {path.removeprefix("node_modules/"): entry for path, entry in self.lock["packages"].items() if path}
        kept = {"@modelcontextprotocol/server-sequential-thinking": "2.0.0", "@modelcontextprotocol/server": "2.4.0",
                "@modelcontextprotocol/core": "2.4.0", "zod": "4.6.7", "chalk": "5.6.2"}
        for name, version in kept.items():
            self.assertEqual(packages[name]["version"], version, name)
            self.assertIn(packages[name]["integrity"][:15], self.provenance, f"{name}: its integrity is not in PROVENANCE.md")
        for name, entry in packages.items():
            self.assertTrue(entry["resolved"].startswith("https://registry.npmjs.org/"), name)
            self.assertRegex(entry["integrity"], r"^sha512-[A-Za-z0-9+/]{86}==$", name)
            self.assertFalse(entry.get("hasInstallScript"), f"{name} has an install script")
        memory = {path: entry["integrity"] for path, entry in read_json("servers", "memory", "package-lock.json")[
            "packages"].items() if path}
        for path in ("node_modules/@modelcontextprotocol/server", "node_modules/@modelcontextprotocol/core",
                     "node_modules/zod"):
            self.assertEqual(self.lock["packages"][path]["integrity"], memory[path],
                             f"{path}: servers/memory's review covers only the same files")
        self.assertEqual(read_json("servers", "sequential-thinking", "package.json")["dependencies"],
                         {"@modelcontextprotocol/server-sequential-thinking": "2.0.0"})

    def test_only_what_runs_is_kept_and_the_reviewed_files_are_checked(self):
        self.assertIn("npm ci --omit=dev --ignore-scripts", self.dockerfile)
        self.assertIn("rm -rf node_modules/yargs ", self.dockerfile)
        self.assertIn("test \"$(ls node_modules | tr '\\n' ' ')\" = \"@modelcontextprotocol chalk zod \"", self.dockerfile)
        digests = re.findall(r'echo "([0-9a-f]{64})  node_modules/', self.dockerfile)
        self.assertEqual(len(digests), 3)
        for digest in digests:
            self.assertIn(digest, self.provenance)
        self.assertIn("51b6382a3e827aceb6bce430b1208d69b93d95ea", self.provenance)
        node = re.search(r"^ARG NODE_IMAGE=\S+@(sha256:[0-9a-f]{64})$", self.dockerfile, re.M)
        self.assertEqual(node.group(0), re.search(r"^ARG NODE_IMAGE=\S+$",
                                                  (ROOT / "servers/memory/Dockerfile").read_text(), re.M).group(0))
        self.assertIn(node.group(1), self.provenance)

    def test_thought_logging_is_off_and_no_code_is_generated(self):
        self.assertRegex(self.dockerfile, r"(?m)^ENV .*DISABLE_THOUGHT_LOGGING=true")
        self.assertIn('"--disallow-code-generation-from-strings"', self.dockerfile)
        self.assertNotIn("env", self.entry, "no variable can turn thought logging back on")

    def test_no_network_no_files_and_one_tool(self):
        spec = read_json("servers", "sequential-thinking", "smoke.json")
        self.assertEqual((self.entry["network"], spec["network"]), ("none", "none"))
        self.assertNotIn("mounts", self.entry)
        self.assertNotIn("mounts", spec)
        self.assertEqual(read_json("servers", "sequential-thinking", "tools.json")["tools"], ["sequentialthinking"])
        refused = [c for c in spec["calls"] if c.get("expect_error")]
        self.assertGreaterEqual(len(refused), 3)
        self.assertTrue([c for c in refused if c.get("absent")])

    def test_the_newer_release_and_when_it_is_old_enough(self):
        self.assertIn("2.1.1", self.provenance)
        self.assertIn("2026-11-18", self.provenance)



class Filesystem(unittest.TestCase):
    """The official filesystem server: the npm release and its packages by integrity, glob (declared, never imported)
    removed, started through our entry.mjs - the allowed directories are exactly the mounted folders and MCP Roots are
    never used - no network, the symlink escapes refused in the smoke spec."""

    TARGETS = ["/work", "/ref1", "/ref2", "/ref3"]

    def setUp(self):
        self.folder = ROOT / "servers" / "filesystem"
        self.dockerfile = (self.folder / "Dockerfile").read_text()
        self.provenance = (self.folder / "PROVENANCE.md").read_text()
        self.entry_source = (self.folder / "src" / "entry.mjs").read_text()
        self.lock = read_json("servers", "filesystem", "package-lock.json")
        self.entry = read_json("servers", "filesystem", "server.json")
        self.spec = read_json("servers", "filesystem", "smoke.json")

    def test_the_lock_pins_every_package_by_integrity_and_the_sdk_is_memorys(self):
        packages = {path.removeprefix("node_modules/"): entry for path, entry in self.lock["packages"].items() if path}
        kept = {"@modelcontextprotocol/server-filesystem": "2.1.0", "@modelcontextprotocol/server": "2.4.0",
                "@modelcontextprotocol/core": "2.4.0", "zod": "4.6.7", "diff": "8.0.4", "minimatch": "10.2.6",
                "brace-expansion": "5.0.12", "balanced-match": "4.0.4"}
        for name, version in kept.items():
            self.assertEqual(packages[name]["version"], version, name)
            self.assertIn(packages[name]["integrity"][:15], self.provenance, f"{name}: its integrity is not in PROVENANCE.md")
        self.assertEqual(set(packages) - set(kept), {"glob", "path-scurry", "lru-cache", "minipass"})
        for name, entry in packages.items():
            self.assertTrue(entry["resolved"].startswith("https://registry.npmjs.org/"), name)
            self.assertRegex(entry["integrity"], r"^sha512-[A-Za-z0-9+/]{86}==$", name)
            self.assertFalse(entry.get("hasInstallScript"), f"{name} has an install script")
        memory = {path: entry["integrity"] for path, entry in read_json("servers", "memory", "package-lock.json")[
            "packages"].items() if path}
        for path in ("node_modules/@modelcontextprotocol/server", "node_modules/@modelcontextprotocol/core",
                     "node_modules/zod"):
            self.assertEqual(self.lock["packages"][path]["integrity"], memory[path],
                             f"{path}: servers/memory's review covers only the same files")
        self.assertEqual(read_json("servers", "filesystem", "package.json")["dependencies"],
                         {"@modelcontextprotocol/server-filesystem": "2.1.0"})

    def test_only_what_runs_is_kept_and_the_reviewed_files_are_checked(self):
        self.assertIn("npm ci --omit=dev --ignore-scripts", self.dockerfile)
        self.assertIn("rm -rf node_modules/glob node_modules/path-scurry node_modules/lru-cache node_modules/minipass",
                      self.dockerfile)
        self.assertIn("test \"$(ls node_modules | tr '\\n' ' ')\" = "
                      "\"@modelcontextprotocol balanced-match brace-expansion diff minimatch zod \"", self.dockerfile)
        digests = re.findall(r'echo "([0-9a-f]{64})  (dist/[a-z-]+\.js|package\.json)"', self.dockerfile)
        self.assertEqual(len(digests), 9)
        self.assertEqual(len({path for _, path in digests}), 9)
        for digest, path in digests:
            self.assertIn(f"`{digest}`", self.provenance, path)
        self.assertIn("194cc86e3ae6400958555bd4116849d822d69263", self.provenance)
        node = re.search(r"^ARG NODE_IMAGE=\S+@(sha256:[0-9a-f]{64})$", self.dockerfile, re.M)
        self.assertEqual(node.group(0), re.search(r"^ARG NODE_IMAGE=\S+$",
                                                  (ROOT / "servers/memory/Dockerfile").read_text(), re.M).group(0))
        self.assertIn(node.group(1), self.provenance)

    def test_the_entry_allows_only_the_mounted_targets(self):
        entrypoint = re.search(r"^ENTRYPOINT (\[.*?\])$", self.dockerfile, re.M | re.S).group(1)
        self.assertEqual(json.loads(entrypoint.replace("\\\n", "")),
                         ["/usr/bin/tini", "-s", "--",
                          "/usr/local/bin/node", "--disallow-code-generation-from-strings", "/opt/filesystem/entry.mjs",
                          *self.TARGETS])
        self.assertIn("COPY src/entry.mjs /opt/filesystem/entry.mjs", self.dockerfile)
        self.assertIn("mkdir -m 0755 /work /ref1 /ref2 /ref3", self.dockerfile)
        self.assertIn('readFileSync("/proc/self/mountinfo", "utf8")', self.entry_source)
        self.assertIn("points.has(target)", self.entry_source)
        self.assertIn('target !== "/"', self.entry_source)
        self.assertIn("extra.length > 0", self.entry_source, "nothing but the mounted targets is allowed")
        self.assertEqual([m["target"] for m in self.entry["mounts"]], self.TARGETS)
        self.assertEqual([m["target"] for m in self.entry["mounts"] if m.get("required")], ["/work"])

    def test_mcp_roots_are_never_used(self):
        self.assertIn("protocol.listRoots = async () => {\n    throw new Error(ROOTS_REFUSED);", self.entry_source)
        self.assertIn("protocol.oninitialized = () => {};", self.entry_source)
        self.assertIn('protocol.setNotificationHandler("notifications/roots/list_changed", () => {});',
                      self.entry_source)
        self.assertIn("confinedServer(allowed, era)", self.entry_source)
        imports = re.findall(r'^import .* from "([^"]+)";$', self.entry_source, re.M)
        self.assertEqual(sorted(imports), ["@modelcontextprotocol/server-filesystem/dist/index.js",
                                           "@modelcontextprotocol/server-filesystem/dist/server.js",
                                           "@modelcontextprotocol/server/stdio", "node:fs", "node:path", "node:url"])
        self.assertNotRegex(self.entry_source, r"https?://|process\.env|child_process")

    def test_no_network_and_the_smoke_spec_tries_the_escapes(self):
        self.assertEqual((self.entry["network"], self.spec["network"]), ("none", "none"))
        self.assertNotIn("env", self.entry)
        self.assertNotIn("hosts", self.entry)
        [mount] = self.spec["mounts"]
        self.assertEqual((mount["target"], mount["fresh"], mount["writable"]), ("/work", True, True))
        links = {item["path"]: item["symlink"] for item in mount["seed"] if "symlink" in item}
        self.assertEqual(links["escape"], "/etc")
        calls = self.spec["calls"]
        self.assertEqual(calls[0], {"tool": "list_allowed_directories", "arguments": {},
                                    "expect": "Allowed directories:\n/work"})
        refused = [c for c in calls if c.get("expect_error")]
        self.assertGreaterEqual(len(refused), 10)
        self.assertTrue([c for c in refused if c.get("absent")])
        texts = " ".join(c["expect"] for c in refused)
        for text in ("symlink target outside allowed directories: /etc/passwd",
                     "path outside allowed directories: /ref1 not in /work", "Parent directory does not exist"):
            self.assertIn(text, texts)
        for call in refused:
            if not call.get("absent"):
                self.assertTrue(call["expect"].startswith(("Access denied - ", "Parent directory does not exist")),
                                call["expect"])

    def test_the_tools_and_their_record(self):
        tools = read_json("servers", "filesystem", "tools.json")["tools"]
        self.assertEqual(len(tools), 14)
        self.assertEqual(tools, sorted(self.spec["expect_tools"]))
        for tool in tools:
            self.assertIn(f"`{tool}`", self.provenance)

    def test_the_newer_releases_and_when_they_are_old_enough(self):
        for text in ("2.2.0", "2026-11-18", "2.3.0", "2026-11-25", "CVE-2025-53110", "CVE-2025-53109",
                     "GHSA-g3hv-75wg-m249"):
            self.assertIn(text, self.provenance)


class Context7(unittest.TestCase):
    """Upstash's Context7 MCP: the npm release and its packages by integrity, only what loads kept, the sign-in nudge
    and the identifying headers patched out, telemetry removed, context7.com only, the key optional."""

    def setUp(self):
        self.folder = ROOT / "servers" / "context7"
        self.dockerfile = (self.folder / "Dockerfile").read_text()
        self.provenance = (self.folder / "PROVENANCE.md").read_text()
        self.prepare = (self.folder / "prepare.mjs").read_text()
        self.lock = read_json("servers", "context7", "package-lock.json")
        self.entry = read_json("servers", "context7", "server.json")
        self.spec = read_json("servers", "context7", "smoke.json")

    def test_the_lock_pins_every_package_by_integrity_without_install_scripts(self):
        packages = {path: entry for path, entry in self.lock["packages"].items() if path}
        self.assertEqual(packages["node_modules/@upstash/context7-mcp"]["version"], "4.5.0")
        for path, entry in packages.items():
            self.assertTrue(entry["resolved"].startswith("https://registry.npmjs.org/"), path)
            self.assertRegex(entry["integrity"], r"^sha512-[A-Za-z0-9+/]{86}==$", path)
            self.assertFalse(entry.get("hasInstallScript"), f"{path} has an install script")
        self.assertIn(packages["node_modules/@upstash/context7-mcp"]["integrity"], self.provenance)
        self.assertEqual(read_json("servers", "context7", "package.json")["dependencies"],
                         {"@upstash/context7-mcp": "4.5.0"})

    def test_prepare_keeps_only_locked_packages_and_no_telemetry(self):
        keep = json.loads("{" + re.search(r"const KEEP = \{(.*?)\};", self.prepare, re.S).group(1)
                          .replace("\n", " ").rstrip(", ") + "}")
        self.assertEqual(len(keep), 74)
        locked = {path.removeprefix("node_modules/"): entry["version"] for path, entry in self.lock["packages"].items()
                  if path.count("node_modules/") == 1}
        for name, version in keep.items():
            self.assertEqual(locked.get(name), version, f"{name} is not locked at {version}")
        for name in keep:
            self.assertNotRegex(name, r"^(@opentelemetry/|@types/|hono$|require-in-the-middle|import-in-the-middle)")
        for module in ("mcp-telemetry.js", "telemetry.js", "telemetry-provider.js"):
            self.assertIn(f'"{module}"', self.prepare)
        self.assertRegex(self.dockerfile, r"(?m)^ENV .*OTEL_SDK_DISABLED=true")
        self.assertNotIn("CONTEXT7_API_URL", self.dockerfile)

    def test_the_build_installs_without_scripts_prepares_and_checks_every_file(self):
        self.assertIn("npm ci --omit=dev --ignore-scripts", self.dockerfile)
        self.assertIn("node prepare.mjs node_modules", self.dockerfile)
        self.assertIn("sha256sum --check --strict --quiet /opt/context7/context7-files.sha256", self.dockerfile)
        files = (self.folder / "context7-files.sha256").read_text().splitlines()
        self.assertEqual(len(files), 21)
        names = [line.split("  ", 1)[1] for line in files]
        self.assertIn("dist/index.js", names)
        self.assertNotIn("dist/lib/telemetry.js", names)
        # the patched files are pinned as patched
        for before, after in re.findall(r'before: "([0-9a-f]{64})",\s*after: "([0-9a-f]{64})"', self.prepare):
            self.assertIn(after, "\n".join(files))
            self.assertNotIn(before, "\n".join(files))
            self.assertIn(before[:8], self.provenance)
            self.assertIn(after[:8], self.provenance)
        self.assertIn('"--disallow-code-generation-from-strings"', self.dockerfile)
        self.assertRegex(self.dockerfile, r'"--transport", "stdio"\]')

    def test_the_patches_remove_the_nudge_and_the_identifying_headers(self):
        self.assertIn("maybeElicitAuthSignIn(server, ctx) {\\n    // sandbox-ai-mcp: no sign-in nudge", self.prepare)
        for header in ("mcp-session-id", "X-Context7-Client-IDE", "X-Context7-Client-Version"):
            self.assertIn(header, self.prepare)

    def test_the_server_advertises_tools_only(self):
        """Context7 declares the prompts and resources capabilities with nothing behind them (empty lists); agents then
        offer a model tools for MCP resources, which local models took for the way to the server's tools. A patch of
        dist/index.js leaves both out, and index.js is pinned as patched."""
        patch = re.search(r'file: "dist/index.js",\s*before: "([0-9a-f]{64})",\s*after: "([0-9a-f]{64})"', self.prepare)
        self.assertIsNotNone(patch, "no patch of dist/index.js in prepare.mjs")
        files = dict(reversed(line.split("  ", 1)) for line in
                     (self.folder / "context7-files.sha256").read_text().splitlines())
        self.assertEqual(files["dist/index.js"], patch.group(2))
        self.assertIn('            prompts: { listChanged: false },\\n            resources: { listChanged: false, subscribe: '
                      'false },\\n', self.prepare)
        self.assertIn("sandbox-ai-mcp: tools only", self.prepare)

    def test_the_research_preview_cannot_be_switched_on(self):
        """4.5.0 adds a research-preview tool (submit-docs-feedback: agent-written feedback POSTed to context7.com,
        with instructions to call it after every answer and not to mention it to the user), on with
        --research-preview or CONTEXT7_RESEARCH_PREVIEW=1. The patch of dist/index.js fixes it off."""
        self.assertIn("isResearchPreviewValue(process.env.CONTEXT7_RESEARCH_PREVIEW);\\n", self.prepare)
        self.assertIn("sandbox-ai-mcp: no research preview", self.prepare)
        self.assertNotRegex(self.dockerfile, r"(?m)^ENV .*CONTEXT7_RESEARCH_PREVIEW")
        self.assertNotIn("submit-docs-feedback", read_json("servers", "context7", "tools.json")["tools"])

    def test_context7_only_and_the_key_optional(self):
        self.assertEqual((self.entry["network"], self.entry["hosts"]), ("allowlist", ["context7.com:443"]))
        self.assertEqual((self.spec["network"], self.spec["hosts"]), ("allowlist", ["context7.com:443"]))
        self.assertEqual(self.entry["env"], [{"name": "CONTEXT7_API_KEY", "description": self.entry["env"][0][
            "description"], "secret": True, "required": False}])
        self.assertNotIn("mounts", self.entry)
        self.assertEqual(read_json("servers", "context7", "tools.json")["tools"], ["query-docs", "resolve-library-id"])

    def test_the_smoke_run_calls_the_service_and_is_refused_the_rest(self):
        real = [c for c in self.spec["calls"] if not c.get("expect_error")]
        refused = [c for c in self.spec["calls"] if c.get("expect_error")]
        self.assertEqual([c["tool"] for c in real], ["resolve-library-id", "query-docs"])
        for call in real:
            self.assertIn("Rate limited or quota exceeded", call["upstream_limited"])
        self.assertGreaterEqual(len(refused), 3)
        self.assertTrue([c for c in refused if c.get("absent")])

    def test_the_release_and_the_newer_ones_are_in_the_provenance(self):
        for text in ("a138857cc23f0abaf214b72b15d974e61598369b", "4.4.4", "4.5.1", "2026-11-17", "89c5244bc22a9bc3287d89ebc7e49b9cb5bb84",
                     "sha512-BTMM4j2ZuZdAHE1sERUCcty1eRcom4LCE04iv2XIi9b9RKhJKQsXMG7gZLgx7FX5uyyaW6xki7ReuhRM4bphZQ=="):
            self.assertIn(text, self.provenance)
        self.assertFalse((ROOT / "candidates" / "context7").exists(), "the candidate is replaced by servers/context7")


class ChromeDevTools(unittest.TestCase):
    """Chrome DevTools MCP with Debian's Chromium: the release by integrity, the telemetry sender and the update check
    removed, every switch off by flag, page-defined tools and extensions off, playwright's limits."""

    def setUp(self):
        self.folder = ROOT / "servers" / "chrome-devtools"
        self.dockerfile = (self.folder / "Dockerfile").read_text()
        self.provenance = (self.folder / "PROVENANCE.md").read_text()
        self.entry = read_json("servers", "chrome-devtools", "server.json")
        self.spec = read_json("servers", "chrome-devtools", "smoke.json")
        self.entrypoint = json.loads(re.search(r"^ENTRYPOINT (\[.*?\])$", self.dockerfile.replace("\\\n", ""),
                                               re.M | re.S).group(1))

    def test_the_release_alone_by_integrity(self):
        lock = read_json("servers", "chrome-devtools", "package-lock.json")
        packages = {path: entry for path, entry in lock["packages"].items() if path}
        self.assertEqual(list(packages), ["node_modules/chrome-devtools-mcp"])
        entry = packages["node_modules/chrome-devtools-mcp"]
        self.assertEqual(entry["version"], "1.12.0")
        self.assertEqual(entry["resolved"], "https://registry.npmjs.org/chrome-devtools-mcp/-/chrome-devtools-mcp-1.12.0.tgz")
        self.assertIn(entry["integrity"], self.provenance)
        self.assertNotIn("dependencies", entry)
        self.assertIn("af2834411a564d366f9cab63efb046d9084f4dba", self.provenance)
        self.assertIn("npm ci --omit=dev --ignore-scripts", self.dockerfile)

    def test_telemetry_and_the_update_check_cannot_run(self):
        files = [line.split("  ", 1)[1] for line in
                 (self.folder / "chrome-devtools-files.sha256").read_text().splitlines()]
        self.assertEqual(len(files), 354)
        for removed in ("build/src/telemetry/watchdog/ClearcutSender.js", "build/src/telemetry/watchdog/main.js",
                        "build/src/bin/check-latest-version.js", "build/src/bin/chrome-devtools.js"):
            self.assertNotIn(removed, files)
            self.assertIn(removed.removeprefix("build/src/").rsplit("/", 1)[0], self.dockerfile)
        self.assertFalse([f for f in files if f.startswith("skills/")])
        self.assertIn("sha256sum --check --strict --quiet /opt/chrome-devtools/chrome-devtools-files.sha256",
                      self.dockerfile)
        env = re.search(r"(?ms)^ENV (.*?)(?<!\\)\n", self.dockerfile).group(1)
        for variable in ("CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS=1", "CHROME_DEVTOOLS_MCP_NO_UPDATE_CHECKS=1",
                         "CHROME_DEVTOOLS_MCP_NO_CONFIG_DISCOVERY=1"):
            self.assertIn(variable, env)

    def test_the_browser_is_its_own_headless_isolated_and_everything_optional_is_off(self):
        self.assertEqual(self.entrypoint[:3], ["/usr/bin/tini", "-s", "--"])
        self.assertEqual(self.entrypoint[self.entrypoint.index("--executable-path") + 1], "/usr/bin/chromium")
        for flag in ("--headless", "--isolated", "--chrome-arg=--no-sandbox", "--no-usage-statistics",
                     "--no-performance-crux", "--no-file-navigations", "--no-category-experimental-third-party",
                     "--no-category-experimental-webmcp", "--no-category-extensions", "--no-category-pwa"):
            self.assertIn(flag, self.entrypoint)
        for flag in ("--browser-url", "--browserUrl", "--ws-endpoint", "--wsEndpoint", "--auto-connect",
                     "--autoConnect", "--user-data-dir", "--allow-unrestricted-paths", "--experimental-devtools",
                     "--experimental-screencast", "--log-file", "--config"):
            self.assertNotIn(flag, " ".join(self.entrypoint), f"{flag} widens what the server does")
        chromium = re.search(r"^ARG CHROMIUM_VERSION=(\S+)$", self.dockerfile, re.M).group(1)
        self.assertEqual(chromium, re.search(r"^ARG CHROMIUM_VERSION=(\S+)$",
                                             (ROOT / "servers/playwright/Dockerfile").read_text(), re.M).group(1))
        self.assertIn(chromium, self.provenance)

    def test_full_network_and_playwrights_limits(self):
        self.assertEqual((self.entry["network"], self.spec["network"]), ("full", "full"))
        self.assertEqual({k: self.spec[k] for k in ("memory", "cpus", "pids", "tmp")},
                         {"memory": "2g", "cpus": 2, "pids": 512, "tmp": "768m"})
        self.assertIn("--memory 2g --pids 512", self.entry["notes"])
        self.assertIn("a 768m /tmp", self.entry["description"])
        self.assertNotIn("env", self.entry)
        self.assertNotIn("mounts", self.entry)

    def test_the_default_tools_and_a_smoke_run_without_outside_hosts(self):
        tools = read_json("servers", "chrome-devtools", "tools.json")["tools"]
        self.assertEqual(len(tools), 32)
        self.assertEqual(tools, sorted(tools))
        for name in ("install_extension", "install_pwa", "execute_webmcp_tool", "click_at", "open_devtools",
                     "get_heapsnapshot_details"):
            self.assertNotIn(name, tools)
        for call in self.spec["calls"]:
            url = call["arguments"].get("url", "data:")
            self.assertTrue(url.startswith(("data:", "file:")), f"{url}: the smoke run needs no outside host")
        refused = [c["tool"] for c in self.spec["calls"] if c.get("expect_error")]
        self.assertEqual(refused, ["new_page", "take_snapshot", "install_extension"])

    def test_the_verdict_follows_the_complete_review(self):
        # Fit to sign only with the complete review on record: every line of its own code in the image read, the
        # package rebuilt from the release commit (and the DevTools frontend and Lighthouse commits it was built from).
        text = " ".join(self.provenance.split())
        self.assertIn("**Fit to sign once CI passes.**", text)
        self.assertNotIn("Not yet fit to sign", text)
        self.assertNotIn("--only <the other servers>", text)
        self.assertIn("The server's own code - every line read.", text)
        self.assertIn("18,195 lines", text)
        self.assertIn("are **byte-identical** to the rebuild", text)
        for commit in ("f22c645573adc85e4553747c577eebb874c3fb43", "cb853a38a6410617518b363590c967b3fe211949"):
            self.assertIn(commit, text)
        # The Lighthouse bundle the record reproduced is the one the image pins.
        pinned = dict(reversed(line.split(None, 1))
                      for line in (self.folder / "chrome-devtools-files.sha256").read_text().splitlines())
        lighthouse = pinned["build/src/third_party/lighthouse-devtools-mcp-bundle.js"]
        self.assertIn(f"`{lighthouse}`, 60,837 lines", text)
        self.assertFalse((ROOT / "candidates" / "chrome-devtools").exists())


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
        self.assertIn('ENTRYPOINT ["/usr/bin/tini", "-s", "--", "/usr/local/bin/engram-mcp"]', final)


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
        "0006-tools-only.patch": {"crates/wa-mcp/src/mcp/mod.rs"},
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

    def test_tools_only(self):
        """The server announces tools only (review of 2026-11-17): upstream announced prompts, resources (the read
        tools' data again, by URI), resource subscriptions and completions, and agents offer a model tools for an
        announced capability, which local models take for the way to the server's tools."""
        patch = self.patch("0006-tools-only.patch")
        for capability in ("enable_prompts", "enable_resources", "enable_resources_subscribe", "enable_completions"):
            self.assertIn(f"-                .{capability}()", patch)
        self.assertIn("+            ServerCapabilities::builder().enable_tools().build(),", patch)
        self.assertIn("tools only", self.provenance)

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
        self.assertRegex(self.dockerfile, r'(?m)^ENTRYPOINT \["/usr/bin/tini", "-s", "--", "/usr/local/bin/wa-mcp"\]\n'
                                          r'CMD \["serve"\]$')
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
            # /work as given; any other folder of the entry gets sandbox-ai's own default folder (0.1.214: MCP folder
            # defaults, e.g. binwalk's /out), never a host path of the user's
            self.assertEqual(definition["mounts"][0], {"target": "/work", "host": str(tmp), "mode": "ro"})
            for mount in definition["mounts"][1:]:
                self.assertIn("/sandbox-ai/mcp-folders/" + name + "/", mount["host"])
            command = load("smoke_test").image_command(mcp, definition, name)
            self.assertIn("--network=none", command)
            self.assertIn(f"--volume={tmp}:/work:ro", command)
            self.assertIn("--read-only", command)
            # Without a folder given, the required /work is the start's own workspace (sandbox-ai 0.1.214: MCP folder
            # defaults, @workspace - one server per workspace), never a host folder sandbox-ai picks
            given_none = mcp.definition_from_entry(entry)
            work = next(m for m in given_none["mounts"] if m["target"] == "/work")
            self.assertEqual(work["host"], "@workspace")

    def test_the_smoke_limits_are_a_definition_sandbox_ai_takes(self):
        """A spec's memory and pids go into the definition as `mcp add --memory --pids` puts them there."""
        smoke = load("smoke_test")
        mcp = self.sandbox_ai_mcp()
        for name in servers():
            with self.subTest(server=name):
                resources = smoke.limits(read_json("servers", name, "smoke.json"))
                definition = mcp.validated_image({"image": f"{make_catalog.IMAGE_PREFIX}{name}@sha256:{'ab' * 32}",
                                                  "network": "full", **resources}, name)
                command = smoke.image_command(mcp, definition, name)
                self.assertIn(f"--memory={resources.get('memory', '512m')}", command)
                self.assertIn(f"--pids-limit={resources.get('pids', 128)}", command)

    def test_tor_and_pid1_are_read_by_sandbox_ai_as_written(self):
        """Every entry's "tor" is what sandbox-ai's tor_support makes of it, and exec's "pid1" reaches its run line
        (no --init: the server is PID 1), the smoke runner's included; every other server keeps --init."""
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        root = tmp / "repo"
        shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns(".git", "__pycache__", "candidates", "sandbox-ai"))
        digest = "sha256:" + "ab" * 32
        digests = json.loads((root / "digests.json").read_text())
        digests["images"] = {name: digest for name in digests["images"]}
        digests["rootfs"] = {}
        (root / "digests.json").write_text(json.dumps(digests, indent=2) + "\n")
        (root / "rootfs.json").write_text(json.dumps({"version": 1, "rootfs": {}}, indent=2) + "\n")
        self.assertEqual(make_catalog.main(["--root", str(root)]), 0)
        mcp = self.sandbox_ai_mcp()
        smoke = load("smoke_test")
        for entry in mcp.read_catalog(str(root / "catalog.json")):
            with self.subTest(server=entry["name"]):
                own = read_json("servers", entry["name"], "server.json")
                self.assertEqual(mcp.tor_support(None, entry), (own["tor"]["support"], own["tor"].get("note", "")))
                mounts = [f"{mount['target']}={tmp}:ro" for mount in entry.get("mounts", [])]
                network = "full" if entry["network"] != "none" else None
                env = [var["name"] for var in entry.get("env", [])]
                definition = mcp.definition_from_entry(entry, mounts=mounts, env=env, network=network)
                self.assertEqual(definition.get("pid1"), own.get("pid1"))
                self.assertEqual("--init" not in smoke.image_command(mcp, definition, entry["name"]),
                                 own.get("pid1") == "server")
        options = smoke.server_options(str(ROOT / "servers/exec/smoke.json"))
        argv, _, _ = smoke.sandbox_ai_argv("sandbox-ai-podman", str(self.checkout), f"local/exec@{digest}", "none",
                                           [(str(tmp), "/work", True)], {}, resources=options)
        self.assertNotIn("--init", argv)
        argv, _, _ = smoke.sandbox_ai_argv("sandbox-ai-podman", str(self.checkout), f"local/exec@{digest}", "none",
                                           [(str(tmp), "/work", True)], {}, resources={})
        self.assertIn("--init", argv)

    def test_without_the_hosts_init_every_image_starts_on_its_own(self):
        """CI's no-host-init run (smoke_test.py --runner sandbox-ai-podman-no-host-init): sandbox-ai is told this host
        has no init binary for Podman's --init (SANDBOX_AI_INIT_BINARY=none) and asks Podman for the image's
        ENTRYPOINT (here a stand-in podman answering with each Dockerfile's): every image is started without --init,
        on tini or as its own PID 1; an image without an init of its own is refused, with a failed report."""
        smoke = load("smoke_test")
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        entrypoints = {f"local/{name}@sha256:{'ab' * 32}": final_command(name) for name in servers()}
        entrypoints["local/no-init@sha256:" + "ab" * 32] = ["/opt/venv/bin/python", "-I", "/opt/mcp/server.py"]
        (tmp / "entrypoints.json").write_text(json.dumps(entrypoints))
        podman = tmp / "bin" / "podman"
        podman.parent.mkdir()
        podman.write_text(f"#!{sys.executable}\nimport json, sys\n"
                          "assert sys.argv[1:5] == ['image', 'inspect', '--format', '{{json .Config.Entrypoint}}']\n"
                          f"print(json.dumps(json.load(open({str(tmp / 'entrypoints.json')!r}))[sys.argv[5]]))\n")
        podman.chmod(0o755)
        saved = {key: os.environ.get(key) for key in ("PATH", "SANDBOX_AI_INIT_BINARY")}

        def restore():
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
        self.addCleanup(restore)
        os.environ["PATH"] = f"{podman.parent}{os.pathsep}{os.environ.get('PATH', '')}"
        for name in servers():
            with self.subTest(server=name):
                os.environ.pop("SANDBOX_AI_INIT_BINARY", None)
                options = smoke.server_options(str(ROOT / "servers" / name / "smoke.json"))
                argv, _, facts = smoke.sandbox_ai_argv(smoke.NO_HOST_INIT, str(self.checkout),
                                                       f"local/{name}@sha256:{'ab' * 32}", "none", [], {},
                                                       resources=options)
                self.assertEqual(os.environ.get("SANDBOX_AI_INIT_BINARY"), "none")
                self.assertNotIn("--init", argv)
                self.assertEqual((facts["host_init"], facts["podman_init"]), ("none", False))
        with self.assertRaises(ValueError) as refused:
            smoke.sandbox_ai_argv(smoke.NO_HOST_INIT, str(self.checkout), "local/no-init@sha256:" + "ab" * 32,
                                  "none", [], {})
        self.assertIn("catatonit", str(refused.exception))
        spec = tmp / "smoke.json"
        spec.write_text(json.dumps({"name": "no-init", "network": "none", "calls": []}))
        report = tmp / "report.json"
        with contextlib.redirect_stdout(io.StringIO()):
            status = smoke.main(["--runner", smoke.NO_HOST_INIT, "--sandbox-ai", str(self.checkout), "--image",
                                 "local/no-init@sha256:" + "ab" * 32, "--spec", str(spec), "--report", str(report)])
        self.assertEqual(status, 1)
        written = json.loads(report.read_text())
        self.assertEqual((written["ok"], written["runner"]), (False, smoke.NO_HOST_INIT))
        self.assertIn("catatonit", written["exception"])

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
