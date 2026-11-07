# telegram - provenance and audit

| | |
|---|---|
| MCP server | this repository, `src/server.py` (MIT, `LICENSES/`) |
| Service | the Telegram Bot API, https://api.telegram.org/bot&lt;token&gt;/ (getMe, getUpdates, getChat, sendMessage, editMessageText) |
| Python packages | `mcp==1.30.0` and its dependencies, hash-locked in `requirements.txt` (the same lock as brave-search; httpx comes with mcp) |
| Debian packages | `python3=3.13.5-1`, `ca-certificates=20250419+deb13u1` |
| Base image | the `debian:trixie-slim` digest in `Dockerfile` |

## Why an own server

The Telegram MCP servers around are mostly user-account clients (MTProto, Telethon or Pyrogram
with an API id, a phone login and a session file that is the whole account): far more than an
agent needs, and a stolen session is a stolen account. A bot is a separate identity that only
sees what is sent to it; five Bot API calls are a small own server, in line with the others
here.

## Audit

**Tools:** `get_me`, `get_updates`, `get_chat`, `send_message`, `edit_message_text`: `POST
.../bot<token>/<method>` with a JSON body, the method from a fixed list of five. No redirects;
answers above 8 MiB are refused; timeout 30 s (getUpdates: 30 s plus its long-polling timeout);
401/404 (the token), 409 (another getUpdates or a webhook), 429 (with its retry time) and other
errors are named, with Telegram's description cut to 300 characters. Not offered: deleting,
forwarding, files, inline mode, webhooks, chat administration.

**Token:** read from `TELEGRAM_BOT_TOKEN` for each request, checked to be `digits:` plus 20-100
characters of `[A-Za-z0-9_-]`, sent only to api.telegram.org, never returned or logged. The Bot API
puts the token in the URL path, so the server keeps every URL away from answers and logs:
network errors are reported by their type only (an httpx exception text or its request can name
the URL), any other exception is reported by its type, httpx's own request log (it logs each URL
at INFO) is turned down to WARNING, and the log formatter, the only handler of the process,
removes the token and anything shaped like one from every line, tracebacks included. Answers
pass the same redaction, so a token someone writes into a chat does not come through either.

**Allowed chats:** `TELEGRAM_ALLOWED_CHATS`, comma-separated numeric chat ids, is recommended.
When it is set, `get_chat`, `send_message` and `edit_message_text` refuse every other chat (and
`@username`s, which cannot be checked against ids), and `get_updates` leaves out the updates of
other chats or of no chat (counted as `skipped_other_chats`; `next_offset` still confirms them).
A malformed value makes every tool refuse rather than allowing every chat. Without it, every chat
the bot is in can be read and written to.

**Arguments:** `chat_id` a non-zero integer of at most 52 bits (or its digits), or `@username`
(5-32 characters) without the allowlist; `text` 1-4096 characters counted in UTF-16 units as
Telegram counts them, not only blanks, no control characters but tab and line breaks;
`parse_mode` empty, `HTML` or `MarkdownV2`; `disable_notification` a boolean;
`reply_to_message_id` 0 (none) or 1 to 2^31-1; `message_id` 1 to 2^31-1; `offset` -100 to
2^52-1 (0: not sent); `limit` 1-100; `timeout` 0-50 s. Link previews are always off for sent
messages (Telegram would fetch the links).

**Results:** a compact form, not Telegram's raw objects: message id, chat (id, type, title,
username, name), sender, date, text or caption (at most 4096 characters), the kinds of media
attached (not the files), the id of the message replied to; for other update kinds the type,
chat id, sender and a callback's data (64 characters). Chat descriptions at most 512 characters,
names 256. Message texts are written by other people: they are data for the agent, not
instructions (said in the tool's description).

**Network:** allowlist `api.telegram.org:443`.

**Tested:** natively (`tests/test_own_servers.py`: handshake, tools/list, missing token, the
allowlist, refused arguments, the update parser against `tests/fixtures/telegram-updates.json`,
and every tool against a local stand-in for the Bot API: the request sent, the errors named, no
redirect followed, the token in no answer and no log line). The smoke spec runs refused calls
only; a live call needs a bot token and a chat, so CI has none.
