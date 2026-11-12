# web-fetch - provenance and audit

| | |
|---|---|
| MCP server | this repository, `src/server.py` (MIT, `LICENSES/`) |
| Python packages | `mcp==1.30.0` and its dependencies (httpx), hash-locked in `requirements.txt` |
| Debian packages | `python3=3.13.5-1`, `ca-certificates=20250419+deb13u1` |
| Base image | the `debian:trixie-slim` digest in `Dockerfile` |

## Why

An agent whose own sandbox has no network can read public web pages through this server, which
runs in a container of its own: it has the network, but no access to the agent's files.

## Audit

**Tool:** `fetch_page(url, max_characters, start, links)`: `GET` of an http(s) URL.

**Addresses:** before each request (the first and every redirect) the host name is resolved and
every address must be public (`ipaddress.is_global`, not multicast): loopback, private,
link-local (cloud metadata at 169.254.169.254), carrier-grade NAT, documentation and reserved
ranges are refused, also when written as an IP literal. Behind sandbox-ai's Tor profile (`SANDBOX_AI_TOR=1` and `SANDBOX_AI_TOR_VIRTUAL_NETWORK`, an IPv4 range inside 10.0.0.0/8) the addresses of that range - Tor's addresses for onion services - are taken too, so `.onion` URLs work; nothing else of the local ranges is. Without a Tor profile a `.onion` name is refused before it is looked up, and every refusal says what the address is and what would apply (`tests/test_onion_behind_tor.py`). URLs with a user name or password,
other schemes and control characters are refused. Remaining risk: the check resolves the name
before the request, so a resolver that answers differently a moment later (DNS rebinding) is not
ruled out; the container itself should not be given more than the full outside network.

**Answers:** at most 5 redirects; text and HTML only (other content types are refused); 5 MiB;
timeout 30 s. HTML is reduced to title, readable text (script, style, svg, head dropped) and
optionally its http(s) links (at most 200); long texts are returned in parts.

**Network:** full.

**Tested:** natively (`tests/test_own_servers.py`: handshake, tools/list, loopback, localhost,
::1, 169.254.169.254, file: and user:password URLs refused, the HTML reduction).
