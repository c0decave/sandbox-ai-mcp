# reddit (prepared) - provenance and audit notes

| | |
|---|---|
| MCP server | karanb192/reddit-mcp-buddy = npm `reddit-mcp-buddy` 1.1.14 (MIT, `LICENSE` "Copyright (c) 2025 Karan Bansal"), published 2026-07-29 (100 days before this audit, see the pinning rule in `docs/CANDIDATES.md`) from commit `dfd3f0941a0ae18ef108a9f7788dd0f350d610b3` (2026-07-29; npm provenance, SLSA v1, `.github/workflows/publish-mcp.yml`, `refs/tags/v1.1.14` at that time). The tag `v1.1.14` was moved afterwards to `e2d3f3fa1ab281a1ef872eeaea86134bbad2c7ec` (tag message: "retagged on registry publish fixes (#67, #68)"); between the two commits only `.github/workflows/` and `server.json` differ, so this pins the commit the provenance names, not the tag |
| Package | `https://registry.npmjs.org/reddit-mcp-buddy/-/reddit-mcp-buddy-1.1.14.tgz`, integrity `sha512-+O1+W5dcGiY5iwtHG4+dYOS9w+nhPtL2vGqT9+Qtp0Q4ymdfQZhznJc6+27O/PHt/FShBTmOjhj3+Y49cKUU7Q==`, SHA-256 `99bc1559908ea66993bd760924e678fcff964dc37b041c80f6b86690fbacd9af` (both checked against the download; the provenance subject has the same SHA-512); 47 files, prebuilt `dist/` (12 modules, the same set as `src/`), `README.md`, `LICENSE`, `package.json` |
| Dependencies | `@modelcontextprotocol/sdk` `^1.29.0` (locked 1.29.0), `zod` `^3.23.8` (locked 3.25.76), `zod-to-json-schema` `^3.24.6` (locked 3.25.2): `npm ci --omit=dev --ignore-scripts` with the `package-lock.json` of the commit above (SHA-256 `b152ed9d876b6c691015c5aa23a59d166b1b6331daa8b0d4133d9eb8fd176459`; lockfileVersion 3, 248 packages, 95 for production, every one from registry.npmjs.org with an integrity hash; install scripts only in the dev packages esbuild and fsevents, none in production; production licences MIT 85, ISC 7, BSD-3-Clause 2, BSD-2-Clause 1). Written on the release day, so every locked version is older than the release |
| Node.js, npm, git | Debian `nodejs` `20.19.2+dfsg-1+deb13u3` (the package needs >= 18, no production package more than that), `npm` `9.2.0~ds1-3`, `git` `1:2.47.3-0+deb13u1` (npm and git in the build stage only) |

**State:** not built. The pins are filled; the build has not been run. Re-pinned from 1.2.0
(published 2026-11-02, too new under the pinning rule) to 1.1.14, the newest release that is
at least 14 days old (1.1.13 is of 2026-05-26). `dist/` was compared with `src/` of the commit
by module set, by every `fetch(` and `process.env` use and by every URL (the same); it was not
recompiled.

**What it is:** a read-only Reddit client of about 4,300 lines of TypeScript. Without
credentials it reads the public RSS (Atom) feeds of subreddits; with an app's client id and
secret it uses Reddit's official OAuth API (`client_credentials` grant, app-only); with a
username and password (script app) it reads as that account (password grant). In-memory cache
(50 MB, TTL 5-15 minutes) and a local rate limit (10, 60 or 100 requests per minute by mode).

**Tools** (`src/mcp-server.ts`, `src/tools/index.ts`), all read (`readOnlyHint`); 1.1.14 has
**no write tools at all**: no posting, commenting, voting, editing, deleting or messaging. The
only non-GET request in the code is the OAuth token request.
- `browse_subreddit` (subreddit, sort, time, limit, include_nsfw, include_subreddit_info) ->
  `/r/{sub}/{sort}.json`, anonymously the `.rss` feed (no scores, comment counts or NSFW flag);
