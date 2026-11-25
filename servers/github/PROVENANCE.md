# github - provenance and review

| | |
|---|---|
| MCP server | this repository, `src/server.py` (MIT), our own (2026-11-25): GitHub read-only over its REST API, 13 tools |
| Upstream | **none taken.** github/github-mcp-server v2.1.0 (MIT, tag commit `4bcdcdf8`, published 2026-11-03) was looked at and **not added** (docs/tier1-dev-reviews.md: a build links 315,705 lines of Go, every toolset is linked whatever `--toolsets` says, an embedded React UI built from 3,252 lines of npm lock). Only its idea - a few read tools named as it names them (`search_repositories`, `get_file_contents`, `list_issues`, `list_commits`, `get_commit`, `search_code`, `list_releases`, `list_workflow_runs`) - is used; no code |
| Service | GitHub's REST API, version `2022-11-28` (`X-GitHub-Api-Version`), at `https://api.github.com` or the Enterprise address in `GITHUB_API_URL`; documented at https://docs.github.com/en/rest |
| Python packages | `requirements.txt`: the shared lock of servers/duckduckgo (`mcp==1.30.0` and its dependencies, httpx 0.28.1 among them; the same versions and hashes) - nothing new |
| Debian packages | `tini=0.19.0-3+b8` (the image's init, its ENTRYPOINT), `python3=3.13.5-1`, `python3-venv=3.13.5-1` (purged after the venv is made), `ca-certificates=20250419+deb13u1` |
| Base image | the `debian:trixie-slim` digest in `Dockerfile` |

## Why our own

The user's choice of 2026-11-25 ("yeah add it") after the tier-1 review: github-mcp-server's complete review does
not fit (above), and agents mostly need to *read* GitHub - files at a ref, issues and pull requests with their
discussion and diff, commits, Actions failures, releases. A server that only knows GET requests is read-only by
construction, small enough to review in full (about 1,050 lines, this file and nothing else of ours), and runs on
the lock every own server of this repository shares.

## What it does

| Tool | Requests (all `GET`, under the API address) |
|---|---|
| `search_repositories(query, sort, page, per_page<=30)` | `/search/repositories?q=&sort=&order=desc&page=&per_page=` |
| `get_repository(owner, repo)` | `/repos/O/R` |
| `get_file_contents(owner, repo, path="", ref?, offset?)` | `/repos/O/R/contents[/PATH]?ref=`; a file above 1 MB (no inline content): the same with `Accept: application/vnd.github.raw+json`, at most 10 MiB read |
| `list_issues(owner, repo, state, labels?, sort, since?, page, per_page<=50)` | `/repos/O/R/issues?...` (pull requests in the answer are left out and counted) |
| `get_issue(owner, repo, issue_number, comments_page)` | `/repos/O/R/issues/N`, and `/repos/O/R/issues/N/comments?page=&per_page=30` when it has comments |
| `list_pull_requests(owner, repo, state, base_branch?, sort, page, per_page<=50)` | `/repos/O/R/pulls?...` |
| `get_pull_request(owner, repo, pull_number, section, page, offset?)` | overview: `/repos/O/R/pulls/N` + `/reviews?per_page=50`; files: `/pulls/N/files`; diff: `/pulls/N` with `Accept: application/vnd.github.diff` (16 MiB at most, parts of 20,000 characters); review_comments: `/pulls/N/comments`; comments: `/issues/N/comments` |
| `list_commits(owner, repo, ref?, path?, author?, since?, until?, page, per_page<=50)` | `/repos/O/R/commits?sha=&path=&author=&since=&until=` |
| `get_commit(owner, repo, ref, page)` | `/repos/O/R/commits/REF?page=&per_page=30` (REF one encoded segment: `releases/v1` is `releases%2Fv1`, which GitHub resolves - seen against api.github.com) |
| `search_code(query, page, per_page<=30)` | `/search/code` with `Accept: application/vnd.github.text-match+json`; without a token refused before anything is sent (GitHub answers 401 to it, checked against api.github.com) |
| `list_workflow_runs(owner, repo, workflow?, branch?, event?, status?, page, per_page<=50)` | `/repos/O/R/actions/runs` or `/repos/O/R/actions/workflows/FILE/runs` |
| `get_workflow_run_logs(owner, repo, run_id, job_id?, offset?)` | without job_id: `/repos/O/R/actions/runs/ID`, `/runs/ID/jobs?filter=latest&per_page=100`, and for at most 3 failed jobs `/repos/O/R/check-runs/JOB/annotations`; with job_id: `/repos/O/R/actions/jobs/JOB/logs` - a redirect to GitHub's storage, read up to 256 MiB / 60 s keeping the last 32 MiB, time stamps and terminal colours taken out, the last 20,000 characters by default with the `##[error]` lines |
| `list_releases(owner, repo, page, per_page<=30)` | `/repos/O/R/releases` |

Every answer is JSON text of at most 24,000 characters (a list shortened with a note saying how many were left out;
texts cut per field: an issue body 8,000, a comment 4,000, a patch 4,000, release notes 1,500 ...); pages and parts
say `next_page` / `next_offset` / `previous_offset`. All tools are annotated `readOnlyHint`, tools only (no
resources or prompts: `tools_only`). The instructions and the catalog notes say that what GitHub returns is data
written by others.

## Settings, secrets, network

- `GITHUB_TOKEN` (catalog secret, optional): one word of printable ASCII; sent as `Authorization: Bearer` **only to
  the API's own origin** (scheme, host, port) - a redirect elsewhere (the Actions storage) goes without it; never
  logged (the server logs only warnings, never a header or a URL with a query), replaced by `[GITHUB_TOKEN]` in any
  error text as a second lock. A fine-grained read-only token is advised (Contents, Issues, Pull requests, Actions,
  Metadata: read). Without one: public repositories only, 60 requests an hour per address, no code search, no
  Actions logs (GitHub answers 403 "Must have admin rights" to an anonymous log download - checked against
  api.github.com).
- `GITHUB_API_URL` (Enterprise): `https://` only, a host name, no user, query or fragment, path segments of
  `[A-Za-z0-9._~-]` without `.`/`..`; checked for every call.
- `GITHUB_CA_CERT`: only with `GITHUB_API_URL`; then that CA alone verifies the Enterprise Server.
- TLS always verified (httpx with certifi's CAs, or the given CA); `HTTPS_PROXY` honoured.
- Network: allowlist `api.github.com:443`. GitHub Enterprise needs `--network egress-all` (its address is the
  user's), one in the local network also `--allow-tcp`. Actions job logs lie on GitHub's storage
  (`productionresultssaN.blob.core.windows.net`, N open-ended: sa0 to sa70 resolve, more may come): an allowlist
  cannot name it, so logs need `--network egress-all`; the answer says so when the storage cannot be reached.

## Review of our code (2026-11-25)

Read in full; what it reads, writes and sends:

- **Sends:** GET requests to the API address and, after a redirect, to GitHub's own hosts only: the API host; for
  github.com `*.github.com`, `*.githubusercontent.com` and `productionresultssa<digits>.blob.core.windows.net`; for
  Enterprise the API host's own domain (`api.acme.ghe.com` -> `*.acme.ghe.com`). `https` only, at most 3 redirects,
  no user info in a target. A redirect anywhere else is refused before it is followed.
- **Reads:** its environment (the three settings); nothing on disk besides its own code and certifi's CA file.
- **Writes:** nothing (no file, no cache); no process is started; no telemetry, no update check, no dynamic code.
- **Paths:** owner `[A-Za-z0-9][A-Za-z0-9_-]{0,99}` (Enterprise managed users have `_`), repo `[A-Za-z0-9._-]{1,100}`
  but not `.`/`..`, each percent-encoded into one segment; a file path split at `/`, every segment non-empty and not
  `.`/`..`, each encoded; a ref after git's own rules (`check-ref-format`: no `..`, `@{`, `//`, control characters,
  spaces, `~^:?*[\`, no leading `-`/`/`, no part starting with `.`, no `.lock`), one encoded segment in a path or a
  query parameter; numbers whole and positive (`true` refused); dates `YYYY-MM-DD[THH:MM[:SS]Z]`; searches one line
  of at most 256 characters (GitHub's limit); a workflow a `.yml`/`.yaml` file name or an id; labels at most 10.
- **Bounds:** JSON 8 MiB, a file 10 MiB, a diff 16 MiB, a log 256 MiB read / 32 MiB kept / 60 s; 20 s per request.
- **Rate limits:** the `x-ratelimit-*` headers of every API answer are kept per resource (core, search,
  code_search); a used-up limit is not asked again before its reset (the answer says until when, and without a token
  that a token gives 5,000 an hour); a 403/429 with `retry-after` (secondary limit) says how long to wait; an answer
  while 10 % or less is left carries a `rate_limit` note.
- **Errors** name the API URL and GitHub's status and message (cut to 400 characters) and what to do (a token, its
  permissions, section files for a diff GitHub will not make).

Found and fixed while writing it (tests first): an issue list mixes pull requests in (GitHub's issues API) - left
out and counted; a repository renamed answers 301 to `/repositories/ID` - followed on the same origin with the token;
a run that failed before any job started has no jobs (seen on api.github.com) - said in the answer.

## Tests

- `tests/test_github.py` (16) against a stand-in GitHub Enterprise on loopback over real TLS with a throwaway CA
  (`tests/tls_fake.py`, the same file as the ops servers'): every tool's request (path, query, `Accept`, the API
  version, the token) and answer; files in parts, raw above 1 MB, binary, above 10 MiB, a symlink, 3,000 entries
  bounded; issues without pull requests, comments paged; every pull-request section, a 406 diff; a branch with `/`;
  code search's media type and its refusal without a token; runs, jobs failed first with annotations, a job log
  redirected to a second stand-in (no `Authorization` there), its end by default, offsets; redirects to other hosts,
  to `http://` and to an unreachable storage; the rate limit used up (no request until its reset), `retry-after`,
  the low-limit note; 401/403/404 hints; TLS without the CA refused; 7 refused settings and 27 hostile arguments
  with nothing sent; after every test: only GETs, the token in no answer or error.
- `tests/test_own_servers.py` `test_github` (in the image in CI, no network).
- `smoke.json` (CI, network none, `GITHUB_API_URL=https://127.0.0.1:9`): every tool's call names its API path in
  the error (19 calls, each pull-request section and both forms of the log tool), and 4 refused calls.
- Against api.github.com without a token (here, 2026-11-25, about 15 requests): get_repository, get_file_contents (the
  top folder and `action.yml` at `releases/v1`), get_commit at `releases/v1`, list_commits, list_issues,
  list_releases, list_workflow_runs, get_workflow_run_logs (a run without jobs), list_pull_requests, a pull
  request's diff, search_repositories - all answered in the shapes the code expects.

## Risks left

- The token decides what can be read; even a read-only token lets the agent read every private repository it
  covers (choose its repositories).
- Issues, comments, code, commit messages, logs and release notes are third-party text (prompt injection possible;
  passed on as data, the presets' rules hold them untrusted where a preset adds rules).
- Actions logs and an Enterprise Server need `--network egress-all`; the server itself still follows redirects only
  to GitHub's hosts, but the sandbox's allowlist no longer pins it to them.
- An Enterprise Server whose logs lie on its own S3/Azure storage (another domain): those redirects are refused.
- Not run with a token here (no test token): code search, logs and private repositories against the real GitHub
  are for a live check.

## Later: writes (a design note, not built)

A `GITHUB_WRITE=1` switch could add a few write tools (comment on an issue or pull request, open an issue, open a
pull request from a pushed branch) as separate functions that send POST/PATCH only to their own fixed paths,
listed only with the switch, each asked by sandbox-ai's rules (the presets' rules files: writes asked), never
merges, deletions, workflow runs, secrets or repository settings; a fine-grained token with exactly those write
permissions. Until then the server has no code that sends anything but GET.
