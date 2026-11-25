#!/usr/bin/env python3
"""toolchains.json: the catalog of build toolchains sandbox-ai reads (sandbox-ai toolchain catalog|add).

    scripts/make_toolchains.py --ci DIR            from a CI run's artifacts (tc-ID-ARCH: its toolchain-*.json
                                                   and both smoke reports): the entries that passed
    scripts/make_toolchains.py --check [--sandbox-ai DIR]
                                                   toolchains.json agrees with toolchains/*/toolchain.json, and
                                                   (with DIR) every entry is one sandbox-ai's own reader takes

An entry is the manifest of a recipe - toolchains/NAME/toolchain.json, or an older version's
toolchains/NAME/LINE/toolchain.json (ID NAME@LINE): several versions of a name are several entries - (name, version,
commands, env, caches, hosts, allow, needs, requires ...) for one architecture, with what the build produced: the archive's URL (a release of this
repository named after the archive's hash), its SHA-256 and sizes, and the upstream sources. Only a toolchain whose
archive passed its smoke test with sandbox-ai under Podman and under Bubblewrap enters (scripts/toolchain_smoke.py);
every other is named and left out. The file is signed with scripts/sign_toolchains.py (docs/TOOLCHAINS.md).

"recipes" beside "toolchains": the toolchains that are built on the user's machine (a recipe with "local": true -
the Android SDK, which may not be passed on), each the manifest and the recipe sandbox-ai runs after the user
accepted its license (scripts/toolchain.py local_entry). No build and no smoke test of this repository's CI stands
behind one - it downloads nothing of it -: what is signed is that its URLs, sizes and hashes are its publisher's.
A sandbox-ai from before them reads "toolchains" alone.
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


def report_problems(folder: Path, entry: dict, root: Path = ROOT) -> list[str]:
    """Why ENTRY (of a build's meta file) may not enter the catalog: both reports under FOLDER must have passed, for
    exactly its archive. They are named after the ID of its recipe (of ROOT): smoke-ID-ARCH-RUNNER.json."""
    problems = []
    try:
        ident = builder().id_of(entry["name"], entry["version"], root)
    except ValueError as exc:
        return [str(exc)]
    for runner in RUNNERS:
        wanted = f"smoke-{ident}-{entry['arch']}-{runner}.json"
        found = sorted(folder.rglob(wanted))
        try:
            report = json.loads(found[0].read_text(encoding="utf-8")) if len(found) == 1 else None
        except (OSError, ValueError):
            report = None
        steps = [c for c in (report or {}).get("checks", []) if str(c.get("check", "")).startswith("run ")]
        if not isinstance(report, dict):
            problems.append(f"no {wanted}" if len(found) != 1 or report is None else f"{wanted} is no report")
        elif report.get("runner") != runner or report.get("name") != entry["name"] or \
                report.get("arch") != entry["arch"] or report.get("version", entry["version"]) != entry["version"]:
            problems.append(f"{wanted} is not the {runner} report of {entry['name']} {entry['version']} "
                            f"{entry['arch']}")
        elif report.get("sha256") != entry["sha256"]:
            problems.append(f"{wanted} is of the archive {report.get('sha256')}, not {entry['sha256']}")
        elif not report.get("ok") or not steps or not all(c.get("ok") for c in report.get("checks", [])):
            failed = [str(c.get("check")) for c in report.get("checks", []) if not c.get("ok")]
            problems.append(f"{runner} failed ({', '.join(failed) or 'nothing was run'})")
    return problems


def order(entry: dict):
    """The catalog's order: by name, its newest version first, then by architecture."""
    numbers, text = builder().version_key(str(entry.get("version")))
    return entry.get("name"), [-number for number in numbers], text, entry.get("arch")


def from_ci(folder: Path, root: Path = ROOT) -> tuple[list[dict], list[str]]:
    """(the entries of the builds under FOLDER that passed both smoke tests, what was left out and why). A toolchain
    another requires is its newest version (its recipe toolchains/NAME/toolchain.json)."""
    entries, left_out = [], []
    for path in sorted(folder.rglob("toolchain-*.json")):
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))["entry"]
        except (OSError, ValueError, KeyError, TypeError):
            left_out.append(f"{path.name}: not a build's meta file")
            continue
        problems = report_problems(folder, entry, root)
        if problems:
            left_out.append(f"{entry['name']} {entry['version']} {entry['arch']}: " + "; ".join(problems))
        else:
            entries.append(entry)
    names = {(entry["name"], entry["arch"]) for entry in entries}
    for entry in list(entries):  # a toolchain without what it requires is of no use
        missing = [other for other in entry.get("requires", []) if (other, entry["arch"]) not in names]
        if missing:
            entries.remove(entry)
            left_out.append(f"{entry['name']} {entry['version']} {entry['arch']}: requires {', '.join(missing)}, "
                            "which did not pass")
    return sorted(entries, key=order), left_out


