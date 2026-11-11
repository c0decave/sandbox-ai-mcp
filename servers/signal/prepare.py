#!/usr/bin/env python3
"""Build step of the signal image (its first stage only; not in the final image). Standard library only.

    prepare.py fetch URL SHA256 FILE
        Download URL into FILE and check its SHA-256 (the release files of signal-cli and Temurin).
    prepare.py signal-cli UNPACKED OUT
        From signal-cli's unpacked JVM release: OUT/lib (the jars), OUT/classpath (the class path
        of signal-cli's own start script, one jar per line, in its order) and OUT/native: the native
        libraries that libsignal-client and sqlite-jdbc would otherwise unpack into /tmp at every
        start (which the container mounts noexec), taken out of their jars and checked by SHA-256.
        The jars keep everything else; without the libraries in them, libsignal falls back to
        System.loadLibrary (java.library.path) and sqlite-jdbc loads org.sqlite.lib.path.
"""
from __future__ import annotations

import hashlib
import re
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

LIBSIGNAL_JAR = "libsignal-client-0.103.0.jar"
SQLITE_JAR = "sqlite-jdbc-3.53.4.0.jar"
#: (jar, entry, file in OUT/native, its SHA-256)
NATIVES = (
    (LIBSIGNAL_JAR, "libsignal_jni_amd64.so", "libsignal_jni.so",
     "e0f4e783c25d0eea3252d9da36dd1dc9752c075dd5c10d1d3f30d9798346050b"),
    (SQLITE_JAR, "org/sqlite/native/Linux/x86_64/libsqlitejdbc.so", "libsqlitejdbc.so",
     "aaad97362c429a34b47488c4a5a966ab090450edde70c2186d1a02c0e2d17cd0"),
)
#: What leaves each jar: every native library it carries (other systems' too).
STRIP = {LIBSIGNAL_JAR: re.compile(r"^[^/]+\.(so|dylib|dll)$"), SQLITE_JAR: re.compile(r"^org/sqlite/native/")}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(url: str, expected: str, out: Path) -> None:
    if not url.startswith("https://github.com/"):
        raise SystemExit(f"{url}: only GitHub release files are fetched")
    with urllib.request.urlopen(url, timeout=300) as answer, out.open("wb") as handle:
        shutil.copyfileobj(answer, handle, 1 << 20)
    if sha256(out) != expected:
        out.unlink()
        raise SystemExit(f"{url}: its SHA-256 differs from the pinned {expected}")


def without(jar: Path, pattern: re.Pattern) -> None:
    """Rewrite *jar* without the entries matching *pattern* (all others byte for byte, same order)."""
    kept = jar.with_suffix(".tmp")
    with zipfile.ZipFile(jar) as source, zipfile.ZipFile(kept, "w") as target:
        for info in source.infolist():
            if not pattern.search(info.filename):
                target.writestr(info, source.read(info), compress_type=info.compress_type)
    kept.replace(jar)


def signal_cli(unpacked: Path, out: Path) -> None:
    start_script = (unpacked / "bin" / "signal-cli").read_text(encoding="utf-8")
    line = re.search(r"^CLASSPATH=(\S+)$", start_script, re.M)
    if not line:
        raise SystemExit("bin/signal-cli has no CLASSPATH line")
    jars = [entry.removeprefix("$APP_HOME/lib/") for entry in line.group(1).split(":")]
    found = sorted(path.name for path in (unpacked / "lib").glob("*.jar"))
    if sorted(jars) != found or any("/" in jar or not jar.endswith(".jar") for jar in jars):
        raise SystemExit("the start script's class path is not exactly the jars in lib/")
    shutil.copytree(unpacked / "lib", out / "lib")
    (out / "classpath").write_text("".join(f"{out}/lib/{jar}\n" for jar in jars), encoding="utf-8")
    (out / "native").mkdir()
    for jar, entry, name, expected in NATIVES:
        with zipfile.ZipFile(out / "lib" / jar) as archive:
            (out / "native" / name).write_bytes(archive.read(entry))
        if sha256(out / "native" / name) != expected:
            raise SystemExit(f"{jar}!{entry}: not the reviewed library (SHA-256 {expected})")
    for jar, pattern in STRIP.items():
        without(out / "lib" / jar, pattern)
        with zipfile.ZipFile(out / "lib" / jar) as archive:
            if any(pattern.search(name) for name in archive.namelist()):
                raise SystemExit(f"{jar}: a native library is left")


def main(argv: list[str]) -> int:
    if len(argv) == 4 and argv[0] == "fetch":
        fetch(argv[1], argv[2], Path(argv[3]))
    elif len(argv) == 3 and argv[0] == "signal-cli":
        signal_cli(Path(argv[1]), Path(argv[2]))
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
