#!/usr/bin/env python3
"""Build a toolchain of toolchains/NAME: the upstream release, pinned and checked, as one read-only tree.

    scripts/toolchain.py build NAME --arch x86_64 --out DIR [--downloads DIR] [--date YYYY-MM-DD]
    scripts/toolchain.py check [NAME ...] [--date YYYY-MM-DD]

`build` runs the steps of toolchains/NAME/toolchain.json ("build") and writes DIR/toolchain-NAME-ARCH.tar.xz (the
files of the prefix, which sandbox-ai mounts read-only at /opt/toolchains/NAME) and DIR/toolchain-NAME-ARCH.json:
the entry of toolchains.json (scripts/make_toolchains.py) with the archive's URL, SHA-256 and sizes, the upstream
"sources" (URL and SHA-256 of every download, the signature that was checked) and "measured": what the tree's ELF
files really need. The steps are data, never a shell:

  {"fetch": FILE, "url": URL, "sha256": HEX | "sha512": HEX, "released": "YYYY-MM-DD"}
      a download, refused unless it has that hash. "url" and the hashes may be {"x86_64": ..., "aarch64": ...}.
      Instead of a hash: "listed": {"in": FILE, "as": NAME} - the SHA-256 that the (signed, verified) checksum file
      FILE lists for NAME -, "fingerprint": the OpenPGP fingerprint of the one key FILE holds, or "signed": true -
      a file a later gpg step verifies, or the signature it verifies with.
  {"gpg": FILE, "signature": FILE, "keys": FILE, "fingerprints": [HEX, ...]}
      FILE must carry a good signature of a key of KEYS (a fetched key file or keyring); with "fingerprints" only
      of one of those keys. Nothing of a file is used before the step that verifies it.
  {"unpack": FILE, "to": DIR, "strip": N, "only": [PREFIX, ...], "merge": [DIR, ...]}
      a tar archive (any compression) or zip into the prefix, without trusting it: no path that leaves it, no
      device, no set-user-ID bit, no link target outside. "strip" drops leading path parts, "only" takes the
      members below these paths (after strip), "merge" lifts the content of these folders into "to" (Rust's
      components).
  {"write": PATH, "text": TEXT, "mode": "755"}    a small file of ours (a wrapper script)
  {"link": PATH, "to": TARGET}                    a relative symbolic link inside the prefix
  {"move": PATH, "to": PATH}, {"remove": [GLOB, ...]}, {"chmod": PATH, "mode": "755"}

In every text of a step "{prefix}" is /opt/toolchains/NAME, "{arch}" the architecture and "{KEY}" a value of
"vars" (per architecture: {"goarch": {"x86_64": "amd64", "aarch64": "arm64"}}).

Then the checks. Every command of the manifest is a file of the tree. Every ELF program and library of this
architecture is read: its NEEDED libraries must be in the tree, glibc's own, or named in "needs.libraries"; the
newest GLIBC_x.y version it asks for must not be above "needs.glibc" (null: none at all). Files matching "optional"
(GUI parts, test data) are measured but only noted. A release younger than 14 days on DATE is refused.

`check` validates every toolchain.json without downloading: the keys, the pins of each architecture, the release
dates. Standard library only (gpg for a "gpg" step, xz for the archive when it is there).
"""

from __future__ import annotations

import argparse
import datetime
import fnmatch
import hashlib
import json
import lzma
import os
import re
import shutil
import stat
import struct
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
RELEASES = "https://github.com/c0decave/sandbox-ai-mcp/releases/download"
MOUNT = "/opt/toolchains"
ARCHES = ("x86_64", "aarch64")
MIN_AGE_DAYS = 14
DOWNLOAD_LIMIT = 2 << 30
NAME = re.compile(r"[a-z][a-z0-9-]{0,31}")
MANIFEST_KEYS = ("name", "version", "title", "description", "license", "homepage", "commands", "env", "caches",
                 "hosts", "allow", "needs", "requires")
KEYS = frozenset({*MANIFEST_KEYS, "arches", "vars", "build", "optional", "smoke", "notes"})
VERBS = ("fetch", "gpg", "unpack", "write", "link", "move", "remove", "chmod")
GLIBC_LIBRARIES = frozenset({"libc.so.6", "libm.so.6", "libdl.so.2", "libpthread.so.0", "librt.so.1", "libutil.so.1",
                             "libresolv.so.2", "libanl.so.1", "libmvec.so.1", "ld-linux-x86-64.so.2",
                             "ld-linux-aarch64.so.1", "linux-vdso.so.1"})
