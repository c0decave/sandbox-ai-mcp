"""The files server (servers/files), offline: every path refusal ('..', outside the folders, links that leave a
folder, links on a write's way, devices, pipes and sockets, a folder swapped for a link while it is walked), the
size limit, FILES_READONLY and the read-only folders, atomic writes (an interrupted write leaves the file as it
was and no temporary file; a file changed meanwhile is never replaced; expected_sha256; permissions, line breaks
and byte order mark kept), each repair and each warning of write_markdown, edit_file's uniqueness check and its
whitespace-tolerant fallback, the line tools, apply_patch, move, copy, mkdir, delete into the trash, diff,
checksum, stat, glob and search (a regular expression that backtracks without end is stopped). The folders are
temporary ones the module's ROOTS point at. CI runs this inside the image too (tests/test_own_servers.py
test_files)."""
from __future__ import annotations

import hashlib
import importlib.util
import os
from pathlib import Path
import shutil
import socket
import stat
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "servers" / "files" / "src" / "server.py"

try:
    import mcp  # noqa: F401 - the server's own dependency
except ImportError:
    mcp = None


def load():
    spec = importlib.util.spec_from_file_location("server_files_test", SERVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


CLEAN_ENV = {"FILES_READONLY": "", "FILES_MAX_BYTES": "", "FILES_TRASH": ""}


@unittest.skipIf(mcp is None, "the server's requirements are not installed (pip install --require-hashes -r "
                              "servers/files/requirements.txt)")
class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load()

    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="files-test-")
        self.addCleanup(shutil.rmtree, self.base, True)
        self.work = os.path.join(self.base, "work")
        self.ref = os.path.join(self.base, "ref")
        self.outside = os.path.join(self.base, "outside")
        for folder in (self.work, self.ref, self.outside):
            os.mkdir(folder)
        Path(self.outside, "secret.txt").write_text("outside secret\n")
        Path(self.ref, "guide.md").write_text("# Guide\n\nread me\n")
        patcher = mock.patch.object(self.m, "ROOTS", {"/work": self.work, "/ref1": self.ref,
                                                    "/ref2": os.path.join(self.base, "missing")})
        patcher.start()
        self.addCleanup(patcher.stop)
        env = mock.patch.dict(os.environ, CLEAN_ENV)
        env.start()
        self.addCleanup(env.stop)

    def put(self, name: str, data: str | bytes) -> Path:
        path = Path(self.work, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, str):
            data = data.encode()
        path.write_bytes(data)
        return path

    def raw(self, name: str) -> bytes:
        return Path(self.work, name).read_bytes()

    def ok(self, answer: dict) -> dict:
        self.assertNotIn("error", answer, answer.get("error"))
        return answer

    def refused(self, answer: dict, text: str) -> str:
        self.assertIn("error", answer, answer)
        self.assertIn(text, answer["error"])
        return answer["error"]

    def leftovers(self) -> list[str]:
        return [str(p) for p in Path(self.work).rglob("*.files-tmp")]


class Paths(Base):
    def test_relative_and_absolute_paths_name_the_same_file(self):
        self.put("docs/a.md", "x\n")
        for path in ("docs/a.md", "./docs/a.md", "/work/docs/a.md", "/work//docs/./a.md", " docs/a.md "):
            self.assertEqual(self.ok(self.m.read_file(path))["path"], "/work/docs/a.md", path)

    def test_paths_that_leave_the_folders_are_refused_before_any_file_is_touched(self):
        for path, text in (("../etc/passwd", "'..' is not allowed"), ("docs/../../x", "'..' is not allowed"),
                           ("/etc/passwd", "outside the folders"), ("/workspace/a", "outside the folders"),
                           ("/work/../outside/secret.txt", "'..' is not allowed"), ("~/a", "home folder"),
                           ("docs\\a.md", "use /"), ("a\x00b", "control characters"), ("a\nb", "control"),
                           ("", "a path inside /work"), ("x" * 5000, "at most")):
            self.refused(self.m.read_file(path), text)
        self.refused(self.m.write_file("../x", "a"), "'..' is not allowed")
        self.refused(self.m.read_file("a/" + "n" * 300), "longer than 255 bytes")

    def test_the_root_listing_and_a_folder_that_is_not_mounted(self):
        listing = self.ok(self.m.list_dir("/"))
        self.assertEqual([e["path"] for e in listing["entries"]], ["/work", "/ref1"])
        self.assertTrue(listing["entries"][0]["writable"])
        self.assertFalse(listing["entries"][1]["writable"])
        self.refused(self.m.read_file("/ref2/x"), "no folder is mounted at /ref2")
        with mock.patch.object(self.m, "ROOTS", {"/work": os.path.join(self.base, "gone")}):
            self.refused(self.m.read_file("a"), "no folder is mounted at /work")

    def test_a_link_out_of_the_folder_is_never_followed(self):
        os.symlink(self.outside, os.path.join(self.work, "escape"))
        os.symlink(os.path.join(self.outside, "secret.txt"), os.path.join(self.work, "secret"))
        os.symlink("../outside/secret.txt", os.path.join(self.work, "relative"))
        os.makedirs(os.path.join(self.work, "a/b"))
        os.symlink("../../../outside", os.path.join(self.work, "a/b/up"))
        for path in ("escape/secret.txt", "secret", "relative", "a/b/up/secret.txt"):
            for answer in (self.m.read_file(path), self.m.checksum(path), self.m.list_dir(path),
                           self.m.search("secret", path=path), self.m.diff(path, content="x")):
                error = self.refused(answer, "never followed")
                self.assertNotIn("outside secret", str(answer))
                del error
        self.refused(self.m.copy("escape/secret.txt", "copied.txt"), "symbolic link")
        self.assertFalse(os.path.exists(os.path.join(self.work, "copied.txt")))
        # glob and search do not go through it either
        self.assertEqual(self.ok(self.m.search("outside secret"))["matches"], [])
        self.assertNotIn("/work/escape/secret.txt", self.ok(self.m.glob("**/*.txt"))["matches"])

    def test_a_link_inside_the_folder_is_followed_by_reads_only(self):
        self.put("real/a.md", "hello\n")
        os.symlink("real", os.path.join(self.work, "alias"))
        os.symlink("../real/a.md", os.path.join(self.work, "real/../link.md"))
        os.symlink(os.path.join(self.work, "real", "a.md"), os.path.join(self.work, "absolute.md"))
        answer = self.ok(self.m.read_file("alias/a.md"))
        self.assertEqual((answer["path"], answer["content"]), ("/work/real/a.md", "hello\n"))
        self.assertEqual(answer["followed_links"], ["/work/alias -> real"])
        self.assertEqual(self.ok(self.m.read_file("absolute.md"))["content"], "hello\n")
        # the write tools go through no link, on the way or at the end
        self.refused(self.m.write_file("alias/b.md", "x"), "do not go through links")
        self.refused(self.m.write_file("absolute.md", "x", overwrite=True), "do not go through links")
        self.refused(self.m.edit_file("alias/a.md", "hello", "bye"), "do not go through links")
        self.refused(self.m.append_file("absolute.md", "x"), "do not go through links")
        self.assertEqual(self.raw("real/a.md"), b"hello\n")
        self.assertTrue(os.path.islink(os.path.join(self.work, "absolute.md")))

    def test_link_loops_end(self):
        os.symlink("loop2", os.path.join(self.work, "loop1"))
        os.symlink("loop1", os.path.join(self.work, "loop2"))
        self.refused(self.m.read_file("loop1"), "a loop?")

    def test_a_folder_swapped_for_a_link_while_it_is_walked_is_not_followed(self):
        """The race: the check said "folder", then it became a link to elsewhere before it was opened. O_NOFOLLOW on
        the open by name in the folder before refuses it."""
        self.put("sub/a.txt", "inside\n")
        real_open = os.open
        swapped = []

        def racing_open(path, flags, mode=0o777, *, dir_fd=None):
            if path == "sub" and dir_fd is not None and not swapped:
                os.rename(os.path.join(self.work, "sub"), os.path.join(self.work, "sub-real"))
                os.symlink(self.outside, os.path.join(self.work, "sub"))
                swapped.append(True)
            return real_open(path, flags, mode, dir_fd=dir_fd)

        Path(self.outside, "a.txt").write_text("outside\n")
        with mock.patch.object(self.m.os, "open", racing_open):
            answer = self.m.read_file("sub/a.txt")
        self.assertTrue(swapped)
        self.refused(answer, "changed while it was opened")
        self.assertNotIn("outside", str(answer.get("content", "")))

    def test_a_file_swapped_for_a_link_before_it_is_opened_is_not_followed(self):
        self.put("a.txt", "inside\n")
        real_open = os.open

        def racing_open(path, flags, mode=0o777, *, dir_fd=None):
            if path == "a.txt" and dir_fd is not None and not flags & os.O_DIRECTORY:
                os.unlink(os.path.join(self.work, "a.txt"))
                os.symlink(os.path.join(self.outside, "secret.txt"), os.path.join(self.work, "a.txt"))
            return real_open(path, flags, mode, dir_fd=dir_fd)

        with mock.patch.object(self.m.os, "open", racing_open):
            answer = self.m.read_file("a.txt")
        self.refused(answer, "symbolic link")
        self.assertNotIn("secret", str(answer))

    def test_pipes_sockets_and_folders_are_not_files(self):
        os.mkfifo(os.path.join(self.work, "fifo"))
        sock = socket.socket(socket.AF_UNIX)
        self.addCleanup(sock.close)
        here = os.getcwd()
        os.chdir(self.work)  # a socket's path is short; bind it by its name in the folder
        try:
            sock.bind("sock")
        finally:
            os.chdir(here)
        os.mkdir(os.path.join(self.work, "dir"))
        self.refused(self.m.read_file("fifo"), "named pipe")
        self.refused(self.m.read_file("sock"), "a socket")
        self.refused(self.m.read_file("dir"), "is a folder")
        self.refused(self.m.write_file("fifo", "x", overwrite=True), "named pipe")
        self.refused(self.m.edit_file("fifo", "a", "b"), "named pipe")
        self.refused(self.m.checksum("fifo"), "named pipe")
        self.assertEqual(self.ok(self.m.stat_tool("fifo"))["type"], "pipe")
        self.assertEqual(self.ok(self.m.search("x"))["matches"], [])  # skipped, not blocked on
        self.refused(self.m.copy("fifo", "f2"), "only files and folders are copied")

    def test_the_size_limit(self):
        self.put("big.txt", "x" * 5000)
        with mock.patch.dict(os.environ, {"FILES_MAX_BYTES": "4K"}):
            self.refused(self.m.read_file("big.txt"), "FILES_MAX_BYTES")
            self.refused(self.m.write_file("new.txt", "y" * 5000), "FILES_MAX_BYTES")
            self.refused(self.m.edit_file("big.txt", "x", "y", replace_all=True), "FILES_MAX_BYTES")
            self.assertNotIn("sha256", self.ok(self.m.stat_tool("big.txt")))
        self.assertFalse(os.path.exists(os.path.join(self.work, "new.txt")))
        for bad in ("lots", "1", "999G"):
            with mock.patch.dict(os.environ, {"FILES_MAX_BYTES": bad}):
                self.refused(self.m.read_file("big.txt"), "FILES_MAX_BYTES must")