- `search_reddit` (query, subreddits, sort, time, limit, author, flair) -> `/search.json`,
  `/r/{sub}/search.json`;
- `get_post_details` (post_id or a reddit.com/redd.it URL, comment options) ->
  `/r/{sub}/comments/{id}.json`, `/api/info.json`; the URL is only parsed for the id, never
  fetched;
- `user_analysis` (username, limits, time range) -> `/user/{name}/about.json`,
  `/user/{name}/{submitted,comments}.json`;
- `reddit_explain` (term): offline glossary, no request.

Without credentials only `browse_subreddit` (RSS) and `reddit_explain` work; Reddit blocks the
logged-out JSON API.

Every identifier is checked against a pattern before it becomes part of a path (subreddit
`[A-Za-z0-9_]{2,21}` with `a+b` and `u_name`, username `[A-Za-z0-9_-]{3,20}`, post id base36
2-13; added in this release, #66), so a tool argument cannot steer the bearer token to another
endpoint; numeric arguments are bounded. The base hosts are constants.

**What is sent:** to `www.reddit.com`: `POST /api/v1/access_token` (Basic auth with client id
and secret, the grant in the body) and, anonymously, the GET requests above; to
`oauth.reddit.com`: the GET requests above with `Authorization: Bearer <token>`. Headers:
`User-Agent: $REDDIT_USER_AGENT` (default `RedditBuddy/1.0 (by /u/karanb192)`),
`Accept: application/json`, `Accept-Language: en-US,en;q=0.9`, `Cache-Control: no-cache`.
Errors go back to the agent as tool results (see the concerns for what they may contain).
Requests use Node's global `fetch` (undici), which in Node 20 does not honour `HTTPS_PROXY`.

**Telemetry:** none. No host other than `www.reddit.com` and `oauth.reddit.com` appears in the
code or `dist/` (the remaining URLs are help texts). The stdio parts of the MCP SDK make no
request; its HTTP server parts (express, hono, cors) are installed but loaded only with
`REDDIT_BUDDY_HTTP`.

**Files:** none needed. With credentials from the environment nothing is written. Without
them it tries to read `$HOME/.reddit-mcp-buddy/auth.json` (written only by the `--auth` CLI,
not part of this image; with `HOME=/tmp` it does not exist).

**Environment / secrets:**
- `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET` (secret): an approved Reddit app; both or
  neither (anonymous RSS mode).
- `REDDIT_USER_AGENT`: Reddit asks for a unique, descriptive one
  (`<platform>:<app id>:<version> (by /u/<username>)`); set it, the default names upstream's
  author.
- `REDDIT_USERNAME` + `REDDIT_PASSWORD` (secret): optional, only for the higher rate limit
  (100 instead of 60 per minute); the password grant gives a token with full account scope
  even though this release only reads. Not to be set for sandbox-ai. There is no
  refresh-token support in 1.1.14.
- `REDDIT_BUDDY_NO_CACHE`; the HTTP transport (`REDDIT_BUDDY_HTTP`, `_PORT`, `_HOST`
  (default `127.0.0.1`), `_ALLOWED_HOSTS`, `_ALLOWED_ORIGINS`) is not used here.

**Reddit's terms:** under Reddit's Responsible Builder Policy, API access needs an app that
Reddit has approved for the use case; creating one at https://www.reddit.com/prefs/apps is not
enough by itself. Free tier: 100 queries per minute per OAuth client id; unauthenticated
traffic is throttled per IP (RSS often one uncached request per 25-60 s). The User-Agent must
be unique and descriptive, a generic one gets throttled or blocked. The server's own cap (60 or
100 per minute) stays below Reddit's limit and honours `Retry-After` / `X-Ratelimit-Reset`
(each wait capped at 30 s, at most two retries).

**What changed in 1.2.0 that matters for security** (`git log dfd3f09..9f099fa`, 14 commits):
- 1.2.0 adds the opt-in write tools (`create_post`, `add_comment`, `subreddit_rules`),
  refresh-token login and an `--oauth` CLI that writes a token file. 1.1.14 has none of
  them: a smaller surface.
