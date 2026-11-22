#!/usr/bin/env python3
"""Smoke-test a built toolchain as sandbox-ai mounts it: compile and run a hello world, under Podman or Bubblewrap.

    scripts/toolchain_smoke.py --sandbox-ai DIR --runner sandbox-ai-podman|sandbox-ai-bwrap \\
        --meta out/toolchain-NAME-ARCH.json --archive out/toolchain-NAME-ARCH.tar.xz \\
        [--with out/toolchain-OTHER-ARCH.json ...] --report smoke-NAME-ARCH-RUNNER.json

Everything between the archive and the mount is sandbox-ai's own code (DIR/sandbox/toolchains.py): `toolchain add`
from a catalog of this run (the SHA-256 checked, the archive unpacked without trusting it into a store of this
test), the start's plan (start_plan: what the toolchain needs against this runner - under Bubblewrap this machine,
under Podman what sandbox-ai's images have), the session folder (write_session: the wrappers, env.sh) and the mounts
(start_mounts), read-only as the launcher mounts them. --with: the toolchains this one requires, built in the same
job. Then the "smoke" steps of the toolchain run in that sandbox, without network, HOME and the working folder
writable: each step's files are written, its command runs with sh, and its output must contain "expect".

The report says which archive (sha256) passed with which sandbox-ai; scripts/sign_toolchains.py signs only entries
with both reports. Standard library only (podman or bwrap).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RUNNERS = ("sandbox-ai-podman", "sandbox-ai-bwrap")
# What sandbox-ai's agent images are built on (sandbox/Containerfile.*: NODE_IMAGE).
IMAGE = "docker.io/library/node:lts-bookworm-slim"
PATH = "/usr/local/bin:/usr/bin:/bin:/usr/local/sbin:/usr/sbin:/sbin"
STEP_SECONDS = 900


def sandbox_ai(directory: Path):
    path = directory / "sandbox" / "toolchains.py"
    if not path.is_file():
        raise SystemExit(f"{directory} has no sandbox/toolchains.py: a sandbox-ai with toolchains is needed "
                         "(repository variable SANDBOX_AI_REF)")
    spec = importlib.util.spec_from_file_location("sandbox_ai_toolchains_for_smoke", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sandbox_command(runner: str, t, entries, session: Path, work: Path, image: str, script: str) -> list[str]:
    """The sandbox as the launcher mounts toolchains: /opt/toolchains (the session's folder) and each tree on it,
    read-only; no network; the wrappers first on PATH, the toolchains' variables as a start sets them."""
    mounts = [(session, t.MOUNT), *((str(source), target) for source, target in t.start_mounts(entries))]
    env = {"PATH": f"{t.BIN}:{PATH}", "HOME": "/work/.home", "LANG": "C.UTF-8", "BASH_ENV": t.ENV_FILE,
           **t.environment(entries)}
    env = {key: value.replace(t.SANDBOX_HOME + "/", "/work/.home/") for key, value in env.items()}
    if runner == "sandbox-ai-podman":
        command = ["podman", "run", "--rm", "--network=none", "--read-only", "--cap-drop=ALL",
                   "--security-opt=no-new-privileges", "--user=0:0", "--tmpfs=/tmp:rw,nosuid,nodev",
                   "--workdir=/work", "--mount", f"type=bind,src={work},dst=/work,rw,nodev,nosuid"]
        for source, target in mounts:
            command += ["--mount", f"type=bind,src={source},dst={target},ro,nodev,nosuid"]
        for key, value in env.items():
            command += ["--env", f"{key}={value}"]
        return [*command, "--entrypoint=/bin/sh", image, "-c", script]
    command = ["bwrap", "--unshare-all", "--die-with-parent", "--clearenv", "--ro-bind", "/usr", "/usr"]
    for path in ("/bin", "/sbin", "/lib", "/lib64", "/lib32"):
        if os.path.islink(path):
            command += ["--symlink", os.readlink(path), path]
        elif os.path.exists(path):
            command += ["--ro-bind", path, path]
    command += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--dir", "/etc"]
    for path in ("/etc/ld.so.cache", "/etc/alternatives", "/etc/passwd", "/etc/group"):
        if os.path.exists(path):
            command += ["--ro-bind", path, path]
    for source, target in mounts:
        command += ["--ro-bind", str(source), target]
    command += ["--bind", str(work), "/work", "--chdir", "/work"]
    for key, value in env.items():
        command += ["--setenv", key, value]
    return [*command, "/bin/sh", "-c", script]


def run_smoke(opts, run=subprocess.run) -> dict:
    t = sandbox_ai(opts.sandbox_ai)
    meta = json.loads(opts.meta.read_text(encoding="utf-8"))
    entry = meta["entry"]
    report = {"name": entry["name"], "version": entry["version"], "arch": entry["arch"], "runner": opts.runner,
              "sha256": entry["sha256"], "ok": False, "checks": []}
    with tempfile.TemporaryDirectory(prefix="toolchain-smoke-") as tmp:
        tmp = Path(tmp)
        os.environ["XDG_DATA_HOME"] = str(tmp / "data")
        try:
            # A catalog of this run: the entries with their archives as local files (the SHA-256 still decides).
            others = [json.loads(path.read_text(encoding="utf-8"))["entry"] for path in opts.requires]
            archives = {entry["name"]: opts.archive,
                        **{other["name"]: path.with_name(path.name[:-len(".json")] + ".tar.xz")
                           for other, path in zip(others, opts.requires)}}
            catalog = tmp / "toolchains.json"
            catalog.write_text(json.dumps({"schema": t.SCHEMA, "version": 1, "toolchains": [
                {**item, "url": str(archives[item["name"]].resolve())} for item in (entry, *others)]}))
            t.add(entry["name"], str(catalog), unsigned=True, out=lambda line: print(line, flush=True))
            backend = "podman" if opts.runner == "sandbox-ai-podman" else "bwrap"
            plan = t.start_plan([entry["name"]], backend, offline=True)
            session, work = tmp / "session", tmp / "work"
            for folder in (session, work, work / ".home"):
                folder.mkdir()
            notes = t.write_session(session, plan["entries"])
            report["checks"].append({"check": "mounted as sandbox-ai mounts it", "ok": True,
                                     "toolchains": [f"{e['name']} {e['version']}" for e in plan["entries"]],
                                     "notes": notes})
            for step in meta.get("smoke") or []:
                for name, text in (step.get("files") or {}).items():
                    (work / name).write_text(text, encoding="utf-8")
                command = sandbox_command(opts.runner, t, plan["entries"], session, work, opts.image, step["run"])
                try:
                    result = run(command, capture_output=True, text=True, timeout=STEP_SECONDS,
                                 stdin=subprocess.DEVNULL)
                    output, status = (result.stdout + result.stderr), result.returncode
                except subprocess.TimeoutExpired:
                    output, status = f"no answer within {STEP_SECONDS} s", 124
                ok = status == 0 and step["expect"] in output
                report["checks"].append({"check": f"run {step['run']}", "ok": ok, "status": status,
                                         "expect": step["expect"], "output": output[-1500:]})
                print(f"{'ok' if ok else 'FAILED'}: {step['run']}\n{output[-1500:] if not ok else ''}", flush=True)
            steps = [check for check in report["checks"] if check["check"].startswith("run ")]
            report["ok"] = bool(steps) and all(check["ok"] for check in report["checks"])
        except (ValueError, OSError, KeyError) as exc:
            report["checks"].append({"check": "mounted as sandbox-ai mounts it", "ok": False, "output": str(exc)})
            print(f"FAILED: {exc}", flush=True)
        finally:
            for directory, dirs, _ in os.walk(tmp):  # the store's trees are read-only
                for name in dirs:
                    if not os.path.islink(os.path.join(directory, name)):
                        os.chmod(os.path.join(directory, name), 0o700)
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--sandbox-ai", type=Path, required=True, help="a sandbox-ai checkout")
    parser.add_argument("--runner", choices=RUNNERS, required=True)
    parser.add_argument("--meta", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--with", dest="requires", type=Path, action="append", default=[],
                        help="the meta file of a toolchain this one requires (its archive beside it)")
    parser.add_argument("--image", default=IMAGE, help="Podman: the image the sandbox runs (the agent images' base)")
    parser.add_argument("--report", type=Path, required=True)
    opts = parser.parse_args(argv)
    if not shutil.which("podman" if opts.runner == "sandbox-ai-podman" else "bwrap"):
        raise SystemExit(f"{opts.runner}: its engine is not installed")
    report = run_smoke(opts)
    try:
        report["sandbox_ai"] = subprocess.run(["git", "-C", str(opts.sandbox_ai), "rev-parse", "HEAD"],
                                              capture_output=True, text=True).stdout.strip() or None
    except OSError:
        report["sandbox_ai"] = None
    opts.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if not report["ok"] and os.environ.get("GITHUB_ACTIONS") == "true":
        failed = "; ".join(str(check.get("check")) for check in report["checks"] if not check["ok"])[:300]
        print(f"::error title={report['name']} {report['arch']} failed under {opts.runner}::{failed}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
