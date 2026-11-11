# engram - provenance and audit

| | |
|---|---|
| Upstream | Gentleman-Programming/engram **v3.6.0** (MIT, `LICENSES/engram-MIT.txt`), tag commit `98912f811c90428e83a6aac99fa439bedb4b268f` (2026-10-24) |
| In the image | `/usr/local/bin/engram-mcp`: this repository's entry point `src/main.go` (MIT) built inside Engram's module at that commit as `cmd/sandbox-ai-mcp`; of Engram it links only `internal/mcp`, `internal/store` and the eight small packages they import (`engram-files.sha256`: 58 Go files, 31,134 lines, plus `go.mod`, `go.sum`, `LICENSE`, each checked by SHA-256 in the build; the build fails if any other Engram package or file is linked). Not built: `cmd/engram` (CLI, `serve` HTTP API, TUI, setup, hooks, update check), `internal/server`, `internal/tui`, `internal/cloud/*` except its constants, `internal/sync`, `internal/llm`, `internal/obsidian`, `internal/setup` |
| Go modules | by `go.sum` of the commit, `go mod download && go mod verify` in the build (proxy.golang.org, checked against sum.golang.org): mcp-go 0.44.0, modernc.org/sqlite 1.58.0 with libc 1.75.6, mathutil 1.7.1, memory 1.12.1, golang.org/x/sys 0.47.0, x/text 0.41.0 and the small modules listed below |
| Build image | `golang:1.26-trixie` (Go 1.26.10) `sha256:a050dcceee6eb9bf110151662dfac7662f3bec40927c7dee48731e3d92083d42`, as docker-library/repo-info recorded it on 2026-10-28 (commit `39f1d151`; the image of `servers/whatsapp`); not in the final image. `CGO_ENABLED=0`, `GOTOOLCHAIN=local`, `-mod=readonly`, `-trimpath` |
| Base image | the `debian:trixie-slim` digest in `Dockerfile` (`sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad`); no Debian package is added (no git, no ca-certificates: no network) |

**Upstream:** https://github.com/Gentleman-Programming/engram (created 2026-02-16, about 7,900 stars, very active:
releases every few days; maintainer Alan Buscaglia, "Gentleman Programming"). Engram is one Go binary with a CLI,
an MCP stdio server, an HTTP API (`engram serve`), a terminal UI, an Obsidian export, agent setup and hooks, and the
client of Engram Cloud (sync, enrollment, autosync). The memory is an SQLite database (modernc.org/sqlite, pure Go)
with FTS5 trigram search. Upstream's Docker files and release binaries are not used.

**Pinning rule:** v3.6.0 (2026-10-24) is the newest release on or before 2026-10-28. Too new: **v3.6.1**
(2026-11-03: sync and soft-delete fixes, diacritics folded in trigram search, UTF-8-safe passive titles,
per-call workspace attribution of prompts, MCP stdio teardown), **v3.6.2** (2026-11-04: Pi companion pin,
release tooling), **v3.7.0** (2026-11-07: organisation-scoped memory, a daemon for `engram serve`, faster store
and sync) and **v3.7.1** (2026-11-11: FTS query size bounded, Go 1.26.11, private-tag redaction of judgment
reasons, project merges with spaces). None fixes something reachable here that the entry point does not already
bound (it caps every argument, see below); re-pin from 2026-11-17 (v3.6.1) or later and re-review the diff. Every
module of `go.sum` predates the release commit.

## The entry point (`src/main.go`)

Engram's own `cmd/engram` is 4,185 lines of `main.go` alone and links every subsystem; the image instead builds a
small entry point of this repository (278 lines, MIT) inside Engram's module (Go allows importing
`internal/` packages only from there). It:

- opens the store at `/data` with `store.FallbackConfig("/data")` - Engram's own limits (observations cut at
  50,000 bytes, 20 search and context results, 15-minute de-duplication); an empty `store.Config` would set them to 0,
  and every saved text would be stored as `... [truncated]` (review finding E-1);