class ReadOnly(Base):
    def test_files_readonly_refuses_every_write(self):
        self.put("a.md", "# A\n")
        with mock.patch.dict(os.environ, {"FILES_READONLY": "1"}):
            for answer in (self.m.write_file("b.txt", "x"), self.m.write_markdown("b.md", "# B"),
                           self.m.edit_file("a.md", "A", "B"), self.m.insert_lines("a.md", 1, "x"),
                           self.m.delete_lines("a.md", 1, 1), self.m.append_file("a.md", "x"),
                           self.m.apply_patch("a.md", "@@ -1 +1 @@\n-# A\n+# B\n"), self.m.move("a.md", "c.md"),
                           self.m.copy("a.md", "c.md"), self.m.mkdir("d"), self.m.delete("a.md")):
                self.refused(answer, "FILES_READONLY=1")
            self.ok(self.m.read_file("a.md"))
            self.assertFalse(self.ok(self.m.list_dir("/"))["entries"][0]["writable"])
        self.assertEqual(sorted(os.listdir(self.work)), ["a.md"])
        with mock.patch.dict(os.environ, {"FILES_READONLY": "maybe"}):
            self.refused(self.m.write_file("b.txt", "x"), "FILES_READONLY must be 1 or 0")

    def test_the_reference_folders_are_never_written(self):
        self.refused(self.m.write_file("/ref1/new.md", "x"), "/ref1 is read-only")
        self.refused(self.m.delete("/ref1/guide.md"), "/ref1 is read-only")
        self.refused(self.m.move("/ref1/guide.md", "g.md"), "/ref1 is read-only")
        self.assertEqual(self.ok(self.m.read_file("/ref1/guide.md"))["content"], "# Guide\n\nread me\n")
        copied = self.ok(self.m.copy("/ref1/guide.md", "guide.md"))  # copying out of it is fine
        self.assertEqual(copied["to"], "/work/guide.md")
        self.assertEqual(self.raw("guide.md"), b"# Guide\n\nread me\n")

    def test_a_folder_mounted_read_only_is_refused_for_writes(self):
        real = os.fstatvfs

        def readonly_fs(fd):
            result = real(fd)
            return os.statvfs_result((*result[:8], result.f_flag | os.ST_RDONLY, *result[9:]))

        with mock.patch.object(self.m.os, "fstatvfs", readonly_fs):
            self.refused(self.m.write_file("a.txt", "x"), "mounted read-only")

    def test_git_internals_and_the_trash_are_not_written(self):
        os.mkdir(os.path.join(self.work, ".git"))
        self.refused(self.m.write_file(".git/hooks/pre-commit", "#!/bin/sh\n", create_dirs=True), "git's own")
        self.refused(self.m.write_file("sub/.GIT/config", "x", create_dirs=True), "git's own")
        self.refused(self.m.delete(".git", recursive=True), "git's own")
        self.refused(self.m.write_file(".trash/x", "x", create_dirs=True), "the user's to empty")
        self.refused(self.m.write_file("/work", "x"), "cannot be written")
        self.assertFalse(os.path.exists(os.path.join(self.work, "sub")))


