# imap - provenance and review

| | |
|---|---|
| MCP server | this repository, `src/server.py` (MIT), our own (2026-11-25): read-only IMAP on Python's standard library (`imaplib`, `email`, `html.parser`, `ssl`) |
| Upstream | none taken. The registry pass of 2026-11-18 (`research-llm/mcp-registry-research-2026-11.md`, gap "Read-only IMAP") looked at Wh1isper/mcp-email-server 1.14.0 (BSD-3-Clause): 24,700 lines with a React web UI, 75 releases, `keyring`, `jinja2`, `loguru`, `mcp<2`, and it sends mail when an SMTP host is set - it stays out; no small reviewed upstream fits |
| Python packages | `requirements.txt`: the shared lock of servers/duckduckgo (`mcp==1.30.0` and its dependencies; the same versions and hashes) - nothing new; IMAP, MIME and HTML parsing are the standard library's |
| Debian packages | `tini=0.19.0-3+b8` (the image's init, its ENTRYPOINT), `python3=3.13.5-1` (its `imaplib`, `email`, `ssl` on Debian's OpenSSL), `ca-certificates=20250419+deb13u1` |
| Base image | the `debian:trixie-slim` digest in `Dockerfile` |

## This server

**Tools** (all `readOnlyHint`):

| Tool | IMAP commands | Answer |
|---|---|---|
| `list_folders(with_counts=true)` | `LIST "" *`; `STATUS "NAME" (MESSAGES UNSEEN)` for the first 50 selectable folders | name (modified UTF-7 decoded), special-use role (sent, drafts, trash, junk, archive ...), not selectable, counts |
| `search_messages(folder="INBOX", from_address?, to_address?, subject?, text?, since?, before?, unread_only=false, flagged_only=false, limit=20)` | `EXAMINE "FOLDER"`; `UID SEARCH [CHARSET UTF-8] SINCE d-Mon-yyyy BEFORE ... UNSEEN FLAGGED FROM "..." ...`; `UID FETCH uids (UID FLAGS RFC822.SIZE BODY.PEEK[HEADER.FIELDS (FROM TO CC SUBJECT DATE MESSAGE-ID)])` | newest first (highest uid): uid, date, from, to, subject, size, read, flagged; how many more matched |
| `read_message(uid, folder="INBOX", offset=0, max_chars=20000)` | `EXAMINE`; `UID FETCH uid (UID RFC822.SIZE)` (more than 25 MiB refused); `UID FETCH uid (UID BODY.PEEK[])` | from, to, cc, reply-to, date, subject, message-id, in-reply-to; the text/plain part, else the HTML part as text (script, style and head dropped, block tags as lines, links' http(s) addresses after their text); the attachments' names; parts of the text by `offset`/`next_offset` |
| `list_attachments(uid, folder="INBOX")` | as `read_message` | file name, content type, decoded size, inline - never the content |

**Read-only by construction:** folders are opened with `EXAMINE` (imaplib's `select(readonly=True)`), never `SELECT`;
bodies and headers are fetched with `BODY.PEEK` (a plain `BODY[]` would set `\Seen`); no command that changes
anything - `STORE`, `COPY`, `MOVE`, `EXPUNGE`, `APPEND`, `CREATE`, `DELETE`, `RENAME`, `SUBSCRIBE` - appears in the file;
no SMTP. A test records every command the stand-in server receives and allows only `CAPABILITY`, `STARTTLS`, `LOGIN`,
`LIST`, `STATUS`, `EXAMINE`, `UID SEARCH`, `UID FETCH`, `LOGOUT`, and no `BODY[` in a fetch.

**Settings:** `IMAP_HOST` (a host name or IP), `IMAP_USER`, the secret `IMAP_PASSWORD` (one line each; imaplib quotes
the password), `IMAP_TLS` `ssl` (implicit TLS, port 993, default) or `starttls` (port 143) - plaintext IMAP is refused,
`IMAP_PORT`, `IMAP_CA_CERT` (PEM or base64 PEM: a private CA or a local bridge's certificate). TLS: Python's default
context (certificate and host name verified), at least TLS 1.2. One connection per tool call: login, work, logout;
30 s timeouts.

**Arguments:** folder names one line without control characters (sent as an IMAP quoted string, modified UTF-7
encoded); uids positive numbers only (no sequence sets: `1:*`, `1,2` refused); search terms one line of at most 200
characters, sent as quoted strings - at most one with non-ASCII characters, sent as an IMAP literal with `CHARSET
UTF-8` (imaplib sends one literal per command); dates `YYYY-MM-DD` (IMAP's month names, not the locale's); numbers in
their ranges. imaplib itself refuses CR, LF and NUL in any argument (a second line of defence against command
injection, tested).

**Answers:** within 24,000 characters (lists cut from the end; a message's text cut so that the JSON with its escapes
fits, `next_offset` names the rest); control characters removed; headers decoded by the `email` package's default
policy (RFC 2047), at most 1,000 characters each. The password appears in no answer or error (tested).

**Network:** `IMAP_HOST` - a host only the user knows: `full` (egress-all) like gitea, `--allow-tcp` for a server in
the local network or a bridge on the host. **Secrets:** `IMAP_PASSWORD`. **Files:** none.

## Tested

- `tests/test_imap.py` (8 tests) against a stand-in IMAP4rev1 server on loopback over real TLS (a throwaway CA given
  as `IMAP_CA_CERT`): the handshake and the message without settings; folders (modified UTF-7, roles, not
  selectable, counts); searches (the criteria sent, dates in IMAP's form, newest first and the count of older ones,
  flags, a non-ASCII term as a literal with `CHARSET UTF-8`, quotes and backslashes escaped); a plain message with an
  injected instruction passed on as data and its PDF attachment listed but not given out, an HTML message as text
  (script and style gone, the link kept), a 5,000-line message in parts without escape sequences, an unknown uid;
  STARTTLS with a base64 CA, a missing CA and a wrong CA refused; a wrong password, an unreachable server; 5 refused
  settings and 12 refused arguments (sequence sets, injected `\r\n A1 DELETE`/`EXPUNGE`, two non-ASCII terms) with
  nothing sent; modified UTF-7 both ways; after every test: only reading commands, only `BODY.PEEK`.
- `tests/test_own_servers.py` `test_imap` (in the image in CI, no network).
- `smoke.json`: the four tools against `127.0.0.1:9` (network none: each says it cannot reach the server) and two
  refused arguments - 6/6 passed over stdio here.

## Risks left

- The password opens the whole mailbox to the IMAP protocol (a provider's app password limits it to IMAP; none
  limits IMAP to reading) - this server's code is the read-only boundary.
- Mail is the classic carrier of prompt injection: a preset using this server should mark its results untrusted
  (research-memory's ruleset does).
- Python's `email` and `html.parser` parse untrusted messages (bounded to 25 MiB; no files written, no network).
- Not run against a real provider here (Dovecot, Gmail, Outlook, Proton Mail Bridge); the commands are RFC 3501's.
