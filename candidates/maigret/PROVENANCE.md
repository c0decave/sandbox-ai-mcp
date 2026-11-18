# maigret - candidate, not admitted (review of 2026-11-18, round 2)

**Review of 2026-11-18 (round 2): not added.** The verdict and its reasons are in `docs/round2-reviews.md`; this
folder keeps what was found, for the next attempt. Nothing here is built.

| | |
|---|---|
| MCP wrapper | w0h1v/mcp-maigret **1.0.18** = npm `mcp-maigret` 1.0.18 (MIT), published 2026-11-03 17:33 UTC from commit `4324d5d8ddb04b523e23c4e9756b6953020c6244`; tarball SHA-256 `d0cafc86e86594dc005ec0f853ecf9d51dd5293004f494f79436b6ddac8242e9`, integrity `sha512-z9FaV/LL0v7v7RFHXL/por9UBSrHGwZ1o/yT8qIAzrJLIdX4de4uMesSVVl9w8wfb/Q/pDyztAddYZFy8gT+4g==`; 1.0.19-1.0.22 too new |
| Tool | soxoj/maigret **0.6.6** (MIT), PyPI wheel uploaded 2026-09-18 08:18 UTC, SHA-256 `f382e7174d202a8002b2ac3ce3cde7c11900c506399dd6110f57b9256c4181c7`; its site database `resources/data.json` has 5,897 sites |

## The wrapper (read in full: `build/index.js`, 324 lines)

Two tools, `search_username` (username, format, `use_all_sites`, tags) and `parse_url`; arguments are checked
(usernames `[A-Za-z0-9_.-]{1,100}`, tags, http(s) URLs without shell characters) and passed to `execFile` without a
shell (good). But it runs maigret **only through Docker**: `docker run --rm -v <reports>:/app/reports
soxoj/maigret:latest ...`, pulling the image when it is missing. That needs the Docker socket inside the container
(root on the host, in effect) and runs an **unpinned `:latest` image** - an automatic update of the code that runs.
Correction to the first pass: there is no "local" runner in 1.0.18. Answers are maigret's whole stdout and stderr,
unbounded.

## maigret 0.6.6 (its own code: 8,559 lines in 20 modules; looked at, not reviewed completely)

- `db_updater.py`: **auto-update** of the site database: at start (every 24 h) it fetches `db_meta.json` from
  `raw.githubusercontent.com/soxoj/maigret/main/...` and then the new `data.json` (checked against the SHA-256 the
  same meta file names, so the source is trusted wholesale); off only with `--no-autoupdate`.
- `activation.py`: per-site "activation" (cookies and tokens fetched from the sites; OnlyFans request signing whose
  rules "rotate upstream" and are to be refreshed from a third-party repository, `DATAHOARDERS/dynamic-rules`).
- `ai.py`: an AI summary of the results sent to `api.openai.com` (only when asked).
- `checking.py`: aiohttp with a "Cloudflare bypass" configuration and **curl_cffi** (libcurl-impersonate, browser TLS
  fingerprints) for some sites; `web/` is a Flask UI; reports in HTML/PDF/XMind/graph formats.
- Network: by design thousands of sites (5,897 in the database; 500 by default): `network: full`.

## Why not admitted

The closure of `maigret==0.6.6` (`uv pip install --exclude-newer 2026-11-04`): **67 packages, about 889,000 lines of
Python, 50 native libraries, 183 MB** - aiohttp, curl-cffi (libcurl-impersonate), lxml, reportlab, networkx, pyvis,
Flask, xmind, socid-extractor, cloudscraper-style helpers. Together with the wrapper's Docker-socket design and the
unpinned `:latest` image, it cannot be admitted under this catalog's rules; with `--no-autoupdate` and without the
wrapper the closure remains unreviewable.

## What would replace it

An own username checker on the shared lock: maigret's `data.json` of a pinned release taken as **data** (site URL
patterns, `checkType` status_code / message / response_url, presence and absence strings, the site's tags), checked
with httpx on a chosen subset (top N by rank or by tag, at most a few hundred sites, a concurrency and time limit),
answers bounded; no auto-update (the database changes only with a reviewed re-pin), no activation code, no Cloudflare
bypass, no AI. Estimate 8-10 h. The `tor` profile of sandbox-ai would then hide the user's address from the sites.
