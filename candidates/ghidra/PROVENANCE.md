# ghidra (prepared) - provenance and audit notes

| | |
|---|---|
| MCP server | clearbluejar/pyghidra-mcp 0.3.0 (Apache-2.0), PyPI, commit `aeaf4d16b0ce09b6dc5e16bb56d204025d2f6f8e` |
| Ghidra | 12.2 (`Ghidra_12.2_build`, Apache-2.0), release zip checked against the SHA-256 GitHub publishes |
| Python packages | `pyghidra-mcp==0.3.0` and 100 dependencies (pyghidra 3.2.0, mcp 2.3.0, chromadb 1.5.9, ghidrecomp 0.5.9, onnxruntime 1.31.1, ...), hash-locked in `requirements.txt` |
| Java | Debian `openjdk-21-jre-headless` (version to pin) |

**Re-pin before building:** 2026-11-16 or an older release. `pyghidra-mcp` 0.3.0 was published 2026-11-02, and 24 of the hash-locked dependencies in `requirements.txt` (pydantic 2.14.2, onnxruntime 1.31.1, opentelemetry 1.45.2, huggingface-hub 2.4.0, ...) on 2026-10-24 to 2026-11-02: too new under the pinning rule (`docs/CANDIDATES.md`) until 2026-11-16 at the latest. Re-lock with uv's `--exclude-newer` set 14 days back; an older pyghidra-mcp needs its own audit. Ghidra 12.2 (2026-10-22) is old enough.

**State:** not built. The Debian package versions could not be looked up where this was
prepared; the Dockerfile refuses to build until they are set (see its header).

**Tools (headless):** decompile_function, search_symbols_by_name, search_code (semantic search
with chromadb), list_project_binaries, list_project_binary_metadata, rename_function,
rename_variable, set_variable_type, set_function_prototype, set_comment, save,
delete_project_binary, list_exports, list_imports, list_xrefs, search_strings, read_bytes,
disassemble, gen_callgraph, import_binary. The GUI tools are not registered with `--no-gui`.

**Files:** `import_binary` takes any path inside the container; only `/work` (the samples,
read-only) and `/out` (the Ghidra project, writable) are mounted, so nothing of the host beyond
them is reachable. The project path is fixed to `/out/ghidra-projects` by the entry point.

**To check when building:** memory (Ghidra's analysis needs well over 512 MiB; the definition
in sandbox-ai sets `--memory=4g`), process limit (the JVM's threads), analysis time of large
binaries, that chromadb's embedding model is not downloaded at run time (no network) or is
baked into the image.

**Network:** none.