class Reading(Base):
    def test_read_whole_parts_and_line_numbers(self):
        self.put("a.txt", "".join(f"line {i}\n" for i in range(1, 11)))
        whole = self.ok(self.m.read_file("a.txt"))
        self.assertEqual((whole["total_lines"], whole["start_line"], whole["end_line"]), (10, 1, 10))
        self.assertEqual(whole["sha256"], sha(self.raw("a.txt")))
        self.assertNotIn("truncated", whole)
        part = self.ok(self.m.read_file("a.txt", start_line=3, end_line=4, line_numbers=True))
        self.assertEqual(part["content"], "3\tline 3\n4\tline 4\n")
        self.assertNotIn("truncated", part)
        self.refused(self.m.read_file("a.txt", start_line=11), "the file has 10 lines")
        self.refused(self.m.read_file("a.txt", start_line=5, end_line=2), "before start_line")
        self.refused(self.m.read_file("a.txt", start_line=0), "start_line")
        self.refused(self.m.read_file("missing.txt"), "does not exist")

    def test_long_files_come_in_parts(self):
        self.put("long.txt", "".join(f"{i}\n" for i in range(1, 2501)))
        first = self.ok(self.m.read_file("long.txt"))
        self.assertEqual((first["end_line"], first["next_start_line"], first["truncated"]), (1000, 1001, True))
        last = self.ok(self.m.read_file("long.txt", start_line=2001))
        self.assertEqual((last["end_line"], last.get("truncated")), (2500, None))
        self.put("wide.txt", ("y" * 1000 + "\n") * 100)
        wide = self.ok(self.m.read_file("wide.txt"))
        self.assertLessEqual(len(wide["content"]), self.m.MAX_READ_CHARS + 100)
        self.assertTrue(wide["truncated"])

    def test_binary_other_encodings_crlf_and_bom_are_reported(self):
        self.put("bin", b"\x00\x01\x02")
        self.assertTrue(self.ok(self.m.read_file("bin"))["binary"])
        self.assertNotIn("content", self.m.read_file("bin"))
        self.put("latin.txt", "caf\xe9\n".encode("latin-1"))
        self.assertIn("not UTF-8", self.ok(self.m.read_file("latin.txt"))["encoding"])
        self.refused(self.m.edit_file("latin.txt", "caf", "tea"), "not UTF-8 text")
        self.put("crlf.txt", b"a\r\nb\r\n")
        answer = self.ok(self.m.read_file("crlf.txt"))
        self.assertEqual((answer["content"], answer["line_endings"]), ("a\nb\n", "crlf"))
        self.put("bom.txt", b"\xef\xbb\xbfhello")
        answer = self.ok(self.m.read_file("bom.txt"))
        self.assertEqual((answer["content"], answer["byte_order_mark"], answer["no_final_newline"]),
                         ("hello", True, True))


class Writing(Base):
    def test_create_then_no_blind_clobbering(self):
        created = self.ok(self.m.write_file("notes/a.txt", "one\ntwo\n", create_dirs=True))
        self.assertEqual((created["action"], created["lines_added"], created["lines"]), ("created", 2, 2))
        self.assertEqual(created["sha256"], sha(b"one\ntwo\n"))
        self.assertIn("made the folder /work/notes", created["notes"])
        self.refused(self.m.write_file("other/a.txt", "x"), "create_dirs=true makes it")
        error = self.refused(self.m.write_file("notes/a.txt", "new\n"), "exists already")
        self.assertIn(sha(b"one\ntwo\n"), error)
        self.refused(self.m.write_file("notes/a.txt", "new\n", expected_sha256="0" * 64), "changed since it was read")
        self.refused(self.m.write_file("notes/a.txt", "new\n", expected_sha256="abc"), "64 hex digits")
        self.assertEqual(self.raw("notes/a.txt"), b"one\ntwo\n")
        replaced = self.ok(self.m.write_file("notes/a.txt", "one\nthree\n", expected_sha256=created["sha256"]))
        self.assertEqual((replaced["action"], replaced["lines_added"], replaced["lines_removed"]), ("replaced", 1, 1))
        self.assertEqual(replaced["previous_sha256"], created["sha256"])
        same = self.ok(self.m.write_file("notes/a.txt", "one\nthree\n", overwrite=True))
        self.assertEqual(same["action"], "unchanged")
        self.refused(self.m.write_file("notes/a.txt", "x", expected_sha256="0" * 64, overwrite=True),
                     "changed since")

    def test_mode_line_breaks_and_bom_are_kept(self):
        path = self.put("run.sh", b"\xef\xbb\xbf#!/bin/sh\r\necho hi\r\n")
        os.chmod(path, 0o750)
        answer = self.ok(self.m.write_file("run.sh", "#!/bin/sh\necho bye\n", overwrite=True))
        self.assertEqual(self.raw("run.sh"), b"\xef\xbb\xbf#!/bin/sh\r\necho bye\r\n")
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o750)
        self.assertIn("written with CRLF", " ".join(answer["notes"]))
        self.ok(self.m.write_file("run.sh", "#!/bin/sh\n", overwrite=True, line_endings="lf"))
        self.assertEqual(self.raw("run.sh"), b"#!/bin/sh\n")
        self.ok(self.m.write_file("win.txt", "a\r\nb\r\n"))
        self.assertEqual(self.raw("win.txt"), b"a\r\nb\r\n")
        self.ok(self.m.write_file("mixed.txt", "a\nb\r\nc\n"))
        self.assertEqual(self.raw("mixed.txt"), b"a\nb\nc\n")
        self.refused(self.m.write_file("x.txt", "a", line_endings="windows"), "keep, lf or crlf")
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.work, "win.txt")).st_mode), 0o666 & ~self.m.UMASK)

    def test_binary_looking_content_needs_allow_binary(self):
        self.refused(self.m.write_file("b.bin", "a\x00b"), "looks binary")
        self.refused(self.m.write_file("b.bin", "\x01\x02\x03\x04" * 10), "looks binary")
        self.assertFalse(os.path.exists(os.path.join(self.work, "b.bin")))
        self.ok(self.m.write_file("b.bin", "a\x00b", allow_binary=True))
        self.assertEqual(self.raw("b.bin"), b"a\x00b")
        self.refused(self.m.write_file("s.txt", "a\udcffb"), "lone surrogates")

    def test_an_interrupted_write_leaves_the_file_and_no_temporary_file(self):
        self.put("a.txt", "original\n")
        real_fsync = os.fsync
        calls = []

        def failing_fsync(fd):
            calls.append(fd)
            raise OSError(5, "Input/output error")

        with mock.patch.object(self.m.os, "fsync", failing_fsync):
            self.refused(self.m.write_file("a.txt", "new\n", overwrite=True), "Input/output error")
            self.refused(self.m.write_file("b.txt", "new\n"), "Input/output error")
        self.assertTrue(calls)
        self.assertEqual(self.raw("a.txt"), b"original\n")
        self.assertFalse(os.path.exists(os.path.join(self.work, "b.txt")))
        self.assertEqual(self.leftovers(), [])
        del real_fsync

    def test_a_file_changed_while_it_is_written_is_not_replaced(self):
        path = self.put("a.txt", "original\n")
        real_encode = self.m.encode

        def meanwhile(*args, **kwargs):
            path.write_text("someone else's change\n")  # in place: the same inode, another size
            return real_encode(*args, **kwargs)

        with mock.patch.object(self.m, "encode", meanwhile):
            self.refused(self.m.edit_file("a.txt", "original", "mine"), "changed while it was written")
        self.assertEqual(path.read_text(), "someone else's change\n")

        def swapped(*args, **kwargs):
            os.unlink(path)
            path.write_text("a new file\n")
            return real_encode(*args, **kwargs)

        with mock.patch.object(self.m, "encode", swapped):
            self.refused(self.m.write_file("a.txt", "mine\n", overwrite=True), "changed while it was written")
        self.assertEqual(path.read_text(), "a new file\n")

        def appeared(*args, **kwargs):
            Path(self.work, "new.txt").write_text("first\n")
            return real_encode(*args, **kwargs)

        with mock.patch.object(self.m, "encode", appeared):
            self.refused(self.m.write_file("new.txt", "second\n"), "appeared while it was written")
        self.assertEqual(self.raw("new.txt"), b"first\n")
        self.assertEqual(self.leftovers(), [])

    def test_a_write_replaces_the_name_never_the_inode_of_a_hard_link(self):
        path = self.put("a.txt", "shared\n")
        other = os.path.join(self.outside, "hardlink.txt")
        os.link(path, other)
        self.ok(self.m.write_file("a.txt", "mine\n", overwrite=True))
        self.assertEqual(Path(other).read_text(), "shared\n")
        self.assertEqual(self.raw("a.txt"), b"mine\n")

    def test_append(self):
        self.put("log.txt", "one")
        answer = self.ok(self.m.append_file("log.txt", "two\n"))
        self.assertEqual(self.raw("log.txt"), b"one\ntwo\n")
        self.assertIn("added one before the text", " ".join(answer["notes"]))
        self.ok(self.m.append_file("new/log.txt", "first\n", create_dirs=True))
        self.assertEqual(self.raw("new/log.txt"), b"first\n")
        self.refused(self.m.append_file("log.txt", ""), "must not be empty")


