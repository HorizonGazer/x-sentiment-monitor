#!/usr/bin/env python3
"""
WEEX Sentinel - Data Collector + Structured Summary Generator

Step 1 of the new pipeline:
  1. Python collects data from X/Twitter + Exa → saves raw JSON
  2. Python generates a structured summary (stats, clusters, sentiment) → saves summary JSON
  3. Claude (AI) reads raw JSON + summary → writes the actual analysis report

Usage:
  python scripts/collect_data.py           # collect + save raw + summary
  python scripts/collect_data.py --from-raw D:/path/to/raw.json   # regenerate summary from existing raw
"""

import sys
import os
import re
import json
import logging
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.collectors.x_twitter import XTwitterCollector
from src.collectors.exa_search import ExaCollector, CROSS_SECTOR_QUERIES, MACRO_FINANCE_QUERIES, GLOBAL_NEWS_QUERIES
from src.collectors.weex_official import WeexOfficialCollector
from src.collectors.base import RawMention
from src.collectors.dedup import dedup_mentions, dedup_dict_items, filter_weex_sources
from src.collectors.earnings import EarningsCollector, get_targets_for_today
from src.sentiment.vader_crypto import create_crypto_vader

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

LOG_ROOT = Path("D:/download/x/x_sentiment_logs")

# Beijing time (China Standard Time = UTC+8, no DST)
CST = timezone(timedelta(hours=8))


def now_cst():
    """Return current Beijing time (UTC+8) as timezone-aware datetime."""
    return datetime.now(timezone.utc).astimezone(CST)

EVENT_CATEGORIES = {
    "爆仓": ["liquidat", "爆仓", "强平", "清算", "rekt", "margin call", "wipeout"],
    "监管": ["regulat", "sec ", "监管", "compliance", "lawsuit", "ban", "禁止", "legal", "法案", "legislation", "clarity", "cftc"],
    "地缘政治": ["war", "geopolit", "sanction", "iran", "russia", "china", "tariff", "trump", "biden", "recession", "地缘", "战争", "制裁", "关税"],
    "技术升级": ["upgrade", "fork", "layer", "rollup", "eip", "升级", "分叉", "L2", "L1", "protocol", "mainnet", "testnet", "pectra"],
    "DeFi": ["defi", "swap", "liquidity", "yield", "staking", "tvl", "aave", "uniswap", "lido", "质押", "流动性", "stablecoin", "稳定币"],
    "Meme": ["meme", "doge", "shib", "pepe", "bonk", "wif", "floki", "土狗"],
    "AI": ["ai ", " ai", "artificial intellig", "gpu", "agent", "openai", "chatgpt", "claude", "llm", "机器学习", "人工智能"],
    "巨鲸": ["whale", "巨鲸", "大户", "accumul", "囤币", "大额转账", "transfer"],
    "ETF": ["etf", "spot etf", "grayscale", "blackrock", "fidelity", "ishares", "morgan stanley"],
    "交易所": ["exchange", "binance", "coinbase", "okx", "bybit", "weex", "listing", "上所", "上币", "delist"],
    "宏观经济": ["fed ", "fomc", "cpi", "inflation", "interest rate", "gdp", "employment", "美联储", "通胀", "利率", "降息", "加息"],
    "安全事件": ["hack", "exploit", "breach", "vulnerability", "漏洞", "被盗", "黑客", "attack", "stolen"],
    "价格走势": ["price", "ath", "pump", "dump", "rally", "crash", "surge", "plunge", "breakout", "暴涨", "暴跌", "突破", "新高"],
    "WEEX动态": ["WEEX", "weex", "交易大赛", "合约大赛", "注册奖励", "邀请返佣"],
    "币圈八卦": ["八卦", "drama", "scandal", "跑路", "暴雷", "撕逼", "内幕", "gossip", "rug pull", "controversy"],
    "币圈热点": ["热点", "trending", "火爆", "刷屏", "爆火", "hot topic"],
}


def classify_event(text):
    text_lower = text.lower()
    scores = {}
    for cat, keywords in EVENT_CATEGORIES.items():
        score = sum(1 for kw in keywords if kw.lower() in text_lower)
        if score > 0:
            scores[cat] = score
    if not scores:
        return "市场动态"
    return max(scores, key=scores.get)