ELF_MACHINES = {"x86_64": 62, "aarch64": 183}


class Refused(ValueError):
    pass


# --- the recipe ------------------------------------------------------------------------------------------------


def load(name: str, root: Path = ROOT) -> dict:
    if not NAME.fullmatch(name) or name == "bin":
        raise Refused(f"{name!r}: a toolchain's name is a lower-case letter, then lower-case letters, digits or '-'")
    path = root / "toolchains" / name / "toolchain.json"
    try:
        recipe = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Refused(f"{path}: {exc}") from None
    if not isinstance(recipe, dict) or recipe.get("name") != name:
        raise Refused(f"{path}: its name must be {name}")
    unknown = sorted(set(recipe) - KEYS)
    if unknown:
        raise Refused(f"{path}: unknown key {unknown[0]!r}")
    return recipe


def for_arch(value, arch: str, what: str):
    """VALUE, or its entry for ARCH when it is a map by architecture."""
    if isinstance(value, dict):
        if arch not in value:
            raise Refused(f"{what}: nothing for {arch}")
        return value[arch]
    return value


def substituted(text: str, recipe: dict, arch: str) -> str:
    values = {"prefix": f"{MOUNT}/{recipe['name']}", "arch": arch, "version": str(recipe.get("version", "")),
              **{key: str(for_arch(value, arch, f"vars.{key}")) for key, value in (recipe.get("vars") or {}).items()}}

    def replace(match):
        if match[1] not in values:
            raise Refused(f"{{{match[1]}}} in {text[:80]!r}: no such variable (vars)")
        return values[match[1]]
    return re.sub(r"\{([a-z][a-z0-9_]*)\}", replace, text)


def problems_of(recipe: dict, today: datetime.date) -> list[str]:
    """What is wrong with a toolchain.json, without a download: keys, pins of each architecture, release dates."""
    found, name = [], recipe.get("name")
    for key in ("version", "title", "description", "license", "homepage"):
        if not isinstance(recipe.get(key), str) or not recipe[key]:
            found.append(f"{key} is missing")
    arches = recipe.get("arches")
    if not isinstance(arches, list) or not arches or set(arches) - set(ARCHES):
        found.append(f"arches must be a list of {', '.join(ARCHES)}")
        arches = []
    if not isinstance(recipe.get("commands"), dict) or not recipe["commands"]:
        found.append("commands must map command names to files below the prefix")
    steps = recipe.get("build")
    if not isinstance(steps, list) or not steps:
        return found + ["build must be a list of steps"]
    fetched, verified, used = {}, set(), set()
    for index, step in enumerate(steps, 1):
        verbs = [verb for verb in VERBS if isinstance(step, dict) and verb in step]
        if len(verbs) != 1:
            found.append(f"step {index}: exactly one of {', '.join(VERBS)}")
            continue
        verb = verbs[0]
        if verb == "fetch":
            pins = [key for key in ("sha256", "sha512", "listed", "fingerprint", "signed") if key in step]
            if len(pins) != 1:
                found.append(f"step {index}: fetch {step['fetch']} needs exactly one of sha256, sha512, listed, "
                             "fingerprint, signed")
            fetched[step["fetch"]] = step
            if pins == ["listed"]:
                listing = (step["listed"] or {}).get("in")
                if listing not in verified:
                    found.append(f"step {index}: {step['fetch']} takes its hash from {listing}, which no gpg step "
                                 "verified before")
            if pins and pins[0] in ("sha256", "sha512", "listed"):
                verified.add(step["fetch"])
            for arch in arches:
                try:
                    url = substituted(str(for_arch(step.get("url"), arch, f"step {index} url")), recipe, arch)
                    if not url.startswith("https://"):
                        found.append(f"step {index}: {url} is not https")
                    for key in ("sha256", "sha512"):
                        if key in step and not re.fullmatch(r"[0-9a-f]{%d}" % (64 if key == "sha256" else 128),
                                                            str(for_arch(step[key], arch, f"step {index} {key}"))):
                            found.append(f"step {index}: {key} for {arch} is not a hash")
                except Refused as exc:
                    found.append(str(exc))
            released = step.get("released")
            if released is not None:
                try:
                    age = (today - datetime.date.fromisoformat(released)).days
                    if age < MIN_AGE_DAYS:
                        found.append(f"step {index}: {step['fetch']} was released {released}, {age} days before "
                                     f"{today}: releases are pinned once they are {MIN_AGE_DAYS} days old")
                except (TypeError, ValueError):
                    found.append(f"step {index}: released must be YYYY-MM-DD")
        elif verb == "gpg":
            for key in ("gpg", "signature", "keys"):
                if step.get(key) not in fetched:
                    found.append(f"step {index}: gpg {key} {step.get(key)!r} was not fetched before")
            for key in ("gpg", "signature"):
                if step.get(key) in fetched and "signed" not in fetched[step[key]] and key == "signature":
                    found.append(f"step {index}: the signature {step[key]} is not a fetch marked signed")
            keys = fetched.get(step.get("keys"), {})
            if not ({"sha256", "sha512", "fingerprint"} & set(keys)) and not step.get("fingerprints"):
                found.append(f"step {index}: the keys {step.get('keys')} are pinned neither by a hash nor by "
                             "fingerprints")
            verified.add(step.get("gpg"))
        elif verb == "unpack":
            used.add(step["unpack"])
            if step["unpack"] not in verified:
                found.append(f"step {index}: {step['unpack']} is unpacked before a hash or a signature vouched for it")
    if not any(isinstance(step, dict) and step.get("released") for step in steps):
        found.append("no fetch step says when its release was made (released)")
    named = {value for step in steps if isinstance(step, dict)
             for value in (step.get("gpg"), step.get("signature"), step.get("keys"),
                           (step.get("listed") or {}).get("in") if isinstance(step.get("listed"), dict) else None)}
    unused = sorted(set(fetched) - used - named)
    if unused:
        found.append(f"fetched and never used: {', '.join(unused)}")
    unsigned = sorted(name_ for name_, step in fetched.items() if "signed" in step and name_ not in named)
    if unsigned:
        found.append(f"marked signed, but no gpg step verifies: {', '.join(unsigned)}")
    return [f"{name}: {problem}" for problem in found]


