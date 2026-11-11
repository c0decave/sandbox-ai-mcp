#!/usr/bin/env python3
"""Sign catalog.json and rootfs.json: the statement that every published server of this catalog works with
sandbox-ai, under Podman and under Bubblewrap.

    scripts/sign_catalog.py --key ~/.config/sandbox-ai/mcp-signing-key --reports DIR
    scripts/sign_catalog.py --verify --signers /path/to/sandbox-ai/sandbox/mcp-signers

Before it signs, for every entry with a digest it requires, in DIR or a folder below it (the "catalog" artifact
of the build workflow keeps them in ci-digests/; `gh run download RUN -n catalog -D DIR`):

  smoke-<name>-sandbox-ai-podman.json   ok, runner sandbox-ai-podman, image IMAGE@DIGEST of the catalog
  smoke-<name>-sandbox-ai-bwrap.json    ok, runner sandbox-ai-bwrap, image IMAGE@DIGEST of the catalog,
                                        rootfs_sha256 of rootfs.json

each with tools.json matched, with at least one passed tool call (a handshake and a tool list say nothing about
the tool), run with no more network than the entry declares, and with catalog.json and rootfs.json current
(scripts/make_catalog.py --check; no rootfs for a server the catalog does not publish). A tool call skipped
because the upstream service rate-limited it (scripts/smoke_test.py, "upstream_limited") does not fail a report
but does not count as that call either; it is named before signing. Then it
writes catalog.json.sig and rootfs.json.sig: SSH signatures (ssh-keygen -Y sign) in the namespace
sandbox-ai-mcp, which sandbox-ai checks against sandbox/mcp-signers before `sandbox-ai mcp add` takes an entry.
The key never leaves your machine: sign after the CI run, then commit catalog.json, rootfs.json and both .sig.
Standard library only (ssh-keygen, OpenSSH 8.1 or newer).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAMESPACE = "sandbox-ai-mcp"
PRINCIPAL = "mcp@sandbox-ai"
RUNNERS = ("sandbox-ai-podman", "sandbox-ai-bwrap")
#: How much network a run had. A report may have had less than the entry declares (searxng's smoke
#: runs without network), never more. "allowlist" counts as "full": sandbox-ai has no per-server
#: egress proxy, so it gives an allowlist entry the full network, which is what CI tests it with.
NETWORK_ORDER = {"none": 0, "allowlist": 1, "full": 1}


def problems_of(root: Path, reports: Path, allow_pending: bool = True) -> list[str]:
    """What stands in the way of signing: a stale catalog, a server without its passed reports (Podman always,
    Bubblewrap where rootfs.json has its rootfs)."""
    problems = []
    check = subprocess.run([sys.executable, str(root / "scripts/make_catalog.py"), "--root", str(root), "--check",
                            *(["--allow-pending"] if allow_pending else [])], capture_output=True, text=True)
    if check.returncode != 0:
        problems.append("the catalog is not current: " + (check.stderr or check.stdout).strip())
    catalog = json.loads((root / "catalog.json").read_text(encoding="utf-8"))
    rootfs = json.loads((root / "rootfs.json").read_text(encoding="utf-8")).get("rootfs", {})
    published = [e for e in catalog.get("entries", []) if e.get("digest")]
    if not published:
        problems.append("no entry has a digest yet: nothing to vouch for")
    if not reports.is_dir():
        problems.append(f"{reports}: not a folder of smoke reports")
        return problems
    for entry in published:
        name = entry["name"]
        problems.extend(server_problems(reports, name, f"{entry['image']}@{entry['digest']}",
                                        (rootfs.get(name) or {}).get("sha256") if name in rootfs else None,
                                        entry.get("network")))
    stale = sorted(set(rootfs) - {e["name"] for e in published})
    if stale:
        problems.append(f"rootfs.json pins a rootfs for {', '.join(stale)}, which the catalog does not "
                        "publish: run scripts/make_catalog.py")
    return problems


def find_report(reports: Path, name: str, runner: str) -> tuple[dict | None, str | None]:
    """(the RUNNER report of NAME under REPORTS, None) or (None, why there is no usable one)."""
    wanted_name = f"smoke-{name}-{runner}.json"
    found = sorted(reports.rglob(wanted_name))
    if len(found) > 1:
        return None, f"{name}: {wanted_name} is there {len(found)} times under {reports} (one CI run only)"
    try:
        report = json.loads(found[0].read_text(encoding="utf-8"))
    except (IndexError, OSError, ValueError):
        return None, f"{name}: no {wanted_name} under {reports}"
    if not isinstance(report, dict) or report.get("runner") != runner or report.get("name") != name:
        return None, f"{name}: {wanted_name} is not the {runner} report of {name}"
    return report, None


def server_problems(reports: Path, name: str, image: str, rootfs_sha256: str | None, network) -> list[str]:
    """Why NAME, published as IMAGE (IMAGE@DIGEST) with network NETWORK, may not be vouched for: its Podman report,
    and its Bubblewrap report for the rootfs ROOTFS_SHA256 when it has one (None: Podman alone), must have passed
    under REPORTS for exactly these. Shared with scripts/ci_results.py, which picks a CI run's servers by it."""
    problems = []
    # Bubblewrap is vouched for only where rootfs.json offers that form: a server whose Bubblewrap smoke test
    # failed is published for Podman alone (its rootfs left out by the build), never signed for Bubblewrap.
    for runner in (r for r in RUNNERS if r != "sandbox-ai-bwrap" or rootfs_sha256 is not None):
        report, problem = find_report(reports, name, runner)
        checks = report.get("checks", []) if report else []
        calls = [c for c in checks if isinstance(c, dict) and str(c.get("check", "")).startswith("tools/call ")]
        if problem:
            problems.append(problem)
        elif not report.get("ok") or not all(isinstance(c, dict) and c.get("ok") for c in checks):
            failed = [c.get("check") for c in checks if not c.get("ok")]
            problems.append(f"{name}: {runner} failed ({', '.join(map(str, failed)) or report.get('exception')})")
        elif any(c.get("skipped") and c not in calls for c in checks):
            problems.append(f"{name}: {runner} skipped a check other than a tool call")
        elif not any(c.get("check") == "tools.json" and c.get("ok") for c in checks):
            problems.append(f"{name}: {runner} did not compare tools/list with tools.json")
        elif not any(c.get("ok") and not c.get("skipped") for c in calls):
            # A handshake and a tool list say nothing about the tool: the signature vouches for a server that ran
            # at least one call of its smoke spec (a call skipped for an upstream rate limit does not count).
            problems.append(f"{name}: {runner} made no tool call (only initialize and tools/list): "
                            f"servers/{name}/smoke.json must call the tool")
        elif NETWORK_ORDER.get(str(report.get("network")), len(NETWORK_ORDER)) > NETWORK_ORDER.get(network, 0):
            problems.append(f"{name}: the {runner} report ran it with network {report.get('network')}, "
                            f"the entry says {network}: a server is never vouched for with "
                            "more network than it declares")
        elif report.get("image") != image:
            problems.append(f"{name}: the {runner} report is of {report.get('image')}, the catalog pins {image}")
        elif runner == "sandbox-ai-bwrap":
            if not rootfs_sha256:
                problems.append(f"{name}: rootfs.json has no rootfs for it")
            elif report.get("rootfs_sha256") != rootfs_sha256:
                problems.append(f"{name}: the bwrap report is of rootfs {report.get('rootfs_sha256')}, "
                                f"rootfs.json says {rootfs_sha256}")
    return problems


