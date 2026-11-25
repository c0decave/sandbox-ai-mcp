"""The codec server (servers/codec): every operation both ways where it has two, recipes of several steps, detect on
each kind it recognises, the bounds (input size, a decompression bomb stopped at 16 MiB, an expansion refused before
it is made, 20 steps, the time limit), files in /work (no '..', no link, no folder), argument checks and the answer
formats. Standard library plus the shared lock's mcp; CI runs this inside the image too (tests/test_own_servers.py
test_codec)."""
from __future__ import annotations

import base64
import bz2
import gzip
import importlib.util
import json
import lzma
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock
import zlib

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "servers" / "codec" / "src" / "server.py"

try:
    import mcp  # noqa: F401 - the server's own dependency
    from mcp.server.fastmcp.exceptions import ToolError
except ImportError:
    mcp = None
    ToolError = Exception


def load():
    spec = importlib.util.spec_from_file_location("server_codec_test", SERVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipIf(mcp is None, "the mcp package is not installed (servers/codec/requirements.txt)")
class Codec(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load()

    def run_text(self, recipe, data, **kwargs) -> str:
        answer = self.m.run_recipe(recipe, data, **kwargs)
        head, _, body = answer.partition("\n")
        self.assertTrue(head.startswith("recipe: "), answer)
        return body.split("\n", 1)[1] if body.startswith(("text (", "base64 (")) else body

    def refused(self, text, function, *args, **kwargs):
        with self.assertRaises(ToolError) as caught:
            function(*args, **kwargs)
        self.assertIn(text, str(caught.exception))

    def test_round_trips(self):
        sample = "Grüße, flag{1}!\n<a href='x'>&</a> 100%"
        pairs = [("to_base64", "from_base64"), ("to_base32", "from_base32"), ("to_base85", "from_base85"),
                 ("to_ascii85", "from_ascii85"), ("to_hex", "from_hex"), ("to_url", "from_url"),
                 ("to_html_entities", "from_html_entities"), ("to_binary", "from_binary"),
                 ("to_decimal", "from_decimal"), ("to_quoted_printable", "from_quoted_printable"),
                 ("gzip", "gunzip"), ("zlib_deflate", "zlib_inflate"), ("raw_deflate", "raw_inflate"),
                 ("bzip2", "bunzip2"), ("xz", "unxz"), ("reverse", "reverse"), ("defang", "refang")]
        for there, back in pairs:
            self.assertEqual(self.run_text([there, back], sample), sample, there)
        self.assertEqual(self.run_text([self.m.Step(op="rot", amount=7), self.m.Step(op="rot", amount=19)], sample),
                         sample)
        self.assertEqual(self.run_text([self.m.Step(op="encode_text", charset="utf-16le"),
                                        self.m.Step(op="decode_text", charset="utf-16le")], sample), sample)

    def test_known_values(self):
        Step = self.m.Step
        self.assertEqual(self.run_text(["to_hex"], "hi"), "6869")
        self.assertEqual(self.run_text(["from_hex"], "0x68 69:21"), "hi!")
        self.assertEqual(self.run_text(["from_base64"], "aGk_"), "hi?")  # base64url, padding added
        self.assertEqual(self.run_text([Step(op="rot")], "Uryyb, Jbeyq"), "Hello, World")
        self.assertEqual(self.run_text([Step(op="hash", algorithm="md5")], "abc"), "900150983cd24fb0d6963f7d28e17f72")
        self.assertEqual(self.run_text([Step(op="hash")], ""),
                         "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")
        self.assertEqual(self.run_text([Step(op="hash", algorithm="crc32")], "abc"), "352441c2")
        self.assertEqual(self.run_text([Step(op="xor", key="key", key_format="utf8"), "to_hex"], "abc"), "0a071a")
        self.assertEqual(self.run_text(["from_decimal"], "72, 105"), "Hi")
        self.assertEqual(self.run_text(["defang"], "see https://evil.example.com/x and a@b.org"),
                         "see hxxps://evil[.]example[.]com/x and a[@]b[.]org")
        self.assertEqual(self.run_text([Step(op="strings", min_length=5)], "ab\x00hello\x01xy\x02world!"),
                         "hello\nworld!")
        jwt = self.run_text(["jwt_decode"], "eyJhbGciOiJub25lIn0.eyJzdWIiOiJhbmEifQ.")
        self.assertEqual(json.loads(jwt)["payload"], {"sub": "ana"})
        self.assertIn("not verified", jwt)
        self.assertIn("bits per byte", self.run_text(["entropy"], "aaaa"))

    def test_a_ctf_recipe(self):
        hidden = base64.b64encode(gzip.compress(bytes(b ^ 0x41 for b in b"flag{x0r_and_gzip}"), mtime=0)).decode()
        recipe = ["from_base64", "gunzip", self.m.Step(op="xor", key="41")]
        answer = self.m.run_recipe(recipe, hidden)
        self.assertIn("recipe: from_base64 -> 38 bytes; gunzip -> 18 bytes; xor -> 18 bytes", answer)
        self.assertTrue(answer.endswith("flag{x0r_and_gzip}"))
        found = json.loads(self.m.detect(hidden))["candidates"]
        self.assertEqual(found[0]["looks_like"], "base64")
        self.assertEqual(found[0]["preview"]["then_looks_like"], ["gzip"])

    def test_detect(self):
        cases = {gzip.compress(b"x"): "gzip", zlib.compress(b"x"): "zlib (default)", bz2.compress(b"x"): "bzip2",
                 lzma.compress(b"x"): "xz", b"%PDF-1.7": "PDF document", b"\x7fELF\x02": "ELF executable",
                 b"666c6167": "hex", b"01100110 01101100": "binary", b"102 108 97 103": "decimal character codes",
                 b"MZXW6YTBOI======": "base32", b"ZmxhZ3t4fQ==": "base64", b"a%20b": "URL encoding",
                 b"&lt;b&gt;": "HTML entities", b"<~9jqo^~>": "ascii85 (Adobe)", b"hxxp://x[.]org": "defanged "
                                                                                                    "indicators",
                 b"eyJhbGciOiJub25lIn0.eyJ4IjoxfQ.": "JWT"}
        for data, what in cases.items():
            found = json.loads(self.m.detect(base64.b64encode(data).decode(), input_format="base64"))
            self.assertIn(what, [c["looks_like"] for c in found["candidates"]], data)
        nothing = json.loads(self.m.detect(base64.b64encode(os.urandom(64)).decode(), input_format="base64"))
        self.assertIn("note", nothing) if not nothing["candidates"] else None

    def test_bounds(self):
        bomb = base64.b64encode(gzip.compress(b"\0" * (40 << 20))).decode()
        self.refused("unpacks to more than 16 MiB", self.m.run_recipe, ["from_base64", "gunzip"], bomb)
        for name, pack in (("zlib_inflate", zlib.compress), ("bunzip2", bz2.compress), ("unxz", lzma.compress)):
            blob = base64.b64encode(pack(b"\0" * (20 << 20))).decode()
            self.refused("unpacks to more than 16 MiB", self.m.run_recipe, ["from_base64", name], blob)
        self.refused("would be larger than 16 MiB", self.m.run_recipe, ["to_binary", "to_binary", "to_binary"],
                     "x" * 300_000)
        self.refused("at most 1 MiB", self.m.run_recipe, ["reverse"], "x" * (2 << 20) + "y")
        self.refused("recipe: 1-20 operations", self.m.run_recipe, ["reverse"] * 21, "x")
        self.refused("recipe: 1-20 operations", self.m.run_recipe, [], "x")
        with mock.patch.object(self.m, "TIME_LIMIT", -1):
            self.refused("took longer than", self.m.run_recipe, ["reverse", "reverse"], "x")

    def test_argument_checks(self):
        Step = self.m.Step
        for recipe, text in (([Step(op="nope")], "op 'nope': one of"), ([Step(op="xor")], "give a key"),
                             ([Step(op="xor", key="zz")], "not hexadecimal"),
                             ([Step(op="xor", key="41", key_format="rot")], "key_format is"),
                             ([Step(op="rot", amount=26)], "amount from 1 to 25"),
                             ([Step(op="hash", algorithm="sha0")], "algorithm one of"),
                             ([Step(op="decode_text", charset="rot13")], "not a text encoding"),
                             ([Step(op="decode_text", charset="klingon")], "unknown charset"),
                             ([Step(op="strings", min_length=1)], "min_length from 2"),
                             ([Step(op="reverse", key="x")], "reverse: takes no key"),
                             (["from_base64"], "not base64"), (["from_binary"], "groups of eight"),
                             (["jwt_decode"], "three base64url parts")):
            self.refused(text, self.m.run_recipe, recipe, "!!")
        with self.assertRaises(Exception):
            Step(op="xor", keyy="41")  # a misspelt argument is refused, not ignored
        self.refused("input_format:", self.m.run_recipe, ["reverse"], "x", input_format="rot13")
        self.refused("output_format:", self.m.run_recipe, ["reverse"], "x", output_format="pdf")
        self.refused("not both", self.m.run_recipe, ["reverse"], "x", path="a.bin")

    def test_output_formats(self):
        binary = self.m.run_recipe(["from_hex"], "00ff7f41")
        self.assertIn("bytes (4), hex dump:\n00000000  00 ff 7f 41", binary)
        self.assertIn("|...A|", binary)
        self.assertIn("base64 (4 bytes):\nAP9/QQ==", self.m.run_recipe(["from_hex"], "00ff7f41", output_format="base64"))
        self.assertIn("text (2 bytes):\nhi", self.m.run_recipe(["from_hex"], "6869", output_format="text"))
        big = self.m.run_recipe(["from_base64"], base64.b64encode(os.urandom(100_000)).decode())
        self.assertLessEqual(len(big), self.m.MAX_CHARS)
        self.assertIn("more bytes not shown", big)
        long_text = self.m.run_recipe(["reverse"], "x" * 100_000)
        self.assertLessEqual(len(long_text), self.m.MAX_CHARS)


@unittest.skipIf(mcp is None, "the mcp package is not installed (servers/codec/requirements.txt)")
class Files(unittest.TestCase):
    def setUp(self):
        self.m = load()
        self.work = Path(tempfile.mkdtemp(prefix="codec-test-"))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.m.ROOTS[self.m.WORK] = str(self.work)
        (self.work / "dir").mkdir()
        (self.work / "dir" / "blob.bin").write_bytes(gzip.compress(b"inside", mtime=0))
        outside = Path(tempfile.mkdtemp(prefix="codec-outside-"))
        self.addCleanup(shutil.rmtree, outside, True)
        (outside / "secret").write_text("secret")
        os.symlink(outside / "secret", self.work / "link")
        os.symlink(outside, self.work / "linkdir")

    def test_reads_a_file_in_work(self):
        for path in ("dir/blob.bin", "/work/dir/blob.bin"):
            self.assertTrue(self.m.run_recipe(["gunzip"], path=path).endswith("inside"))
        self.assertEqual(json.loads(self.m.detect(path="dir/blob.bin"))["candidates"][0]["looks_like"], "gzip")

    def test_refused(self):
        for path, text in (("../etc/passwd", "no '..'"), ("/etc/passwd", "only files in /work"),
                           ("link", "is a link"), ("linkdir/secret", "a link"), ("dir", "not a regular file"),
                           ("missing", "does not exist"), ("a\nb", "path:"), ("", "path:")):
            with self.assertRaises(ToolError, msg=path) as caught:
                self.m.run_recipe(["reverse"], path=path)
            self.assertIn(text, str(caught.exception), path)
        (self.work / "big").write_bytes(b"x" * (self.m.MAX_INPUT + 1))
        with self.assertRaises(ToolError) as caught:
            self.m.detect(path="big")
        self.assertIn("larger than 1 MiB", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
