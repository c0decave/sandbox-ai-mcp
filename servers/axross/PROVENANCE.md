# axross - provenance and audit

| | |
|---|---|
| MCP server | **axross-headless-mcp 0.15.180** (c0decave/axross-headless-mcp, Apache-2.0) - the user's own project: axross's MCP server written out of axross (c0decave/axross) by its `scripts/export_standalone.py`, without Qt. Tag `v0.15.180` (annotated, tag object `ad170393`), commit **`079769632443724b24bcf9aa3f288edbc456b9e5`** (2026-11-20). The repository's HEAD on 2026-11-20 is one commit later (`0ba44233`: a Dockerfile at the root for Glama and the Docker MCP Catalog), which is in no wheel and not used here |
| As installed | the PyPI wheel `axross_headless_mcp-0.15.180-py3-none-any.whl`, uploaded 2026-11-20T09:01:28Z, sha256 **`ab2f9b2fd8cfcfbe1f5ba5aa94267e357886c5f577d5c786f2709f9e758a3c7f`** (sdist `4e0cdd39...`, not installed). Its 259 files under `axross_headless_mcp/` are **byte for byte the tag's `src/`** (compared file by file; the wheel adds only its `dist-info`: one console script, `axross-headless-mcp`, not used). The GitHub release of the tag carries a wheel with another hash (`2b402d7d...`, in its `SHA256SUMS`) and the same 259 files: the two were built separately (time stamps in the zip), so the release's checksum file does not vouch for PyPI's file (finding 12) |
| What runs | `src/server.py` of this repository (MIT): fixes the root, the groups, the folders, the keyring, refuses every module not reviewed, then runs upstream's `core.mcp_cli.main` unchanged |
| Kept in the image | **65 files, 42,294 lines** of the package (`reviewed.sha256`, each checked by SHA-256 when the image is built); the other 194 files (118,970 lines of Python and the data under `resources/`) are deleted, and `src/server.py` refuses to import any module outside the list |
| Python packages | 22 pins hash-locked in `requirements.txt` (19 on Linux); `invoke`, `secretstorage` and `jeepney` are uninstalled again in the image (below) |
| Debian packages | `tini=0.19.0-3+b8` (the image's init, its ENTRYPOINT: no host init needed), `python3=3.13.5-1`, `ca-certificates=20250419+deb13u1` (as every Python server here) |
| Base image | the `debian:trixie-slim` digest in `Dockerfile` |

## Pinning rule

The rule that a release must be 14 days old is for third-party releases; axross-headless-mcp is the user's own project,
so its newest release, 0.15.180 of 2026-11-20 (0.15.179 was 2026-11-19), is pinned. Its **third-party** dependencies
follow the rule: the lock was made with `uv pip compile --universal --python-version 3.13 --generate-hashes
--exclude-newer 2026-11-06T00:00:00Z --exclude-newer-package axross-headless-mcp=2026-11-21T00:00:00Z` (uv 0.13.8) from
`requirements.in`; every other pin was uploaded on or before 2026-11-05 (PyPI upload times, checked one by one):
`pycparser` 3.12 (2026-10-22), `paramiko` 5.1.0 (2026-10-18), `more-itertools` 11.2.1 (2026-10-14), `rpds-py` 2026.9.1
(2026-10-04), `cryptography` 50.0.2 (2026-09-30), `cffi` 2.1.1 (2026-08-03), `jaraco-functools` 4.6.0 (2026-07-14),
`invoke` 3.0.3 (2026-04-07), `jaraco-context` 6.1.2, `attrs` 26.1.0 (2026-03), `jsonschema` 4.26.0, `pynacl` 1.6.2
(2026-01), `secretstorage` 3.5.0, `keyring` 25.7.0 (2025-11), `referencing` 0.37.0, `bcrypt` 5.0.0,
`jsonschema-specifications` 2025.9.1 (2025-09), `jeepney` 0.9.0 (2025-02), `pywin32-ctypes` 0.2.3 (Windows only),
`jaraco-classes` 3.4.0 (2024), `pysocks` 1.7.1 (2019). `cryptography`, `cffi`, `pycparser`, `attrs`, `jsonschema`,
`referencing` and `rpds-py` are the versions the other servers of this repository ship.

## What the server does (as this image runs it)

Upstream's MCP server (protocol 2025-11-25, 2025-06-18, 2024-11-05) over stdio, with `--mcp-root /work --mcp-tools remote`
and, only with `AXROSS_WRITE=1`, `--mcp-write`. **23 tools** (`tools.json`), 14 of them read-only:

| Tools | What they read, write or reach |
|---|---|
| `list_dir`, `stat`, `read_file`, `checksum`, `search`, `walk`, `recursive_checksum`, `grep`, `list_versions`, `open_version_read` | read: the folder mounted at `/work`, or an opened profile (`backend='profile:NAME'`). `read_file` at most 4 MiB a call (text or base64, with `offset`), `grep` a regex in a child process killed after 5 s a file (files of at most 4 MiB, at most 500 matches), `walk` at most 100,000 entries and 64 levels, `checksum` sha256/sha1/md5/sha512 (on SFTP: the server's `sha256sum`, else streamed). `search` asks axross's metadata index, which is empty in this image (the index group is not offered): it answers `[]` |
| `write_file`, `mkdir`, `remove`, `rename`, `copy`, `bulk_copy`, `symlink`, `hardlink`, `chmod` (**only with AXROSS_WRITE=1**) | write: in `/work` (the mount must be `:rw`) or on an opened profile. Writes are atomic (a temporary file in the target's folder, renamed); `chmod` only the bits of 755; a file with other hard links is not written; a symlink in `/work` only to a target in `/work`; the root itself is never removed or renamed; on a profile flagged *production* every write is refused; on a remote, a path with `..` is refused for writes |
| `remote_profiles`, `remote_open`, `remote_close`, `list_backends` | read `/axross/profiles.json` (no secret is listed); `remote_open` connects one SFTP profile (at most 8 open): TCP to the profile's host and port, the host key checked against `/ssh/known_hosts` (an unknown key is refused with how to check and add it, a changed one refused; nothing is ever trusted on first use), then the password from `AXROSS_PASSWORDS` or the key file of that name in `/ssh` |

**What it connects to:** nothing but the SFTP host of a profile the agent opens, and only when the human gave the
server a network (the catalog's `network` is `none`). **What it starts:** one child Python per `grep` (`python -I -S -c`
with the matcher's own code, stdin/stdout pipes, 1 GiB address space, a CPU limit, killed with its parent); nothing
else (no ProxyCommand, no `file(1)`: see below). **On a remote** the SFTP backend also runs a few fixed commands over
the SSH connection - `sha256sum`/`sha1sum`/`md5sum -- PATH` for `checksum`, `cp -p -- SRC DST` for `copy`, `ln -- T L`
for `hardlink`, `df -Pk -- PATH` - each path quoted with `shlex.quote`; never anything else (`remote_exec` and
`remote_script` belong to the `exec` group, which is not offered). **What it writes besides the tools' targets:** in
its HOME, `/tmp/home` (the container's tmpfs, gone with the container): the log (`.local/state/axross/logs/axross.log`,
5 MiB x 4 at most), the operation journal, half-written-file records, the visit history, a lock file. The audit trail
(tool, outcome, paths and sizes - never contents) goes to stderr too.

## What `src/server.py` fixes (and why)

1. **The root and the groups.** `--mcp-root /work`, `--mcp-tools remote`, `--mcp-write` only with `AXROSS_WRITE=1`;
   no `--mcp-http`, `--mcp-allow-scripts`, `--mcp-allow-exec`, `--mcp-allow-secret-reads`. The server takes no
   arguments. Upstream reads `AXROSS_MCP_TOOLS`, `AXROSS_MCP_WRITE` and `AXROSS_MCP` from the environment: every
   `AXROSS_*` variable except `AXROSS_MCP_REMOTE_TIMEOUT` and `AXROSS_SECURITY_MODE` is dropped, and so are `XDG_*`
   (which would move axross's state and journal into the root), `GIT_CONFIG*`, `PYTHON_KEYRING*`, `SSH_AUTH_SOCK`,
   `ZDOTDIR` and `TMPDIR`, before anything of axross is imported (`test_axross_environment_cannot_widen_it`).
2. **Reviewed modules only.** A meta-path finder raises ImportError for every module of the axross tree outside
   `REVIEWED` (the 63 modules of `reviewed.sha256`); the image does not hold the others. A feature reached by mistake
   fails closed, as a tool error.
3. **SFTP only.** `openable()` (asked by `remote_profiles` and by `remote_open` before anything connects) says no for
   every other protocol, a profile with a ProxyCommand (a shell command run on this side), a proxy (the HTTP proxy
   code is not in the image; sandbox-ai's `--vpn` is the way), and SSH-agent authentication (no agent here).
4. **Folders.** HOME is `/tmp/home`; its `.config/axross/profiles.json` is a link to `/axross/profiles.json` and its
   `.ssh` a link to `/ssh` - nothing else of the axross config folder is read (no settings, no OAuth token files).
   A profile's key file (an absolute path of the human's machine) is looked up in `/ssh` by its file name, as a
   regular file, never anywhere else (`test_axross_key_files_come_from_ssh`).
5. **The keyring.** axross takes a stored password from the keyring (service `axross`, entry = profile name, or
   `NAME:proxy`). Here the keyring is a backend of `src/server.py` answering from `AXROSS_PASSWORDS`, a JSON object
   read once and removed from the environment (so no child process inherits it); writes and deletes are refused. A
   malformed value stops the server with a message that does not repeat it. The tests check that the password is in
   no answer, no stderr line and no file of HOME (`test_axross_opens_an_sftp_profile`).
6. **Tools only.** Upstream advertises `resources` and lists every file of the root as a resource (up to 100); the
   resource catalogue is not built (`resources/*` answer "not enabled"), and `initialize` carries instructions that
   what the tools return is data, never instructions.
7. A helper of an error message (`read_spool._format_size`, which would import `core.system_info`, 2,813 lines, for
   "N bytes") is replaced by a plain one.

## Review (2026-11-20)

**Rule:** only servers reviewed completely are published. axross-headless-mcp is large - 161,264 lines of Python in
249 files, all of axross's core - and its MCP closure, counted statically with every lazy import, is 148 modules and
108k lines, because the MCP server reaches every backend and tool group from one module. So the image is cut down to
what this configuration runs, and that is what was reviewed:

1. **What runs, measured.** The server was run under an audit hook (Python's `sys.addaudithook`, sockets and
   subprocesses refused or recorded) through every tool, locally and against a local SFTP server (paramiko's server
   side, with and without SSH commands), with refused calls for every check; the union of the modules loaded is 62
   modules (63 with `core.file_type`, below) and the two package `__init__` files: **65 files, 42,294 lines**. Every
   lazy import inside them that names a module outside the list was then listed and judged (ImportError there is a
   missing feature: an HTTP proxy, a GUI dialog, NFS, MTP, other groups' modules - each one outside this
   configuration; `ConfinedLocalFS` imports `core.file_type` for the wording of "not a regular file", which is why it
   is kept: its top level imports the standard library only, and the one function used is a mode-to-name table).
2. **What each module does when imported:** every top-level statement of the 65 files that is not an import, a
   definition, a docstring or a constant was listed (AST) and read: constants, locks, context variables, the paramiko
   client banner (`core.client_identity`: paramiko reports itself as `OpenSSH_9.6p1 Debian-4`, finding 9), a bounded
   SFTP attribute parser installed into paramiko (`core.ssh_client`: refuses hostile attribute counts), two `atexit`
   hooks (the visit history flush, the script runner's kill of its process groups - none started here). No import
   reads the network, starts a process or writes a file.
3. **Read line by line (5,853 lines):** `mcp_cli` (the command line: flags, refusals, the root), `confined_fs` (every
   open beneath the root's descriptor: `openat2(RESOLVE_BENEATH | RESOLVE_NO_SYMLINKS | RESOLVE_NO_MAGICLINKS)`, else a
   walk with `O_NOFOLLOW | O_DIRECTORY`; writes via a temporary file renamed in the parent's descriptor; hard-linked
   files refused; the tree removal), `regex_worker` (the child process and its protocol), `credentials` (the keyring
   use), `local_fs`, `path_policy`, `subprocess_env`, `exec_util`, `redaction`, `partials`, `security_mode`,
   `tls_env`, `client_identity`, `xdg_dirs`, `json_store`, `secure_storage`, `structured_log`, `posix_compat`,
   `open_limits`, `ramfs_settings`, `svg_gate`, `tmpfs_detect`, the package `__init__`s and `axross/_version`.
4. **Read along the paths this configuration takes (about 5,100 of the 24,541 lines of 12 modules):** `mcp_server` - the root checks
   (`_enforce_root`, `_enforce_root_entry`, `_refuse_protected`, the confinement of the backend), `_build_tools`' path
   helpers, every handler of the 19 file and write tools, `grep` and its walk, the checksum paths, the dispatcher
   (initialize, the lifecycle, `tools/call` with its schema check, rate limit, time limits, cancellation, result caps),
   `serve`, the stdio loop and the resource catalogue that is switched off; `mcp_groups` - `openable`,
   `check_remote_path`, `RemoteRegistry` (open, close, production, the host-key errors), the `remote` group's tools;
   `ssh_client` - `connect`, `_verify_host_key`, `trust_current_host_key` (never called: `remote_open` passes no
   prompt), `_authenticate`, `load_private_key`, `agent_with_keys`, every `exec_command` site (`hardlink`, `df`,
   `copy`, `checksum`, `exec`) and `command_bytes`, the attribute parser; `protected_places` - the secret rules
   (`secret_in_content`, `inside_key_block`, `SecretScanningReader`, `remote_secret_refusal`, the names and patterns);
   `proxy.create_direct_socket` and its host check; `server_ops.server_side_copy`; `connection_manager._create_session`
   and its lazy loader; `profiles` (the file, `password_needed`, the keyring fields); `telnet_client.copy_command`;
   `read_spool` (where remote reads spool); `conn_health` (its probe thread); `file_type._special_description`.
5. **The rest (about 31,300 lines: the other functions of those 12 modules, and `backend_registry`, `log_config`,
   `i18n`, `atomic_io`, `operation_journal`, `metadata_index`, `sftp_io`, `visit_history`, `mcp_script_pin`,
   `script_runner`, `previews`, `db_fs_base`, `backend_guard`, `log_areas` and the small rest): by the scan below,
   every hit read, and by the measured runs.** Most of it is code for other backends, other groups or the GUI
   that this configuration does not call (the audit-hook runs saw what it calls); `atomic_io`, `sftp_io` and
   `operation_journal` are on the write paths and were seen working there, not read line by line.
6. **Scan of every kept file and every installed wheel:** files that run at interpreter start (`*.pth`,
   `sitecustomize`, `usercustomize`: none); native code; `subprocess`/`os.system`/`os.popen`/`os.exec*`/`pty`,
   `exec(`/`eval(`, `pickle`/`marshal`, `__import__`/`import_module`, `ctypes`, base64 decoding, `urlopen`/`http.client`/
   `socket.create_connection`/`requests`, every URL, `telemetry`/`update`, and every environment variable read. In the
   kept axross code the hits are: the regex worker's child (above); `ctypes` for `openat2`, `renameat2` and the
   worker's `prctl(PR_SET_PDEATHSIG)`; the SFTP ProxyCommand (`CleanEnvProxyCommand`, refused by the entry point);
   `script_runner`'s `exec` and `subprocess` (only `script_run`, a tool of the scripts group, not offered);
   `file_type.file_command_description` (`file(1)`, only for the filetype group, not offered); `importlib` in the
   backend registry (its own modules by name, the ones not in the image fail) and `connection_manager` (its lazy
   classes); base64 decoding of `content_b64` arguments. **No telemetry, no update check, no download of code** - the
   self-updater (`core/self_update.py`, 1,475 lines) and everything that fetches are among the deleted files.
7. **Third-party code.** `paramiko` 5.1.0 (18,621 lines, LGPL-2.1, new here): by the scan only - axross uses its
   public client API (`Transport`, `auth_password`, `auth_publickey`, `SFTPClient`, `PKey` loading; known_hosts
   is read by axross itself), the same API every paramiko-based tool uses; its only process is `ProxyCommand`
   (`paramiko/proxy.py`, never used here), its `config.py` imports `invoke` only for an SSH config's `Match exec`
   (axross never uses paramiko's SSHConfig); no network but the socket it is given. `keyring` 25.7.0 (2,519 lines) with `jaraco.*` and `more-itertools`: read `core.py`
   (`set_keyring`, `get_password`; its `__import__` of a backend named in the environment or a config file never runs
   once a backend is set, and the variable is dropped) and `backend.py`; `jaraco.context`'s `urlopen`/`subprocess`
   and `jaraco.functools`' `eval` are in helpers keyring does not call. `PySocks` 1.7.1 (847 lines, SOCKS proxies:
   refused by the entry point). `bcrypt` 5.0.0 and `pynacl` 1.6.2 are native (Rust, libsodium), used by paramiko for
   ed25519 and bcrypt-protected OpenSSH keys. **Removed from the image after the install:** `invoke` 3.0.3 (14,808
   lines with a vendored YAML, a command runner), `secretstorage` 3.5.0 and `jeepney` 0.9.0 (D-Bus, the desktop's
   Secret Service): imported only for what this server never does; the Dockerfile checks they are gone and that
   `paramiko.config.invoke` is None.

**What this means for signing:** the files that run were measured, every file that ships was scanned and its import
time read, and the security-relevant code - the root, links, secrets, the keyring, host keys, authentication, every
process and every remote command - was read line by line: **about 11,000 of the 42,294 lines that ship**. The other
**about 31,300 lines** (item 5) and paramiko were not read line by line. That is less than this repository's rule
asks of a third-party server ("reviewed completely"). It is the user's own code: the user decides whether the
measured closure, the cut-down image, the import guard and this reading are enough to sign, or whether item 5 gets
a pass of its own first (a list of its modules and functions: `python3 -I` over `reviewed.sha256`'s files).

## Findings

1. **Resources list the whole root (switched off here).** Upstream advertises `resources` and `resources/list` returns
   up to 100 files of the root (names, sizes), `.env` and `id_rsa` included (their contents stay refused). Local models
   take resource tools for the way to the server's tools; the entry point builds no resource catalogue.
2. **The environment widens the server (dropped here).** `AXROSS_MCP_TOOLS=all`, `AXROSS_MCP_WRITE=1` and
   `AXROSS_MCP=1` switch on groups and writing without a flag; `XDG_STATE_HOME`/`AXROSS_OPERATION_JOURNAL`/
   `AXROSS_METADATA_DB` move axross's files. By design upstream; here every such variable is removed first.
3. **A remote is not confined (documented; upstream suggestion).** `--mcp-root` applies to the local disk only: an
   opened SFTP profile gives the agent every path the SSH account can reach, and with `AXROSS_WRITE=1` it can change
   them. axross refuses `..` in remote write paths, secret names on the remote (`~/.ssh/*` but public keys,
   `.env`, histories, `/proc/*/environ`, TLS private keys) and every write on a *production* profile. Use an account of
   its own for the profile, best a chroot'ed `internal-sftp` one. Suggestion for axross: an optional remote root per
   profile (its start folder), enforced like `--mcp-root`.
4. **Encrypted key files cannot be used (upstream suggestion).** `remote_open` passes no key passphrase
   (`ConnectionManager.connect(profile, password=...)`), so an encrypted key fails with "needs a passphrase". Suggestion:
   take it from the keyring like the password (`NAME:secret:key_passphrase`).
5. **Host keys: strict (good).** `remote_open` gives no prompt, so an unknown host key is refused with the command to
   check and add it, a changed one is refused, `@revoked` keys are refused, and nothing is ever appended to
   known_hosts (`/ssh` is read-only anyway). Tested against the local SFTP server: no password is sent to a host whose
   key is unknown.
6. **Servers that refuse commands: checksum and copy fail (upstream bug, functional).** Against an SFTP server that
   runs no SSH commands (OpenSSH with `ForceCommand internal-sftp`, the restricted setup finding 3 recommends),
   `checksum` answers "checksum failed: the server refuses to run commands" instead of hashing by streaming, and
   `copy` "SSH copy: the server refused the command" instead of copying by streaming: `SSHSession.checksum` raises on
   `_ExecRefused` where `_hash_one_path` expects `""`, and `server_ops._copy_fallback_allowed` does not count
   `_ExecRefused` as "unsupported". Reproduced with the test server; `read_file`, `write_file`, `rename`, `remove`,
   `mkdir`, `bulk_copy` and `chmod` work there. Suggested fix: `checksum` returns `""` once commands are refused, and
   `_ExecRefused` allows the stream fallback.
7. **Remote commands without the exec group (documented).** On SFTP, `checksum`, `copy`, `hardlink` and the free
   space run `sha256sum`, `cp -p`, `ln` and `df` on the remote host (every path `shlex.quote`d after `--`); they show
   in the remote's logs as commands of that account. Not a way to run other commands.
8. **Secrets stay put (good; one consequence).** Files that hold credentials by their name, and any file whose
   contents hold a private key's BEGIN/END line, a PuTTY key or a KeePass signature - in the first MiB, and for every
   byte read past it through the scanning reader - are refused by every reading tool, also through a link; this image
   never offers `--mcp-allow-secret-reads`. A project with test keys in its sources gets those files refused.
9. **It calls itself OpenSSH (documented).** paramiko's client banner is set to `SSH-2.0-OpenSSH_9.6p1 Debian-4`
   (`core.client_identity`, axross's OPSEC choice), so a server's log shows an OpenSSH 9.6 client, not paramiko.
10. **Limits worth knowing.** 30 tool calls at once, then one a second (`tools/call rate limit exceeded`); one
    `read_file` answers up to 4 MiB (base64: about 5.6 MB) - small local models should pass `max_bytes`; results at
    most 16 MiB; time limits 15 s (quick tools), 60 s (walk, grep), 30 s (writes), 300 s (hashing), 1800 s (copies).
11. **The wheel ships far more than the server (cut here; upstream suggestion).** The package holds all of axross's
    core: a credential-attack module (`core/cred_attack.py`), a port-scan script, an offensive MCP discovery list, the
    self-updater, an LLM agent, a reverse file server and 40 backends - reachable only through groups and flags this
    image does not set, and deleted from it. Suggestion: `export_standalone.py mcp` could write only the MCP closure
    of the default groups (and the extras as their own wheels).
12. **Two wheels for one release (upstream suggestion).** PyPI's and the GitHub release's wheel of 0.15.180 differ in
    their hash (`ab2f9b2f...` and `2b402d7d...`) though their files are the tag's byte for byte: the release workflow
    builds twice. With one build uploaded to both (or `SOURCE_DATE_EPOCH`), the release's `SHA256SUMS` would vouch for
    the file pip installs. The pin is PyPI's hash, checked against the tag here.
13. **An error message pulled in a large module (worked around).** `read_spool`'s free-space message imported
    `core.system_info` (2,813 lines) for a size format and `ConfinedLocalFS` imports `core.file_type` (868 lines) for
    the name of a special file; the first is replaced, the second kept (item 1 of the review).

**Nothing has to change in axross's code before this image is signed**: the cut, the import guard and the entry
point cover findings 1, 2, 11 and 13; 3, 7, 8, 9 and 10 are documented in the catalog entry's notes; 4, 6 and 12 are
suggestions for axross, not risks. What the user has to decide is the review depth above.

## Tests

`tests/test_axross.py` (6, no packages needed): the pin (tag, commit and wheel hash in this file, the lock's
packages), the manifest against `REVIEWED`, the recorded tools, the catalog entry, the smoke spec, the Dockerfile's
steps. `tests/test_own_servers.py` `Axross` (9; in CI inside the image with its own Python, no network; here with a
venv of `requirements.txt` and the package cut down as the Dockerfile cuts it): the tools with and without
`AXROSS_WRITE`, tools only and the instructions, the environment that cannot widen it, `/work` (`..`, absolute paths,
a link out, `.env`, writes through a link, a symlink to `/etc/shadow`, setuid), the import guard, `AXROSS_PASSWORDS`,
an SFTP profile against a local paramiko server (list, read, write, `..`, close; the password nowhere in answers, logs
or files), an unknown host key (refused, nothing sent, nothing trusted), a key file from `/ssh`, and the profiles this
image does not open (SMB, ProxyCommand, a SOCKS proxy, an SSH agent). `smoke.json`: 12 calls, 6 of them refused.
