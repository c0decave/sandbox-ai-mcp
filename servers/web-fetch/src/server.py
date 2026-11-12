#!/usr/bin/env python3
"""Web fetch MCP server (sandbox-ai-mcp): one web page as readable text, for agents whose own
sandbox has no network.

Tools:
    - fetch_page: an http(s) URL as text (HTML reduced to its readable text and links), or the
      raw text of a text document

Needs network "full". Only public addresses are fetched: a name that resolves to a loopback,
private, link-local or otherwise non-public address is refused, also after a redirect (so the
server cannot be used to reach the host or its local network). At most 5 redirects, 5 MiB per
answer, text and HTML only. The check resolves the name before the request; a resolver that
answers differently a moment later (DNS rebinding) is not ruled out. Behind sandbox-ai's Tor profile
(SANDBOX_AI_TOR=1 and SANDBOX_AI_TOR_VIRTUAL_NETWORK) the addresses of Tor's range for onion services are
fetched too, so .onion URLs work; without a Tor profile a .onion name is refused before it is looked up.
"""

from __future__ import annotations

import html.parser
import ipaddress
import logging
import os
import socket
import sys
import urllib.parse

import httpx
from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
log = logging.getLogger("web-fetch-mcp")

MAX_ANSWER = 5 << 20
TIMEOUT = 30.0
MAX_REDIRECTS = 5
TEXT_TYPES = ("text/", "application/json", "application/xml", "application/xhtml+xml", "application/javascript")

mcp = FastMCP("web-fetch-mcp")


class ArgumentError(ValueError):
    """A tool argument that is not accepted, or an answer that cannot be used; the text says why."""


class TextParser(html.parser.HTMLParser):
    """Readable text and links of an HTML page: script, style and similar elements are dropped."""
    SKIP = {"script", "style", "noscript", "template", "svg", "head"}
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "pre",
             "blockquote", "header", "footer", "table", "ul", "ol"}

    def __init__(self, base):
        super().__init__(convert_charrefs=True)
        self.base, self.parts, self.links, self.title, self._skip, self._in_title = base, [], [], "", 0, False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag in self.BLOCK:
            self.parts.append("\n")
        if tag == "a":
            href = dict(attrs).get("href") or ""
            target = urllib.parse.urljoin(self.base, href)
            if urllib.parse.urlsplit(target).scheme in ("http", "https") and len(self.links) < 200:
                self.links.append(target)

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)

    def text(self):
        lines = (" ".join(line.split()) for line in "".join(self.parts).splitlines())
        out, blank = [], False
        for line in lines:
            if line:
                out.append(line)
                blank = False
            elif not blank and out:
                out.append("")
                blank = True
        return "\n".join(out).strip()


def page_text(body: str, base: str) -> dict:
    parser = TextParser(base)
    parser.feed(body)
    return {"title": " ".join(parser.title.split()), "text": parser.text(), "links": list(dict.fromkeys(parser.links))}


def check_url(url) -> str:
    """URL if it is http(s) to a public address (behind Tor also an onion service's); ArgumentError otherwise."""
    if not isinstance(url, str) or len(url) > 2048 or any(ord(c) < 33 for c in url):
        raise ArgumentError("url: an http or https URL")
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        raise ArgumentError("url: an http or https URL without user name or password")
    check_onion_name(parts.hostname)
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
        infos = socket.getaddrinfo(parts.hostname, port, type=socket.SOCK_STREAM)
    except (OSError, ValueError) as exc:
        raise ArgumentError(f"cannot resolve {parts.hostname}: {exc}") from None
    for info in infos:
        address = ipaddress.ip_address(info[4][0].split("%")[0])
        if not (public(address) or in_tor_network(address)):
            raise ArgumentError(refusal(parts.hostname, address, None))
    return url


NAT64 = (ipaddress.ip_network("64:ff9b::/96"), ipaddress.ip_network("64:ff9b:1::/48"))