# --- downloads and signatures ----------------------------------------------------------------------------------


def download(url: str, target: Path, opener=None) -> None:
    opener = opener or (lambda u: urllib.request.urlopen(u, timeout=300))  # noqa: S310 - https only (checked)
    if not url.startswith("https://"):
        raise Refused(f"{url}: not https")
    size = 0
    with opener(url) as source, open(target, "wb") as out:
        while True:
            chunk = source.read(1 << 20)
            if not chunk:
                break
            size += len(chunk)
            if size > DOWNLOAD_LIMIT:
                raise Refused(f"{url}: larger than {DOWNLOAD_LIMIT >> 30} GiB")
            out.write(chunk)


def digest(path: Path, kind: str = "sha256") -> str:
    found = hashlib.new(kind)
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            found.update(chunk)
    return found.hexdigest()


def listed_hash(listing: Path, name: str) -> str:
    """The SHA-256 a checksum file (lines "HEX  NAME") lists for NAME."""
    for line in listing.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == name and re.fullmatch(r"[0-9a-f]{64}", parts[0]):
            return parts[0]
    raise Refused(f"{listing.name} lists no SHA-256 for {name}")


def gpg_fingerprints(key_file: Path, run=subprocess.run) -> list[str]:
    result = run(["gpg", "--batch", "--no-options", "--show-keys", "--with-colons", str(key_file)],
                 capture_output=True, text=True)
    primary, found = False, []
    for line in result.stdout.splitlines():
        fields = line.split(":")
        if fields[0] == "pub":
            primary = True
        elif fields[0] == "fpr" and primary:
            found.append(fields[9])
            primary = False
    return found


