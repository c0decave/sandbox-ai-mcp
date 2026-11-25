"""The markitdown server (servers/markitdown): its own code offline - paths (no '..', nothing outside /work, no web
address or data: URI, no link, no folder, pipe, empty or oversized file), answers in parts of 24,000 characters with
the offset of the next, the cache (a changed file is converted again), the conversion child (an empty environment,
the descriptor as its standard input, a time limit, a cap on what it prints) - and, where markitdown is installed
(inside the image, or a venv from servers/markitdown/requirements.txt), every format on the fixtures and hostile
documents (a zip bomb, entity expansion, deep nesting, a binary file). The folders are temporary ones the module's
ROOTS point at. CI runs this inside the image too (tests/test_own_servers.py test_markitdown)."""
from __future__ import annotations

import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import textwrap
import unittest
from unittest import mock
import zipfile

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "servers" / "markitdown" / "src" / "server.py"
CHILD = ROOT / "servers" / "markitdown" / "src" / "convert.py"

try:
    import mcp  # noqa: F401 - the server's own dependency
    from mcp.server.fastmcp.exceptions import ToolError
except ImportError:
    mcp = None
    ToolError = Exception

#: markitdown, mammoth and pdfminer.six: in the image, or a venv from servers/markitdown/requirements.txt (not
#: imported here: markitdown imports magika, which convert.py stands in for)
HAVE_MARKITDOWN = all(importlib.util.find_spec(name) for name in ("markitdown", "mammoth", "pdfminer"))


