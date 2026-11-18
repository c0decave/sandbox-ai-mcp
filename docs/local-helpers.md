# MCP helpers for local models (2026-11-18)

For `/root/briefs/mcp-local-helpers.md` (part of round 2, `docs/round2-reviews.md`). The question: which public MCP
servers - or small ones of our own - help a **local** model (LM Studio, Ollama, vLLM behind OpenCode, Codex, Hermes,
Qwen Code, DSH) do its tasks. Local models fail in typical ways (see `LOCAL_LLM_TOOLS.md`): too many tools in view,
arithmetic and dates done in the head, "now" unknown, facts and APIs remembered wrongly, plans and findings lost at
a context compaction, code read as whole files. Each helper below names the failure it addresses.

Rules as for every server here: a complete review at a pin at least 14 days old, or our own code; tools only;
answers within 24,000 characters; nothing signed or published - the added servers are **pending** catalog entries.

## The helpers, per server

| Server | Helps a local model with | Result | Pin / source | Effort | Tools (schema weight) |
|---|---|---|---|---|---|
| [time](../servers/time) | **exact time**: the date, weekday and time in a zone, zone conversion | **added, pending** | official `mcp-server-time` **2026.10.28** (wheel `4b8a1865...6c31`, commit `74af74c8`), reviewed in full | 2 h | 2 (small) |
| [calculator](../servers/calculator) | **exact arithmetic**, units, date spans and date sums | **added, pending** (own) | our code; githejie/mcp-server-calculator 0.2.1 refused: unbounded (`9**9**9` hangs it) | 3 h | 4 (small) |
| [wikipedia](../servers/wikipedia) | **facts to read instead of remember** (grounding) | **added, pending** (own) | our code; Rudra-ravi/wikipedia-mcp 2.0.1 not clearly better (~12 tools, fastmcp 2.x) | 2.5 h | 3 (small) |
| [arxiv](../servers/arxiv) | **papers to read** (research tasks) | **added, pending** (own) | our code; blazickjp/arxiv-mcp-server 0.8.2 not clearly better (19 tools + 3 prompts) | 3 h | 3 (small) |
| [osv](../servers/osv) | **dependency facts** (which versions are vulnerable, which fix it) instead of guessing | **added, pending** (own) | StacklokLabs/osv-mcp v0.1.4 reviewed, re-implemented for stdio | 3 h | 3 (small) |
| context7 (in the catalog) | **docs lookup** of current library APIs | in the catalog (4.5.0) | - | - | 2 |
| tasks, code-search, files, exec (in the catalog) | **planning**, **reading the code base**, reliable writes, commands that end | in the catalog | - | - | 10, 7, 18, 7 |
| engram, memory (in the catalog) | **memory across compaction** | in the catalog | - | - | engram 23, memory 9 |
| sequential-thinking (in the catalog) | written-down reasoning (capable models; small ones tend to loop) | in the catalog | - | - | 1 |
| **tool router** | **fewer tools in view** | **designed; belongs in sandbox-ai's relay, not in the catalog** (below) | - | 16-24 h in sandbox-ai | 2 meta-tools |
| compaction / summary helper | memory across compaction | **not added: engram already covers it** (below) | - | - | - |

## Tool router: design and where it belongs

**The problem.** A local model with 30k-64k of context and weak tool selection gets worse with every tool it sees:
the catalog's 38 servers together offer 325 tools (files 18, engram 23, chrome-devtools 32, shodan 11, ...), whose
schemas alone take 15k-40k tokens, and small models pick wrong or invent names. mcpproxy-go's answer is a gateway that
shows the model two meta-tools - `retrieve_tools(query)` (BM25 over every upstream tool's name and description) and a
call tool - and hides the rest.

**Decision: it belongs in sandbox-ai's MCP relay (`sandbox/runtime.py`, `McpRelays`/`McpGateway`), not in this
catalog.** Reasons:

1. *Only the relay sees every server.* A catalog server runs in its own container with only its own network and
   mounts; it cannot reach the other servers' sockets (they are hidden from everything but the run's supervisor) and
   must not get them. `McpRelays` already holds every relay of a run in one process, sees each server's
   `tools/list` answer (it already filters tools a ruleset denies, `McpConnection` around line 1455) and every
   `tools/call`.
2. *The gateway's guarantees must hold for routed calls.* Rules (allow/ask/deny per tool and argument), approvals,
   taint, the kill switch and `mcp-calls.jsonl` live in `McpGateway`. A router inside the relay forwards a routed call
   to the target server's own gateway, so nothing is bypassed; a router as a server would be a second, unchecked path.