def gpg_verify(data: Path, signature: Path, keys: Path, fingerprints=(), run=subprocess.run) -> str:
    """The fingerprint of the key of KEYS whose good signature SIGNATURE is over DATA; Refused otherwise."""
    with tempfile.TemporaryDirectory() as home:
        os.chmod(home, 0o700)
        base = ["gpg", "--batch", "--no-options", "--homedir", home]
        if keys.name.endswith(".kbx"):
            base += ["--no-default-keyring", "--keyring", str(keys)]
        elif run([*base, "--import", str(keys)], capture_output=True).returncode != 0:
            raise Refused(f"gpg could not import {keys.name}")
        result = run([*base, "--status-fd", "1", "--verify", str(signature), str(data)], capture_output=True,
                     text=True)
    valid = [line.split() for line in result.stdout.splitlines() if line.startswith("[GNUPG:] VALIDSIG ")]
    if result.returncode != 0 or not valid:
        raise Refused(f"{data.name}: no good signature in {signature.name} by a key of {keys.name}")
    signer = valid[0][-1]  # the primary key's fingerprint
    wanted = {value.replace(" ", "").upper() for value in fingerprints}
    if wanted and signer.upper() not in wanted:
        raise Refused(f"{data.name}: signed by {signer}, not by one of {', '.join(sorted(wanted))}")
    return signer


# --- unpacking without trusting the archive ---------------------------------------------------------------------


def safe_relative(name: str, strip: int = 0):
    """NAME of an archive member as path parts below the target (after STRIP leading parts), or None: nothing left."""
    parts = [part for part in PurePosixPath(str(name).replace("\\", "/").lstrip("/")).parts if part not in ("", ".")]
    if any(part == ".." or "\0" in part for part in parts):
        raise Refused(f"archive member {name!r} leaves the tree")
    parts = parts[strip:]
    return parts or None


def target_of(top: Path, parts) -> Path:
    """TOP/PARTS with every folder on the way a real folder of TOP (never through a link the archive made)."""
    current = top
    for part in parts[:-1]:
        current = current / part
        if current.is_symlink() or (current.exists() and not current.is_dir()):
            raise Refused(f"archive member {'/'.join(parts)} lies below {current.relative_to(top)}, which is no folder")
        current.mkdir(exist_ok=True)
    return current / parts[-1]


def link_inside(top: Path, path: Path, target: str) -> None:
    """A symbolic link PATH -> TARGET, refused when TARGET is absolute or leads out of TOP."""
    if target.startswith("/"):
        raise Refused(f"{path.relative_to(top)}: an absolute link ({target}) is not taken")
    resolved = os.path.normpath(os.path.join(os.path.dirname(path.relative_to(top).as_posix()), target))
    if resolved == ".." or resolved.startswith("../"):
        raise Refused(f"{path.relative_to(top)}: its link target {target} leaves the tree")
    if path.is_symlink() or path.exists():
        if path.is_dir() and not path.is_symlink():
            raise Refused(f"{path.relative_to(top)}: a link where a folder is")
        path.unlink()
    os.symlink(target, path)


def wanted(parts, only) -> bool:
    joined = "/".join(parts)
    return not only or any(joined == prefix.rstrip("/") or joined.startswith(prefix.rstrip("/") + "/")
                           for prefix in only)


def write_member(path: Path, source, mode: int) -> None:
    if path.is_symlink() or path.is_dir():
        if path.is_dir() and not path.is_symlink():
            raise Refused(f"{path.name}: a file where a folder is")
        path.unlink()
    with open(path, "wb") as out:
        shutil.copyfileobj(source, out)
    os.chmod(path, 0o755 if mode & 0o111 else 0o644)  # no set-user-ID, set-group-ID or world-writable bit


def unpack(archive: Path, top: Path, strip: int = 0, only=()) -> None:
    """ARCHIVE (tar, any compression; or zip) into TOP, without trusting it."""
    top.mkdir(parents=True, exist_ok=True)
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as source:
            for info in source.infolist():
                parts = safe_relative(info.filename, strip)
                if parts is None or not wanted(parts, only):
                    continue
                mode = (info.external_attr >> 16) & 0o7777
                kind = (info.external_attr >> 16) & 0o170000
                path = target_of(top, parts)
                if info.is_dir():
                    path.mkdir(exist_ok=True)
                elif kind == stat.S_IFLNK:
                    link_inside(top, path, source.read(info).decode())
                else:
                    with source.open(info) as stream:
                        write_member(path, stream, mode)
        return
    with tarfile.open(archive, mode="r:*") as source:
        for member in source:
            parts = safe_relative(member.name, strip)
            if parts is None or not wanted(parts, only):
                continue
            path = target_of(top, parts)
            if member.isdir():
                if path.is_symlink() or (path.exists() and not path.is_dir()):
                    raise Refused(f"archive member {member.name}: a folder where something else is")
                path.mkdir(exist_ok=True)
            elif member.isfile():
                write_member(path, source.extractfile(member), member.mode)
            elif member.issym():
                link_inside(top, path, member.linkname)
            elif member.islnk():
                other = safe_relative(member.linkname, strip)
                origin = target_of(top, other) if other else None
                if origin is None or origin.is_symlink() or not origin.is_file():
                    raise Refused(f"archive member {member.name}: a hard link to {member.linkname}, no file of it")
                if path.exists() or path.is_symlink():
                    path.unlink()
                shutil.copyfile(origin, path)
                os.chmod(path, stat.S_IMODE(origin.stat().st_mode))
            # devices, FIFOs and anything else are left out


