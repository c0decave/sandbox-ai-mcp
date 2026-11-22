"""Check that every jar a server ships is byte for byte the published one in its Maven repository (CI, before the build).

A server that ships jars names them in ``servers/NAME/maven-central.json``: per jar its Maven coordinate, the
Dockerfile ARGs that pin it (its URL and SHA-256, the bytes the image's ``ADD --checksum`` takes), where the image
keeps it, and the repository it is published in (``repository``, per jar or for the whole spec: Maven Central, the
default, or Google's Maven, where Google publishes com.android.tools.* - smali 3.0.10 is there, not on Maven
Central)::

    {"schema": "sandbox-ai-mcp-maven-central", "version": 2,
     "jars": [{"coordinate": "com.android.tools.smali:smali:3.0.10", "url_arg": "SMALI_URL",
               "sha256_arg": "SMALI_SHA256", "image_path": "/opt/smali/smali-3.0.10.jar",
               "repository": "https://dl.google.com/dl/android/maven2"}, ...]}

The URL is either the jar's own URL in that repository (the image takes it from there: smali) or a GitHub release
asset that must be the very same bytes (cfr). What is checked, per jar:

1. The jar is downloaded from the repository with every checksum file (``.sha1``, ``.sha256``, ``.sha512``) the
   repository publishes beside it, and must hash to each of them; a missing one is said, and a jar for which the
   repository publishes none fails (nothing to check the bytes against).
2. Its SHA-256 must be the one the Dockerfile pins: the image's bytes are the published bytes.
3. A jar the image takes from elsewhere (a GitHub release asset) is downloaded from there too and must hash to the
   same pin.

Any difference fails (exit 1, an ``::error`` annotation); the report (``--report``) lists per jar the coordinate, the
URLs, the SHA-256 and the published checksums that matched. ``--image`` checks a built image: the folders that hold
the spec's jars contain exactly those jars, each with its pinned SHA-256.

    scripts/maven_central.py --server smali [--report FILE]     # download and check (no spec: nothing to do)
    scripts/maven_central.py --server smali --image IMG          # the built image ships exactly the checked jars

Standard library only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = "sandbox-ai-mcp-maven-central"
VERSION = 2
REPOSITORY = "https://repo1.maven.org/maven2"
#: The Maven repositories a spec may name ("repository", default Maven Central): Maven Central, and Google's Maven
#: (maven.google.com), where Google publishes com.android.tools.* - smali 3.0.10 is there, not on Maven Central.
REPOSITORIES = (REPOSITORY, "https://dl.google.com/dl/android/maven2")
#: The checksum files a repository may publish next to a jar; every one that is there must match.
CHECKSUMS = ("sha1", "sha256", "sha512")
MAX_SIZE = 64 << 20
#: Where a jar may come from besides its repository (a Dockerfile ARG) - nothing else is fetched.
SHIPPED_HOSTS = ("https://github.com/",)
_COORDINATE = re.compile(r"^([A-Za-z0-9_.-]+):([A-Za-z0-9_.-]+):([A-Za-z0-9_.-]+)$")
_ARG = re.compile(r"^ARG\s+([A-Z0-9_]+)=(\S+)\s*$", re.M)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DIGEST = {"sha1": re.compile(r"^[0-9a-f]{40}$"), "sha256": re.compile(r"^[0-9a-f]{64}$"),
           "sha512": re.compile(r"^[0-9a-f]{128}$")}

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


def maven_url(coordinate: str, repository: str = REPOSITORY) -> str:
    group, artifact, version = _COORDINATE.match(coordinate).groups()
    return f"{repository}/{group.replace('.', '/')}/{artifact}/{version}/{artifact}-{version}.jar"


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
    default = spec.get("repository", REPOSITORY)
    args = dict(_ARG.findall((folder / "Dockerfile").read_text(encoding="utf-8")))
    jars, seen = [], set()
    for jar in spec["jars"]:
        if not isinstance(jar, dict):
            raise Problem(f"{path}: a jar must be an object")
        coordinate = jar.get("coordinate")
        if not isinstance(coordinate, str) or not _COORDINATE.match(coordinate):
            raise Problem(f"{path}: every jar needs a coordinate group:artifact:version ({jar.get('url_arg')})")
        repository = jar.get("repository", default)
        if repository not in REPOSITORIES:
            raise Problem(f"{path}: repository {repository!r} is none of {', '.join(REPOSITORIES)}")
        url, sha256 = args.get(jar.get("url_arg")), args.get(jar.get("sha256_arg"))
        if not url or not sha256:
            raise Problem(f"{path}: the Dockerfile has no ARG {jar.get('url_arg')} / {jar.get('sha256_arg')}")
        if not _SHA256.match(sha256):
            raise Problem(f"{path}: {jar['sha256_arg']}={sha256} is not a SHA-256")
        published = maven_url(coordinate, repository)
        if url.startswith(tuple(f"{r}/" for r in REPOSITORIES)):
            if url != published:
                raise Problem(f"{path}: {jar['url_arg']}={url} is not the jar of {coordinate} ({published})")
        elif not url.startswith(SHIPPED_HOSTS):
            raise Problem(f"{path}: {jar['url_arg']}={url} is not an https URL of {repository} or of "
                          f"{', '.join(SHIPPED_HOSTS)}")
        image_path = jar.get("image_path")
        if not isinstance(image_path, str) or not image_path.startswith("/opt/") or ".." in image_path \
                or not image_path.endswith(".jar"):
            raise Problem(f"{path}: image_path {image_path!r} is not a jar below /opt")
        for key in (coordinate, image_path):
            if key in seen:
                raise Problem(f"{path}: {key} is named twice")
            seen.add(key)
        jars.append({"coordinate": coordinate, "name": url.rsplit("/", 1)[1], "url": url, "maven_url": published,
                     "sha256": sha256, "image_path": image_path, "repository": repository})
    return {"jars": jars}


def maven_jar(coordinate: str, get: Fetch, notes: list[str], repository: str = REPOSITORY) -> tuple[bytes, dict]:
    """The jar of *coordinate* in *repository* and {kind: value} of every checksum file (.sha1, .sha256, .sha512)
    the repository publishes for it, each checked against the jar; at least one must be there."""
    url = maven_url(coordinate, repository)
    data = get(url)
    if data is None:
        raise Problem(f"{coordinate}: not in {repository} ({url})")
    sums = {}
    for kind in CHECKSUMS:
        text = get(f"{url}.{kind}")
        if text is None:
            notes.append(f"{coordinate}: {repository} publishes no .{kind}")
            continue
        value = text.decode("ascii", "replace").split()[0].strip().lower() if text.strip() else ""
        if not _DIGEST[kind].match(value):
            raise Problem(f"{coordinate}: {url}.{kind} holds no {kind} ({value[:80]!r})")
        actual = hashlib.new(kind, data).hexdigest()
        if actual != value:
            raise Problem(f"{coordinate}: the jar's {kind} is {actual}, {url}.{kind} says {value}")
        sums[kind] = value
    if not sums:
        raise Problem(f"{coordinate}: {repository} publishes no checksum for {url} (none of "
                      f"{', '.join('.' + k for k in CHECKSUMS)}): nothing to check its bytes against")
    return data, sums


def check(folder: Path, get: Fetch = fetch) -> dict:
    """Download and check every jar of the server in *folder* (see the module's text)."""
    spec = load_spec(folder)
    if spec is None:
        return {"server": folder.name, "passed": True, "jars": [], "notes": ["no maven-central.json: nothing to do"]}
    notes: list[str] = []
    reports = []
    for jar in spec["jars"]:
        data, sums = maven_jar(jar["coordinate"], get, notes, jar["repository"])
        published = hashlib.sha256(data).hexdigest()
        report = {"jar": jar["name"], "coordinate": jar["coordinate"], "repository": jar["repository"],
                  "maven_url": jar["maven_url"], "url": jar["url"], "sha256": jar["sha256"],
                  "image_path": jar["image_path"], "size": len(data), "checksums": sums,
                  "repository_sha256": published, "passed": published == jar["sha256"],
                  "compared": "the whole jar, byte for byte: its SHA-256 against the Dockerfile's pin, the jar "
                              f"against {', '.join('.' + k for k in sums)} as {jar['repository']} publishes them"}
        if jar["url"] == jar["maven_url"]:
            report["shipped_from"] = "the repository"
        else:
            shipped = get(jar["url"])
            if shipped is None:
                raise Problem(f"{jar['url']}: not found")
            actual = hashlib.sha256(shipped).hexdigest()
            if actual != jar["sha256"]:
                raise Problem(f"{jar['name']}: SHA-256 {actual}, the Dockerfile pins {jar['sha256']}")
            report["shipped_from"] = jar["url"]
        reports.append(report)
    return {"server": folder.name, "passed": all(r["passed"] for r in reports), "jars": reports, "notes": notes}


def check_image(folder: Path, image: str, engine: str = "docker") -> list[str]:
    """The problems of *image*: the folders that hold the spec's jars contain exactly those jars, each hashing to
    the Dockerfile's SHA-256."""
    spec = load_spec(folder)
    if spec is None:
        return []
    expected = {jar["image_path"]: jar["sha256"] for jar in spec["jars"]}
    folders = sorted({posixpath.dirname(path) for path in expected})
    result = subprocess.run([engine, "run", "--rm", "--network=none", "--entrypoint", "find", image, *folders,
                             "!", "-type", "d", "-exec", "sha256sum", "{}", "+"],
                            capture_output=True, text=True, timeout=300, check=False)
    found = dict(reversed(line.split(None, 1)) for line in result.stdout.splitlines() if line.strip())
    problems = []
    for path, sha256 in expected.items():
        actual = found.get(path)
        if actual != sha256:
            problems.append(f"{path} in the image: SHA-256 {actual or 'missing'}, the published jar checked was "
                            f"{sha256}")
    for path in sorted(set(found) - set(expected)):
        problems.append(f"{path} in the image is no jar of maven-central.json (SHA-256 {found[path]})")
    if result.returncode != 0 and not problems:
        problems.append(f"find/sha256sum in the image failed: {result.stderr.strip()[-300:]}")
    return problems


def _summary(report: dict) -> list[str]:
    lines = [f"maven-central {report['server']}: {'passed' if report['passed'] else 'FAILED'}"]
    for jar in report["jars"]:
        lines.append(f"  {jar['coordinate']} {jar['jar']} (sha256 {jar['sha256']}): "
                     f"{'passed' if jar['passed'] else 'FAILED'} - from {jar['shipped_from']}, "
                     f"{jar['size']} bytes, checked against the published {', '.join(jar['checksums'])}")
        if not jar["passed"]:
            lines.append(f"    {jar['maven_url']} has SHA-256 {jar['repository_sha256']}, the Dockerfile pins "
                         f"{jar['sha256']}")
    lines.extend(f"  {note}" for note in report["notes"])
    return lines


def _escape(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--server", required=True, help="the folder name below servers/")
    parser.add_argument("--image", help="check that this built image ships exactly the checked jars")
    parser.add_argument("--engine", default="docker")
    parser.add_argument("--report", help="write the check as JSON here")
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
            print(f"maven-central {args.server}: the image ships exactly the checked jars" if load_spec(folder)
                  else f"{args.server}: no maven-central.json, nothing to check")
            return 0
        report = check(folder)
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
