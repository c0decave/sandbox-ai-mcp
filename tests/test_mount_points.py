"""Every folder a server's catalog entry lets sandbox-ai mount is already there in its image.

Catalog CI 45006851694 (2026-11-22): files and code-search failed under Bubblewrap with "bwrap: Can't mkdir /work:
Read-only file system". Podman makes a missing mount point itself; Bubblewrap binds a folder only onto one that is
there, and the server's root file system (its rootfs) is mounted read-only. So each image makes every target its
server.json declares (mkdir -p or install -d, before it drops to its user)."""
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parent.parent


def made_folders(dockerfile: str) -> set[str]:
    """The absolute folders a Dockerfile's RUN lines make with mkdir or install -d (flags skipped)."""
    text = re.sub(r"\\\n", " ", dockerfile)  # continued lines as one
    made = set()
    for command in re.findall(r"(?:mkdir|install\s+-d)\b([^&;|\n]*)", text):
        made |= {word.strip("\"'").rstrip("/") for word in command.split() if word.strip("\"'").startswith("/")}
    return made


class MountPoints(unittest.TestCase):
    def test_every_declared_mount_target_is_made_by_the_image(self):
        missing = {}
        for entry in sorted((ROOT / "servers").glob("*/server.json")):
            targets = {mount["target"].rstrip("/") for mount in json.loads(entry.read_text()).get("mounts", [])}
            dockerfile = next((entry.parent / name for name in ("Dockerfile", "Containerfile")
                               if (entry.parent / name).is_file()), None)
            if not targets or dockerfile is None:
                continue
            lacking = sorted(targets - made_folders(dockerfile.read_text()))
            if lacking:
                missing[entry.parent.name] = lacking
        self.assertEqual(missing, {}, "a mount target its image does not make: Bubblewrap cannot mount there")

    def test_every_image_makes_the_usual_mount_targets(self):
        """The user (2026-11-22): /work, /work_ro, /work_rw, /app and /srv exist in every server's image, so any of
        them can be mounted under Bubblewrap whatever the entry declares."""
        usual = {"/work", "/work_ro", "/work_rw", "/app", "/srv"}
        lacking = {}
        for folder in sorted([*(ROOT / "servers").iterdir(), *(ROOT / "candidates").iterdir()]):
            dockerfile = next((folder / name for name in ("Dockerfile", "Containerfile") if (folder / name).is_file()),
                              None)
            if dockerfile is not None and usual - made_folders(dockerfile.read_text()):
                lacking[f"{folder.parent.name}/{folder.name}"] = sorted(usual - made_folders(dockerfile.read_text()))
        self.assertEqual(lacking, {})

    def test_the_folder_parser(self):
        self.assertEqual(made_folders("RUN useradd x \\\n && mkdir -p /work /out\n"), {"/work", "/out"})
        self.assertEqual(made_folders("RUN install -d -o 10001 -g 10001 -m 0700 /data \\\n && install -d /send"),
                         {"/data", "/send"})
        self.assertEqual(made_folders("RUN mkdir -p /opt/x/ && echo /notmade"), {"/opt/x"})


if __name__ == "__main__":
    unittest.main()