3. *No new trust.* A router server would need the union of all servers' rights; in the relay it needs none.
4. *Agents differ.* Whether to route is a per-start choice (a small model yes, Claude no): a relay option, like the
   other start options, not a catalog entry.

**Design (for sandbox-ai):**

- Start option `--mcp-router` (and a board/app switch per start, CLI + app + web parity): the agent's MCP
  configuration then names one server, `tools`, served by the supervisor, instead of (or besides, `--mcp-router=both`)
  the individual servers.
- `tools` offers two tools: `find_tools(query, limit=5)` - BM25 (k1 1.2, b 0.75) over `server.tool name`, the
  description and the parameter names, plus an exact-name boost; answers at most 5 tools **with their full input
  schemas**, so the model can call them next - and `call_tool(server, tool, arguments)`, which forwards to that
  server's relay as if the agent had called it (same gateway, rules, approvals, records; a denied tool is never found).
  Optionally a short pinned list (`--mcp-router-pin files.read_file,exec.run_command`) is offered directly, for the
  tools a model needs every turn.
- The index is built from the `tools/list` answers the relays already fetch; `notifications/tools/list_changed`
  rebuilds it. Standard library only (BM25 is ~60 lines), no embedding model, deterministic.
- Bounds: `find_tools` answers within 24,000 characters (5 schemas), a call's answer passes through unchanged (each
  server bounds its own).

**Trade-offs.** One more round trip per new tool (find, then call); a model that never searches never finds; BM25 on
short descriptions misses synonyms (descriptions in this catalog are written to name what a tool does; an exact-name
boost catches models that know the name); the agent's own tool-permission UI sees only `tools.call_tool` (sandbox-ai's
gateway still asks per real tool). Capable models do not need it.

**Built here?** No: the variant that fits is a change to sandbox-ai's relay, outside this repository (and outside this
task's repository). It is listed under "Next" in the research report for a sandbox-ai feature branch, with the A/B
test below.

## Compaction / summary helper

**Not added.** What a local model loses at a compaction is the goal, the plan, what it found out and what failed.
The catalog covers all four: **tasks** keeps goal, steps and notes of mistakes in `/work/.tasks` (`next_step` gives
the one step to do now); **engram** keeps observations, decisions and bugs with full-text search, and has
`mem_session_summary` (write a session summary), `mem_context` (recent sessions after a restart or compaction, at most
64 KiB) and `mem_session_start`/`end`. A separate "summarise my context" server would have to call a model itself
(an LLM in the loop: a key, a cost, a second model's errors) or only store what the agent writes - which engram does.
Vector stores (qdrant, chroma: section 2.9 of the research) duplicate engram and download embedding models. What is
missing is not a server but the habit: sandbox-ai's presets for local models should add tasks + engram and a system
prompt line "after a compaction call next_step and mem_context first" - an A/B item below.

## What the round-5/6 A/B should test

Same task set, same model (the research's local ranking), with and without the helper, 3 runs each; measure task
success, wrong tool names, tokens of tool schemas in the prompt, wall time.

| Helper | A (without) | B (with) | Expect |
|---|---|---|---|
| time | the model asked "what weekday is 2026-12-24 in Tokyo" / "how many days until ..." | time + calculator | correct dates instead of guesses; one call each |
| calculator | arithmetic in tasks (invoices, unit conversions, percentages) done in the head | calculator, prompt "use calculate for every calculation" | fewer wrong numbers; check the model actually calls it (small models skip tools for "easy" sums) |
| wikipedia | factual questions answered from memory | wikipedia | fewer hallucinated facts; watch for over-long `get_article` use (pages) |
| arxiv | "find recent papers on X and summarise one" with web-fetch only | arxiv | ids that exist; full-text pages read instead of PDF failures |
| osv | "upgrade the vulnerable dependencies of this lock file" | osv (batch) | the right fixed versions; one batch call instead of many |
| tool router | the servers of a start offered directly (often 50-100 tools) | `--mcp-router` (2 meta-tools + 3 pinned) | fewer wrong tool names, smaller prompts; cost: one extra round trip; measure whether small models search at all |
| compaction | a long task forced through a compaction | presets with tasks + engram and the "after a compaction" prompt line | the plan resumed instead of restarted |
| shodan (11 tools) | offered directly | through the router | shows the router's value on a many-tool server |

## Not helpers, but noted

- **mcpproxy-go** v0.72.0 (2026-10-27, pinnable): a whole gateway (quarantine, tray app, Docker isolation, web UI),
  30 h+ to review; only its BM25 idea is taken (above).
- **pydantic/mcp-run-python**: archived; exec covers running code.
- **serena** (LSP-based code navigation): looked at on 2026-11-13 (`LOCAL_LLM_TOOLS.md`), code-search serves small
  models better.
