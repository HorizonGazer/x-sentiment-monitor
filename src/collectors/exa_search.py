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
    # ── 大方向：让搜索引擎匹配当下最热的内容 ──
    "bitcoin news today",
    "crypto market news today",
    "ethereum news today",
    "solana news today",
    "cryptocurrency regulation news",
    "bitcoin ETF news",
    "crypto hack exploit security",
    "crypto whale accumulation",
    "DeFi news TVL yield",
    "meme coin trending news",
    "crypto exchange news",
    "stablecoin regulation news",
    "XRP crypto news",
    "crypto institutional news",
    "bitcoin mining news",
    "crypto geopolitical impact",
]

AUTHORITY_DOMAINS = [
    # ── 加密专业媒体（一线）──
    "coindesk.com",
    "cointelegraph.com",
    "theblock.co",
    "decrypt.co",
    "blockworks.co",
    "dlnews.com",
    "crypto.news",
    "cryptobriefing.com",
    "cryptoslate.com",
    "bitcoinmagazine.com",
    "news.bitcoin.com",
    "ambcrypto.com",
    "bitcoinist.com",
    "unchainedcrypto.com",
    "defiant.news",
    # ── 主流财经 ──
    "finance.yahoo.com",
    "bloomberg.com",
    "reuters.com",
    "cnbc.com",
    "forbes.com",
    "wsj.com",
    "ft.com",
    # ── 数据/分析平台 ──
    "cryptorank.io",
    "coingecko.com",
    "messari.io",
    "glassnode.com",
    "dune.com",
    # ── 监管/官方 ──
    "sec.gov",
    "cftc.gov",
]

# ── WEEX-specific search queries ────────────────────────────────────────────
WEEX_QUERIES: list[str] = [
    "WEEX exchange news",
    "WEEX 交易所 活动",
    "WEEX trading competition",
    "WEEX crypto listing",
]

# ── Crypto gossip / drama search queries ────────────────────────────────────
GOSSIP_QUERIES: list[str] = [
    "crypto drama scandal controversy",
    "币圈八卦 跑路 暴雷",
    "crypto rug pull insider trading fraud",
    "crypto influencer scandal",
]

# ── Crypto hot topics search queries ────────────────────────────────────────
HOT_TOPICS_QUERIES: list[str] = [
    "crypto breaking news today",
    "cryptocurrency biggest news this week",
    "加密货币 最新消息 今日",
    "bitcoin ethereum latest developments",
]

# ── Cross-sector (跨圈) search queries ──────────────────────────────────────
CROSS_SECTOR_QUERIES: list[str] = [
    "oil price crypto impact today",
    "gold price crypto today",
    "AI technology crypto blockchain news",
    "stock market crypto correlation",
    "tariff trade war crypto",
    "Fed interest rate crypto impact",
    "geopolitical crisis crypto market",
]

# ── Macro / Fed / US Stock (宏观财经) search queries ────────────────────────
MACRO_FINANCE_QUERIES: list[str] = [
    "Federal Reserve interest rate decision today",
    "Fed FOMC meeting minutes latest",
    "US CPI inflation data today",
    "US stock market news today S&P 500 Nasdaq",
    "Treasury yield bond market news",
    "美联储 利率 降息 最新",
    "Wall Street earnings report today",
    "US employment jobs data nonfarm",
    "dollar index DXY forex today",
    "global recession risk economic outlook",
    "US China trade tariff news today",
    "tech stocks NVIDIA Apple Tesla today",
]

