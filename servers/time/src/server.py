"""time (mcp-server-time 2026.10.28, the official MCP reference server, the hash-pinned wheel in /opt/venv) as an MCP
server of sandbox-ai-mcp.

Upstream's two tools run unchanged - get_current_time (an IANA zone's current time, weekday, DST) and convert_time
(a wall-clock time HH:MM of today from one zone to another) - on upstream's own MCPServer (MCP Python SDK 2.3.0, the
reviewed lock of servers/osint-mcp). This file only starts them, with four changes:

- the local zone the tool descriptions name comes from LOCAL_TIMEZONE (an IANA name, e.g. Europe/Berlin; checked
  like upstream's --local-timezone) and else from tzlocal as upstream does, which in the container finds Etc/UTC;
  a bad LOCAL_TIMEZONE ends the server before the handshake with one line, as upstream's flag does;
- every zone argument is checked before upstream sees it: at most 64 characters of [A-Za-z0-9_+-] in up to four
  "/"-separated parts, so a model's long or odd text is refused with a short message (upstream echoes the whole
  value, and for a path-like value zoneinfo's error names a file of the container), and the time at most 16
  characters;
- every answer is bounded (MAX_ANSWER characters as sent; upstream's answers are a few hundred);
- the server advertises tools only (tools_only): the SDK announced resources and prompts with nothing behind them.

No network, no file written; the zone database is the pinned tzdata wheel (IANA 2026f).
"""
import asyncio
import functools
import os
import re
import sys

from mcp.server.mcpserver.exceptions import ToolError
from mcp_server_time import server as upstream

#: Characters of one answer at most (clients such as Claude Code, Qwen Code and Hermes show a model only a preview of a
#: result much above 25,000 characters); upstream's answers stay far below.
MAX_ANSWER = 24_000
ZONE = re.compile(r"[A-Za-z0-9_+\-]{1,40}(?:/[A-Za-z0-9_+\-]{1,40}){0,3}")
MAX_ZONE = 64
MAX_TIME = 16
ZONE_ARGUMENTS = ("timezone", "source_timezone", "target_timezone")


def checked_zone(name: str, value) -> str:
    """VALUE when it can be an IANA zone name; else a ToolError a model can read (the value is not echoed)."""
    if not isinstance(value, str) or len(value) > MAX_ZONE or not ZONE.fullmatch(value):
        raise ToolError(f"Invalid timezone: {name} must be an IANA timezone name such as 'Europe/Berlin' or "
                        f"'America/New_York' (at most {MAX_ZONE} characters, letters, digits, _ + - and /)")
    return value


def local_zone() -> str:
    """The zone named as local in the tool descriptions: LOCAL_TIMEZONE if set (an exact IANA key, else the server
    ends), else what tzlocal finds as upstream asks it, else UTC."""
    wanted = os.environ.get("LOCAL_TIMEZONE", "").strip()
    if wanted:
        try:
            checked_zone("LOCAL_TIMEZONE", wanted)
            upstream.load_zoneinfo(wanted)
        except Exception:  # noqa: BLE001 - upstream ends the same way on a bad --local-timezone
            sys.exit(f"Error: invalid LOCAL_TIMEZONE {wanted[:80]!r}: not a known IANA timezone name")
        return wanted
    try:
        return str(upstream.get_local_tz(None))
    except Exception:  # noqa: BLE001 - a broken /etc/localtime or TZ: UTC, as upstream's fallback
        return "UTC"


def checked_tool(fn):
    """FN (an upstream tool function) with its arguments checked first and its answer bounded."""
    @functools.wraps(fn)
    def run(**arguments):
        for name in ZONE_ARGUMENTS:
            if name in arguments:
                arguments[name] = checked_zone(name, arguments[name])
        if "time" in arguments and (not isinstance(arguments["time"], str) or len(arguments["time"]) > MAX_TIME):
            raise ToolError("Invalid time format. Expected HH:MM [24-hour format]")
        answer = fn(**arguments)
        if len(answer.model_dump_json(indent=2)) > MAX_ANSWER:  # never for upstream's answers; kept as a guard
            raise ToolError("the answer is too long")
        return answer
    return run


def tools_only(server):
    """SERVER (an MCPServer) advertises tools only: the SDK registers the handlers of resources and prompts for every
    server, and the capabilities of the initialize answer follow the handlers, so a server that publishes neither
    advertised both. Agents then offer a model tools for MCP resources, which local models took for the way to the
    server's tools (sandbox-ai research round 1, "the MCP-resource trap")."""
    for method in ("resources/list", "resources/read", "resources/templates/list", "resources/subscribe",
                   "resources/unsubscribe", "prompts/list", "prompts/get"):
        server._lowlevel_server._request_handlers.pop(method, None)


def create_server():
    server = upstream.create_server(local_zone())
    for tool in server._tool_manager.list_tools():
        tool.fn = checked_tool(tool.fn)
    tools_only(server)
    return server


if __name__ == "__main__":
    asyncio.run(create_server().run_stdio_async())