def inside(tree: Path, value: str) -> Path:
    parts = safe_relative(value)
    if parts is None or str(value).startswith("/"):
        raise Refused(f"{value!r} is no path below the prefix")
    return tree.joinpath(*parts)


def merge(source: Path, target: Path) -> None:
    """The content of the folder SOURCE lifted into TARGET (folders joined, files moved), SOURCE removed."""
    for entry in sorted(source.iterdir()):
        to = target / entry.name
        if entry.is_dir() and not entry.is_symlink():
            to.mkdir(exist_ok=True)
            merge(entry, to)
        else:
            if to.exists() or to.is_symlink():
                to.unlink()
            entry.rename(to)
    source.rmdir()


# --- the steps -------------------------------------------------------------------------------------------------


def run_steps(recipe: dict, arch: str, tree: Path, downloads: Path, opener=None, gpg=subprocess.run) -> list[dict]:
    """The build steps of RECIPE for ARCH into TREE; the sources ({url, sha256[, signature]}) of its downloads."""
    sources, verified, files = {}, set(), {}
    tree.mkdir(parents=True, exist_ok=True)
    downloads.mkdir(parents=True, exist_ok=True)

    def text(value):
        return substituted(str(for_arch(value, arch, "a step")), recipe, arch)

    def fetched(name):
        if name not in files:
            raise Refused(f"{name} was not fetched")
        return files[name]

    for index, step in enumerate(recipe["build"], 1):
        if "fetch" in step:
            name, url, signed_by = step["fetch"], text(step["url"]), None
            if "/" in name or name.startswith("."):
                raise Refused(f"step {index}: {name!r} is no file name")
            path = downloads / name
            pinned = next((kind for kind in ("sha256", "sha512") if kind in step), None)
            if path.is_file() and pinned and digest(path, pinned) != text(step[pinned]):
                path.unlink()  # a kept download of another release (--downloads): fetched again
            if not path.is_file():
                print(f"fetch {url}", flush=True)
                download(url, path, opener)
            files[name] = path
            found = digest(path)
            if "sha256" in step or "sha512" in step:
                kind = "sha256" if "sha256" in step else "sha512"
                if digest(path, kind) != text(step[kind]):
                    raise Refused(f"{url}: {kind} {digest(path, kind)}, pinned is {text(step[kind])}: not used")
                verified.add(name)
            elif "listed" in step:
                listing = step["listed"]["in"]
                if listing not in verified:
                    raise Refused(f"step {index}: {listing} was not verified: its hashes are not taken")
                if found != listed_hash(fetched(listing), text(step["listed"]["as"])):
                    raise Refused(f"{url}: SHA-256 {found} is not the one {listing} lists: not used")
                verified.add(name)
                signed_by = sources[listing].get("signature")  # the listing's signature vouches for this file
            elif "fingerprint" in step:
                have = gpg_fingerprints(path, gpg)
                want = text(step["fingerprint"]).replace(" ", "").upper()
                if [value.upper() for value in have] != [want]:
                    raise Refused(f"{url}: holds the keys {', '.join(have) or 'none'}, pinned is {want}: not used")
            sources[name] = {"url": url, "sha256": found, **({"signature": signed_by} if signed_by else {})}
        elif "gpg" in step:
            signer = gpg_verify(fetched(step["gpg"]), fetched(step["signature"]), fetched(step["keys"]),
                                [text(value) for value in step.get("fingerprints", [])], gpg)
            verified.add(step["gpg"])
            sources[step["gpg"]]["signature"] = f"OpenPGP {signer}"
            print(f"gpg: {step['gpg']} is signed by {signer}", flush=True)
        elif "unpack" in step:
            name = step["unpack"]
            if name not in verified:
                raise Refused(f"step {index}: {name} is unpacked before a hash or a signature vouched for it")
            target = inside(tree, text(step["to"])) if step.get("to", ".") != "." else tree
            if step.get("merge"):
                with tempfile.TemporaryDirectory(dir=tree.parent) as work:
                    unpack(fetched(name), Path(work), int(step.get("strip", 0)))
                    target.mkdir(parents=True, exist_ok=True)
                    for folder in step["merge"]:
                        part = inside(Path(work), text(folder))
                        if not part.is_dir():
                            raise Refused(f"step {index}: {name} has no folder {text(folder)}")
                        merge(part, target)
            else:
                unpack(fetched(name), target, int(step.get("strip", 0)), [text(v) for v in step.get("only", [])])
        elif "write" in step:
            path = inside(tree, text(step["write"]))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text(step["text"]), encoding="utf-8")
            os.chmod(path, 0o755 if step.get("mode", "644") == "755" else 0o644)
        elif "link" in step:
            path = inside(tree, text(step["link"]))
            path.parent.mkdir(parents=True, exist_ok=True)
            link_inside(tree, path, text(step["to"]))
        elif "move" in step:
            target = inside(tree, text(step["to"]))
            target.parent.mkdir(parents=True, exist_ok=True)
            inside(tree, text(step["move"])).rename(target)
        elif "remove" in step:
            for pattern in step["remove"]:
                safe_relative(text(pattern))
                for path in sorted(tree.glob(text(pattern)), reverse=True):
                    if path.is_dir() and not path.is_symlink():
                        shutil.rmtree(path)
                    else:
                        path.unlink()
        elif "chmod" in step:
            os.chmod(inside(tree, text(step["chmod"])), 0o755 if step.get("mode") == "755" else 0o644)
        else:
            raise Refused(f"step {index}: none of {', '.join(VERBS)}")
    return [sources[name] for name in sources if name in verified]


