# New server of 2026-11-25: github (our own, read-only)

The user, 2026-11-25, on the lead's proposal after the tier-1 review ("yeah add it"): instead of the official
github/github-mcp-server - not added by mcpnew-dev ([tier1-dev-reviews.md](tier1-dev-reviews.md): a build of v2.1.0
links 315,705 lines of Go, every toolset is linked whatever `--toolsets` says, an embedded React UI from 3,252 lines
of npm lock) - our own small read-only server over GitHub's REST API, on the shared reviewed lock like the ops and
data servers. The share of the agent mcpnew-github. Rules as in [round2-reviews.md](round2-reviews.md) and the
hardening round's: the whole code that runs reviewed, nothing new pinned (no dependency beyond the lock), no
telemetry, no install script, no auto-update, tools only, answers within 24,000 characters, hostile inputs tested,
tini as ENTRYPOINT, a smoke call for every tool. Nothing here is signed or published: a **pending** catalog entry
(digest `null` in `digests.json`) until CI has built it, its smoke reports pass and the catalog is signed with the
human.

## Overview

| Server | Verdict | Source | Network | Secret | Tools (smoked) | stdio here |
|---|---|---|---|---|---|---|
| [github](../servers/github) | **added, pending** (own); github-mcp-server stays out | our `src/server.py` (about 1,050 lines), `mcp==1.30.0` + httpx of the shared lock | allowlist `api.github.com:443` (logs and Enterprise: `--network egress-all`) | `GITHUB_TOKEN` (optional) | 13 (13, offline: each names its API path) | smoke 23/23, stand-in 14/14 calls, 15 tools' tests 16/16 |

## github - added (pending)

| | |
|---|---|
| Verdict | **added**, pending signature |
| Tools | `search_repositories`, `get_repository`, `get_file_contents` (a file at any ref in parts of 20,000 characters, raw above 1 MB, at most 10 MiB, binary files by size only; or a folder's entries), `list_issues` (pull requests left out), `get_issue` (with comments, 30 a page), `list_pull_requests`, `get_pull_request` (`section`: overview with reviews, files with patches, the diff in parts, review comments, comments), `list_commits`, `get_commit` (patches, 30 files a page), `search_code` (needs a token: text-match fragments), `list_workflow_runs`, `get_workflow_run_logs` (a run's jobs failed first with failed steps and GitHub's annotations; a job's log: its end by default, time stamps and colours out, the `##[error]` lines), `list_releases`. All `readOnlyHint`; the tool list is 11 KB of JSON (small for local models) |
| Read-only | by construction: the code has one request function and it sends `GET` only; no write tool exists. A `GITHUB_WRITE` switch is only a design note (PROVENANCE.md) |
| Token | `GITHUB_TOKEN`, optional catalog secret; sent only to the API's own origin (scheme, host, port) - not to the storage a job log is redirected to; never logged or answered (and scrubbed from error texts). Fine-grained read-only advised. Without one: 60 requests an hour per address (the instructions, the errors and the notes say so), no code search, no Actions logs |
| Enterprise | `GITHUB_API_URL` (`https://` only, checked), `GITHUB_CA_CERT` for a private CA; the catalog's allowlist names only api.github.com, so Enterprise needs `--network egress-all` (and `--allow-tcp` for one in the LAN) - the entry's notes and the variable's description say so |
| Path parts | owner, repo, ref and path each become exactly their own URL segments (encoded; `.`/`..`/empty segments refused; refs after git's `check-ref-format`); numbers, dates, searches, labels, workflow names checked; 27 hostile arguments refused with nothing sent |
| Redirects | at most 3, `https` only, only to GitHub's hosts: the API host; for github.com `*.github.com`, `*.githubusercontent.com`, `productionresultssaN.blob.core.windows.net` (the Actions results storage); for Enterprise the API host's own domain |
| Bounds | JSON 8 MiB, file 10 MiB, diff 16 MiB, log 256 MiB read / 32 MiB kept / 60 s, 20 s per request; every answer at most 24,000 characters (lists shortened with a note, texts cut per field) |
| Rate limits | `x-ratelimit-*` kept per resource; a used-up one is not asked again before its reset (the answer says until when and that a token gives 5,000/h); `retry-after` said; a low limit (10 % left) noted in answers |
| Found while building | issues API mixes pull requests in (left out, counted); a renamed repository answers 301 (followed on the same origin); a run that failed before its jobs started has none (said); an anonymous log download answers 403 "Must have admin rights" (a token is needed: said); code search answers 401 without a token (refused before sending) |
| Tests | `tests/test_github.py` 16 against a stand-in Enterprise over real TLS (tests/tls_fake.py, the file the ops servers brought - the same bytes); `tests/test_own_servers.py` `test_github` |
| Tor | **limited**: HTTPS over TCP works through Tor; without a token the per-address limit of 60/h is shared with everyone on the exit (often used up) - give a token; an Enterprise Server in the LAN cannot be reached through Tor. Not run behind Tor here |
| Risks left | the token's reach decides what the agent can read; GitHub content is third-party text (prompt injection: data, not instructions); logs need egress-all (the server's own redirect check stays); an Enterprise Server with logs on its own S3/Azure domain: those redirects are refused |
| Effort | about 5 h |