def load():
    spec = importlib.util.spec_from_file_location("server_markitdown_test", SERVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixtures() -> dict[str, bytes]:
    spec = importlib.util.spec_from_file_location("fixtures_markitdown_test", ROOT / "scripts" / "fixtures.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {f["path"]: f["data"] for f in module.load()}


def docx(document_xml: str, extra: dict | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.'
                         'org/package/2006/content-types"/>')
        archive.writestr("_rels/.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/'
                         'package/2006/relationships"><Relationship Id="r1" Type="http://schemas.openxmlformats.org/'
                         'officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
                         '</Relationships>')
        archive.writestr("word/document.xml", document_xml)
        for name, data in (extra or {}).items():
            archive.writestr(name, data)
    return buffer.getvalue()


@unittest.skipIf(mcp is None, "the mcp package is not installed (servers/markitdown/requirements.txt)")
class Paths(unittest.TestCase):
    def setUp(self):
        self.module = load()
        self.work = Path(tempfile.mkdtemp(prefix="markitdown-test-"))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.module.ROOTS[self.module.WORK] = str(self.work)
        (self.work / "docs").mkdir()
        (self.work / "docs" / "a.txt").write_text("hello\n")
        (self.work / "empty.txt").write_bytes(b"")

    def refused(self, uri, text):
        with self.assertRaises(self.module.Refused) as caught:
            fd, _, _ = self.module.open_input(uri)
            os.close(fd)
        self.assertIn(text, str(caught.exception))

    def test_names_inside_work(self):
        for uri in ("docs/a.txt", "/work/docs/a.txt", "file:///work/docs/a.txt", "file://localhost/work/docs/a.txt",
                    "./docs/./a.txt", "file:///work/docs/%61.txt"):
            fd, shown, info = self.module.open_input(uri)
            os.close(fd)
            self.assertEqual(shown, "/work/docs/a.txt", uri)
            self.assertEqual(info.st_size, 6)

    def test_refused(self):
        self.refused("../etc/passwd", "'..' is not allowed")
        self.refused("docs/../../etc/passwd", "'..' is not allowed")
        self.refused("/etc/passwd", "only files in /work")
        self.refused("/workx/a.txt", "only files in /work")
        self.refused("file:///etc/passwd", "only files in /work")
        self.refused("file://evil.example/work/a.txt", "not on a host")
        self.refused("file:///work/%2e%2e/etc/passwd", "'..' is not allowed")
        self.refused("https://example.com/a.pdf", "no web addresses")
        self.refused("http://169.254.169.254/latest/meta-data", "no web addresses")
        self.refused("data:text/plain,hello", "no data: URIs")
        self.refused("~/a.txt", "'~' is not a folder")
        self.refused("docs/a\nb.txt", "uri:")
        self.refused("", "uri:")
        self.refused("x" * 5000, "uri:")
        self.refused("/work", "name a file")
        self.refused("docs", "is a folder")
        self.refused("empty.txt", "is empty")
        self.refused("missing.pdf", "does not exist")
        self.refused("docs/" + "n" * 300, "longer than 255 bytes")
        for bad in (None, 7, ["a"]):
            self.refused(bad, "uri:")

    def test_links_and_special_files(self):
        outside = Path(tempfile.mkdtemp(prefix="markitdown-outside-"))
        self.addCleanup(shutil.rmtree, outside, True)
        (outside / "secret.txt").write_text("secret\n")
        os.symlink(outside / "secret.txt", self.work / "link.txt")
        os.symlink(outside, self.work / "linked")
        os.symlink("docs/a.txt", self.work / "inside-link.txt")
        os.mkfifo(self.work / "pipe.txt")
        self.refused("link.txt", "is a link")
        self.refused("linked/secret.txt", "is a link")
        self.refused("inside-link.txt", "is a link")
        self.refused("pipe.txt", "not a regular file")

    def test_too_large(self):
        with mock.patch.object(self.module, "MAX_INPUT_BYTES", 3):
            self.refused("docs/a.txt", "larger than")

    def test_pages(self):
        page = self.module.page
        text = ("line of text\n" * 4000)
        first = page("/work/a.md", text, 0)
        head, body = first.split("\n\n", 1)
        self.assertLessEqual(len(body), self.module.MAX_CHARS)
        self.assertTrue(body.endswith("\n"))  # cut after a whole line
        self.assertRegex(head, r"^/work/a\.md: characters 0-\d+ of 52000 \(more: offset=\d+\)$")
        offset = int(head.rsplit("=", 1)[1].rstrip(")"))
        seen, parts = body, 1
        while "(more: offset=" in head:
            head, body = page("/work/a.md", text, offset).split("\n\n", 1)
            seen += body
            parts += 1
            if "(more: offset=" in head:
                offset = int(head.rsplit("=", 1)[1].rstrip(")"))
        self.assertEqual(seen, text)
        self.assertEqual(parts, 3)
        self.assertIn("no text", page("/work/scan.pdf", "", 0))
        with self.assertRaises(self.module.Refused):
            page("/work/a.md", "abc", 10)
        long_line = "x" * 60000
        self.assertEqual(len(page("/work/a.md", long_line, 0).split("\n\n", 1)[1]), self.module.MAX_CHARS)

    def test_offset_checked(self):
        for bad in (-1, True, "3"):
            with self.assertRaises(ToolError) as caught:
                self.module.convert_to_markdown("docs/a.txt", bad)
            self.assertIn("offset:", str(caught.exception))

    def test_cache_and_changed_file(self):
        calls = []

        def child(fd, extension):
            calls.append(extension)
            return os.read(fd, 100).decode()
        with mock.patch.object(self.module, "run_child", child):
            self.assertIn("hello", self.module.convert_to_markdown("docs/a.txt"))
            self.assertIn("hello", self.module.convert_to_markdown("/work/docs/a.txt"))
            self.assertEqual(calls, [".txt"])
            (self.work / "docs" / "a.txt").write_text("changed text\n")
            self.assertIn("changed text", self.module.convert_to_markdown("docs/a.txt"))
            self.assertEqual(calls, [".txt", ".txt"])

    def test_cache_bounded(self):
        cache = self.module.Cache()
        with mock.patch.object(self.module, "CACHE_BYTES", 100):
            for index in range(20):
                cache.put((index,), "x" * 60)
            self.assertEqual(len(cache._items), 1)
            self.assertIsNotNone(cache.get((19,)))
        cache = self.module.Cache()
        for index in range(20):
            cache.put((index,), "x")
        self.assertEqual(len(cache._items), self.module.CACHE_ENTRIES)


@unittest.skipIf(mcp is None, "the mcp package is not installed (servers/markitdown/requirements.txt)")
class Child(unittest.TestCase):
    """The child's command line, environment and limits, with a stand-in for convert.py."""

    def setUp(self):
        self.module = load()
        self.work = Path(tempfile.mkdtemp(prefix="markitdown-child-"))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.module.ROOTS[self.module.WORK] = str(self.work)
        (self.work / "a.pdf").write_bytes(b"%PDF-1.4 stand-in")

    def fake(self, body: str):
        path = self.work / "fake_convert.py"
        path.write_text(textwrap.dedent(body))
        return mock.patch.object(self.module, "CHILD", str(path))

    def test_environment_and_descriptor(self):
        with self.fake("""
            import json, os, sys
            print(json.dumps({"env": dict(os.environ), "argv": sys.argv[1:], "stdin": sys.stdin.buffer.read().decode(),
                              "cwd": os.getcwd()}))
        """), mock.patch.dict(os.environ, {"SECRET_TOKEN": "s3cret"}):
            answer = self.module.convert_to_markdown("a.pdf")
        seen = json.loads(answer.split("\n\n", 1)[1])
        self.assertNotIn("SECRET_TOKEN", seen["env"])
        self.assertEqual(set(seen["env"]) - {"LC_CTYPE"}, {"LANG", "HOME", "PATH"})
        self.assertEqual(seen["argv"], [".pdf"])
        self.assertEqual(seen["stdin"], "%PDF-1.4 stand-in")
        self.assertEqual(seen["cwd"], "/")

    def test_odd_extension_not_passed(self):
        (self.work / "a.p;df").write_bytes(b"x")
        with self.fake("import sys; print(repr(sys.argv[1:]))"):
            self.assertIn("['']", self.module.convert_to_markdown("a.p;df"))

    def test_time_limit(self):
        with self.fake("import time; time.sleep(60)"), mock.patch.object(self.module, "TIME_LIMIT", 1):
            with self.assertRaises(ToolError) as caught:
                self.module.convert_to_markdown("a.pdf")
        self.assertIn("longer than 1 s", str(caught.exception))

    def test_output_capped(self):
        with self.fake("import sys; sys.stdout.write('y' * 5000)"), \
                mock.patch.object(self.module, "MAX_MARKDOWN_BYTES", 1000):
            answer = self.module.convert_to_markdown("a.pdf")
        self.assertIn("characters 0-", answer)
        self.assertIn("[the Markdown was cut at", answer)
        self.assertEqual(answer.count("y"), 1000)

    def test_exit_statuses(self):
        for status, text in ((2, "this kind of file is not converted"), (3, "broken thing"), (4, "broken thing"),
                             (9, "exit status 9")):
            with self.fake(f"import sys; print('broken thing', file=sys.stderr); sys.exit({status})"):
                with self.assertRaises(ToolError) as caught:
                    self.module.convert_to_markdown("a.pdf")
            self.assertIn(text, str(caught.exception), status)


@unittest.skipIf(mcp is None or not HAVE_MARKITDOWN, "markitdown is not installed (servers/markitdown/requirements.txt)")
class Formats(unittest.TestCase):
    """The real conversion child on the fixtures and on hostile documents."""

    @classmethod
    def setUpClass(cls):
        cls.files = fixtures()

    def setUp(self):
        self.module = load()
        self.work = Path(tempfile.mkdtemp(prefix="markitdown-formats-"))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.module.ROOTS[self.module.WORK] = str(self.work)
        for name in ("sample.docx", "sample.xlsx", "sample.pptx", "sample.pdf", "sample.epub"):
            (self.work / name).write_bytes(self.files[name])
        for name in ("sales.csv", "notes.html"):
            shutil.copy(ROOT / "tests" / "fixtures" / name, self.work / name)

    def convert(self, name: str) -> str:
        return self.module.convert_to_markdown(name).split("\n\n", 1)[1]

    def refused(self, name: str) -> str:
        with self.assertRaises(ToolError) as caught:
            self.module.convert_to_markdown(name)
        return str(caught.exception)

    def test_docx(self):
        text = self.convert("sample.docx")
        self.assertIn("# Quarterly report", text)
        self.assertIn("**12 percent**", text)
        self.assertIn("| North | 4200 |", text)

    def test_xlsx(self):
        text = self.convert("sample.xlsx")
        self.assertIn("## Inventory", text)
        self.assertIn("| Item | Count | Checked |", text)
        self.assertIn("| Widget \\| large | 17 | 2026-11-01 |", text)
        self.assertIn("| Gadget | 2.5 | TRUE |", text)
        self.assertIn("## Notes", text)

    def test_pptx(self):
        text = self.convert("sample.pptx")
        self.assertLess(text.index("Project kickoff"), text.index("Timeline"))  # the presentation's order
        self.assertIn("# Project kickoff", text)
        self.assertIn("### Notes:\nMention the budget first", text)
        self.assertIn("| Design | 3 |", text)

    def test_pdf(self):
        text = self.convert("sample.pdf")
        self.assertIn("Invoice 2026-0042", text)
        self.assertIn("Total due: 1,250.00 EUR", text)

    def test_epub_html_csv_text(self):
        self.assertIn("# Chapter One", self.convert("sample.epub"))
        self.assertIn("**Title:** The Lighthouse Keeper", self.convert("sample.epub"))
        html = self.convert("notes.html")
        self.assertIn("[login bug](https://example.com/issue/7)", html)
        self.assertNotIn("javascript:", html)
        self.assertNotIn("never shown", html)
        self.assertIn("| West | Widget | 2026-Q2 | 150 | 9.00 |", self.convert("sales.csv"))
        (self.work / "server.log").write_text("2026-11-25 started\nüber alles\n")
        self.assertIn("über alles", self.convert("server.log"))
        (self.work / "nb.ipynb").write_text(json.dumps({"cells": [{"cell_type": "markdown", "source": ["# Notebook"]},
                                                                 {"cell_type": "code", "source": ["print(1)"]}],
                                                       "metadata": {}, "nbformat": 4, "nbformat_minor": 5}))
        self.assertIn("print(1)", self.convert("nb.ipynb"))

    def test_binary_refused(self):
        (self.work / "blob.bin").write_bytes(bytes(range(256)) * 20)
        self.assertIn("this kind of file is not converted", self.refused("blob.bin"))
        (self.work / "photo.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        self.assertIn("not converted", self.refused("photo.png"))

    def test_zip_bomb(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("word/document.xml", b"<a>" + b" " * (64 << 20) + b"</a>")
        (self.work / "bomb.docx").write_bytes(buffer.getvalue())
        self.assertIn("compressed more than 200:1", self.refused("bomb.docx"))

    def test_entity_expansion(self):
        laughs = ('<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">'
                  + "".join(f'<!ENTITY lol{i} "{("&lol" + (str(i - 1) if i > 1 else "") + ";") * 10}">'
                            for i in range(1, 10))
                  + ']><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
                  '<w:p><w:r><w:t>&lol9;</w:t></w:r></w:p></w:body></w:document>')
        (self.work / "laughs.docx").write_bytes(docx(laughs))
        try:
            text = self.convert("laughs.docx")
        except ToolError as exc:
            text = str(exc)
        self.assertNotIn("lol" * 1000, text)
        (self.work / "laughs.xlsx").write_bytes(docx("<x/>", {"xl/workbook.xml": laughs}))
        self.assertIn("the conversion failed", self.refused("laughs.xlsx"))

    def test_deep_html(self):
        (self.work / "deep.html").write_text("<div>" * 20000 + "deep text" + "</div>" * 20000)
        self.assertIn("deep text", self.convert("deep.html"))

    def test_broken_documents(self):
        for name in ("broken.docx", "broken.xlsx", "broken.pptx", "broken.pdf", "broken.epub"):
            (self.work / name).write_bytes(b"PK\x03\x04 not really a zip")
            self.assertIn("the conversion failed", self.refused(name), name)

    def test_whole_session_over_stdio(self):
        """The server as the image starts it, with /work pointed at the fixtures folder through a wrapper."""
        wrapper = self.work / "run.py"
        wrapper.write_text(textwrap.dedent(f"""
            import runpy, sys
            sys.argv = [{str(SERVER)!r}]
            module = runpy.run_path({str(SERVER)!r}, run_name="not_main")
            module["ROOTS"]["/work"] = {str(self.work)!r}
            module["tools_only"](module["mcp"])
            module["mcp"].run("stdio")
        """))
        import subprocess
        messages = [{"jsonrpc": "2.0", "id": 0, "method": "initialize",
                     "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                "clientInfo": {"name": "test", "version": "1"}}},
                    {"jsonrpc": "2.0", "method": "notifications/initialized"},
                    {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                    {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                     "params": {"name": "convert_to_markdown", "arguments": {"uri": "sample.docx"}}}]
        process = subprocess.Popen([sys.executable, "-I", str(wrapper)], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        answers = {}
        try:
            for message in messages:
                process.stdin.write(json.dumps(message) + "\n")
                process.stdin.flush()
                while "id" in message and message["id"] not in answers:
                    answer = json.loads(process.stdout.readline())
                    answers[answer.get("id")] = answer
        finally:
            process.stdin.close()
            process.wait(60)
            process.stdout.close()
        self.assertNotIn("resources", answers[0]["result"]["capabilities"])
        self.assertEqual([t["name"] for t in answers[1]["result"]["tools"]], ["convert_to_markdown"])
        self.assertIn("Quarterly report", answers[2]["result"]["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
