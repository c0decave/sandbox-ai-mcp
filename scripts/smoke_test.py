#!/usr/bin/env python3
"""Start a hub image exactly the way axross starts a catalog server and talk MCP to it.

The container gets axross's run line (core/mcp_install.py, ``RUN_FLAGS`` and
``run_command``): ``--rm -i --init --pull=never --log-driver=none --cap-drop=ALL
--security-opt=no-new-privileges --read-only --tmpfs=/tmp:rw,nosuid,nodev,noexec,size=64m,notmpcopyup
--pids-limit=128 --memory=512m``, the environment through a pipe (``--env-file=/dev/fd/N``),
``--network=none``, the full network, or axross's allowlist network (pasta bound to the
host's loopback, its only way out axross's CONNECT proxy, ``core.mcp_egress``; that needs
``--axross DIR`` to run the very proxy axross runs), and folders as
``--volume=HOST:TARGET:ro|rw`` with ``--user=0:0``. The spec's ``env`` (and, for the
allowlist, the proxy variables axross sets) go through the pipe as axross sends them.

Then: ``initialize``, ``notifications/initialized``, ``tools/list`` and every call of
the spec (``servers/<name>/smoke.json``), each checked for an expected text. With
``--tools-file servers/<name>/tools.json`` the offered tools must be exactly the recorded
ones, so a changed tool list fails.

    scripts/smoke_test.py --image IMAGE --spec servers/radare2/smoke.json --var FIXTURES=/abs/dir

``${NAME}`` in the spec is replaced by ``--var NAME=VALUE`` (with ``--list-only`` a variable not
given is empty: the server must start and list its tools without its secrets). Exit status 0 when
every check passed. Standard library only.

A mount may be ``{"target": "/data", "fresh": true, "writable": true}`` instead of naming a host folder: the run then
gets a new empty folder of its own (removed afterwards), for a server that keeps its data in a folder the user mounts
writable (a note, a memory) and must write, search and read it back in its smoke run without touching anything else.

A spec may raise the limits for a server that needs more (``"memory": "2g"``, ``"pids": 512``, what the
server's catalog notes tell users to add with ``sandbox-ai mcp add --memory --pids``): the run line then
has these instead of 512m and 128, and the sandbox-ai runners put them into the definition, as
``mcp add`` does.

A call may name the answers of an upstream service that refuses for its own reasons, a rate limit
(``"upstream_limited": ["DuckDuckGo answered HTTP 202", ...]``, texts the server only writes when the
service did answer, with that status). Such a call is retried ``--upstream-retries`` times with
exponential backoff (``--upstream-backoff`` seconds, doubled each time); still limited, the check is
marked ``"skipped": "upstream rate-limited"`` and does not fail the run: the server started, offered
its recorded tools, reached the service through the sandbox's network and turned its refusal into
the documented error. Every other check (the refused calls) must still pass, and a call with
``expect_error`` cannot be skipped. On GitHub Actions a failure is an error annotation and a skipped
call a warning, which the API returns without the job log.

``--runner sandbox-ai-podman`` and ``--runner sandbox-ai-bwrap`` (with ``--sandbox-ai DIR``, a
checkout) start the server the way sandbox-ai does instead: its own ``mcp.image_command`` for
the image, or its ``mcp_rootfs`` for the rootfs archive (``--rootfs FILE --rootfs-meta FILE``:
checked against the SHA-256, unpacked, run per connection with bwrap). ``--report FILE`` keeps
the report; scripts/sign_catalog.py signs a catalog only when both reports of every server
passed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import selectors
import shutil
import subprocess
import sys
import tempfile
import time

#: Mirrors axross core/mcp_install.py RUN_FLAGS (checked against it when axross is at hand).
RUN_FLAGS = (
    "--rm", "-i", "--init", "--pull=never", "--log-driver=none",
    "--cap-drop=ALL", "--security-opt=no-new-privileges", "--read-only",
    "--tmpfs=/tmp:rw,nosuid,nodev,noexec,size=64m,notmpcopyup", "--pids-limit=128", "--memory=512m",
)
#: Mirrors axross core/mcp_install.py ALLOWLIST_NETWORK (the token is the proxy's port).
ALLOWLIST_NETWORK = ("--network=pasta:--no-map-gw,--no-udp,--no-icmp,--ipv4-only,"
                     "-o,127.0.0.1,-T,AXROSS_EGRESS_PORT")
PROTOCOL_VERSION = "2025-06-18"
#: sandbox-ai's own patterns for a definition's limits (sandbox/mcp.py validated_image).
MEMORY = re.compile(r"^[1-9][0-9]{0,5}[mg]$")


def run_command(name: str, image: str, *, network: str = "none", mounts=(), args=(),
                program: str = "podman", env_fd: int | str = "AXROSS_ENV_FD",
                run_id: str = "AXROSS_RUN_ID", egress_port: int | str = "AXROSS_EGRESS_PORT",
                memory: str | None = None, pids: int | None = None) -> list[str]:
    """The ``podman run`` line axross builds for a container server (*memory* and *pids* replace its limits)."""
    flags = tuple(f"--memory={memory}" if memory and f.startswith("--memory=") else
                  f"--pids-limit={pids}" if pids and f.startswith("--pids-limit=") else f for f in RUN_FLAGS)
    if os.path.basename(program) == "docker":
        # notmpcopyup is podman's: docker refuses it ("invalid tmpfs option"),
        # and its tmpfs never copies the image's /tmp up anyway - same /tmp.
        flags = tuple(f.replace(",notmpcopyup", "") for f in flags)
    argv = [program, "run", *flags, f"--name=sandbox-ai-mcp-{name}-{run_id}",
            f"--label=io.axross.mcp={name}", f"--env-file=/dev/fd/{env_fd}"]
    if network == "none":
        argv.append("--network=none")
    elif network == "allowlist":
        argv.append(ALLOWLIST_NETWORK.replace("AXROSS_EGRESS_PORT", str(egress_port)))
    elif network != "full":
        raise ValueError("network: none, allowlist or full")
    if mounts:
        argv.append("--user=0:0")
        for host, target, writable in mounts:
            argv.append(f"--volume={host}:{target}:{'rw' if writable else 'ro'}")
    return [*argv, image, *args]


def env_file(env: dict, proxy_port: int | None) -> bytes:
    """The ``NAME=value`` lines axross writes to the pipe (core/mcp_client.py _env_file)."""
    values = dict(env)
    if proxy_port is not None:
        proxy = f"http://127.0.0.1:{proxy_port}"
        for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
            values[name] = proxy
        values["NO_PROXY"] = values["no_proxy"] = ""
    for name, value in values.items():
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$", name) or any(c in value for c in "\n\r\x00"):
            raise ValueError(f"env: {name!r} is not a single-line variable")
    return "".join(f"{k}={v}\n" for k, v in values.items()).encode()


def start_proxy(hosts: list[str], axross_dir: str):
    """axross's own CONNECT proxy for *hosts* (core.mcp_egress.EgressProxy)."""
    sys.path.insert(0, axross_dir)
    from core.mcp_egress import EgressProxy  # axross

    proxy = EgressProxy(hosts)
    proxy.start()
    return proxy


