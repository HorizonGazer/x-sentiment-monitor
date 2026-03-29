#!/usr/bin/env python3
"""
WEEX Sentinel - Crypto Sentiment Final Report Generator (v2)

Scrapes X/Twitter via Playwright, collects news via ExaCollector,
runs VADER sentiment analysis, and generates a commercial-grade markdown report.
Collects fresh data each run for the last 24 hours.
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

# ── Constants ──

LOG_ROOT = Path("D:/download/x/x_sentiment_logs")

EVENT_CATEGORIES = {
    "爆仓": ["liquidat", "爆仓", "强平", "清算", "rekt", "margin call", "wipeout"],
    "监管": [
        "regulat",
        "sec ",
        "监管",
        "compliance",
        "lawsuit",
        "ban",
        "禁止",
        "legal",
        "法案",
        "legislation",
        "clarity",
        "cftc",
    ],
    "地缘政治": [
        "war",
        "geopolit",
        "sanction",
        "iran",
        "russia",
        "china",
        "tariff",
        "trump",
        "biden",
        "recession",
        "地缘",
        "战争",
        "制裁",
        "关税",
    ],
    "技术升级": [
        "upgrade",
        "fork",
        "layer",
        "rollup",
        "eip",
        "升级",
        "分叉",
        "L2",
        "L1",
        "protocol",
        "mainnet",
        "testnet",
        "pectra",
    ],
    "DeFi": [
        "defi",
        "swap",
        "liquidity",
        "yield",
        "staking",
        "tvl",
        "aave",
        "uniswap",
        "lido",
        "质押",
        "流动性",
        "stablecoin",
        "稳定币",
    ],
    "Meme": ["meme", "doge", "shib", "pepe", "bonk", "wif", "floki", "土狗"],
    "AI": [
        "ai ",
        " ai",
        "artificial intellig",
        "gpu",
        "agent",
        "openai",
        "chatgpt",
        "claude",
        "llm",
        "机器学习",
        "人工智能",
    ],
    "巨鲸": ["whale", "巨鲸", "大户", "accumul", "囤币", "大额转账", "transfer"],
    "ETF": ["etf", "spot etf", "grayscale", "blackrock", "fidelity", "ishares", "morgan stanley"],
    "交易所": [
        "exchange",
        "binance",
        "coinbase",
        "okx",
        "bybit",
        "weex",
        "listing",
        "上所",
        "上币",
        "delist",
    ],
    "宏观经济": [
        "fed ",
        "fomc",
        "cpi",
        "inflation",
        "interest rate",
        "gdp",
        "employment",
        "美联储",
        "通胀",
        "利率",
        "降息",
        "加息",
    ],
    "安全事件": [
        "hack",
        "exploit",
        "breach",
        "vulnerability",
        "漏洞",
        "被盗",
        "黑客",
        "attack",
        "stolen",
    ],
    "价格走势": [
        "price",
        "ath",
        "pump",
        "dump",
        "rally",
        "crash",
        "surge",
        "plunge",
        "breakout",
        "暴涨",
        "暴跌",
        "突破",
        "新高",
    ],
}

WEEX_PERSPECTIVES = {
    "爆仓": "大规模清算往往标志着杠杆出清阶段。WEEX 建议用户关注资金费率回归正常化的时间窗口，合理控制仓位杠杆倍数，利用 WEEX 的止盈止损工具管理风险敞口。",
    "监管": "监管框架落地是双刃剑——短期冲击估值，但长期为机构入场扫清法律障碍。WEEX 持续跟踪全球主要司法管辖区的政策变化，建议用户关注合规交易所的优势。",
    "地缘政治": "地缘冲突通常引发短期避险情绪。WEEX 提供黄金/原油等 TradFi 合约，用户可通过多资产对冲分散风险。",
    "技术升级": "协议升级是基本面改善的核心驱动力。WEEX 建议关注升级前后的链上数据变化，技术升级往往带来中期价值重估机会。",
    "DeFi": "DeFi 协议的 TVL 和收益率变化是链上资金流向的风向标。WEEX 支持主流 DeFi 代币的现货和合约交易。",
    "Meme": "Meme 币行情波动剧烈。WEEX 提醒用户严格控制 Meme 币仓位占比，设置止损，避免 FOMO 情绪主导决策。",
    "AI": "AI + Crypto 赛道持续获得资本和社区关注。WEEX 已上线多个 AI 概念代币，同时探索 AI 辅助交易工具。",
    "巨鲸": "巨鲸动向是市场资金流向的领先指标。散户出逃 + 机构吸筹 = 经典的底部换手结构。WEEX 的实时行情工具可帮助用户第一时间捕捉异动。",
    "ETF": "ETF 资金流入/流出是机构情绪的直接体现。现货 ETF 的持续净流入对中长期价格构成支撑。",
    "交易所": "交易所动态直接影响代币流动性。WEEX 的快速上币机制确保用户不错过热点。",
    "宏观经济": "宏观经济数据是加密市场的外部定价锚。WEEX 建议用户在重要数据发布前适当降低杠杆。",
    "安全事件": "安全事件是行业信任度的最大威胁。WEEX 采用多重签名冷钱包、实时风控系统和 1000 BTC 保护基金。",
    "价格走势": "WEEX 提供专业 K 线工具、深度图和实时资金费率数据，帮助用户做出更理性的交易决策。",
}


# ── Helpers (unchanged logic) ──


def classify_event(text):
    text_lower = text.lower()
    scores = {}
    for cat, keywords in EVENT_CATEGORIES.items():
        score = sum(1 for kw in keywords if kw.lower() in text_lower)
        if score > 0:
            scores[cat] = score
    if not scores:
        return "\u5e02\u573a\u52a8\u6001"
    return max(scores, key=scores.get)


def severity_label(compound, engagement):
    if abs(compound) > 0.6 and engagement > 500:
        return "\U0001f534 \u9ad8"
    elif abs(compound) > 0.3 or engagement > 200:
        return "\U0001f7e1 \u4e2d"
    return "\U0001f7e2 \u4f4e"


def fmt_dt(dt):
    if dt.tzinfo is None:
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    return dt.strftime("%Y-%m-%dT%H:%M:%S%z")


def sentiment_emoji(compound):
    if compound > 0.3:
        return "\U0001f7e2 \u5f3a\u70c8\u770b\u6da8"
    elif compound > 0.05:
        return "\U0001f7e2 \u6e29\u548c\u770b\u6da8"
    elif compound > -0.05:
        return "\u26aa \u4e2d\u6027"
    elif compound > -0.3:
        return "\U0001f534 \u6e29\u548c\u770b\u8dcc"
    return "\U0001f534 \u5f3a\u70c8\u770b\u8dcc"


def overall_sentiment_text(results):
    if not results:
        return "\u6570\u636e\u4e0d\u8db3"
    avg = sum(r["compound"] for r in results) / len(results)
    bullish = sum(1 for r in results if r["compound"] > 0.05)
    bearish = sum(1 for r in results if r["compound"] < -0.05)
    neutral = len(results) - bullish - bearish
    if avg > 0.1:
        return f"\u504f\u5411\u4e50\u89c2\uff08\u79ef\u6781 {bullish} / \u8c28\u614e {bearish} / \u4e2d\u6027 {neutral}\uff09"
    elif avg > -0.1:
        return f"\u4e2d\u6027\u504f\u8c28\u614e\uff08\u79ef\u6781 {bullish} / \u8c28\u614e {bearish} / \u4e2d\u6027 {neutral}\uff09"
    return f"\u504f\u7a7a\u8c28\u614e\uff08\u79ef\u6781 {bullish} / \u8c28\u614e {bearish} / \u4e2d\u6027 {neutral}\uff09"


def _safe(text, maxlen=120):
    return text[:maxlen].replace("\n", " ").replace("|", "\\|").strip()


# ── Content Cleaning ──

_NOISE_PATTERNS = [
    r"Oops,?\s*something went wrong",
    r"×\s*Bitcoin Magazine.*?(?=\w{3,})",
    r"Compartir este art[ií]culo.*?(?=\w{3,})",
    r"Bagikan artikel ini.*?(?=\w{3,})",
    r"Share this article.*?(?=\w{3,})",
    r"Salin tautan.*?(?=\w{3,})",
    r"Copiar enlace.*?(?=\w{3,})",
    r"Copy link.*?(?=\w{3,})",
    r"X \(Twitter\) LinkedIn Facebook (Email|Correo electr[oó]nico)",
    r"News Bitcoin Magazine Portfolio Tracker & Media Get it",
    r"Facebook Instagram Linkedin Rumble Twitter Youtube",
    r"Press Releases - Submit a press release - Read All",
    r"No Result View All Result",
    r"AD Active Currencies:.*?(?=\w{5,})",
    r"Ecosystem English",
    r"#\s*$",
    r"\s*##\s*$",
    r"Pasar\s+Bagikan\s+Bagikan",
    r"Mercados\s+Compartir\s+Compartir",
    r"Markets\s+Share\s+Share",
    r"NEWS\s*-\s*BUSINESS",
    r"Bitcoin\s*-\s*News\s*-\s*Price\s*-\s*Businesses\s*-\s*Acceptance",
    r"Market Cap:\s*\$[\d.]+[TMBK]?\s*Bitcoin Dominance:\s*[\d.]+%\s*24h Market Cap Change:\s*\$[\d.\-]+",
    r"\w+\$[\d.]+\s+[\d.]+%\s*",
    r"Get it\s+Facebook",
    r"[A-Z]{2,5}-USD\s+[+\-]?[\d.]+%",
    r"Section Navigation\s+News",
    r"####\s+Latest News\s+Analysis\s+Neutral",
    r"Best Crypto Rankings in Real-Time Overview & Prices.*?(?=The reason|$)",
]
_NOISE_RE = re.compile("|".join(_NOISE_PATTERNS), re.IGNORECASE)


def _clean_content(text: str) -> str:
    text = _NOISE_RE.sub("", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    text = re.sub(r"^[\s·\-—|#]+", "", text).strip()
    return text


def _extract_article_title(content: str, url: str = "") -> str:
    """Extract the real article title from exa content (first sentence before period/repeats)."""
    if not content:
        return ""
    # exa content often starts with the title, then repeats it
    # Try to extract the first sentence (before first period or line break)
    cleaned = _clean_content(content)
    # Skip converter/listing pages
    if url and ("/convert/" in url or url.endswith("/coins/") or url.endswith("/meme/")):
        return ""
    # First line is usually the title
    first = cleaned.split(". ")[0].strip()
    # Remove trailing punctuation artifacts
    first = re.sub(r"\s*[|\\#\-–—]+\s*.*$", "", first).strip()
    if len(first) > 120:
        first = first[:117] + "..."
    if len(first) < 10:
        return ""
    return first


def _extract_key_facts(content: str) -> dict:
    """Extract concrete facts from article content: prices, percentages, entities, dates."""
    facts = {
        "prices": [],
        "percentages": [],
        "entities": [],
        "amounts": [],
        "key_phrases": [],
    }
    if not content:
        return facts

    # Extract price points with context
    for m in re.finditer(
        r'(?:(?:BTC|bitcoin|ETH|ethereum|XRP|SOL)\s+(?:at|to|below|above|near|around|hit|dropped?\s+to|rose?\s+to|reached?)\s+)?\$[\d,.]+[KkMmBb]?',
        content, re.I,
    ):
        val = m.group().strip()
        if len(val) > 5:
            facts["prices"].append(val)

    # Extract standalone dollar amounts with context
    for m in re.finditer(r'\$([\d,.]+)\s*([KkMmBbTt](?:illion|illion)?|[KkMmBb])\b', content):
        amount = f"${m.group(1)}{m.group(2).upper()}"
        facts["amounts"].append(amount)

    # Extract percentages with context
    for m in re.finditer(r'(?:\w+\s+){0,3}[\-+]?[\d,.]+%(?:\s+\w+){0,3}', content):
        pct = m.group().strip()
        if len(pct) > 3:
            facts["percentages"].append(pct)

    # Extract key entities
    entity_patterns = [
        r"(?:Morgan\s+Stanley|BlackRock|Fidelity|Grayscale|Vanguard|Goldman\s+Sachs)",
        r"(?:SEC|CFTC|Fed(?:eral\s+Reserve)?|FOMC|Treasury|Congress|Senate)",
        r"(?:Coinbase|Binance|Kraken|OKX|Bitwise|ARK\s+Invest|iShares)",
        r"(?:Paul\s+Atkins|Gary\s+Gensler|Cynthia\s+Lummis|Ray\s+Dalio|Trump)",
        r"(?:Ripple|Lido|Hyperliquid|Aave|Uniswap|Ethena)",
        r"(?:CLARITY\s+Act|GENIUS\s+Act)",
    ]
    for pat in entity_patterns:
        for m in re.finditer(pat, content, re.I):
            entity = m.group().strip()
            if entity not in facts["entities"]:
                facts["entities"].append(entity)

    # Extract key informational phrases (sentences with numbers/entities)
    sentences = re.split(r'[.!?]\s+', content)
    for s in sentences[:20]:
        s = s.strip()
        if len(s) < 30 or len(s) > 300:
            continue
        has_number = bool(re.search(r'\$[\d,.]+|[\d,.]+%|\d+[KMBkmb]\b', s))
        has_entity = bool(re.search(r'(?:Morgan|BlackRock|SEC|ETF|Lido|Ripple|CLARITY|Fed|Trump|Coinbase)', s, re.I))
        if has_number or has_entity:
            clean_s = re.sub(r'\s+', ' ', s).strip()
            if clean_s not in facts["key_phrases"]:
                facts["key_phrases"].append(clean_s)

    for k in facts:
        facts[k] = list(dict.fromkeys(facts[k]))[:8]
    return facts


def _build_event_detail_text(exa_items: list) -> str:
    """Build data-driven event detail by actually reading exa sources."""
    all_facts = {"prices": [], "percentages": [], "entities": [], "amounts": [], "key_phrases": []}

    for ei in exa_items[:5]:
        em = ei["mention"]
        facts = _extract_key_facts(em.content)
        for k in all_facts:
            all_facts[k].extend(facts[k])

    for k in all_facts:
        all_facts[k] = list(dict.fromkeys(all_facts[k]))[:6]

    parts = []

    data_items = []
    if all_facts["prices"]:
        data_items.extend(all_facts["prices"][:3])
    if all_facts["amounts"]:
        data_items.extend(all_facts["amounts"][:3])
    if all_facts["percentages"]:
        data_items.extend(all_facts["percentages"][:3])
    if data_items:
        parts.append(f"**关键数据：** {' · '.join(data_items[:6])}")

    if all_facts["entities"]:
        parts.append(f"**涉及机构/人物：** {', '.join(all_facts['entities'][:5])}")

    if all_facts["key_phrases"]:
        parts.append("")
        parts.append("**信源要点摘录：**")
        parts.append("")
        for phrase in all_facts["key_phrases"][:4]:
            clean = _safe(phrase, 250)
            parts.append(f"- {clean}")

    return "\n".join(parts)


def _clean_author(author: str) -> str:
    author = re.sub(r"\s{2,}.*", "", author).strip()
    author = re.sub(r"\s+(Mon|Tue|Wed|Thu|Fri|Sat|Sun),?\s.*", "", author).strip()
    if len(author) > 30:
        author = author[:27] + "..."
    return author


def _normalize_url(url: str) -> str:
    normalized = re.sub(r"https?://(?:www\.)?", "", url)
    normalized = re.sub(r"/(id|es|zh|zh-CN|ja|ko|pt|fr|de|ru|tr|vi|ar)/", "/", normalized)
    return normalized.rstrip("/").lower()


def _dedup_exa_items(items: list) -> list:
    seen_urls = set()
    deduped = []
    # URL patterns that are not real articles (converter pages, price listings, etc.)
    junk_patterns = ["/convert/", "/coins/", "/cryptos/meme", "/quote/", "/news/$"]
    for item in items:
        m = item["mention"]
        url = m.url or ""
        norm = _normalize_url(url)
        if norm in seen_urls:
            continue
        # Skip junk pages
        if any(p in url.lower() for p in junk_patterns):
            continue
        seen_urls.add(norm)
        deduped.append(item)
    return deduped


# ── Collection & Analysis (unchanged) ──


def _collect_x_with_retry(limit: int = 30, max_retries: int = 2) -> list:
    """Collect X/Twitter data with retry on failure."""
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
    # Filter to only recent tweets (last 48h) — old tweets should not appear in daily reports
    cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
    x_filtered = [m for m in x_mentions if m.created_at >= cutoff]
    if len(x_filtered) < len(x_mentions):
        logger.info("X/Twitter: filtered %d old tweets (before %s), keeping %d",
                     len(x_mentions) - len(x_filtered), cutoff.isoformat(), len(x_filtered))
    all_mentions.extend(x_filtered)

    x_count = sum(1 for m in all_mentions if m.platform == "x")
    exa_count = sum(1 for m in all_mentions if m.platform in ("news", "exa"))
    logger.info("Collection complete: %d total (%d exa + %d x)", len(all_mentions), exa_count, x_count)
    return all_mentions


def analyze_sentiment(mentions):
    analyzer = create_crypto_vader()
    results = []
    symbol_scores = defaultdict(list)
    for m in mentions:
        scores = analyzer.polarity_scores(m.content)
        compound = scores["compound"]
        m.sentiment_raw = compound
        engagement = m.upvotes * 3 + m.reposts * 2 + m.replies
        category = classify_event(m.content)
        entry = {
            "mention": m,
            "compound": compound,
            "pos": scores["pos"],
            "neg": scores["neg"],
            "neu": scores["neu"],
            "engagement": engagement,
            "category": category,
            "severity": severity_label(compound, engagement),
        }
        results.append(entry)
        symbol_scores[m.symbol].append(compound)
    symbol_avg = {}
    for sym, vals in symbol_scores.items():
        symbol_avg[sym] = {
            "avg": sum(vals) / len(vals),
            "count": len(vals),
            "bullish": sum(1 for v in vals if v > 0.05),
            "bearish": sum(1 for v in vals if v < -0.05),
            "neutral": sum(1 for v in vals if -0.05 <= v <= 0.05),
        }
    results.sort(key=lambda x: x["engagement"], reverse=True)
    return results, symbol_avg


def _summarize_event_title(category, items):
    top = items[0]["mention"]
    content = top.content.lower()
    numbers = [
        n
        for n in re.findall(r"\$(\d[\d,.]{2,})[KMBkmb]?", top.content)
        if len(n.replace(",", "").replace(".", "")) >= 3
    ]
    num_str = f"${numbers[0]}" if numbers else ""

    title_map = {
        "\u7206\u4ed3": lambda: (
            f"\u5927\u89c4\u6a21\u6e05\u7b97\u6ce2\u53ca\u5e02\u573a\uff0c{num_str} \u591a\u5934\u7206\u4ed3"
            if num_str
            else "\u5e02\u573a\u7206\u4ed3\u6f6e\u5f15\u53d1\u6050\u614c"
        ),
        "\u76d1\u7ba1": lambda: _extract_regulation_title(top.content),
        "\u5730\u7f18\u653f\u6cbb": lambda: _extract_geopolitics_title(top.content),
        "\u6280\u672f\u5347\u7ea7": lambda: (
            f"\u534f\u8bae\u5347\u7ea7\u52a8\u6001\u5f15\u53d1\u5173\u6ce8"
        ),
        "DeFi": lambda: f"DeFi \u8d5b\u9053\u51fa\u73b0\u91cd\u8981\u53d8\u5316",
        "Meme": lambda: f"Meme \u5e01\u8d5b\u9053\u5f02\u52a8",
        "AI": lambda: f"AI + Crypto \u8d5b\u9053\u83b7\u5f97\u65b0\u5173\u6ce8",
        "\u5de8\u9cb8": lambda: _extract_whale_title(top.content, num_str),
        "ETF": lambda: _extract_etf_title(top.content, num_str),
        "\u4ea4\u6613\u6240": lambda: f"\u4ea4\u6613\u6240\u52a8\u6001\u66f4\u65b0",
        "\u5b8f\u89c2\u7ecf\u6d4e": lambda: (
            f"\u5b8f\u89c2\u7ecf\u6d4e\u6570\u636e\u5f71\u54cd\u5e02\u573a"
        ),
        "\u5b89\u5168\u4e8b\u4ef6": lambda: f"\u5b89\u5168\u4e8b\u4ef6\u8b66\u62a5",
        "\u4ef7\u683c\u8d70\u52bf": lambda: _extract_price_title(top.content, num_str),
    }
    fn = title_map.get(category)
    if fn:
        try:
            return fn()
        except Exception:
            pass
    cn_summary = _summarize_cn(top.content, category)
    if cn_summary and len(cn_summary) < 60:
        return cn_summary
    title = top.content.split(".")[0].strip()
    if len(title) > 60:
        title = title[:57] + "..."
    return f"{category}：{title}" if title else category


def _extract_regulation_title(content):
    c = content.lower()
    if "clarity" in c:
        return "CLARITY \u6cd5\u6848\u63a8\u8fdb\uff0c\u7a33\u5b9a\u5e01\u76d1\u7ba1\u6846\u67b6\u6210\u578b"
    if "sec" in c and "xrp" in c:
        return "SEC \u5c06 XRP \u5f52\u7c7b\u4e3a\u5546\u54c1"
    if "sec" in c:
        return "SEC \u76d1\u7ba1\u52a8\u6001\u66f4\u65b0"
    if "etf" in c.lower() and "approv" in c:
        return "\u52a0\u5bc6 ETF \u5ba1\u6279\u8fdb\u5c55"
    return "\u76d1\u7ba1\u653f\u7b56\u65b0\u52a8\u5411"


def _extract_geopolitics_title(content):
    c = content.lower()
    if "trump" in c and "bitcoin" in c:
        return "Trump \u53d1\u8868\u6bd4\u7279\u5e01\u79ef\u6781\u8a00\u8bba"
    if "trump" in c:
        return "Trump \u653f\u7b56\u52a8\u5411\u5f71\u54cd\u5e02\u573a"
    if "tariff" in c or "\u5173\u7a0e" in c:
        return "\u5173\u7a0e\u653f\u7b56\u53d8\u5316\u5f15\u53d1\u5e02\u573a\u6ce2\u52a8"
    return "\u5730\u7f18\u51b2\u7a81\u5347\u7ea7\u5f71\u54cd\u5e02\u573a"


def _extract_whale_title(content, num_str):
    if num_str:
        return f"\u5de8\u9cb8\u9006\u52bf\u5438\u7b79 {num_str} BTC\uff0c\u6563\u6237\u6301\u7eed\u51fa\u9003"
    return "\u5de8\u9cb8\u5f02\u52a8\uff1a\u5927\u989d\u8f6c\u8d26\u5f15\u53d1\u5173\u6ce8"


def _extract_etf_title(content, num_str):
    c = content.lower()
    if "morgan stanley" in c:
        return "Morgan Stanley \u4ee5\u8d85\u4f4e\u8d39\u7387\u5165\u5c40 BTC ETF"
    if "outflow" in c or "\u6d41\u51fa" in c:
        return f"BTC ETF \u6253\u7834\u6d41\u5165\u8d8b\u52bf\uff0c\u5355\u5468\u51c0\u6d41\u51fa"
    if num_str:
        return (
            f"BTC ETF \u8d44\u91d1\u6d41\u52a8\u5f02\u5e38\uff0c{num_str} \u89c4\u6a21\u53d8\u5316"
        )
    return "ETF \u8d44\u91d1\u6d41\u5411\u53d8\u5316\u5f15\u53d1\u5173\u6ce8"


def _extract_price_title(content, num_str):
    c = content.lower()
    if "btc" in c or "bitcoin" in c:
        if num_str:
            return f"BTC \u4ef7\u683c\u6ce2\u52a8\uff0c{num_str} \u5173\u53e3\u6210\u7126\u70b9"
        return "BTC \u4ef7\u683c\u5267\u70c8\u6ce2\u52a8"
    if num_str:
        return f"\u5e02\u573a\u4ef7\u683c\u5f02\u52a8\uff0c{num_str} \u6210\u5173\u952e\u6570\u636e"
    return "\u5e02\u573a\u4ef7\u683c\u8d70\u52bf\u53d8\u5316"


def cluster_events(results):
    clusters = defaultdict(list)
    for r in results:
        clusters[r["category"]].append(r)
    events = []
    for cat, items in clusters.items():
        exa_items = [i for i in items if i["mention"].platform == "exa"]
        x_items = [i for i in items if i["mention"].platform == "x"]
        exa_items.sort(key=lambda x: abs(x["compound"]), reverse=True)
        x_items.sort(key=lambda x: x["engagement"], reverse=True)
        total_engagement = sum(i["engagement"] for i in items)
        avg_sentiment = sum(i["compound"] for i in items) / len(items) if items else 0
        top_exa = exa_items[0]["mention"] if exa_items else None
        top_x = x_items[0]["mention"] if x_items else None
        top = top_exa or top_x or items[0]["mention"]
        title = _summarize_event_title(cat, items)
        events.append(
            {
                "category": cat,
                "title": title,
                "items": items,
                "exa_items": exa_items,
                "x_items": x_items,
                "total_engagement": total_engagement,
                "avg_sentiment": avg_sentiment,
                "top_mention": top,
                "top_exa": top_exa,
                "top_x": top_x,
                "severity": items[0]["severity"] if items else "🟢 低",
                "count": len(items),
                "exa_count": len(exa_items),
                "x_count": len(x_items),
            }
        )
    events.sort(key=lambda x: (x["exa_count"] + x["x_count"], x["total_engagement"]), reverse=True)
    return events


# ── V2 Report Generator ──


def _get_report_number():
    now = datetime.now()
    day_num = now.timetuple().tm_yday
    return f"WS-{now.year}-{now.strftime('%m%d')}-{day_num:03d}"


def _source_links(items):
    urls = []
    for item in items:
        m = item["mention"]
        if m.url and m.url.startswith("http"):
            domain = re.search(r"https?://(?:www\.)?([^/]+)", m.url)
            label = domain.group(1).split(".")[0].capitalize() if domain else "Source"
            urls.append(f"[{label}]({m.url})")
    seen = set()
    unique = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            unique.append(u)
        if len(unique) >= 4:
            break
    return " \u00b7 ".join(unique) if unique else "X/Twitter"


def _summarize_cn(content, category):
    c = content.lower()
    parts = []
    if "morgan stanley" in c and "etf" in c:
        parts.append("摩根士丹利以超低费率入局比特币 ETF 竞争")
    if "blackrock" in c and ("sell" in c or "outflow" in c):
        parts.append("贝莱德领衔 ETF 抛售潮")
    if "blackrock" in c and ("buy" in c or "inflow" in c or "accumul" in c):
        parts.append("贝莱德持续增持比特币 ETF")
    if "fidelity" in c and ("sell" in c or "outflow" in c):
        parts.append("富达基金出现 ETF 净流出")
    if "fidelity" in c and ("buy" in c or "inflow" in c):
        parts.append("富达基金加仓比特币 ETF")
    if "ripple" in c and "ai" in c:
        parts.append("Ripple 引入 AI 技术对 XRP 账本进行压力测试")
    if "bitcoin" in c and (
        "crash" in c or "drop" in c or "fall" in c or "low" in c or "slide" in c or "dip" in c
    ):
        nums = [
            n
            for n in re.findall(r"\$(\d[\d,]{3,})[kK]?", content)
            if int(n.replace(",", "")) >= 1000
        ]
        if nums:
            parts.append(f"BTC 价格跌至 ${nums[0]} 附近")
        else:
            parts.append("BTC 价格出现明显回调")
    if (
        "bitcoin" in c
        and (
            "surge" in c
            or "rally" in c
            or "soar" in c
            or "jump" in c
            or "all-time high" in c
            or "breakout" in c
        )
        and not (
            "drop" in c
            or "fall" in c
            or "crash" in c
            or "slide" in c
            or "dip" in c
            or "red month" in c
        )
    ):
        nums = [
            n
            for n in re.findall(r"\$(\d[\d,]{3,})[kK]?", content)
            if int(n.replace(",", "")) >= 1000
        ]
        if nums:
            parts.append(f"BTC 突破 ${nums[0]} 关口")
        else:
            parts.append("BTC 价格强势反弹")
    if "ethereum" in c and ("upgrade" in c or "pectra" in c or "dencun" in c):
        parts.append("以太坊协议升级推进中")
    if "ethereum" in c and ("drop" in c or "fall" in c or "low" in c):
        parts.append("ETH 价格承压下行")
    if "solana" in c and ("trap" in c or "cautious" in c or "drop" in c or "fall" in c):
        parts.append("SOL 陷入盘整区间，交易者保持谨慎")
    if "solana" in c and ("surge" in c or "rally" in c or "tps" in c):
        parts.append("Solana 生态活跃度提升")
    if "miner" in c and ("ai" in c or "sell" in c or "pressure" in c):
        parts.append("矿企面临盈利压力，加速转型 AI 业务")
    if "miner" in c and "profit" in c:
        parts.append("矿企盈利能力受到挤压")
    if "institution" in c and ("adopt" in c or "embed" in c or "enter" in c):
        parts.append("机构资金加速入场加密市场")
    if "conviction" in c or "long-term hold" in c or "hodl" in c:
        parts.append("长期持有者信心增强")
    if "oil" in c and ("fear" in c or "inflation" in c or "risk" in c):
        parts.append("原油价格波动加剧通胀担忧")
    if "trump" in c:
        if "tariff" in c or "关税" in c:
            parts.append("特朗普关税政策引发市场避险情绪")
        elif "bitcoin" in c or "crypto" in c:
            parts.append("特朗普就加密货币发表积极言论")
        else:
            parts.append("特朗普政策动向影响市场预期")
    if "sec" in c and "xrp" in c:
        parts.append("SEC 将 XRP 归类为商品，监管框架进一步明确")
    if "sec" in c and "commodity" in c:
        parts.append("SEC 加密资产分类标准更新")
    if "clarity" in c and ("act" in c or "bill" in c or "stablecoin" in c):
        parts.append("CLARITY 法案推进稳定币监管框架")
    if "coinbase" in c and ("stablecoin" in c or "reward" in c):
        parts.append("Coinbase 稳定币收益政策引发监管博弈")
    if "hyperliquid" in c:
        parts.append("Hyperliquid 平台政策动态")
    if "hack" in c or "exploit" in c or "stolen" in c:
        parts.append("安全事件引发市场担忧")
    if "whale" in c or ("accumul" in c and "institution" not in c):
        parts.append("巨鲸地址出现大额异动")
    if (
        "stablecoin" in c
        and ("regulat" in c or "clarity" in c or "framework" in c or "legislation" in c)
        and "clarity act" not in " ".join(parts).lower()
    ):
        parts.append("稳定币监管框架取得新进展")
    if "defi" in c and "tvl" in c:
        parts.append("DeFi 协议 TVL 出现显著变化")
    if "aave" in c or "uniswap" in c or "lido" in c:
        parts.append("头部 DeFi 协议出现重要动态")
    if "liquidat" in c or "rekt" in c:
        nums = re.findall(r"\$[\d,.]+[MBmb]?", content)
        if nums:
            parts.append(f"市场爆仓规模达 {nums[0]}")
        else:
            parts.append("大规模清算事件冲击市场")
    if "fed" in c or "fomc" in c:
        parts.append("美联储政策信号影响风险资产定价")
    if "rate cut" in c or "rate hike" in c or "interest rate" in c:
        parts.append("利率预期变化影响市场走势")
    if "cpi" in c or "inflation" in c and "oil" not in c:
        parts.append("通胀数据牵动市场神经")
    if "etf" in c and "inflow" in c:
        parts.append("ETF 资金持续流入")
    if "etf" in c and "outflow" in c:
        parts.append("ETF 资金出现净流出")
    if "etf" in c and ("race" in c or "compet" in c or "fee" in c or "launch" in c):
        parts.append("ETF 发行商竞争加剧")
    if "xlm" in c or "stellar" in c:
        parts.append("Stellar (XLM) 生态动态更新")
    if "red month" in c or "consecutive" in c and "loss" in c:
        parts.append("BTC 面临连续月线收阴压力")
    if "six" in c and "month" in c and "red" in c:
        parts.append("BTC 连续六个月收跌创纪录")

    unique_parts = list(dict.fromkeys(parts))
    if unique_parts:
        return "；".join(unique_parts[:3])

    cat_defaults = {
        "AI": "AI + Crypto 赛道出现新动态",
        "ETF": "ETF 市场格局发生变化",
        "价格走势": "加密市场价格出现显著波动",
        "监管": "监管政策出现新进展",
        "地缘政治": "地缘政治因素影响市场情绪",
        "技术升级": "区块链协议迎来技术升级",
        "DeFi": "DeFi 赛道出现重要变化",
        "Meme": "Meme 币板块异动明显",
        "巨鲸": "链上大额转账引发关注",
        "交易所": "交易所出现重要动态",
        "宏观经济": "宏观经济数据影响市场",
        "安全事件": "安全事件引发行业关注",
        "爆仓": "杠杆清算规模扩大",
    }

    title = content.split(".")[0].strip() if "." in content else content[:60].strip()
    default = cat_defaults.get(category, "市场出现新动态")
    if len(title) > 10 and len(title) < 80:
        return f"{default}（{title}）"
    return default


def _event_background(category: str) -> str:
    """Return contextual background for the event category."""
    backgrounds = {
        "爆仓": "杠杆清算是加密市场高波动性的典型表现。大规模爆仓通常发生在价格急剧波动时，过度杠杆化的头寸被强制平仓，形成「多杀多」或「空杀空」的连锁反应。历史数据显示，大规模清算事件往往标志着短期底部或顶部的形成。",
        "监管": "全球加密货币监管正处于从「灰色地带」向「制度化」转变的关键阶段。美国 SEC、CFTC 的政策走向直接影响市场预期。监管框架的明确化虽短期可能带来不确定性冲击，但长期将为机构资金入场扫清障碍。",
        "地缘政治": "地缘政治事件通过风险偏好渠道影响加密市场。传统避险情绪升温时，比特币的「数字黄金」叙事可能被强化；但若引发全面风险抛售，加密资产同样承压。关税、制裁等贸易政策变化对全球资金流动和通胀预期产生直接影响。",
        "技术升级": "区块链协议升级是基本面改善的核心驱动力。以太坊的 EIP 提案和 Layer 2 生态发展直接影响 Gas 费用、TPS 和开发者生态。成功的技术升级往往带来中期价值重估。",
        "DeFi": "去中心化金融（DeFi）是链上金融创新的核心阵地。TVL（总锁仓价值）、收益率和协议收入是衡量 DeFi 健康度的关键指标。头部协议的政策变化和安全事件对整个赛道具有风向标意义。",
        "Meme": "Meme 币板块以高波动性和社区驱动为特征，通常在市场情绪高涨时表现活跃。该板块的异动往往反映散户资金的活跃度和市场风险偏好的变化。",
        "AI": "AI 与加密货币的融合是当前最活跃的叙事之一。AI Agent、去中心化计算和数据市场等概念持续获得资本关注。该赛道的发展受益于 AI 技术进步和区块链基础设施的成熟。",
        "巨鲸": "链上巨鲸（持有大量加密资产的地址）的动向是市场资金流向的领先指标。巨鲸的集中买入或抛售行为往往预示着市场方向性变化，尤其是「散户出逃、机构吸筹」的结构性换手信号值得高度关注。",
        "ETF": "比特币现货 ETF 是机构资金入场的核心通道。ETF 的日/周资金流入流出数据是衡量机构情绪最直接的指标。ETF 竞争格局（费率、AUM、发行商）直接影响市场的中长期资金供给。",
        "交易所": "加密交易所是市场流动性的核心枢纽。交易所的上币、下币、费率调整、安全事件等直接影响相关代币的价格和流动性。交易所格局的变化反映行业竞争态势。",
        "宏观经济": "宏观经济数据（CPI、利率、就业）通过流动性和风险偏好渠道影响加密市场定价。美联储的货币政策是全球风险资产定价的锚，利率预期变化直接传导至加密市场。",
        "安全事件": "智能合约漏洞、黑客攻击和桥接协议被盗是 DeFi 生态面临的最大系统性风险。安全事件不仅造成直接经济损失，更严重侵蚀行业信任度，可能引发监管收紧。",
        "价格走势": "加密资产价格受多重因素驱动：链上数据（活跃地址、交易量）、资金流向（ETF、稳定币）、技术面（关键支撑/阻力位）和宏观面（利率、流动性）。价格的剧烈波动既是风险也是机会。",
    }
    return backgrounds.get(category, "该领域近期出现重要动态，值得持续关注其后续发展和市场影响。")


def _event_impact_analysis(category: str, avg_sentiment: float, engagement: int, exa_count: int, x_count: int) -> str:
    """Generate impact analysis text for an event."""
    # Determine impact magnitude
    if engagement > 1000 or exa_count > 5:
        magnitude = "高"
    elif engagement > 200 or exa_count > 2:
        magnitude = "中"
    else:
        magnitude = "低"

    # Determine sentiment direction
    if avg_sentiment > 0.15:
        direction = "积极"
        market_implication = "短期可能推动相关资产价格上行，但需警惕情绪过热后的回调风险"
    elif avg_sentiment > 0.05:
        direction = "温和积极"
        market_implication = "市场反应偏正面，但力度有限，建议观察后续资金流向确认"
    elif avg_sentiment > -0.05:
        direction = "中性分化"
        market_implication = "多空分歧较大，市场尚未形成一致预期，短期波动可能加大"
    elif avg_sentiment > -0.15:
        direction = "温和消极"
        market_implication = "市场情绪偏谨慎，建议降低杠杆、控制仓位，等待趋势明确"
    else:
        direction = "显著消极"
        market_implication = "恐慌情绪蔓延，短期可能继续承压，但超跌后或迎来反弹窗口"

    coverage = f"{exa_count} 家权威媒体报道"
    if x_count > 0:
        coverage += f"、{x_count} 条社区讨论"

    return (
        f"**影响程度：{magnitude}** · **市场情绪：{direction}（{avg_sentiment:+.3f}）**\n\n"
        f"该事件获得 {coverage}，总互动量 {engagement:,}。"
        f"{market_implication}。"
    )


def generate_report_v2(results, symbol_avg, events, all_mentions):
    now = datetime.now(timezone.utc)
    now_cst = now + timedelta(hours=8)
    now_str = now_cst.strftime("%Y-%m-%d %H:%M") + " (UTC+8)"
    yesterday = (now_cst - timedelta(days=1)).strftime("%Y-%m-%d")
    today = now_cst.strftime("%Y-%m-%d")
    report_num = _get_report_number()

    x_count = sum(1 for m in all_mentions if m.platform == "x")
    news_count = sum(1 for m in all_mentions if m.platform in ("news", "exa"))
    total_engagement = sum(r["engagement"] for r in results)
    sentiment_text = overall_sentiment_text(results)
    avg_compound = sum(r["compound"] for r in results) / max(len(results), 1)
    bullish = sum(1 for r in results if r["compound"] > 0.05)
    bearish = sum(1 for r in results if r["compound"] < -0.05)
    neutral = len(results) - bullish - bearish

    top_symbols = sorted(
        [(k, v) for k, v in symbol_avg.items() if k != "UNKNOWN"],
        key=lambda x: x[1]["count"],
        reverse=True,
    )[:8]
    sym_list = ", ".join(f"${s[0]}" for s in top_symbols[:6]) if top_symbols else "$BTC"

    L = []
    a = L.append

    # ════════════════════════════════════════════════════════════════
    # 封面
    # ════════════════════════════════════════════════════════════════
    a("# WEEX Sentinel 加密货币行业舆情研究报告")
    a("")
    a('<div align="center">')
    a("")
    a("**WEEX Exchange · Digital Asset Intelligence Division**")
    a("")
    a(f"报告编号：{report_num} | 密级：内部参考")
    a("")
    a(f"生成时间：{now_str} | 数据窗口：{yesterday} ~ {today}")
    a("")
    a("</div>")
    a("")
    a("---")
    a("")

    # ════════════════════════════════════════════════════════════════
    # 执行摘要 — 总览 + 结论
    # ════════════════════════════════════════════════════════════════
    a("## 执行摘要")
    a("")

    # 核心结论先行
    if avg_compound > 0.1:
        conclusion = "短期情绪偏多，但需警惕过热风险。建议关注关键支撑位和资金费率变化，适当止盈锁定收益。"
    elif avg_compound > -0.1:
        conclusion = "市场情绪分化，多空博弈加剧。建议控制仓位、降低杠杆倍数，等待方向确认后再加码。"
    else:
        conclusion = "短期恐慌性抛售明显，但机构资金动向值得关注。市场可能正处于「散户出逃、机构接盘」的转换期，超跌后或迎来反弹窗口。"

    a(f"> **核心结论：** {conclusion}")
    a("")

    # 数据总览
    a("### 数据总览")
    a("")
    a(f"本报告基于过去 24 小时内全网采集的 **{len(all_mentions)} 条**有效数据：")
    a("")
    a(f"- **Exa 权威来源：** {news_count} 条（CoinDesk、CoinTelegraph、Yahoo Finance、Reuters 等）")
    a(f"- **X/Twitter 社区：** {x_count} 条有效推文（经过垃圾信息过滤）")
    a(f"- **覆盖币种：** {len(symbol_avg)} 个")
    a(f"- **总互动量：** {total_engagement:,}")
    a(f"- **市场情绪：** {sentiment_text}")
    a(f"- **看多/看空/中性：** {bullish} / {bearish} / {neutral}（{bullish / max(len(results), 1) * 100:.0f}% / {bearish / max(len(results), 1) * 100:.0f}% / {neutral / max(len(results), 1) * 100:.0f}%）")
    a("")

    # 核心叙事线 — 按时间线理清事件内在逻辑
    a("### 核心叙事线")
    a("")

    # Group related categories and build narrative
    macro_cats = {"宏观经济", "地缘政治"}
    market_cats = {"价格走势", "ETF", "爆仓"}
    onchain_cats = {"巨鲸", "DeFi", "技术升级"}
    industry_cats = {"监管", "交易所", "安全事件"}

    macro_events = [e for e in events if e["category"] in macro_cats]
    market_events = [e for e in events if e["category"] in market_cats]
    onchain_events = [e for e in events if e["category"] in onchain_cats]
    industry_events = [e for e in events if e["category"] in industry_cats]

    thread_idx = 1
    if macro_events:
        titles = "、".join(f"「{e['title'][:25]}」" for e in macro_events[:2])
        a(f"**叙事线 {thread_idx}：宏观/地缘 → 风险偏好传导**")
        a("")
        a(f"  {titles}。宏观面的变化通过流动性和风险偏好渠道传导至加密市场。")
        if market_events:
            a(f"  → 直接影响：{'、'.join(e['category'] for e in market_events[:2])} 板块联动反应")
        a("")
        thread_idx += 1

    if market_events:
        titles = "、".join(f"「{e['title'][:25]}」" for e in market_events[:2])
        a(f"**叙事线 {thread_idx}：价格/资金 → 市场结构变化**")
        a("")
        a(f"  {titles}。价格走势与资金流向相互验证，反映市场结构性变化。")
        if onchain_events:
            a(f"  → 链上响应：{'、'.join(e['category'] for e in onchain_events[:2])} 数据同步异动")
        a("")
        thread_idx += 1

    if industry_events:
        titles = "、".join(f"「{e['title'][:25]}」" for e in industry_events[:2])
        a(f"**叙事线 {thread_idx}：行业/监管 → 合规化进程**")
        a("")
        a(f"  {titles}。行业基础设施和监管环境的变化影响中长期市场格局。")
        a("")
        thread_idx += 1

    remaining = [e for e in events if e["category"] not in macro_cats | market_cats | onchain_cats | industry_cats]
    if remaining:
        for e in remaining[:2]:
            a(f"**叙事线 {thread_idx}：{e['category']} — {e['title'][:30]}**")
            a("")
            thread_idx += 1

    a("")

    # 热点事件概览
    a("### 热点事件概览")
    a("")
    a("| # | 事件 | 分类 | 严重程度 | 情感 | 来源数 |")
    a("|---|---|---|---|---|---|")
    for idx, event in enumerate(events[:8], 1):
        title = event["title"]
        if len(title) > 40:
            title = title[:37] + "..."
        exa_n = event.get("exa_count", 0)
        x_n = event.get("x_count", 0)
        a(f"| {idx} | {title} | {event['category']} | {event['severity']} | {sentiment_emoji(event['avg_sentiment'])} | {exa_n}+{x_n} |")
    a("")

    # 币种情感一览
    a("### 币种情感一览")
    a("")
    a("| 关键指标 | 数值 |")
    a("|---|---|")
    for sym, data in top_symbols[:5]:
        direction = "看多" if data["avg"] > 0.05 else "看空" if data["avg"] < -0.05 else "中性"
        bar_len = min(int(abs(data["avg"]) * 20), 10)
        bar = "█" * bar_len + "░" * (10 - bar_len)
        a(
            f"| {sym} | {data['avg']:+.3f} {bar} {direction}（{data['count']} 条 · 多{data['bullish']}/空{data['bearish']}/中{data['neutral']}）|"
        )
    a("")
    a("---")
    a("")

    # ════════════════════════════════════════════════════════════════
    # 一、市场行情概览
    # ════════════════════════════════════════════════════════════════
    a("## 一、市场行情概览")
    a("")
    a("| 币种 | 讨论量 | 情感均值 | 方向 | 看多 | 看空 | 中性 |")
    a("|---|---|---|---|---|---|---|")
    for sym, data in top_symbols[:8]:
        direction = (
            "📈 看多" if data["avg"] > 0.05 else "📉 看空" if data["avg"] < -0.05 else "⚖️ 中性"
        )
        a(
            f"| ${sym} | {data['count']} | {data['avg']:+.3f} | {direction} | {data['bullish']} | {data['bearish']} | {data['neutral']} |"
        )
    a("")

    if top_symbols:
        hottest = top_symbols[0]
        a(f"**热搜币种：** {sym_list}")
        a(f"**讨论量最高：** ${hottest[0]}（{hottest[1]['count']} 条提及）")
        a("")

    # 市场情绪分析
    a("### 市场情绪分析")
    a("")
    bullish_pct = bullish / max(len(results), 1) * 100
    bearish_pct = bearish / max(len(results), 1) * 100
    neutral_pct = neutral / max(len(results), 1) * 100

    if avg_compound > 0.1:
        mood_desc = "市场整体情绪偏乐观。多方力量占据主导，看多信号明显高于看空信号。但历史经验表明，市场过热时需警惕短期回调风险。"
    elif avg_compound > 0:
        mood_desc = "市场情绪温和偏多。虽然多方略占上风，但力度有限，表明市场参与者对当前价位仍存在分歧。建议关注关键技术位的突破确认。"
    elif avg_compound > -0.1:
        mood_desc = "市场情绪偏中性，多空双方势均力敌。这种分化格局通常预示着市场即将选择方向，建议降低杠杆、分批建仓。"
    else:
        mood_desc = "市场情绪明显偏空，恐慌情绪有所蔓延。但极端恐慌往往也是逆向指标——当散户大面积出逃时，机构资金可能正在逆势布局。"

    a(f"综合 {len(results)} 条数据的 VADER 情感分析结果：看多 {bullish_pct:.0f}% · 看空 {bearish_pct:.0f}% · 中性 {neutral_pct:.0f}%。")
    a("")
    a(mood_desc)
    a("")
    a("---")
    a("")

    # ════════════════════════════════════════════════════════════════
    # 二、核心事件深度分析（独立、详细）
    # ════════════════════════════════════════════════════════════════
    a("## 二、核心事件深度分析")
    a("")

    for idx, event in enumerate(events[:8], 1):
        exa_items = _dedup_exa_items(event.get("exa_items", []))
        x_items = event.get("x_items", [])
        cat = event["category"]
        avg_s = event["avg_sentiment"]
        exa_n = event.get("exa_count", 0)
        x_n = event.get("x_count", 0)

        a(f"### 事件 {idx}：{event['title']}")
        a("")

        # ── 事件概况卡片 ──
        a("#### 事件概况")
        a("")
        a(f"| 维度 | 详情 |")
        a("|---|---|")
        a(f"| 分类 | {cat} |")
        a(f"| 严重程度 | {event['severity']} |")
        a(f"| 市场情感 | {sentiment_emoji(avg_s)}（{avg_s:+.3f}）|")
        a(f"| 信息来源 | 权威媒体 {exa_n} 条 · X/Twitter {x_n} 条 |")
        a(f"| 总互动量 | {event['total_engagement']:,} |")
        a("")

        # ── 背景分析 ──
        a("#### 背景")
        a("")
        a(_event_background(cat))
        a("")

        # ── 事件详情 ──
        a("#### 事件详情")
        a("")

        # 核心动态 — aggregate from ALL items in the cluster
        all_cluster_content = " ".join(item["mention"].content for item in event["items"][:10])
        cn_summary = _summarize_cn(all_cluster_content, cat)
        if not cn_summary or cn_summary == "稳定币监管框架取得新进展":
            for ei in exa_items[:3]:
                title = _extract_article_title(ei["mention"].content, ei["mention"].url or "")
                if title and len(title) > 15:
                    cn_summary = title
                    break
        if not cn_summary:
            cn_summary = event["title"]
        a(f"**核心动态：** {cn_summary}")
        a("")

        # Data-driven detail from exa sources
        detail_text = _build_event_detail_text(exa_items)
        if detail_text:
            a(detail_text)
            a("")

        # 权威资讯详情 — 精选 3 条，use real article titles
        if exa_items:
            a("**权威资讯来源：**")
            a("")
            for ei_idx, ei in enumerate(exa_items[:3], 1):
                em = ei["mention"]
                domain = re.search(r"https?://(?:www\.)?([^/]+)", em.url or "")
                dname = domain.group(1) if domain else em.author
                ts = fmt_dt(em.created_at)
                cleaned = _clean_content(em.content)
                article_title = _extract_article_title(em.content, em.url or "")
                if not article_title or len(article_title) < 15:
                    article_title = _safe(cleaned.split(".")[0], 100)
                a(f"{ei_idx}. **{article_title}** — [{dname}]({em.url})（{ts}）")
                content_preview = _safe(cleaned, 300)
                if len(content_preview) > 80:
                    a(f"   > {content_preview}")
            a("")

        # X/Twitter 社区声音 — 典型观点 2 条 + 综合总结 (deduped)
        if x_items:
            # Dedup by source_id
            seen_x_ids = set()
            x_deduped = []
            for xi in x_items:
                sid = xi["mention"].source_id
                if sid not in seen_x_ids:
                    seen_x_ids.add(sid)
                    x_deduped.append(xi)
            x_items = x_deduped

            x_bullish = sum(1 for xi in x_items if xi["compound"] > 0.05)
            x_bearish = sum(1 for xi in x_items if xi["compound"] < -0.05)
            x_neutral_count = len(x_items) - x_bullish - x_bearish
            a(f"**X/Twitter 社区声音：** 共 {len(x_items)} 条讨论（看多 {x_bullish} / 看空 {x_bearish} / 中性 {x_neutral_count}）")
            a("")
            a("典型观点：")
            a("")
            for xi in x_items[:2]:
                xm = xi["mention"]
                ts = fmt_dt(xm.created_at)
                sentiment_tag = sentiment_emoji(xi["compound"])
                a(f"> 「{_safe(xm.content, 200)}」")
                a(
                    f"> —— [@{xm.author}]({xm.url}) · {xm.upvotes:,} 赞 · {ts} · {sentiment_tag}"
                )
                a("")

        # ── 多源交叉验证 ──
        if exa_items and x_items:
            a("#### 多源交叉验证")
            a("")
            exa_content = " ".join(ei["mention"].content[:200] for ei in exa_items[:3]).lower()
            x_content = " ".join(xi["mention"].content[:200] for xi in x_items[:3]).lower()
            common_keywords = []
            check_words = [
                "btc", "bitcoin", "eth", "ethereum", "price", "sec", "etf",
                "whale", "liquidat", "pump", "dump", "rally", "crash",
                "regulation", "defi", "stablecoin", "trump", "tariff",
                "fed", "rate", "hack", "upgrade", "sol", "solana", "meme",
                "ai", "agent", "layer", "airdrop",
            ]
            for w in check_words:
                if w in exa_content and w in x_content:
                    common_keywords.append(w)

            if common_keywords:
                a(f"- **关键词共振：** Exa 权威媒体与 X 社区在 **{', '.join(common_keywords[:5])}** 上形成信息共振")
            else:
                a(f"- **话题对齐：** 权威媒体报道与社区讨论均聚焦于 **{cat}** 方向")

            exa_avg = sum(ei["compound"] for ei in exa_items) / len(exa_items) if exa_items else 0
            x_avg = sum(xi["compound"] for xi in x_items) / len(x_items) if x_items else 0
            if (exa_avg > 0.05 and x_avg > 0.05) or (exa_avg < -0.05 and x_avg < -0.05):
                a(f"- **情绪一致性：高** — 媒体 {exa_avg:+.2f} / 社区 {x_avg:+.2f}，方向一致，信号可信度较高")
            else:
                a(f"- **情绪一致性：分化** — 媒体 {exa_avg:+.2f} / 社区 {x_avg:+.2f}，存在分歧，需进一步观察")
            a("")

        # ── 影响分析 ──
        a("#### 影响评估")
        a("")
        a(_event_impact_analysis(cat, avg_s, event["total_engagement"], exa_n, x_n))
        a("")

        # ── WEEX 视角 ──
        perspective = WEEX_PERSPECTIVES.get(
            cat, "WEEX 持续关注该领域动态，为用户提供及时的市场情报和交易工具支持。"
        )
        a(f"**WEEX 视角：** {perspective}")
        a("")

        # ── 来源汇总 ──
        exa_domains = []
        for ei in exa_items[:5]:
            em = ei["mention"]
            domain = re.search(r"https?://(?:www\.)?([^/]+)", em.url or "")
            if domain:
                exa_domains.append(domain.group(1).replace("www.", ""))

        a("<details>")
        a("<summary>来源明细（点击展开）</summary>")
        a("")
        if exa_domains:
            a(f"- 权威媒体：{', '.join(list(dict.fromkeys(exa_domains))[:6])}")
        if x_items:
            x_authors = list(dict.fromkeys(f"@{xi['mention'].author}" for xi in x_items[:5]))
            a(f"- X/Twitter：{', '.join(x_authors)}")
        a(f"- 事件分类：{cat} | 情感均值：{avg_s:+.3f}")
        a("")
        a("</details>")
        a("")
        a("---")
        a("")

    # ════════════════════════════════════════════════════════════════
    # 三、市场总结与展望
    # ════════════════════════════════════════════════════════════════
    a("## 三、市场总结与展望")
    a("")

    # 事件关联分析
    if len(events) >= 2:
        a("### 事件关联分析")
        a("")
        cats = [e["category"] for e in events[:8]]
        cat_set = set(cats)

        # Always generate cross-event linkages
        linkages_found = False
        if "价格走势" in cat_set and "ETF" in cat_set:
            etf_ev = next((e for e in events if e["category"] == "ETF"), None)
            price_ev = next((e for e in events if e["category"] == "价格走势"), None)
            etf_sent = f"({etf_ev['avg_sentiment']:+.2f})" if etf_ev else ""
            price_sent = f"({price_ev['avg_sentiment']:+.2f})" if price_ev else ""
            a(f"- **价格-ETF 联动：** BTC 价格走势 {price_sent} 与 ETF 资金流动 {etf_sent} 存在明显联动。"
              " 机构通过 ETF 渠道的申赎行为直接改变现货市场供需平衡，是当前行情的核心定价因子之一。")
            linkages_found = True
        if "监管" in cat_set and ("DeFi" in cat_set or "交易所" in cat_set):
            a("- **监管-行业联动：** CLARITY 法案等监管框架的推进，将直接影响 DeFi 协议的合规化路径"
              "和交易所的运营策略。短期的不确定性压力与长期的制度红利形成对冲。")
            linkages_found = True
        if "地缘政治" in cat_set:
            a("- **地缘-宏观联动：** 伊朗局势等地缘冲突通过原油价格→通胀预期→利率路径的传导链"
              "影响全球风险偏好。加密市场作为风险资产，同步承受流动性紧缩预期的冲击。")
            linkages_found = True
        if "AI" in cat_set:
            a("- **AI-Crypto 共振：** AI + Crypto 赛道不断获得关注，AI Agent 自主交易和去中心化计算"
              "等叙事与链上基础设施需求形成正反馈循环，矿企 AI 转型加速了这一趋势。")
            linkages_found = True
        if "巨鲸" in cat_set and "价格走势" in cat_set:
            a("- **巨鲸-价格联动：** 链上大额地址的操作节奏与价格走势形成领先-滞后关系，"
              "「散户出逃、机构吸筹」的结构性换手信号是重要的底部确认指标。")
            linkages_found = True
        if not linkages_found:
            a("- 当前各事件之间的关联性较弱，市场缺乏统一的主题驱动力。")

        # 综合叙事
        a("")
        top_cats = list(dict.fromkeys(cats))[:5]
        a(f"过去 24 小时的核心叙事围绕 **{'、'.join(top_cats)}** 展开。")
        a("")

        positive_events = [e for e in events[:8] if e["avg_sentiment"] > 0.05]
        negative_events = [e for e in events[:8] if e["avg_sentiment"] < -0.05]

        if positive_events and negative_events:
            pos_titles = "、".join(f"「{e['title'][:25]}」" for e in positive_events[:2])
            neg_titles = "、".join(f"「{e['title'][:25]}」" for e in negative_events[:2])
            a(f"利多因素（{pos_titles}）与利空因素（{neg_titles}）相互博弈。"
              f"多方 {len(positive_events)} 个事件 vs 空方 {len(negative_events)} 个事件，"
              "市场短期方向仍需确认。")
        elif positive_events:
            a(f"利多因素占据主导（{len(positive_events)}/{len(events[:8])} 个事件偏多），"
              "市场情绪偏乐观，但需注意过热后的回调风险。")
        elif negative_events:
            a(f"利空因素集中释放（{len(negative_events)}/{len(events[:8])} 个事件偏空），"
              "市场承压明显。建议关注恐慌情绪消化后的技术性反弹窗口。")
        else:
            a("市场处于多空平衡状态，缺乏明确的方向性催化剂。")
        a("")

    # 操作建议
    a("### 操作建议")
    a("")
    if avg_compound > 0.1:
        a("1. **仓位管理：** 维持 60-70% 仓位，适当止盈锁定部分利润")
        a("2. **关注标的：** 重点关注讨论量和情感双升的币种")
        a("3. **风险提示：** 市场情绪偏热时反而需要冷静，设置好止损位")
    elif avg_compound > -0.1:
        a("1. **仓位管理：** 控制在 40-50% 仓位，保留现金等待方向确认")
        a("2. **关注标的：** 关注情感分化但基本面向好的币种")
        a("3. **风险提示：** 方向不明时降低杠杆至 3x 以内，避免双向爆仓")
    else:
        a("1. **仓位管理：** 降至 20-30% 轻仓，以防守为主")
        a("2. **关注标的：** 关注巨鲸逆势吸筹的标的，可能是反弹先行军")
        a("3. **风险提示：** 恐慌期不追空、不抄底，等待企稳信号再入场")
    a("")
    a(f"**核心结论：** {conclusion}")
    a("")
    a("---")
    a("")

    return "\n".join(L)


# ── V2 Tweet Drafts (12 diverse templates) ──


def generate_tweet_drafts_v2(events, results, symbol_avg):
    known_syms = sorted(
        [(k, v) for k, v in symbol_avg.items() if k != "UNKNOWN"],
        key=lambda x: x[1]["count"],
        reverse=True,
    )
    if not known_syms:
        known_syms = sorted(symbol_avg.items(), key=lambda x: x[1]["count"], reverse=True)
    sym1 = known_syms[0][0] if known_syms else "BTC"
    sym1_data = known_syms[0][1] if known_syms else {"avg": 0, "count": 0}
    sym2 = known_syms[1][0] if len(known_syms) > 1 else "ETH"
    sym2_data = known_syms[1][1] if len(known_syms) > 1 else {"avg": 0, "count": 0}

    top_event = events[0] if events else None
    top_m = top_event["top_mention"] if top_event else None
    second_event = events[1] if len(events) > 1 else top_event
    third_event = events[2] if len(events) > 2 else top_event

    top_kol = results[0] if results else None
    top_kol_m = top_kol["mention"] if top_kol else None

    bullish_pct = sum(1 for r in results if r["compound"] > 0.05) / max(len(results), 1) * 100
    bearish_pct = sum(1 for r in results if r["compound"] < -0.05) / max(len(results), 1) * 100

    ev1_title = top_event["title"] if top_event else "\u5e02\u573a\u52a8\u6001"
    ev2_title = second_event["title"] if second_event else "\u5e02\u573a\u52a8\u6001"
    ev3_title = third_event["title"] if third_event else "\u5e02\u573a\u52a8\u6001"
    ev1_cat = top_event["category"] if top_event else "\u5e02\u573a\u52a8\u6001"

    now_short = datetime.now(timezone.utc).strftime("%m/%d")
    now_eng = datetime.now(timezone.utc).strftime("%b %d")

    # Build event bullet points for reuse
    ev_bullets = []
    for e in events[:4]:
        ev_bullets.append(e["title"])

    L = []
    a = L.append

    a("## 四、推文草稿（参考语料风格 · 去AI味 · 12 套）")
    a("")
    a("> 语料参考：@WeexCn · @weexglobal_ch · @Bitget_zh · @binancezh · TG/IG 社群")
    a("> 风格参考：见 references/copywriting_materials.txt")
    a("> 风格要求：口语化、有梗、带互动、像真人运营写的、禁止「引发关注」「值得注意」等AI味用语")
    a("")

    # ── A. Hot Reply ──
    a(f"### A. 热点跟帖")
    if top_kol_m:
        a(f" \u2192 [@{top_kol_m.author}]({top_kol_m.url})")
    a("")
    a("```")
    if top_kol and top_kol["compound"] < -0.1:
        a(
            f"\u6760\u6746\u6e05\u5b8c\u4e86\uff0c\u8d4c\u684c\u4e0a\u4eba\u5c11\u4e86\uff0c\u53cd\u800c\u662f\u597d\u4e8b\u3002"
        )
        a(
            f"\u6bcf\u6b21{ev1_cat}\u4e4b\u540e\u90fd\u662f\u91cd\u65b0\u5b9a\u4ef7\u7684\u8d77\u70b9\uff0c\u770b\u73b0\u8d27\u6210\u4ea4\u91cf\u8ddf\u4e0d\u8ddf\u5f97\u4e0a\u3002"
        )
    else:
        a(f"\u8bf4\u5f97\u5bf9\u3002{ev1_title}\u8fd9\u4e2a\u65b9\u5411\u6700\u8fd1\u786e\u5b9e\u8001\u80fd\u770b\u5230\u3002")
        a(
            f"\u5168\u7f51 {sym1} \u8ba8\u8bba\u91cf {sym1_data['count']} \u6761\uff0c{'多军' if sym1_data['avg'] > 0 else '\u7a7a\u519b'}\u5360\u4e0a\u98ce\u3002"
        )
    a("#crypto")
    a("```")
    a("")

    # ── B. Data Flash ──
    a("### B. @WeexCn 数据速报")
    a("")
    a("```")
    a(f"\U0001f4ca {now_short} \u52a0\u5bc6\u5e02\u573a\u8206\u60c5\u901f\u62a5")
    a("")
    a(f"{sym1} \u60c5\u611f {sym1_data['avg']:+.2f} | {sym2} \u60c5\u611f {sym2_data['avg']:+.2f}")
    for b in ev_bullets[:3]:
        a(f"\u25b8 {b}")
    a(f"\u770b\u6da8 {bullish_pct:.0f}% / \u770b\u8dcc {bearish_pct:.0f}%")
    a("")
    a("\u6570\u636e\u6765\u6e90\uff1aWEEX Sentinel AI \u8206\u60c5\u7cfb\u7edf")
    a("#WEEX #BTC #\u52a0\u5bc6\u8d27\u5e01")
    a("```")
    a("")

    # ── C. Activity Promo ──
    a("### C. @WeexCn 活动导流")
    a("")
    a("```")
    a("WEEX 限时活动｜波动就是机会 \U0001f525")
    a("")
    a("今日热点：")
    for b in ev_bullets[:3]:
        a(f"\u2022 {b}")
    a("")
    a("合约交易连续 7 天 \u2192 20U 仓位空投")
    a("邀请有效用户 \u2192 50U 体验金")
    a("限时 0 手续费，名额有限 \U0001fae1")
    a("#WEEX #Crypto")
    a("```")
    a("")

    # ── D. Casual Commentary ──
    a("### D. @WeexCn 口语化吐槽")
    a("")
    a("```")
    a("刚刷完今天的 crypto twitter，几个感受：")
    a("")
    for i, b in enumerate(ev_bullets[:3], 1):
        a(f"{i}. {b}")
    a("")
    if sym1_data["avg"] < -0.1:
        a("又是被市场教做人的一天\U0001f605")
    elif sym1_data["avg"] > 0.1:
        a("今天空军集体破防了吧\U0001f60f")
    else:
        a("你说这是底还是半山腰？评论区聊聊")
    a(f"#WEEX #{sym1}")
    a("```")
    a("")

    # ── E. ABCD Quiz ──
    a("### E. @weexglobal_ch ABCD \u4e92\u52d5\u6e2c\u9a57\uff08\u62bd\u734e + UID\uff09")
    a("")
    a("```")
    a(
        f"\U0001f4ca \u5c0f\u6e2c\u8a66\uff5c\u4eca\u5929\u52a0\u5bc6\u5e02\u5834\u767c\u751f\u4e86\u4ec0\u9ebc\uff1f"
    )
    a("")
    labels = ["A", "B", "C", "D"]
    emojis = ["\U0001f631", "\U0001f40b", "\U0001f4c9", "\U0001f3e6"]
    for i, e in enumerate(events[:4]):
        a(f"{labels[i]}. {e['title']} {emojis[i] if i < len(emojis) else ''}")
    if len(events) < 4:
        for i in range(len(events), 4):
            a(f"{labels[i]}. \u5e02\u573a\u6574\u4f53\u5e73\u7a33 \U0001f60c")
    a("")
    a("\u8ffd\u8e64 @weexglobal_ch")
    a("\u8f49\u767c + \u6309\u8b9a\u672c\u63a8\u6587")
    a("\u8a55\u8ad6\u5340\u7559\u8a00\u300c\u9078\u9805 + UID\u300d")
    a("")
    next_draw = (datetime.now() + timedelta(days=2)).strftime(
        "%-m/%-d" if os.name != "nt" else "%#m/%#d"
    )
    a(f"{next_draw} \u96a8\u6a5f\u62bd 5 \u4f4d\uff0c\u6bcf\u4eba 10 USDT")
    a(f"#WEEX #{sym1}")
    a("```")
    a("")

    # ── F. Price Prediction Poll ──
    a("### F. @weexglobal_ch \u50f9\u683c\u9810\u6e2c\u6295\u7968")
    a("")
    a("```")
    a(
        f"{sym1} \u672c\u9031\u60c5\u611f {sym1_data['avg']:+.2f}\uff0c\u770b\u6da8 {bullish_pct:.0f}% vs \u770b\u8dcc {bearish_pct:.0f}%"
    )
    a("")
    a(
        f"\u4f60\u89ba\u5f97\u2014\u2014\u4e0b\u9031\u4e00 {sym1} \u6703\u6f32\u9084\u662f\u8dcc\uff1f"
    )
    a("")
    a("\u8ffd\u8e64 @weexglobal_ch")
    a("\u8f49\u767c\u6309\u8b9a\u9019\u689d\u63a8\u6587")
    a("\u8a55\u8ad6\u5340\u7559\u8a00 \u300c\u6f32\u300d \u6216 \u300c\u8dcc\u300d + UID")
    a("")
    a("\u96a8\u6a5f\u62bd 3 \u4f4d\u9810\u6e2c\u6210\u529f\u8005\uff0c\u6bcf\u4eba 10 USDT")
    a("48h \u5f8c\u958b\u734e\uff5e")
    a(f"#WEEX #{sym1}")
    a("```")
    a("")

    # ── G. Fun Analogy ──
    a("### G. @weexglobal_ch \u8da3\u5473\u985e\u6bd4")
    a("")
    a("```")
    if sym1_data["avg"] < -0.1:
        a(
            f"{sym1} \u6628\u5929\u6025\u8a3a\u5ba4\u6436\u6551\uff0c\u4eca\u5929\u8f49\u666e\u901a\u75c5\u623f\u89c0\u5bdf \U0001f3e5"
        )
        a("")
        a(
            f"\u91ab\u751f\uff08\u6280\u8853\u9762\uff09\u8aaa\uff1a\u751f\u547d\u9ad4\u5fb5\u8da8\u7a69\uff0c\u4f46\u9084\u9700\u8981\u89c0\u5bdf"
        )
        a(
            f"\u5bb6\u5c6c\uff08\u6563\u6236\uff09\u8aaa\uff1a\u8981\u4e0d\u8981\u8f49\u9662\uff08\u63db\u5e63\uff09\uff1f"
        )
        a(
            f"\u8b77\u58eb\uff08WEEX\uff09\u8aaa\uff1a\u5225\u614c\uff0c\u5148\u770b\u770b\u660e\u5929\u7684\u6aa2\u67e5\u5831\u544a \U0001f4cb"
        )
    else:
        a(
            f"{sym1} \u4eca\u5929\u50cf\u559d\u4e86\u7d05\u725b\u7684\u904b\u52d5\u54e1 \U0001f3c3\u200d\u2642\ufe0f\U0001f4a8"
        )
        a("")
        a(
            f"\u6559\u7df4\uff08\u6280\u8853\u9762\uff09\u8aaa\uff1a\u72c0\u614b\u4e0d\u932f\uff0c\u4f46\u5225\u885d\u592a\u731b"
        )
        a(
            f"\u89c0\u773e\uff08\u6563\u6236\uff09\u8aaa\uff1a\u885d\u554a\uff01\u7834\u7d00\u9304\uff01"
        )
        a(
            f"\u968a\u91ab\uff08WEEX\uff09\u8aaa\uff1a\u8a18\u5f97\u505a\u597d\u9632\u8b77\uff0c\u5225\u53d7\u50b7 \U0001f6e1\ufe0f"
        )
    a("")
    a(f"\u4f60\u89ba\u5f97 {sym1} \u4ec0\u9ebc\u6642\u5019\u80fd\u300c\u51fa\u9662\u300d\uff1f")
    a("\u7559\u8a00 + UID \u62bd 3 \u4eba\u9001 10U")
    a(f"#WEEX #{sym1}")
    a("```")
    a("")

    # ── H. English Market Pulse ──
    a("### H. @WEEX_Official English Market Pulse")
    a("")
    a("```")
    a(f"Crypto market pulse \u2014 {now_eng}")
    a("")
    for e in events[: min(5, len(events))]:
        emoji = (
            "\U0001f4c9"
            if e["avg_sentiment"] < -0.1
            else "\U0001f4c8"
            if e["avg_sentiment"] > 0.1
            else "\U0001f4ca"
        )
        a(f"{emoji} {e['title']}")
    a("")
    sent_word = (
        "Bullish" if sym1_data["avg"] > 0.05 else "Bearish" if sym1_data["avg"] < -0.05 else "Mixed"
    )
    a(f"Overall sentiment: {sent_word}")
    a("")
    a("Trade on WEEX \u2014 up to 200x leverage, zero slippage")
    a(f"#WEEX #{sym1} #Crypto")
    a("```")
    a("")

    # ── I. Hot Coin Alert ──
    a("### I. @WEEX_Official Hot Coin Alert")
    a("")
    a("```")
    a(f"#WEEX Hot Coin Alert \U0001f525")
    a("")
    a(f"${sym1} highlights:")
    a(f"\u2192 {sym1_data['count']} mentions, sentiment {sym1_data['avg']:+.3f}")
    a(f"\u2192 Top narrative: {ev1_title}")
    if top_m:
        a(f"\u2192 Key voice: @{top_m.author} ({top_m.upvotes:,} likes)")
    a("")
    a(f"Trade ${sym1}/USDT on WEEX")
    a("Up to 200x leverage | Industry-low fees")
    a(f"#WEEX #{sym1} #Crypto")
    a("```")
    a("")

    # ── J. Thread ──
    a("### J. @WeexCn Thread \u6df1\u5ea6\u5206\u6790\uff08\u9010\u6761\u53d1\u5e03\uff09")
    a("")
    a("```")
    a(
        "\u4eca\u5929\u6709\u51e0\u4ef6\u4e8b\u503c\u5f97\u8bf4\u4e00\u4e0b\uff0c\u6bd4\u5237 K \u7ebf\u6709\u7528\u3002"
    )
    a("```")
    for tidx, te in enumerate(events[:3], 1):
        tm = te["top_mention"]
        a("```")
        a(f"{tidx}/ {te['title']}")
        a("")
        a(f"@{tm.author}\uff1a\u300c{_safe(tm.content, 100)}\u300d")
        a(f"({tm.upvotes:,} \u8d5e \u00b7 {tm.reposts:,} \u8f6c)")
        a("```")
    a("```")
    a(f"{len(events[:3]) + 1}/ \u603b\u7ed3")
    a("")
    cats = "\u3001".join(e["title"] for e in events[:3])
    a(f"{cats}\u2014\u2014")
    a(
        "\u770b\u7740\u662f\u51e0\u4ef6\u4e8b\uff0c\u5176\u5b9e\u6307\u5411\u540c\u4e00\u4e2a\u65b9\u5411\u3002\u81ea\u5df1\u54c1\u3002"
    )
    a(f"#crypto #{sym1} #WEEX")
    a("```")
    a("")

    # ── K. TG Push ──
    a("### K. TG \u793e\u7fa4\u63a8\u9001")
    a("")
    a("```")
    a("\U0001f6a8 \u4eca\u5929\u7684\u884c\u60c5\u6709\u70b9\u523a\u6fc0")
    a("")
    for i, b in enumerate(ev_bullets[:4]):
        icons = ["\U0001f4ca", "\U0001f40b", "\U0001f4dc", "\U0001f3e6"]
        a(f"{icons[i] if i < len(icons) else '\u25b8'} {b}")
    a("")
    a(f"\u770b\u6da8 {bullish_pct:.0f}% / \u770b\u8dcc {bearish_pct:.0f}%")
    a("")
    a("\u6ce2\u52a8 = \u673a\u4f1a\uff0c\u4e0a WEEX \u5408\u7ea6\u4ea4\u6613")
    a("\u624b\u7eed\u8d39\u5168\u7f51\u6700\u4f4e \U0001f447")
    a("")
    a(f"#BTC #WEEX #Crypto")
    a("")
    a("\U0001f310 \u5b98\u65b9\u7f51\u7ad9\uff5c\U0001f4fa YouTube")
    a("\U0001f426 Twitter \uff5c \U0001f4f8 Instagram")
    a("```")
    a("")

    # ── L. Meme / Engagement Bait ──
    a("### L. Meme / \u53e3\u8bed\u5316 engagement bait")
    a("")
    a("```")
    a(f"\u522b\u95ee\uff0c\u95ee\u5c31\u662f{ev_bullets[0] if ev_bullets else ev1_cat}")
    a(
        f"\u522b\u89e3\u91ca\uff0c\u89e3\u91ca\u5c31\u662f{ev_bullets[1] if len(ev_bullets) > 1 else '\u5e02\u573a\u5728\u91cd\u65b0\u5b9a\u4ef7'}"
    )
    a(
        f"\u522b\u9884\u6d4b\uff0c\u9884\u6d4b\u5c31\u662f{ev_bullets[2] if len(ev_bullets) > 2 else '\u673a\u6784\u90fd\u5165\u573a\u4e86'}"
    )
    a("")
    a("\u4f60\u4eca\u5929\u662f \U0001f48e \u8fd8\u662f \U0001f9fb\uff1f")
    a("")
    a(f"#crypto #{sym1} #WEEX")
    a("```")
    a("")

    return "\n".join(L)


# ── V2 Ops Strategy + Data Sources + Appendix ──


def generate_ops_strategy_v2(events, results, symbol_avg):
    known_syms = sorted(
        [(k, v) for k, v in symbol_avg.items() if k != "UNKNOWN"],
        key=lambda x: x[1]["count"],
        reverse=True,
    )
    sym1 = known_syms[0][0] if known_syms else "BTC"
    top_event = events[0] if events else None
    top_m = top_event["top_mention"] if top_event else None
    kol_results = [r for r in results if r["engagement"] > 50][:5]

    L = []
    a = L.append

    a("## \u4e94\u3001\u8fd0\u8425\u7b56\u7565")
    a("")
    a("| \u6e20\u9053 | \u52a8\u4f5c | \u4f18\u5148\u7ea7 | \u65f6\u6548 |")
    a("|---|---|---|---|")
    if top_m:
        a(
            f"| @WeexCn | \u8ddf\u5e16 @{_clean_author(top_m.author)} \u70ed\u95e8\u63a8\u6587 | \u2b50\u2b50\u2b50 | \u7acb\u5373 |"
        )
    if top_event:
        a(
            f"| @WeexCn | \u300c{top_event['title']}\u300d\u72ec\u7acb\u5e16 | \u2b50\u2b50\u2b50 | 30min |"
        )
    a(
        f"| @weexglobal_ch | {sym1} \u4ef7\u683c\u9884\u6d4b\u4e92\u52a8\uff08\u62bd\u5956+UID\uff09 | \u2b50\u2b50\u2b50 | 1h |"
    )
    a("| @WEEX_Official | \u82f1\u6587\u5e02\u573a\u5feb\u8baf | \u2b50\u2b50 | 2h |")
    a(
        "| TG \u793e\u7fa4 | \u5e02\u573a\u901f\u62a5 + \u6d3b\u52a8\u94fe\u63a5 | \u2b50\u2b50 | \u7acb\u5373 |"
    )
    kol_names = [f"@{_clean_author(r['mention'].author)}" for r in kol_results[:3]]
    if kol_names:
        a(f"| \u8f6c\u8bc4 KOL | {'\u3001'.join(kol_names)} | \u2b50\u2b50 | 1h |")
    a("")

    if events:
        narrative = f"\u300c{events[0]['title']}\u300d"
        a(f"**\u6838\u5fc3\u53d9\u4e8b\uff1a{narrative}**")
    a("")
    a("---")
    a("")

    return "\n".join(L)


def generate_data_sources(all_mentions, results):
    x_count = sum(1 for m in all_mentions if m.platform == "x")
    news_count = sum(1 for m in all_mentions if m.platform in ("news", "exa"))

    L = []
    a = L.append

    a("## \u516d\u3001\u6570\u636e\u6765\u6e90")
    a("")
    a("| \u6570\u636e\u6e90 | \u65b9\u6cd5 | \u8986\u76d6\u8303\u56f4 | \u6570\u91cf |")
    a("|---|---|---|---|")
    a(
        f"| X/Twitter | Playwright + Firefox Cookie | crypto/bitcoin/ethereum \u5173\u952e\u8bcd\u641c\u7d22 | {x_count} \u6761 |"
    )
    a(
        f"| Exa \u5168\u7f51\u8bed\u4e49\u641c\u7d22 | mcporter MCP\uff08\u514d\u8d39\uff0c\u65e0\u9700 API key\uff09 | CoinDesk \u00b7 CoinTelegraph \u00b7 Yahoo Finance \u00b7 Reuters \u00b7 SEC | {news_count}+ \u6761 |"
    )
    a(
        "| Jina Reader | URL \u2192 Markdown\uff08\u514d\u8d39\uff09 | \u4efb\u610f\u7f51\u9875\u5168\u6587\u8bfb\u53d6 | \u6309\u9700 |"
    )
    a(
        f"| \u60c5\u611f\u5206\u6790 | VADER \u52a0\u5bc6\u9886\u57df\u5b9a\u5236\u8bcd\u5178\uff08120+ \u8bcd\u6c47\uff09 | \u5168\u90e8 X/Twitter \u91c7\u96c6\u5185\u5bb9 | {x_count} \u6761 |"
    )
    a("")
    a(
        "**Exa \u641c\u7d22\u96c6\u6210\u65b9\u5f0f\uff1a** \u501f\u9274 [Agent-Reach](https://github.com/Panniantong/Agent-Reach) \u9879\u76ee\uff0c\u901a\u8fc7 `mcporter` MCP \u63a5\u5165 Exa\uff08`mcporter config add exa https://mcp.exa.ai/mcp`\uff09\uff0c\u514d\u8d39\u65e0\u9700 API key\u3002"
    )
    a("")
    a("---")
    a("")

    return "\n".join(L)


def generate_appendix(results):
    L = []
    a = L.append

    a("## \u9644\u5f55\uff1a\u5168\u91cf\u6570\u636e\u660e\u7ec6")
    a("")
    a(
        "| # | \u5e73\u53f0 | \u4f5c\u8005 | \u5e01\u79cd | \u5185\u5bb9\u6458\u8981 | \u70b9\u8d5e | \u8f6c\u53d1 | \u8bc4\u8bba | \u60c5\u611f | \u5224\u5b9a | \u65f6\u95f4 | \u94fe\u63a5 |"
    )
    a("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for idx, r in enumerate(results, 1):
        m = r["mention"]
        snippet = m.content[:60].replace("\n", " ").replace("|", "\\|")
        if len(m.content) > 60:
            snippet += "..."
        ts = fmt_dt(m.created_at)
        label = sentiment_emoji(r["compound"])
        link = f"[\u2197]({m.url})" if m.url else ""
        a(
            f"| {idx} | {m.platform} | @{m.author} | {m.symbol} | {snippet} "
            f"| {m.upvotes} | {m.reposts} | {m.replies} "
            f"| {r['compound']:.3f} | {label} | {ts} | {link} |"
        )
    a("")

    return "\n".join(L)


def _mention_to_dict(m, compound):
    return {
        "platform": m.platform,
        "source_id": m.source_id,
        "symbol": m.symbol,
        "symbol_type": m.symbol_type,
        "author": m.author,
        "content": m.content,
        "url": m.url,
        "created_at": fmt_dt(m.created_at),
        "collected_at": fmt_dt(m.collected_at),
        "likes": m.upvotes,
        "reposts": m.reposts,
        "replies": m.replies,
        "language": m.language,
        "tags": m.tags,
        "sentiment_score": round(compound, 4),
        "sentiment_label": sentiment_emoji(compound),
    }


# ── Main ──


def main():
    logger.info("=== WEEX Sentinel Final Report Generator (v2) ===")

    logger.info("Step 1/4: Collecting data...")
    all_mentions = collect_all_mentions()
    if not all_mentions:
        logger.error("No mentions collected. Exiting.")
        sys.exit(1)
    logger.info("Total mentions collected: %d", len(all_mentions))

    logger.info("Step 2/4: Analyzing sentiment...")
    results, symbol_avg = analyze_sentiment(all_mentions)
    logger.info("Sentiment analysis complete. Symbols: %d", len(symbol_avg))

    logger.info("Step 3/4: Clustering events...")
    events = cluster_events(results)
    logger.info("Events clustered: %d categories", len(events))

    logger.info("Step 4/4: Generating v2 report...")
    report_body = generate_report_v2(results, symbol_avg, events, all_mentions)
    tweet_drafts = generate_tweet_drafts_v2(events, results, symbol_avg)
    ops_strategy = generate_ops_strategy_v2(events, results, symbol_avg)
    data_sources = generate_data_sources(all_mentions, results)
    appendix = generate_appendix(results)

    report_num = _get_report_number()
    footer = f"\n*WEEX Sentinel v3.0 \u00b7 Playwright + Exa (mcporter MCP) + Jina Reader + VADER NLP \u00b7 {report_num}*\n"

    full_report = "\n".join(
        [
            report_body,
            tweet_drafts,
            ops_strategy,
            data_sources,
            appendix,
            footer,
        ]
    )

    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H%M%S")
    out_dir = LOG_ROOT / date_str
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{time_str}_report.md"
    raw_path = out_dir / f"{time_str}_raw.json"

    out_path.write_text(full_report, encoding="utf-8")
    logger.info("Report saved to: %s", out_path)

    raw_data = [_mention_to_dict(r["mention"], r["compound"]) for r in results]
    raw_path.write_text(json.dumps(raw_data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Raw JSON saved to: %s", raw_path)

    logger.info("Report length: %d chars, %d lines", len(full_report), full_report.count("\n"))
    print(f"\n\u2705 Report generated: {out_path}")
    print(f"\u2705 Raw data saved: {raw_path}")
    print(
        f"\u2705 Mentions: {len(all_mentions)} | Events: {len(events)} | Symbols: {len(symbol_avg)}"
    )


if __name__ == "__main__":
    main()
