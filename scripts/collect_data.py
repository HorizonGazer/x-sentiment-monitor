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
from src.collectors.exa_search import ExaCollector
from src.collectors.base import RawMention
from src.sentiment.vader_crypto import create_crypto_vader

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

LOG_ROOT = Path(os.environ.get("SENTINEL_LOG_ROOT", "D:/download/x/x_sentiment_logs"))

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
        exa_mentions = exa_collector.collect_trending(limit=60)
        all_mentions.extend(exa_mentions)
        logger.info("Exa/News: collected %d mentions from authority sources", len(exa_mentions))
    except Exception as e:
        logger.error("Exa/News collection failed: %s", e)

    logger.info("Collecting X/Twitter data (corroboration)...")
    x_mentions = _collect_x_with_retry(limit=30)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
    x_filtered = [m for m in x_mentions if m.created_at >= cutoff]
    if len(x_filtered) < len(x_mentions):
        logger.info("X/Twitter: filtered %d old tweets, keeping %d",
                     len(x_mentions) - len(x_filtered), len(x_filtered))
    all_mentions.extend(x_filtered)
    return all_mentions


def fmt_dt(dt):
    if dt.tzinfo is None:
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    return dt.strftime("%Y-%m-%dT%H:%M:%S%z")


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


def _mention_to_dict(m, compound, category):
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
        "category": category,
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

        entry = _mention_to_dict(m, compound, category)
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
    all_sentiments = [r["sentiment_score"] for r in results]
    overall_avg = sum(all_sentiments) / len(all_sentiments) if all_sentiments else 0
    bullish_pct = sum(1 for s in all_sentiments if s > 0.05) / len(all_sentiments) * 100 if all_sentiments else 0
    bearish_pct = sum(1 for s in all_sentiments if s < -0.05) / len(all_sentiments) * 100 if all_sentiments else 0

    summary = {
        "generated_at": datetime.now().isoformat(),
        "coverage_period": f"{(datetime.now() - timedelta(hours=30)).strftime('%Y-%m-%d %H:%M')} — {datetime.now().strftime('%Y-%m-%d %H:%M')} UTC+8",
        "stats": {
            "total_mentions": len(results),
            "x_count": x_count,
            "exa_count": exa_count,
            "overall_sentiment_avg": round(overall_avg, 4),
            "bullish_pct": round(bullish_pct, 1),
            "bearish_pct": round(bearish_pct, 1),
            "neutral_pct": round(100 - bullish_pct - bearish_pct, 1),
        },
        "symbol_breakdown": symbol_avg,
        "event_clusters": events,
    }

    return results, summary


# ---------------------------------------------------------------------------
#  Post-processing: deduplication + spam filtering
# ---------------------------------------------------------------------------

# Language path prefixes commonly used by crypto news sites for translated versions
_LANG_PREFIX_RE = re.compile(
    r"^(https?://[^/]+)/(?:nl|fr|pl|es|zh|sl|et|it|uk)(/.*)",
    re.IGNORECASE,
)

# Domains known to publish multi-language mirrors under /<lang>/ paths
_MULTILANG_DOMAINS = {
    "bitcoin.com", "www.bitcoin.com",
    "coindesk.com", "www.coindesk.com",
    "cointelegraph.com", "www.cointelegraph.com",
    "decrypt.co", "www.decrypt.co",
    "beincrypto.com", "www.beincrypto.com",
}

# Spam keyword patterns (case-insensitive)
_SPAM_KEYWORDS = re.compile(
    r"\b(?:airdrop|claim\s+(?:your|now|free)|drop\s+your\s+wallet|fcfs"
    r"|giveaway|whitelist\s+spot|free\s+tokens?)\b",
    re.IGNORECASE,
)

# Engagement-farming step patterns ("step 1 ... step 2 ..." with wallet/airdrop language)
_STEP_PATTERN = re.compile(
    r"step\s*[12].*(?:wallet|airdrop|follow|retweet|rt\b)",
    re.IGNORECASE | re.DOTALL,
)
_FOLLOW_RT_PATTERN = re.compile(
    r"follow\s*[\+\&]\s*(?:retweet|rt\b)",
    re.IGNORECASE,
)

# Authority news sources whose airdrop coverage should NOT be filtered
_AUTHORITY_SOURCES = {
    "cointelegraph", "coindesk", "theblock", "decrypt", "beincrypto",
    "bitcoinmagazine", "bloomberg", "reuters", "coinpost", "blockworks",
    "thedefiant", "dlnews",
}


def _normalize_exa_url(url: str) -> str:
    """Strip language path prefix from known multi-language news domains."""
    if not url:
        return url
    m = _LANG_PREFIX_RE.match(url)
    if m:
        from urllib.parse import urlparse
        domain = urlparse(url).hostname or ""
        if domain in _MULTILANG_DOMAINS:
            return m.group(1) + m.group(2)
    # Also strip trailing slashes for more reliable dedup
    return url.rstrip("/")


def _is_authority_source(entry: dict) -> bool:
    """Check if the entry is from a trusted news source."""
    author = (entry.get("author") or "").lower().replace(" ", "")
    url = (entry.get("url") or "").lower()
    for src in _AUTHORITY_SOURCES:
        if src in author or src in url:
            return True
    return False


