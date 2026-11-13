# bluesky - provenance and audit

| | |
|---|---|
| MCP server | this repository, `src/server.py` (MIT, `LICENSES/`), written for this repository and reviewed in full (below) |
| Service | the AT Protocol: the account's PDS (`BLUESKY_PDS`, default `https://bsky.social`, Bluesky's entryway that serves every account Bluesky hosts) for the session and the writes, Bluesky's public AppView `https://public.api.bsky.app` for the reads, never with the session |
| Python packages | `mcp==1.30.0` and its dependencies (httpx 0.28.1 among them), hash-locked in `requirements.txt` (byte-identical to web-fetch's but for the `# via` line; the same set youtube, gowitness and whatweb run) |
| Debian packages | `python3=3.13.5-1`, `python3-venv=3.13.5-1` (purged after the venv is made), `ca-certificates=20250419+deb13u1` |
| Base image | the `debian:trixie-slim` digest in `Dockerfile` (the same as web-fetch's and youtube's) |

**Pinning rule:** no new third-party release comes in: the Python set is the lock the published web-fetch, youtube,
gowitness and whatweb images already use (taken under the 14-day rule when it was made), and the Debian versions and
base digest are theirs. The server uses Python's standard library besides the SDK and httpx (no grapheme, image or
AT Protocol library).

## Why an own server

