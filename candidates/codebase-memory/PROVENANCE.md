# codebase-memory (prepared) - provenance and audit notes

| | |
|---|---|
| MCP server | DeusData/codebase-memory-mcp 0.12.1 (MIT), tag `v0.12.1`, commit `a7158ac2f48ca646b4527341b76f930f2aeff87e` (release of 2026-10-16) |
| Binary | `codebase-memory-mcp-linux-amd64-portable.tar.gz` (fully static build), SHA-256 `8c3d0341064301e78ecc84cf7348d4e2c6562a0f57448243ea560aaa34de36c1`: the digest GitHub publishes for the asset, the line in the release's `checksums.txt`, and the hash of the downloaded file agree |
| git | Debian `git` `1:2.47.3-0+deb13u1` (trixie main index of 2026-11-05) |
| Licences | MIT (`LICENSES/`, from the pinned commit); the vendored libraries' notices (`THIRD_PARTY_NOTICES.md` of the archive) are copied into the image |

**State:** not built. All pins are set; the image has not been built or smoke-tested. The
release also publishes SLSA provenance and cosign bundles (`*.bundle`); they were not
verified here (`gh attestation verify` needs a GitHub login).

**What it is:** a native C server (tree-sitter parsers for 162 languages, SQLite store) that
indexes a repository into a code graph. MCP over stdio. The default entry point starts a
detached daemon in the same container that the MCP process talks to; it ends with the last
client, so with one container per connection it lives as long as the connection.

**Tools (17):** index_repository, list_projects, delete_project, index_status,
check_index_coverage, search_graph, trace_path (alias trace_call_path), detect_changes,
query_graph, get_graph_schema, compare_graphs, get_code_snippet, get_file_outline,
get_architecture, search_code, manage_adr, ingest_traces (README section "MCP Tools",
handlers `handle_*` in `src/mcp/mcp.c`).

**Files:** `index_repository` reads any directory it is given; `CBM_ALLOWED_ROOT=/work` (set
by the image) makes it refuse paths outside `/work` after resolving symlinks and `..`
(`main_session_context` in `src/main.c`; also always refuses `/`, `/etc`, `/usr`, `$HOME`
and credential folders such as `.ssh`). `get_code_snippet`, `get_file_outline` and
`search_code` read files of indexed projects. Writes go only to `CBM_CACHE_DIR`
(`/out/codebase-memory`: SQLite indexes, ADRs of `manage_adr`, traces of `ingest_traces`,
logs) and `$HOME` (`/tmp`, its config). The repository can be mounted read-only.

**Processes:** git runs through `/bin/sh -c "git -C \"<repo>\" ..."`
(`src/foundation/compat_fs.c`, `src/git/git_context.c`). Interpolated values are checked by
`cbm_validate_shell_arg` / `cbm_validate_shell_path_arg` (`src/foundation/str_util.c`: refuse
quotes, `;|&$\`<>`, backslash, newlines); `detect_changes` also refuses a `base_branch`
starting with `-`. Repository-local git variables (`GIT_DIR`, `GIT_CONFIG_COUNT`, ...) are
stripped from the children (`src/foundation/git_env.c`), so the image trusts every directory in
`/etc/gitconfig` (`safe.directory=*`) for mounts owned by another uid.

**Network:** none needed. The README says the binary makes no request of its own (no update
check, no telemetry; `install`/`update` are separate commands not used here). The embedded web
UI (CBM Lens) is switched on by default when no config file exists and would listen on
`127.0.0.1:9749`; the entry point passes `--ui=false`. Its optional browser model download
only happens in the UI.

**To check when building:** memory (indexing large repositories needs more than 512 MiB;
start with `--memory=2g`), the process limit (index worker threads), that the daemon's
socket/lock files work with the read-only root and `noexec` /tmp, the size of the image (the
binary is 330 MB with the embedded UI), the tools/list of 0.12.1 for `tools.json`.

**Mounts:** `/work` (repository, read-only), `/out` (writable, indexes).
