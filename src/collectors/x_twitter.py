"""
X (Twitter) collector — migrated from scripts/x_sentiment.py.

Uses sync_playwright with Firefox cookie auth to scrape tweets via DOM extraction.
Implements the Collector protocol producing RawMention records.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from playwright.sync_api import Browser, BrowserContext, Page, ViewportSize
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from .base import RawMention
from .symbol_extractor import extract_symbols

logger = logging.getLogger(__name__)

# ── Quality thresholds (migrated from legacy) ───────────────────────────────
MIN_CONTENT_LEN = 50

SPAM_PATTERNS: list[str] = [
    r"^(up|gm|gn|lfg|nice|wow|hi|hello|wagmi|ngmi)\b",
    r"^\s*UID\s*[:：]?\s*\d+",
    r"^@\w+\s*@\w+\s*@\w+",
    r"^(RT|retweet)\s",
    r"^#\w+\s+(is|are)\s+(the\s+)?(best|greatest|top|number)",
    r"doing things RIGHT",
    r"^(Let us help you grow|Say Hi|Follow|Check out|Don't miss)",
    r"^Accounts under \d",
    r"^(FREE|free)\s+.*(SIGNAL|signal)",
    r"(join|enter).*(giveaway|raffle|lottery)",
    r"(DM|dm)\s*(me|for|to)\s*(collab|promo|marketing|join|access)",
    r"(100|1000)x\s*(gem|potential|guaranteed)",
    r"(next|new)\s*(100|1000)x",
    r"(guaranteed|easy)\s*(profit|money|income|return)",
    r"(send|drop)\s*(your|ur)\s*(wallet|address|ETH|SOL)",
    r"(whitelist|WL|wl)\s*(spot|open|live|now)",
    r"^(like|retweet|rt|follow|tag)\s.*(to\s*win|for\s*a\s*chance)",
    r"(telegram|t\.me)/\S+",
    r"not\s*financial\s*advice.*dyor",
    r"(🚀\s*){3,}",
    r"(say\s*yes|boost\s*(you|me|us)|let'?s\s*boost)",
    r"(under|over)\s*\d+[KkMm]?\s*impression",
    r"(private|alpha|vip)\s*(TG|telegram|group|channel)",
    r"DM\s*(TO|ME|FOR)\s*(JOIN|ACCESS|GET)",
    r"\d{3,}(\.\d+)?x\s*(return|gain|profit)",
    r"(i\s*make\s*it\s*look\s*easy|missing\s*out\s*on\s*massive)",
    r"CA\s*:\s*\w{30,}",
    r"BUY\.?\s+(?:ALTCOINS|CRYPTO|NOW)\.?\s+(?:NOW|ALTCOINS)",
    r"WE\s+ARE\s+ABOUT\s+TO\s+MAKE\s+(?:STUPID|INSANE|CRAZY)\s+AMOUNTS",
    r"(?:DM\s+(?:me|now)|dropped\s+early\s+on\s+my\s+TG).*(?:miss|late|follow)",
    r"fill\s+in\s+the\s+blank",
    r"(?:drop|comment|reply)\s+(?:a|your|the)\s*(?:🔥|💯|emoji|word|answer)",
    r"(?:if\s+you\s+agree|who\s+else|say\s+it\s+louder|repost\s+if)",
    r"(?:tag\s+someone|share\s+this|quote\s+this)\s+(?:who|if|and)",
    r"^(?:patience|hodl|diamond\s*hands?|stay\s*strong|trust\s*the\s*process|"
    r"we'?re?\s*(?:still\s*)?early)\b.*[.!]?\s*$",
    r"^.{0,15}(?:is\s+key|is\s+everything|will\s+prevail)\b",
    r"(?:#\w+\s*){7,}",
    r"(?:X\s+saw\s+it\s+late|don'?t\s+blame\s+me).*(?:TG|telegram|DM|follow)",
    r"(?:we\s+made|I\s+made)\s+\d+x\s+profit",
    r"took\s+@?\w+'?s?\s+advice",
    r"(?:worth|someone)\s+(?:keeping\s+an?\s+eye|following|watching)",
    r"(?:range\s+day|meetup|launch\s+party|happy\s+hour).*(?:DM|details|RSVP)",
]
_SPAM_RE = [re.compile(p, re.I) for p in SPAM_PATTERNS]

# ── Batch DOM extraction JS (migrated from legacy) ─────────────────────────
BATCH_ARTICLES_JS = """() => {
    const articles = document.querySelectorAll('article');
    return Array.from(articles).map(node => {
        const txt = (sel) => node.querySelector(sel)?.innerText?.trim() || '';
        const attr = (sel, name) => node.querySelector(sel)?.getAttribute(name) || '';
        const nameWrap = node.querySelector('[data-testid="User-Name"]');
        const links = nameWrap ? Array.from(nameWrap.querySelectorAll('a[href^="/"]')) : [];
        let author = '';
        for (const a of links) {
            const t = (a.innerText || '').trim();
            if (t.startsWith('@')) { author = t.slice(1); break; }
        }
        return {
            author,
            content: txt('[data-testid="tweetText"]'),
            created_at: attr('time', 'datetime'),
            reply_aria: node.querySelector('[data-testid="reply"]')?.getAttribute('aria-label') || '',
            repost_aria: node.querySelector('[data-testid="retweet"]')?.getAttribute('aria-label') || '',
            like_aria: node.querySelector('[data-testid="like"]')?.getAttribute('aria-label') || '',
            url: (Array.from(node.querySelectorAll('a[href*="/status/"]')).map(a => a.href).find(Boolean)) || '',
        };
    });
}"""


@dataclass
class _TweetRaw:
    tweet_id: str
    author: str
    content: str
    likes: int
    reposts: int
    replies: int
    created_at: str
    tags: list[str]
    url: str


# ── Search query templates ──────────────────────────────────────────────────

CRYPTO_QUERIES: list[str] = [
    "crypto min_faves:200 min_retweets:20",
    "bitcoin OR btc min_faves:300",
    "ethereum OR eth min_faves:200",
    "solana OR sol min_faves:150",
    "加密货币 OR 比特币 min_faves:50",
    "defi min_faves:100",
    "airdrop min_faves:150",
]

STOCK_QUERIES: list[str] = [
    "$MSTR OR microstrategy min_faves:100",
    "$COIN OR coinbase min_faves:100",
    "$RIOT OR $MARA OR $CLSK min_faves:50",
    "bitcoin mining stocks min_faves:50",
    "crypto stocks min_faves:100",
]


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\u200b", " ")).strip()


def _extract_tags(text: str) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for tag in re.findall(r"#([\w\u4e00-\u9fff-]+)", text or ""):
        if tag not in seen:
            seen.add(tag)
            result.append(tag)
    return result


def _safe_int(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    text = str(value).replace(",", "").strip()
    if not text:
        return 0
    m = re.search(r"(\d+(?:\.\d+)?)\s*([KMB]?)", text, re.I)
    if not m:
        return 0
    number = float(m.group(1))
    suffix = m.group(2).upper()
    return int(number * {"": 1, "K": 1000, "M": 1_000_000, "B": 1_000_000_000}[suffix])


def _parse_stat(label: str, action_word: str) -> int:
    if not label:
        return 0
    label = label.replace("Reply", "Replies").replace("Like", "Likes").replace("Repost", "reposts")
    m = re.search(rf"([\d.,KMB]+)\s+{re.escape(action_word)}", label, re.I)
    return _safe_int(m.group(1)) if m else 0


def _content_fingerprint(text: str) -> str:
    t = re.sub(r"https?://\S+|[#@]\w+|\$\w+", "", text.lower())
    t = re.sub(r"[^\w\u4e00-\u9fff]", "", t)
    return t[:80]


def _is_spam(text: str, seen_fps: dict[str, int]) -> bool:
    if len(text) < MIN_CONTENT_LEN:
        return True
    for pat in _SPAM_RE:
        if pat.search(text):
            return True
    url_count = len(re.findall(r"https?://\S+", text))
    text_no_url = re.sub(r"https?://\S+", "", text).strip()
    if url_count >= 2 and len(text_no_url) < 30:
        return True
    stripped = re.sub(r"[#@]\w+|https?://\S+|\$\w+", "", text).strip()
    if len(stripped) < 25:
        return True
    fp = _content_fingerprint(text)
    if fp:
        seen_fps[fp] = seen_fps.get(fp, 0) + 1
        if seen_fps[fp] > 2:
            return True
    alpha_chars = len(re.findall(r"[\w\u4e00-\u9fff]", text))
    if alpha_chars < len(text) * 0.4 and len(text) > 30:
        return True
    return False


# ── Firefox cookie extraction ───────────────────────────────────────────────


def _find_firefox_profile() -> Path | None:
    import platform as _plat

    system = _plat.system()
    if system == "Windows":
        base = Path(os.environ.get("APPDATA", "")) / "Mozilla" / "Firefox" / "Profiles"
    elif system == "Darwin":
        base = Path.home() / "Library" / "Application Support" / "Firefox" / "Profiles"
    else:
        base = Path.home() / ".mozilla" / "firefox"
    if not base.exists():
        return None
    for p in sorted(base.iterdir(), reverse=True):
        if p.is_dir() and "default" in p.name and (p / "cookies.sqlite").exists():
            return p
    return None


def _extract_firefox_cookies(profile_dir: Path) -> list[dict[str, Any]]:
    cookies_db = profile_dir / "cookies.sqlite"
    if not cookies_db.exists():
        raise FileNotFoundError(f"cookies.sqlite not found: {cookies_db}")
    tmp = (
        Path(tempfile.gettempdir())
        / f"ff_cookies_{datetime.now().strftime('%Y%m%d%H%M%S%f')}.sqlite"
    )
    shutil.copy2(cookies_db, tmp)
    conn = None
    try:
        conn = sqlite3.connect(str(tmp))
        rows = conn.execute(
            "SELECT host, path, isSecure, name, value FROM moz_cookies "
            "WHERE host LIKE '%x.com%' OR host LIKE '%twitter.com%' ORDER BY host, name"
        ).fetchall()
    finally:
        if conn:
            conn.close()
        tmp.unlink(missing_ok=True)
    if not rows:
        raise RuntimeError("No x.com/twitter.com cookies found")
    cookies: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    names: set[str] = set()
    for host, path, is_secure, name, value in rows:
        domain = host if host.startswith(".") else "." + host
        key = (domain, path or "/", name)
        if key in seen:
            continue
        seen.add(key)
        names.add(name)
        cookies.append(
            {
                "name": name,
                "value": value,
                "domain": domain,
                "path": path or "/",
                "secure": bool(is_secure),
                "httpOnly": False,
            }
        )
    missing = [n for n in ("auth_token", "ct0") if n not in names]
    if missing:
        raise RuntimeError(f"Missing required X cookies: {missing}")
    return cookies


def _raw_to_tweet(raw: dict[str, Any]) -> _TweetRaw | None:
    if not raw or not raw.get("author") or not raw.get("url"):
        return None
    text = _normalize_text(raw.get("content", ""))
    if not text:
        return None
    tid = re.search(r"/status/(\d+)", raw["url"])
    if not tid:
        return None
    return _TweetRaw(
        tweet_id=tid.group(1),
        author=raw["author"],
        content=text,
        likes=_parse_stat(raw.get("like_aria", ""), "Likes"),
        reposts=_parse_stat(raw.get("repost_aria", ""), "reposts"),
        replies=_parse_stat(raw.get("reply_aria", ""), "Replies"),
        created_at=raw.get("created_at", ""),
        tags=_extract_tags(text),
        url=raw["url"],
    )


def _tweet_to_mentions(tweet: _TweetRaw, now: datetime) -> list[RawMention]:
    symbols = extract_symbols(tweet.content)
    if not symbols:
        symbols = [("UNKNOWN", "crypto")]

    created = now
    if tweet.created_at:
        try:
            created = datetime.fromisoformat(tweet.created_at.replace("Z", "+00:00"))
        except ValueError:
            pass

    mentions: list[RawMention] = []
    for sym, stype in symbols:
        mentions.append(
            RawMention(
                platform="x",
                source_id=tweet.tweet_id,
                symbol=sym,
                symbol_type=stype,
                author=tweet.author,
                content=tweet.content,
                created_at=created,
                collected_at=now,
                url=tweet.url,
                upvotes=tweet.likes,
                reposts=tweet.reposts,
                replies=tweet.replies,
                language="en",
                tags=tweet.tags,
                extra={"quality_score": tweet.likes * 3 + tweet.reposts * 2 + tweet.replies},
            )
        )
    return mentions


class XTwitterCollector:
    """
    X/Twitter collector using Playwright + Firefox cookie auth.

    Implements the Collector protocol.
    """

    CRYPTO_QUERIES = CRYPTO_QUERIES
    STOCK_QUERIES = STOCK_QUERIES

    def __init__(
        self,
        *,
        firefox_profile: str | Path | None = None,
        headless: bool = True,
        language: str = "zh-CN",
        viewport_width: int = 1440,
        viewport_height: int = 2400,
    ) -> None:
        self._profile_dir: Path | None = (
            Path(firefox_profile) if firefox_profile else _find_firefox_profile()
        )
        self._headless = headless
        self._language = language
        self._viewport = ViewportSize(width=viewport_width, height=viewport_height)
        self._last_tweet_id: str | None = None
        self._seen_fingerprints: dict[str, int] = {}

    @property
    def last_tweet_id(self) -> str | None:
        return self._last_tweet_id

    def _ensure_profile(self) -> Path:
        if self._profile_dir is None:
            raise RuntimeError(
                "Firefox profile not found. Set firefox_profile or log in to X in Firefox."
            )
        return self._profile_dir

    def _create_context(self, browser: Browser) -> BrowserContext:
        cookies = _extract_firefox_cookies(self._ensure_profile())
        ctx = browser.new_context(locale=self._language, viewport=self._viewport)
        ctx.add_cookies(cookies)  # type: ignore[arg-type]
        return ctx

    def _scroll_collect(self, page: Page, limit: int) -> list[_TweetRaw]:
        tweets: list[_TweetRaw] = []
        seen: set[str] = set()
        stable = 0
        last_count = -1

        while len(tweets) < limit and stable < 4:
            page.wait_for_timeout(800)
            raw_list: list[dict[str, Any]] = page.evaluate(BATCH_ARTICLES_JS)
            for raw in raw_list:
                t = _raw_to_tweet(raw)
                if not t or t.tweet_id in seen:
                    continue
                if _is_spam(t.content, self._seen_fingerprints):
                    continue
                seen.add(t.tweet_id)
                tweets.append(t)
                if len(tweets) >= limit:
                    break
            if len(raw_list) == last_count:
                stable += 1
            else:
                stable = 0
                last_count = len(raw_list)
            page.mouse.wheel(0, 2500)

        if tweets:
            self._last_tweet_id = tweets[-1].tweet_id
        return tweets[:limit]

    def _search_and_collect(
        self, context: BrowserContext, query: str, limit: int
    ) -> list[_TweetRaw]:
        seen_ids: set[str] = set()
        all_tweets: list[_TweetRaw] = []

        # Round 1: Top results
        page = context.new_page()
        try:
            page.goto(
                f"https://x.com/search?q={quote(query)}&src=typed_query",
                wait_until="domcontentloaded",
                timeout=60000,
            )
            page.wait_for_timeout(2500)
            for t in self._scroll_collect(page, limit):
                if t.tweet_id not in seen_ids:
                    seen_ids.add(t.tweet_id)
                    all_tweets.append(t)
        except PlaywrightTimeoutError:
            logger.warning("Timeout on Top search for %r", query)
        finally:
            page.close()

        # Round 2: Latest with min_faves filter
        remaining = limit - len(all_tweets)
        if remaining > 0:
            page2 = context.new_page()
            try:
                page2.goto(
                    f"https://x.com/search?q={quote(query)}%20min_faves%3A3&src=typed_query&f=live",
                    wait_until="domcontentloaded",
                    timeout=60000,
                )
                page2.wait_for_timeout(2500)
                for t in self._scroll_collect(page2, remaining + 5):
                    if t.tweet_id not in seen_ids:
                        seen_ids.add(t.tweet_id)
                        all_tweets.append(t)
            except PlaywrightTimeoutError:
                logger.warning("Timeout on Latest search for %r", query)
            finally:
                page2.close()

        return all_tweets[:limit]

    def _tweets_to_mentions(self, tweets: list[_TweetRaw]) -> list[RawMention]:
        now = datetime.now(timezone.utc)
        mentions: list[RawMention] = []
        seen_ids: set[str] = set()
        for t in tweets:
            if t.tweet_id in seen_ids:
                continue
            seen_ids.add(t.tweet_id)
            mentions.extend(_tweet_to_mentions(t, now))
        return mentions

    def collect_trending(self, limit: int = 100) -> list[RawMention]:
        queries = self.CRYPTO_QUERIES + self.STOCK_QUERIES
        per_query = max(limit // len(queries) + 3, 8)
        all_tweets: list[_TweetRaw] = []
        seen_ids: set[str] = set()

        with sync_playwright() as p:
            browser = p.firefox.launch(headless=self._headless)
            ctx = self._create_context(browser)
            try:
                for q in queries:
                    page = ctx.new_page()
                    try:
                        url = f"https://x.com/search?q={quote(q)}&src=typed_query&f=live"
                        page.goto(url, wait_until="domcontentloaded", timeout=60000)
                        page.wait_for_timeout(2500)
                        batch = self._scroll_collect(page, per_query)
                        for t in batch:
                            if t.tweet_id not in seen_ids:
                                seen_ids.add(t.tweet_id)
                                all_tweets.append(t)
                    except PlaywrightTimeoutError:
                        logger.warning("Timeout collecting trending query %r", q)
                    finally:
                        page.close()
            finally:
                browser.close()

        all_tweets.sort(key=lambda t: t.likes * 3 + t.reposts * 2 + t.replies, reverse=True)
        return self._tweets_to_mentions(all_tweets[:limit])

    def collect_symbol(self, symbol: str, days: int = 1) -> list[RawMention]:
        query = f"{symbol} OR ${symbol}"
        if days <= 1:
            query += " min_faves:3"

        with sync_playwright() as p:
            browser = p.firefox.launch(headless=self._headless)
            ctx = self._create_context(browser)
            try:
                tweets = self._search_and_collect(ctx, query, limit=50)
            finally:
                browser.close()

        mentions = self._tweets_to_mentions(tweets)
        if days > 0:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            mentions = [m for m in mentions if m.created_at >= cutoff]
        return mentions

    def search(self, query: str, limit: int = 50) -> list[RawMention]:
        with sync_playwright() as p:
            browser = p.firefox.launch(headless=self._headless)
            ctx = self._create_context(browser)
            try:
                tweets = self._search_and_collect(ctx, query, limit)
            finally:
                browser.close()
        return self._tweets_to_mentions(tweets)

    def health_check(self) -> dict[str, Any]:
        status: dict[str, Any] = {
            "platform": "x_twitter",
            "profile_found": self._profile_dir is not None,
            "profile_path": str(self._profile_dir) if self._profile_dir else None,
            "cookies_valid": False,
            "last_tweet_id": self._last_tweet_id,
        }
        if self._profile_dir:
            try:
                _extract_firefox_cookies(self._profile_dir)
                status["cookies_valid"] = True
            except Exception as exc:
                status["error"] = str(exc)
        return status