class Markdown(Base):
    def repair(self, text, title=None):
        return self.m.repair_markdown(text, title)

    def test_a_fence_around_everything_is_unwrapped(self):
        out, repairs, _, _ = self.repair("```markdown\n# Title\n\nText\n\n```python\nx = 1\n```\n```\n")
        self.assertEqual(out, "# Title\n\nText\n\n```python\nx = 1\n```\n")
        self.assertIn("wrapped in a code fence (markdown)", repairs[0])
        out, repairs, _, _ = self.repair("\n```\n# Title\ntext\n```\n\n")
        self.assertEqual(out, "# Title\ntext\n")
        out, repairs, _, _ = self.repair("```md\n# T\n")  # cut off: the fence never closed
        self.assertEqual(out, "# T\n")
        self.assertIn("never closed", repairs[0])
        # a document that is a code block stays one
        self.assertEqual(self.repair("```python\nprint(1)\n```\n")[0], "```python\nprint(1)\n```\n")
        self.assertEqual(self.repair("```\nplain code\n```\n")[0], "```\nplain code\n```\n")
        # two blocks, the first and last line fences: not one wrapper
        text = "```markdown\nexample\n```\nSome text\n```markdown\nx\n```\n"
        self.assertEqual(self.repair(text)[0], text)

    def test_literal_escapes_are_decoded_when_there_is_no_line_break(self):
        out, repairs, _, _ = self.repair("# Title\\n\\nSay \\\"hi\\\"\\n\\tindented\\n- use `\\n` in code\\n")
        self.assertEqual(out, '# Title\n\nSay "hi"\n\tindented\n- use `\\n` in code\n')
        self.assertIn("decoded 5 \\n, 1 \\t, 2 \\\"", repairs[0])
        # with real line breaks nothing is decoded, but it is reported outside code
        text = "# Title\n\nA literal \\n here\n\n```\nprint('a\\nb')\n```\n"
        out, repairs, warnings, _ = self.repair(text)
        self.assertEqual(out, text)
        self.assertEqual(repairs, [])
        self.assertEqual([w for w in warnings if "literal \\n" in w], [
            "a literal \\n outside code on line 3 (left as is: the text has real line breaks too)"])

    def test_json_string_content_is_decoded(self):
        out, repairs, _, _ = self.repair('"# Title\\n\\nBody with \\"quotes\\"\\n"')
        self.assertEqual(out, '# Title\n\nBody with "quotes"\n')
        self.assertIn("JSON string", repairs[0])
        self.assertEqual(self.repair('"just quoted"')[0], '"just quoted"\n')  # one quoted line: kept
        self.assertEqual(self.repair('"not" and "json"\n')[0], '"not" and "json"\n')

    def test_line_breaks_trailing_whitespace_and_the_end(self):
        out, repairs, _, _ = self.repair("\n\n# T\r\nline one  \r\nline two\r\nend \r\n\tcode\t\rlast")
        self.assertEqual(out, "# T\nline one  \nline two\nend\n\tcode\nlast\n")
        joined = " | ".join(repairs)
        for text in ("normalised to LF (4 CRLF, 1 CR)", "trailing whitespace outside code on lines 6, 7",
                     "2 blank lines at the start", "missing line break at the end"):
            self.assertIn(text, joined)
        # the hard line break (two spaces before the next line) is kept; code keeps its spaces
        out, _, _, _ = self.repair("a  \nb\n\n```\nkeep   \n```\n\n\n")
        self.assertEqual(out, "a  \nb\n\n```\nkeep   \n```\n")

    def test_an_open_code_fence_is_closed_at_the_end(self):
        out, repairs, _, structure = self.repair("# T\n\n```bash\necho hi\n")
        self.assertEqual(out, "# T\n\n```bash\necho hi\n```\n")
        self.assertIn("opened at line 3 (```bash) was not closed", repairs[0])
        self.assertTrue(structure["code_fences_balanced"])
        out, _, _, _ = self.repair("~~~~\na\n```\n")
        self.assertEqual(out, "~~~~\na\n```\n~~~~\n")

    def test_headings_without_a_space_outside_code(self):
        text = ("#Title\n\n##Section two\n\n#include <stdio.h>\n#123 is an issue\n#fff\n#tag1 #tag2\n#!/bin/sh\n"
                "\n```python\n#comment in code\n```\n\n<!--\n#not a heading in a comment\n-->\n")
        out, repairs, _, _ = self.repair(text)
        self.assertEqual(out.split("\n")[:3], ["# Title", "", "## Section two"])
        for kept in ("#include <stdio.h>", "#123 is an issue", "#fff", "#tag1 #tag2", "#!/bin/sh",
                     "#comment in code", "#not a heading in a comment"):
            self.assertIn("\n" + kept + "\n", out)
        self.assertIn("missing space after # in 2 headings (lines 1, 3)", " ".join(repairs))

    def test_the_first_heading_repeated_and_the_title(self):
        out, repairs, _, _ = self.repair("# Report\n\n# Report\n\nText\n")
        self.assertEqual(out, "# Report\n\nText\n")
        self.assertIn("repeated right after itself", repairs[0])
        out, repairs, _, _ = self.repair("Text\n", title="Report")
        self.assertEqual(out, "# Report\n\nText\n")
        out, repairs, _, _ = self.repair("# report\n\nText\n", title="Report")
        self.assertEqual((out, repairs), ("# report\n\nText\n", []))
        out, _, warnings, _ = self.repair("# Other\n\nText\n", title="Report")
        self.assertEqual(out, "# Other\n\nText\n")
        self.assertIn("title \"Report\" not added", warnings[0])
        out, _, _, _ = self.repair("---\ntitle: x\n---\nText\n", title="Report")
        self.assertEqual(out, "---\ntitle: x\n---\n# Report\n\nText\n")

    def test_tables_are_reported_not_rewritten(self):
        text = "| a | b | c |\n|---|---|---|\n| 1 | 2 |\n| 1 | 2 | 3 | 4 |\n| `x|y` | 2 | 3 |\n\n| a | b |\n| c | d |\n"
        out, repairs, warnings, structure = self.repair(text)
        self.assertEqual(out, text)
        self.assertEqual(repairs, [])
        self.assertIn("table at line 1 has 3 columns, but rows at line 3 (2), 4 (4) differ", warnings[0])
        self.assertIn("lines 7-8 look like a table but have no delimiter row", warnings[1])
        self.assertEqual(structure["tables"], 1)
        _, _, warnings, _ = self.repair("| a | b |\n|---|\n| 1 | 2 |\n")
        self.assertIn("the header has 2 columns but the delimiter row under it 1", warnings[0])

    def test_html_and_scripts_are_kept_and_reported(self):
        text = "# T\n\n<div align=\"center\">x</div>\n\n<script>alert(1)</script>\n\n`<b>` in code\n\n<https://example.com>\n"
        out, _, warnings, _ = self.repair(text)
        self.assertEqual(out, text)
        joined = " | ".join(warnings)
        self.assertIn("line 5: active HTML (<script)", joined)
        self.assertIn("raw HTML on line 3 (left as is)", joined)
        _, _, warnings, _ = self.repair("a <!-- open\n\nb\n")
        self.assertIn("HTML comment (<!--) opened at line 1 is not closed", warnings[0])

    def test_links_heading_levels_and_front_matter(self):
        text = "# T\n\n### Deep\n\n[a](http://x\n[b]()\n[c][nowhere]\n[d][ok]\n\n[ok]: http://example.com\n"
        _, _, warnings, structure = self.repair(text)
        joined = " | ".join(warnings)
        for part in ("jumps from level 1 to 3", "line 5: a link's ( is not closed", "line 6: a link with an empty",
                     "[nowhere] has no definition"):
            self.assertIn(part, joined)
        self.assertNotIn("[ok] has no definition", joined)
        _, _, warnings, _ = self.repair("---\ntitle: x\nno end\n")
        self.assertIn("front matter (---) that is not closed", warnings[0])
        out, repairs, _, _ = self.repair("---\ntitle: x  \n#x: y\n---\n#Title\n")
        self.assertEqual(out, "---\ntitle: x  \n#x: y\n---\n# Title\n")

    def test_lists_with_tabs_are_left_as_they_are(self):
        text = "- a\n\t- b\n    - c\n"
        self.assertEqual(self.repair(text)[:2], (text, []))

    def test_write_markdown_writes_the_repair_and_reports_it(self):
        broken = "```markdown\n#Notes\r\n\r\n#Notes\r\nSome text   \r\n\r\n```sh\r\nls\r\n```\r\n```"
        answer = self.ok(self.m.write_markdown("docs/notes.md", broken, create_dirs=True))
        self.assertEqual(self.raw("docs/notes.md"), b"# Notes\n\nSome text\n\n```sh\nls\n```\n")
        self.assertEqual(answer["action"], "created")
        self.assertEqual(len(answer["repairs"]), 5, answer["repairs"])
        self.assertEqual(answer["sha256"], sha(self.raw("docs/notes.md")))
        self.refused(self.m.write_markdown("docs/notes.md", "# New\n"), "exists already")
        self.refused(self.m.write_markdown("notes.txt", "# x"), "use write_file")
        self.refused(self.m.write_markdown("a.md", ""), "must not be empty")
        self.refused(self.m.write_markdown("a.md", "\n\n  \n"), "nothing left to write")
        self.refused(self.m.write_markdown("a.md", "x", title="a\nb"), "one line")

    def test_write_markdown_keeps_an_existing_crlf_file_crlf(self):
        self.put("win.md", b"# Old\r\n")
        old = sha(b"# Old\r\n")
        self.ok(self.m.write_markdown("win.md", "# New\n\ntext\n", expected_sha256=old))
        self.assertEqual(self.raw("win.md"), b"# New\r\n\r\ntext\r\n")

    def test_a_dry_run_writes_nothing(self):
        answer = self.ok(self.m.write_markdown("plan.md", "#Plan\\n\\n- one\\n- two", dry_run=True))
        self.assertEqual(answer["would"], "create the file")
        self.assertIn("+# Plan", answer["changes_to_content"])
        self.assertFalse(os.path.exists(os.path.join(self.work, "plan.md")))
        self.put("plan.md", "# Plan\n")
        answer = self.ok(self.m.write_markdown("plan.md", "# Plan\n\n- one\n", dry_run=True))
        self.assertEqual((answer["would"], answer["sha256_now"]), ("replace the file", sha(b"# Plan\n")))
        self.assertIn("expected_sha256", answer["needs"])
        self.assertIn("+- one", answer["diff"])
        self.assertEqual(self.raw("plan.md"), b"# Plan\n")
        with mock.patch.dict(os.environ, {"FILES_READONLY": "1"}):
            self.assertIn("FILES_READONLY", self.ok(self.m.write_markdown("x.md", "# X", dry_run=True))
                          ["would_be_refused"])
        self.assertIn("create_dirs=true", self.ok(self.m.write_markdown("new/x.md", "# X", dry_run=True))["needs"])


