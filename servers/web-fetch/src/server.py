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
answers differently a moment later (DNS rebinding) is not ruled out.
"""

from __future__ import annotations

import html.parser
import ipaddress
import logging
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
    """URL if it is http(s) to a public address; ArgumentError otherwise."""
    if not isinstance(url, str) or len(url) > 2048 or any(ord(c) < 33 for c in url):
        raise ArgumentError("url: an http or https URL")
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        raise ArgumentError("url: an http or https URL without user name or password")
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
        infos = socket.getaddrinfo(parts.hostname, port, type=socket.SOCK_STREAM)
    except (OSError, ValueError) as exc:
        raise ArgumentError(f"cannot resolve {parts.hostname}: {exc}") from None
    for info in infos:
        address = ipaddress.ip_address(info[4][0].split("%")[0])
        if not public(address):
            raise ArgumentError(f"{parts.hostname} resolves to {address}, which is not a public address")
    return url


NAT64 = (ipaddress.ip_network("64:ff9b::/96"), ipaddress.ip_network("64:ff9b:1::/48"))


def public(address) -> bool:
    """A global unicast address; for IPv6 that carries an IPv4 one (NAT64 64:ff9b::/96 and the local-use
    64:ff9b:1::/48, IPv4-mapped, 6to4 2002::/16), the IPv4 address it reaches must be global too."""
    if not address.is_global or address.is_multicast:
        return False
    if address.version == 6:
        embedded = None
        if any(address in net for net in NAT64):
            embedded = ipaddress.IPv4Address(int(address) & 0xFFFFFFFF)
        elif address.ipv4_mapped is not None:
            embedded = address.ipv4_mapped
        elif address.sixtofour is not None:
            embedded = address.sixtofour
        if embedded is not None and (not embedded.is_global or embedded.is_multicast):
            return False
    return True


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
