"""Compare the jars a server ships with the same release in its publisher's Maven repository (CI, before the build).

A server whose jars come from somewhere other than a Maven repository (a GitHub release asset) names, in
``servers/NAME/maven-central.json``, the Dockerfile ARGs that pin each jar (its URL and SHA-256), where the image
keeps it, the Maven artifacts it is built from, and the repository they are in (``repository``: Maven Central, the
default, or Google's Maven, where Google publishes com.android.tools.* - smali 3.0.10 is there, not on Maven Central)::

    {"schema": "sandbox-ai-mcp-maven-central", "version": 1,
     "repository": "https://dl.google.com/dl/android/maven2",
     "jars": [{"url_arg": "SMALI_URL", "sha256_arg": "SMALI_SHA256",
               "image_path": "/opt/smali/smali-3.0.10-fat-release.jar",
               "built_from": ["com.android.tools.smali:smali:3.0.10", ...],
               "own_prefixes": ["com/android/tools/smali/"]}]}

What is compared, per jar:

1. The shipped jar is downloaded from the URL of its ARG and must hash to the ARG's SHA-256 (the bytes the image's
   ``ADD --checksum`` takes). Each Maven jar is downloaded from the repository, with every checksum file
   (``.sha1``, ``.sha256``, ``.sha512``) the repository publishes for it, and must hash to each of them (a missing
   one is said; with none, the jar is the one the repository serves over HTTPS, its SHA-256 said).
2. A jar that is byte for byte one of its Maven jars passes as such.
3. Otherwise the entries: every file of every ``built_from`` jar except its ``META-INF/`` must be in the shipped jar
   with identical bytes (nothing of the release left out or changed), and every file of the shipped jar under an
   ``own_prefixes`` folder must be one of those files with identical bytes (nothing added to the release's
   packages). The rest of a fat jar (its bundled third-party libraries) is not compared here.

Any difference fails (exit 1, an ``::error`` annotation). For differing class files, as a diagnosis only (it never
passes a jar), ``javap -c -p`` of both sides is compared with constant-pool numbers left out, when javap is there.

    scripts/maven_central.py --server smali [--report FILE]     # download and compare (no spec: nothing to do)
    scripts/maven_central.py --server smali --image IMG          # the built image ships exactly the pinned jars

Standard library only.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = "sandbox-ai-mcp-maven-central"
VERSION = 1
REPOSITORY = "https://repo1.maven.org/maven2"
#: The Maven repositories a spec may name ("repository", default Maven Central): Maven Central, and Google's Maven
#: (maven.google.com), where Google publishes com.android.tools.* - smali 3.0.10 is there, not on Maven Central.
REPOSITORIES = (REPOSITORY, "https://dl.google.com/dl/android/maven2")
#: The checksum files a repository may publish next to a jar; every one that is there must match.
CHECKSUMS = ("sha1", "sha256", "sha512")
MAX_SIZE = 64 << 20
#: Where a shipped jar may come from (its Dockerfile ARG) - nothing else is fetched.
SHIPPED_HOSTS = ("https://github.com/",)
_COORDINATE = re.compile(r"^([A-Za-z0-9_.-]+):([A-Za-z0-9_.-]+):([A-Za-z0-9_.-]+)$")
_ARG = re.compile(r"^ARG\s+([A-Z0-9_]+)=(\S+)\s*$", re.M)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DIGEST = {"sha1": re.compile(r"^[0-9a-f]{40}$"), "sha256": re.compile(r"^[0-9a-f]{64}$"),
           "sha512": re.compile(r"^[0-9a-f]{128}$")}
DIAGNOSE_MAX = 20

Fetch = Callable[[str], "bytes | None"]


class Problem(ValueError):
    """What is wrong, as text."""


def fetch(url: str) -> bytes | None:
    """The bytes at *url* (``None`` for a 404), three tries, at most MAX_SIZE."""
    last: Exception | None = None
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "sandbox-ai-mcp-ci"})
            with urllib.request.urlopen(request, timeout=60) as answer:  # noqa: S310 - https URLs checked by callers
                data = answer.read(MAX_SIZE + 1)
            if len(data) > MAX_SIZE:
                raise Problem(f"{url}: larger than {MAX_SIZE} bytes")
            return data
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            last = error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            last = error
        time.sleep(5 * (attempt + 1))
    raise Problem(f"{url}: {last}")


def load_spec(folder: Path) -> dict | None:
    """The checked spec of the server in *folder*, with each jar's URL and SHA-256 from its Dockerfile; ``None``
    when the server has no maven-central.json."""
    path = folder / "maven-central.json"
    if not path.is_file():
        return None
    spec = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(spec, dict) or spec.get("schema") != SCHEMA or spec.get("version") != VERSION \
            or not isinstance(spec.get("jars"), list) or not spec["jars"]:
        raise Problem(f"{path}: expected {{\"schema\": \"{SCHEMA}\", \"version\": {VERSION}, \"jars\": [...]}}")
    repository = spec.get("repository", REPOSITORY)
    if repository not in REPOSITORIES:
        raise Problem(f"{path}: repository {repository!r} is none of {', '.join(REPOSITORIES)}")
    args = dict(_ARG.findall((folder / "Dockerfile").read_text(encoding="utf-8")))
    jars = []
    for jar in spec["jars"]:
        if not isinstance(jar, dict):
            raise Problem(f"{path}: a jar must be an object")
        url, sha256 = args.get(jar.get("url_arg")), args.get(jar.get("sha256_arg"))
        if not url or not sha256:
            raise Problem(f"{path}: the Dockerfile has no ARG {jar.get('url_arg')} / {jar.get('sha256_arg')}")
        if not url.startswith(SHIPPED_HOSTS) or not _SHA256.match(sha256):
            raise Problem(f"{path}: {jar['url_arg']}={url} is not an https URL of {SHIPPED_HOSTS} with a SHA-256")
        image_path = jar.get("image_path")
        if not isinstance(image_path, str) or not image_path.startswith("/opt/") or ".." in image_path:
            raise Problem(f"{path}: image_path {image_path!r} is not a file below /opt")
        built_from = jar.get("built_from")
        if not isinstance(built_from, list) or not built_from \
                or not all(isinstance(c, str) and _COORDINATE.match(c) for c in built_from):
            raise Problem(f"{path}: built_from must list group:artifact:version coordinates")
        prefixes = jar.get("own_prefixes")
        if not isinstance(prefixes, list) or not prefixes \
                or not all(isinstance(p, str) and p.endswith("/") and not p.startswith("/") for p in prefixes):
            raise Problem(f"{path}: own_prefixes must list package folders such as \"org/example/\"")
        jars.append({"name": url.rsplit("/", 1)[1], "url": url, "sha256": sha256, "image_path": image_path,
                     "built_from": built_from, "own_prefixes": prefixes})
    return {"jars": jars, "repository": repository}


def maven_url(coordinate: str, repository: str = REPOSITORY) -> str:
    group, artifact, version = _COORDINATE.match(coordinate).groups()
    return f"{repository}/{group.replace('.', '/')}/{artifact}/{version}/{artifact}-{version}.jar"


def maven_jar(coordinate: str, get: Fetch, notes: list[str], repository: str = REPOSITORY) -> bytes:
    """The jar of *coordinate* in *repository*, checked against every checksum file (.sha1, .sha256, .sha512) the
    repository publishes for it."""
    url = maven_url(coordinate, repository)
    data = get(url)
    if data is None:
        raise Problem(f"{coordinate}: not in {repository} ({url})")
    sums = {}
    for kind in CHECKSUMS:
        pattern = _DIGEST[kind]
        text = get(f"{url}.{kind}")
        if text is None:
            if kind != "sha512":
                notes.append(f"{coordinate}: {repository} publishes no .{kind}")
            continue
        value = text.decode("ascii", "replace").split()[0].strip().lower() if text.strip() else ""
        if not pattern.match(value):
            raise Problem(f"{coordinate}: {url}.{kind} holds no {kind} ({value[:80]!r})")
        actual = hashlib.new(kind, data).hexdigest()
        if actual != value:
            raise Problem(f"{coordinate}: the jar's {kind} is {actual}, {url}.{kind} says {value}")
        sums[kind] = value
    if not sums:
        notes.append(f"{coordinate}: {repository} publishes no checksum for it: the jar is the one served over HTTPS "
                     f"there, sha256 {hashlib.sha256(data).hexdigest()}")
    else:
        notes.append(f"{coordinate}: {len(data)} bytes, " + ", ".join(f"{k} {v}" for k, v in sums.items())
                     + f" (as {repository} publishes them)")
    return data


def _files(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        out = {}
        for info in archive.infolist():
            if info.is_dir():
                continue
            if info.filename in out and archive.read(info) != out[info.filename]:
                raise Problem(f"{info.filename} is in the jar twice with different bytes")
            out[info.filename] = archive.read(info)
        return out


def _normalized_javap(data: bytes, javap: str) -> str | None:
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "C.class"
        path.write_bytes(data)
        result = subprocess.run([javap, "-c", "-p", str(path)], capture_output=True, text=True, timeout=60,
                                check=False)
    if result.returncode != 0:
        return None
    lines = [line for line in result.stdout.splitlines() if not line.startswith(("Compiled from", "Classfile"))]
    return re.sub(r"#\d+(?:[.,:]\d+)?", "#", "\n".join(lines))


def compare(shipped_name: str, shipped: bytes, built_from: dict[str, bytes], own_prefixes: list[str],
            javap: str | None = None) -> dict:
    """What *shipped* is compared with the Maven jars *built_from* (coordinate -> bytes)."""
    for coordinate, data in built_from.items():
        if data == shipped:
            return {"jar": shipped_name, "passed": True, "identical_to": coordinate,
                    "compared": "the whole jar, byte for byte"}
    files = _files(shipped)
    release: dict[str, tuple[str, bytes]] = {}
    for coordinate, data in built_from.items():
        for name, content in _files(data).items():
            if name.startswith("META-INF/"):
                continue
            if name in release and release[name][1] != content:
                raise Problem(f"{name} differs between {release[name][0]} and {coordinate}")
            release.setdefault(name, (coordinate, content))
    missing = sorted(name for name in release if name not in files)
    differing = sorted(name for name, (_, content) in release.items() if name in files and files[name] != content)
    own = [name for name in files if name.startswith(tuple(own_prefixes))]
    added = sorted(name for name in own if name not in release)
    report = {
        "jar": shipped_name, "passed": not (missing or differing or added),
        "compared": (f"every file of {', '.join(built_from)} but META-INF/ against the jar's file of that name, byte "
                     f"for byte; every file of the jar under {', '.join(own_prefixes)} must be one of them"),
        "release_files": len(release), "identical": len(release) - len(missing) - len(differing),
        "own_files": len(own), "missing": missing[:50], "differing": differing[:50], "added": added[:50],
        "counts": {"missing": len(missing), "differing": len(differing), "added": len(added)},
        "not_compared": len(files) - len([n for n in files if n in release or n.startswith(tuple(own_prefixes))]),
    }
    if differing and javap:
        sample = [name for name in differing if name.endswith(".class")][:DIAGNOSE_MAX]
        same = [name for name in sample
                if (left := _normalized_javap(files[name], javap)) is not None
                and left == _normalized_javap(release[name][1], javap)]
        report["diagnosis"] = (f"javap -c -p without constant-pool numbers: {len(same)} of the first {len(sample)} "
                               "differing classes disassemble the same (a diagnosis only, the jar still fails)")
    return report


def check(folder: Path, get: Fetch = fetch, javap: str | None = None) -> dict:
    """Download and compare every jar of the server in *folder* (see the module's text)."""
    spec = load_spec(folder)
    if spec is None:
        return {"server": folder.name, "passed": True, "jars": [], "notes": ["no maven-central.json: nothing to do"]}
    notes: list[str] = []
    cache: dict[str, bytes] = {}
    reports = []
    for jar in spec["jars"]:
        shipped = get(jar["url"])
        if shipped is None:
            raise Problem(f"{jar['url']}: not found")
        actual = hashlib.sha256(shipped).hexdigest()
        if actual != jar["sha256"]:
            raise Problem(f"{jar['name']}: SHA-256 {actual}, the Dockerfile pins {jar['sha256']}")
        built_from = {}
        for coordinate in jar["built_from"]:
            if coordinate not in cache:
                cache[coordinate] = maven_jar(coordinate, get, notes, spec["repository"])
            built_from[coordinate] = cache[coordinate]
        report = compare(jar["name"], shipped, built_from, jar["own_prefixes"], javap)
        report["sha256"] = jar["sha256"]
        report["image_path"] = jar["image_path"]
        reports.append(report)
    return {"server": folder.name, "passed": all(r["passed"] for r in reports), "jars": reports, "notes": notes}


def check_image(folder: Path, image: str, engine: str = "docker") -> list[str]:
    """The problems of *image*: each pinned jar at its image_path must hash to the Dockerfile's SHA-256."""
    spec = load_spec(folder)
    if spec is None:
        return []
    paths = [jar["image_path"] for jar in spec["jars"]]
    result = subprocess.run([engine, "run", "--rm", "--network=none", "--entrypoint", "sha256sum", image, *paths],
                            capture_output=True, text=True, timeout=300, check=False)
    found = dict(reversed(line.split(None, 1)) for line in result.stdout.splitlines() if line.strip())
    problems = []
    for jar in spec["jars"]:
        actual = found.get(jar["image_path"])
        if actual != jar["sha256"]:
            problems.append(f"{jar['image_path']} in the image: SHA-256 {actual or 'missing'}, compared with Maven "
                            f"Central was {jar['sha256']}")
    if result.returncode != 0 and not problems:
        problems.append(f"sha256sum in the image failed: {result.stderr.strip()[-300:]}")
    return problems


def _summary(report: dict) -> list[str]:
    lines = [f"maven-central {report['server']}: {'passed' if report['passed'] else 'FAILED'}"]
    for jar in report["jars"]:
        lines.append(f"  {jar['jar']} (sha256 {jar['sha256']}): {'passed' if jar['passed'] else 'FAILED'} - "
                     f"{jar['compared']}")
        if "identical_to" in jar:
            lines.append(f"    byte for byte {jar['identical_to']}")
        else:
            lines.append(f"    {jar['identical']} of {jar['release_files']} release files identical, "
                         f"{jar['own_files']} files under the release's packages, {jar['not_compared']} others "
                         f"(bundled libraries) not compared; missing {jar['counts']['missing']}, differing "
                         f"{jar['counts']['differing']}, added {jar['counts']['added']}")
            for kind in ("missing", "differing", "added"):
                for name in jar[kind][:10]:
                    lines.append(f"    {kind}: {name}")
            if "diagnosis" in jar:
                lines.append(f"    {jar['diagnosis']}")
    lines.extend(f"  {note}" for note in report["notes"])
    return lines


def _escape(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--server", required=True, help="the folder name below servers/")
    parser.add_argument("--image", help="check that this built image ships exactly the compared jars")
    parser.add_argument("--engine", default="docker")
    parser.add_argument("--report", help="write the comparison as JSON here")
    args = parser.parse_args(argv)
    folder = ROOT / "servers" / args.server
    if not (folder / "server.json").is_file():
        print(f"no server {args.server}", file=sys.stderr)
        return 2
    try:
        if args.image:
            problems = check_image(folder, args.image, args.engine)
            for problem in problems:
                print(problem)
            if problems:
                print(f"::error title=maven-central {args.server}::{_escape(chr(10).join(problems))}")
                return 1
            print(f"maven-central {args.server}: the image ships the compared jars" if load_spec(folder)
                  else f"{args.server}: no maven-central.json, nothing to check")
            return 0
        report = check(folder, javap=shutil.which("javap"))
    except Problem as problem:
        print(f"::error title=maven-central {args.server}::{_escape(str(problem))}")
        return 1
    lines = _summary(report)
    print("\n".join(lines))
    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if not report["passed"]:
        print(f"::error title=maven-central {args.server}::{_escape(chr(10).join(lines))}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