# ── Global News (全球新闻) search queries ────────────────────────────────────
GLOBAL_NEWS_QUERIES: list[str] = [
    # 全球热门
    "breaking world news today",
    "global headlines today most important",
    # 科技/AI（英文）
    "AI artificial intelligence news today",
    "tech industry news NVIDIA OpenAI Google Apple today",
    "semiconductor chip supply chain news",
    # 国内科技/财经（中文火爆）
    "国内科技 今日热点 头条",
    "AI 大模型 国内 新闻 今日",
    "互联网巨头 阿里 腾讯 字节 美团 京东 拼多多 今日",
    "国产芯片 半导体 今日 突破",
    "新能源车 比亚迪 蔚来 小鹏 理想 小米汽车 今日",
    "造车新势力 销量 财报 今日",
    "国内独角兽 估值 融资 今日",
    "中概股 美股 今日 涨跌",
    "国内政策 新政 监管 今日",
    "36氪 今日热文 创投 早报",
    "钛媒体 虎嗅 今日 头条",
    "雷峰网 量子位 机器之心 今日",
    "IT之家 数码 今日热搜",
    # 美股
    "US stock market today S&P Nasdaq Dow",
    "Wall Street earnings market moving today",
    "美股 行情 涨跌 今日",
    # A股/港股
    "A股 行情 今日 沪深",
    "Hong Kong stock market HSI Hang Seng today",
    "港股 恒生 今日 行情",
    "China stock market A-share today",
    "北向资金 今日 流入流出",
    # 风投/融资
    "venture capital funding round today",
    "startup funding Series A B C crypto web3",
    "融资 投资 轮次 今日",
    "国内融资 创投 今日 IPO",
    # 国际政治/地缘
    "geopolitical news conflict sanctions today",
    "US China relations trade policy today",
    "Trump tariff trade war latest",
    "international politics diplomacy today",
    # 大宗商品
    "crude oil price OPEC today",
    "gold silver commodity price today",
    "commodity market agricultural metals today",
    # 国内财经/产业（48h火爆）
    "财经 头条 今日 热门",
    "产业 行业 突发 今日 国内",
    "国内 热搜 财经 商业 今日",
    # 港澳台热点（24h火爆）
    "香港 今日 新闻 头条 热点",
    "台湾 今日 新闻 头条 热点",
    "澳门 今日 新闻 热点",
    "Hong Kong news today breaking",
    "Taiwan news today breaking",
    "Macau news today breaking",
    "香港 财经 股市 今日",
    "台湾 财经 股市 今日",
    "港股 行情 今日 恒生",
    "台股 行情 今日 加权",
    "香港 科技 创科 AI 今日",
    "台湾 科技 半导体 AI 今日",
    "香港 加密货币 虚拟资产 Web3 今日",
    "台湾 加密货币 虚拟货币 区块链 今日",
    "港澳 金融 监管 政策 今日",
    "港台 IPO 新股 上市",
]