def substitute(value, variables: dict[str, str], missing: str | None = None):
    """*value* with ``${NAME}`` replaced by ``variables[NAME]``; a NAME not given is *missing*, or refused when
    *missing* is None."""
    if isinstance(value, str):
        def one(match):
            key = match.group(1)
            if key not in variables:
                if missing is not None:
                    return missing
                raise KeyError(f"the spec uses ${{{key}}}: pass --var {key}=VALUE")
            return variables[key]
        return re.sub(r"\$\{([A-Z0-9_]+)\}", one, value)
    if isinstance(value, list):
        return [substitute(v, variables, missing) for v in value]
    if isinstance(value, dict):
        return {k: substitute(v, variables, missing) for k, v in value.items()}
    return value


def upstream_limits(spec: dict) -> None:
    """ValueError unless every call's ``upstream_limited`` is a list of non-empty texts, on a call that expects a
    result (a refused call proves the server's own checks and is never skipped)."""
    for call in spec.get("calls", []):
        markers = call.get("upstream_limited")
        if markers is None:
            continue
        if not isinstance(markers, list) or not markers or not all(isinstance(m, str) and m.strip() for m in markers):
            raise ValueError(f"{call.get('tool')}: upstream_limited must be a list of texts")
        if call.get("expect_error"):
            raise ValueError(f"{call.get('tool')}: a call with expect_error cannot be upstream_limited")