# --- what the tree needs: its ELF files ---------------------------------------------------------------------------


def elf_facts(data: bytes, machine: int):
    """{"needed": [library names], "glibc": (major, minor) or None, "static": bool} of the ELF program or library
    DATA of MACHINE (64-bit, little-endian); None for anything else (a script, test data of another machine)."""
    if len(data) < 64 or data[:4] != b"\x7fELF" or data[4] != 2 or data[5] != 1:
        return None
    kind, arch = struct.unpack_from("<HH", data, 16)
    if kind not in (2, 3) or arch != machine:
        return None
    phoff, = struct.unpack_from("<Q", data, 32)
    phentsize, phnum = struct.unpack_from("<HH", data, 54)
    loads, dynamic = [], None
    for index in range(min(phnum, 256)):
        offset = phoff + index * phentsize
        if offset + 56 > len(data):
            return None
        ptype, _, poffset, vaddr, _, filesz = struct.unpack_from("<IIQQQQ", data, offset)
        if ptype == 1:
            loads.append((vaddr, poffset, filesz))
        elif ptype == 2:
            dynamic = (poffset, filesz)
    if dynamic is None:
        return {"needed": [], "glibc": None, "static": True}

    def at(address):
        for vaddr, poffset, filesz in loads:
            if vaddr <= address < vaddr + filesz:
                return poffset + address - vaddr
        return None
    entries = {}
    needed_offsets = []
    for offset in range(dynamic[0], min(dynamic[0] + dynamic[1], len(data) - 15), 16):
        tag, value = struct.unpack_from("<qQ", data, offset)
        if tag == 0:
            break
        if tag == 1:
            needed_offsets.append(value)
        else:
            entries[tag] = value
    strtab = at(entries.get(5, 0)) if 5 in entries else None

    def string(offset):
        if strtab is None or strtab + offset >= len(data):
            return ""
        end = data.find(b"\0", strtab + offset, strtab + offset + 256)
        return data[strtab + offset:end].decode("utf-8", "replace") if end >= 0 else ""
    needed = [string(offset) for offset in needed_offsets]
    newest = None
    position = at(entries[0x6ffffffe]) if 0x6ffffffe in entries else None  # DT_VERNEED
    for _ in range(min(entries.get(0x6fffffff, 0), 64)):  # DT_VERNEEDNUM
        if position is None or position + 16 > len(data):
            break
        _, count, _, aux, following = struct.unpack_from("<HHIII", data, position)
        entry = position + aux
        for _ in range(min(count, 256)):
            if entry + 16 > len(data):
                break
            _, _, _, name, next_aux = struct.unpack_from("<IHHII", data, entry)
            match = re.fullmatch(r"GLIBC_([0-9]+)\.([0-9]+)(?:\.[0-9]+)?", string(name))
            if match:
                newest = max(newest or (0, 0), (int(match[1]), int(match[2])))
            if not next_aux:
                break
            entry += next_aux
        if not following:
            break
        position += following
    return {"needed": [name for name in needed if name], "glibc": newest, "static": False}


