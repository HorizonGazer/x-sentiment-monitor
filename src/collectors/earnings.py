"""
US Stock Earnings Tracker for WEEX-listed stock tokens.

Monitors:
- T-1 day (day before earnings): forecast/expected values
- T day (earnings day): actual values + stock T-day open→close % change

Data source: Exa MCP (财经数据 from authoritative sources)
- Earnings data: IR pages, Reuters, Bloomberg, Yahoo Finance, SeekingAlpha
- Stock prices: Yahoo Finance, MarketWatch, Bloomberg

Output: list[RawMention] tagged with 'earnings_forecast' or 'earnings_actual',
ready for ingestion into the regular sentiment pipeline.

CRITICAL RULES (from 优化.md):
- BMNR / WFC are EXCLUDED (already published — out of forecast/actual flow)
- WEEX channels are NEVER used as a source (they are second-hand)
- Stock change % uses T-day OPEN → T-day CLOSE only
- Missing fields are marked "—" (not fabricated)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from .base import RawMention
from .exa_search import ExaCollector

logger = logging.getLogger(__name__)


# ── Watchlist (from D:/download/x/优化.md, BMNR/WFC excluded) ───────────────
@dataclass
class StockTarget:
    name: str          # 公司名（中/英）
    ticker: str        # 股票代码
    earnings_date: str # YYYY-MM-DD
    weex_token: str    # WEEX 交易代币名
    weex_url: str      # WEEX 交易链接（仅作"用户行动入口"，非信源）


STOCK_WATCHLIST: list[StockTarget] = [
    StockTarget("特斯拉", "TSLA", "2026-04-22", "TSLA", "https://www.weex.com/zh-CN/futures/TSLA-USDT"),
    StockTarget("洛克希德马丁", "LMT", "2026-04-23", "LMT", "https://www.weex.com/zh-CN/futures/LMT-USDT"),
    StockTarget("英特尔", "INTC", "2026-04-23", "INTC", "https://www.weex.com/zh-CN/spot/INTCON-USDT"),
    StockTarget("宝洁", "PG", "2026-04-24", "PG", "https://www.weex.com/zh-CN/futures/PG-USDT"),
    StockTarget("Robinhood", "HOOD", "2026-04-28", "HOOD", "https://www.weex.com/zh-CN/futures/HOOD-USDT"),
    StockTarget("希捷科技", "STX", "2026-04-28", "STXSTOCK", "https://www.weex.com/zh-CN/futures/STXSTOCK-USDT"),
    StockTarget("亚马逊", "AMZN", "2026-04-29", "AMZN", "https://www.weex.com/zh-CN/futures/AMZN-USDT"),
    StockTarget("Meta", "META", "2026-04-29", "META", "https://www.weex.com/zh-CN/futures/META-USDT"),
    StockTarget("Nebius", "NBIS", "2026-04-29", "NBIS", "https://www.weex.com/zh-CN/futures/NBIS-USDT"),
    StockTarget("谷歌", "GOOGL", "2026-04-29", "GOOGL", "https://www.weex.com/zh-CN/futures/GOOGL-USDT"),
    StockTarget("微软", "MSFT", "2026-04-29", "MSFT", "https://www.weex.com/zh-CN/futures/MSFT-USDT"),
    StockTarget("Reddit", "RDDT", "2026-04-30", "RDDT", "https://www.weex.com/zh-CN/futures/RDDT-USDT"),
    StockTarget("苹果", "AAPL", "2026-04-30", "AAPL", "https://www.weex.com/zh-CN/futures/AAPL-USDT"),
    StockTarget("闪迪", "SNDK", "2026-04-30", "SNDK", "https://www.weex.com/zh-CN/futures/SNDK-USDT"),
    StockTarget("林德集团", "LIN", "2026-05-01", "LIN", "http://www.weex.com/zh-CN/futures/LIN-USDT"),
    StockTarget("Palantir", "PLTR", "2026-05-04", "PLTR", "https://www.weex.com/zh-CN/futures/PLTR-USDT"),
    StockTarget("Strategy", "MSTR", "2026-05-05", "MSTR", "https://www.weex.com/zh-CN/futures/MSTR-USDT"),
    StockTarget("IONQ", "IONQ", "2026-05-06", "IONQ", "https://www.weex.com/zh-CN/futures/IONQ-USDT"),
    StockTarget("Coinbase", "COIN", "2026-05-07", "COIN", "https://www.weex.com/zh-CN/futures/COIN-USDT"),
    StockTarget("CoreWeave", "CRWV", "2026-05-07", "CRWV", "https://www.weex.com/zh-CN/futures/CRWV-USDT"),
    StockTarget("PayPal", "PAYP", "2026-05-07", "PAYP", "https://www.weex.com/zh-CN/futures/PAYP-USDT"),
    StockTarget("Circle", "CRCL", "2026-05-11", "CRCL", "https://www.weex.com/zh-CN/futures/CRCL-USDT"),
    StockTarget("沃尔玛", "WM", "2026-05-14", "WM", "https://www.weex.com/zh-CN/futures/WM-USDT"),
    StockTarget("京东", "JD", "2026-05-19", "JD", "https://www.weex.com/zh-CN/futures/JD-USDT"),
    StockTarget("英伟达", "NVDA", "2026-05-20", "NVDA", "https://www.weex.com/zh-CN/futures/NVDA-USDT"),
    StockTarget("拼多多", "PDD", "2026-05-27", "PDD", "https://www.weex.com/zh-CN/futures/PDD-USDT"),
    StockTarget("富途证券", "FUTU", "2026-06-03", "FUTU", "https://www.weex.com/zh-CN/futures/FUTU-USDT"),
    StockTarget("甲骨文", "ORCL", "2026-06-16", "ORCL", "https://www.weex.com/zh-CN/futures/ORCL-USDT"),
    StockTarget("美光科技", "MU", "2026-07-01", "MU", "https://www.weex.com/zh-CN/futures/MU-USDT"),
    StockTarget("台积电", "TSM", "2026-07-16", "TSM", "https://www.weex.com/zh-CN/futures/TSM-USDT"),
    StockTarget("开市客", "COST", "2026-07-29", "COST", "https://www.weex.com/zh-CN/futures/COST-USDT"),
    # NOTE: BMNR (Bitmine) and WFC (富国银行) are intentionally excluded
    # — they are marked "已发布" in upstream spec.
]


# ── Source domains for earnings data (WEEX explicitly NOT included) ─────────
EARNINGS_DOMAINS: list[str] = [
    "reuters.com",
    "bloomberg.com",
    "cnbc.com",
    "wsj.com",
    "ft.com",
    "finance.yahoo.com",
    "marketwatch.com",
    "barrons.com",
    "seekingalpha.com",
    "investing.com",
    "businesswire.com",
    "prnewswire.com",
    "globenewswire.com",
    # 中文财经
    "wallstreetcn.com",
    "jin10.com",
    "cls.cn",
    "caixin.com",
    "yicai.com",
    "36kr.com",
]

# 信源黑名单：永不接受作为信源（仅作交易入口）
WEEX_BLACKLIST_DOMAINS: list[str] = [
    "weex.com",
    "blog.weex.com",
    "support.weex.com",
    "weex.zendesk.com",
]


def _is_weex_source(url: str) -> bool:
    """Check if URL is from WEEX (must be excluded as a news source)."""
    return any(d in (url or "").lower() for d in WEEX_BLACKLIST_DOMAINS)


def _today_str() -> str:
    return date.today().strftime("%Y-%m-%d")


def get_targets_for_today(today: date | None = None) -> dict[str, list[StockTarget]]:
    """
    Returns stocks needing forecast (T-1) or actual (T) coverage today.

    {
      "forecast": [stocks with earnings tomorrow],
      "actual":   [stocks with earnings today],
    }
    """
    today = today or date.today()
    tomorrow = today + timedelta(days=1)

    forecast = []
    actual = []
    for s in STOCK_WATCHLIST:
        try:
            ed = datetime.strptime(s.earnings_date, "%Y-%m-%d").date()
        except ValueError:
            continue
        if ed == tomorrow:
            forecast.append(s)
        elif ed == today:
            actual.append(s)
    return {"forecast": forecast, "actual": actual}


class EarningsCollector:
    """
    Collects earnings data via Exa for WEEX-listed stocks.
    All RawMention output is tagged so the report writer can route correctly.
    """

    def __init__(self) -> None:
        self.exa = ExaCollector()

    # ── Forecast (T-1) ─────────────────────────────────────────────────
    def collect_forecast(self, target: StockTarget, num_results: int = 8) -> list[RawMention]:
        """Search Exa for analyst expectations / consensus estimates."""
        queries = [
            f"{target.ticker} earnings preview expected EPS revenue analyst estimate",
            f"{target.name} {target.ticker} 财报预期 分析师预测",
            f"{target.ticker} Q1 Q2 Q3 Q4 earnings forecast consensus",
            f"{target.ticker} earnings whisper number analyst expectation",
        ]
        return self._search_to_mentions(
            target, queries,
            tag="earnings_forecast",
            num_results=num_results,
            freshness="week",
        )

    # ── Actual (T) ─────────────────────────────────────────────────────
    def collect_actual(self, target: StockTarget, num_results: int = 10) -> list[RawMention]:
        """Search Exa for actual reported numbers + stock reaction."""
        queries = [
            f"{target.ticker} earnings results reported revenue EPS",
            f"{target.name} {target.ticker} 财报 实际 营收 EPS",
            f"{target.ticker} earnings beat miss reaction stock price",
            f"{target.ticker} Q1 Q2 Q3 Q4 earnings actual report",
            f"{target.ticker} stock price open close earnings day",
        ]
        return self._search_to_mentions(
            target, queries,
            tag="earnings_actual",
            num_results=num_results,
            freshness="24h",
        )

    # ── Stock T-day open→close change ──────────────────────────────────
    def collect_price_change(self, target: StockTarget, num_results: int = 5) -> list[RawMention]:
        """Search for the stock's T-day open and close prices."""
        queries = [
            f"{target.ticker} stock open close price today {_today_str()}",
            f"{target.ticker} stock daily range high low today",
        ]
        return self._search_to_mentions(
            target, queries,
            tag="stock_price_change",
            num_results=num_results,
            freshness="24h",
        )

    # ── Internal helper ────────────────────────────────────────────────
    def _search_to_mentions(
        self,
        target: StockTarget,
        queries: list[str],
        tag: str,
        num_results: int,
        freshness: str,
    ) -> list[RawMention]:
        mentions: list[RawMention] = []
        seen_urls: set[str] = set()

        for q in queries:
            results = self.exa.search_exa(
                q,
                num_results=num_results,
                freshness=freshness,
                include_domains=EARNINGS_DOMAINS,
            )
            for r in results:
                url = r.get("url", "")
                if not url or url in seen_urls:
                    continue
                # ❌ HARD RULE: Never accept WEEX as a source
                if _is_weex_source(url):
                    logger.debug("Skipping WEEX URL (not a valid source): %s", url)
                    continue
                seen_urls.add(url)

                title = r.get("title", "")
                text = (r.get("text", "") or "")[:600]
                content = f"{title}. {text}".strip() if text else title
                if not content or len(content) < 20:
                    continue

                pub = r.get("published", "")
                try:
                    dt = datetime.fromisoformat(pub.replace("Z", "+00:00")) if pub else datetime.now(timezone.utc)
                except ValueError:
                    dt = datetime.now(timezone.utc)

                author = r.get("author", "") or ""
                if not author or author == "N/A":
                    domain = re.search(r"https?://(?:www\.)?([^/]+)", url)
                    author = domain.group(1) if domain else "Web"

                mentions.append(
                    RawMention(
                        platform="exa_earnings",
                        source_id=url,
                        symbol=target.ticker,
                        symbol_type="stock",
                        author=author,
                        content=content,
                        url=url,
                        created_at=dt,
                        collected_at=datetime.now(timezone.utc),
                        upvotes=0,
                        reposts=0,
                        replies=0,
                        tags=[tag, "earnings", target.ticker, target.weex_token],
                        extra={
                            "earnings_target": {
                                "name": target.name,
                                "ticker": target.ticker,
                                "earnings_date": target.earnings_date,
                                "weex_token": target.weex_token,
                                "weex_url": target.weex_url,  # 仅交易入口，非信源
                            },
                            "stage": tag,  # earnings_forecast / earnings_actual / stock_price_change
                        },
                    )
                )

        return mentions

    # ── Public entry: collect all earnings-relevant data for today ────
    def collect_today(self, today: date | None = None) -> dict[str, Any]:
        """
        One-shot collection for the day's earnings tracker.
        Returns:
          {
            "forecast": {ticker: [RawMention]},
            "actual":   {ticker: [RawMention]},
            "price":    {ticker: [RawMention]},
            "targets":  {"forecast": [StockTarget], "actual": [StockTarget]},
          }
        """
        targets = get_targets_for_today(today)
        out: dict[str, Any] = {
            "forecast": {},
            "actual": {},
            "price": {},
            "targets": targets,
        }

        for s in targets["forecast"]:
            try:
                out["forecast"][s.ticker] = self.collect_forecast(s)
                logger.info("Earnings forecast: %s collected %d mentions",
                            s.ticker, len(out["forecast"][s.ticker]))
            except Exception as e:
                logger.warning("Earnings forecast failed for %s: %s", s.ticker, e)
                out["forecast"][s.ticker] = []

        for s in targets["actual"]:
            try:
                out["actual"][s.ticker] = self.collect_actual(s)
                out["price"][s.ticker] = self.collect_price_change(s)
                logger.info("Earnings actual: %s collected %d (actual) + %d (price)",
                            s.ticker,
                            len(out["actual"][s.ticker]),
                            len(out["price"][s.ticker]))
            except Exception as e:
                logger.warning("Earnings actual/price failed for %s: %s", s.ticker, e)
                out["actual"][s.ticker] = []
                out["price"][s.ticker] = []

        return out
