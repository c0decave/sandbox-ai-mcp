# telegram-user - provenance and audit

| | |
|---|---|
| MCP server | this repository, `src/server.py` and `src/login.py` (MIT, `LICENSES/`) |
| Service | Telegram's MTProto API (the protocol of the official apps), as a user account |
| Python packages | `mcp==1.30.0` (the same lock as telegram) and `telethon==1.45.0` (MIT, PyPI, 2026-09-10) with `pyaes==1.6.1` (MIT), `rsa==4.9.1` (Apache-2.0), `pyasn1==0.6.4` (BSD-2-Clause; 0.6.5 of 2026-10-27 fixes four quadratic-time decoding advisories, GHSA-2qm8-x737-gmw5, -mm57-4v3p-rchx, -9m75-vc3g-4x39, -fm9c-5rcf-2q5p, but is too new under the pinning rule until 2026-11-10; Telethon decodes with it only RSA public keys, its built-in ones and the CDN keys Telegram sends over the encrypted connection, so no outside input reaches it: re-lock to 0.6.5 from 2026-11-10), hash-locked in `requirements.txt` |
| Build only | `setuptools==84.2.1`, hash-locked in `requirements-build.txt`, removed from the image after the build |
| Debian packages | `python3=3.13.5-1` (no ca-certificates: nothing here speaks TLS) |
| Base image | the `debian:trixie-slim` digest in `Dockerfile` |

## Why an own server, and why a user account

The `telegram` server of this repository is a bot: it only sees what is sent to it. Investigating
public channels and groups (reading their history, searching them, following forwards and
comments, checking invite links) needs a user account; the Bot API cannot do it. The user-account
MCP servers around expose the whole account (send, delete, contacts, the session file on disk);
this one is read-only unless it is turned on, keeps the session in the container's memory, and
offers only what an investigation needs.

**Use an account made for the investigation**, not your own: the session is the whole account,
and joining a chat is visible to its admins.

## Telethon 1.45.0 (audited briefly)

