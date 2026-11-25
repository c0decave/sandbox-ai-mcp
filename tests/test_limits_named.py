"""A server whose description or notes name the limits it needs (--memory 2g, --pids 512, "a /tmp of 768m", "2g memory,
256 processes and a 256m /tmp", or only --memory) must have them machine-readable too: smoke.json's memory, pids and tmp
become rootfs.json's "limits", which sandbox-ai's `mcp add` and `mcp set --recommended` apply. Prose alone is read by
nobody's program: a server added with sandbox-ai's defaults (512m, 128 processes, a /tmp of 64m) then fails later -
Chromium, the JVMs (the user, 2026-11-25: gowitness behind Tor). A value named "default" is sandbox-ai's, not a need."""
import importlib.util
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIZE = r"(\d+(?:\.\d+)?[mMgG])"
NAMED = {
    "memory": [rf"--memory {SIZE}\b", rf"\b{SIZE} memory\b"],
    "pids": [r"--pids (\d+)\b", r"\b(\d+) processes\b"],
    "tmp": [rf"/tmp of {SIZE}\b", rf"\b{SIZE} /tmp\b", rf"--tmp {SIZE}\b"],
}
BARE = {"memory": r"--memory\b(?! \d)", "pids": r"--pids\b(?! \d)", "tmp": r"--tmp\b(?![\w-]| \d)"}


def mib(value):
    number, unit = float(value[:-1]), value[-1].lower()
    return number * (1024 if unit == "g" else 1)


def prose(entry):
    return " ".join(str(part) for part in (entry.get("description"), entry.get("notes"),
                                           (entry.get("tor") or {}).get("note") if isinstance(entry.get("tor"), dict)
                                           else None) if part)


def named(text):
    """{key: [values named as needed]} (an empty list: the option named without a value)."""
    found = {}
    for key, patterns in NAMED.items():
        for pattern in patterns:
            for match in re.finditer(pattern, text):
                if re.search(r"default[^:.;]{0,30}$", text[max(0, match.start() - 40):match.start()]):
                    continue  # ("within the default 512 MiB and 128 processes": sandbox-ai's, not a need)
                found.setdefault(key, []).append(match.group(1))
        if re.search(BARE[key], text):
            found.setdefault(key, [])
    return found


def smoke_limits(name):
    spec = importlib.util.spec_from_file_location("smoke_test_for_limits_named", ROOT / "scripts" / "smoke_test.py")
    smoke = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke)
    path = ROOT / "servers" / name / "smoke.json"
    return smoke.limits(json.loads(path.read_text(encoding="utf-8"))) if path.is_file() else {}


SERVERS = sorted(path.parent.name for path in (ROOT / "servers").glob("*/server.json"))


class LimitsNamed(unittest.TestCase):
    """unittest, not pytest: CI runs `python3 -m unittest discover -s tests` without pytest installed."""

    def test_the_limits_its_text_names_are_machine_readable(self):
        for name in SERVERS:
            with self.subTest(server=name):
                entry = json.loads((ROOT / "servers" / name / "server.json").read_text(encoding="utf-8"))
                wanted = named(prose(entry))
                if not wanted:
                    continue
                limits = smoke_limits(name)
                for key, values in wanted.items():
                    self.assertIn(key, limits, f"servers/{name}: its text names its {key} "
                                               f"({', '.join(values) or 'without a value'}) but smoke.json sets none: "
                                               f"add \"{key}\" there (it becomes rootfs.json's limits)")
                    if not values:
                        continue
                    least = min(values, key=lambda v, key=key: mib(v) if key != "pids" else int(v))
                    given = limits[key]
                    if key == "pids":
                        self.assertGreaterEqual(int(given), int(least),
                                                f"servers/{name}: pids {given} is below the {least} its text needs")
                    else:
                        self.assertGreaterEqual(mib(given), mib(least),
                                                f"servers/{name}: {key} {given} is below the {least} its text needs")

    def test_rootfs_json_publishes_what_smoke_json_sets(self):
        """rootfs.json (signed, beside catalog.json) is what sandbox-ai reads: it carries each server's limits as its
        smoke.json sets them (scripts/make_catalog.py writes it; --check fails when it is not current)."""
        published = json.loads((ROOT / "rootfs.json").read_text(encoding="utf-8")).get("limits") or {}
        digests = json.loads((ROOT / "digests.json").read_text(encoding="utf-8")).get("images") or {}
        for name in SERVERS:
            limits = smoke_limits(name)
            if limits and digests.get(name):
                self.assertEqual(published.get(name), limits, f"rootfs.json: {name}'s limits are not smoke.json's")

    def test_the_rule_reads_the_ways_the_texts_say_it(self):
        self.assertEqual(named("Add it with --network full --memory 2g --pids 512 (Chromium ...) and a /tmp of 768m."),
                         {"memory": ["2g"], "pids": ["512"], "tmp": ["768m"]})
        self.assertEqual(named("Needs more than the default limits: 2g memory, 256 processes and a 512m /tmp; a large "
                               "app wants --memory 4g --tmp 1g"),
                         {"memory": ["4g", "2g"], "pids": ["256"], "tmp": ["512m", "1g"]})
        self.assertEqual(named("does not start within the default 512 MiB and 128 processes"), {})
        self.assertEqual(named("A large binary can exceed the container memory (--memory)."), {"memory": []})
        self.assertEqual(named("podman run --tmpfs=/tmp:rw,size=64m IMAGE"), {})


if __name__ == "__main__":
    unittest.main()