def embedded_ipv4(address):
    """The IPv4 address an IPv6 address reaches (NAT64 64:ff9b::/96 and the local-use 64:ff9b:1::/48,
    IPv4-mapped, 6to4 2002::/16), else None."""
    if address.version != 6:
        return None
    if any(address in net for net in NAT64):
        return ipaddress.IPv4Address(int(address) & 0xFFFFFFFF)
    return address.ipv4_mapped or address.sixtofour


def public(address) -> bool:
    """A global unicast address; for IPv6 that carries an IPv4 one (embedded_ipv4), the IPv4 address it
    reaches must be global too."""
    if not address.is_global or address.is_multicast:
        return False
    embedded = embedded_ipv4(address)
    if embedded is not None and (not embedded.is_global or embedded.is_multicast):
        return False
    return True


# -- onion services behind sandbox-ai's Tor profile -------------------------------------------------------------------
# The same block is in web-fetch, gowitness and whatweb (each image has its own copy: keep them alike). Behind a Tor
# profile sandbox-ai sets SANDBOX_AI_TOR=1 and SANDBOX_AI_TOR_VIRTUAL_NETWORK, the IPv4 range tor maps .onion names
# into (AutomapHostsOnResolve; tor's default 10.192.0.0/10). Every connection of the container goes through Tor then,
# and an address of that range is an onion service: it is taken, nothing else of 10.0.0.0/8 or the other local,
# loopback, link-local or reserved ranges is. The error texts say what an address is and what would apply.

TOR_DEFAULT_NETWORK = ipaddress.ip_network("10.192.0.0/10")
TOR_PARENT = ipaddress.ip_network("10.0.0.0/8")
LOCAL_NETWORKS = tuple(ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
                                                         "100.64.0.0/10", "fc00::/7"))
METADATA = (ipaddress.ip_address("169.254.169.254"), ipaddress.ip_address("fd00:ec2::254"))
NEEDS_TOR = (".onion needs a Tor profile (start the server behind one: --vpn TOR_PROFILE); "
             "this server does not run behind Tor")
NOT_TOLD = ("this server was not told Tor's address range (SANDBOX_AI_TOR_VIRTUAL_NETWORK missing or invalid: "
            "an older sandbox-ai?)")


def tor_network():
    """(behind Tor, Tor's virtual IPv4 range or None): (False, None) without SANDBOX_AI_TOR=1; (True, None) when
    SANDBOX_AI_TOR_VIRTUAL_NETWORK is missing, not an IPv4 network or not inside 10.0.0.0/8."""
    if os.environ.get("SANDBOX_AI_TOR") != "1":
        return False, None
    try:
        network = ipaddress.IPv4Network(os.environ.get("SANDBOX_AI_TOR_VIRTUAL_NETWORK", "").strip(), strict=True)
    except ValueError:
        return True, None
    return True, (network if network.subnet_of(TOR_PARENT) else None)


def onion(host: str) -> bool:
    return host.rstrip(".").lower().rpartition(".")[2] == "onion"


def check_onion_name(host: str) -> None:
    """Before any lookup: a .onion name only behind Tor (so it never goes to a resolver outside Tor either)."""
    if onion(host) and not tor_network()[0]:
        raise ArgumentError(f"refused: {host}: {NEEDS_TOR}")


def in_tor_network(address) -> bool:
    """An IPv4 address of the range Tor announced (behind Tor only)."""
    network = tor_network()[1]
    return network is not None and address.version == 4 and address in network


def address_kind(address) -> str:
    if address in METADATA:
        return "the cloud metadata address (link-local)"
    if address.is_loopback:
        return "a loopback address (the server's own container)"
    if address.is_unspecified:
        return "the unspecified address"
    if address.is_link_local:
        return "a link-local address"
    if address.is_multicast:
        return "a multicast address"
    if any(address in net for net in LOCAL_NETWORKS):
        return "a local-network address"
    return "a reserved or documentation address"