class Editing(Base):
    def test_exact_unique_replacement(self):
        self.put("a.py", "def f():\n    return 1\n\n\ndef g():\n    return 2\n")
        answer = self.ok(self.m.edit_file("a.py", "    return 2\n", "    return 3\n"))
        self.assertEqual((answer["match"], answer["line"], answer["lines_added"], answer["lines_removed"]),
                         ("exact", 6, 1, 1))
        self.assertIn("6\t    return 3", answer["preview"])
        self.assertEqual(answer["sha256"], sha(self.raw("a.py")))

    def test_zero_or_several_matches_are_refused(self):
        self.put("a.py", "x = 1\ny = 1\nx = 1\n")
        error = self.refused(self.m.edit_file("a.py", "x = 1", "x = 2"), "occurs 2 times (lines 1, 3)")
        del error
        error = self.refused(self.m.edit_file("a.py", "z = 1", "z = 2"), "was not found")
        self.assertIn("most similar place is at line", error)
        self.assertEqual(self.raw("a.py"), b"x = 1\ny = 1\nx = 1\n")
        every = self.ok(self.m.edit_file("a.py", "x = 1", "x = 2", replace_all=True))
        self.assertEqual((every["replaced"], every["lines_changed_at"]), (2, [1, 3]))
        self.refused(self.m.edit_file("a.py", "x", "x"), "the same")
        self.refused(self.m.edit_file("a.py", "", "x"), "must not be empty")

    def test_the_whitespace_tolerant_fallback_takes_exactly_one_match(self):
        self.put("a.py", "if x:\n        call(a,  b)\n")
        answer = self.ok(self.m.edit_file("a.py", "    call(a, b)", "    call(a, c)"))
        self.assertEqual(answer["match"], "whitespace-tolerant")
        self.assertIn("differs only in spaces", answer["notes"][0])
        self.assertEqual(self.raw("a.py"), b"if x:\n        call(a, c)\n")
        self.put("b.py", "f( a )\nf(  a  )\n")
        self.refused(self.m.edit_file("b.py", "f(a )", "g"), "was not found")
        self.refused(self.m.edit_file("b.py", "f(\ta )", "g"), "matches 2 places")
        self.put("c.txt", "one two\nthree\n")
        self.ok(self.m.edit_file("c.txt", "two three", "2 3"))
        self.assertEqual(self.raw("c.txt"), b"one 2 3\n")

    def test_line_numbers_copied_from_read_file_are_left_out(self):
        self.put("a.txt", "alpha\nbeta\ngamma\n")
        answer = self.ok(self.m.edit_file("a.txt", "2\tbeta\n3\tgamma\n", "2\tBETA\n3\tgamma\n"))
        self.assertIn("line numbers", answer["notes"][0])
        self.assertEqual(self.raw("a.txt"), b"alpha\nBETA\ngamma\n")

    def test_edits_keep_crlf_and_check_expected_sha256(self):
        self.put("w.txt", b"a\r\nb\r\n")
        self.refused(self.m.edit_file("w.txt", "a", "c", expected_sha256="1" * 64), "changed since")
        self.ok(self.m.edit_file("w.txt", "a\nb", "c\nd", expected_sha256=sha(b"a\r\nb\r\n")))
        self.assertEqual(self.raw("w.txt"), b"c\r\nd\r\n")
        self.refused(self.m.edit_file("nope.txt", "a", "b"), "does not exist")

    def test_insert_and_delete_lines(self):
        self.put("a.txt", "1\n2\n3\n")
        self.ok(self.m.insert_lines("a.txt", 1, "0"))
        self.ok(self.m.insert_lines("a.txt", 5, "4\n5\n"))
        self.assertEqual(self.raw("a.txt"), b"0\n1\n2\n3\n4\n5\n")
        self.refused(self.m.insert_lines("a.txt", 8, "x"), "the file has 6 lines (use 7")
        answer = self.ok(self.m.delete_lines("a.txt", 2, 3))
        self.assertEqual(answer["deleted"], ["2\t1", "3\t2"])
        self.assertEqual(answer["lines_removed"], 2)
        self.assertEqual(self.raw("a.txt"), b"0\n3\n4\n5\n")
        self.refused(self.m.delete_lines("a.txt", 3, 9), "the file has 4 lines")
        self.refused(self.m.delete_lines("a.txt", 3, 2), "before start")
        self.refused(self.m.insert_lines("a.txt", 1, "x", expected_sha256="2" * 64), "changed since")
        self.put("b.txt", "a\nb")
        self.ok(self.m.delete_lines("b.txt", 2, 2))
        self.assertEqual(self.raw("b.txt"), b"a\n")
        self.put("c.txt", "a\nb")
        self.ok(self.m.delete_lines("c.txt", 1, 1))
        self.assertEqual(self.raw("c.txt"), b"b")
        self.ok(self.m.insert_lines("c.txt", 2, "c"))
        self.assertEqual(self.raw("c.txt"), b"b\nc\n")