def glibc_tuple(value):
    match = re.fullmatch(r"([0-9]{1,2})\.([0-9]{1,3})", value) if isinstance(value, str) else None
    return (int(match[1]), int(match[2])) if match else None


def measured(tree: Path, arch: str, optional=()) -> dict:
    """What the ELF files of TREE need: {"glibc": "2.28" or None, "libraries": [names not in the tree and not
    glibc's], "by": {library or "glibc X.Y": [files]}, "optional": the same of the files matching OPTIONAL}."""
    provided, facts = set(), {}
    for path in sorted(tree.rglob("*")):
        if path.is_symlink() or not path.is_file():
            if path.is_symlink():
                provided.add(path.name)
            continue
        provided.add(path.name)
        relative = path.relative_to(tree).as_posix()
        with open(path, "rb") as stream:
            head = stream.read(4)
            if head != b"\x7fELF":
                continue
            found = elf_facts(head + stream.read(), ELF_MACHINES[arch])
        if found is not None:
            facts[relative] = found
    result = {"glibc": None, "libraries": set(), "by": {}, "optional": {"glibc": None, "libraries": set()}}
    for relative, found in facts.items():
        part = result["optional"] if any(fnmatch.fnmatch(relative, pattern) for pattern in optional) else result
        if found["glibc"] and (part["glibc"] is None or found["glibc"] > part["glibc"]):
            part["glibc"] = found["glibc"]
            if part is result:
                result["by"] = {key: value for key, value in result["by"].items() if not key.startswith("glibc ")}
                result["by"]["glibc %d.%d" % found["glibc"]] = [relative]
        for library in found["needed"]:
            if library.startswith("$ORIGIN/"):  # named by its place beside the program: a file of the tree
                library = os.path.basename(library)
            if library not in provided and library not in GLIBC_LIBRARIES:
                part["libraries"].add(library)
                if part is result:
                    result["by"].setdefault(library, []).append(relative)
    for part in (result, result["optional"]):
        part["glibc"] = "%d.%d" % part["glibc"] if part["glibc"] else None
        part["libraries"] = sorted(part["libraries"])
    result["by"] = {key: value[:5] for key, value in sorted(result["by"].items())}
    return result


def needs_problems(recipe: dict, found: dict) -> list[str]:
    """Where the tree needs more than its manifest says (needs: glibc floor, libraries)."""
    needs = recipe.get("needs") or {}
    problems = []
    floor, have = glibc_tuple(needs.get("glibc")), glibc_tuple(found["glibc"])
    if have and (floor is None or have > floor):
        files = ", ".join(found["by"].get("glibc " + found["glibc"], []))
        problems.append(f"its programs need glibc {found['glibc']} ({files}), needs.glibc says {needs.get('glibc')}")
    for library in found["libraries"]:
        if library not in (needs.get("libraries") or []):
            problems.append(f"{library} is needed by {', '.join(found['by'].get(library, []))}: neither in the tree "
                            "nor in needs.libraries (or list these files as optional)")
    return problems


# --- the archive -----------------------------------------------------------------------------------------------


def tree_size(tree: Path) -> int:
    return sum(path.lstat().st_size for path in tree.rglob("*") if path.is_file() and not path.is_symlink())


def pack(tree: Path, archive: Path) -> None:
    """TREE as ARCHIVE (tar.xz): its files by name, without owners or times of this machine, no special bits."""
    def clean(info):
        info.uid = info.gid = 0
        info.uname = info.gname = ""
        info.mtime = 0
        if info.isdir() or (info.isfile() and info.mode & 0o111):
            info.mode = 0o755
        elif info.isfile():
            info.mode = 0o644
        return info
    xz = shutil.which("xz")
    if xz:  # every core (the trees are large); the bytes are pinned by the SHA-256 this build writes
        with open(archive, "wb") as raw:
            process = subprocess.Popen([xz, "-T0", "-6", "-c"], stdin=subprocess.PIPE, stdout=raw)
            with tarfile.open(fileobj=process.stdin, mode="w|") as out:
                for path in sorted(tree.rglob("*")):
                    out.add(path, arcname=path.relative_to(tree).as_posix(), recursive=False, filter=clean)
            process.stdin.close()
            if process.wait() != 0:
                raise Refused("xz failed")
        return
    with lzma.open(archive, "wb", preset=6) as raw, tarfile.open(fileobj=raw, mode="w|") as out:
        for path in sorted(tree.rglob("*")):
            out.add(path, arcname=path.relative_to(tree).as_posix(), recursive=False, filter=clean)