def classify_cross_sector_type(text):
    """Classify cross-sector / global news mention into sub-type based on content keywords."""
    text_lower = text.lower()
    if any(k in text_lower for k in ["crude oil", "gold", "xau", "opec", "silver", "commodity", "原油", "黄金", "大宗"]):
        return "commodity"
    if any(k in text_lower for k in ["ai model", "gpt", "claude", "gemini", "openai", "nvidia", "semiconductor", "chip", "算力", "芯片", "人工智能"]):
        return "ai_tech"
    if any(k in text_lower for k in ["a股", "沪深", "上证", "深证", "a-share", "csi", "shanghai"]):
        return "a_share"
    if any(k in text_lower for k in ["hong kong", "hang seng", "hsi", "港股", "恒生"]):
        return "hk_stock"
    if any(k in text_lower for k in ["s&p", "nasdaq", "dow", "wall street", "美股", "nyse"]):
        return "us_stock"
    if any(k in text_lower for k in ["venture capital", "funding round", "series a", "series b", "融资", "投资", "风投", "vc "]):
        return "vc_funding"
    if any(k in text_lower for k in ["geopolit", "sanction", "tariff", "trade war", "conflict", "diplomacy", "地缘", "制裁", "关税"]):
        return "geopolitics"
    if any(k in text_lower for k in ["elon musk", "musk", "trump", "流量"]):
        return "influencer"
    if any(k in text_lower for k in ["stock market", "cpi", "fed ", "fomc", "interest rate", "美联储", "通胀", "利率"]):
        return "macro"
    return "other"


def classify_global_news_sector(text):
    """Classify global news mention into sector for report Chapter 2."""
    text_lower = text.lower()
    # 国内科技/互联网（优先识别国内大厂关键词）
    if any(k in text_lower for k in [
        "阿里", "腾讯", "字节", "美团", "京东", "拼多多", "百度", "网易", "小米",
        "比亚迪", "蔚来", "小鹏", "理想", "华为", "中兴", "宁德时代",
        "国产芯片", "国产替代", "新能源车", "造车新势力",
        "36氪", "虎嗅", "钛媒体", "雷锋网", "量子位", "机器之心", "极客公园"
    ]):
        return "国内科技"
    if any(k in text_lower for k in ["ai ", " ai", "openai", "nvidia", "gpu", "semiconductor", "chip", "chatgpt", "claude", "gemini", "llm", "人工智能", "芯片", "算力", "大模型"]):
        return "科技/AI"
    if any(k in text_lower for k in ["s&p", "nasdaq", "dow", "wall street", "美股", "nyse", "earnings"]):
        return "美股"
    if any(k in text_lower for k in ["a股", "沪深", "上证", "深证", "a-share", "shanghai composite", "北向资金"]):
        return "A股"
    if any(k in text_lower for k in ["hong kong", "hang seng", "hsi", "港股", "恒生"]):
        return "港股"
    if any(k in text_lower for k in ["台湾", "taiwan", "twse", "台股", "加权指数", "tsmc", "台积电", "聯發科", "香港", "澳门", "macau"]):
        return "港澳台"
    if any(k in text_lower for k in ["venture capital", "funding round", "series a", "series b", "series c", "融资", "投资", "风投", "vc ", "startup", "ipo", "独角兽"]):
        return "风投/融资"
    if any(k in text_lower for k in ["crude oil", "gold", "silver", "opec", "commodity", "原油", "黄金", "白银", "大宗"]):
        return "大宗商品"
    if any(k in text_lower for k in ["geopolit", "sanction", "tariff", "trade war", "conflict", "diplomacy", "地缘", "制裁", "关税", "战争"]):
        return "国际政治"
    if any(k in text_lower for k in ["fed ", "fomc", "cpi", "inflation", "interest rate", "gdp", "美联储", "通胀", "利率", "降息", "加息"]):
        return "金融/宏观"
    return "全球热门"


def _collect_x_with_retry(limit=30, max_retries=2):
    for attempt in range(1, max_retries + 1):
        try:
            x_collector = XTwitterCollector(headless=True)
            x_mentions = x_collector.collect_trending(limit=limit)
            if x_mentions:
                logger.info("X/Twitter: collected %d mentions (attempt %d)", len(x_mentions), attempt)
                return x_mentions
            logger.warning("X/Twitter: 0 mentions on attempt %d, retrying...", attempt)
        except Exception as e:
            logger.warning("X/Twitter attempt %d failed: %s", attempt, e)
        if attempt < max_retries:
            time.sleep(3)
    logger.error("X/Twitter: all %d attempts returned 0 results", max_retries)
    return []