An agent in a sandbox that writes articles should announce them on the user's Bluesky account **without ever
seeing the user's credentials**. The handle and an app password are given to this server's container only
(sandbox-ai's secrets, `--env BLUESKY_APP_PASSWORD@SECRET`); the server signs in itself and keeps the session in
memory. The agent gets tool answers, never a token.

The AT Protocol SDKs (`atproto` for Python, `@atproto/api`) were not used: the Python one brings pydantic models for
every lexicon, `cryptography`, `dnspython`, `websockets`, `libipld` (a Rust extension) and a firehose client - a large
surface for a dozen fixed XRPC calls. The whole code path here is one file of our own on the SDK and httpx this
repository already ships.

## Tools

| Tool | Writes? | Requests |
|---|---|---|
| `post` | **yes** (only with `BLUESKY_WRITE=1`): one public post | AppView `com.atproto.identity.resolveHandle` (each @mention, at most 20), `app.bsky.feed.getPosts` (with `reply_to`); PDS `com.atproto.repo.uploadBlob` (each image or the card's thumbnail), `com.atproto.repo.createRecord` (`app.bsky.feed.post`, a record key chosen here), `com.atproto.repo.getRecord` (only after an answer that got lost) |
| `thread` | **yes** (only with `BLUESKY_WRITE=1`): 2-10 posts, each a reply to the one before | as `post`, per post |
| `delete_post` | **yes** (only with `BLUESKY_WRITE=1`): one of the account's own posts | PDS `com.atproto.repo.getRecord`, `com.atproto.repo.deleteRecord` with `swapRecord` |
| `get_profile` | no | AppView `app.bsky.actor.getProfile` (the account's own: after the sign-in, for its DID) |
| `list_my_posts` | no | AppView `app.bsky.feed.getAuthorFeed` (`posts_with_replies`, at most 3 pages) |
| `get_post_thread` | no | AppView `com.atproto.identity.resolveHandle` (an address with a handle), `app.bsky.feed.getPostThread` |

Every write also needs the session: PDS `com.atproto.server.createSession` once per connection, then
`com.atproto.server.refreshSession` when the access token is about to expire.

**Write mode.** Read-only unless the user sets `BLUESKY_WRITE=1` (exactly `1`), like signal and whatsapp. Unlike
those two, the write tools stay in `tools/list` and refuse every call ("writing is off ... nothing was posted"):
the tool list, `tools.json` and an approval ruleset stay the same whether writing is on or not, and an agent learns
why it cannot post instead of not finding the tool. The switch is checked after the arguments' own checks (which
touch neither files nor the network) and before the credentials, any file and any request. The write tools are
marked in their descriptions (`WRITES to the user's Bluesky account (only with BLUESKY_WRITE=1): ...`), in their MCP
annotations (`readOnlyHint: false`; `delete_post` also `destructiveHint: true`) and in `tools.json` (`write_tools`,
`write_switch`, and the recommended ruleset that makes sandbox-ai ask for each write call).

## Audit of the server (`src/server.py`, read in full)

**Credentials.** `BLUESKY_HANDLE` (a handle, `@` optional, or a DID) and `BLUESKY_APP_PASSWORD` from the
environment only, read when needed, checked for their shape and named, never quoted, when missing or malformed.
Without them the server starts, `tools/list` works, the reads of other accounts work, and every call that needs the
account refuses with that text (after its own argument checks). **Never the account password:** the value must be
shaped like an app password (`xxxx-xxxx-xxxx-xxxx`, lower-case letters and digits) or it is not sent at all; and
since an account password could in principle have that shape, the session Bluesky gives is checked too: the access
token's `scope` claim must be `com.atproto.appPass`. `com.atproto.access` (the account password: full access, the
account's e-mail, password and deletion included), `com.atproto.appPassPrivileged` (an app password with access to
direct messages, which no tool needs) and anything unknown are refused, and that session is ended at once
(`com.atproto.server.deleteSession`) - fail closed should Bluesky rename its scopes. The JWT is not verified (the
PDS that issued it does that, over TLS); its claims are read for the scope, the subject (must be the session's DID)
and the expiry only.

**Session.** `createSession` (`{"identifier", "password"}`) at the PDS; the access and refresh tokens are kept in
memory with their expiry (from `exp`; renewed a minute early, half its life early for a short-lived one, and at
least every two hours); an expired or refused access token (`ExpiredToken`, `InvalidToken`, HTTP 401) is renewed
once per request with `refreshSession` (the refresh token as Bearer, to the PDS only), and a refused refresh signs in
again. A renewed session must belong to the same DID. One lock serializes sign-in and renewal. Sign-in refusals:
every 4xx answer reads "Bluesky refused the sign-in (HTTP N, ErrorName)" (the smoke run relies on that), with
`AuthFactorTokenRequired` (the account password with e-mail 2FA) and a taken-down account named, and a 429 reads
"Bluesky refused the sign-in for now" with the wait; a 5xx reads "Bluesky's sign-in answered HTTP 5xx". Bluesky's
`message` is not passed on for a sign-in; elsewhere it is bounded to 300 characters and redacted. The account's
status (`active: false`, `status`) is kept: a deactivated or suspended account posts nothing.

**Where the account lives ("resolve the handle's PDS").** All PDS requests go to `BLUESKY_PDS` (default
`https://bsky.social`). That entryway signs in and serves every account Bluesky hosts, wherever its actual PDS
(`*.host.bsky.network`) is, so the host list stays fixed and declarable (`bsky.social:443`); an account on a PDS of
its own sets `BLUESKY_PDS` to it (that host then replaces `bsky.social`). The session's DID document names the
account's actual PDS (`#atproto_pds`): `get_profile` shows it as `pds_of_the_account` when it differs, but the
server does not switch to it on its own - that would send the session to a host taken from an answer, and one the
catalog cannot list (no wildcards). Handles are resolved to DIDs (mentions, a `reply_to` or post address with a
handle, another account's profile) with `com.atproto.identity.resolveHandle` at the public AppView, which needs no
other host (no `plc.directory`, no DNS or `/.well-known` lookups of the handle's own domain).

**No secret in an answer or a log line.** Every answer and every error passes `redact`: the configured app password,
every session token this process was given (also the refused ones), and anything shaped like one (`eyJ...` JWTs,
`Bearer ...`, an app password's `xxxx-xxxx-xxxx-xxxx`) become `<secret>`. The log handler is the only one of the
process (`force=True`) and redacts every line, tracebacks included; httpx's and httpcore's request logging is set to
warnings; an uncaught exception is logged by its type only, and an unexpected exception in a tool is answered as
`internal error (TYPE)`. Nothing but MCP goes to stdout.

**Requests.** All go through `_send`, which refuses anything but `https://` to the PDS host or
`public.api.bsky.app` on port 443 without user information, and refuses to send an `Authorization` header to any host
but the PDS (so a token never reaches the AppView, and `BLUESKY_PDS` may not be the AppView). `BLUESKY_PDS` must be
`https://HOST` (port 443, no path, query, fragment or user information, a host name). No redirects are followed;
answers are read to at most 4 MiB; timeouts 15 s to connect, 30 s to read, 60 s per write. `HTTPS_PROXY` is
honoured (httpx `trust_env`: proxies and `SSL_CERT_FILE` only; no netrc). TLS is verified with httpx's default
(certifi from the lock). **No telemetry, no update check, no other host; no linked site is ever fetched.**

**Retries and rate limits.** At most 3 tries per request. A 429 is waited for when Bluesky's `ratelimit-reset` (or
`Retry-After`) is at most 30 s away, else the error says when to try again ("nothing was changed by this request");
502-504 and a broken connection are tried again with backoff (2-16 s plus jitter) for requests that are safe to
repeat (reads, the sign-in, an upload - the same bytes give the same blob). **A post is never posted twice:**
`createRecord` gets a record key chosen here (a TID: microseconds and a random clock id, 13 base32-sortable
characters, increasing within the process); after a broken connection or a 5xx the server asks the PDS for that key
(`getRecord`): if the post is there it is the answer, else it tries again (at most 3 times, then "checked: nothing
was posted"). A 400 on a retry is checked the same way (the key may exist from the try whose answer got lost).

**Text, graphemes, facets.** A post's text: line breaks normalised to `\n`, trimmed, no control characters (tabs and
line breaks allowed; no C0/C1 controls, U+2028/U+2029, lone surrogates; no invisible text - Unicode tag characters
outside an emoji flag, variation selectors in a row, bidi embedding/override/isolate controls, also in alt texts,
card titles and descriptions); at most **300 graphemes** and **3000 bytes**
in UTF-8 (the lexicon's `maxGraphemes` and `maxLength`), empty only with images or a card. Graphemes are counted with
an implementation of Unicode's extended grapheme clusters (UAX #29, rules GB3-GB13: CR LF, controls, Hangul syllable
sequences, Extend/ZWJ/SpacingMark, Prepend, emoji ZWJ sequences over Extended_Pictographic, regional-indicator
pairs; the properties from `unicodedata` and the ranges of emoji-data.txt), checked against ICU 78's
`Intl.Segmenter` (Unicode 17) on 437 strings (emoji families, flags, subdivision flags, keycaps, skin tones, Hangul
jamo, Thai, Devanagari, Arabic prepend marks, half-width kana and random mixes): equal except Indic conjuncts, which
Unicode 15.1's GB9c joins and this count does not - so it counts more, never fewer: at worst a Hindi text close to
the limit is refused here though Bluesky would take it. Facets are found as the Bluesky app finds them and placed by
UTF-8 byte offsets (`byteStart`, `byteEnd`): **links** `http(s)://...` after a space, a line break or `(` (trailing
`.,;:!?"'` and any `)` without its `(` left out; a host with a dot; at most 2000 characters); **mentions** `@handle`
after a space, a line break or `(`, a valid handle (trailing `.` and `-` left out), linked only if the AppView
resolves it to a DID (otherwise plain text, and the answer lists it under `mentions_not_linked`); **hashtags** `#` or
`＃` at the start or after a space, not followed by U+FE0F, up to a space or one of the characters the app excludes,
trailing punctuation left out, not only digits (ASCII, as JavaScript's `\d`) and punctuation, at most 64 graphemes and
640 bytes. Overlaps keep the earlier facet; facets are sorted by `byteStart`. `langs`: at most 3 BCP-47 codes.

**Replies and threads.** `reply_to` (an `at://DID-or-handle/app.bsky.feed.post/RKEY` URI or a
`https://bsky.app/profile/.../post/...` address; other collections, `.`/`..` keys and other sites refused) is read
at the AppView (`getPosts`): its `uri` and `cid` are the parent, its own `reply.root` (else itself) the root. A thread
checks every post first - texts, languages, cards, image paths, then (after the write switch and the credentials)
every image file - before the first post goes out; each post then answers the one before with the thread's root. If
Bluesky fails in between (or anything unexpected happens), the answer lists what was posted and how to continue.

**Images and link cards.** Files only below `/upload` (a folder the user mounts read-only; without it a post with an
image says how to mount it). The path is checked as text first: absolute, below `/upload`, no `.` or `..` parts, no
hidden names, no control characters, `.jpg`, `.jpeg`, `.png` or `.webp`. Then `/upload` and every folder on the way
are opened with `O_NOFOLLOW | O_DIRECTORY` relative to the one before (a link anywhere, `/upload` itself included, is
refused), the file is looked at with `lstat` (only a regular file: no link, folder, device, pipe or socket), opened
with `O_NOFOLLOW | O_NONBLOCK | O_NOCTTY` and checked again with `fstat` (the same inode; owned by the server's own
user - the user's own files under sandbox-ai's Podman `--user=0:0` and its Bubblewrap `--uid`; exactly one name;
not empty; at most 1,000,000 bytes, the lexicon's `maxSize`) and read once with `pread`. The content must be the
type its extension says (JPEG, PNG or WebP by their signatures). **Metadata is removed before the upload**, because
the PDS keeps the uploaded blob as it is and serves it to anyone (`com.atproto.sync.getBlob`), even where the app
shows a re-encoded copy. Only what the picture needs stays (since the independent review, finding 1): JPEG - every
APPn segment but JFIF/JFXX (APP0), the ICC profile (APP2) and Adobe's colour transform (APP14) goes (EXIF with a
camera's GPS position and XMP in APP1, IPTC in APP13, a C2PA manifest in APP11, GoPro's APP6, MPF, Ducky, ...), and
comments, segment by segment, across every scan of a progressive JPEG, and anything after the end-of-image marker (a
phone's "motion photo" video, for one); PNG - every chunk but the critical, colour, transparency, pixel-size and APNG
ones goes (`eXIf`, `tEXt`, `zTXt`, `iTXt`, `tIME`, C2PA's `caBX`, private chunks), and anything after `IEND`; WebP -
every chunk but `VP8X`, `VP8 `, `VP8L`, `ALPH`, `ANIM`, `ANMF` and `ICCP` goes (`EXIF`, `XMP `, `C2PA`, unknown ones;
the VP8X flags cleared, the RIFF size rewritten), and anything after the RIFF. Colour profiles and Adobe's APP14 stay
(they change how the pixels look); what was removed is named once per kind. An image whose EXIF orientation is not 1 is refused (it would show
turned once the EXIF is gone: "save it upright first"). Width and height come from the header (JPEG SOFn, PNG IHDR,
WebP VP8X/VP8/VP8L) into `aspectRatio`. Alt text is required for every image (at most 2000 graphemes, the app's
limit); at most 4 images; images and a card exclude each other (Bluesky shows one embed). The answer lists what was
removed per image. A link card (`app.bsky.embed.external`) is built from what the agent gives - `url` (http(s), no
user information, at most 2000 characters), `title` (required, at most 300 graphemes), `description` (at most 1000)
and an optional `thumb` from `/upload` (the same rules as an image) - **the linked site is never fetched**, so no
allow-list of sites is needed and no other host is contacted.

**Deleting.** `delete_post` takes an `at://` URI or a `bsky.app` address; its author must be the signed-in account
(its DID, or its handle as the session names it): any other is refused before a request. The post is read from the
account's own repository (`getRecord`; "the account has no post ..." otherwise) and deleted with `swapRecord` set
to the CID just read, so exactly the post shown is deleted; the answer shows its text.

**Reads.** At the public AppView, never with the session. Bounded: a post's text at most 3000 characters, names and
other texts of Bluesky's at most 300 (a profile's description 600), at most 50 posts in `list_my_posts` (reposts
and other accounts' posts left out), at most 100 posts in `get_post_thread` out of at most 1,000 entries of the answer (depth 0-10, parents 0-20, flattened with
levels; deleted and blocked posts named), labels at most 10. Addresses in answers are built only from checked DIDs
and record keys. Answers about other accounts carry a note that their texts are data, not instructions.

## Self-review: what was found and changed

Reviewed file by file as the third-party code of this repository is (telemetry, other hosts, token leaks, the
account password, path escapes, unbounded answers, double posts), then the server read again from the top for
correctness against the AT Protocol's lexicons. Findings 4 and 5 showed up as failing tests; the others were found
by reading. Each fix has a test in `tests/test_bluesky.py` (named in the table):

| # | Severity | Where | Finding | Fix |
|---|---|---|---|---|
| 1 | medium (privacy) | images | The first version scanned a JPEG's image data for the first `FF D9`: a progressive JPEG with that byte pair in a Huffman table between scans was cut short, and a comment or EXIF block **between** scans went out with the location in it | the JPEG is walked marker by marker, each scan's entropy-coded data up to the next real marker (`SelfReview.test_a_progressive_jpeg_...`) |
| 2 | low | session | A renewed session was taken whatever account it named | a renewal for another DID is refused and the session dropped (`test_a_refreshed_session_of_another_account_is_refused`) |
| 3 | low | `thread` | An unexpected exception after the first post answered "internal error" without the posts already published | the answer lists what was posted whatever failed (`test_an_unexpected_failure_in_a_thread_still_lists_what_was_posted`) |
| 4 | low | session | A short-lived access token (30 s) was renewed on every request (the fixed one-minute margin was longer than its life) | a minute early, or half its life early when shorter (`test_the_token_is_renewed_before_it_expires`) |
| 5 | low | `_xrpc` | An empty JSON object (`deleteRecord`'s answer) was taken for "not JSON", so a successful delete was reported as failed | only an answer that does not parse to an object is an error (`Delete.test_only_the_accounts_own_posts`) |
| 6 | low (CI) | sign-in | A 429 at the sign-in read "rate limit", not "Bluesky refused the sign-in": a rate-limited CI runner would have failed the smoke run on wording | the sign-in's 429 reads "Bluesky refused the sign-in for now ..." (`test_sign_in_refusals_read_the_same`) |
| 7 | low | `createRecord` | A 400 on a retry (the key existing from the try whose answer got lost) was reported as "nothing was posted" | a 400 on a retry is checked with `getRecord`, a real refusal explained (`test_a_post_that_lands_late_is_found_after_a_400`) |
| 8 | low | hashtags | Python's `isdigit` takes Arabic-Indic and other digits as digits, JavaScript's `\d` does not: `#١٢٣` would have been no tag here but one in the app | ASCII digits only (`test_facet_rules_like_the_app`) |
| 9 | cosmetic | links | The app drops a final `)` only when the link has no `(` at all, so `(see https://x/(a))` kept both | any `)` without its `(` is left out (`test_facet_rules_like_the_app`) |
| 10 | reviewability | source | Invisible characters (U+2028, U+2029, a soft hyphen, ZWJ, the variation selector) stood literally in strings | written as `\u` escapes; the source is ASCII only |

**Found clean:** every request passes the host check, the `Authorization` header only to the PDS; no token,
password or app-password-shaped text reaches an answer or a log line (tests with Bluesky echoing tokens in its error
messages); the account password is never sent (shape check) and never used (scope check, session ended); the write
switch is checked before any file or request; every file is opened without following links; a post is not
duplicated after a lost answer; every answer and loop is bounded (3 tries, 30 s per wait, 3 feed pages, 100 thread
posts, 20 mention lookups, 4 MiB per answer). No `eval`, `exec`, `pickle`, `marshal`, `subprocess`, sockets or
`ctypes`.

**Decisions** (not findings): the write tools stay listed when writing is off (see *Write mode*); no link-card fetching
at all instead of an allow-list of sites (the agent knows its article's title and description; fetching would add
hosts and an SSRF surface); no automatic switch to the PDS named in the DID document (see *Where the account lives*);
a privileged app password is refused, not just warned about (least privilege: no tool reads direct messages);
images are cleaned, not refused, when they carry metadata (the agent's own screenshots and photos should just work).

**Remaining risks** (accepted): (a) an app password can post, delete posts, follow, block and change the profile;
the server offers only posting and deleting the account's own posts, the approvals are the guard, and the token
never leaves the container. (b) Posts are public at once; what is posted is what the agent wrote and the human
approved (the approval shows the arguments, not the images' pixels). (c) The reads use the public AppView: an account
that asked Bluesky to hide it from logged-out viewers may be missing from them. (d) The redaction of app-password
shapes also hides such text in posts the server returns (cosmetic). (e) Should Bluesky change the app-password format
or the session scopes, the server refuses to sign in (fails closed) until it is updated. (f) The entryway
`bsky.social` serves Bluesky-hosted accounts by forwarding to their PDS; should Bluesky stop that, `BLUESKY_PDS` set
to the account's PDS (shown by `get_profile`) works, and the catalog's host would need that host. (g) EXIF in XMP
(`tiff:Orientation`) is removed without being read; ICC profiles stay; what the pixels show is not checked. (h) The
grapheme count follows Python's `unicodedata` (Unicode 15.1 in the image's Python 3.13) and lacks GB9c: a character
newer than that, or an Indic conjunct, may count differently from Bluesky's - one way only for GB9c (more here),
either way for unassigned code points (rare). (i) sandbox-ai gives the allowlist entry the full network, so the host
check in `_send` is the boundary. (j) Nothing was run against the live service; the smoke run reaches only
`createSession` with a name no one can register.

**Limits:** none beyond sandbox-ai's defaults (512m memory, 128 processes, a 64m /tmp): a thread holds at most 40
images of 1 MB in memory and nothing is written to /tmp, so `smoke.json` sets none.

## Tested

- `tests/test_bluesky.py` (no network; a fake PDS and AppView as an httpx transport, every credential-shaped value
  made at run time): the sign-in once per connection and kept, an expired token refreshed once, renewal before the
  token's `exp`, a refused refresh signing in again, the account password's and a privileged or unknown session
  refused and ended, every sign-in refusal reading the same (401, 400, 403, 2FA, takedown, 429, 500), missing and
  malformed credentials and `BLUESKY_PDS` (nothing sent), a DID and an own PDS; the write switch (`""`, `0`, `true`,
  `yes` all refuse; reads still work); facets with emoji, a skin tone, umlauts, CJK, an en dash and a flag checked by
  slicing the UTF-8 bytes at each facet's offsets; the facet rules; the 300-grapheme and 3000-byte limits (emoji,
  combining accents, family emoji); replies (root and parent) and refused addresses; link cards without a request to
  the site; images (JPEG with EXIF GPS, XMP, a comment and a motion-photo trailer; PNG with `eXIf`, `tEXt` and a
  trailer; WebP with `EXIF` and `XMP `) cleaned with their aspect ratios, and every refused image (no alt, 5 images,
  too large, turned by EXIF, wrong type, not an image, images with a card); a lost answer not posted twice, retried
  5xx, given-up retries; rate limits waited for or named; threads (root and parent chain, languages, the root under a
  reply, everything checked before the first post, a failure in between); deleting only the account's own posts,
  with `swapRecord`; profiles, the feed without reposts, a flattened and bounded thread; no secret in answers, errors
  or logs; every path refusal (outside, `..`, hidden, links, a linked folder, a linked `/upload`, a pipe, a device, a
  folder, hard links, another user's file, empty, nothing mounted); the grapheme count; the tool list against
  `tools.json`; the independent review's findings (class `IndependentReview`). 49 tests.
- `tests/test_own_servers.py` `test_bluesky`: the server over stdio (tools, the write switch, a path outside
  `/upload`, no credentials), then all of the above inside the image in CI (its Python and libraries, no network).
- `tests/test_analysis_servers.py` `Bluesky`: the shared lock, the imports, the two hosts, the secret flags, the write
  switch and ruleset in `tools.json`, the smoke spec.
- `smoke.json`, without an account: a handle under `.example` (which no one can register) and an app-password-shaped
  placeholder, so the one real call (`get_profile`) reaches `createSession` at `bsky.social` through the run line's
  network and Bluesky refuses it (expected: "Bluesky refused the sign-in", which every 4xx and a 429 give; a
  connection that fails gives "not reachable", a 5xx "answered HTTP 5xx", so neither passes); the refused calls -
  `post`, `thread` and `delete_post` with `BLUESKY_WRITE` unset, an image outside `/upload`, `..`, an image without
  alt text, 301 graphemes, a `javascript:` card, a post address on another site, `n` out of range.

## Independent review, 2026-11-13

A second reviewer, not the builder, read the server again from scratch for backdoors and bad code, without relying
on the self-review above. Threat model: a prompt-injected agent calls the tools with any arguments; the PDS or the
AppView answers anything (within TLS); a crafted image file lies in `/upload`. Line numbers below are those of the
reviewed commit `b8dbda1`.

**Read line by line:** `src/server.py` (1,707 lines), `Dockerfile` (27), `server.json` (58), `smoke.json` (133),
`tools.json` (31), `requirements.in` (1), `requirements.txt` (586: identical to youtube's and web-fetch's but for the
`# via` line), both `LICENSES/` files (21 and 26 lines, byte-identical to youtube's), this file (253),
`tests/test_bluesky.py` (955), and the branch's diff against `main` of `tests/test_analysis_servers.py` (+68),
`tests/test_own_servers.py` (+27), `.github/workflows/build.yml` (one matrix entry), `catalog.json` (+65, the entry
generated from `server.json`, pending), `digests.json` (+1, `null`), `README.md` (+65) and `SECURITY.md` (+4).
**Read for context:** httpx 0.28.1 (`trust_env`: proxies and `SSL_CERT_*`; netrc only through an explicit
`NetRCAuth`; no brotli or zstd decoder in the lock), `scripts/smoke_test.py` (substring match, per-call timeout,
default 120 s), the AT Protocol PDS's session scopes (`com.atproto.access`, `appPass`, `appPassPrivileged`, `refresh`,
`takendown`, `signupQueued`), and sandbox-ai's approval text for an MCP call (`approvals.py`, `shown`).
**Scanned:** no `eval`/`exec`/`pickle`/`marshal`/`subprocess`/sockets/`ctypes`; the source is ASCII only; every URL
is the PDS, `public.api.bsky.app`, or a `bsky.app` link put into an answer. **Fuzzed:** the three image parsers with
90,000 mutated files (no exception but the documented refusal, none slower than 50 ms) and hand-made worst cases
(1 MB of `FF` fill bytes, of restart markers, of empty segments and chunks: each under 0.2 s, memory bounded by the
file). The validators' regular expressions were tried with backtracking inputs (no case over a millisecond).

### Findings (all fixed test-first: each test in `IndependentReview` failed before the fix)

| # | Severity | Where (at `b8dbda1`) | Scenario | Status |
|---|---|---|---|---|
| 1 | **low-medium** (privacy) | `server.py` 640-651 `_jpeg`, 673-679 `_png`, 710-720 `_webp` | Metadata was removed by a list of what to drop: APP1, APP13 and comments of a JPEG, `eXIf` and text chunks of a PNG, `EXIF`/`XMP ` of a WebP. Everything else went out as it was, readable by anyone at `getBlob`: a C2PA manifest (JPEG APP11 JUMBF, PNG `caBX`, WebP `C2PA` - cameras and phones that sign their photos write one, and it can carry the camera's EXIF, location included, and the signer's identity), GoPro's APP6, MPF, Ducky, PNG `tIME`, private chunks | CONFIRMED with crafted files (`test_metadata_in_other_segments_and_chunks_is_removed_too`); that a given camera puts its location there is plausible, not shown. Fixed |
| 2 | low | `server.py` 1691-1701 `get_post_thread` | The replies were taken off the front of a list (`pop(0)`, quadratic), all of them, whatever the limit of 100 rows: an AppView answer of 1,000,000 empty replies (3.8 MiB, under the 4 MiB limit) held the server's event loop - every other call included - for 128 s | CONFIRMED (`test_a_huge_thread_answer_is_walked_in_bounded_time`: 18.9 s for 400,000 before, 0.3 s after with the fake's own encoding), fixed |
| 3 | low | `server.py` 232-277 `grapheme_clusters` (used by 307, 777, 805, 814) | A cluster grew by `+=` while the list held it (quadratic): one letter with 1,000,000 combining accents in a post's text, an alt text or a card's title or description held the event loop for 159 s before anything was refused | CONFIRMED (`test_long_texts_are_counted_in_linear_time`), fixed |
| 4 | low | `server.py` 286-293 `_no_controls` | Invisible text was taken: Unicode tag characters (each an invisible copy of an ASCII character), runs of variation selectors (any bytes after an emoji) and bidi override/isolate controls. A prompt-injected agent could post text the user does not see - in an approval view that renders Unicode, and in the published post - such as data taken from the sandbox. sandbox-ai's own question text escapes every non-ASCII character, which shows them | CONFIRMED (`test_invisible_text_is_refused`: posted before), fixed |
| 5 | low | `server.py` 657, 725 | What was removed from an image was listed per segment: a 1 MB WebP of 120,000 empty `EXIF` chunks gave an answer of 120,000 names (about 1 MB) | CONFIRMED (`test_what_was_removed_is_named_once`), fixed |
| 6 | low (CI) | `smoke.json` call 1 | The one real call had a 60 s timeout, but a sign-in rate limit that resets within 30 s is waited for twice before the server answers "Bluesky refused the sign-in for now": the harness would have timed out first and failed a server that works | CONFIRMED by arithmetic (`test_the_smoke_call_outlasts_two_rate_limit_waits`), fixed |
| 7 | info | `server.py` 961-967 `_rate_wait` | `str.isdigit` takes `²` and Arabic-Indic digits: a `retry-after: ²` (or a number of 5,000 digits) answered "internal error (ValueError)" instead of backing off, `ratelimit-reset: ١` waited 0.5 s instead of backing off | CONFIRMED (`test_rate_limit_headers_that_are_not_plain_numbers`), fixed |

**Fixes.** (1) The parsers keep only what the picture needs: a JPEG's JFIF/JFXX APP0, ICC APP2 and Adobe APP14 (by
their identifiers; every other APPn, comments and the trailer go); a PNG's critical, colour, transparency,
pixel-size and APNG chunks; a WebP's `VP8X`, `VP8 `, `VP8L`, `ALPH`, `ANIM`, `ANMF`, `ICCP`. (2) A `deque`, at most
1,000 entries of the answer looked at (`MAX_THREAD_NODES`), every reply list cut at that length (the answer
then says `truncated`); a `replies` that is not a list is ignored. (3) Clusters are found by their start indices and sliced once; a post's text of more than
12,000 bytes is refused without being counted. (4) `_no_hidden_text` (called by `_no_controls`, so for texts, alt
texts, card fields, URLs and paths): tag characters only as an emoji flag's (U+1F3F4, U+E0020-U+E007E, U+E007F), no
two variation selectors in a row, no U+202A-U+202E or U+2066-U+2069. Emoji, the flags of England or Scotland,
keycaps, skin tones, ZWJ sequences, Hebrew with an RLM still work (tested). (5) Each kind is named once. (6) 120 s.
(7) ASCII digits only, at most 12.

**Questions of the brief, answered.**
*Credentials.* The app password is read from the environment only when needed, refused before sending unless it
has an app password's shape, and sent only in `createSession`'s body to the PDS. The scope is read from the access
token's payload (the second dot-separated part, base64url, JSON): exactly `com.atproto.appPass` is taken, and the
subject must be the session's DID; `com.atproto.access`, `appPassPrivileged`, `takendown`, a token that is not a JWT
(no claims) and anything unknown are refused and ended with `deleteSession` (the refresh token, to the PDS). The
claim is not verified, and needs no verification: only the PDS, over verified TLS, gives the token, and a PDS that
lied about it would hold the account anyway; no other answer (AppView, `getRecord`) can touch the session. A refresh
is checked the same way and must keep the DID. Tokens, also refused ones, are added to the redaction before
anything else is done with them; every answer passes `scrub`, every error `redact`, every log line the one
redacting handler (`force=True`; mcp's own `basicConfig` then does nothing), the excepthook logs a type only.
*Hosts.* Every request goes through `_send` and `_checked_url`: `https`, the host exactly the PDS's or
`public.api.bsky.app`, port 443, no user information; an `Authorization` header only to the PDS host (refresh and
`deleteSession` included). No redirect is followed. URLs are built from constants and the checked `BLUESKY_PDS`
only (arguments go into `params` or JSON bodies). Handles are resolved at the AppView without the session; the DID
document's PDS is shown, never used. *Write guard.* `post`, `thread` and `delete_post` check `BLUESKY_WRITE == "1"`
after their own argument checks and before the credentials, any file and any request. *Delete.* The at-URI's
authority must equal the session's DID (case-sensitive; `did:PLC:`, a percent-encoded or other DID fails) or its
handle (lower-cased on both sides); and whatever the authority, `getRecord` and `deleteRecord` name the session's own
DID as `repo`, so no other repository can be touched, and `swapRecord` pins the CID just read. *Facets.* Offsets
come from the UTF-8 encoding of the text the record carries; lone surrogates are refused; a link facet is only
`http(s)://` with a host that has a dot (no `javascript:` or `data:`), a card URL the same; at most 2,000
characters. *Images.* The path rules hold (the `openat` chain with `O_NOFOLLOW`, `lstat`, `O_NONBLOCK | O_NOCTTY`,
`fstat`: same inode, own user, one name, size); every parser loop advances on each step and reads only within the
1 MB file; nothing is decompressed; an EXIF orientation other than 1 is refused. *Threads.* Everything is checked,
and every file read, before the first post; a failure in between names what was posted. *Idempotency.* The record
key is chosen before the first try, a lost answer (no connection, 500-504, a 400 on a retry) is looked up with an
unauthenticated `getRecord` of the own repository before a retry; at most 3 tries. *Retries and rate limits.* At
most 3 tries per request (429, 502-504, a broken connection; a request that may have been carried out only when
safe), at most 30 s per wait, one renewal per request. *Answer sizes.* 4 MiB per answer (a gzip chunk can expand to
about 64 MiB before the check, within the 512 MiB limit), every text in an answer bounded. *MCP.* FastMCP over stdio;
nothing but MCP on stdout. *Pins.* The lock is the one youtube, gowitness and whatweb ship (cut-off 2026-10-23,
21 days, so the 14-day rule holds), hash-checked, wheels only; the base digest and Debian versions are theirs; pip and
the venv tooling are removed; user 10001; `python -I -u`. *Smoke spec.* The real call expects "Bluesky refused the
sign-in", which every 4xx, a 2FA refusal, a takedown and a 429 give, but not a 5xx or no connection; with finding 6
it outlasts two rate-limit waits.

**Remaining risks** (accepted, in addition to (a)-(j) above). (k) Steganography in visible text (a zero-width space
here and there, look-alike letters, word choice) still carries a few bits per post; only the high-bandwidth
invisible channels are closed. (l) sandbox-ai's question for an MCP call shows the first 300 characters of the
arguments: the rest of a long post, of a thread, is not in that text (sandbox-ai, not this server; worth a look
there). (m) A `deleteRecord` retried after a 502-504 whose delete went through reports the second try's refusal
("the post changed in the meantime" or "no such record") although the post is gone (misleading, not harmful).
(n) With wrong credentials every call signs in again, so a looping agent can use up the account's 30 sign-ins in 5
minutes (the account itself stays usable from elsewhere). (o) An `ANMF` frame of an animated WebP is kept whole,
with any unknown chunk inside it. (p) The JWT claims are not verified (see above). (q) The smoke spec's placeholder
`smok-etes-tonl-y000` has an app password's shape (it must, to reach Bluesky); GitHub's push protection has no
Bluesky pattern as far as this review knows. (r) Nothing was run against the live service.

**Tested here:** `tests/test_bluesky.py` 49 tests (42 + 7 new) with mcp 1.30.0 and httpx 0.28.1 of the lock
(Python 3.11; the image has 3.13); `tests/test_own_servers.py` `test_bluesky` (the server over stdio); the whole
suite (`SANDBOX_AI_CHECKOUT=... python -m unittest discover -s tests`: 297 tests OK, 42 skipped);
`scripts/make_catalog.py --check --allow-pending --sandbox-ai` OK (bluesky pending its first digest).

**Verdict: fit to sign - yes**, once CI has built the image from this tree and both sandbox-ai smoke reports
(Podman, Bubblewrap) have passed. No backdoor, telemetry, other host or path for the app password or a token was
found; the scope check reads the right claim and fails closed; deletes cannot leave the account's own repository.
The seven findings are fixed and the remaining risks are listed above.
