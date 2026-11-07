#!/usr/bin/env python3
"""SearXNG MCP server (sandbox-ai-mcp): web search through a SearXNG instance of yours (a metasearch engine that
asks many search engines at once, without tracking), with its JSON API.

Tools:
    - web_search: results (title, URL, snippet, the engines that found it) for a query, optionally in a
      category, a language and a time range, page by page

SEARXNG_URL names the instance (https://search.example.org, or http://IP:PORT in a private network); only its
/search is requested, with format=json (the instance must allow that format: search.formats in its
settings.yml). Network: that host and port only. Arguments are validated, no redirects are followed, answers
are size-bounded, and only http and https result links are returned.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import re
import sys
import urllib.parse

import httpx
from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
log = logging.getLogger("searxng-mcp")

MAX_ANSWER = 4 << 20
TIMEOUT = 30.0
CATEGORIES = ("general", "news", "science", "it", "images", "videos", "music", "files", "map", "social media")
TIME_RANGES = ("", "day", "week", "month", "year")
LANGUAGE = re.compile(r"^(?:all|auto|[a-z]{2}(?:-[A-Z]{2})?)$")

mcp = FastMCP("searxng-mcp")


class ArgumentError(ValueError):
    """A tool argument or setting that is not accepted; the text says why."""


def instance(value=None) -> str:
    """SEARXNG_URL checked: http(s), a host, no credentials, query or fragment; plain http only to a private,
    loopback or CGNAT address (the instance of your LAN); the URL without a trailing slash."""
    url = (os.environ.get("SEARXNG_URL", "") if value is None else value).strip()
    if not url:
        raise ArgumentError("SEARXNG_URL is not set: the address of your SearXNG instance, e.g. "
                            "https://search.example.org or http://192.168.1.20:8888")
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password \
            or parsed.query or parsed.fragment or any(ord(c) < 33 for c in url) or len(url) > 300:
        raise ArgumentError("SEARXNG_URL: http(s)://HOST[:PORT][/PATH], without credentials, query or fragment")
    if parsed.scheme == "http":
        try:
            address = ipaddress.ip_address(parsed.hostname)
        except ValueError:
            address = None
        if address is None or not (address.is_private or address.is_loopback
                                   or address in ipaddress.ip_network("100.64.0.0/10")):
            raise ArgumentError("SEARXNG_URL: plain http only to a private address; use https for a name")
    return url.rstrip("/")


def results_of(data, limit: int) -> list[dict]:
    """The results of SearXNG's JSON answer: title, URL (http or https only), snippet and engines."""
    found = []
    for entry in (data.get("results") if isinstance(data, dict) else None) or []:
        if not isinstance(entry, dict):
            continue
        url, title = entry.get("url"), entry.get("title")
        if not isinstance(url, str) or urllib.parse.urlsplit(url).scheme not in ("http", "https"):
            continue
        if not isinstance(title, str) or not title.strip():
            continue
        content = entry.get("content") if isinstance(entry.get("content"), str) else ""
        engines = [e for e in entry.get("engines") or [] if isinstance(e, str)][:10]
        found.append({"title": " ".join(title.split())[:300], "url": url[:2000],
                      "snippet": " ".join(content.split())[:1000], "engines": engines})
        if len(found) >= limit:
            break
    return found


def extras_of(data) -> dict:
    """Suggestions and answers SearXNG gives beside the results (text only, bounded)."""
    if not isinstance(data, dict):
        return {}
    texts = lambda key: [" ".join(v.split())[:300] for v in data.get(key) or [] if isinstance(v, str)][:10]  # noqa: E731
    answers = [a for a in data.get("answers") or [] if isinstance(a, str)] + \
        [a.get("answer") for a in data.get("answers") or [] if isinstance(a, dict) and isinstance(a.get("answer"), str)]
    return {"suggestions": texts("suggestions"), "answers": [" ".join(a.split())[:500] for a in answers][:5]}


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


async def _get(url: str, params: dict) -> dict:
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False, trust_env=True,
                                 headers={"User-Agent": "sandbox-ai-mcp searxng", "Accept": "application/json"}) \
            as client:
        async with client.stream("GET", url + "/search", params=params) as response:
            if response.status_code == 403:
                raise ArgumentError("SearXNG refused the JSON format (403): add json to search.formats in the "
                                    "instance's settings.yml")
            if response.status_code == 429:
                raise ArgumentError("SearXNG's limiter refused the query (429): allow this client in its limiter")
            if response.status_code != 200:
                raise ArgumentError(f"SearXNG answered HTTP {response.status_code}")
            body = b""
            async for chunk in response.aiter_bytes():
                body += chunk
                if len(body) > MAX_ANSWER:
                    raise ArgumentError("SearXNG's answer is larger than 4 MiB")
    try:
        return json.loads(body)
    except ValueError:
        raise ArgumentError("SearXNG did not answer with JSON (is format=json allowed?)") from None


@mcp.tool()
async def web_search(query: str, max_results: int = 10, category: str = "general", language: str = "auto",
                     time_range: str = "", page: int = 1) -> dict:
    """Search the web through SearXNG (many search engines at once). Returns up to max_results (1-50) results with
    title, URL, snippet and the engines that found each, plus suggestions. category: general, news, science, it,
    images, videos, music, files, map, social media; language: auto, all, or a code such as de or en-US;
    time_range: "", day, week, month or year; page: 1-10."""
    try:
        url = instance()
        text = _query(query)
        limit = _int(max_results, "max_results", 1, 50, 10)
        number = _int(page, "page", 1, 10, 1)
        if category not in CATEGORIES:
            raise ArgumentError("category: one of " + ", ".join(CATEGORIES))
        if not isinstance(language, str) or not LANGUAGE.match(language):
            raise ArgumentError("language: auto, all, or a code such as de or en-US")
        if time_range not in TIME_RANGES:
            raise ArgumentError("time_range: '', day, week, month or year")
        params = {"q": text, "format": "json", "categories": category, "language": language, "pageno": number,
                  "safesearch": 1}
        if time_range:
            params["time_range"] = time_range
        try:
            data = await _get(url, params)
        except httpx.HTTPError as exc:
            raise ArgumentError(f"SearXNG not reachable at {url}: {exc}") from None
        results = results_of(data, limit)
        return {"query": text, "results": results, "count": len(results), **extras_of(data)}
    except ArgumentError as exc:
        return {"error": str(exc)}


if __name__ == "__main__":
    mcp.run("stdio")
