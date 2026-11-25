# web-fetch - provenance and audit

| | |
|---|---|
| MCP server | this repository, `src/server.py` (MIT, `LICENSES/`) |
| Python packages | `mcp==1.30.0` and its dependencies (httpx), hash-locked in `requirements.txt` |
| Debian packages | `tini=0.19.0-3+b8` (the image's init, its ENTRYPOINT: no host init needed), `python3=3.13.5-1`, `ca-certificates=20250419+deb13u1` |
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
other schemes and control characters are refused. **DNS rebinding** (review of 2026-11-17, fixed): the
check resolved the name before the request and httpx resolved it again to connect, so a name that answered a
public address to the check and a local one a moment later reached the local one. Now httpcore's network backend
(`PublicBackend`) resolves the name where each connection is made, checks every address of that answer the same
way and connects to one of them (TLS still verifies the name, which httpcore gives as the server name); a Unix
socket is never opened. Behind a proxy (`HTTPS_PROXY`) the proxy connects, the check before the request holds.

**Answers:** at most 5 redirects; text and HTML only (other content types are refused); 5 MiB;
timeout 30 s per connection, read and write, and 90 s for the whole call (a host that sends a byte now and then
kept a call open for as long as it liked). The charset of the Content-Type, else of a `<meta charset>`, is
honoured (ISO-8859-1 and windows-1252 pages came as replacement characters; latin-1 is read as windows-1252, as
browsers do). HTML is reduced to title (300 characters), readable text (script, style, svg, head dropped; the head
ends where the body or anything of it starts, as HTML lets `</head>` out - such pages came back empty) and
optionally its http(s) links (at most 200 of 500 characters each, 8,000 characters together). A part is at most
24,000 characters and 400 lines with text, whatever `max_characters` asks (100,000 were allowed; clients show a
model only a preview of a tool result much above 25,000 characters), and `next_start` says where the next one
starts. The server's instructions and the tool's description say that a page's content is the page author's:
data, never instructions. It advertises tools only (no empty resources or prompts).

**Connection errors:** a connection that fails or is reset to a name with IPv6 and IPv4 addresses
is tried once more over IPv4 only (the client bound to 0.0.0.0, so only the name's IPv4 addresses
are taken; httpx's async client does not leave an IPv6 path that takes the connection and then
resets it, as a network without working IPv6 does). The retry starts from the requested URL again
and goes through every check again (the address check before each hop, redirects, content type,
size): it reaches no host the first try could not. Timeouts and answers are not retried. Every
error says what happened - refused (the port), reset (during the TLS handshake), no connection or
no answer within 30 s, no route (no IPv6 here), the name no longer resolving, the TLS certificate,
the proxy - and what to do next (do not fetch the URL again in a loop, try a timeout once more at
most, use another source); HTTP 404 and 410 say that the page does not exist. Inside a sandbox-ai
sandbox (`SANDBOX_AI_RUN`) a refused, reset or timed-out connection also names the `sandbox-ai net
allow` option the human can give, since the sandbox refuses a host that is not allowed this way.

**Network:** full.

**Tested:** natively (`tests/test_own_servers.py`: handshake, tools/list, loopback, localhost,
::1, 169.254.169.254, file: and user:password URLs refused, the HTML reduction; against servers on
loopback with a stand-in resolver: the retry over IPv4 only, a redirect to a private address refused
on the retry too, no retry for a name with IPv4 addresses only, the refused, reset and timed-out
errors with their advice, HTTP 404; review of 2026-11-17: a rebinding resolver refused at the connection, a page
without `</head>`, an SVG's title, parts within 24,000 characters and 400 lines that add up to the whole text, the
page's charset, the deadline against a dripping host, malformed URLs answered as errors, tools only). Live from the
review's sandbox: docs.python.org, pypi.org, github.com and registry.npmjs.org read (the same text as before the
changes), 169.254.169.254 refused, a 404 named.
