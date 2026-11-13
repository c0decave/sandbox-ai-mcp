# Security policy

## Reporting a vulnerability

Please report vulnerabilities privately through GitHub's **Report a vulnerability** button
(Security tab of https://github.com/c0decave/sandbox-ai-mcp, private vulnerability reporting).
Do not open a public issue for a vulnerability. Include the server, the image digest, what an
attacker controls (tool arguments, a fetched page, a search answer, a file) and what they gain.

We aim to acknowledge a report within 7 days and to publish a fixed image, with a new digest in
`catalog.json`, as soon as a fix is verified.

## Scope

- the MCP servers in `servers/*/src`: argument validation, address and path checks, anything
  that lets a tool call or an answer escape the intended behaviour. radare2 has no `src`: its MCP
  server is upstream's r2mcp, built from the pinned commit and started with radare2's own sandbox
  (`-s /work -g none`); the packaging and those flags are in scope, r2mcp's own code upstream;
- the file-analysis servers (radare2, capa, binwalk): a path that escapes the folder mounted at
  `/work`, a write outside `/out` and the container's `/tmp`, anything a crafted input file makes
  the server do beyond reporting about it;
- youtube: a token, the client secret or an upload session reaching a tool answer, a log line or a host other
  than `oauth2.googleapis.com` and `www.googleapis.com`; a file uploaded from outside `/upload` (a link, a
  device, another user's file); a public video without `YOUTUBE_ALLOW_PUBLIC=1`;
- exec: a command that keeps running after its time limit or `stop_job` (beyond a daemon that double-forks into a
  session of its own, which ends with the connection), a start folder outside `/work` accepted, a command reaching
  the server's MCP connection (its `/proc` entries), a variable of the server's environment reaching a command
  without `EXEC_ENV_ALLOW`, `lint` running code of the project, output beyond the documented bounds held in memory;
  the commands themselves can do anything inside the container and `/work` - that is the tool's purpose;
- tasks: a read or write outside `/work/.tasks` (through a link or otherwise), a lost change when several connections
  write one plan, a plan it cannot read overwritten;
- the Dockerfiles and the published images `ghcr.io/c0decave/sandbox-ai-mcp-*` (a pinned
  component with a known vulnerability, a wrong user, a missing pin);
- `scripts/make_catalog.py` and `catalog.json` (anything that could make sandbox-ai or axross pull
  an image other than the one reviewed).

Vulnerabilities of upstream components (Playwright MCP, Chromium, pyghidra-mcp, Ghidra, Telethon,
radare2, r2mcp, capa, binwalk and its extractors, the Python packages) belong upstream, unless the
packaging here makes them reachable in a way upstream does not. A crash of an analysis tool on a
crafted file is such an upstream matter; it happens inside a container with no network, no
capabilities and a read-only root.

## The model behind these images

- sandbox-ai and axross run them with the same container flags: no capabilities, no new
  privileges, read-only root file system, `noexec` /tmp, process and memory limits, rootless
  podman, no network unless granted, only the folders the user mounts.
- Tool arguments come from a language model and are untrusted; so are fetched pages and search
  answers.
- Images are referenced by digest only. A digest in `catalog.json` changes only through
  `scripts/make_catalog.py` from the digests a CI run reports.
- CI fails a build when Trivy finds a CRITICAL vulnerability with an available fix.