## The stdio verification here (transcript summary)

No Podman in the review sandbox: the server ran from its source in a throwaway Python 3.13 venv made from the
hash-locked `requirements.txt` (`/root/tt-mcpnew-github`), over stdio as its image starts it
(`python -I -u server.py`):

- **Smoke spec** (as CI runs it: network none, `GITHUB_API_URL=https://127.0.0.1:9`, a placeholder token):
  initialize answers `tools` (and `experimental`) only; tools/list equals `tools.json` (13); 23 of 23 calls passed -
  19 tool calls each naming its API path in the error (`cannot reach https://127.0.0.1:9/repos/octocat/Hello-World/...`:
  all 13 tools, every section of `get_pull_request`, both forms of `get_workflow_run_logs`) and 4 refused calls (a
  `..` path, an owner with `/..`, a ref with `..`, a repo `..`).
- **Against the stand-in GitHub** (tests/test_github.py's, over TLS with a throwaway CA as an Enterprise Server):
  14 of 14 real calls over stdio, one per tool and the log tool twice; the largest answer 23,779 characters (an
  issue with 30 long comments, shortened with a note); only `GET` seen; no `Authorization` at the log storage.
- **Against api.github.com** without a token (about 15 requests of the 60/h): get_repository, get_file_contents
  (the top folder; `action.yml` at the branch `releases/v1`), get_commit at `releases/v1` (the ref as one encoded
  segment `releases%2Fv1` - GitHub resolves it), list_commits, list_issues, list_releases, list_workflow_runs,
  get_workflow_run_logs (a run without jobs), list_pull_requests, a pull request's diff, search_repositories: every
  answer in the shape the code expects.
- The repository's suite (one process, this venv): 896 tests, 101 skipped (servers whose requirements are not in
  this venv); the one failure, `test_frida`, needs frida (not in this venv, unrelated). With `SANDBOX_AI_CHECKOUT` of
  sandbox-ai main the `SandboxAiAgrees` tests fail for every image alike here (no catatonit on this host and no image
  to inspect for its init; the images of mcp-public before the hardening branch bring none) - not github's own.
  `make_catalog.py --check --allow-pending --sandbox-ai`: 41 pinned entries accepted, github refused for its missing
  digest, as it must be.
- sandbox-ai's side: tests/test_presets_all.py and test_mcp_tool_budget.py, the 17 other core test files that name
  the changed presets, the docs tests (5,952 + 1,822 passed), the app's preset tests (588, two updated for the new
  optional value).

## The sandbox-ai side

Branch `feature/mcpnew-github` of sandbox-ai (worktree from `/work` main): the coding presets (`coding-*`, 13),
`code-audit`, `dependency-upgrade` and `pair-reviewer` offer `github` as an optional `--mcp` value (none by default,
the hint gives `sandbox-ai mcp add mcp:github --env GITHUB_TOKEN@SECRET` and the egress-all for logs);
`sandbox/mcp_catalog_tools.json` lists its 13 tools for the tool budget; README/README_DE "GitHub from the catalog".
No rules file: the server cannot write, and none of these presets has a ruleset to hold its results untrusted.

## What only CI or a real host can prove

- The image builds (Debian packages and wheels by hash), Trivy, the smoke spec inside the image under Podman,
  Bubblewrap and without a host init, `test_own_servers` inside the image.
- Live with a fine-grained token: private repositories, code search, an Actions job log through the storage redirect
  (with `--network egress-all`), the rate-limit headers of an authenticated client; the allowlist start (api.github.com
  pinned, no DNS) with sandbox-ai; GitHub behind Tor; an Enterprise Server (a GHES trial or GHE.com).