class Patching(Base):
    def test_a_clean_patch_and_one_found_elsewhere(self):
        self.put("a.txt", "one\ntwo\nthree\nfour\n")
        answer = self.ok(self.m.apply_patch("a.txt", "--- a/a.txt\n+++ b/a.txt\n@@ -2,2 +2,2 @@\n two\n-three\n"
                                                     "+THREE\n"))
        self.assertEqual(self.raw("a.txt"), b"one\ntwo\nTHREE\nfour\n")
        self.assertEqual((answer["hunks"], answer["lines_added"], answer["lines_removed"]), (1, 1, 1))
        answer = self.ok(self.m.apply_patch("a.txt", "@@ -1,2 +1,3 @@\n THREE\n four\n+five\n"))
        self.assertIn("applied at line 3 (its header says 1)", " ".join(answer["notes"]))
        self.assertEqual(self.raw("a.txt"), b"one\ntwo\nTHREE\nfour\nfive\n")

    def test_a_hunk_that_does_not_apply_writes_nothing_and_shows_the_file(self):
        self.put("a.txt", "one\ntwo\nthree\n")
        error = self.refused(self.m.apply_patch("a.txt", "@@ -1,1 +1,1 @@\n-one\n+ONE\n@@ -2,2 +2,2 @@\n twoo\n"
                                                         "-three\n+3\n"), "hunk 2")
        self.assertIn("but the file has there:\n2\ttwo\n3\tthree", error)
        self.assertIn("nothing was written", error)
        self.assertEqual(self.raw("a.txt"), b"one\ntwo\nthree\n")

    def test_patch_forms(self):
        self.put("a.txt", "a\n\nb\n")
        answer = self.ok(self.m.apply_patch("a.txt", "@@ -1,3 +1,3 @@\n a\n\n-b\n+c\n\\ No newline at end of file\n"))
        self.assertEqual(self.raw("a.txt"), b"a\n\nc")
        self.assertIn("empty context", " ".join(answer["notes"]))
        self.ok(self.m.apply_patch("new.txt", "--- /dev/null\n+++ b/new.txt\n@@ -0,0 +1,2 @@\n+x\n+y\n"))
        self.assertEqual(self.raw("new.txt"), b"x\ny\n")
        self.refused(self.m.apply_patch("a.txt", "--- a\n+++ a\n@@ -1 +1 @@\n-a\n+b\n--- b\n+++ b\n@@ -1 +1 @@\n-x\n+y\n"),
                     "one file")
        self.refused(self.m.apply_patch("a.txt", "just text"), "hunk header")
        self.refused(self.m.apply_patch("a.txt", "@@ -1 +1 @@\n*a\n"), "starts with ' '")
        self.refused(self.m.apply_patch("gone.txt", "@@ -1 +1 @@\n-a\n+b\n"), "does not exist")
        answer = self.ok(self.m.apply_patch("new.txt", "@@ -1,5 +1,5 @@\n-x\n+X\n"))
        self.assertIn("header counts", " ".join(answer["notes"]))


