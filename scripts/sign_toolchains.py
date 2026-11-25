#!/usr/bin/env python3
"""Sign toolchains.json: the statement that every toolchain of it was built from its pinned upstream release and
compiled and ran a hello world with sandbox-ai, under Podman and under Bubblewrap.

    scripts/sign_toolchains.py --key ~/.config/sandbox-ai/mcp-signing-key --reports DIR
    scripts/sign_toolchains.py --verify --signers /path/to/sandbox-ai/sandbox/mcp-signers

The same key and namespace as catalog.json (scripts/sign_catalog.py: ssh-keygen -Y sign, namespace sandbox-ai-mcp,
principal mcp@sandbox-ai); sandbox-ai checks toolchains.json.sig against sandbox/mcp-signers before `sandbox-ai
toolchain add` takes an entry. Before it signs it requires, in DIR or a folder below it (the artifact "toolchains"
of the toolchains workflow), for every entry - every version of a name is one - both smoke reports -
smoke-ID-ARCH-sandbox-ai-podman.json and ...-bwrap.json, ID the entry's recipe (NAME, or NAME@LINE for an older
version) -, passed, for exactly the entry's archive (sha256); that toolchains.json agrees with the recipes
(scripts/make_toolchains.py --check); and that every toolchain an entry requires is in it. The key never leaves
your machine. Standard library only (ssh-keygen).

The "recipes" of toolchains.json (the toolchains built on the user's machine: the Android SDK) have no archive and
no report of this repository's CI, which downloads nothing of them. For them the signature says: the recipe is the
one of this repository (make_toolchains.py --check holds each to its toolchain.json: every download with its size
and SHA-256), and its URLs, sizes and hashes are its publisher's - confirm that yourself before you sign (sandbox-ai's
live check: `sandbox-ai live_check --only toolchain-live` adds android-sdk from this catalog and builds an app).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"{name}_for_toolchains", Path(__file__).with_name(f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def problems_of(root: Path, reports: Path) -> list[str]:
    make = load("make_toolchains")
    problems = make.check(root, None)
    if problems:
        return [f"toolchains.json is not current: {problem}" for problem in problems]
    catalog = json.loads((root / "toolchains.json").read_text(encoding="utf-8"))
    entries = catalog["toolchains"]
    if not entries and not catalog.get("recipes"):
        return ["toolchains.json has no entry: nothing to vouch for"]
    if not reports.is_dir():
        return [f"{reports}: not a folder of smoke reports"]
    names = {(entry["name"], entry["arch"]) for entry in entries}
    for entry in entries:
        label = f"{entry['name']} {entry['version']} {entry['arch']}"
        problems += [f"{label}: {problem}" for problem in make.report_problems(reports, entry, root)]
        problems += [f"{label}: requires {other}, which is not in toolchains.json"
                     for other in entry.get("requires", []) if (other, entry["arch"]) not in names]
        if not entry.get("sources"):
            problems.append(f"{label}: no upstream sources recorded")
    return problems


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--key", help="the private key (or the .pub of a key in ssh-agent)")
    parser.add_argument("--reports", type=Path, help="the smoke reports of the CI run")
    parser.add_argument("--verify", action="store_true", help="check the signature instead")
    parser.add_argument("--signers", type=Path, help="with --verify: sandbox-ai's sandbox/mcp-signers")
    opts = parser.parse_args(argv)
    sign_catalog = load("sign_catalog")
    path = opts.root.resolve() / "toolchains.json"
    if opts.verify:
        if not opts.signers:
            parser.error("--verify needs --signers")
        return 0 if sign_catalog.verify(path, opts.signers) else 1
    if not (opts.key and opts.reports):
        parser.error("--key and --reports are needed")
    if not path.is_file():
        print(f"refused: {path} missing", file=sys.stderr)
        return 1
    problems = problems_of(opts.root.resolve(), opts.reports)
    for problem in problems:
        print(f"refused: {problem}", file=sys.stderr)
    if problems:
        print("nothing signed", file=sys.stderr)
        return 1
    print(f"signed {sign_catalog.sign(path, opts.key).name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
