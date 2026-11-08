#!/usr/bin/env python3
"""Write the binary smoke fixtures of the file-analysis servers, each checked against its SHA-256.

The text fixtures of the search servers (recorded answers) are files in ``tests/fixtures``. The
binary inputs of the file-analysis servers (radare2, capa, binwalk) would be opaque blobs in the
repository, so they live in ``tests/fixtures/analysis-files.json`` as base64 of their gzip, pinned
by the SHA-256 of the file itself, with a line saying what each one is and where it comes from.

    scripts/fixtures.py                 # write them into tests/fixtures
    scripts/fixtures.py --out DIR       # ... into DIR (what CI passes as --var FIXTURES=DIR)
    scripts/fixtures.py --check         # only check the pins (writes nothing)

A file whose bytes do not hash to the pinned SHA-256 is never written: exit 1 and nothing touched.
The fixtures are read by the analysis tools inside their container; nothing ever executes them.
Standard library only.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import gzip
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "tests/fixtures/analysis-files.json"
SCHEMA = "sandbox-ai-mcp-fixtures"
VERSION = 1
MAX_SIZE = 4 << 20
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class FixtureProblem(ValueError):
    """What is wrong with the fixture spec, as text."""


def load(spec: Path = SPEC) -> list[dict]:
    """The fixtures of *spec*: ``[{"path", "sha256", "size", "data"}]``, every pin checked."""
    document = json.loads(spec.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("schema") != SCHEMA or document.get("version") != VERSION \
            or not isinstance(document.get("files"), list) or not document["files"]:
        raise FixtureProblem(f"{spec.name}: expected {{\"schema\": \"{SCHEMA}\", \"version\": {VERSION}, "
                             "\"files\": [...]}")
    out, seen = [], set()
    for entry in document["files"]:
        if not isinstance(entry, dict):
            raise FixtureProblem(f"{spec.name}: a file must be an object")
        name = entry.get("path")
        if not isinstance(name, str) or not _NAME.match(name):
            raise FixtureProblem(f"{spec.name}: {name!r} is not a plain file name")
        if name in seen:
            raise FixtureProblem(f"{spec.name}: {name} is there twice")
        seen.add(name)
        if not isinstance(entry.get("sha256"), str) or not _SHA256.match(entry["sha256"]):
            raise FixtureProblem(f"{spec.name}: {name}: sha256 must be 64 lower-case hex digits")
        if not isinstance(entry.get("what"), str) or not entry["what"].strip():
            raise FixtureProblem(f"{spec.name}: {name}: 'what' must say what the file is")
        try:
            data = gzip.decompress(base64.b64decode(entry.get("gzip_base64") or "", validate=True))
        except (binascii.Error, OSError, ValueError, TypeError) as exc:
            raise FixtureProblem(f"{spec.name}: {name}: gzip_base64 is not base64 of a gzip ({exc})") from None
        if len(data) > MAX_SIZE:
            raise FixtureProblem(f"{spec.name}: {name}: larger than {MAX_SIZE >> 20} MiB "
                                 "(fixtures are small by design)")
        found = hashlib.sha256(data).hexdigest()
        if found != entry["sha256"]:
            raise FixtureProblem(f"{spec.name}: {name}: the bytes hash to {found}, the spec pins {entry['sha256']}")
        if entry.get("size") not in (None, len(data)):
            raise FixtureProblem(f"{spec.name}: {name}: size says {entry['size']}, the bytes are {len(data)}")
        out.append({"path": name, "sha256": found, "size": len(data), "data": data})
    return out


def write(fixtures: list[dict], out: Path) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for fixture in fixtures:
        path = out / fixture["path"]
        path.write_bytes(fixture["data"])
        path.chmod(0o644)  # never executable: these files are analysed, not run
        written.append(path)
    return written


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--spec", type=Path, default=SPEC)
    parser.add_argument("--out", type=Path, default=SPEC.parent, help="default: tests/fixtures")
    parser.add_argument("--check", action="store_true", help="check the pins, write nothing")
    opts = parser.parse_args(argv)
    try:
        fixtures = load(opts.spec)
    except (FixtureProblem, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    names = ", ".join(f"{f['path']} ({f['size']} bytes)" for f in fixtures)
    if opts.check:
        print(f"OK: {len(fixtures)} fixtures match their SHA-256: {names}")
        return 0
    write(fixtures, opts.out)
    print(f"wrote {len(fixtures)} fixtures to {opts.out}: {names}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