class FilesAndFolders(Base):
    def test_move(self):
        self.put("a.txt", "a\n")
        os.mkdir(os.path.join(self.work, "dir"))
        answer = self.ok(self.m.move("a.txt", "dir"))
        self.assertEqual(answer["to"], "/work/dir/a.txt")
        self.put("b.txt", "b\n")
        self.refused(self.m.move("b.txt", "dir/a.txt"), "exists already")
        self.ok(self.m.move("b.txt", "dir/a.txt", overwrite=True))
        self.assertEqual(self.raw("dir/a.txt"), b"b\n")
        self.refused(self.m.move("dir", "dir/sub"), "inside")
        self.ok(self.m.move("dir/a.txt", "x/y/z.txt", create_dirs=True))
        self.assertEqual(self.raw("x/y/z.txt"), b"b\n")
        os.symlink(self.outside, os.path.join(self.work, "link"))
        self.ok(self.m.move("link", "link2"))  # the link itself
        self.assertEqual(os.readlink(os.path.join(self.work, "link2")), self.outside)
        self.assertTrue(os.path.exists(os.path.join(self.outside, "secret.txt")))
        self.refused(self.m.move("gone", "x"), "does not exist")
        self.put("deep/c.txt", "c\n")
        self.assertEqual(self.ok(self.m.move("deep/c.txt", "/work"))["to"], "/work/c.txt")  # the root as a folder
        self.refused(self.m.copy("c.txt", "."), "src and dst are the same")

    def test_copy(self):
        self.put("src/a.txt", "a\n")
        self.put("src/sub/b.txt", "b\n")
        os.chmod(os.path.join(self.work, "src/a.txt"), 0o640)
        os.symlink(self.outside, os.path.join(self.work, "src/escape"))
        answer = self.ok(self.m.copy("src", "dst"))
        self.assertEqual((answer["type"], answer["entries"], answer["left_out"]), ("dir", 4, ["/work/src/escape"]))
        self.assertEqual(self.raw("dst/sub/b.txt"), b"b\n")
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.work, "dst/a.txt")).st_mode), 0o640)
        self.assertFalse(os.path.lexists(os.path.join(self.work, "dst/escape")))
        self.refused(self.m.copy("src", "dst/a.txt"), "exists already")
        self.assertEqual(self.ok(self.m.copy("src/a.txt", "dst/sub"))["to"], "/work/dst/sub/a.txt")  # into it
        self.refused(self.m.copy("src/sub/b.txt", "dst/a.txt"), "overwrite=true")
        self.ok(self.m.copy("src/sub/b.txt", "dst/a.txt", overwrite=True))
        self.assertEqual(self.raw("dst/a.txt"), b"b\n")
        self.refused(self.m.copy("src", "src/inner"), "inside")
        self.assertEqual(self.leftovers(), [])

    def test_mkdir(self):
        answer = self.ok(self.m.mkdir("a/b/c"))
        self.assertEqual(answer["made_folders"], ["/work/a", "/work/a/b", "/work/a/b/c"])
        self.assertEqual(self.ok(self.m.mkdir("a/b"))["action"], "exists already")
        self.put("f", "x")
        self.refused(self.m.mkdir("f"), "not a folder")
        self.refused(self.m.mkdir("f/g"), "not a folder")

    def test_delete_moves_into_the_trash(self):
        self.put("docs/a.md", "keep me\n")
        self.put("docs/b.md", "b\n")
        answer = self.ok(self.m.delete("docs/a.md"))
        self.assertTrue(answer["moved_to"].startswith("/work/.trash/"))
        self.assertFalse(os.path.exists(os.path.join(self.work, "docs/a.md")))
        trashed = os.path.join(self.work, answer["moved_to"][len("/work/"):])
        self.assertEqual(Path(trashed).read_text(), "keep me\n")
        self.assertEqual(Path(self.work, ".trash/.gitignore").read_text().splitlines()[-1], "*")
        self.ok(self.m.move(answer["moved_to"], "docs/a.md"))  # the restore the answer names
        self.assertEqual(self.raw("docs/a.md"), b"keep me\n")
        self.refused(self.m.delete("docs"), "recursive=true")
        self.ok(self.m.delete("docs", recursive=True))
        self.assertFalse(os.path.exists(os.path.join(self.work, "docs")))
        self.refused(self.m.delete(".trash", recursive=True), "the user's to empty")
        os.symlink(self.outside, os.path.join(self.work, "link"))
        self.ok(self.m.delete("link"))
        self.assertTrue(os.path.exists(os.path.join(self.outside, "secret.txt")))  # never what it points to
        self.refused(self.m.delete("/work"), "cannot be written")

    def test_delete_for_real_without_the_trash(self):
        self.put("tree/a/b.txt", "x")
        with mock.patch.dict(os.environ, {"FILES_TRASH": "0"}):
            self.assertIn("for good", self.ok(self.m.delete("tree", recursive=True))["note"])
        self.assertEqual(os.listdir(self.work), [])

    def test_a_trash_that_is_a_link_is_refused(self):
        os.symlink(self.outside, os.path.join(self.work, ".trash"))
        self.put("a.txt", "x")
        self.refused(self.m.delete("a.txt"), "is not a folder")
        self.assertEqual(self.raw("a.txt"), b"x")
        self.assertEqual(sorted(os.listdir(self.outside)), ["secret.txt"])


class Looking(Base):
    def test_list_dir(self):
        self.put("a.txt", "abc")
        self.put("sub/b.txt", "b")
        self.put("node_modules/x/y.js", "y")
        os.symlink("a.txt", os.path.join(self.work, "l"))
        answer = self.ok(self.m.list_dir(depth=3))
        paths = {e["path"]: e for e in answer["entries"]}
        self.assertEqual(paths["/work/a.txt"]["size"], 3)
        self.assertEqual(paths["/work/l"], {"path": "/work/l", "type": "link", "target": "a.txt"})
        self.assertIn("/work/sub/b.txt", paths)
        self.assertTrue(paths["/work/node_modules"]["not_listed"])
        self.assertNotIn("/work/node_modules/x", paths)
        self.refused(self.m.list_dir("a.txt"), "not a folder")
        self.refused(self.m.list_dir(depth=9), "depth")
        for i in range(600):
            self.put(f"many/{i:03}", "")
        self.assertIn("first 500", self.ok(self.m.list_dir("many"))["truncated"])

    def test_glob(self):
        for name in ("a.md", "docs/b.md", "docs/deep/c.md", "docs/x.txt", ".git/d.md", "src/e.py"):
            self.put(name, "x")
        self.assertEqual(self.ok(self.m.glob("**/*.md"))["matches"],
                         ["/work/a.md", "/work/docs/b.md", "/work/docs/deep/c.md"])
        self.assertEqual(self.ok(self.m.glob("*.md", path="docs"))["matches"], ["/work/docs/b.md"])
        self.assertEqual(self.ok(self.m.glob("/work/docs/*"))["matches"],
                         ["/work/docs/b.md", "/work/docs/deep/", "/work/docs/x.txt"])
        self.assertEqual(self.ok(self.m.glob("/ref1/*.md"))["matches"], ["/ref1/guide.md"])
        self.refused(self.m.glob("../*"), "'..'")
        self.refused(self.m.glob("/etc/*"), "outside")

    def test_search(self):
        self.put("a.py", "def alpha():\n    return 'Beta'\n")
        self.put("b.txt", "beta and BETA\n")
        self.put("bin.dat", b"beta\x00")
        answer = self.ok(self.m.search("beta"))
        self.assertEqual([(m["path"], m["line"]) for m in answer["matches"]], [("/work/b.txt", 1)])
        self.assertEqual(answer["files_skipped"], 1)
        answer = self.ok(self.m.search("beta", ignore_case=True, include="*.py"))
        self.assertEqual(answer["matches"], [{"path": "/work/a.py", "line": 2, "text": "    return 'Beta'"}])
        answer = self.ok(self.m.search(r"def \w+\(", regex=True))
        self.assertEqual(answer["matches"][0]["line"], 1)
        self.refused(self.m.search("(", regex=True), "not a valid regular expression")
        self.assertEqual(self.ok(self.m.search("((", regex=False))["matches"], [])
        self.assertEqual(self.ok(self.m.search("Beta", path="a.py"))["count"], 1)
        for i in range(30):
            self.put(f"many/{i}.txt", "needle\n")
        self.assertIn("more than 5", self.ok(self.m.search("needle", max_results=5))["truncated"])
        self.refused(self.m.search("x", max_results=0), "max_results")

    def test_a_regular_expression_that_backtracks_without_end_is_stopped(self):
        self.put("a.txt", "a" * 40 + "b\n")
        with mock.patch.object(self.m, "TIME_LIMIT", 0.5):
            answer = self.ok(self.m.search(r"(a+)+$", regex=True))
        self.assertIn("stopped after", answer["stopped"])

    def test_stat_checksum_and_diff(self):
        self.put("a.txt", "one\ntwo\n")
        self.put("b.txt", "one\nthree\n")
        info = self.ok(self.m.stat_tool("a.txt"))
        self.assertEqual((info["type"], info["size"], info["lines"], info["sha256"]),
                         ("file", 8, 2, sha(b"one\ntwo\n")))
        self.assertEqual(self.ok(self.m.stat_tool("missing")), {"path": "/work/missing", "exists": False})
        os.symlink("a.txt", os.path.join(self.work, "l"))
        link = self.ok(self.m.stat_tool("l"))
        self.assertEqual((link["type"], link["points_to"], link["target_exists"]), ("link", "/work/a.txt", True))
        self.assertEqual(self.ok(self.m.stat_tool("/work"))["entries"], 3)
        self.assertEqual(self.ok(self.m.checksum("a.txt"))["checksum"], sha(b"one\ntwo\n"))
        self.assertEqual(self.ok(self.m.checksum("a.txt", algorithm="md5"))["checksum"],
                         hashlib.md5(b"one\ntwo\n").hexdigest())
        self.refused(self.m.checksum("a.txt", algorithm="crc"), "algorithm")
        answer = self.ok(self.m.diff("a.txt", "b.txt"))
        self.assertEqual((answer["lines_added"], answer["lines_removed"], answer["identical"]), (1, 1, False))
        self.assertIn("-two\n+three", answer["diff"])
        self.assertTrue(self.ok(self.m.diff("a.txt", content="one\ntwo\n"))["identical"])
        self.refused(self.m.diff("a.txt"), "one of the two")
        self.refused(self.m.diff("a.txt", "b.txt", content="x"), "one of the two")


