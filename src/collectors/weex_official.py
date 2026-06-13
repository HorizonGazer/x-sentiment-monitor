"""
WEEX Official website collector — scrapes announcements, activities, and blog posts.

Uses Playwright with Firefox to fetch WEEX official pages and extract structured data.
Produces RawMention records with platform="weex_official".
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin

from playwright.sync_api import Browser, BrowserContext, Page, ViewportSize
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from .base import RawMention

logger = logging.getLogger(__name__)

# ── Target pages ─────────────────────────────────────────────────────────────

WEEX_BLOG_URL = "https://blog.weex.com"
WEEX_ZENDESK_URL = "https://weexsupport.zendesk.com/hc/zh-cn/sections/18187498498841"  # Announcements section


# ── DOM extraction JS ────────────────────────────────────────────────────────

BLOG_EXTRACT_JS = """() => {
    const items = [];
    // Blog cards / article entries
    document.querySelectorAll('article, .post-card, .blog-post, [class*="article"], [class*="post"]').forEach(node => {
        const a = node.querySelector('a[href]');
        const title = node.querySelector('h1, h2, h3, h4, [class*="title"]');
        const desc = node.querySelector('p, [class*="desc"], [class*="excerpt"], [class*="summary"]');
        const time = node.querySelector('time, [class*="date"], [class*="time"]');
        if (title || a) {
            items.push({
                title: (title?.innerText || a?.innerText || '').trim(),
                url: a?.href || '',
                description: (desc?.innerText || '').trim().slice(0, 500),
                date: time?.getAttribute('datetime') || time?.innerText || '',
            });
        }
    });
    // Fallback: grab all links with titles if no structured cards found
    if (items.length === 0) {
        document.querySelectorAll('a[href]').forEach(a => {
            const text = (a.innerText || '').trim();
            if (text.length > 10 && text.length < 200 && a.href.includes('/blog') || a.href.includes('/article')) {
                items.push({title: text, url: a.href, description: '', date: ''});
            }
        });
    }
    return items;
}"""

ZENDESK_EXTRACT_JS = """() => {
    const items = [];
    document.querySelectorAll('.article-list-item, [class*="article"], li a[href*="/articles/"]').forEach(node => {
        const a = node.tagName === 'A' ? node : node.querySelector('a[href]');
        const title = node.querySelector('[class*="title"]') || a;
        const date = node.querySelector('time, [class*="date"]');
        if (a && title) {
            items.push({
                title: (title.innerText || '').trim(),
                url: a.href || '',
                description: '',
                date: date?.getAttribute('datetime') || date?.innerText || '',
            });
        }
    });
    return items;
}"""


@dataclass
class _PageItem:
    title: str
    url: str
    description: str
    date: str
    source: str  # "blog" | "zendesk"


class WeexOfficialCollector:
    """
    Scrapes WEEX official blog and Zendesk announcements.
    Produces RawMention records with platform="weex_official".
    """

    def __init__(
        self,
        *,
        headless: bool = True,
        viewport_width: int = 1440,
        viewport_height: int = 900,
    ) -> None:
        self._headless = headless
        self._viewport = ViewportSize(width=viewport_width, height=viewport_height)

    def _scrape_page(
        self, browser: Browser, url: str, js: str, source: str, limit: int
    ) -> list[_PageItem]:
        items: list[_PageItem] = []
        page = browser.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)

            raw_items: list[dict[str, str]] = page.evaluate(js)
            seen_titles: set[str] = set()
            for raw in raw_items:
                title = (raw.get("title") or "").strip()
                if not title or title in seen_titles:
                    continue
                seen_titles.add(title)
                items.append(
                    _PageItem(
                        title=title,
                        url=raw.get("url", ""),
                        description=raw.get("description", ""),
                        date=raw.get("date", ""),
                        source=source,
                    )
                )
                if len(items) >= limit:
                    break
        except PlaywrightTimeoutError:
            logger.warning("Timeout scraping %s", url)
        except Exception as e:
            logger.warning("Error scraping %s: %s", url, e)
        finally:
            page.close()
        return items

    def collect(self, limit: int = 30) -> list[RawMention]:
        """Collect WEEX official announcements and blog posts."""
        all_items: list[_PageItem] = []
        now = datetime.now(timezone.utc)

        with sync_playwright() as p:
            browser = p.firefox.launch(headless=self._headless)
            try:
                # Blog
                blog_items = self._scrape_page(
                    browser, WEEX_BLOG_URL, BLOG_EXTRACT_JS, "blog", limit // 2
                )
                all_items.extend(blog_items)
                logger.info("WEEX Blog: scraped %d items", len(blog_items))

                # Zendesk announcements
                zendesk_items = self._scrape_page(
                    browser, WEEX_ZENDESK_URL, ZENDESK_EXTRACT_JS, "zendesk", limit // 2
                )
                all_items.extend(zendesk_items)
                logger.info("WEEX Zendesk: scraped %d items", len(zendesk_items))
            finally:
                browser.close()

        # Convert to RawMention
        mentions: list[RawMention] = []
        for item in all_items:
            content = item.title
            if item.description:
                content = f"{item.title}。{item.description}"

            created = now
            if item.date:
                try:
                    created = datetime.fromisoformat(
                        item.date.replace("Z", "+00:00")
                    )
                except (ValueError, TypeError):
                    pass

            mentions.append(
                RawMention(
                    platform="weex_official",
                    source_id=item.url or item.title,
                    symbol="WEEX",
                    symbol_type="crypto",
                    author=f"WEEX ({item.source})",
                    content=content,
                    created_at=created,
                    collected_at=now,
                    url=item.url,
                    tags=["WEEX", item.source],
                )
            )

        logger.info("WEEX Official: total %d mentions", len(mentions))
        return mentions[:limit]

    def health_check(self) -> dict[str, Any]:
        return {
            "platform": "weex_official",
            "blog_url": WEEX_BLOG_URL,
            "zendesk_url": WEEX_ZENDESK_URL,
        }
