"""
Cross-section deduplication for WEEX Sentinel.

Three dedup strategies (any one matches → duplicate):
  1. source_id (tweet ID / URL) — exact match
  2. URL canonicalization — strip utm_*, fbclid, gclid, mc_cid, etc.
  3. Content similarity — SimHash with 0.75 threshold (looser per spec)

Applied:
  - Globally before saving raw.json (dedup across all collectors)
  - Per-section in summary generation (final pass)
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections import defaultdict
from typing import Iterable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

logger = logging.getLogger(__name__)


# ── 1. URL canonicalization ─────────────────────────────────────────────
TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "mc_cid", "mc_eid", "ref", "ref_src", "ref_url",
    "_ga", "_gl", "yclid", "msclkid", "igshid", "share_src",
    "s",  # twitter share param
    "t",  # twitter share param
}


def canonicalize_url(url: str) -> str:
    """Remove tracking params, normalize trailing slash, lowercase host."""
    if not url:
        return ""
    try:
        p = urlparse(url)
        # Drop tracking params
        clean_qs = [(k, v) for k, v in parse_qsl(p.query) if k.lower() not in TRACKING_PARAMS]
        new_query = urlencode(clean_qs)
        # Normalize host
        netloc = p.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        # Strip fragment, normalize path trailing slash
        path = p.path.rstrip("/") or "/"
        return urlunparse((p.scheme.lower() or "https", netloc, path, "", new_query, ""))
    except Exception:
        return url


# ── 2. SimHash-based content similarity ────────────────────────────────
def _tokenize(text: str) -> list[str]:
    """Cheap CN+EN tokenization: keep CJK chars as single tokens, EN as words."""
    text = (text or "").lower()
    # Pull out hashtags/mentions/words/CJK chars
    return re.findall(r"[#@]?\w{2,}|[\u4e00-\u9fff]", text)


def _simhash(text: str, hash_bits: int = 64) -> int:
    """Compute 64-bit SimHash."""
    tokens = _tokenize(text)
    if not tokens:
        return 0
    weights: dict[str, int] = defaultdict(int)
    for tok in tokens:
        weights[tok] += 1

    bit_vec = [0] * hash_bits
    for tok, w in weights.items():
        h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
        for i in range(hash_bits):
            if (h >> i) & 1:
                bit_vec[i] += w
            else:
                bit_vec[i] -= w
    fingerprint = 0
    for i in range(hash_bits):
        if bit_vec[i] > 0:
            fingerprint |= (1 << i)
    return fingerprint


def _hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def _similarity(a: int, b: int, hash_bits: int = 64) -> float:
    return 1.0 - _hamming(a, b) / hash_bits


# ── 3. Main dedup entrypoint ───────────────────────────────────────────
def dedup_mentions(
    mentions: Iterable,
    *,
    similarity_threshold: float = 0.75,
    keep_first: bool = True,
):
    """
    Deduplicate a list of RawMention objects.

    Args:
      mentions: iterable of RawMention
      similarity_threshold: 0.75 = looser (per 优化.md), 0.85 = stricter default
      keep_first: True = keep first occurrence (others dropped)

    Returns:
      (deduped_list, dedup_stats)
    """
    seen_source_ids: set[str] = set()
    seen_canonical_urls: set[str] = set()
    kept: list = []
    kept_simhashes: list[tuple[int, str]] = []  # (simhash, source_id)
    stats = {
        "total": 0,
        "dropped_by_source_id": 0,
        "dropped_by_url": 0,
        "dropped_by_similarity": 0,
        "kept": 0,
    }

    for m in mentions:
        stats["total"] += 1

        # Strategy 1: source_id
        sid = getattr(m, "source_id", "") or ""
        if sid and sid in seen_source_ids:
            stats["dropped_by_source_id"] += 1
            continue

        # Strategy 2: canonicalized URL
        url = getattr(m, "url", "") or ""
        canonical = canonicalize_url(url) if url else ""
        if canonical and canonical in seen_canonical_urls:
            stats["dropped_by_url"] += 1
            continue

        # Strategy 3: SimHash similarity
        content = getattr(m, "content", "") or ""
        sh = _simhash(content) if content else 0
        is_dup = False
        if sh != 0:
            for prev_sh, _prev_sid in kept_simhashes:
                if prev_sh == 0:
                    continue
                if _similarity(sh, prev_sh) >= similarity_threshold:
                    is_dup = True
                    break
        if is_dup:
            stats["dropped_by_similarity"] += 1
            continue

        # Keep this mention
        if sid:
            seen_source_ids.add(sid)
        if canonical:
            seen_canonical_urls.add(canonical)
        kept_simhashes.append((sh, sid))
        kept.append(m)
        stats["kept"] += 1

    return kept, stats


def dedup_dict_items(
    items: list[dict],
    *,
    similarity_threshold: float = 0.75,
) -> tuple[list[dict], dict]:
    """
    Same logic but for already-serialized dict items (used in summary generation).
    Looks at item['source_id'], item['url'], item['content'].
    """
    seen_source_ids: set[str] = set()
    seen_canonical_urls: set[str] = set()
    kept: list[dict] = []
    kept_simhashes: list[tuple[int, str]] = []
    stats = {
        "total": 0,
        "dropped_by_source_id": 0,
        "dropped_by_url": 0,
        "dropped_by_similarity": 0,
        "kept": 0,
    }

    for it in items:
        stats["total"] += 1

        sid = it.get("source_id", "") or ""
        if sid and sid in seen_source_ids:
            stats["dropped_by_source_id"] += 1
            continue

        url = it.get("url", "") or ""
        canonical = canonicalize_url(url) if url else ""
        if canonical and canonical in seen_canonical_urls:
            stats["dropped_by_url"] += 1
            continue

        content = it.get("content", "") or ""
        sh = _simhash(content) if content else 0
        is_dup = False
        if sh != 0:
            for prev_sh, _ in kept_simhashes:
                if prev_sh == 0:
                    continue
                if _similarity(sh, prev_sh) >= similarity_threshold:
                    is_dup = True
                    break
        if is_dup:
            stats["dropped_by_similarity"] += 1
            continue

        if sid:
            seen_source_ids.add(sid)
        if canonical:
            seen_canonical_urls.add(canonical)
        kept_simhashes.append((sh, sid))
        kept.append(it)
        stats["kept"] += 1

    return kept, stats


# ── 4. WEEX source filter (per 优化.md改造点4) ─────────────────────────
WEEX_SOURCE_DOMAINS = {
    "weex.com",
    "blog.weex.com",
    "support.weex.com",
    "weex.zendesk.com",
}


def is_weex_source(url: str) -> bool:
    """Returns True if URL is from WEEX (must be excluded from news/source list)."""
    if not url:
        return False
    try:
        host = urlparse(url).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        return any(host == d or host.endswith("." + d) for d in WEEX_SOURCE_DOMAINS)
    except Exception:
        return False


def filter_weex_sources(mentions: Iterable, allow_weex_official_platform: bool = True) -> tuple[list, int]:
    """
    Drop any mention whose URL points to WEEX channels — they are二手 sources.

    Args:
      allow_weex_official_platform: keep mentions where platform == 'weex_official'
        (these are intentionally collected and routed to Ch6 'WEEX 运营日历' only,
        never used as news sources in Ch2/Ch3/Ch5)

    Returns:
      (filtered_list, num_dropped)
    """
    kept: list = []
    dropped = 0
    for m in mentions:
        url = getattr(m, "url", "") or ""
        platform = getattr(m, "platform", "") or ""
        if is_weex_source(url):
            if allow_weex_official_platform and platform == "weex_official":
                kept.append(m)
                continue
            dropped += 1
            continue
        kept.append(m)
    return kept, dropped