- serves the tools of Engram's `agent` profile (`mcp.ResolveTools("agent")`, 23; not the admin tools `mem_delete`,
  `mem_stats`, `mem_timeline`, `mem_merge_projects`) with `MCPConfig.DefaultProject` = `ENGRAM_PROJECT` (default
  `brain`, Engram's normalised form only), and registers a session `sandbox-ai-mcp-PROJECT` the first time a project
  is used in a folder, so reads work on a fresh folder (Engram refuses reads of a project that does not exist yet);
- takes the `directory` argument of `mem_session_start` and the `directory`/`cwd` arguments of `mem_current_project`
  out of their schemas and refuses them: Engram would scan those folders (`.engram/config.json`, child `.git`
  directories) and run `git` in them (E-2);
- wraps every tool (`guard`): without a writable `/data` every call answers so (the tools are still listed, which CI's
  first step needs); arguments over 512 KiB in all, texts over 64 KiB (`content`, `new_content`, `find`, `replace`,
  `summary`, `evidence`, `reasoning`, `observation`) or 1 KiB (every other string: titles, queries, ids, names) and
  `limit` over 100 or `before`/`after` over 50 are refused (E-3, E-4, E-5); a panic in a handler becomes a tool error
  (mcp-go recovers none by default, Engram only in its write queue; M-2);
- reads stdin through a line limit of 4 MiB (mcp-go reads whole lines without a limit; M-1) and stops on SIGINT/SIGTERM
  or end of input (mcp-go then finishes the queued calls);
- has no network, process or file code of its own; `--version` prints the version.

`src/main_test.go` runs in the image build (`go test`): the 23 tools and no others, every call refused without
`/data`, no folder arguments, the argument bounds, a panic as a tool error, the line limit, project names.

## What was reviewed

**Engram, line by line** - every Go file that is linked, at `98912f81` (`engram-files.sha256`; the build checks
each file and that nothing else of Engram is linked). Read in five slices (the MCP layer with `internal/project`,
`diagnostic`, `hostbind`, `agentops`, `command`, `identityfile`, `timeutil`, `cloud/constants`; `store.go` 1-7283;
`store.go` 7284-14444; the other 29 files of `internal/store`). Also read, not linked on Linux: `command_windows.go`,
`hostbind/start_unix_ps.go` and `start_windows.go`, `identityfile/publish_other.go`,
`store/filesystem_policy_unix.go`.

| File | Lines | SHA-256 |
|---|---|---|
| `internal/agentops/consolidate.go` | 76 | `fefe61539da738653a1065645aa0850c4bc8ee017aa1d7762faea79087a80342` |
| `internal/agentops/judgments.go` | 74 | `7b60861bca130ebfdb5e768f48254cd9e2bd4cc647f24105c6cd2f2cbec10692` |
| `internal/cloud/constants/constants.go` | 50 | `9e80534319aea82464591dd6d810f3464fc1b36d60d6aea1e0cbc75ac68809a6` |
| `internal/command/command_other.go` | 14 | `e26e980785f99d94aa1bdf4cd00225e556010305dbfa1758bb9fef5497a69b0a` |
| `internal/diagnostic/caller_binding.go` | 117 | `13bea951d73e20e5250d2e7f83bdee9ac3d8bafc39fbdbeb7917a826f2043628` |
| `internal/diagnostic/checks.go` | 848 | `8101fe0acdaad1514779e3995b123be346fa66219ca2b45d781fb831f09738ee` |
| `internal/diagnostic/diagnostic.go` | 253 | `bb54b7c75ed48bc1ccbb31f327f0102a7f53e44bedd20757fa788ce826e8f761` |
| `internal/diagnostic/registry.go` | 67 | `269758512ba61ed0bff08265d5d36266c7a57e5f02b1cf6b6f74ce3038c4c425` |
| `internal/diagnostic/repair.go` | 523 | `db176e7d92f48c1f60c3d05af92cc3557074b3f10ec675154257985cf6563fcf` |
| `internal/hostbind/hostbind.go` | 139 | `eb37f4d7858c9bfa468c1c9227145d9bcb378e6b8f6123f3d6779b372c639afd` |
| `internal/hostbind/start_linux.go` | 38 | `a08649b112f8e25ae68d96d56e330755e59580fffc71a5d3560c3f051d59f418` |
| `internal/identityfile/publish_linux.go` | 30 | `1bc8e9a9cf2860b5de676c4ca518c5a22c587efab14d37e5e20f78d8df13c972` |
| `internal/mcp/activity.go` | 334 | `e1618745aa170c9db1960fba48d6a81550a90c2dfc6e51ff0d5bd9e568d4b7ca` |
| `internal/mcp/agent_contract.go` | 262 | `1c524e456bc8f3ddd5f36cf3b7ee378cfdd47b4816d140441254f2135b624496` |
| `internal/mcp/agent_contract_pi.go` | 248 | `c6b099bb04897bc37f39bdd1f622e4ed4aeaecb67bfd3e1d0dabaa35d827be2a` |
| `internal/mcp/consolidate.go` | 92 | `3c4173871c4b9137b3d3f6afb32064e5b93c0c7b5c7ee986e9cf19dc0921421e` |
| `internal/mcp/mcp.go` | 3898 | `85f78dd4e998e0e8f452fecd2932467709c913f90102044cc4c27090c5e43496` |
| `internal/mcp/prompt_search.go` | 56 | `62b4494f7ba75de356dc9cfa29537fd40f0fefb59f8c6f43c0ff80eb6abaa9cc` |
| `internal/mcp/save_timing.go` | 49 | `0289f351bd01c08b4cd611915909a67936a1aceaf2b098b6b24468eca133462a` |
| `internal/mcp/session_finalize.go` | 97 | `ff4330d7af13a7212558e3865dc6b24c9b41ba72886a6dc29a50bdc04e8638a7` |
| `internal/mcp/write_queue.go` | 104 | `15ee24135108c1ce75b605f538e6d1e51107d8211e590ef63b06c546695a44ef` |
| `internal/project/detect.go` | 718 | `ce314e772b4ccb334188325ac3fcc0e3030f8efda0abe17775930d84dba02754` |
| `internal/project/identity.go` | 137 | `3742d21daf6a359f9847c0eb79f0d70f44ed2209ffc2e5127152b7ff54963782` |
| `internal/project/inspect.go` | 117 | `d5be1156f5812f6a29d3546052ba8227ef10978a12f3d338cc0ea375354e3c53` |
| `internal/project/resolution.go` | 140 | `a9cbd7961368c663a806b4047212e79fbd5be5ff40579b0519344839385efaa8` |
| `internal/project/routing_candidate.go` | 46 | `190c995f090bd0ec05753fbd0d01ad6c1491f593da93fb11edfff20c94808c88` |
| `internal/project/similar.go` | 173 | `a50cccae1d56eb9953a4dd2c51c908f6dc86399e8d74539c66701e826df8f016` |
| `internal/store/candidate_relevance.go` | 82 | `39c745f4b9193f22210506886589d6600746904c35e56ad46d38bfc13dd66d60` |
| `internal/store/capture_project_provenance.go` | 117 | `c19e18f46c4c12b86791f6c045e8aaa4c53389f2007ffa3965db6dde89486cca` |
| `internal/store/compatibility.go` | 161 | `8e4a3e12fa9f6a68f7276dc9bd9049f014536ee26a7c199dcf273b5e3bb70ee6` |
| `internal/store/consolidate.go` | 416 | `fba90e2dac10144eaea2bfe7b3fc3730bd9ab41ed290993d95870dcc3b9e35a9` |
| `internal/store/context_history.go` | 256 | `496342480b308d71e12539ff508eb03b969d67c6a1ff0c9dd2579b9188f3197a` |
| `internal/store/data_directory.go` | 15 | `9fd0eebd688430f9fa3395ba9ab54a44904b51bb8435e4d4a7c296176dfad82f` |
| `internal/store/dead_row_prune.go` | 265 | `64a9ac4dd62892b5b741cf88ad27442c5deb574b87fef7159b8a05fcbc1291dc` |
| `internal/store/diagnostic.go` | 1414 | `57bb1572c146c714c4bf263da80ac6a2e55b5f83120e6ee723af6a5312d3193a` |
| `internal/store/enrolled_repair_batches.go` | 82 | `092881806e3bcd8987456bf92b550c2d68505380bfd23b9204b39638d1c80762` |
| `internal/store/filesystem_policy.go` | 72 | `e3021e20204d7fe0a238719a1809988728bd4463d40c0d972336e33a1e734547` |
| `internal/store/filesystem_policy_linux.go` | 35 | `c8c0fc0db1b07c1b9a78e3fffe6e0a01166d90d9c6c24ff44c910c4286975022` |
| `internal/store/generation_fence.go` | 541 | `d4f1b345af951272ea826651e3584ba36ba2c2868c875e41e7b1223afb5e0c87` |
| `internal/store/instance.go` | 116 | `6b977b19d32574e01e331efdb76713c52aec8b6f8ee3d153b3dd6be717f29ac5` |
| `internal/store/migrate_copy.go` | 509 | `d4195fa897493b54fae30785355c88d28360f451d2b795cd6da9861ed9c48550` |
| `internal/store/migration_lock.go` | 94 | `fa1da3e25befc8a096210f9fe859bb9b85435da1870067198a8fde70a9888513` |
| `internal/store/migration_lock_unix.go` | 30 | `407725689f823ada1ccdb076657a12ef5dec7ef6cc8bcf3a9ee1ebdadffd3693` |
| `internal/store/observation_provenance.go` | 47 | `7929a51cd48e88426316c1866267276630b47368cea8dd41bde4b1090b022187` |
| `internal/store/project_alias.go` | 145 | `5df6ad75d43f72ca1dd5ab189b8c6d5f0dc517623eeab0eac9b4f236099a96f3` |
| `internal/store/project_history.go` | 66 | `29f8ad5c17aee0717ca8f4fd94c6a5aeaf984912f9cea59c01aed5f12e62f1e4` |
| `internal/store/prompt_capture.go` | 17 | `6a47cc6e2b6449ade373b584bf6cc191000bce4eb1a9a4740fe7efe18306f162` |
| `internal/store/prompt_discard.go` | 510 | `0843b65e6254d7b736903f5ceea37f87a02ca6f3a17fe71f609d0634427dff1f` |
| `internal/store/prompt_source_confirmation.go` | 109 | `95938f6a1222786fb4d6422ea0c255b587e3a53e818108a6aef2c8917bec5a67` |
| `internal/store/relations.go` | 1757 | `d1fc885ae617bf8dcf8e7be4acd690deca2a24f09d7ca1762e827c361e94b147` |
| `internal/store/relations_scan_batch.go` | 318 | `05f8695dd6602b7e697afd69a65d8681e8bd51e1f6c9f1cb3e53ea4e1460710b` |
| `internal/store/runner.go` | 25 | `38d1bde348cfd92937c66acf45f9a5246d63dc2c1dbc9824f4cefb822aa32d94` |
| `internal/store/search_projection.go` | 52 | `29828f7b3399aee797cb1403c2e3e18f6a667b42bba9e905a78d7ae6064569da` |
| `internal/store/session_finalize.go` | 122 | `558c53a1e9464aaf1302bd28c6b0dbf63d829eef0982338652eb91babadd0642` |
| `internal/store/session_identity_repair.go` | 525 | `b6f41b4fddee6790445227c9ca1ad613980175ffbeb7bfebcf4be8049465735a` |
| `internal/store/sqlite_cantopen.go` | 37 | `2dd0403c8e59ae2b23416b259046e6a9b7342f752222da32cb5e219fe7546d8a` |
| `internal/store/store.go` | 14444 | `2715b4adc0cf6681c6503ca313aa808e16e0b29a6c599a9a7ff902349182b4c9` |
| `internal/timeutil/timeutil.go` | 55 | `aad46098505055402ae136c19fdfb650def37e782a7dd643a476f3b3e6d8304a` |
| `go.mod` | 68 | `4a3ad075945ecd6bc1caf89e79b0469eca11707865adb0e714cacbc193949f9c` |
| `go.sum` | 168 | `bc4aba57199d8ad4f93b0a1ac18bdd546eb846f72199bfc2b83c37a183b7baf0` |
| `LICENSE` | 21 | `09608597ddda4e5f9033ac407a0d401986d96376c47f6d46789ca38db672dc15` |

**mcp-go v0.44.0, line by line** (github.com/mark3labs/mcp-go, MIT, `LICENSES/mcp-go-MIT.txt`; GitHub tag
archive; `go.sum` `h1:OlYfcVviAnwNN40QZUrrzU0QZjq3En7rCU5X09a/B7I=`): all 29 non-test files of `mcp/`, `server/`
(including `server/internal/gen`, a `go generate` tool that is not linked) and `util/`, 13,028 lines - the stdio
transport and everything it calls, and also the SSE and streamable-HTTP transports, which are compiled in but never
started (nothing in them runs at package initialisation or from the stdio path).

| File | Lines | SHA-256 |
|---|---|---|
| `mcp/consts.go` | 12 | `22bc90aff3022dd03e61a4666e695f78dae3990c140b2ea74ab254ab8b7f6c6c` |
| `mcp/errors.go` | 132 | `36dc6520ed29810bcfd43c8ae1986635b0fa2f07a56a198dc8aceaecee918cea` |
| `mcp/prompts.go` | 186 | `2c73098f480e729018d617d086e76eecc13621410e5d40556e79d5bf1a752a2f` |
| `mcp/resources.go` | 146 | `9d9fb2b620158708c9ef0d0fb28b023387beb9f2a30841ce0e721ad22e4548c8` |
| `mcp/tasks.go` | 208 | `a26539ae4c2090b1a1847e06c2445fb1a64f25caac4336b2ac333c1f7f243b92` |
| `mcp/tools.go` | 1444 | `5bfc33a6db125632fa7384f4167881f4d25a214d6e0de7b3fde125086d486646` |
| `mcp/typed_tools.go` | 42 | `bfe53b905251d0aa57320ef41615e9ea433e476e95cd953a38bb0a3f1aa8903b` |
| `mcp/types.go` | 1599 | `ecafaa19779d891f8b17c73e2ab86e58e597a4f40757a55091c8e0040f4e466e` |
| `mcp/utils.go` | 999 | `a41b4b0c34ca82b1e1257b5477750713860e7909774fa43b8a048bde313572de` |
| `server/completion.go` | 35 | `39463223549bedf491990bff22a4ffa951f1903bab6797d927631cd80c2a62ca` |
| `server/constants.go` | 7 | `ed1bb248190f7a7873f37a50465a3841d155aa51bc726825a770468241558056` |
| `server/ctx.go` | 8 | `5d93403de8fcce9677c127300ad50257d3110d7e0b8f853c40000f4816f1275e` |
| `server/elicitation.go` | 87 | `bab7787034043222a782e6a888269a84b036a261ba32d32045464fc599939eb2` |
| `server/errors.go` | 36 | `10e6008a46949ecf815e8184f5482d6e312fe331a694748cbdece55dae541e03` |
| `server/hooks.go` | 692 | `2cfbaf27f5fd9dd2d498d8aa629a1a36dfeea76b66265388cf6c516d41b44549` |
| `server/http_transport_options.go` | 11 | `f38bd60229f1c7c14f80e229f6cf278f208e2a7edd2c9f0faef1fb9f09cd0944` |
| `server/inprocess_session.go` | 165 | `43c38b42f560a446d360f1fdbd688de2d531226503c5deb006f017edcc41de9e` |
| `server/request_handler.go` | 469 | `dcbc8f86659874528697bf7e001800445da384c1e7873ddd61c22bae181a1e3a` |
| `server/roots.go` | 32 | `4750c18acb806ff07c58be2f49743217d9c895992681b795bb75f39668900072` |
| `server/sampling.go` | 61 | `dbf591f6a7fd80dd95e782dfa0692cdf53355966577a7795a4911ad52881bc04` |
| `server/server.go` | 2316 | `9dc4dcd4a2ea1bc5eb26320c9559a4e656427952a7120598d69b9980217084be` |
| `server/session.go` | 759 | `7aadf6d795611c3082249dfc3100008ecb90dae5a1821f0fb70dcc95889602f4` |
| `server/sse.go` | 824 | `c4c910e69bda8e2c6f9c7e55e7f67e5fcd75254bd74f0dac7a3cb1a58d90319f` |
| `server/stdio.go` | 877 | `fced4a703e6570c9a882ace82f42db3e0bcd84c106a0f78346834a10d437d2d1` |
| `server/streamable_http.go` | 1462 | `b5d9e3833d9c3d72b15db7078704f8489c8f86c2c165cb68939bd9d5dcef9ad8` |
| `server/task_hooks.go` | 136 | `b943118b21cf9faba7f06ceb00d8d71b02cfd3e1525246d05dc241c8e917bdfe` |
| `server/internal/gen/main.go` (not linked) | 87 | `2c0ed8054d1520606072c5eeb34fe3c1be0ba2eb87a7bb1baae05161ca704a8f` |
| `server/internal/gen/data.go` (not linked) | 163 | `e9107f0ff795e6e32d9fc5360b336ba5bbc262de0aa2c7015913b0288ce77351` |
| `util/logger.go` | 33 | `b7d1d3985244a56c662411d1ecb1504c42dc53a7329efc742b6d3d0300e8aad3` |

**The other Go modules** - the import graph of `internal/mcp` and `internal/store` (linux/amd64, `CGO_ENABLED=0`, no
tests). Each was fetched as its tag archive (GitHub; GitLab `cznic` for modernc.org) and its `h1:` hash computed over
the archive: all 17 equal engram's `go.sum` (and so the module zips CI verifies), both module and `go.mod` lines.

| Module | Version | `go.sum` | Linked packages, files / lines | Depth |
|---|---|---|---|---|
| github.com/google/uuid | v1.6.0 | `h1:NIvaJDMOsjHA8n1jAhLSgzrAzy1Hgr+hNrb57e+94F0=` | uuid, 15 / 1,311 | read in full |
| github.com/invopop/jsonschema | v0.13.0 | `h1:KvpoAJWEjR3uD9Kbm2HWJmqsEaHt8lBUpd0qHcIi21E=` | 5 / 1,490 | read in full |
| github.com/wk8/go-ordered-map/v2 | v2.1.8 | `h1:5h/BUHu93oj4gIdvHHHGsScSTMijfx5PeYkE/fJgbpc=` | 3 / 549 | read in full |
| github.com/bahlo/generic-list-go | v0.2.0 | `h1:5sz/EEAK+ls5wF+NeqDpk5+iNdMDXrh3z3nPnH1Wvgk=` | 1 / 235 | read in full |
| github.com/buger/jsonparser | v1.1.1 | `h1:2PnMjfWD7wBILjqQbt530v576A/cAbQvEW9gGIpYMUs=` | 5 / 1,664 | read in full |
| github.com/mailru/easyjson | v0.7.7 | `h1:UGYAvKxe3sBsEDzO8ZeWOSlIQfWFlxbzLZe7hwFURr0=` | buffer, jwriter, 2 / 683 | read in full |
| github.com/spf13/cast | v1.7.1 | `h1:cuNEagBQEHWN1FnbGEjCXL2szYEXqfJPbP2HNUaca9Y=` | 3 / 1,713 | read in full |
| github.com/yosida95/uritemplate/v3 | v3.0.2 | `h1:Ed3Oyj9yrmi9087+NczuL5BwkIc4wvTb5zIM+UJPGz4=` | 11 / 1,631 | read in full |
| github.com/remyoudompheng/bigfft | v0.0.0-20230129092748-24d4a6f8daec | `h1:W09IVJc94icq4NjY3clb7Lk8O1qJ8BdBEF8z0ibU0rE=` | 4 / 689 | read in full |
| github.com/dustin/go-humanize | v1.0.1 | `h1:GzkhY7T5VNhEkwH0PVJgjz+fX1rhBrR7pRT3mDkpeCY=` | 11 / 1,038 (through libc's `probes.go`) | read in full |
| modernc.org/memory | v1.12.1 | `h1:nFMiWrpStgZczNl6XI9GnIk/rWhYIyHGUaR04pGbp9g=` | 6 / 847 | read in full |
| modernc.org/mathutil | v1.7.1 | `h1:GCZVGXdaN8gTqB1Mf/usp1Y/hSqgI2vAGGP4jZMCxOU=` | 13 / 10,263 | read in full except the data file `tables.go` (6,995 lines, scanned: data and one `init()` that indexes it) |
| gopkg.in/yaml.v3 | v3.0.1 | `h1:fxVm/GzAzEWqLHuvctI91KS9hhNmmWOoWu0XTYJS7CA=` | 13 / 11,285 (through go-ordered-map's `yaml.go`) | risky surfaces |
| golang.org/x/sys | v0.47.0 | `h1:o7XGOvZQCADBQQ4Y7VNq2dRWQR7JmOUW8Kxx4ZsNgWs=` | unix, 42 / 20,837 and `asm_linux_amd64.s` | risky surfaces |
| golang.org/x/text | v0.41.0 | `h1:vz/seA0lnX87Othu2f/0L24RcgrXD9/YFTSuGjj3rH8=` | transform, unicode/norm, 10 / 10,864 | risky surfaces |
| modernc.org/libc | v1.75.6 | `h1:yKk8qo+Di4gkmvRboK8ocCqH22FiUCR6jRy2OwtCRus=` | libc, sys/types, uuid/uuid, 32 / 170,725 and 2 `.s` | the hand-written core read in full (`libc_musl.go`, `syscall_musl*.go`, `mem_musl.go`, `probes.go`, `watch.go`, `etc_musl.go`, TLS, the small files); the transpiled musl (`ccgo_linux_amd64.go`, 153,659 lines) by risky surfaces and a call graph from every libc symbol SQLite uses; every `init()`; the 1,875 assembly stubs checked by script (no `SYSCALL`, each calls only its Go function) |
| modernc.org/sqlite | v1.58.0 | `h1:38u40/bwkfM7f0Myhosl+SEMltSDxnGdQf8o6Kjmys0=` | sqlite, lib, vtab, 148 / 239,900 | the Go driver's open, DSN and connection paths read; the transpiled SQLite by risky surfaces: extension loading, temporary files, the syscall table, all 41 `init()` (table fills only) |

Not linked although in `go.sum`: ncruces/go-strftime (only libc's non-Linux file), josharian/intern (only easyjson's
`jlexer`), and everything of Engram's CLI, HTTP API, TUI and cloud client (pgx, bubbletea, templ, x/net, ...).

What SQLite can reach in libc, by that call graph: `access`, `chmod`, `chown`, `clock_gettime`, `close`, `fchmod`,
`fcntl`, `fstat`, `fsync`, `ftruncate`, `getcwd`, `getpid`, `getrlimit`, `lstat`, `mkdir`, `mmap`/`mremap`/`munmap`,
`open`, `pread64`/`pwrite64`, `read`/`write`, `readlink`, `rename`, `rmdir`, `stat`, `unlink`, time and sleep calls -
no exec, fork, clone, socket, connect or DNS.

## Findings

No backdoor, telemetry, update check, network access or code loading was found in what is linked. Engram's only
subprocess is `git` (project detection); there is no git in the image and `PATH` has no writable folder. The cloud
and sync code that is linked (`internal/store`) is local bookkeeping in SQLite: it journals changes only for projects
enrolled in Engram Cloud, and no MCP tool enrolls one. "E" are Engram, "M" mcp-go, "G" the other Go modules.

| Id | Severity | Where | What | Handling |
|---|---|---|---|---|
| E-1 | medium | `store/store.go` 864-889, 4961-4985, 5337, 5738, 5886 | the store fills no defaults: with a bare `store.Config{DataDir: ...}` every observation would be stored as `... [truncated]`, search would return nothing (`LIMIT 0`) | the entry point uses `store.FallbackConfig("/data")`, as Engram's own callers do; a test checks it |
| E-2 | low | `mcp/mcp.go` 2584-2593, 2973-2978, 1277-1294; `project/detect.go` 342-690, 420-439, 592-649; `project/identity.go` 75-92 | `mem_session_start` with `directory` and `mem_current_project` with `directory`/`cwd` scan any folder of the container (its `.engram/config.json`, child `.git` folders), run `git -C DIR ...` there (a hostile repository's `core.fsmonitor` would run) and can write `engram-project-identity.json` into its git folder; a directory also bypasses the project (a project named after its last path component, control characters allowed) | the arguments are removed from the schemas and refused (smoke spec); no git in the image |
| E-3 | low | `store/store.go` 4245ff., 5048, 5608, 6114-6168; `relations.go` 427-438; `candidate_relevance.go` | no length cap on titles, types, topic keys, session ids, project names and queries; a save compares title words pairwise against every full-text match (one SQLite connection, not cancellable); `mem_search_prompts` and `mem_review` take any `limit` | the entry point caps every string (1 KiB, texts 64 KiB), the whole call (512 KiB), `limit` (100) and `before`/`after` (50) |
| E-4 | low | `store/store.go` 13770-13890 | `mem_capture_passive` saves every list item under "## Key Learnings" as its own observation, without a count limit; its title cut can split a UTF-8 character | bounded by the 64 KiB content cap |
| E-5 | low | `store/store.go` 4511; `mcp/mcp.go` 1507-1540 | `mem_pin`/`mem_unpin` work on any observation id, whatever its project, and return it | one memory folder per case: everything in it belongs to that case |
| E-6 | low | `store/generation_fence.go` 54-84 | Engram stops for good (until restarted) if `engram.db`, `-wal` or `-shm` is replaced or deleted while it runs | notes: do not change the folder while a connection uses it |
| E-7 | info | `store/store.go` 13338-13474, 13249-13336 | two migrations rebuild tables, only on a database of an old schema (pre-3.x) | a fresh folder never triggers them |
| E-8 | info | `mcp/mcp.go` 248-431, tool descriptions; `activity.go` 300, 331 | the instructions and descriptions steer the agent: save proactively, a session summary is "MANDATORY", the first call should be `mem_current_project`, nudges after ten minutes without a save; error hints name `engram` CLI commands that do not exist in the image | stated in the entry's notes; memory use is the server's purpose |
| E-9 | info | `mcp/mcp.go` 3809-3813, `hostbind/hostbind.go` 118-135 | a write without `session_id` reads `/data/host-sessions/<ppid>.json` and `/proc/<ppid>/stat`; skipped when the parent is PID 1 (podman's `--init`, Bubblewrap) | read only, inside `/data` |
| E-10 | info | `store/candidate_relevance.go` 12-35 | `init()` registers a pure SQL function with modernc sqlite | no I/O |
| E-11 | info | `store/store.go` 13724-13735 | `<private>...</private>` redaction is a best-effort regex | not a security boundary |
| M-1 | low | `server/stdio.go` 497-508, 544 | stdin lines are read whole, without a size limit, and copied several times | the entry point stops at a 4 MiB line |
| M-2 | low | `server/server.go` 299-344, 1513 | a panic in a tool handler is not recovered unless `WithRecovery` is set; Engram does not set it (only its write queue recovers) | `guard` recovers every tool |
| M-3 | info | `mcp/tools.go` 1013-1444, `server/server.go` | schemas (`Required`, enums, lengths) are not enforced by mcp-go; `GetInt` truncates floats | Engram validates its own arguments; the entry point bounds sizes and counts |
| M-4 | info | `server/stdio.go` 547-550, 615-622 | up to 5 tool calls run at once, a queue of 100; `notifications/cancelled` is not handled | Engram serialises writes in its own queue, SQLite has one connection |
| M-5 | info | `server/stdio.go` 230, 291, 354; `server.go` 2026-2079 | sampling/roots/elicitation requests skip the write lock; tasks without TTL are kept | never used by Engram |
| M-6 | info | `server/internal/gen/main.go` 46 | the code generator runs `go run golang.org/x/tools/cmd/goimports@latest` | `go generate` is never run; the package is not linked |
| G-1 | low | libc `libc_musl.go` 860-880, `ccgo_linux_amd64.go` | `Xsystem` (`exec.Command("sh", "-c", ...)`), `Xexecve`, `Xvfork`, the musl socket and resolver functions exist in libc | none is referenced by SQLite or the driver (call graph), so the linker drops them; `popen` panics, `fork` returns ENOSYS |
| G-2 | info | sqlite `lib` `_loadExt`, `_unixDlOpen` | `load_extension()` is compiled in, but off unless enabled (the driver never does) and `dlopen` is a stub returning 0 | cannot load anything |
| G-3 | low | sqlite `lib` `_unixTempFileDir`/`_unixTempFileInit` | temporary files go to the first writable of `SQLITE_TMPDIR`, `TMPDIR`, `/var/tmp`, `/usr/tmp`, `/tmp`, `.` (`O_EXCL|O_NOFOLLOW`, unlinked at once) | the image sets `SQLITE_TMPDIR=/tmp` |
| G-4 | info | sqlite `lib` | SQLite reads `/dev/urandom`, opens `/dev/null` for a closed fd 0-2, reads zoneinfo for `'localtime'`, follows symlinks in the database path | read only; the agent cannot create files in `/data` other than through Engram |
| G-5 | info | sqlite compile options | ATTACH, `VACUUM INTO`, `writable_schema` are compiled in; `_defensive` is off | no SQL from the agent reaches SQLite unbound: every value is a parameter (review of `internal/store`), FTS terms are quoted |
| G-6 | low | spf13/cast `caste.go` 294-505 | out-of-range numbers wrap silently | Engram reads its numbers itself; the entry point caps `limit`, `before`, `after` |
| G-7 | info | google/uuid `node_net.go` 22; uritemplate `match.go`, `escape.go`; jsonparser `parser.go` 732 | network interface listing for version 1/2/6 UUIDs; quadratic matching and imperfect escaping of URI templates; panics on truncated JSON in `Delete`/`Set` | not used: mcp-go makes version 4 UUIDs, Engram registers no resource templates, mcp-go does not call those jsonparser functions |
| G-8 | info | libc `libc_musl.go` 164 | `init()` reads `/proc/self/exe` and the page size; the environment is copied into C's `environ` | no I/O beyond that |

**No patches to Engram:** every change the packaging needs is in the entry point, which uses only Engram's
exported API (`mcp.NewServerWithConfig`, `mcp.ResolveTools`, `store.New`, `store.FallbackConfig`,
`store.ProjectExists`, `store.CreateSession`, `store.NormalizeProject`) and mcp-go's (`ListTools`, `AddTools`,
`NewStdioServer`, `Listen`).

## Tools (`tools.json`, 23: Engram's `agent` profile)

Write: `mem_save` (an observation: title, type, content; `topic_key` upserts), `mem_update`, `mem_save_prompt`,
`mem_capture_passive`, `mem_session_summary`, `mem_session_start` (without `directory`), `mem_session_end`,
`mem_session_finalize`, `mem_consolidate` (preview, then confirm with its fingerprint; sources are soft-deleted),
`mem_judge`, `mem_judge_many`, `mem_compare` (verdicts on possibly conflicting memories), `mem_review` (list or mark
reviewed), `mem_pin`, `mem_unpin`. Read: `mem_search` (FTS5, every word quoted: no query operators), `mem_search_prompts`,
`mem_context` (recent sessions, at most 64 KiB), `mem_get_observation`, `mem_suggest_topic_key`,
`mem_current_project` (without `directory`/`cwd`), `mem_list_projects`, `mem_doctor` (read-only diagnostics; runs a
passive WAL checkpoint). No tool takes a file path; nothing talks to Engram Cloud, an LLM or the network.

## Network, data and files

- `network: none`: the container has no network namespace; the linked code has no network client (the HTTP
  transports of mcp-go are compiled in, never started).
- Data: the folder mounted writable at `/data` (required): `engram.db` (0600) with `engram.db-wal`/`-shm` (WAL,
  persistent), `.instance-id` (0600), `.instance-id.lock` and `.migrate.lock` (flock). Engram refuses NFS and SMB
  (`statfs`). One folder per case or project: `--mount /data=~/brains/CASE:rw`; `ENGRAM_PROJECT` names the project
  inside it (default `brain`).
- Without a mount `/data` is part of the read-only root: the server starts, lists its tools, and every call answers
  "no memory: /data is not a writable folder ...".
- Outside `/data` the server reads only `/proc/<ppid>/stat` (skipped under an init) and zoneinfo; it writes nothing
  else (stderr only).

## Tested

- Not built here: no Go toolchain and no container engine in this sandbox (`proxy.golang.org` is not reachable
  either). The entry point and its tests (`src/main_test.go`) compile and run first in CI's image build.
- `tests/test_analysis_servers.py` (`Engram`, `BrainServers`): the commit and every reviewed file pinned and listed
  here, only `internal/mcp` and `internal/store` imported, no `os/exec`/`net` in the entry point, the 23 tools equal to
  the test's list, the refused folder arguments, no git in the image.
- CI: the image build (file and module checks, `go vet`, `go test`), then the smoke spec with the hardened run line
  and a fresh writable `/data`: `mem_current_project` says `brain`, `mem_save`, `mem_search` finds it,
  `mem_get_observation` reads it back, `mem_list_projects`; refused: `directory` and `cwd`, a 1,025-byte query, a
  `limit` of 100,000, `mem_merge_projects` and `mem_delete` (not offered). Then Trivy (the Go standard library of
  1.26.10 is scanned in the binary), and sandbox-ai's own Podman and Bubblewrap runs.

## Verdict

Reviewed completely: every linked line of Engram and mcp-go, the other modules on their risky surfaces, the entry
point ours. One medium finding (E-1) and the folder-scanning arguments (E-2) are handled in the entry point; nothing
needed a patch. Ready for CI; sign once both smoke reports pass. Only CI can show that the entry point compiles
against Engram and mcp-go as reviewed.