# ── Global News authority domains ────────────────────────────────────────────
GLOBAL_NEWS_DOMAINS: list[str] = [
    # ── 全球顶级综合媒体 ──
    "reuters.com",
    "apnews.com",
    "bbc.com",
    "nytimes.com",
    "washingtonpost.com",
    "theguardian.com",
    "aljazeera.com",
    # ── 科技/AI（海外）──
    "techcrunch.com",
    "theverge.com",
    "wired.com",
    "arstechnica.com",
    "technologyreview.com",
    "tomshardware.com",
    "engadget.com",
    "venturebeat.com",
    # ── 财经/市场（海外）──
    "bloomberg.com",
    "cnbc.com",
    "wsj.com",
    "ft.com",
    "finance.yahoo.com",
    "marketwatch.com",
    "barrons.com",
    "seekingalpha.com",
    "investing.com",
    # ── A股/港股/亚太 ──
    "scmp.com",
    "nikkei.com",
    "asia.nikkei.com",
    # ── 国内科技媒体 ──
    "36kr.com",          # 36氪 — 创投/科技头条
    "huxiu.com",         # 虎嗅 — 商业/科技深度
    "tmtpost.com",       # 钛媒体 — 科技产业
    "ithome.com",        # IT之家 — 数码/科技热搜
    "leiphone.com",      # 雷锋网 — AI/科技
    "geekpark.net",      # 极客公园 — 科技创新
    "qbitai.com",        # 量子位 — AI 资讯
    "jiqizhixin.com",    # 机器之心 — AI 研究
    "pingwest.com",      # 品玩 PingWest — 科技消费
    "ifanr.com",         # 爱范儿 — 科技/数码
    "cnbeta.com.tw",     # cnBeta — 科技综合
    "donews.com",        # DoNews — 互联网行业
    # ── 国内财经媒体 ──
    "wallstreetcn.com",  # 华尔街见闻 — 实时财经
    "jin10.com",         # 金十数据 — 财经快讯
    "cls.cn",            # 财联社 — A股快讯
    "caixin.com",        # 财新 — 深度财经
    "yicai.com",         # 第一财经
    "jiemian.com",       # 界面新闻
    "stcn.com",          # 证券时报
    "cs.com.cn",         # 中国证券报
    "sse.com.cn",        # 上交所
    "eastmoney.com",     # 东方财富
    "10jqka.com.cn",     # 同花顺
    "sohu.com",          # 搜狐财经/科技
    "sina.com.cn",       # 新浪财经/科技
    "qq.com",            # 腾讯新闻
    "163.com",           # 网易财经/科技
    "thepaper.cn",       # 澎湃新闻
    "guancha.cn",        # 观察者网
    # ── VC/创投 ──
    "crunchbase.com",
    "pitchbook.com",
    "itjuzi.com",        # IT桔子 — 国内创投数据
    "cyzone.cn",         # 创业邦
    # ── 大宗商品 ──
    "oilprice.com",
    "kitco.com",
    "mining.com",
    # ── 港澳台媒体 ──
    "hk01.com",              # 香港01 — 综合新闻
    "exmoo.com",             # 力报 — 澳门综合
    "hket.com",              # 香港经济日报 — 财经
    "mingpao.com",           # 明报 — 综合
    "wenweipo.com",          # 文汇报 — 综合
    "bastillepost.com",      # 巴士的报 — 新闻
    "rthk.hk",               # 港台 — 公共广播
    "std.stheadline.com",    # 星岛日报 — 综合
    "cna.com.tw",            # 中央社 — 台湾官方通讯社
    "udn.com",               # 联合报 — 综合
    "chinatimes.com",        # 中时电子报 — 综合
    "ltn.com.tw",            # 自由时报 — 综合
    "ettoday.net",           # ETtoday — 新闻
    "storm.mg",              # 风传媒 — 深度
    "thenewslens.com",       # 关键评论网 — 深度
    "taiwannews.com.tw",     # 台湾英文新闻 — 英文
    "tw.news.yahoo.com",     # Yahoo奇摩新闻 — 聚合
    "tw.stock.yahoo.com",    # Yahoo奇摩股市 — 台股
    "businesstoday.com.tw",  # 今周刊 — 财经
    "wealth.com.tw",         # 财富网 — 财经
    "ctwant.com",            # CTWANT — 新闻
    "twreporter.org",        # 报导者 — 深度调查
    "cmmedia.com.tw",        # 信传媒 — 财经
    "taronews.tw",           # 芋传媒 — 综合
    "newtalk.tw",            # Newtalk新闻 — 综合
    "setn.com",              # 三立新闻网 — 综合
    "tvbs.com.tw",           # TVBS — 综合
    "ftvnews.com.tw",        # 民视新闻网 — 综合
    "pts.org.tw",            # 公视 — 公共媒体
]

# ── 港澳台专属域名（collect_hk_tw_macau 专用，确保命中率） ──────────────────
HK_TW_MACAU_DOMAINS: list[str] = [
    # 香港
    "hk01.com",
    "hket.com",
    "mingpao.com",
    "wenweipo.com",
    "bastillepost.com",
    "rthk.hk",
    "std.stheadline.com",
    "scmp.com",
    # 澳门
    "exmoo.com",
    # 台湾
    "cna.com.tw",
    "udn.com",
    "chinatimes.com",
    "ltn.com.tw",
    "ettoday.net",
    "storm.mg",
    "thenewslens.com",
    "taiwannews.com.tw",
    "tw.news.yahoo.com",
    "tw.stock.yahoo.com",
    "businesstoday.com.tw",
    "wealth.com.tw",
    "ctwant.com",
    "newtalk.tw",
    "setn.com",
    "tvbs.com.tw",
    "cmmedia.com.tw",
    "taronews.tw",
]

# ── 港澳台专属查询词 ──────────────────────────────────────────────────────
HK_TW_MACAU_QUERIES: list[str] = [
    "香港 今日 新闻 头条 热点",
    "台湾 今日 新闻 头条 热点",
    "澳门 今日 新闻 热点",
    "Hong Kong news today breaking",
    "Taiwan news today breaking",
    "香港 财经 股市 恒生 今日",
    "台湾 财经 股市 加权 今日",
    "港股 行情 今日 恒生指数",
    "台股 行情 今日 加权指数",
    "香港 科技 创科 AI 初创 今日",
    "台湾 半导体 台积电 芯片 AI 今日",
    "香港 加密货币 虚拟资产 ETF Web3 今日",
    "台湾 加密货币 虚拟货币 区块链 监管 今日",
    "港澳 金融 监管 政策 牌照 今日",
    "港台 IPO 新股 上市 认购",
    "Hong Kong crypto regulation Web3 today",
    "Taiwan semiconductor TSMC chip news today",
]