def limits(spec: dict) -> dict:
    """``{"memory": ..., "pids": ...}`` of the spec (only those it sets), ValueError unless sandbox-ai would take
    them in a definition."""
    found = {}
    if "memory" in spec:
        if not isinstance(spec["memory"], str) or not MEMORY.match(spec["memory"]):
            raise ValueError("memory must be like 512m or 2g")
        found["memory"] = spec["memory"]
    if "pids" in spec:
        pids = spec["pids"]
        if isinstance(pids, bool) or not isinstance(pids, int) or not 16 <= pids <= 4096:
            raise ValueError("pids must be 16-4096")
        found["pids"] = pids
    return found


def spec_mounts(spec: dict, variables: dict[str, str], fresh: list[str]) -> list[tuple[str, str, bool]]:
    """(host, target, writable) of the spec's mounts; a ``"fresh": true`` mount gets a new empty folder, appended to
    *fresh* (the caller removes them). ValueError for a mount that names both or neither."""
    mounts = []
    for mount in spec.get("mounts", []):
        if mount.get("fresh"):
            if "host" in mount or not mount.get("writable"):
                raise ValueError(f"mount {mount.get('target')}: a fresh folder has no host and is writable")
            host = tempfile.mkdtemp(prefix=f"smoke-{spec.get('name', 'server')}-")
            fresh.append(host)
        elif "host" in mount:
            host = substitute(mount["host"], variables)
        else:
            raise ValueError(f"mount {mount.get('target')}: give a host folder or fresh: true")
        mounts.append((host, mount["target"], bool(mount.get("writable"))))
    return mounts


def failure_hint(runner: str, stderr: str) -> str | None:
    """What a known failure of the run line means."""
    if runner == "sandbox-ai-bwrap" and "usage: bwrap" in stderr:
        return ("bwrap printed its usage: it got no command. sandbox-ai's mcp_rootfs passes the command after '--' "
                "inside --args FD, where bwrap (every version) does not take it; the command must follow --args on "
                "bwrap's own command line. Point SANDBOX_AI_REF at a sandbox-ai with that fix.")
    return None


