#!/usr/bin/env python3
"""The extension's runtime dependencies against Maven Central (the build stage of servers/burp/Dockerfile).

Gradle resolved the runtime class path the fat jar is made of; LISTING has one line per jar, "GROUP:MODULE:VERSION
PATH". Each jar must be the one Maven Central publishes: its SHA-1 equal to the .sha1 file published beside it (and
its SHA-256 to the .sha256 where there is one), else this fails the build. The result - coordinates, file, SHA-256,
the licence names of its POM - is written to OUT (in the image: /opt/burp-mcp/runtime-dependencies.json), so what the
jar contains can be read without unpacking it. Standard library only.

    python3 -I check_dependencies.py LISTING OUT
"""
import hashlib
import json
import re
import sys
import urllib.error
import urllib.request

CENTRAL = "https://repo1.maven.org/maven2/"
COORDINATE = re.compile(r"([A-Za-z0-9_.-]+):([A-Za-z0-9_.-]+):([A-Za-z0-9_.+-]+)")


def fetch(url, limit=1 << 20):
    try:
        with urllib.request.urlopen(url, timeout=60) as answer:
            return answer.read(limit)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def digest(path, name):
    hasher = hashlib.new(name)
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            hasher.update(block)
    return hasher.hexdigest()


def published(text):
    """The checksum of a .sha1/.sha256 file (its first word, lower case)."""
    words = text.decode("ascii", "replace").split()
    return words[0].lower() if words else ""


def licences(pom):
    if not pom:
        return []
    text = pom.decode("utf-8", "replace")
    block = re.search(r"<licenses>(.*?)</licenses>", text, re.S)
    return re.findall(r"<name>\s*(.*?)\s*</name>", block.group(1), re.S) if block else []


def main(argv):
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    listing, out = argv
    rows, problems = [], []
    for line in open(listing, encoding="utf-8").read().splitlines():
        if not line.strip():
            continue
        coordinate, path = line.split(" ", 1)
        match = COORDINATE.fullmatch(coordinate)
        if not match:
            problems.append(f"{coordinate}: not GROUP:MODULE:VERSION")
            continue
        group, module, version = match.groups()
        name = path.rsplit("/", 1)[-1]
        base = f"{CENTRAL}{group.replace('.', '/')}/{module}/{version}/"
        sha1, sha256 = digest(path, "sha1"), digest(path, "sha256")
        central_sha1 = fetch(base + name + ".sha1")
        if central_sha1 is None:
            problems.append(f"{coordinate}: {name} is not on Maven Central")
            continue
        if published(central_sha1) != sha1:
            problems.append(f"{coordinate}: {name} differs from Maven Central's (SHA-1 {sha1}, published "
                            f"{published(central_sha1)})")
            continue
        central_sha256 = fetch(base + name + ".sha256")
        if central_sha256 is not None and published(central_sha256) != sha256:
            problems.append(f"{coordinate}: {name} differs from Maven Central's SHA-256")
            continue
        pom = fetch(f"{base}{module}-{version}.pom")
        rows.append({"coordinate": coordinate, "file": name, "sha256": sha256, "licenses": licences(pom)})
        print(f"{coordinate}  {name}  sha256 {sha256}  = Maven Central")
    if problems or not rows:
        for problem in problems or ["no runtime dependency listed"]:
            print(f"error: {problem}", file=sys.stderr)
        return 1
    with open(out, "w", encoding="utf-8") as handle:
        json.dump({"about": "The runtime dependencies inside burp-mcp-all.jar, each checked against Maven Central "
                            "when the image was built (servers/burp/check_dependencies.py)",
                   "dependencies": sorted(rows, key=lambda row: row["coordinate"])}, handle, indent=1)
        handle.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