def refusal(host: str, address, private_targets) -> str:
    """Why *host*, resolving to *address* (which the server's own check refused), is refused, and what would apply.
    *private_targets*: whether ALLOW_PRIVATE_TARGETS=1 is set; None for a server without that setting."""
    behind, network = tor_network()
    carried = embedded_ipv4(address)
    judged = carried if carried is not None and (not carried.is_global or carried.is_multicast) else address
    shown = str(address) if judged is address else f"{address} (which reaches {judged})"
    try:
        literal = ipaddress.ip_address(host) == address
    except ValueError:
        literal = False
    start = f"refused: {shown} is" if literal else f"refused: {host} resolves to {shown},"
    if behind and network is None and judged in TOR_DEFAULT_NETWORK:
        return f"{start} Tor's address for an onion service; {NOT_TOLD}"
    kind = address_kind(judged)
    text = f"{start} {kind}, not a public address"
    if kind == "a local-network address":
        if private_targets is None:
            text += "; this server never connects to local-network addresses"
        elif not private_targets:
            text += " (ALLOW_PRIVATE_TARGETS=1 allows your own LAN)"
    else:
        text += "; this server never connects to it" + ("" if private_targets is None
                                                         else ", not even with ALLOW_PRIVATE_TARGETS=1")
    if behind and onion(host):
        text += (f"; behind Tor an onion name must resolve into Tor's range {network}" if network is not None
                 else f"; {NOT_TOLD}")
    elif behind and network is not None and judged in TOR_PARENT:
        text += f"; behind Tor only Tor's range for onion services ({network}) is taken of 10.0.0.0/8"
    elif not behind and (onion(host) or judged in TOR_DEFAULT_NETWORK):
        text += f"; if it is Tor's address for an onion service: {NEEDS_TOR}"
    return text


def _int(value, name: str, low: int, high: int, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ArgumentError(f"{name}: an integer from {low} to {high}")
    return value


async def fetch(url: str) -> tuple[str, str, bytes]:
    """(final URL, content type, body) after at most MAX_REDIRECTS checked redirects."""
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False, trust_env=True,
                                 headers={"User-Agent": "Mozilla/5.0 (sandbox-ai-mcp web-fetch)"}) as client:
        for _ in range(MAX_REDIRECTS + 1):
            check_url(url)
            async with client.stream("GET", url) as response:
                if response.status_code in (301, 302, 303, 307, 308) and response.headers.get("location"):
                    url = urllib.parse.urljoin(url, response.headers["location"])
                    continue
                if response.status_code >= 400:
                    raise ArgumentError(f"{url} answered HTTP {response.status_code}")
                kind = response.headers.get("content-type", "").split(";")[0].strip().lower()
                if kind and not kind.startswith(TEXT_TYPES):
                    raise ArgumentError(f"{url} is {kind}, not text or HTML")
                body = b""
                async for chunk in response.aiter_bytes():
                    body += chunk
                    if len(body) > MAX_ANSWER:
                        raise ArgumentError(f"{url} is larger than 5 MiB")
                return url, kind, body
    raise ArgumentError(f"more than {MAX_REDIRECTS} redirects")


@mcp.tool()
async def fetch_page(url: str, max_characters: int = 20000, start: int = 0, links: bool = False) -> dict:
    """Fetch an http(s) URL and return its readable text (HTML: title, text, and with links=True
    the page's links). Long texts are returned in parts: max_characters 100-100000 from start."""
    try:
        check_url(url)
        limit = _int(max_characters, "max_characters", 100, 100000, 20000)
        offset = _int(start, "start", 0, 50_000_000, 0)
        try:
            final, kind, body = await fetch(url)
        except httpx.HTTPError as exc:
            raise ArgumentError(f"{url} not reachable: {exc}") from None
        text = body.decode("utf-8", "replace")
        if kind in ("text/html", "application/xhtml+xml") or (not kind and "<html" in text[:2000].lower()):
            page = page_text(text, final)
        else:
            page = {"title": "", "text": text, "links": []}
        part = page["text"][offset:offset + limit]
        result = {"url": final, "content_type": kind, "title": page["title"], "text": part,
                  "start": offset, "total_characters": len(page["text"]),
                  "more": offset + limit < len(page["text"])}
        if links is True:
            result["links"] = page["links"]
        return result
    except ArgumentError as exc:
        return {"error": str(exc)}


if __name__ == "__main__":
    mcp.run("stdio")
