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
  that lets a tool call or an answer escape the intended behaviour;
- the Dockerfiles and the published images `ghcr.io/c0decave/sandbox-ai-mcp-*` (a pinned
  component with a known vulnerability, a wrong user, a missing pin);
- `scripts/make_catalog.py` and `catalog.json` (anything that could make sandbox-ai or axross pull
  an image other than the one reviewed).

Vulnerabilities of upstream components (Playwright MCP, Chromium, pyghidra-mcp, Ghidra, Telethon,
the Python packages) belong upstream, unless the packaging here makes them reachable in a way
upstream does not.

## The model behind these images

- sandbox-ai and axross run them with the same container flags: no capabilities, no new
  privileges, read-only root file system, `noexec` /tmp, process and memory limits, rootless
  podman, no network unless granted, only the folders the user mounts.
- Tool arguments come from a language model and are untrusted; so are fetched pages and search
  answers.
- Images are referenced by digest only. A digest in `catalog.json` changes only through
  `scripts/make_catalog.py` from the digests a CI run reports.
- CI fails a build when Trivy finds a CRITICAL vulnerability with an available fix.
