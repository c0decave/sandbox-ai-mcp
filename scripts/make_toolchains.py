#!/usr/bin/env python3
"""toolchains.json: the catalog of build toolchains sandbox-ai reads (sandbox-ai toolchain catalog|add).

    scripts/make_toolchains.py --ci DIR            from a CI run's artifacts (tc-NAME-ARCH: its toolchain-*.json
                                                   and both smoke reports): the entries that passed
    scripts/make_toolchains.py --check [--sandbox-ai DIR]
                                                   toolchains.json agrees with toolchains/*/toolchain.json, and
                                                   (with DIR) every entry is one sandbox-ai's own reader takes

An entry is the manifest of toolchains/NAME/toolchain.json (name, version, commands, env, caches, hosts, allow,
needs, requires ...) for one architecture, with what the build produced: the archive's URL (a release of this
repository named after the archive's hash), its SHA-256 and sizes, and the upstream sources. Only a toolchain whose
archive passed its smoke test with sandbox-ai under Podman and under Bubblewrap enters (scripts/toolchain_smoke.py);
every other is named and left out. The file is signed with scripts/sign_toolchains.py (docs/TOOLCHAINS.md).
Standard library only.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = "sandbox-ai-toolchains"
RUNNERS = ("sandbox-ai-podman", "sandbox-ai-bwrap")


def builder():
    spec = importlib.util.spec_from_file_location("toolchain_for_catalog", Path(__file__).with_name("toolchain.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def report_problems(folder: Path, entry: dict) -> list[str]:
    """Why ENTRY (of a build's meta file) may not enter the catalog: both reports under FOLDER must have passed, for
    exactly its archive."""
    problems = []
    for runner in RUNNERS:
        wanted = f"smoke-{entry['name']}-{entry['arch']}-{runner}.json"
        found = sorted(folder.rglob(wanted))
        try:
            report = json.loads(found[0].read_text(encoding="utf-8")) if len(found) == 1 else None
        except (OSError, ValueError):
            report = None
        steps = [c for c in (report or {}).get("checks", []) if str(c.get("check", "")).startswith("run ")]
        if not isinstance(report, dict):
            problems.append(f"no {wanted}" if len(found) != 1 or report is None else f"{wanted} is no report")
        elif report.get("runner") != runner or report.get("name") != entry["name"] or \
                report.get("arch") != entry["arch"]:
            problems.append(f"{wanted} is not the {runner} report of {entry['name']} {entry['arch']}")
        elif report.get("sha256") != entry["sha256"]:
            problems.append(f"{wanted} is of the archive {report.get('sha256')}, not {entry['sha256']}")
        elif not report.get("ok") or not steps or not all(c.get("ok") for c in report.get("checks", [])):
            failed = [str(c.get("check")) for c in report.get("checks", []) if not c.get("ok")]
            problems.append(f"{runner} failed ({', '.join(failed) or 'nothing was run'})")
    return problems


def from_ci(folder: Path) -> tuple[list[dict], list[str]]:
    """(the entries of the builds under FOLDER that passed both smoke tests, what was left out and why)."""
    entries, left_out = [], []
    for path in sorted(folder.rglob("toolchain-*.json")):
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))["entry"]
        except (OSError, ValueError, KeyError, TypeError):
            left_out.append(f"{path.name}: not a build's meta file")
            continue
        problems = report_problems(folder, entry)
        if problems:
            left_out.append(f"{entry['name']} {entry['arch']}: " + "; ".join(problems))
        else:
            entries.append(entry)
    names = {(entry["name"], entry["arch"]) for entry in entries}
    for entry in list(entries):  # a toolchain without what it requires is of no use
        missing = [other for other in entry.get("requires", []) if (other, entry["arch"]) not in names]
        if missing:
            entries.remove(entry)
            left_out.append(f"{entry['name']} {entry['arch']}: requires {', '.join(missing)}, which did not pass")
    return sorted(entries, key=lambda e: (e["name"], e["arch"])), left_out


def document(entries: list[dict]) -> str:
    return json.dumps({"schema": SCHEMA, "version": 1, "toolchains": entries}, indent=2) + "\n"


def check(root: Path, sandbox_ai: Path | None) -> list[str]:
    problems = []
    try:
        catalog = json.loads((root / "toolchains.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"toolchains.json: {exc}"]
    if catalog.get("schema") != SCHEMA or catalog.get("version") != 1 or \
            not isinstance(catalog.get("toolchains"), list):
        return [f"toolchains.json: expected schema {SCHEMA}, version 1"]
    build = builder()
    reader = None
    if sandbox_ai is not None:
        spec = importlib.util.spec_from_file_location("sandbox_ai_toolchains_for_check",
                                                      sandbox_ai / "sandbox" / "toolchains.py")
        reader = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(reader)
    seen = set()
    for entry in catalog["toolchains"]:
        label = f"{entry.get('name')} {entry.get('arch')}"
        if (entry.get("name"), entry.get("version"), entry.get("arch")) in seen:
            problems.append(f"{label}: twice in toolchains.json")
        seen.add((entry.get("name"), entry.get("version"), entry.get("arch")))
        try:
            recipe = build.load(str(entry.get("name")), root)
        except ValueError as exc:
            problems.append(f"{label}: {exc}")
            continue
        wanted = build.manifest(recipe, entry.get("arch"))
        for key, value in wanted.items():
            if entry.get(key) != value:
                problems.append(f"{label}: {key} is not what toolchains/{entry.get('name')}/toolchain.json says")
        if not str(entry.get("url", "")).startswith(f"{build.RELEASES}/toolchain-{entry.get('name')}-"
                                                    f"{entry.get('arch')}-{str(entry.get('sha256'))[:12]}/"):
            problems.append(f"{label}: its url is not this repository's release of its archive")
        if reader is not None:
            try:
                reader.validated(entry, label)
            except ValueError as exc:
                problems.append(f"sandbox-ai does not take it: {exc}")
    return problems


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--ci", type=Path, help="the downloaded artifacts of the toolchain jobs")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--sandbox-ai", type=Path, help="with --check: a sandbox-ai checkout (its reader)")
    opts = parser.parse_args(argv)
    if opts.check:
        problems = check(opts.root, opts.sandbox_ai)
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1 if problems else 0
    if not opts.ci:
        parser.error("--ci DIR or --check")
    entries, left_out = from_ci(opts.ci)
    for line in left_out:
        print(f"left out: {line}", file=sys.stderr)
        print(f"::warning title=left out of toolchains.json::{line[:300]}")
    if not entries:
        print("no toolchain passed: no catalog", file=sys.stderr)
        return 1
    (opts.root / "toolchains.json").write_text(document(entries), encoding="utf-8")
    print("\n".join(f"{entry['name']} {entry['version']} {entry['arch']}" for entry in entries))
    return 0


if __name__ == "__main__":
    sys.exit(main())
