#!/usr/bin/env python3
"""Brave Search MCP server (sandbox-ai-mcp): web and news search through the official Brave Search
API.

Tools:
    - web_search: web results (title, URL, description)
    - news_search: news results (title, URL, description, age, source)

Needs the API key in the environment variable BRAVE_API_KEY (a secret; it is never returned or
logged) and network access to api.search.brave.com only (network "allowlist" with
api.search.brave.com:443; HTTPS_PROXY is honoured). Requests are fixed to the API's two
endpoints; arguments are validated; answers are size-bounded.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys

import httpx
from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
log = logging.getLogger("brave-search-mcp")

API = "https://api.search.brave.com/res/v1/"
MAX_ANSWER = 8 << 20
TIMEOUT = 30.0
COUNTRY = re.compile(r"^[A-Za-z]{2}$|^ALL$")
FRESHNESS = ("", "pd", "pw", "pm", "py")

mcp = FastMCP("brave-search-mcp")


class ArgumentError(ValueError):
    """A tool argument that is not accepted, or an answer that cannot be used; the text says why."""


def _query(value) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 400 or any(ord(c) < 32 for c in value):
        raise ArgumentError("query: 1-400 characters of text")
    return value.strip()


def _int(value, name: str, low: int, high: int, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ArgumentError(f"{name}: an integer from {low} to {high}")
    return value


def _key() -> str:
    key = os.environ.get("BRAVE_API_KEY", "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", key):
        raise ArgumentError("no Brave Search API key: set BRAVE_API_KEY for this server")
    return key


async def _get(endpoint: str, params: dict) -> dict:
    headers = {"Accept": "application/json", "X-Subscription-Token": _key(),
               "User-Agent": "sandbox-ai-mcp brave-search"}
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False, trust_env=True, headers=headers) as client:
        async with client.stream("GET", API + endpoint, params=params) as response:
            if response.status_code == 401 or response.status_code == 403:
                raise ArgumentError("Brave Search refused the API key")
            if response.status_code == 429:
                raise ArgumentError("Brave Search rate limit reached: retry later")
            if response.status_code != 200:
                raise ArgumentError(f"Brave Search answered HTTP {response.status_code}")
            body = b""
            async for chunk in response.aiter_bytes():
                body += chunk
                if len(body) > MAX_ANSWER:
                    raise ArgumentError("Brave Search's answer is larger than 8 MiB")
    try:
        data = json.loads(body)
    except ValueError:
        raise ArgumentError("Brave Search did not answer JSON") from None
    if not isinstance(data, dict):
        raise ArgumentError("Brave Search answered something else than an object")
    return data


def _params(query, count, country, freshness, offset) -> dict:
    params = {"q": _query(query), "count": _int(count, "count", 1, 20, 10), "offset": _int(offset, "offset", 0, 9, 0)}
    if country:
        if not isinstance(country, str) or not COUNTRY.match(country):
            raise ArgumentError("country: a two-letter country code or ALL")
        params["country"] = country.upper() if country != "ALL" else "ALL"
    if freshness not in FRESHNESS:
        raise ArgumentError("freshness: pd (day), pw (week), pm (month), py (year) or empty")
    if freshness:
        params["freshness"] = freshness
    return params


def web_results(data: dict) -> list[dict]:
    rows = (data.get("web") or {}).get("results") or []
    return [{"title": str(r.get("title", "")), "url": str(r.get("url", "")), "description": str(r.get("description", ""))}
            for r in rows if isinstance(r, dict) and str(r.get("url", "")).startswith(("http://", "https://"))]


def news_results(data: dict) -> list[dict]:
    rows = data.get("results") or []
    return [{"title": str(r.get("title", "")), "url": str(r.get("url", "")), "description": str(r.get("description", "")),
             "age": str(r.get("age", "")), "source": str((r.get("meta_url") or {}).get("hostname", ""))}
            for r in rows if isinstance(r, dict) and str(r.get("url", "")).startswith(("http://", "https://"))]


@mcp.tool()
async def web_search(query: str, count: int = 10, country: str = "", freshness: str = "", offset: int = 0) -> dict:
    """Search the web with Brave Search. count 1-20, offset 0-9 (pages), country a two-letter
    code (or ALL), freshness pd/pw/pm/py (day, week, month, year) or empty."""
    try:
        params = _params(query, count, country, freshness, offset)
        try:
            data = await _get("web/search", params)
        except httpx.HTTPError as exc:
            raise ArgumentError(f"Brave Search not reachable: {exc}") from None
        results = web_results(data)
        return {"query": params["q"], "results": results, "count": len(results)}
    except ArgumentError as exc:
        return {"error": str(exc)}


@mcp.tool()
async def news_search(query: str, count: int = 10, country: str = "", freshness: str = "", offset: int = 0) -> dict:
    """Search news with Brave Search; the same arguments as web_search."""
    try:
        params = _params(query, count, country, freshness, offset)
        try:
            data = await _get("news/search", params)
        except httpx.HTTPError as exc:
            raise ArgumentError(f"Brave Search not reachable: {exc}") from None
        results = news_results(data)
        return {"query": params["q"], "results": results, "count": len(results)}
    except ArgumentError as exc:
        return {"error": str(exc)}


if __name__ == "__main__":
    mcp.run("stdio")