def local_entries(root: Path = ROOT) -> list[dict]:
    """The entries of "recipes": every local recipe of ROOT (built on the user's machine), each architecture."""
    build = builder()
    found = []
    for ident in build.recipe_ids(root):
        recipe = build.load(ident, root)
        if build.is_local(recipe):
            found += [build.local_entry(ident, arch, root) for arch in recipe.get("arches") or []]
    return sorted(found, key=order)


def with_required(recipes: list[dict], entries: list[dict]) -> tuple[list[dict], list[str]]:
    """(the RECIPES whose required toolchains are among ENTRIES for their architecture, what was left out and why):
    a toolchain without what it requires is of no use (android-sdk without the jdk)."""
    names = {(entry["name"], entry["arch"]) for entry in entries}
    kept, left_out = [], []
    for entry in recipes:
        missing = [other for other in entry.get("requires", []) if (other, entry["arch"]) not in names]
        if missing:
            left_out.append(f"{entry['name']} {entry['version']} {entry['arch']}: requires {', '.join(missing)}, "
                            "which is not in toolchains.json")
        else:
            kept.append(entry)
    return kept, left_out


def document(entries: list[dict], recipes: list[dict] | None = None) -> str:
    return json.dumps({"schema": SCHEMA, "version": 1, "toolchains": entries,
                       **({"recipes": recipes} if recipes else {})}, indent=2) + "\n"


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
        label = f"{entry.get('name')} {entry.get('version')} {entry.get('arch')}"
        if (entry.get("name"), entry.get("version"), entry.get("arch")) in seen:
            problems.append(f"{label}: twice in toolchains.json")
        seen.add((entry.get("name"), entry.get("version"), entry.get("arch")))
        try:
            ident = build.id_of(str(entry.get("name")), str(entry.get("version")), root)
            recipe = build.load(ident, root)
        except ValueError as exc:
            problems.append(f"{label}: {exc}")
            continue
        wanted = build.manifest(recipe, entry.get("arch"))
        where = build.recipe_path(ident, root).relative_to(root).as_posix()
        for key, value in wanted.items():
            if entry.get(key) != value:
                problems.append(f"{label}: {key} is not what {where} says")
        if not str(entry.get("url", "")).startswith(f"{build.RELEASES}/toolchain-{entry.get('name')}-"
                                                    f"{entry.get('arch')}-{str(entry.get('sha256'))[:12]}/"):
            problems.append(f"{label}: its url is not this repository's release of its archive")
        if build.is_local(recipe):
            problems.append(f"{label}: its recipe is local (built on the user's machine): it belongs in \"recipes\"")
        if reader is not None:
            try:
                reader.validated(entry, label)
            except ValueError as exc:
                problems.append(f"sandbox-ai does not take it: {exc}")
    # "recipes": exactly the local recipes of this repository, each as scripts/toolchain.py makes its entry (one
    # whose required toolchains are not in the catalog is left out, as an archive's entry is: with_required).
    listed = catalog.get("recipes", [])
    if not isinstance(listed, list):
        return problems + ["toolchains.json: recipes must be a list"]
    try:
        wanted = local_entries(root)
    except ValueError as exc:
        return problems + [f"a local recipe: {exc}"]
    key = lambda entry: (entry.get("name"), entry.get("version"), entry.get("arch"))  # noqa: E731
    for entry in wanted:
        label = f"{entry['name']} {entry['version']} {entry['arch']}"
        same = [other for other in listed if isinstance(other, dict) and key(other) == key(entry)]
        if not same and not with_required([entry], catalog["toolchains"])[0]:
            continue  # (left out: what it requires did not pass)
        if len(same) != 1:
            problems.append(f"{label}: {'twice' if same else 'not'} in the recipes of toolchains.json (run "
                            "scripts/make_toolchains.py --recipes)")
        elif same[0] != entry:
            differs = sorted(k for k in {*entry, *same[0]} if entry.get(k) != same[0].get(k))
            problems.append(f"{label}: {', '.join(differs)} is not what its recipe says (run "
                            "scripts/make_toolchains.py --recipes)")
        problems += [f"{label}: requires {other}, which is not in toolchains.json"
                     for other in entry.get("requires", [])
                     if not any(e.get("name") == other and e.get("arch") == entry["arch"]
                                for e in catalog["toolchains"])]
        # (a sandbox-ai from before recipes reads "toolchains" alone and is told nothing of these: no problem of
        # the catalog's - the checkout the CI checks against may be the published one)
        if reader is not None and hasattr(reader, "RECIPES_LIMIT"):
            try:
                reader.validated(entry, label)
            except ValueError as exc:
                problems.append(f"sandbox-ai does not take it: {exc}")
    for other in listed:
        if not isinstance(other, dict) or not any(key(other) == key(entry) for entry in wanted):
            problems.append(f"{other.get('name') if isinstance(other, dict) else other!r}: in the recipes of "
                            "toolchains.json, but no local recipe of this repository")
    return problems


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--ci", type=Path, help="the downloaded artifacts of the toolchain jobs")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--recipes", action="store_true",
                        help="write the \"recipes\" of toolchains.json anew from the local recipes (its \"toolchains\" "
                             "stay as they are): after a local recipe changed - then sign again")
    parser.add_argument("--sandbox-ai", type=Path, help="with --check: a sandbox-ai checkout (its reader)")
    opts = parser.parse_args(argv)
    if opts.check:
        problems = check(opts.root, opts.sandbox_ai)
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1 if problems else 0
    if opts.recipes:
        path = opts.root / "toolchains.json"
        catalog = json.loads(path.read_text(encoding="utf-8"))
        recipes, left_out = with_required(local_entries(opts.root), catalog["toolchains"])
        for line in left_out:
            print(f"left out: {line}", file=sys.stderr)
        path.write_text(document(catalog["toolchains"], recipes), encoding="utf-8")
        print("\n".join(f"recipe {entry['name']} {entry['version']} {entry['arch']}" for entry in recipes))
        return 0
    if not opts.ci:
        parser.error("--ci DIR, --recipes or --check")
    entries, left_out = from_ci(opts.ci, opts.root)
    for line in left_out:
        print(f"left out: {line}", file=sys.stderr)
        print(f"::warning title=left out of toolchains.json::{line[:300]}")
    if not entries:
        print("no toolchain passed: no catalog", file=sys.stderr)
        return 1
    recipes, without = with_required(local_entries(opts.root), entries)
    for line in without:
        print(f"left out: {line}", file=sys.stderr)
        print(f"::warning title=left out of toolchains.json::{line[:300]}")
    (opts.root / "toolchains.json").write_text(document(entries, recipes), encoding="utf-8")
    print("\n".join([*(f"{entry['name']} {entry['version']} {entry['arch']}" for entry in entries),
                     *(f"recipe {entry['name']} {entry['version']} {entry['arch']}" for entry in recipes)]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
