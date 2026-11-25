#!/usr/bin/env python3
"""The recipes of the toolchain android-sdk (toolchains/android-sdk: 37, and the older lines 36 and 35), written from
sandbox-ai's own list of pins.

    scripts/android_sdk_recipes.py --sandbox-ai DIR            write them
    scripts/android_sdk_recipes.py --sandbox-ai DIR --check    they are what DIR's pins make (exit status 1: not)

The Android SDK may not be passed on (Android Software Development Kit License Agreement, section 3.4), so these
recipes are "local": this repository builds and publishes no archive of them; toolchains.json publishes the recipe
and sandbox-ai runs it on the user's machine once they accepted the license (scripts/toolchain.py's docstring).

One list of pins for everything Android in sandbox-ai: DIR/sandbox/recipes/android-dev/sdk.lock (each Google archive
with its size, Google's SHA-1 and the SHA-256 of a download that was made and checked; its comment lines say since
when each is in Google's repository), the package.xml files beside it (what sdkmanager writes beside a package it
installs: the Android Gradle plugin and sdkmanager find the packages by them) and the acceptance sdkmanager records
(licenses/android-sdk-license). A line is one API level: its platform and build-tools, with platform-tools, the
command-line tools, the NDK and CMake that every line has. No emulator and no system image: those need /dev/kvm
(sandbox-ai's service android-emulator).

What nothing here measures is said here: UNPACKED (the bytes each archive unpacks to: the sum of the file sizes its
central directory lists, read on 2026-11-24), STRIP (whether its files lie in one folder of the archive) and NEEDS
(what the tree's ELF files need of the system: measured with scripts/toolchain.py's own measure on the tree
sandbox-ai built from the line 37 on 2026-11-24 - the newest GLIBC_x.y any of them asks for is CMake's, and aapt,
aapt2, aidl, clang and lld load libgcc_s and libz of the system; the NDK's Python modules for curses, bz2, crypt
and nis and build-tools' RenderScript compiler (libncurses.so.5, libtinfo.so.5) need more and are not vouched for).
Standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "android-sdk"
# line: (the platform's package, the build-tools' package); the first is the newest (the name's own recipe).
LINES = {"37": ("platforms;android-37.0", "build-tools;37.0.0"),
         "36": ("platforms;android-36", "build-tools;36.0.0"),
         "35": ("platforms;android-35", "build-tools;35.0.0")}
COMMON = ("cmdline-tools;23.0", "platform-tools", "ndk;30.0.16248370", "cmake;4.1.2", "cmake;3.22.1")
UNPACKED = {"cmdline-tools;23.0": 181024533, "platform-tools": 22198160, "platforms;android-37.0": 124986304,
            "platforms;android-36": 106177284, "platforms;android-35": 102589879, "build-tools;37.0.0": 158047817,
            "build-tools;36.0.0": 153141817, "build-tools;35.0.0": 153245182, "ndk;30.0.16248370": 2347519582,
            "cmake;4.1.2": 77063181, "cmake;3.22.1": 53059675}
STRIP = {"cmake;4.1.2": 0, "cmake;3.22.1": 0}  # every other archive holds one folder: its contents are the package
NEEDS = {"glibc": "2.28", "libraries": ["libgcc_s.so.1", "libz.so.1"]}
SDK = "/opt/android-sdk/"  # where the lock's rows put a package in the image variant android-dev
NDK, CMAKE, CMDLINE = "ndk/30.0.16248370", "cmake/4.1.2", "cmdline-tools/23.0"
PACKAGE_XML = re.compile(r'(<\?xml[^\n]*\n<ns2:repository[^>]*>\n?)<license id="android-sdk-license" type="text">'
                         r'(.*?)</license>(.*)', re.S)


def lock_rows(text: str) -> dict:
    """{package: {"version", "to", "size", "sha1", "sha256", "url", "released"}} of sdk.lock's Google archives."""
    rows, released = {}, None
    for line in text.splitlines():
        if line.startswith("#"):
            found = re.search(r"in Google's repository by (\d{4}-\d\d-\d\d)", line)
            released = found[1] if found else released
            continue
        parts = line.split()
        if len(parts) != 7 or parts[0] == "-" or not parts[2].startswith(SDK):
            continue
        package, version, dest, size, sha1, sha256, url = parts
        rows[package] = {"version": version, "to": dest[len(SDK):], "size": int(size), "sha1": sha1, "sha256": sha256,
                         "url": url, "released": released}
    return rows