- Dependency advisories fixed by 1.2.0 (#87, #88), and whether they reach 1.1.14 over stdio:
  - `@modelcontextprotocol/sdk` 1.29.0: GHSA-f897-62hf-6gxq, -46jr-4wx8-v453, -rvq5-wwqv-78pq,
    -22jm-h49p-29qw, -6prh-2h8m-c8cw, -6qxp-vccf-f47h concern the HTTP transports, bearer
    auth, experimental tasks and the OAuth client; GHSA-46jr states that stdio-only servers
    are not affected, and 1.1.14 uses none of the others. Not reached.
  - body-parser 2.3.0, hono 4.12.31, `@hono/node-server` 1.19.14, qs 6.15.3, proxy-addr 2.0.7,
    ip-address 10.2.0: the HTTP stack, loaded only with `REDDIT_BUDDY_HTTP`. Not reached.
  - fast-uri 3.1.4 (ajv's URI parser; several host-confusion advisories): used for URI
    formats in JSON-schema validation; this server's schemas have no URI format. Not reached
    in practice.
  - zod 3.25.76: GHSA-mrhx-c7xc-m3w5 (high), memory exhaustion on a large array of failing
    elements. Reached: `tools/call` arguments are parsed with zod (`subreddits` is an
    array). Over stdio the only caller is the agent, so the effect is the agent crashing its
    own container; 1.2.0 also caps tool input at 1,000 elements/keys.
- Code hardening in #88 that 1.1.14 lacks:
  - a failed token request puts Reddit's raw response body into the error, and the error is
    not scrubbed of the client secret or password (Reddit's error bodies do not echo them;
    1.2.0 keeps only the OAuth error code and redacts the secrets);
  - an upstream API error body goes to the agent uncut (a whole HTML page; 1.2.0 cuts it to a
    200-character plain-text excerpt);
  - cache keys replace every character outside `[a-z0-9_-]` with `_`, so two queries that
    differ only there (`c++` and `c__`) share a cache entry and one gets the other's results;
  - a secret containing `$` or `${...}` is taken for an unresolved placeholder and silently
    dropped (the server then runs anonymously).
- #82: a long `Retry-After` blocks the call (up to 30 s per retry) instead of returning the
  wait. #81, #86: clearer messages for logged-out 403s. No other security change.

**Concerns:**
- Usefulness without approved credentials is small (one tool, RSS data without metrics); the
  approval is Reddit's decision.
- Not the newest release: the fixes above stay out until a later release is old enough. For
  sandbox-ai's stdio use the open points are the zod memory issue (the agent can crash its own
  container), the uncut error bodies and the cache-key collision; none of them reaches a
  secret or another host.
- The default User-Agent names upstream's author; the catalog should require
  `REDDIT_USER_AGENT`.
- Content from Reddit is untrusted text handed to the agent (prompt injection); the server
  does not mark or filter it.
- Single maintainer (884 stars, 7,300 npm downloads a month); the tag of this release was
  moved after publishing (CI-only difference, declared in the tag message).
- Node 20's `fetch` ignores `HTTPS_PROXY` (as with agentql).

**To check when building:** the build commands above (Debian npm 9.2 with a lockfile written by
a newer npm), the tools/list of 1.1.14 for `tools.json` (five read tools; the smoke test needs
no secret), that nothing is written outside `/tmp`, a live `browse_subreddit` over RSS, and the
proxy: with sandbox-ai's current `--network full` it works; under an allowlist proxy it needs a
preload that sets an undici `EnvHttpProxyAgent`, or Node >= 24 with `NODE_USE_ENV_PROXY=1`.
When a later release (1.2.0 or newer) is at least 14 days old, re-audit and move to it for the
fixes above; keep `REDDIT_BUDDY_WRITE` unset then.

**Network:** allowlist `www.reddit.com:443`, `oauth.reddit.com:443`.