# ── Macro / Finance authority domains ────────────────────────────────────────
MACRO_AUTHORITY_DOMAINS: list[str] = [
    # ── 顶级财经媒体 ──
    "bloomberg.com",
    "reuters.com",
    "cnbc.com",
    "wsj.com",
    "ft.com",
    "finance.yahoo.com",
    "marketwatch.com",
    "barrons.com",
    "seekingalpha.com",
    "investing.com",
    "tradingview.com",
    # ── 宏观经济/央行 ──
    "federalreserve.gov",
    "bls.gov",
    "bea.gov",
    # ── 财经分析 ──
    "zerohedge.com",
    "forexlive.com",
    "fxstreet.com",
    "dailyfx.com",
    # ── 中文财经 ──
    "wallstreetcn.com",
    "jin10.com",
    "cls.cn",
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

    def collect_trending(self, limit: int = 100) -> list[RawMention]:
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

        # Phase 1: search each query with 24h freshness (max 12 results each)
        for query in CRYPTO_QUERIES:
            results = self.search_exa(
                query, num_results=12, freshness="24h", include_domains=AUTHORITY_DOMAINS
            )
            _add_results(results)
            if len(mentions) >= limit:
                break

        # Phase 2: broader "today" catch-all if still short
        if len(mentions) < limit:
            broad = self.search_exa(
                "crypto market news today", num_results=15, freshness="24h",
                include_domains=AUTHORITY_DOMAINS
            )
            _add_results(broad)

        # Phase 3: breaking news without domain restriction
        if len(mentions) < limit:
            breaking = self.search_exa(
                "bitcoin breaking news today", num_results=10, freshness="24h"
            )
            _add_results(breaking)

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

    def _collect_by_queries(
        self,
        queries: list[str],
        limit: int,
        freshness: str = "24h",
        include_domains: list[str] | None = None,
    ) -> list[RawMention]:
        """Generic helper: search multiple queries and return deduplicated mentions."""
        mentions: list[RawMention] = []
        seen_urls: set[str] = set()

        def _add_results(results: list[dict]) -> None:
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

        for query in queries:
            results = self.search_exa(
                query, num_results=10, freshness=freshness, include_domains=include_domains
            )
            _add_results(results)
            if len(mentions) >= limit:
                break

        return mentions[:limit]

    def collect_weex(self, limit: int = 20) -> list[RawMention]:
        """Collect WEEX-related news and articles."""
        return self._collect_by_queries(WEEX_QUERIES, limit, freshness="24h")

    def collect_gossip(self, limit: int = 20) -> list[RawMention]:
        """Collect crypto gossip and drama articles."""
        return self._collect_by_queries(
            GOSSIP_QUERIES, limit, freshness="24h", include_domains=AUTHORITY_DOMAINS
        )

    def collect_hot_topics(self, limit: int = 20) -> list[RawMention]:
        """Collect crypto hot topics and trending articles."""
        return self._collect_by_queries(
            HOT_TOPICS_QUERIES, limit, freshness="24h", include_domains=AUTHORITY_DOMAINS
        )

    def collect_cross_sector(self, limit: int = 20) -> list[RawMention]:
        """Collect cross-sector (跨圈) news linking macro/AI/commodity events to crypto."""
        return self._collect_by_queries(
            CROSS_SECTOR_QUERIES, limit, freshness="24h", include_domains=AUTHORITY_DOMAINS
        )

    def collect_macro_finance(self, limit: int = 20) -> list[RawMention]:
        """Collect macro finance / Fed / US stock market news."""
        return self._collect_by_queries(
            MACRO_FINANCE_QUERIES, limit, freshness="24h",
            include_domains=MACRO_AUTHORITY_DOMAINS
        )

    def collect_global_news(self, limit: int = 80) -> list[RawMention]:
        """Collect global news across sectors: tech/AI, stocks, VC, geopolitics, commodities."""
        return self._collect_by_queries(
            GLOBAL_NEWS_QUERIES, limit, freshness="24h",
            include_domains=GLOBAL_NEWS_DOMAINS
        )

    def collect_hk_tw_macau(self, limit: int = 30) -> list[RawMention]:
        """Collect Hong Kong, Taiwan, Macau news with dedicated domain whitelist."""
        return self._collect_by_queries(
            HK_TW_MACAU_QUERIES, limit, freshness="24h",
            include_domains=HK_TW_MACAU_DOMAINS
        )

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