def manifest(recipe: dict, arch: str) -> dict:
    """The catalog entry's own part of RECIPE for ARCH (what sandbox-ai's toolchains.validated reads)."""
    entry = {key: recipe[key] for key in MANIFEST_KEYS if key in recipe}
    entry["arch"] = arch
    # (env keeps its "{prefix}": sandbox-ai puts the mount point in)
    entry.setdefault("needs", {"glibc": None, "libraries": []})
    return entry


def build(name: str, arch: str, out: Path, downloads: Path | None = None, today: datetime.date | None = None,
          root: Path = ROOT, opener=None, gpg=subprocess.run) -> dict:
    recipe = load(name, root)
    today = today or datetime.date.today()
    problems = problems_of(recipe, today)
    if arch not in (recipe.get("arches") or []):
        problems.append(f"{name}: not built for {arch} (arches)")
    if problems:
        raise Refused("; ".join(problems))
    out.mkdir(parents=True, exist_ok=True)
    tree = out / f"tree-{name}-{arch}"
    if tree.exists():
        shutil.rmtree(tree)
    sources = run_steps(recipe, arch, tree, downloads or out / "downloads", opener, gpg)
    missing = [path for path in recipe["commands"].values() if not (tree / path).is_file()]
    if missing:
        raise Refused(f"{name}: the tree has no {missing[0]}, which the manifest names as a command")
    not_runnable = [path for path in recipe["commands"].values() if not os.access(tree / path, os.X_OK)]
    if not_runnable:
        raise Refused(f"{name}: {not_runnable[0]} is not executable")
    found = measured(tree, arch, recipe.get("optional") or [])
    problems = needs_problems(recipe, found)
    if problems:
        raise Refused(f"{name}: " + "; ".join(problems))
    archive = out / f"toolchain-{name}-{arch}.tar.xz"
    pack(tree, archive)
    sha = digest(archive)
    entry = {**manifest(recipe, arch),
             "url": f"{RELEASES}/toolchain-{name}-{arch}-{sha[:12]}/{archive.name}", "sha256": sha,
             "size": archive.stat().st_size, "unpacked": tree_size(tree), "sources": sources}
    meta = {"entry": entry, "measured": {key: found[key] for key in ("glibc", "libraries", "optional")},
            "smoke": recipe.get("smoke") or []}
    (out / f"toolchain-{name}-{arch}.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return meta


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    builder = commands.add_parser("build")
    builder.add_argument("name")
    builder.add_argument("--arch", choices=ARCHES, required=True)
    builder.add_argument("--out", type=Path, required=True)
    builder.add_argument("--downloads", type=Path)
    builder.add_argument("--date", help="today, for the 14-day rule (default: today)")
    builder.add_argument("--root", type=Path, default=ROOT)
    checker = commands.add_parser("check")
    checker.add_argument("names", nargs="*")
    checker.add_argument("--date")
    checker.add_argument("--root", type=Path, default=ROOT)
    opts = parser.parse_args(argv)
    today = datetime.date.fromisoformat(opts.date) if opts.date else datetime.date.today()
    try:
        if opts.command == "build":
            meta = build(opts.name, opts.arch, opts.out, opts.downloads, today, opts.root)
            print(json.dumps({key: meta["entry"][key] for key in ("name", "version", "arch", "sha256", "size",
                                                                  "unpacked")} | {"measured": meta["measured"]},
                             indent=2))
            return 0
        names = opts.names or sorted(path.parent.name for path in (opts.root / "toolchains").glob("*/toolchain.json"))
        problems = []
        for name in names:
            problems += problems_of(load(name, opts.root), today)
        for problem in problems:
            print(problem, file=sys.stderr)
        print(f"{len(names)} toolchains, {len(problems)} problems")
        return 1 if problems else 0
    except Refused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