`telethon-1.45.0-py3-none-any.whl`, sha256 `339e24c83aedc9f12cbe389264627edc49779e4289c535aa90aafc4ce62f7972`
(PyPI; the source is https://codeberg.org/Lonami/Telethon). MIT (`LICENSES/telethon-MIT.txt`).
Pure Python. Dependencies: `pyaes` (AES in Python, the fallback), `rsa` (the server keys of the
key exchange) and `pyasn1`; `cryptg` (an optional C speedup) is not installed - Telethon uses
OpenSSL's AES-IGE through `ctypes` (`libssl.so.3`, found with `ldconfig -p`) when it is there.

**What it sends:** MTProto over TCP (`asyncio.open_connection`, transport `TcpFull`, or
`TcpMTProxyRandomizedIntermediate` with `TELEGRAM_MTPROXY`) to the data centre the session names
(an IPv4 address and port 443 in the StringSession), and to other data centres of Telegram when a
file lives there (`download_media`); the addresses come from Telegram's own config. Nothing else:
no HTTP client is used (`aiohttp`, which Telethon would use only for bot web documents, and
`python-socks`/`PySocks` for SOCKS proxies are not installed), **no telemetry, no update check**.
On connecting it sends `initConnection` with the api_id, a device model, system and app version
and language codes: the server sets them to fixed values (`sandbox-ai-mcp`, `telegram-user`,
`1.0`, `en`) instead of Telethon's defaults, which are the host's machine type and kernel release.
Those values are what the account's list of devices shows.

**What it stores:** with a `StringSession` object (not a file name) Telethon uses a
`MemorySession`: the auth key, the data centre and the entity cache stay in memory; no
`.session` SQLite file is created (tested: `connect()` in an empty working folder leaves it empty).
`client.session.save()`, which returns the session string, is never called by the server.

**Flood waits:** Telethon sleeps through a `FLOOD_WAIT` of up to 60 s and repeats the request by
default. The server sets `flood_sleep_threshold=0`: every `FloodWaitError`,
`FloodPremiumWaitError` and `SlowModeWaitError` comes back at once as a tool error naming the wait
(`retry_after`); nothing is retried. Other retries are kept small (`request_retries=2`,
`connection_retries=2`, 15 s per request, 120 s per tool, 600 s per download). The update loop is
off (`receive_updates=False`): the server only asks, it does not follow.

## Audit of the server

**Secrets:** `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` and `TELEGRAM_SESSION` from the environment
only, checked for their shape (digits; 32 hex digits; a StringSession of 341-383 characters)
and named, never quoted, when missing or malformed. Without them the server starts, `tools/list`
works, it says on stderr which variable is missing, and every tool refuses with that text (the
same as the `telegram` server without a token). The session is never returned and never logged:
the log formatter (the only handler of the process; uncaught exceptions are logged by type only)
removes the session, the API hash, the MTProto proxy secret and the API id from every line,
tracebacks included; every answer passes the same redaction (the configured values and anything
shaped like a StringSession), so a session someone posts in a chat does not come through either.
Unexpected exceptions are reported by their type only. `get_me` never returns the account's
phone number.

**Read tools (always):** `get_me`, `resolve_chat` (contacts.resolveUsername or the entity cache),
`search_chats` (contacts.search, 1-100), `get_chat_info` (channels.getFullChannel,
messages.getFullChat, users.getFullUser), `check_invite` (messages.checkChatInvite: looks,
does not join), `list_dialogs` (1-200), `get_messages` (messages.getHistory: 1-200, `offset_id`,
`min_id`, `max_id`, `since`/`until` as ISO dates, oldest first), `search_messages`
(messages.search in one chat, optionally of one sender), `search_global` (messages.searchGlobal:
the account's chats), `get_replies` (messages.getReplies: a post's comments or a thread). A chat
is an `@username`, a t.me link (`/s/NAME`, `/c/ID`) or a marked numeric id; an id works for chats
the session knows (the account's dialogs are loaded once, at most 500, on the first unknown id),
anything public by username. Media are metadata only (kind, size, MIME type, file name, duration,
dimensions; a link preview's URL and title; a place; a contact; a poll); links come with their
hidden targets (`MessageEntityTextUrl`).

**download_media:** offered only when a writable `/out` is mounted (`--mount /out=DIR:rw`),
otherwise not in `tools/list`. It saves one message's photo or document as
`/out/telegram-user/<chat id>_<message id>.<ext>` (the extension from the MIME type, never the
sender's file name), refuses a file Telegram says is larger than `TELEGRAM_USER_DOWNLOAD_MB`
(default 20 MiB, at most 2000) and stops (and removes the file) when more bytes arrive than
that; it never overwrites (`O_EXCL`, `O_NOFOLLOW`) and answers path, size and SHA-256.

**Write tools (opt-in):** `send_message` (plain text, 1-4096 UTF-16 units, no Markdown or HTML
parsing, no link preview), `join_channel` (channels.joinChannel; an invite link with
messages.importChatInvite), `leave_channel` (channels.leaveChannel, or messages.deleteChatUser of
the account itself for a basic group; never a conversation with a user), `mark_read`. They are
registered only when `TELEGRAM_USER_WRITE=1` when the server starts: otherwise they are not in
`tools/list` and cannot be called; each also checks again. `TELEGRAM_USER_ALLOWED_CHATS`
(comma-separated marked ids and `@usernames`) limits them to those chats, compared after the chat
is resolved (id, or any of its active usernames); an invite link cannot be checked before joining,
so with the list set it is refused; a malformed list makes every write tool refuse. Not offered at
all: deleting or editing messages, forwarding, contacts, the account's settings, sessions, calls,
secret chats.

**Limits and arguments:** messages 1-200 per call (Telethon then asks in pages of 100), dialogs
1-200, chat search 1-100, queries 1-256 characters on one line, ids 0 to 2^31-1, texts in answers
at most 4096 characters (`text_truncated`), descriptions 1024, names 256, links 50 per message.
Bad arguments are named before the account is used.

**Untrusted content:** message texts, captions, names, descriptions, links and downloaded files
are written by other people. Every reading tool says so in its description and answers carry a
`note` saying it: data for the agent, not instructions.

**Network:** `full`. MTProto goes to Telegram's data centres by IP address (the session's, and the
ones Telegram's config names), not to an HTTPS host, so there is no host list to allow. Telegram
sees the address the connection comes from: put a VPN in front (`sandbox-ai mcp add telegram-user
--vpn PROFILE`; its kill switch lets nothing out but through the tunnel), or an MTProto proxy
with `TELEGRAM_MTPROXY=host:port:secret` (32 hex digits, optionally `dd`-prefixed; Telethon does
not support `ee` fake-TLS secrets).

## The login (once, by a human)

`src/login.py` asks for the api_id and api_hash (or takes `TELEGRAM_API_ID` and
`TELEGRAM_API_HASH` from the environment), the phone number, the login code and the two-step
password (`getpass`, not shown), logs in with an in-memory `StringSession` and prints the
session on standard output - only that; prompts and Telethon's own messages go to stderr. It
writes no file, and refuses to print to a terminal without `--show`. Run it on the host, where
the account's address may be seen (e.g. through the same VPN):

```bash
python3 -m venv /tmp/tg-login
/tmp/tg-login/bin/pip install --require-hashes --only-binary=:all: -r servers/telegram-user/requirements-build.txt
/tmp/tg-login/bin/pip install --require-hashes --only-binary=:all: --no-binary=pyaes --no-build-isolation \
  -r servers/telegram-user/requirements.txt
/tmp/tg-login/bin/python -I servers/telegram-user/src/login.py | sandbox-ai secrets set TELEGRAM_SESSION
sandbox-ai secrets set TELEGRAM_API_ID      # and TELEGRAM_API_HASH, each from standard input
rm -rf /tmp/tg-login
```

The image has it too (`/opt/mcp/login.py`):
`podman run --rm -it --entrypoint /opt/venv/bin/python IMAGE@DIGEST -I /opt/mcp/login.py --show`
prints the session on the terminal (a pseudo-terminal joins stdout and stderr), to paste into
`sandbox-ai secrets set TELEGRAM_SESSION`. End the session in Telegram (Settings > Devices,
`sandbox-ai-mcp`) when the investigation is over.

## Tested

Natively (`tests/test_telegram_user.py`, with a fake Telethon client injected in place of the
real one, no network): tools/list read-only by default and with `TELEGRAM_USER_WRITE=1` (only
`1`), `download_media` only with a writable `/out`; the missing and malformed secrets (named,
never shown); refused arguments and limits (before anything is asked); the options of every
request (`offset_date`, `reverse`, limits); the message format (links with hidden targets,
forwards, replies, media metadata, truncation); unknown ids and the one dialog load; flood waits
answered with their time and not retried; a revoked session; the allowed chats of the write
tools and a broken list; downloads (cap, lying sizes, no overwrite, the sender's file name never
used); the client's options (`flood_sleep_threshold=0`, no update loop, the fixed device, an
in-memory session, no file); `login.py` (only the session on stdout, no file, no terminal
without `--show`); and the secrets in no answer and no log line. The smoke spec runs refused calls
only: a live call needs an account, so CI has none.
