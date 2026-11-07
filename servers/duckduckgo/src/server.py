#!/usr/bin/env python3
"""DuckDuckGo MCP server (sandbox-ai-mcp): web search without an API key, through DuckDuckGo's
HTML endpoint.

Tools:
    - web_search: results (title, URL, snippet) for a query

Needs network access to html.duckduckgo.com only (network "allowlist" with
html.duckduckgo.com:443; HTTPS_PROXY is honoured). Arguments are validated, the request is
fixed to https://html.duckduckgo.com/html/, answers are size-bounded, and result links are
decoded from DuckDuckGo's redirect form (only http and https links are returned).
"""

from __future__ import annotations

import html.parser
import logging
import re
import sys
import urllib.parse

import httpx
from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
log = logging.getLogger("duckduckgo-mcp")

ENDPOINT = "https://html.duckduckgo.com/html/"
MAX_ANSWER = 4 << 20
TIMEOUT = 30.0
REGIONS = re.compile(r"^(?:wt-wt|[a-z]{2}-[a-z]{2})$")

mcp = FastMCP("duckduckgo-mcp")


class ArgumentError(ValueError):
    """A tool argument that is not accepted; the text says why."""


class ResultParser(html.parser.HTMLParser):
    """Results of DuckDuckGo's HTML page: links with class result__a, snippets result__snippet."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results, self._field, self._ad = [], None, False

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = (attributes.get("class") or "").split()
        if tag == "div" and "result" in classes:
            self._ad = "result--ad" in classes  # sponsored results are not search results
        if tag == "a" and "result__a" in classes:
            url = "" if self._ad else real_url(attributes.get("href") or "")
            self.results.append({"title": "", "url": url, "snippet": ""})
            self._field = "title"
        elif tag in ("a", "div", "td") and "result__snippet" in classes and self.results:
            self._field = "snippet"

    def handle_endtag(self, tag):
        if tag in ("a", "div", "td"):
            self._field = None

    def handle_data(self, data):
        if self._field and self.results:
            self.results[-1][self._field] += data


def real_url(href: str) -> str:
    """The target of a result link: DuckDuckGo wraps it as //duckduckgo.com/l/?uddg=<url>."""
    parsed = urllib.parse.urlsplit(href if "://" in href else "https:" + href if href.startswith("//") else href)
    if parsed.path == "/l/" and "uddg" in urllib.parse.parse_qs(parsed.query):
        href = urllib.parse.parse_qs(parsed.query)["uddg"][0]
    target = urllib.parse.urlsplit(href)
    if target.scheme not in ("http", "https") or (target.hostname or "").endswith("duckduckgo.com"):
        return ""  # scripts, and DuckDuckGo's own pages (ad redirects)
    return href


def parse_results(page: str, limit: int) -> list[dict]:
    parser = ResultParser()
    parser.feed(page)
    found = []
    for result in parser.results:
        title = " ".join(result["title"].split())
        if not result["url"] or not title:
            continue  # ads and malformed entries
        found.append({"title": title, "url": result["url"], "snippet": " ".join(result["snippet"].split())})
        if len(found) >= limit:
            break
    return found


def _query(value) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 500 or any(ord(c) < 32 for c in value):
        raise ArgumentError("query: 1-500 characters of text")
    return value.strip()


def _int(value, name: str, low: int, high: int, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ArgumentError(f"{name}: an integer from {low} to {high}")
    return value


async def _post(form: dict) -> str:
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False, trust_env=True,
                                 headers={"User-Agent": "Mozilla/5.0 (sandbox-ai-mcp duckduckgo)"}) as client:
        async with client.stream("POST", ENDPOINT, data=form) as response:
            if response.status_code != 200:
                raise ArgumentError(f"DuckDuckGo answered HTTP {response.status_code} (rate limited? retry later)")
            body = b""
            async for chunk in response.aiter_bytes():
                body += chunk
                if len(body) > MAX_ANSWER:
                    raise ArgumentError("DuckDuckGo's answer is larger than 4 MiB")
            return body.decode("utf-8", "replace")


@mcp.tool()
async def web_search(query: str, max_results: int = 10, region: str = "wt-wt") -> dict:
    """Search the web with DuckDuckGo. Returns up to max_results (1-30) results with title,
    URL and snippet. region: wt-wt (no region) or a code such as de-de, us-en."""
    try:
        text = _query(query)
        limit = _int(max_results, "max_results", 1, 30, 10)
        if not isinstance(region, str) or not REGIONS.match(region):
            raise ArgumentError("region: wt-wt or a code such as de-de")
        try:
            page = await _post({"q": text, "kl": region})
        except httpx.HTTPError as exc:
            raise ArgumentError(f"DuckDuckGo not reachable: {exc}") from None
        results = parse_results(page, limit)
        return {"query": text, "results": results, "count": len(results)}
    except ArgumentError as exc:
        return {"error": str(exc)}


if __name__ == "__main__":
    mcp.run("stdio")