def recipe(line: str, sandbox_ai: Path) -> dict:
    """The recipe of the line LINE (37, 36, 35) from SANDBOX_AI's pins."""
    folder = sandbox_ai / "sandbox" / "recipes" / "android-dev"
    rows = lock_rows((folder / "sdk.lock").read_text(encoding="utf-8"))
    platform, build_tools = LINES[line]
    packages = [COMMON[0], COMMON[1], platform, build_tools, *COMMON[2:]]
    version = rows[build_tools]["version"]
    api = rows[platform]["to"].rpartition("/")[2]  # android-37.0
    steps, head, license_text = [], None, None
    for package in packages:
        row = rows[package]
        if not re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) or not row["released"]:
            raise SystemExit(f"{package}: sdk.lock has no confirmed SHA-256 or no date for it")
        file = package.replace(";", "-") + ".zip"
        steps.append({"fetch": file, "url": row["url"], "size": row["size"], "sha256": row["sha256"],
                      "sha1": row["sha1"], "released": row["released"]})
        steps.append({"unpack": file, "to": row["to"], "strip": STRIP.get(package, 1)})
        found = PACKAGE_XML.fullmatch((folder / "package-xml" / (package.replace(";", "_") + ".xml"))
                                      .read_text(encoding="utf-8"))
        if not found or (head, license_text) not in ((None, None), (found[1], found[2])):
            raise SystemExit(f"{package}: its package.xml is not what the others are (head, license, package)")
        head, license_text = found[1], found[2]
        steps.append({"write": f"{row['to']}/package.xml", "mode": "644",
                      "text": '{xmlhead}<license id="android-sdk-license" type="text">{license}</license>' + found[3]})
    steps.append({"write": "licenses/android-sdk-license", "mode": "644",
                  "text": (folder / "android-sdk-license").read_text(encoding="utf-8")})
    tools = rows[build_tools]["to"]
    ndk = rows[COMMON[2]]["version"]
    return {
        "name": NAME, "version": version, "local": True, "terms": "android-sdk-license",
        "title": f"Android SDK (API {api.partition('-')[2].partition('.')[0]})",
        "description": (
            f"The Android SDK for building apps: the platform {api} with build-tools {version}, platform-tools "
            f"{rows[COMMON[1]]['version']} (adb, fastboot), the command-line tools {rows[COMMON[0]]['version']} "
            "(apkanalyzer; sdkmanager needs a writable SDK and is not offered), the "
            f"NDK {ndk} and CMake {rows[COMMON[3]]['version']} and {rows[COMMON[4]]['version']}. No archive of ours "
            "(Google's license forbids passing the SDK on): sandbox-ai fetches each file from dl.google.com on your "
            "machine once you accepted that license and checks it against this signed recipe. Mounted read-only: "
            "nothing is installed into it, and the Android Gradle plugin is told not to try (GRADLE_OPTS) - it "
            f"names what a project needs beyond compileSdk {api.partition('-')[2].partition('.')[0]} and "
            f"buildToolsVersion \"{version}\". Gradle and the JDK: the toolchain jdk. No emulator (the service "
            "android-emulator). RenderScript's compiler and the NDK's Python modules for curses, bz2, crypt and nis "
            "need libraries of the system and are not vouched for."),
        "license": "Android Software Development Kit License Agreement (Google; may not be redistributed)",
        "homepage": "https://developer.android.com/studio",
        "arches": ["x86_64"],
        "vars": {"xmlhead": head, "license": license_text},
        # No sdkmanager and no avdmanager: sdkmanager needs a writable SDK (it makes a lock folder in it even to list:
        # tried on 2026-11-24, it fails on the read-only tree), and an AVD needs a system image, which no line has.
        "commands": {"adb": "platform-tools/adb", "fastboot": "platform-tools/fastboot",
                     "apkanalyzer": f"{CMDLINE}/bin/apkanalyzer", "aapt": f"{tools}/aapt", "aapt2": f"{tools}/aapt2", "apksigner": f"{tools}/apksigner",
                     "zipalign": f"{tools}/zipalign", "d8": f"{tools}/d8", "aidl": f"{tools}/aidl",
                     "ndk-build": f"{NDK}/ndk-build", "cmake": f"{CMAKE}/bin/cmake", "ninja": f"{CMAKE}/bin/ninja"},
        "env": {"ANDROID_HOME": "{prefix}", "ANDROID_SDK_ROOT": "{prefix}", "ANDROID_NDK_HOME": "{prefix}/" + NDK,
                "ANDROID_NDK_ROOT": "{prefix}/" + NDK,
                "GRADLE_OPTS": "-Dorg.gradle.project.android.builder.sdkDownload=false"},
        "caches": {},
        "hosts": ["dl.google.com", "maven.google.com"],
        "allow": [],
        "needs": NEEDS,
        "requires": ["jdk"],
        "unpacked": sum(UNPACKED[package] for package in packages),
        "build": steps,
        "notes": ("Written by scripts/android_sdk_recipes.py from sandbox-ai's sandbox/recipes/android-dev (sdk.lock: "
                  "Google's SDK repository as nixpkgs keeps it - size and SHA-1 -, and the SHA-256 of a download of "
                  "each archive made on 2026-11-24, whose size and SHA-1 matched). needs: measured on the tree "
                  "sandbox-ai built from the line 37 that day (the script's NEEDS); this repository's CI builds and "
                  "measures nothing of it. Tried that day with that tree, read-only, the toolchain jdk (Gradle 9.9.0) "
                  "and the Android Gradle plugin 9.5.2: assembleDebug of a small app (compileSdk 37, buildToolsVersion "
                  "37.0.0) built its APK and wrote nothing into the tree; with GRADLE_OPTS as set here a project that "
                  "names android-36 is told 'Failed to find target with hash string android-36', without it the "
                  "plugin tries to install it and fails with 'The SDK directory is not writable'."),
    }


def path_of(line: str, root: Path) -> Path:
    folder = root / "toolchains" / NAME
    return (folder if line == next(iter(LINES)) else folder / line) / "toolchain.json"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--sandbox-ai", type=Path, required=True, help="a sandbox-ai checkout (its pins)")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--check", action="store_true")
    opts = parser.parse_args(argv)
    status = 0
    for line in LINES:
        text = json.dumps(recipe(line, opts.sandbox_ai), indent=2) + "\n"
        path = path_of(line, opts.root)
        if opts.check:
            if not path.is_file() or path.read_text(encoding="utf-8") != text:
                print(f"{path.relative_to(opts.root)} is not what {opts.sandbox_ai}'s pins make", file=sys.stderr)
                status = 1
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            print(path.relative_to(opts.root))
    return status


if __name__ == "__main__":
    sys.exit(main())