def escape_annotation(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def skipped_annotations(report: dict, retries: int) -> list[str]:
    """A GitHub Actions warning for each real call skipped because its upstream service rate-limited it."""
    return [f"::warning title=smoke {report.get('name')} ({report.get('runner')}) upstream rate-limited::"
            + escape_annotation(f"{check}: skipped after {retries} retries (the service answered and refused); "
                                "the other calls and tools/list passed")
            for check in report.get("skipped", [])]


def load_module(path, name):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def annotation(report: dict) -> str:
    """A GitHub Actions error annotation for a failed smoke run: the exception, the failed checks and the end of
    stderr, so the reason can be read from the check run without the job log."""
    lines = [f"runner {report.get('runner')}, image {report.get('image')}"]
    if report.get("exception"):
        lines.append(f"exception: {report['exception']}")
    if report.get("hint"):
        lines.append(f"hint: {report['hint']}")
    for check in report.get("checks", []):
        if not check.get("ok"):
            lines.append(f"failed: {check.get('check')} expected {check.get('expect', check.get('missing'))!r}, "
                         f"got {str(check.get('text', ''))[:300]!r}")
    tail = str(report.get("stderr_tail") or "").strip()
    if tail:
        lines.append("stderr: " + tail[-1500:])
    return f"::error title=smoke {report.get('name')} ({report.get('runner')})::{escape_annotation(chr(10).join(lines))}"


def sandbox_ai_argv(runner: str, checkout: str, image: str, network: str, mounts, env: dict,
                    rootfs: str | None = None, meta: dict | None = None,
                    resources: dict | None = None) -> tuple[list[str], dict, dict]:
    """(argv, environment, facts) of a server started as sandbox-ai starts it: the image with sandbox-ai's own
    run line (mcp.image_command), or the rootfs archive checked, unpacked and run with bwrap (mcp_rootfs)."""
    import tempfile
    state = tempfile.mkdtemp(prefix="smoke-sandbox-ai-")
    if runner != "sandbox-ai-podman":
        # the rootfs store of the bwrap runner lives below XDG_DATA_HOME: a fresh one per smoke run. Never for
        # Podman: rootless podman keeps its images below XDG_DATA_HOME too, and a fresh one would not hold the image
        # the workflow has just pulled ("image not known").
        os.environ.setdefault("XDG_DATA_HOME", os.path.join(state, "data"))
    mcp = load_module(os.path.join(checkout, "sandbox", "mcp.py"), "sandbox_ai_mcp_for_smoke")
    definition = {"network": "full" if network in ("full", "allowlist") else "none", "env": sorted(env),
                  "mounts": [{"target": target, "host": host, "mode": "rw" if writable else "ro"}
                             for host, target, writable in mounts], **(resources or {})}
    environment = {**os.environ, **env}
    if runner == "sandbox-ai-podman":
        definition = mcp.validated_image({**definition, "image": image}, "smoke")
        return mcp.image_command(definition), environment, {"image": image}
    rootfs_module = mcp.rootfs_module()
    meta = meta or {}
    tree = rootfs_module.install(os.path.abspath(rootfs), meta["sha256"])
    definition = mcp.validated_image({**definition, "rootfs": {
        "path": str(tree), "sha256": meta["sha256"], "entrypoint": meta["entrypoint"],
        "user": meta.get("user", 65534), "workdir": meta.get("workdir", "/tmp"), "env": meta.get("env", {})}},
        "smoke")
    checked = os.path.join(state, "definition.json")
    with open(checked, "w", encoding="utf-8") as handle:
        json.dump(definition, handle)
    return rootfs_module.bwrap_command(checked, definition), environment, {"rootfs_sha256": meta["sha256"]}


class Session:
    def __init__(self, argv: list[str], env_fd: int | None, env: dict | None = None) -> None:
        self.proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, pass_fds=(env_fd,) if env_fd is not None else (),
                                     env=env)
        self.sel = selectors.DefaultSelector()
        self.sel.register(self.proc.stdout, selectors.EVENT_READ)
        self.buf = b""
        self.next_id = 1

    def send(self, message: dict) -> None:
        self.proc.stdin.write(json.dumps(message).encode() + b"\n")
        self.proc.stdin.flush()

    def request(self, method: str, params: dict, timeout: float) -> dict:
        ident = self.next_id
        self.next_id += 1
        self.send({"jsonrpc": "2.0", "id": ident, "method": method, "params": params})
        deadline = time.monotonic() + timeout
        while True:
            while b"\n" in self.buf:
                line, self.buf = self.buf.split(b"\n", 1)
                if not line.strip():
                    continue
                try:
                    message = json.loads(line)
                except ValueError:
                    raise RuntimeError(f"not JSON-RPC on stdout: {line[:200]!r}") from None
                if message.get("id") == ident and ("result" in message or "error" in message):
                    return message
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError(f"{method}: no answer within {timeout:g} s")
            if not self.sel.select(left):
                continue
            chunk = os.read(self.proc.stdout.fileno(), 65536)
            if not chunk:
                raise RuntimeError(f"{method}: the server closed stdout (exit {self.proc.poll()})")
            self.buf += chunk

    def close(self) -> str:
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
        return self.proc.stderr.read().decode("utf-8", "replace")


def result_text(message: dict) -> str:
    if "error" in message:
        return "JSON-RPC error: " + json.dumps(message["error"])
    content = message.get("result", {}).get("content") or []
    return "\n".join(c.get("text", "") for c in content if isinstance(c, dict))