def collect_all_mentions():
    all_mentions = []
    logger.info("Collecting Exa/News data (PRIMARY source)...")
    try:
        exa_collector = ExaCollector()
        exa_mentions = exa_collector.collect_trending(limit=100)
        all_mentions.extend(exa_mentions)
        logger.info("Exa/News: collected %d mentions from authority sources", len(exa_mentions))
    except Exception as e:
        logger.error("Exa/News collection failed: %s", e)

    logger.info("Collecting Exa WEEX news...")
    try:
        exa_collector = ExaCollector()
        weex_exa = exa_collector.collect_weex(limit=20)
        all_mentions.extend(weex_exa)
        logger.info("Exa WEEX: collected %d mentions", len(weex_exa))
    except Exception as e:
        logger.error("Exa WEEX collection failed: %s", e)

    logger.info("Collecting Exa gossip/hot topics...")
    try:
        exa_collector = ExaCollector()
        gossip_exa = exa_collector.collect_gossip(limit=20)
        all_mentions.extend(gossip_exa)
        logger.info("Exa gossip: collected %d mentions", len(gossip_exa))
        hot_exa = exa_collector.collect_hot_topics(limit=20)
        all_mentions.extend(hot_exa)
        logger.info("Exa hot topics: collected %d mentions", len(hot_exa))
    except Exception as e:
        logger.error("Exa gossip/hot topics collection failed: %s", e)

    logger.info("Collecting Exa cross-sector (跨圈) data...")
    try:
        exa_collector = ExaCollector()
        cross_sector_mentions = exa_collector.collect_cross_sector(limit=20)
        # Tag each mention with category and cross_sector_type
        for m in cross_sector_mentions:
            m.tags = list(set(m.tags + ["跨圈热点"]))
            m.extra["cross_sector_type"] = classify_cross_sector_type(m.content)
        all_mentions.extend(cross_sector_mentions)
        logger.info(f"Cross-sector: collected {len(cross_sector_mentions)} mentions")
    except Exception as e:
        logger.error("Exa cross-sector collection failed: %s", e)

    logger.info("Collecting Exa macro finance (宏观财经) data...")
    try:
        exa_collector = ExaCollector()
        macro_mentions = exa_collector.collect_macro_finance(limit=20)
        for m in macro_mentions:
            m.tags = list(set(m.tags + ["宏观财经"]))
        all_mentions.extend(macro_mentions)
        logger.info("Macro finance: collected %d mentions", len(macro_mentions))
    except Exception as e:
        logger.error("Exa macro finance collection failed: %s", e)

    logger.info("Collecting Exa global news (全球新闻) data...")
    try:
        exa_collector = ExaCollector()
        global_mentions = exa_collector.collect_global_news(limit=80)
        for m in global_mentions:
            m.tags = list(set(m.tags + ["全球新闻"]))
            m.extra["global_news_sector"] = classify_global_news_sector(m.content)
        all_mentions.extend(global_mentions)
        logger.info("Global news: collected %d mentions", len(global_mentions))
    except Exception as e:
        logger.error("Exa global news collection failed: %s", e)

    logger.info("Collecting Exa Hong Kong/Taiwan/Macau (港澳台) news...")
    try:
        exa_collector = ExaCollector()
        hk_tw_mentions = exa_collector.collect_hk_tw_macau(limit=30)
        for m in hk_tw_mentions:
            m.tags = list(set(m.tags + ["港澳台"]))
            m.extra["global_news_sector"] = "港澳台"
        all_mentions.extend(hk_tw_mentions)
        logger.info("HK/TW/Macau: collected %d mentions", len(hk_tw_mentions))
    except Exception as e:
        logger.error("Exa HK/TW/Macau collection failed: %s", e)

    logger.info("Collecting X/Twitter data (corroboration)...")
    x_mentions = _collect_x_with_retry(limit=30)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
    x_filtered = [m for m in x_mentions if m.created_at >= cutoff]
    if len(x_filtered) < len(x_mentions):
        logger.info("X/Twitter: filtered %d old tweets, keeping %d",
                     len(x_mentions) - len(x_filtered), len(x_filtered))
    all_mentions.extend(x_filtered)

    logger.info("Collecting X/Twitter WEEX mentions...")
    try:
        x_collector = XTwitterCollector(headless=True)
        weex_x = x_collector.collect_weex(limit=20)
        all_mentions.extend(weex_x)
        logger.info("X WEEX: collected %d mentions", len(weex_x))
    except Exception as e:
        logger.error("X WEEX collection failed: %s", e)

    logger.info("Collecting X/Twitter gossip...")
    try:
        x_collector = XTwitterCollector(headless=True)
        gossip_x = x_collector.collect_gossip(limit=20)
        all_mentions.extend(gossip_x)
        logger.info("X gossip: collected %d mentions", len(gossip_x))
    except Exception as e:
        logger.error("X gossip collection failed: %s", e)

    logger.info("Collecting X/Twitter hot topics...")
    try:
        x_collector = XTwitterCollector(headless=True)
        hot_x = x_collector.collect_hot_topics(limit=20)
        all_mentions.extend(hot_x)
        logger.info("X hot topics: collected %d mentions", len(hot_x))
    except Exception as e:
        logger.error("X hot topics collection failed: %s", e)

    logger.info("Collecting WEEX official website...")
    try:
        weex_collector = WeexOfficialCollector(headless=True)
        weex_official = weex_collector.collect(limit=20)
        all_mentions.extend(weex_official)
        logger.info("WEEX Official: collected %d mentions", len(weex_official))
    except Exception as e:
        logger.error("WEEX Official collection failed: %s", e)

    # ── US Stock Earnings Tracker (NEW per 优化.md 改造3) ──────────────
    logger.info("Collecting US stock earnings (T-1 forecast + T actual)...")
    try:
        earnings_collector = EarningsCollector()
        earnings_today = earnings_collector.collect_today()
        for ticker, ms in earnings_today["forecast"].items():
            for m in ms:
                m.tags = list(set(m.tags + ["美股财报", "财报预告"]))
            all_mentions.extend(ms)
        for ticker, ms in earnings_today["actual"].items():
            for m in ms:
                m.tags = list(set(m.tags + ["美股财报", "财报实际"]))
            all_mentions.extend(ms)
        for ticker, ms in earnings_today["price"].items():
            for m in ms:
                m.tags = list(set(m.tags + ["美股财报", "股价变动"]))
            all_mentions.extend(ms)
        logger.info(
            "Earnings tracker: forecast=%d ticker(s), actual=%d ticker(s)",
            len(earnings_today["targets"]["forecast"]),
            len(earnings_today["targets"]["actual"]),
        )
    except Exception as e:
        logger.error("Earnings collection failed: %s", e)

    return all_mentions


