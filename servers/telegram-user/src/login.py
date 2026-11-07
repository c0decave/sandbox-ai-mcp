#!/usr/bin/env python3
"""Log a Telegram user account in once and print its Telethon StringSession, for the
telegram-user MCP server. A human runs this, on the host, never an agent:

    python3 -I login.py | sandbox-ai secrets set TELEGRAM_SESSION

It asks on the terminal for the api_id and api_hash (https://my.telegram.org; taken from
TELEGRAM_API_ID and TELEGRAM_API_HASH when they are set), the phone number, the login code Telegram
sends and, if the account has one, the two-step verification password (not shown while typed).
Prompts and messages go to stderr; standard output gets the session and nothing else, so it can be
piped straight into the secret store. The session lives in memory only (StringSession): no
.session file is written, here or anywhere. It refuses to print the session to a terminal unless
--show is given.

The session is the whole account: whoever has it can read and write as you until you end it
(Telegram: Settings > Devices, the device "sandbox-ai-mcp").
"""

from __future__ import annotations

import asyncio
import contextlib
import getpass
import os
import re
import sys

from telethon import TelegramClient
from telethon.sessions import StringSession

# The same as the server's (src/server.py DEVICE): the account's list of devices shows it.
DEVICE = {"device_model": "sandbox-ai-mcp", "system_version": "telegram-user", "app_version": "1.0",
          "lang_code": "en", "system_lang_code": "en"}


def ask(prompt: str) -> str:
    """One line from the terminal, the prompt on stderr (stdout carries only the session)."""
    sys.stderr.write(prompt)
    sys.stderr.flush()
    line = sys.stdin.readline()
    if not line:
        raise SystemExit("login.py: no input")
    return line.strip()


def secret(prompt: str) -> str:
    return getpass.getpass(prompt, stream=sys.stderr)


def api_credentials() -> tuple[int, str]:
    api_id = os.environ.get("TELEGRAM_API_ID", "").strip() or ask("api_id (https://my.telegram.org): ")
    if not re.fullmatch(r"[0-9]{1,12}", api_id) or not int(api_id):
        raise SystemExit("login.py: api_id is a number (https://my.telegram.org, API development tools)")
    api_hash = os.environ.get("TELEGRAM_API_HASH", "").strip() or secret("api_hash (not shown): ")
    if not re.fullmatch(r"[0-9a-fA-F]{32}", api_hash):
        raise SystemExit("login.py: api_hash is 32 hex digits (https://my.telegram.org)")
    return int(api_id), api_hash


async def login(api_id: int, api_hash: str) -> tuple[object, str]:
    """(the account, its StringSession) after an interactive login."""
    client = TelegramClient(StringSession(), api_id, api_hash, **DEVICE, receive_updates=False)
    # Telethon prints "Signed in successfully as ..." to stdout: keep stdout for the session.
    with contextlib.redirect_stdout(sys.stderr):
        await client.start(phone=lambda: ask("Phone number (international, e.g. +4917012345678): "),
                           code_callback=lambda: ask("Login code (sent by Telegram): "),
                           password=lambda: secret("Two-step verification password (not shown): "))
        me = await client.get_me()
        session = client.session.save()
        await client.disconnect()
    return me, session


def main(argv: list[str]) -> int:
    if argv not in ([], ["--show"]):
        print(__doc__, file=sys.stderr)
        return 2
    if sys.stdout.isatty() and argv != ["--show"]:
        print("login.py: standard output is a terminal and would show the session (the whole account).\n"
              "Pipe it into the secret store instead:\n"
              "    python3 -I login.py | sandbox-ai secrets set TELEGRAM_SESSION\n"
              "or pass --show to print it here anyway.", file=sys.stderr)
        return 2
    api_id, api_hash = api_credentials()
    me, session = asyncio.run(login(api_id, api_hash))
    if getattr(me, "bot", False):
        print("login.py: that is a bot; telegram-user is for a user account", file=sys.stderr)
        return 1
    name = " ".join(p for p in (getattr(me, "first_name", None), getattr(me, "last_name", None)) if p)
    print(f"login.py: logged in as {name or '?'} (id {getattr(me, 'id', '?')}); the session follows on "
          "standard output. Keep it secret: it is the whole account.", file=sys.stderr)
    sys.stdout.write(session + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
