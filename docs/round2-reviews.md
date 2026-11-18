# MCP round 2: reviews (2026-11-18)

The second round of `/work/research-llm/mcp-registry-research-2026-11.md` (its "Second pass" section has the registry
research): full reviews of the servers it ranked highest, in the order the brief set, and the helpers for local
models. Rules as everywhere in this repository: the whole code that runs read, every dependency reviewed or already
reviewed here, a release pinned only when it is at least 14 days old (cut-off for this round: published before
2026-11-04 18:00 UTC), no telemetry, no install script, no auto-update, tools only, answers within 24,000 characters,
hostile inputs tested. Nothing here is signed or published: each added server is a **pending** catalog entry (digest
`null` in `digests.json`) until CI has built it, both smoke reports pass and the catalog is signed with the human.

Effort is the time this review and packaging took (or would take), not counting CI.

## time - added (pending)

| | |
|---|---|
| Verdict | **added**, pending signature |
| Upstream | modelcontextprotocol/servers `src/time`, PyPI `mcp-server-time` |
| Pin | **2026.10.28** (wheel SHA-256 `4b8a1865e8c45da2d2247e72ca83ea087e5c8bc597c9ca93c63e9103aeb46c31`, = commit `74af74c8`); 2026.11.4 turns 14 days old on 2026-11-18 21:34 UTC, after this review |
| Dependencies | the SDK 2.3.0 lock of osint-mcp (reviewed there) + tzdata 2026.6 (data) + tzlocal 5.4.5 (read in full) |
| Network | none |
| Tools | `get_current_time`, `convert_time` (2026.10.28 has no `get_time_ago`; that came later) |
| Changes | zone arguments checked before upstream (long or path-like values echoed or answered with a container path), answers bounded, tools only, `LOCAL_TIMEZONE` |
| Tests | `tests/test_time.py` (5 tests, 11 hostile calls), smoke spec 2 real + 3 refused calls |
| Effort | 2 h |
| Risks left | the container's clock is the host's (a wrong host clock is a wrong answer); `convert_time` converts a time of *today* only (upstream's design); the zone database ages with the pin (IANA 2026f) |