class Limits(Base):
    def test_time_limits_nest(self):
        import time as clock
        with self.m.time_limit(5):
            with self.assertRaises(self.m.TimeLimit):
                with self.m.time_limit(0.2):
                    clock.sleep(1)
            import signal
            left, _ = signal.getitimer(signal.ITIMER_REAL)
            self.assertGreater(left, 3)  # the enclosing limit goes on
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0], 0)

    def test_tool_descriptions_name_what_they_write(self):
        import json
        recorded = json.loads((ROOT / "servers/files/tools.json").read_text())
        tools = {tool.name: tool for tool in self.m.mcp._tool_manager.list_tools()}
        self.assertEqual(sorted(tools), recorded["tools"])
        for name in recorded["write_tools"]:
            self.assertTrue(tools[name].description.startswith("WRITES"), name)
            self.assertFalse(tools[name].annotations.readOnlyHint, name)
        for name in recorded["read_only_tools"]:
            self.assertTrue(tools[name].annotations.readOnlyHint, name)
        self.assertEqual(set(recorded["write_tools"]) | set(recorded["read_only_tools"]), set(recorded["tools"]))


class IndependentReview(Base):
    """Found by the independent review of 2026-11-13 (servers/files/PROVENANCE.md); each failed before its fix."""

    def test_an_over_indented_fence_line_does_not_close_a_code_block(self):
        # a line indented 4 spaces or more inside a fence is code (CommonMark), not its closing fence: what follows
        # stays code - no '# ' added to a comment, no trailing spaces removed, no extra fence at the end
        text = "# T\n\n```text\n    ```\n#comment in code   \n```\n"
        out, repairs, _, structure = self.m.repair_markdown(text)
        self.assertEqual((out, repairs), (text, []))
        self.assertTrue(structure["code_fences_balanced"])
        # a fence inside a list item may be indented; its closing fence too
        text = "- item\n\n  ```sh\n  #x   \n  ```\n"
        self.assertEqual(self.m.repair_markdown(text)[0], text)
        # an open fence is closed at its own indentation
        self.assertEqual(self.m.repair_markdown("- a\n\n  ```sh\n  ls\n")[0], "- a\n\n  ```sh\n  ls\n  ```\n")

    def test_raw_html_blocks_and_indented_code_are_left_alone(self):
        for text in ("# T\n\n<pre>\n#notheading\nkeep   \n</pre>\n",
                     "# T\n\n<script>\n#x  \n</script>\n",
                     "# T\n\nText\n\n    #!/bin/sh\n    #comment   \n\tindented\t\n"):
            with self.subTest(text=text):
                out, repairs, _, _ = self.m.repair_markdown(text)
                self.assertEqual((out, repairs), (text, []))
        # a tab-indented line right after a paragraph line continues the paragraph: still repaired
        self.assertEqual(self.m.repair_markdown("end\n\tcode\t\n")[0], "end\n\tcode\n")

    def test_one_quoted_line_is_not_taken_for_a_json_string(self):
        for text in ('"To be or not to be"', '"C:\\temp"', '"\\u0041"'):
            with self.subTest(text=text):
                self.assertEqual(self.m.repair_markdown(text)[0], text + "\n")
        out, repairs, _, _ = self.m.repair_markdown('"# Title\\n\\nBody\\n"')
        self.assertEqual(out, "# Title\n\nBody\n")

    def test_long_names_beyond_ascii_are_written_and_copied(self):
        name = "\u6587" * 84  # 252 bytes: a valid name, but a temporary name of 100 such characters is not
        self.ok(self.m.write_file(name + ".md", "hi\n"))
        self.ok(self.m.write_markdown(name[:-1] + ".md", "# hi\n"))
        self.put("tree/a.txt", "a\n")
        self.ok(self.m.copy("tree", name))
        self.ok(self.m.copy(name + ".md", name[:-1] + "x"))
        self.assertEqual(Path(self.work, name, "a.txt").read_text(), "a\n")

    def test_the_trash_gitignore_is_never_written_through_a_link(self):
        # .trash swapped for a link between its mkdir and the .gitignore's creation (an agent racing the server)
        real_mkdir = os.mkdir
        outside = self.outside

        def racing(path, mode=0o777, *, dir_fd=None):
            real_mkdir(path, mode, dir_fd=dir_fd)
            if path == ".trash":
                os.rmdir(path, dir_fd=dir_fd)
                os.symlink(outside, path, dir_fd=dir_fd)

        self.put("a.txt", "x")
        with mock.patch.object(self.m.os, "mkdir", racing):
            self.refused(self.m.delete("a.txt"), "is not a folder")
        self.assertEqual(sorted(os.listdir(self.outside)), ["secret.txt"])
        self.assertEqual(self.raw("a.txt"), b"x")

    def test_git_spelled_with_invisible_or_compatibility_characters_is_still_git(self):
        # on a file system that ignores or folds such characters (HFS+, some network shares) these are .git
        for path in (".git\u200c/hooks/pre-commit", ".\uff47it/config", "sub/.G\u00ADIT/hooks/x", ".Trash/x"):
            with self.subTest(path=path):
                self.assertIn("error", self.m.write_file(path, "x", create_dirs=True))
        self.assertEqual(os.listdir(self.work), [])


if __name__ == "__main__":
    unittest.main()