def skipped_calls(reports: Path, names) -> list[str]:
    """The tool calls of NAMES' reports that were skipped because the upstream service rate-limited them (in passed
    reports; said before signing, never hidden)."""
    notes = []
    for name in names:
        for runner in RUNNERS:
            report, _ = find_report(reports, name, runner)
            for check in (report or {}).get("checks", []):
                if isinstance(check, dict) and check.get("skipped"):
                    notes.append(f"{name}: {runner}: {check.get('check')} skipped ({check['skipped']})")
    return notes


def sign(path: Path, key: str) -> Path:
    result = subprocess.run(["ssh-keygen", "-Y", "sign", "-f", key, "-n", NAMESPACE], input=path.read_bytes(),
                            stdout=subprocess.PIPE)
    if result.returncode != 0 or b"BEGIN SSH SIGNATURE" not in result.stdout:
        raise RuntimeError(f"ssh-keygen -Y sign -f {key} failed")
    signature = path.with_name(path.name + ".sig")
    signature.write_bytes(result.stdout)
    return signature


def verify(path: Path, signers: Path) -> bool:
    signature = path.with_name(path.name + ".sig")
    if not signature.exists():
        print(f"{signature.name}: missing", file=sys.stderr)
        return False
    with tempfile.TemporaryDirectory() as tmp:
        allowed = Path(tmp, "allowed_signers")
        allowed.write_text("".join(line + "\n" for line in signers.read_text().splitlines()
                                   if line.strip() and not line.startswith("#")))
        result = subprocess.run(["ssh-keygen", "-Y", "verify", "-f", str(allowed), "-I", PRINCIPAL, "-n", NAMESPACE,
                                 "-s", str(signature)], input=path.read_bytes(), capture_output=True)
    print(f"{path.name}: " + ("good" if result.returncode == 0 else (result.stderr or result.stdout).decode().strip()))
    return result.returncode == 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--key", help="the private key (or the .pub of a key in ssh-agent)")
    parser.add_argument("--reports", type=Path, help="the smoke reports of the CI run")
    parser.add_argument("--verify", action="store_true", help="check the signatures instead")
    parser.add_argument("--signers", type=Path, help="with --verify: sandbox-ai's sandbox/mcp-signers")
    opts = parser.parse_args(argv)
    root = opts.root.resolve()
    files = [root / "catalog.json", root / "rootfs.json"]
    if opts.verify:
        if not opts.signers:
            parser.error("--verify needs --signers")
        results = [verify(path, opts.signers) for path in files]  # each file reported, not only the first bad one
        return 0 if all(results) else 1
    if not (opts.key and opts.reports):
        parser.error("--key and --reports are needed")
    missing = [path.name for path in files if not path.is_file()]
    if missing:
        print(f"refused: {', '.join(missing)} missing under {root}", file=sys.stderr)
        return 1
    problems = problems_of(root, opts.reports)
    for problem in problems:
        print(f"refused: {problem}", file=sys.stderr)
    if problems:
        print("nothing signed", file=sys.stderr)
        return 1
    catalog = json.loads((root / "catalog.json").read_text(encoding="utf-8"))
    for note in skipped_calls(opts.reports, [e["name"] for e in catalog.get("entries", []) if e.get("digest")]):
        print(f"note: {note}: the server reached the service, which refused; its other calls passed")
    for path in files:
        print(f"signed {sign(path, opts.key).name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
