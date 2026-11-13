# youtube - provenance and audit

| | |
|---|---|
| MCP server | this repository, `src/server.py` and `src/authorize.py` (MIT, `LICENSES/`), written for this repository and reviewed in full (below) |
| Service | the YouTube Data API v3 (`www.googleapis.com/youtube/v3/`, `www.googleapis.com/upload/youtube/v3/`) and Google's OAuth 2.0 token endpoint (`oauth2.googleapis.com/token`) |
| Python packages | `mcp==1.30.0` and its dependencies (httpx 0.28.1 among them), hash-locked in `requirements.txt` (byte-identical to web-fetch's but for the `# via` line; the same set gowitness and whatweb run) |
| Debian packages | `python3=3.13.5-1`, `python3-venv=3.13.5-1` (purged after the venv is made), `ca-certificates=20250419+deb13u1` |
| Base image | the `debian:trixie-slim` digest in `Dockerfile` (the same as web-fetch's) |

**Pinning rule:** no new third-party release comes in: the Python set is the lock the published web-fetch,
gowitness and whatweb images already use (taken under the 14-day rule when it was made), and the Debian versions
and base digest are theirs. `authorize.py` uses Python's standard library only.

## Why an own server

An agent in a sandbox (sandbox-ai's video-creation preset) makes a video and should publish it to the user's
channel **without ever seeing the user's Google credentials**. The OAuth client and its refresh token are given
to this server's container only (sandbox-ai's secrets, `--env NAME`); the server refreshes its access token itself
and keeps it in memory. The agent gets tool answers, never a token.

Google's client libraries (`google-api-python-client`, `google-auth`, `google-auth-oauthlib`) were not used: they
bring `httplib2`, `uritemplate`, `pyparsing`, `cachetools`, `rsa`, `pyasn1`, `oauthlib`, `requests` and a
discovery-document client that can call any method of any Google API - a large surface for five fixed requests.
The whole code path here is two files of our own on the SDK and httpx this repository already ships.

## Tools

| Tool | Writes? | Requests | Scope (any of) | Quota units |
|---|---|---|---|---|
| `upload_video` | **yes**: a new video, private by default | `POST upload/youtube/v3/videos?uploadType=resumable&part=snippet,status`, then `PUT` chunks to the session | youtube.upload (also youtube, youtube.force-ssl) | about 1600 (videos.insert) |
| `set_thumbnail` | **yes**: replaces a thumbnail | `GET youtube/v3/videos?part=status&id=ID` (the public guard; not with `YOUTUBE_ALLOW_PUBLIC=1`), `POST upload/youtube/v3/thumbnails/set?videoId=ID&uploadType=media` | youtube.upload, and youtube.readonly for the guard's read | 51 |
| `upload_captions` | **yes**: adds a caption track | `GET youtube/v3/videos?part=status&id=ID` (the public guard, as above), `POST upload/youtube/v3/captions?part=snippet&uploadType=multipart` | youtube.force-ssl | 401 |
| `update_metadata` | **yes**: changes the given fields | `GET youtube/v3/videos?part=snippet,status&id=ID`, `PUT youtube/v3/videos?part=...` | youtube.force-ssl | 51 |
| `list_my_videos` | no | `GET channels?mine=true`, `GET playlistItems` (the uploads playlist), `GET videos?part=status` | youtube.readonly (or youtube.force-ssl) | 3 |

**Least privilege.** `authorize.py` asks for `youtube.upload` and `youtube.readonly` by default: uploads,
thumbnails and the list. `youtube.force-ssl` (captions, metadata updates) is asked for only with
`--scopes upload,readonly,force-ssl`; it is broad (Google: see, edit and permanently delete videos, ratings,
comments and captions) - the server offers no tool that deletes or comments, but the token itself could, which is
one more reason it never leaves the container. The scopes Google granted come back with every token refresh; a
tool whose scope is missing refuses before it calls YouTube and names the scope and the `authorize.py` option.

**Quota.** A project gets 10,000 units a day unless Google grants more; an upload costs about 1600, so about six
uploads a day. `quotaExceeded` comes back as an error naming the quota, the costs and the reset (midnight Pacific
Time); `uploadLimitExceeded` (the channel's own limit) and the rate limits are named as well.

**Unverified projects.** Google locks every video uploaded through videos.insert by a project that has not passed
its audit (every new project) to private, whatever privacy was asked. `upload_video`'s answer says so, and
`update_metadata`'s when it makes a video unlisted or public. The audit form:
https://support.google.com/youtube/contact/yt_api_form.

**Write mode.** Changing the channel is what this server is for, so its write tools are always offered; they are
marked in their descriptions (`WRITES to the user's YouTube channel: ...`), in their MCP annotations
(`readOnlyHint: false`) and in `tools.json` (`write_tools`). The guard is sandbox-ai's approvals: a ruleset (see the
README) that asks for each call of the four write tools, so the human sees every upload with its arguments. Beyond
that the server refuses on its own: public videos without `YOUTUBE_ALLOW_PUBLIC=1` (an upload, a change to public,
and any change - metadata, thumbnail, captions - to a video that is public already or scheduled to become public, or
whose privacy cannot be read), files outside `/upload`, more than one upload at a time.

## Audit of the server (`src/server.py`, read in full)

**Credentials.** `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN` from the environment only,
read when needed, checked for their shape and named, never quoted, when missing or malformed. Without them the
server starts, `tools/list` works and every call that would need Google refuses with that text (after its own
argument checks). The token refresh (`grant_type=refresh_token`) is a form POST to
`https://oauth2.googleapis.com/token`; the access token is kept in memory with its expiry (refreshed two minutes
early) and dropped on a 401, which is tried once more with a new one. `invalid_grant` (expired or revoked; 7 days
for an app still in Testing) and `invalid_client`/`unauthorized_client`/`deleted_client` are explained; every 4xx of
the token endpoint reads "Google refused the ..." (the smoke run relies on it); Google's `error_description` is not
passed on, its `error` code only reduced to safe characters.

**No secret in an answer or a log line.** Every answer and every error passes `redact`: the configured client
secret and refresh token, every access token this process was given, and anything shaped like a Google
credential (`ya29.`, `1//`, `GOCSPX-`, `Bearer ...`) or an upload session (`upload_id=...`, whoever has it can
write into the upload; the session's address and id of this process also where Google names them bare) become
`<secret>`. The log handler is the only one of the process (`force=True`) and
redacts every line, tracebacks included; httpx's and httpcore's request logging (URLs with the session id) is set
to warnings; an uncaught exception is logged by its type only, and an unexpected exception in a tool is answered
as `internal error (TYPE)`. The upload session's address is never returned.

**Requests.** All go through `_send`, which refuses anything but `https://` to `oauth2.googleapis.com` or
`www.googleapis.com` on port 443 without user information - the resumable session's `Location` too, which must
also be on `/upload/youtube/v3/videos` (else the upload stops before a byte or a token goes there). No redirects
are followed; answers are read to at most 4 MiB; timeouts 30 s to connect, 60 s to read, 300 s per write.
`HTTPS_PROXY` is honoured (httpx `trust_env`: proxies and `SSL_CERT_FILE` only; no netrc). TLS is verified with
httpx's default (certifi from the lock). **No telemetry, no update check, no other host.**

**Resumable upload.** The session is started with the metadata (`snippet`, `status`), `X-Upload-Content-Length`
and `X-Upload-Content-Type`; the file goes in 8 MiB pieces (a multiple of 256 KiB, as Google requires) with
`Content-Range`, each `308` answer's `Range` telling where to go on (a `Range` beyond the file is refused). After a
5xx, a 429 or a broken connection the server waits (exponential backoff with jitter, at most 64 s) and asks the
session how much it has (`Content-Range: bytes */SIZE`), then goes on from there; 8 failures in a row, or 8 answers
without progress, give up ("nothing was published"); a session that is gone (404/410) is said to be. At most twice
the file plus one piece per allowed failure is sent in all (a session that keeps "forgetting" bytes it had taken is
given up, not fed for ever). The file is
read with `pread` from the descriptor opened once, so it cannot be swapped during the upload; a file that shrinks
stops the upload. One upload at a time per connection (memory stays at about one piece).

**Files.** Only below `/upload` (a folder the user mounts read-only; without it every file tool says how to mount
it). The path is checked as text first: absolute, below `/upload`, no `.` or `..` parts, no hidden names, no control
characters, the right extension (video: .mp4 .m4v .mov .3gp .webm .mkv .avi .mpg .mpeg .wmv .flv; thumbnail .jpg
.jpeg .png; captions .srt .vtt). Then `/upload` and every folder on the way are opened with `O_NOFOLLOW |
O_DIRECTORY` relative to the one before (a link anywhere, `/upload` itself included, is refused), the file is
looked at with `lstat` (only a regular file: no link, folder, device, pipe or socket), opened with `O_NOFOLLOW |
O_NONBLOCK | O_NOCTTY` and checked again with `fstat` (the same inode; owned by the server's own user - the user's
own files under sandbox-ai's Podman `--user=0:0` and its Bubblewrap `--uid` - so no other user's files; exactly
one name, so no hard link to a file elsewhere; not empty; at most `YOUTUBE_MAX_UPLOAD_MB`, default 4096 MiB,
YouTube's 256 GB at most; thumbnails 2 MiB, captions 5 MiB). A video must start like a video container (MP4/MOV,
Matroska/WebM, AVI, MPEG, ASF, FLV), a thumbnail must be a PNG or JPEG (its size is read from the header; 1280x720
is recommended in the answer), captions must be UTF-8 without NUL bytes, WebVTT starting with `WEBVTT`, SRT with
a timing line.

**Fields.** title 1-100 characters, no `<` or `>`, no control characters; description at most 5000 bytes in UTF-8
(with the chapters), no `<` or `>`, line breaks and tabs allowed; tags without `<`, `>` or `,`, at most 500
characters together as YouTube counts them (a comma between tags, a tag with a space counted with its quotes);
`category_id` a number of 1-3 digits; `default_language` (snippet's `defaultLanguage` and `defaultAudioLanguage`)
and the caption `language` BCP-47; `privacy` private (default), unlisted, public only with `YOUTUBE_ALLOW_PUBLIC=1`;
`made_for_kids` (`selfDeclaredMadeForKids`) is a required boolean without a default; `contains_synthetic_media`
(`containsSyntheticMedia`, YouTube's altered or synthetic content disclosure) a boolean, false unless given (the
user's decision of 2026-11-13: the agent sets it when the video shows realistic AI-made or altered content); chapters (`{"start": "0:00",
"title": ...}` or `"0:00 title"`) start at 0:00, at least 3, in order, each at least 10 s after the one before,
and are written into the description as `M:SS title` lines; a video id is 11 characters of `[A-Za-z0-9_-]`; a
caption name at most 150 characters. `update_metadata` reads the video first and sends back its writable fields
with only the given ones changed (videos.update replaces a whole part: an omitted description or tag list would
otherwise be deleted); `publishAt` is kept only for a video that stays private; chapters need the description.

**Answers.** Bounded: texts of Google's at most 300 characters (titles, error messages), at most 5 reason codes,
at most 50 videos; video ids checked before they are used in links (`https://youtu.be/ID`, Studio's edit page).

## Audit of the authorization helper (`src/authorize.py`, read in full)

Run once by a human on the host (also in the image at `/opt/mcp/authorize.py`; the server never runs it). The
loopback flow for a "Desktop app" OAuth client: an HTTP server on `127.0.0.1` (a free port, never another
address), the sign-in address with `access_type=offline`, `prompt=consent`, PKCE (`S256`, a verifier of 86
characters) and a random state; the redirect is taken only on `/` with the right state (compared in constant time,
as bytes), only the first one, anything else gets 404; the request line (it carries the code) is not logged. The
listener sets no `SO_REUSEPORT` (no second listener on the port) and drops a connection that sends nothing within
20 s (it serves one request at a time). With `--open` the browser is started with standard output pointed at
stderr, so nothing it prints lands in the pipe that carries the token.
The code is exchanged at `https://oauth2.googleapis.com/token` (urllib, TLS verified); standard output gets the
refresh token and nothing else, and not a terminal unless `--show`; messages (the granted scopes, the next steps)
go to stderr without the token or the client secret. No file is written; the client JSON is only read. A Web
client's JSON is refused (it has no loopback redirect). Hosts: `accounts.google.com` (in the address the user
opens; the helper does not fetch it) and `oauth2.googleapis.com`.

## Self-review: what was found and changed

Reviewed file by file as the third-party code of this repository is (telemetry, other hosts, token leaks, path
escapes, unbounded answers):

- `server.py`: `update_metadata` could rename or re-describe **any** public video of the channel, not only the
  agent's uploads: a change to a video that is public now needs `YOUTUBE_ALLOW_PUBLIC=1` as well (it reads the
  video anyway). Google's error answers could carry any number of reason codes: at most 5 are named. An upload
  session that answers `308` without taking bytes would have been tried forever: at most 8 answers without
  progress. Retries tell a broken connection from a refusal by type (`Unreachable`), not by its text. Found clean:
  every request passes the host check, the session's `Location` included; no token, secret or session id reaches
  an answer or a log line (tests below); every file is opened without following links.
- `authorize.py`: a state with non-ASCII characters made `compare_digest` raise (a traceback on stderr): compared
  as bytes now; a second redirect after the first could replace the result: the first one counts; Google's
  `error` parameter is reduced to safe characters before it is printed (no terminal escapes).
- `Dockerfile`: the base digest and Debian pins of web-fetch; pip and the venv tooling removed; user 10001.

**Remaining risks** (accepted): the write tools act on every video of the channel the token can reach (the
non-public ones without `YOUTUBE_ALLOW_PUBLIC`): the approvals are the guard. Between the `lstat` and the `open`
of a file, someone who can create device nodes in the mounted folder could swap one in (`O_NONBLOCK | O_NOCTTY`,
and `fstat` refuses it before a byte is read); an agent in a sandbox cannot make device nodes. A title of Google's
that looks like a credential (`Bearer something`) is redacted in an answer too. sandbox-ai gives an `allowlist`
entry the full network (it cannot limit a server to hosts yet): the host check of `_send` is what keeps the
requests on Google's two hosts.

**Limits:** none beyond sandbox-ai's defaults (512m memory, 128 processes, a 64m /tmp): the upload holds one 8 MiB
piece at a time and writes nothing to /tmp, so `smoke.json` sets none.

## Tested

- `tests/test_youtube.py` (no network; a fake Google as an httpx transport): token refresh, its cache, expiry and
  errors; a 401 answered with one new token; the resumable upload with a chunk that fails with 503 after Google kept
  1000 of its bytes, resumed from the `Range` the session reports, and a broken connection resumed the same way;
  the retries giving up; an expired session; the session's `Location` on another host, on http, on another port
  or path refused before a byte is sent; quota errors; one upload at a time; the size cap; thumbnails (PNG, JPEG,
  dimensions, 2 MB, an unverified channel); captions (the multipart body, SRT and WebVTT checks); `update_metadata`
  sending back the untouched fields, part by part, and a public video guarded; `list_my_videos`; every field limit;
  every path refusal (outside, `..`, hidden, links, a linked folder, a linked `/upload`, a pipe, a device, a folder,
  hard links, another user's file, empty, not a video); the scopes; no secret in answers, errors and log lines; the
  tool list against `tools.json`; `authorize.py`'s loopback flow (PKCE, state, wrong state and path refused, only
  the token on stdout, a terminal refused, a refused consent, a Desktop client's JSON).
- `tests/test_own_servers.py` `test_youtube`: the server over stdio, then all of the above inside the image in CI
  (its Python and libraries, no network).
- `smoke.json`, without an account: placeholders that only look like credentials, so the one real call reaches
  `oauth2.googleapis.com` through the run line's network and Google refuses the client (expected: "Google refused
  the ", which every 4xx answer of the token endpoint gives - `invalid_client` for an unknown client, but also
  `unauthorized_client`, `deleted_client`, `invalid_grant` or `invalid_request` should Google word it otherwise;
  a connection that fails gives "not reachable", a 5xx "answered HTTP 5xx", so neither passes); the
  refused calls - a path outside `/upload`, `..`, public without `YOUTUBE_ALLOW_PUBLIC`, a missing
  `made_for_kids`, a title with `<`, no `/upload` mounted, a thumbnail that is not JPEG or PNG.

## Independent review, 2026-11-13

A second reviewer, not the builder, read the server again from scratch for backdoors and bad code, without
relying on the self-review above. Line numbers below are those of the reviewed commit `28f7516`.

**Read line by line:** `src/server.py` (1,108 lines), `src/authorize.py` (241), `Dockerfile` (28), `server.json`
(64), `smoke.json` (104), `tools.json` (25), `requirements.in` (1), `requirements.txt` (586: compared byte for
byte with web-fetch's, identical except its `# via` line), both `LICENSES/` files (the MIT texts signal and
osint-mcp ship, identical), this file (183), `tests/test_youtube.py` (849), and the branch's diff of
`tests/test_own_servers.py` (+25), `tests/test_analysis_servers.py` (+62), `.github/workflows/build.yml` (one
matrix entry), `catalog.json` (the entry, generated from `server.json`), `digests.json` (pending), `README.md`
(+71) and `SECURITY.md` (+3). **Read for context:** mcp 1.30's `configure_logging` (a `basicConfig` without `force`,
which does nothing once the server's own handler is in place), httpx 0.28.1's `trust_env` (proxies and
`SSL_CERT_*` only, no netrc), `scripts/smoke_test.py`'s matching (an expected text is a substring).
**Scanned:** no `eval`/`exec`/`pickle`/`marshal`/`subprocess`/sockets/`ctypes` in either file; the only non-ASCII
characters are the dashes a chapter title is stripped of; every URL is one of Google's two API hosts, the sign-in
page, or a link put into an answer (`youtu.be`, Studio, Google's help pages).

### Findings (all fixed test-first: the test failed before the fix)

| # | Severity | Where (at `28f7516`) | Scenario | Status |
|---|---|---|---|---|
| 1 | **medium** | `server.py` 886-912 `set_thumbnail`, 929-967 `upload_captions` | No public guard: an agent without `YOUTUBE_ALLOW_PUBLIC` could replace the thumbnail of any **public** video of the channel (with the default scopes) or add a caption track to it, which everyone then sees; the docs promised "any change to a video that is public already" needs the flag | CONFIRMED (`test_a_public_videos_thumbnail_and_captions_need_allow_public`), fixed |
| 2 | low-medium | `server.py` 1018-1021 `update_metadata` (and the two above) | A private video with `publishAt`, which the user has scheduled to go public, counted as not public: the agent could rewrite its title and description, which then went public on schedule, without the flag. A missing or unknown privacy state was taken as not public | CONFIRMED (`test_a_video_scheduled_to_go_public_counts_as_public`), fixed |
| 3 | low | `server.py` 733-791 `_resumable_upload` | A session whose `308` ranges alternately advance and fall back ("forgetting" bytes) reset the failure and stall counters on every advance, so the upload never ended (bandwidth and time, no quota). This needs Google, or someone who can break TLS, to misbehave | CONFIRMED (`test_a_session_that_keeps_forgetting_bytes_is_given_up`: over 400 requests before the fix), fixed |
| 4 | low | `server.py` 100-115, 685-692 | The upload session was redacted only in the shape `upload_id=...`. A Google error naming the session id bare would have reached the agent through `explain`'s message, and with it the right to write into the upload | CONFIRMED against the fake Google (`test_the_bare_session_id_never_reaches_an_answer`), fixed |
| 5 | low (CI) | `smoke.json` call 1, `server.py` 617-627 | The smoke run expected exactly `Google refused the OAuth client (invalid_client)`. Google answers an unknown client with 401 `invalid_client` ("The OAuth client was not found."), but answers like `deleted_client`, `invalid_grant` or `invalid_request` would have read differently (the last as "answered HTTP 400"), and CI would have failed on wording alone | CONFIRMED (`test_every_refusal_of_the_token_endpoint_reads_the_same`), fixed |
| 6 | low | `authorize.py` 219-222 | With `--open`, `webbrowser.open` starts the browser on the helper's standard output, which is the pipe into `sandbox-ai secrets set`. Chrome prints "Opening in existing browser session." there, which would corrupt the stored refresh token, and a browser that holds the pipe open keeps `secrets set` waiting. Not a leak: the output only goes to the user's own secret store | CONFIRMED with a child process that writes to stdout (`test_the_browser_never_writes_into_the_token_pipe`), fixed |
| 7 | low (hardening) | `authorize.py` 155 | `http.server.HTTPServer`: some Python versions set `allow_reuse_port` on it, which would let a second listener of the same user share the port and receive the redirect's code (useless without the PKCE verifier and client secret, which that user could read anyway). The server is single-threaded with no timeout, so a local connection that sends nothing held up the browser's redirect until the 300 s wait ended | plausible (depends on the host's Python; 3.11 here does not set it), hardened (`test_the_loopback_listener_is_not_shared_and_not_held`) |

**Fixes.** (1, 2) `_refuse_public` reads the video's state first (`videos.list part=status`, 1 unit, scope
youtube.readonly or force-ssl; not needed with `YOUTUBE_ALLOW_PUBLIC=1`). `_not_public` then refuses a video that
is public, scheduled to become public, whose privacy cannot be read, or that this channel cannot see. All three
write tools that change an existing video use it. With only youtube.upload granted, `set_thumbnail` names the
missing youtube.readonly; `upload_captions` checks its own force-ssl first. (3) An upload sends at most `2 x size +
2 x RETRIES x CHUNK` bytes in all, then gives up ("nothing was published"). (4) The session's address and its
`upload_id` are added to the redacted secrets as soon as the session is checked. (5) Every 4xx answer of the
token endpoint now reads "Google refused the ..." (`deleted_client` is named as a client refusal; other codes are
reduced to safe characters), a 5xx reads "answered HTTP 5xx", and the smoke run expects "Google refused the ". A
failed connection ("not reachable") and a server error still fail it, so the check still proves Google answered
through the sandbox's network. (6) `open_browser` points file descriptor 1 at stderr while the browser starts.
(7) `LoopbackHTTPServer` sets `allow_reuse_port = False`, and the handler drops a silent connection after 20 s.

**User decision implemented:** `contains_synthetic_media` defaults to false and is no longer required;
`made_for_kids` stays required without a default (signature, tool description, `server.json`/`catalog.json`,
README, this file; `ToolList` checks the schema: required `path`, `title`, `made_for_kids`, and the default false).

**Questions of the brief, answered.** *Can an update make a private video public without the flag?* No:
`privacy=public` is refused by `_privacy`, the server never sets `publishAt`, and it keeps `publishAt` only for a
video that stays private. The one way round it was the user's own schedule, now finding 2. *Hosts:* every request
goes through `_send` and `_checked_url`: `https` only, the host exactly one of the two, port 443, and no user
information, so any `@` is refused and a URL-parser difference cannot point the request elsewhere. The session's
`Location` must also be on `/upload/youtube/v3/videos`, and no redirect is followed. *Injection:* no argument
reaches a header (MIME types come from a fixed table, `Content-Range` from integers, the multipart boundary is 128
random bits and checked against the file). JSON is written with `json.dumps` (CR, LF and non-ASCII escaped) and
queries with `urlencode` after the video id is checked. *Paths:* the `openat` chain is `O_NOFOLLOW | O_DIRECTORY`,
then `lstat`, then `open(O_NOFOLLOW | O_NONBLOCK | O_NOCTTY)` and `fstat` (same inode, own user, one name, size).
A FIFO swapped in between `lstat` and `open` opens without blocking and is refused by `fstat`. An agent cannot
make device nodes, a hard link cannot cross the mount (`EXDEV`) and one name is required anyway, and a folder
renamed during the walk leads only to files the agent could see already. *Retries:* backoff of at most 64 s plus
jitter, 8 failures in a row, and a new session is never started on its own. *Logging:* the redacting handler is
the only one (checked against mcp's own `configure_logging`), the excepthook logs only the exception type, and
httpx logs warnings only. Nothing but MCP goes to stdout. *Pins:* the lock is web-fetch's (cut-off 2026-10-23, 21
days old, so the 14-day rule holds), hash-checked, wheels only. The base digest and Debian versions are
web-fetch's; pip and the venv tooling are removed; user 10001; `python -I -u`.

**Remaining risks.** (a) Starting the session is retried up to 8 times on 5xx and 429. Whether Google charges
videos.insert's quota for a failed start is not documented, so at worst a day's quota is used up (availability
only). (b) An approval shows the path, not the content, and the agent can change the file in place during the
upload (same inode): what gets published is what the agent wrote. (c) Unlisted needs no flag: anyone with the
link can watch. (d) The `Bearer ...` redaction also hides ordinary words in Google's texts ("ring bearer
ceremony"): cosmetic. (e) Titles and descriptions that `list_my_videos` returns are data from the user's own
channel, not instructions. (f) A force-ssl token could delete; no tool offers that. (g) sandbox-ai gives the
allowlist entry the full network, so the host check in `_send` is the boundary. (h) A local process can still hold
up the redirect listener for 20 s per connection. (i) The cost of 1600 units per upload is Google's table as the
builder recorded it, not re-checked here (no network). (j) Nothing was run against the live API; CI's smoke run
reaches only the token endpoint.

**Tested here:** `tests/test_youtube.py` 49 tests (39 + 10 new) with mcp 1.30.0 and httpx 0.28.1 of the lock;
the whole suite (`SANDBOX_AI_CHECKOUT=... python3 -m unittest discover -s tests`: 243 tests OK; 96 skipped under a
Python without the lock's packages, 42 with them); `scripts/make_catalog.py --check --allow-pending --sandbox-ai`
OK (youtube pending its first digest).

**Verdict: fit to sign - yes**, once CI has built the image from this tree and both sandbox-ai smoke reports
(Podman, Bubblewrap) have passed. No backdoor, telemetry, other host or path for a secret was found. The seven
findings are fixed and the remaining risks are listed above.