def fmt_dt(dt):
    """Format datetime as Beijing time (UTC+8). Inputs may be naive or any tz."""
    if dt.tzinfo is None:
        # Treat naive as UTC for safety, then convert
        dt = dt.replace(tzinfo=timezone.utc)
    dt_cst = dt.astimezone(CST)
    return dt_cst.strftime("%Y-%m-%dT%H:%M:%S%z")


def sentiment_emoji(compound):
    if compound > 0.3:
        return "强烈看涨"
    elif compound > 0.05:
        return "温和看涨"
    elif compound > -0.05:
        return "中性"
    elif compound > -0.3:
        return "温和看跌"
    return "强烈看跌"


def _mention_to_dict(m, compound):
    return {
        "platform": m.platform,
        "source_id": m.source_id,
        "symbol": m.symbol,
        "author": m.author,
        "content": m.content,
        "url": m.url,
        "created_at": fmt_dt(m.created_at),
        "likes": m.upvotes,
        "reposts": m.reposts,
        "replies": m.replies,
        "language": m.language,
        "tags": m.tags,
        "sentiment_score": round(compound, 4),
        "sentiment_label": sentiment_emoji(compound),
        "category": "跨圈热点" if "跨圈热点" in m.tags else ("全球新闻" if "全球新闻" in m.tags else classify_event(m.content)),
        "cross_sector_type": m.extra.get("cross_sector_type", ""),
        "global_news_sector": m.extra.get("global_news_sector", ""),
    }


