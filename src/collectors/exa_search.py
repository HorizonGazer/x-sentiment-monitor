"""
Exa web intelligence collector via mcporter MCP (free, no API key).

Primary: mcporter call exa.web_search_exa / exa.crawling_exa
Fallback: Jina Reader for URL reading, RSS for news feeds
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from typing import Any

import httpx

from .base import RawMention
from .symbol_extractor import extract_symbols

logger = logging.getLogger(__name__)

JINA_PREFIX = "https://r.jina.ai/"
HEADERS = {"User-Agent": "WEEX-Sentinel/1.0"}
TIMEOUT = 15

CRYPTO_QUERIES = [
    "Bitcoin price analysis market crash liquidation whale accumulation",
    "cryptocurrency regulation SEC CLARITY Act stablecoin ETF approval",
    "Ethereum Solana DeFi protocol upgrade TVL yield",
    "crypto institutional adoption BlackRock Morgan Stanley Fidelity ETF inflow",
    "Bitcoin mining hashrate AI data center energy",
    "meme coin Dogecoin Pepe Solana trending pump",
    "crypto exchange Binance Coinbase OKX listing delisting",
    "geopolitical risk tariff sanctions war impact crypto market",
    "XRP Ripple SEC commodity classification legal",
    "stablecoin USDC USDT Circle Tether regulation yield ban",
]

AUTHORITY_DOMAINS = [
    "coindesk.com",
    "cointelegraph.com",
    "theblock.co",
    "decrypt.co",
    "bitcoinmagazine.com",
    "blockworks.co",
    "finance.yahoo.com",
    "bloomberg.com",
    "reuters.com",
    "sec.gov",
    "cnbc.com",
    "forbes.com",
    "wsj.com",
    "ft.com",
    "ambcrypto.com",
    "cryptoslate.com",
    "bitcoinist.com",
    "news.bitcoin.com",
    "crypto.news",
    "dlnews.com",
]


def _find_mcporter() -> str | None:
    path = shutil.which("mcporter")
    if path:
        return path
    candidates = [
        os.path.expandvars(r"%APPDATA%\npm\mcporter.cmd"),
        os.path.expanduser("~/.npm-global/bin/mcporter"),
        "/usr/local/bin/mcporter",
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


_MCPORTER_PATH = _find_mcporter()


def _mcporter_available() -> bool:
    return _MCPORTER_PATH is not None


MCPORTER_CWD = os.environ.get("MCPORTER_CWD", r"D:\download\x")


def _mcporter_call(tool_call: str, timeout: int = 30) -> str | None:
    if not _MCPORTER_PATH:
        return None
    try:
        r = subprocess.run(
            [_MCPORTER_PATH, "call", tool_call],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=True,
            cwd=MCPORTER_CWD,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
        if r.stderr:
            logger.warning("mcporter stderr: %s", r.stderr[:200])
    except subprocess.TimeoutExpired:
        logger.warning("mcporter call timed out: %s", tool_call[:80])
    except Exception as e:
        logger.warning("mcporter call failed: %s", e)
    return None


def _parse_exa_results(raw: str) -> list[dict]:
    results = []
    current: dict[str, str] = {}
    for line in raw.split("\n"):
        line = line.strip()
        if line.startswith("Title: "):
            if current.get("title"):
                results.append(current)
            current = {"title": line[7:], "url": "", "published": "", "author": "", "text": ""}
        elif line.startswith("URL: "):
            current["url"] = line[5:]
        elif line.startswith("Published: "):
            current["published"] = line[11:]
        elif line.startswith("Author: "):
            current["author"] = line[8:]
        elif line.startswith("Highlights:"):
            pass
        elif line == "---":
            if current.get("title"):
                results.append(current)
                current = {}
        elif current and line:
            current["text"] = (current.get("text", "") + " " + line).strip()
    if current.get("title"):
        results.append(current)
    return results


class ExaCollector:
    def __init__(self, timeout: float = TIMEOUT):
        self._timeout = timeout
        self._has_mcporter = _mcporter_available()

    @property
    def exa_available(self) -> bool:
        return self._has_mcporter

    def search_exa(
        self,
        query: str,
        num_results: int = 8,
        freshness: str = "week",
        include_domains: list[str] | None = None,
    ) -> list[dict]:
        if not self._has_mcporter:
            logger.warning("mcporter not installed, Exa search unavailable")
            return []
        if include_domains:
            domains_str = ", ".join(f'"{d}"' for d in include_domains)
            call = f'exa.web_search_exa(query: "{query}", numResults: {num_results}, freshness: "{freshness}", includeDomains: [{domains_str}])'
        else:
            call = f'exa.web_search_exa(query: "{query}", numResults: {num_results}, freshness: "{freshness}")'
        raw = _mcporter_call(call, timeout=30)
        if not raw:
            return []
        return _parse_exa_results(raw)

    def crawl_url(self, url: str, max_chars: int = 3000) -> str | None:
        if self._has_mcporter:
            call = f'exa.crawling_exa(urls: ["{url}"], maxCharacters: {max_chars})'
            raw = _mcporter_call(call, timeout=20)
            if raw:
                return raw[:max_chars]
        try:
            r = httpx.get(
                f"{JINA_PREFIX}{url}", headers=HEADERS, timeout=self._timeout, follow_redirects=True
            )
            if r.status_code == 200:
                return r.text[:max_chars]
        except Exception as e:
            logger.warning("Jina read failed for %s: %s", url, e)
        return None

    def collect_trending(self, limit: int = 60) -> list[RawMention]:
        mentions: list[RawMention] = []
        seen_urls: set[str] = set()

        def _add_results(results):
            for r in results:
                url = r.get("url", "")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                title = r.get("title", "")
                text = r.get("text", "")[:500]
                content = f"{title}. {text}".strip() if text else title
                if not content or len(content) < 20:
                    continue
                syms = extract_symbols(content)
                sym = syms[0][0] if syms else "UNKNOWN"
                stype = syms[0][1] if syms else "crypto"
                pub = r.get("published", "")
                try:
                    dt = (
                        datetime.fromisoformat(pub.replace("Z", "+00:00"))
                        if pub
                        else datetime.now(timezone.utc)
                    )
                except ValueError:
                    dt = datetime.now(timezone.utc)
                author = r.get("author", "")
                if not author or author == "N/A":
                    domain = re.search(r"https?://(?:www\.)?([^/]+)", url)
                    author = domain.group(1) if domain else "Web"
                mentions.append(
                    RawMention(
                        platform="exa",
                        source_id=url,
                        symbol=sym,
                        symbol_type=stype,
                        author=author,
                        content=content,
                        url=url,
                        created_at=dt,
                        collected_at=datetime.now(timezone.utc),
                        upvotes=0,
                        reposts=0,
                        replies=0,
                    )
                )

        for query in CRYPTO_QUERIES:
            results = self.search_exa(
                query, num_results=10, freshness="24h", include_domains=AUTHORITY_DOMAINS
            )
            if len(results) < 3:
                results = self.search_exa(
                    query, num_results=10, freshness="week", include_domains=AUTHORITY_DOMAINS
                )
            _add_results(results)
            if len(mentions) >= limit:
                break

        if len(mentions) < limit:
            broad = self.search_exa("crypto market news today", num_results=10, freshness="24h")
            _add_results(broad)

        return mentions[:limit]

    def collect_symbol(self, symbol: str, days: int = 1) -> list[RawMention]:
        freshness = "24h" if days <= 1 else "week"
        results = self.search_exa(
            f"{symbol} crypto news analysis price", num_results=10, freshness=freshness
        )
        mentions = []
        for r in results:
            content = f"{r.get('title', '')}. {r.get('text', '')[:300]}".strip()
            if not content:
                continue
            try:
                dt = datetime.fromisoformat(r.get("published", "").replace("Z", "+00:00"))
            except (ValueError, TypeError):
                dt = datetime.now(timezone.utc)
            mentions.append(
                RawMention(
                    platform="exa",
                    source_id=r.get("url", ""),
                    symbol=symbol,
                    symbol_type="crypto",
                    author=r.get("author", "Web"),
                    content=content,
                    url=r.get("url", ""),
                    created_at=dt,
                    collected_at=datetime.now(timezone.utc),
                )
            )
        return mentions

    def search(self, query: str, limit: int = 20) -> list[RawMention]:
        results = self.search_exa(query, num_results=limit)
        mentions = []
        for r in results:
            content = f"{r.get('title', '')}. {r.get('text', '')[:300]}".strip()
            if not content:
                continue
            syms = extract_symbols(content)
            sym = syms[0][0] if syms else "UNKNOWN"
            mentions.append(
                RawMention(
                    platform="exa",
                    source_id=r.get("url", ""),
                    symbol=sym,
                    symbol_type="crypto",
                    author=r.get("author", "Web"),
                    content=content,
                    url=r.get("url", ""),
                    created_at=datetime.now(timezone.utc),
                    collected_at=datetime.now(timezone.utc),
                )
            )
        return mentions

    def health_check(self) -> dict:
        status = {
            "platform": "exa",
            "mcporter_installed": self._has_mcporter,
            "exa_configured": False,
            "jina_available": False,
        }
        if self._has_mcporter:
            try:
                r = subprocess.run(
                    ["mcporter", "config", "list"], capture_output=True, encoding="utf-8", timeout=5
                )
                status["exa_configured"] = "exa" in r.stdout.lower()
            except Exception:
                pass
        try:
            r = httpx.get(f"{JINA_PREFIX}https://example.com", headers=HEADERS, timeout=5)
            status["jina_available"] = r.status_code == 200
        except Exception:
            pass
        return status