def _is_spam_tweet(entry: dict) -> bool:
    """Return True if the tweet looks like airdrop/engagement-farming spam."""
    content = entry.get("content", "")
    if _SPAM_KEYWORDS.search(content):
        return True
    if _FOLLOW_RT_PATTERN.search(content):
        return True
    if _STEP_PATTERN.search(content):
        return True
    return False


def post_process(results: list) -> tuple:
    """
    Post-process analyzed results:
      1. Deduplicate multi-language Exa/news articles (keep English / first seen)
      2. Deduplicate exact same tweet URLs from X
      3. Remove spam tweets (airdrop bots, engagement farming)

    Returns:
      (filtered_results, filter_stats)  where filter_stats is a dict
    """
    before_count = len(results)
    dedup_removed = 0
    spam_removed = 0

    # --- Pass 1: Deduplication ---------------------------------------------------
    seen_urls = {}          # normalized_url -> index of kept entry
    kept = []

    for entry in results:
        url = entry.get("url") or ""
        platform = entry.get("platform", "")

        if platform in ("exa", "news"):
            norm = _normalize_exa_url(url)
        else:
            # X/Twitter: exact URL dedup (strip trailing slash only)
            norm = url.rstrip("/") if url else ""

        if norm and norm in seen_urls:
            dedup_removed += 1
            continue

        if norm:
            seen_urls[norm] = len(kept)
        kept.append(entry)

    # --- Pass 2: Spam filtering (X/Twitter only) ---------------------------------
    final = []
    for entry in kept:
        platform = entry.get("platform", "")
        if platform == "x":
            if _is_spam_tweet(entry) and not _is_authority_source(entry):
                spam_removed += 1
                continue
        final.append(entry)

    after_count = len(final)
    filter_stats = {
        "before_total": before_count,
        "after_total": after_count,
        "removed_total": before_count - after_count,
        "dedup_removed": dedup_removed,
        "spam_removed": spam_removed,
        "details": (
            f"Removed {dedup_removed} duplicate articles (multi-lang mirrors / same tweet URL) "
            f"and {spam_removed} spam tweets (airdrop bots / engagement farming)"
        ),
    }

    logger.info(
        "Post-processing: %d → %d  (dedup -%d, spam -%d)",
        before_count, after_count, dedup_removed, spam_removed,
    )

    return final, filter_stats


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-raw", type=str, help="Regenerate summary from existing raw JSON")
    args = parser.parse_args()

    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H%M%S")
    out_dir = LOG_ROOT / date_str
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.from_raw:
        logger.info("Loading from existing raw JSON: %s", args.from_raw)
        raw_data = json.loads(Path(args.from_raw).read_text(encoding="utf-8"))
        logger.info("Loaded %d entries from raw JSON", len(raw_data))
        filtered, filter_stats = post_process(raw_data)
        analyzer = create_crypto_vader()
        symbol_scores = defaultdict(list)
        category_items = defaultdict(list)
        for entry in filtered:
            compound = entry.get("sentiment_score", 0)
            sym = entry.get("symbol", "UNKNOWN")
            cat = entry.get("category", "市场动态")
            symbol_scores[sym].append(compound)
            category_items[cat].append(entry)
        symbol_avg = {}
        for sym, vals in symbol_scores.items():
            symbol_avg[sym] = {
                "avg": round(sum(vals) / len(vals), 4),
                "count": len(vals),
                "bullish": sum(1 for v in vals if v > 0.05),
                "bearish": sum(1 for v in vals if v < -0.05),
                "neutral": sum(1 for v in vals if -0.05 <= v <= 0.05),
            }
        all_sentiments = [e.get("sentiment_score", 0) for e in filtered]
        overall_avg = sum(all_sentiments) / len(all_sentiments) if all_sentiments else 0
        bullish_pct = sum(1 for s in all_sentiments if s > 0.05) / len(all_sentiments) * 100 if all_sentiments else 0
        bearish_pct = sum(1 for s in all_sentiments if s < -0.05) / len(all_sentiments) * 100 if all_sentiments else 0
        summary = {
            "generated_at": datetime.now().isoformat(),
            "regenerated_from": args.from_raw,
            "stats": {
                "total_mentions": len(filtered),
                "x_count": sum(1 for e in filtered if e.get("platform") == "x"),
                "exa_count": sum(1 for e in filtered if e.get("platform") in ("exa", "news")),
                "overall_sentiment_avg": round(overall_avg, 4),
                "bullish_pct": round(bullish_pct, 1),
                "bearish_pct": round(bearish_pct, 1),
                "neutral_pct": round(100 - bullish_pct - bearish_pct, 1),
            },
            "symbol_breakdown": symbol_avg,
            "filtered": filter_stats,
        }
        summary_path = out_dir / f"{time_str}_summary.json"
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n✅ Summary regenerated: {summary_path}")
        return

    logger.info("=== WEEX Sentinel Data Collector ===")

    logger.info("Step 1/4: Collecting data...")
    all_mentions = collect_all_mentions()
    if not all_mentions:
        logger.error("No mentions collected. Exiting.")
        sys.exit(1)
    logger.info("Total mentions collected: %d", len(all_mentions))

    logger.info("Step 2/4: Analyzing sentiment & generating summary...")
    results, summary = analyze_and_summarize(all_mentions)

    logger.info("Step 3/4: Post-processing (dedup + spam filter)...")
    results, filter_stats = post_process(results)
    summary["filtered"] = filter_stats

    logger.info("Step 4/4: Saving files...")

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