def analyze_and_summarize(all_mentions):
    """Run VADER sentiment analysis and generate structured summary."""
    analyzer = create_crypto_vader()
    results = []
    symbol_scores = defaultdict(list)
    category_items = defaultdict(list)

    for m in all_mentions:
        scores = analyzer.polarity_scores(m.content)
        compound = scores["compound"]
        engagement = m.upvotes * 3 + m.reposts * 2 + m.replies
        category = classify_event(m.content)

        entry = _mention_to_dict(m, compound)
        entry["engagement"] = engagement
        results.append(entry)

        symbol_scores[m.symbol].append(compound)
        category_items[category].append(entry)

    # Symbol averages
    symbol_avg = {}
    for sym, vals in symbol_scores.items():
        symbol_avg[sym] = {
            "avg": round(sum(vals) / len(vals), 4),
            "count": len(vals),
            "bullish": sum(1 for v in vals if v > 0.05),
            "bearish": sum(1 for v in vals if v < -0.05),
            "neutral": sum(1 for v in vals if -0.05 <= v <= 0.05),
        }

    # Event clusters
    events = []
    for cat, items in category_items.items():
        exa_items = [i for i in items if i["platform"] in ("exa", "news")]
        x_items = [i for i in items if i["platform"] == "x"]
        avg_sent = sum(i["sentiment_score"] for i in items) / len(items) if items else 0
        total_eng = sum(i["engagement"] for i in items)

        # Top sources by engagement
        top_sources = sorted(items, key=lambda x: x["engagement"], reverse=True)[:5]

        events.append({
            "category": cat,
            "count": len(items),
            "exa_count": len(exa_items),
            "x_count": len(x_items),
            "avg_sentiment": round(avg_sent, 4),
            "total_engagement": total_eng,
            "top_sources": [
                {"author": s["author"], "content": s["content"][:200], "url": s["url"],
                 "sentiment": s["sentiment_score"], "platform": s["platform"]}
                for s in top_sources
            ],
        })

    events.sort(key=lambda x: (x["exa_count"] + x["x_count"], x["total_engagement"]), reverse=True)

    # Overall stats
    x_count = sum(1 for r in results if r["platform"] == "x")
    exa_count = sum(1 for r in results if r["platform"] in ("exa", "news"))
    weex_official_count = sum(1 for r in results if r["platform"] == "weex_official")
    all_sentiments = [r["sentiment_score"] for r in results]
    overall_avg = sum(all_sentiments) / len(all_sentiments) if all_sentiments else 0
    bullish_pct = sum(1 for s in all_sentiments if s > 0.05) / len(all_sentiments) * 100 if all_sentiments else 0
    bearish_pct = sum(1 for s in all_sentiments if s < -0.05) / len(all_sentiments) * 100 if all_sentiments else 0

    # WEEX activities (from weex_official platform + WEEX-category items)
    weex_items = [r for r in results if r["platform"] == "weex_official" or r.get("category") == "WEEX动态"]
    weex_activities = [
        {"title": item["content"][:200], "url": item.get("url", ""), "platform": item["platform"],
         "author": item["author"], "sentiment": item["sentiment_score"]}
        for item in weex_items[:10]
    ]

    # Gossip highlights
    gossip_items = [r for r in results if r.get("category") == "币圈八卦"]
    gossip_items.sort(key=lambda x: x.get("engagement", 0), reverse=True)
    gossip_highlights = [
        {"content": item["content"][:300], "url": item.get("url", ""), "platform": item["platform"],
         "author": item["author"], "sentiment": item["sentiment_score"], "engagement": item.get("engagement", 0)}
        for item in gossip_items[:8]
    ]

    # Hot topics
    hot_items = [r for r in results if r.get("category") == "币圈热点"]
    hot_items.sort(key=lambda x: x.get("engagement", 0), reverse=True)
    hot_topics = [
        {"content": item["content"][:300], "url": item.get("url", ""), "platform": item["platform"],
         "author": item["author"], "sentiment": item["sentiment_score"], "engagement": item.get("engagement", 0)}
        for item in hot_items[:8]
    ]

    # Cross-sector highlights (跨圈热点)
    cross_sector_items = [r for r in results if r.get("category") == "跨圈热点"]
    cross_sector_items.sort(key=lambda x: x.get("engagement", 0), reverse=True)
    cross_sector_highlights = [
        {"content": item["content"][:300], "url": item.get("url", ""), "platform": item["platform"],
         "author": item["author"], "sentiment": item["sentiment_score"], "engagement": item.get("engagement", 0),
         "cross_sector_type": item.get("cross_sector_type", "")}
        for item in cross_sector_items[:8]
    ]

    # Macro finance highlights (宏观财经)
    macro_items = [r for r in results if "宏观财经" in r.get("tags", [])]
    macro_items.sort(key=lambda x: x.get("engagement", 0), reverse=True)
    macro_finance_highlights = [
        {"content": item["content"][:300], "url": item.get("url", ""), "platform": item["platform"],
         "author": item["author"], "sentiment": item["sentiment_score"], "engagement": item.get("engagement", 0),
         "created_at": item.get("created_at", "")}
        for item in macro_items[:10]
    ]

    # Global news highlights (全球新闻) — grouped by sector
    global_items = [r for r in results if "全球新闻" in r.get("tags", [])]
    global_items.sort(key=lambda x: x.get("engagement", 0), reverse=True)
    global_news_highlights = [
        {"content": item["content"][:300], "url": item.get("url", ""), "platform": item["platform"],
         "author": item["author"], "sentiment": item["sentiment_score"], "engagement": item.get("engagement", 0),
         "created_at": item.get("created_at", ""), "sector": item.get("extra", {}).get("global_news_sector", "全球热门") if isinstance(item.get("extra"), dict) else "全球热门"}
        for item in global_items[:20]
    ]

    # ── US Stock Earnings highlights (NEW per 优化.md 改造3) ──────────
    earnings_items = [r for r in results if "美股财报" in r.get("tags", [])]
    earnings_targets = get_targets_for_today()
    earnings_section = {
        "today": now_cst().strftime("%Y-%m-%d"),
        "forecast_targets": [
            {"name": s.name, "ticker": s.ticker, "earnings_date": s.earnings_date,
             "weex_token": s.weex_token, "weex_url": s.weex_url}
            for s in earnings_targets["forecast"]
        ],
        "actual_targets": [
            {"name": s.name, "ticker": s.ticker, "earnings_date": s.earnings_date,
             "weex_token": s.weex_token, "weex_url": s.weex_url}
            for s in earnings_targets["actual"]
        ],
        "forecast_sources": [
            {"ticker": item.get("symbol", ""), "content": item["content"][:400],
             "url": item.get("url", ""), "author": item["author"],
             "created_at": item.get("created_at", "")}
            for item in earnings_items if "财报预告" in item.get("tags", [])
        ],
        "actual_sources": [
            {"ticker": item.get("symbol", ""), "content": item["content"][:400],
             "url": item.get("url", ""), "author": item["author"],
             "created_at": item.get("created_at", "")}
            for item in earnings_items if "财报实际" in item.get("tags", [])
        ],
        "price_sources": [
            {"ticker": item.get("symbol", ""), "content": item["content"][:400],
             "url": item.get("url", ""), "author": item["author"],
             "created_at": item.get("created_at", "")}
            for item in earnings_items if "股价变动" in item.get("tags", [])
        ],
    }

    # Compute actual coverage period from data timestamps (Beijing time, last 48h window)
    now_dt = now_cst()
    cutoff_coverage = now_dt - timedelta(hours=48)
    timestamps = []
    for r in results:
        ca = r.get("created_at", "")
        if ca:
            try:
                from dateutil.parser import parse as dtparse
                ts = dtparse(ca)
                # Convert to CST for display
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                ts_cst = ts.astimezone(CST)
                if ts_cst > cutoff_coverage:
                    timestamps.append(ts_cst)
            except Exception:
                pass
    if timestamps:
        earliest = min(timestamps).strftime('%Y-%m-%d %H:%M')
        latest = max(timestamps).strftime('%Y-%m-%d %H:%M')
    else:
        earliest = (now_dt - timedelta(hours=30)).strftime('%Y-%m-%d %H:%M')
        latest = now_dt.strftime('%Y-%m-%d %H:%M')

    summary = {
        "generated_at": now_cst().isoformat(),
        "generated_at_cst": now_cst().strftime("%Y-%m-%d %H:%M:%S CST (UTC+8)"),
        "coverage_period": f"{earliest} — {latest} CST (UTC+8)",
        "freshness_window_hours": 48,
        "timezone": "Asia/Shanghai (UTC+8)",
        "stats": {
            "total_mentions": len(results),
            "x_count": x_count,
            "exa_count": exa_count,
            "weex_official_count": weex_official_count,
            "overall_sentiment_avg": round(overall_avg, 4),
            "bullish_pct": round(bullish_pct, 1),
            "bearish_pct": round(bearish_pct, 1),
            "neutral_pct": round(100 - bullish_pct - bearish_pct, 1),
        },
        "symbol_breakdown": symbol_avg,
        "event_clusters": events,
        "weex_activities": weex_activities,
        "gossip_highlights": gossip_highlights,
        "hot_topics": hot_topics,
        "cross_sector_highlights": cross_sector_highlights,
        "macro_finance_highlights": macro_finance_highlights,
        "global_news_highlights": global_news_highlights,
        "earnings_section": earnings_section,
    }

    return results, summary


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-raw", type=str, help="Regenerate summary from existing raw JSON")
    args = parser.parse_args()

    now = now_cst()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H%M%S")
    out_dir = LOG_ROOT / date_str
    out_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Beijing time (UTC+8): %s", now.strftime("%Y-%m-%d %H:%M:%S"))

    if args.from_raw:
        logger.info("Loading from existing raw JSON: %s", args.from_raw)
        # For --from-raw, we'd need to reconstruct RawMention objects
        # For now, just print a message
        logger.info("Use the raw JSON directly with Claude for analysis.")
        return

    logger.info("=== WEEX Sentinel Data Collector ===")

    logger.info("Step 1/3: Collecting data...")
    all_mentions = collect_all_mentions()
    if not all_mentions:
        logger.error("No mentions collected. Exiting.")
        sys.exit(1)
    logger.info("Total mentions collected: %d", len(all_mentions))

    # Hard cutoff: drop any mention older than 48h (Beijing time) to guarantee freshness
    cutoff_48h = (datetime.now(timezone.utc) - timedelta(hours=48)).replace(tzinfo=None)
    before_filter = len(all_mentions)
    # Normalize m.created_at to naive UTC for safe comparison
    all_mentions = [m for m in all_mentions if (m.created_at.replace(tzinfo=None) if m.created_at.tzinfo else m.created_at) >= cutoff_48h]
    dropped = before_filter - len(all_mentions)
    if dropped:
        logger.info("Freshness filter: dropped %d stale items (>48h), keeping %d", dropped, len(all_mentions))

    # WEEX source filter (per 优化.md 改造点4): WEEX channels are 二手 sources
    # Keep platform=weex_official (routed to Ch6 only), drop weex.com URLs from other collectors
    before_weex = len(all_mentions)
    all_mentions, weex_dropped = filter_weex_sources(all_mentions, allow_weex_official_platform=True)
    if weex_dropped:
        logger.info("WEEX source filter: dropped %d items citing WEEX as source, keeping %d",
                    weex_dropped, len(all_mentions))

    # Global deduplication (per 优化.md 改造点1): source_id + canonical URL + SimHash 0.75
    before_dedup = len(all_mentions)
    all_mentions, dedup_stats = dedup_mentions(all_mentions, similarity_threshold=0.75)
    logger.info(
        "Dedup: kept %d / %d (dropped sid=%d url=%d sim=%d)",
        dedup_stats["kept"], before_dedup,
        dedup_stats["dropped_by_source_id"],
        dedup_stats["dropped_by_url"],
        dedup_stats["dropped_by_similarity"],
    )

    logger.info("Step 2/3: Analyzing sentiment & generating summary...")
    results, summary = analyze_and_summarize(all_mentions)
    summary["dedup_stats"] = dedup_stats
    summary["weex_sources_dropped"] = weex_dropped

    logger.info("Step 3/3: Saving files...")

    raw_path = out_dir / f"{time_str}_raw.json"
    raw_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Raw JSON saved: %s", raw_path)

    summary_path = out_dir / f"{time_str}_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Summary JSON saved: %s", summary_path)

    print(f"\n✅ Data collected: {raw_path}")
    print(f"✅ Summary saved: {summary_path}")
    print(f"✅ Mentions: {len(results)} | Events: {len(summary['event_clusters'])} | Symbols: {len(summary['symbol_breakdown'])}")
    print(f"\n📋 Next step: Ask Claude to read {raw_path} and write the analysis report.")


if __name__ == "__main__":
    main()