def check_tools_file(report: dict, names: list[str], path: str) -> bool:
    """Whether tools/list offered exactly the tools of *path* (``{"tools": [...]}``)."""
    with open(path, encoding="utf-8") as handle:
        recorded = json.load(handle)["tools"]
    added = sorted(set(names) - set(recorded))
    gone = sorted(set(recorded) - set(names))
    report["checks"].append({"check": "tools.json", "ok": not added and not gone,
                             "not_recorded": added, "missing": gone})
    return not added and not gone


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--image", required=True, help="image reference or ID")
    parser.add_argument("--spec", required=True, help="servers/<name>/smoke.json")
    parser.add_argument("--var", action="append", default=[], help="NAME=VALUE for ${NAME}")
    parser.add_argument("--engine", default="podman", help="podman (default) or docker")
    parser.add_argument("--list-only", action="store_true",
                        help="initialize and tools/list only (no calls, no folders)")
    parser.add_argument("--print-argv", action="store_true")
    parser.add_argument("--runner", choices=["axross", "sandbox-ai-podman", "sandbox-ai-bwrap"], default="axross",
                        help="whose run line starts the server (default: axross's)")
    parser.add_argument("--sandbox-ai", help="a sandbox-ai checkout, for the sandbox-ai runners")
    parser.add_argument("--rootfs", help="the rootfs archive (sandbox-ai-bwrap)")
    parser.add_argument("--rootfs-meta", help="its rootfs-<name>.json: sha256, entrypoint, user, workdir, env")
    parser.add_argument("--report", help="write the report to this file as well")
    parser.add_argument("--axross", help="an axross checkout: its egress proxy for allowlist specs")
    parser.add_argument("--max-text", type=int, default=1500, help="result text shown per call")
    parser.add_argument("--tools-file", help="servers/<name>/tools.json: tools/list must offer "
                        "exactly these tools (a changed tool list fails)")
    parser.add_argument("--upstream-retries", type=int, default=3,
                        help="retries of a call whose upstream service is rate-limited (default 3)")
    parser.add_argument("--upstream-backoff", type=float, default=15.0,
                        help="seconds before the first retry, doubled for each next one (default 15)")
    opts = parser.parse_args(argv)

    variables = dict(v.split("=", 1) for v in opts.var)
    missing = "" if opts.list_only else None  # tools/list must work without the secrets
    with open(opts.spec, encoding="utf-8") as handle:
        spec = json.load(handle)
    upstream_limits(spec)
    resources = limits(spec)
    name = spec["name"]
    network = spec.get("network", "none")
    fresh: list[str] = []  # the empty folders of "fresh" mounts, removed at the end
    mounts = [] if opts.list_only else spec_mounts(spec, variables, fresh)
    if opts.list_only and network == "allowlist":
        network = "none"  # tools/list needs no network (and CI has no axross proxy)
    proxy = None
    if network == "allowlist":
        if opts.axross:
            proxy = start_proxy(spec.get("hosts", []), opts.axross)
        else:
            # Without axross's proxy the allowlist cannot be enforced here: the smoke test then checks
            # the server's behaviour with the full network (CI), not the allowlist itself.
            print("smoke: allowlist spec without --axross: using the full network", file=sys.stderr)
            network = "full"
    facts = {}
    if opts.runner == "axross":
        read_fd, write_fd = os.pipe()
        os.write(write_fd, env_file(substitute(spec.get("env", {}), variables, missing),
                                    proxy.port if proxy else None))
        os.close(write_fd)
        argv = run_command(f"smoke-{name}", opts.image, network=network, mounts=mounts,
                           args=spec.get("args", []), program=opts.engine, env_fd=read_fd,
                           run_id=secrets.token_hex(4), egress_port=proxy.port if proxy else "", **resources)
        environment = None
    else:
        if not opts.sandbox_ai:
            parser.error(f"--runner {opts.runner} needs --sandbox-ai DIR")
        meta = None
        if opts.runner == "sandbox-ai-bwrap":
            if not (opts.rootfs and opts.rootfs_meta):
                parser.error("--runner sandbox-ai-bwrap needs --rootfs and --rootfs-meta")
            with open(opts.rootfs_meta, encoding="utf-8") as handle:
                meta = json.load(handle)
        read_fd = None
        argv, environment, facts = sandbox_ai_argv(opts.runner, opts.sandbox_ai, opts.image, network, mounts,
                                                   substitute(spec.get("env", {}), variables, missing),
                                                   opts.rootfs, meta, resources)
    if opts.print_argv:
        print("argv:", json.dumps(argv))
    session = Session(argv, read_fd, environment)
    if read_fd is not None:
        os.close(read_fd)
    report = {"name": name, "image": opts.image, "network": network, "runner": opts.runner, **resources, **facts,
              "checks": [], "skipped": []}
    ok = True
    try:
        init = session.request("initialize", {
            "protocolVersion": PROTOCOL_VERSION, "capabilities": {},
            "clientInfo": {"name": "sandbox-ai-mcp-smoke", "version": "1"}},
            spec.get("start_timeout", 60))
        info = init.get("result", {}).get("serverInfo", {})
        report["server"] = info
        report["protocolVersion"] = init.get("result", {}).get("protocolVersion")
        session.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        tools = session.request("tools/list", {}, 60).get("result", {}).get("tools", [])
        names = [t.get("name") for t in tools]
        report["tools"] = names
        missing = [t for t in spec.get("expect_tools", []) if t not in names]
        report["checks"].append({"check": "tools/list", "ok": not missing, "missing": missing})
        ok &= not missing
        if opts.tools_file:
            ok &= check_tools_file(report, names, opts.tools_file)
        for call in [] if opts.list_only else spec.get("calls", []):
            arguments = substitute(call.get("arguments", {}), variables)
            expect = substitute(call.get("expect", ""), variables)
            markers = call.get("upstream_limited") or []
            started = time.monotonic()
            attempt = 0
            while True:
                attempt += 1
                answer = session.request("tools/call", {"name": call["tool"], "arguments": arguments},
                                         call.get("timeout", 120))
                text = result_text(answer)
                passed = expect in text and "error" not in answer
                if call.get("expect_error"):
                    passed = expect in text
                limited = None if passed or "error" in answer else next((m for m in markers if m in text), None)
                if limited is None or attempt > opts.upstream_retries:
                    break
                wait = opts.upstream_backoff * 2 ** (attempt - 1)
                print(f"smoke: {call['tool']}: upstream rate-limited ({limited}); retry {attempt} of "
                      f"{opts.upstream_retries} in {wait:g} s", file=sys.stderr, flush=True)
                time.sleep(wait)
            check = {"check": f"tools/call {call['tool']}", "arguments": arguments, "ok": passed,
                     "expect": expect, "seconds": round(time.monotonic() - started, 2), "attempts": attempt,
                     "text": text[: opts.max_text]}
            if limited is not None:
                # The service answered and refused (its status in the server's error): not this server's failure.
                check.update(ok=True, skipped="upstream rate-limited", upstream=limited)
                report["skipped"].append(check["check"])
            report["checks"].append(check)
            ok &= check["ok"]
    except Exception as exc:  # noqa: BLE001 - reported, not hidden
        ok = False
        report["exception"] = f"{type(exc).__name__}: {exc}"
    finally:
        stderr = session.close()
        report["stderr_tail"] = stderr[-3000:]
        if proxy is not None:
            proxy.close()
        for folder in fresh:
            # a root-run container (docker) may leave files the runner cannot remove: CI's runner is thrown away
            shutil.rmtree(folder, ignore_errors=True)
    report["ok"] = bool(ok)
    hint = None if ok else failure_hint(opts.runner, stderr)  # all of it: bwrap's usage is longer than the tail
    if hint:
        report["hint"] = hint
    print(json.dumps(report, indent=2))
    if os.environ.get("GITHUB_ACTIONS") == "true":
        for line in ([] if ok else [annotation(report)]) + skipped_annotations(report, opts.upstream_retries):
            print(line, flush=True)
    if opts.report:
        with open(opts.report, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
