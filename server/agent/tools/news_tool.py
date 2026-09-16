"""search_news：搜索 API（Tavily）优先，RSS 兜底，去重 + 时间过滤（§14）。"""
from __future__ import annotations

import functools
import html
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, urlunparse

import feedparser
import httpx

logger = logging.getLogger(__name__)

TAVILY_URL = "https://api.tavily.com/search"
MAX_SNIPPET_CHARS = 300
FEED_TIMEOUT_SECONDS = 10
FEED_CACHE_TTL_SECONDS = 120       # 成功抓取缓存时长
FEED_FAIL_CACHE_TTL_SECONDS = 60   # 失败负缓存时长（避免反复等待同一个超时源）

# feed_url -> (过期时刻 monotonic, 响应体 | None)
_FEED_CACHE: dict[str, tuple[float, bytes | None]] = {}
_FEED_CACHE_LOCK = threading.Lock()


def _normalize_url(url: str) -> str:
    parts = urlparse(url or "")
    return urlunparse((parts.scheme, parts.netloc, parts.path, "", "", ""))


def _proxy(settings) -> str | None:
    """可选 HTTP 代理（HTTP_PROXY_URL）；为空时交给 httpx 读取系统代理。"""
    return (settings.http_proxy or "").strip() or None


def _strip_html(text: str) -> str:
    plain = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(plain)).strip()


def _tavily_search(query: str, max_results: int, days: int, settings) -> list[dict]:
    response = httpx.post(
        TAVILY_URL,
        json={
            "api_key": settings.search_api_key,
            "query": query,
            "max_results": max_results,
            "topic": "news",
            "days": days,
            "search_depth": "basic",
        },
        timeout=FEED_TIMEOUT_SECONDS,
        proxy=_proxy(settings),
    )
    response.raise_for_status()
    items: list[dict] = []
    for result in response.json().get("results", []):
        url = result.get("url", "")
        title = (result.get("title") or "").strip()
        if not title:
            continue
        items.append({
            "title": title,
            "url": url,
            "source": urlparse(url).netloc,
            "published_at": result.get("published_date") or result.get("published_at"),
            "snippet": _strip_html(result.get("content", ""))[:MAX_SNIPPET_CHARS],
        })
    return items


def _fetch_feed(feed_url: str, proxy: str | None = None) -> bytes | None:
    """抓取单个 RSS（成功/失败均带 TTL 缓存），失败返回 None。"""
    now = time.monotonic()
    with _FEED_CACHE_LOCK:
        cached = _FEED_CACHE.get(feed_url)
        if cached and cached[0] > now:
            return cached[1]

    content: bytes | None = None
    try:
        response = httpx.get(
            feed_url,
            timeout=FEED_TIMEOUT_SECONDS,
            follow_redirects=True,
            headers={"User-Agent": "ai-news-agent/1.0"},
            proxy=proxy,
        )
        response.raise_for_status()
        content = response.content
    except Exception as exc:  # noqa: BLE001  单源失败不影响其它源
        logger.warning("RSS 抓取失败: %s (%s)", feed_url, exc)

    ttl = FEED_CACHE_TTL_SECONDS if content is not None else FEED_FAIL_CACHE_TTL_SECONDS
    with _FEED_CACHE_LOCK:
        _FEED_CACHE[feed_url] = (now + ttl, content)
    return content


def _rss_search(query: str, max_results: int, days: int, settings) -> list[dict]:
    tokens = [t.lower() for t in re.split(r"[\s,，]+", query) if t]
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    feeds = list(settings.rss_feeds)
    if not feeds:
        return []

    # 并发抓取：单次搜索总耗时 ≈ 最慢的单源，而不是各源之和；命中缓存则不再打网络
    fetch = functools.partial(_fetch_feed, proxy=_proxy(settings))
    with ThreadPoolExecutor(max_workers=min(8, len(feeds))) as pool:
        fetched = list(pool.map(fetch, feeds))

    items: list[dict] = []
    for feed_url, content in zip(feeds, fetched):
        if content is None:
            continue
        parsed = feedparser.parse(content)

        for entry in parsed.entries:
            title = (entry.get("title") or "").strip()
            if not title:
                continue
            summary = _strip_html(entry.get("summary", ""))
            if tokens and not any(tok in f"{title} {summary}".lower() for tok in tokens):
                continue
            if getattr(entry, "published_parsed", None):
                published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                if published < cutoff:
                    continue
            url = entry.get("link", "")
            item = {
                "title": title,
                "url": url,
                "source": parsed.feed.get("title", feed_url),
                "published_at": entry.get("published") or entry.get("updated"),
                "snippet": summary[:MAX_SNIPPET_CHARS],
            }
            # RSS guid 用于跨源去重：仅在有效且与 url 不同时携带，避免冗余字段增大 token
            guid = str(entry.get("id") or "").strip()
            if guid and guid != url:
                item["guid"] = guid
            items.append(item)
    return items


def _dedupe(items: list[dict]) -> list[dict]:
    """去重：guid > url > 标题，三项各自非空才参与判重。"""
    seen_guids: set[str] = set()
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    unique: list[dict] = []
    for item in items:
        guid_key = (item.get("guid") or "").strip()
        url_key = _normalize_url(item.get("url", ""))
        title_key = (item.get("title") or "").strip().lower()
        if (
            (guid_key and guid_key in seen_guids)
            or (url_key and url_key in seen_urls)
            or (title_key and title_key in seen_titles)
        ):
            continue
        if guid_key:
            seen_guids.add(guid_key)
        if url_key:
            seen_urls.add(url_key)
        if title_key:
            seen_titles.add(title_key)
        unique.append(item)
    return unique


def search_news(args: dict, ctx) -> dict:
    query = args["query"]
    max_results = int(args.get("max_results", 8))
    days = int(args.get("days", 1))
    settings = ctx.settings

    provider = "none"
    items: list[dict] = []

    if settings.search_api_key and settings.search_provider == "tavily":
        try:
            items = _tavily_search(query, max_results, days, settings)
            provider = "tavily"
        except Exception as exc:  # noqa: BLE001  降级 RSS
            logger.warning("Tavily 搜索失败，降级 RSS: %s", exc)
            items = []

    if not items:
        items = _rss_search(query, max_results, days, settings)
        provider = "rss" if items else "none"

    items = _dedupe(items)[:max_results]
    return {"items": items, "provider": provider, "count": len(items)}
