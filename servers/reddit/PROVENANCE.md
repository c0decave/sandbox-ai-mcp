# reddit - provenance and review

| | |
|---|---|
| MCP server | this repository, `src/server.py` (MIT), our own (2026-11-25): the four read tools of reddit-mcp-buddy over Reddit's OAuth API, app-only, read-only by construction |
| Upstream reviewed | karanb192/reddit-mcp-buddy **1.2.1** (MIT, `LICENSES/reddit-mcp-buddy-MIT.txt`), npm `reddit-mcp-buddy` 1.2.1 published 2026-11-10 17:07 UTC (14 days 18 hours before this review; 1.3.0 of 2026-11-11 09:02 too new), git head `59d533305139603b5b9cc6dd16460862b8f21c62`, tarball SHA-256 `1f1f09faf42d555db35a7c6ee783edb6bf4e0599211b760b6a4d7a8dafa9c6f3`, integrity `sha512-9H9TpmJTmekjUs9aFISVIVo31grhOqmuHWLjpLxiiBoMrFP7yTfLZgAieYbMS8tr6rUolD4UML94WRRaDfPslA==`. Not installed: see "The candidate's open review" |
| Python packages | `requirements.txt`: the shared lock of servers/duckduckgo (`mcp==1.30.0` and its dependencies, httpx among them; the same versions and hashes) - nothing new |
| Debian packages | `tini=0.19.0-3+b8` (the image's init, its ENTRYPOINT), `python3=3.13.5-1`, `ca-certificates=20250419+deb13u1` |
| Base image | the `debian:trixie-slim` digest in `Dockerfile` |

## The candidate's open review (candidates/reddit, docs/CANDIDATES.md)

The review of 2026-11-17 left reddit "not added yet - review not finished": the pinning rule asked for 1.2.0, which
adds write tools and an OAuth consent flow, on `@modelcontextprotocol/sdk` ^1.32.2 and zod 4 (the SDK 1.x closure,
about 95 npm packages, reviewed nowhere in this repository). Its way forward: "read 1.2.0 completely, review the SDK
1.32.2 stdio path (or port the read tools onto the shared Python lock as for agentql), keep the write tools off".
**Done here: the port.** The npm package stays out (its closure is unchanged in 1.2.1: `@modelcontextprotocol/sdk`
^1.32.2, `zod` ^4.6.7); `candidates/reddit` (1.1.14) is superseded by this server.

**What changed since the candidate:** Reddit ended logged-out access (its RSS feeds) on 2026-11-13 and stopped
accepting new API access requests on 2026-10-31 (upstream's `LOGGED_OUT_ENDED_MESSAGE`, 1.2.1); upstream now fails
every logged-out read without contacting Reddit. So this server has no anonymous mode at all: it needs an approved
app's id and secret.

**Read in full (5,576 lines of JavaScript in `dist/`, the read path):** `tools/index.js` (592: the schemas - the
identifier patterns are security boundaries, as its comments say - and the four read tools, the comment tree, the
local author/flair filters and their note), `services/reddit-api.js` read paths (`browseSubreddit`, the RSS fallback
and its Atom parser, `getPost` with `/api/info.json`, `search`, `getUser`, `getUserPosts`, `getSubreddit`, `get` with
its rate-limit and retry handling), `core/auth.js` (468: environment, client_credentials / password / refresh_token
grants, the token response checks, secrets redacted from errors; a token file `~/.reddit-mcp-buddy/auth.json` only for
its `--auth` CLI setup), `core/rate-limiter.js`, `core/cache.js`. **Skimmed** (not ported, off by default):
`tools/write.js`, `core/write-gate.js`, `services/write-errors.js` (posts, comments, `REDDIT_BUDDY_WRITE`),
`core/oauth-consent.js` (a local HTTP listener on `localhost` for the consent redirect, writes the refresh token),
`cli.js` (`child_process` only to open a browser for `--auth`).
**Hosts:** `www.reddit.com`, `oauth.reddit.com` (the rest are help links). **Telemetry:** none. **Update check:**
none. **Findings** (none a backdoor):

| Severity | Where | What | Here |
|---|---|---|---|
| medium | `auth.js` | the password grant gives a token with the full scope of the user's account (it only reads, but the token could write) | app-only `client_credentials` only: the token reads as the app |
| low | `reddit-api.js` | answers read without a size limit (Node's `fetch`), Node 20's `fetch` ignores `HTTPS_PROXY` (an allowlist proxy is bypassed or fails) | at most 8 MiB read; httpx honours `HTTPS_PROXY` |
| low | `tools/index.js` | `get_post_details` with a URL accepts any host's link with `/r/X/comments/ID` (it never fetches it, only takes the id) | only reddit.com, *.reddit.com and redd.it links |
| info | `reddit-api.js` | the default User-Agent names upstream's author | `REDDIT_USER_AGENT` required |

## This server

**Tools** (all `readOnlyHint`; after the token request only GET to `oauth.reddit.com`, each with `raw_json=1`):

| Tool | Requests |
|---|---|
| `browse_subreddit(subreddit, sort="hot", time?, limit=25, include_nsfw=false, include_subreddit_info=false)` | `/r/SUB/SORT?limit=&t=`, `/r/SUB/about` |
| `search_reddit(query, subreddits?, sort="relevance", time="all", limit=25, author?, flair?)` | `/search` or `/r/A+B/search?restrict_sr=true` (one request for several subreddits, upstream made one each) |
| `get_post_details(post_id? \| url?, subreddit?, comment_limit=20, comment_sort="best", comment_depth=3, max_top_comments=5)` | `/r/SUB/comments/ID` or `/comments/ID` (no `/api/info.json` lookup needed) |
| `user_analysis(username, posts_limit=10, comments_limit=10, time_range="month", top_subreddits_limit=10)` | `/user/NAME/about`, `/user/NAME/submitted`, `/user/NAME/comments` |

Upstream's offline glossary `reddit_explain` is not taken (no data from Reddit). **The token:** `POST
https://www.reddit.com/api/v1/access_token` with Basic `CLIENT_ID:SECRET` and `grant_type=client_credentials`, kept in
memory until a minute before it expires, renewed once after a 401; Reddit's error code (`invalid_client` ...) is said,
never its body; the secret and the token appear in no answer or error (tested). **Identifiers** with upstream's
patterns (subreddit `[A-Za-z0-9_]{2,21}` with `a+b` and `u_NAME`, user `[A-Za-z0-9_-]{3,20}`, post id base36 2-13)
before they become part of a path; everything else as query parameters. **Rate limit:** a 429 waits once when
Reddit's reset is at most 5 s away, else says when to try again. **Answers:** posts with 500 characters of text (a
post's details 4,000, comments 1,500), within 24,000 characters (cut from the end, said so).

**Requests:** httpx, TLS verified, no redirects, 20 s, at most 8 MiB read. **Network:** allowlist
`www.reddit.com:443`, `oauth.reddit.com:443`. **Secrets:** `REDDIT_CLIENT_SECRET`. **Files:** none.

## Tested

- `tests/test_reddit.py` (6 tests) against a stand-in of both hosts on loopback: the handshake and the message without
  credentials; the token request (Basic auth, the body, the User-Agent), the token kept and renewed after a 401, GETs
  only after it; browse (NSFW left out, texts cut, subreddit info, `t` only for top), search across two subreddits
  with the author/flair filter and its note, the query sent; a post by reddit.com URL, by redd.it and by `t3_` id, the
  comment tree to the depth asked, an injected instruction passed on as data; a user's activity and top subreddits;
  429/403/404, wrong credentials, an unreachable Reddit (no secret in any error); 18 hostile arguments and 2 bad
  settings with nothing sent; 100 long posts bounded to 24,000 characters.
- `tests/test_own_servers.py` `test_reddit` (in the image in CI, no network).
- `smoke.json`: the four tools with stand-in credentials and network none (each says it cannot reach
  `https://www.reddit.com`, the token request) and two refused arguments - 6/6 passed over stdio here. No real call:
  CI has no approved Reddit app; reddit.com is also blocked in the review sandbox.

## Risks left

- Not run against Reddit itself (no approved app here, and Reddit no longer approves new ones since 2026-10-31): the
  paths and fields are upstream's, which ran against the real API; a live check needs the user's own app.
- Reddit's terms are the user's to keep (an approved app, a descriptive User-Agent, the rate limit).
- Posts and comments are untrusted text (prompt injection; passed on as data).
