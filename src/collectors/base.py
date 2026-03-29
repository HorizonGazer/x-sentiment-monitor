"""
Base types and protocol for all data collectors.

RawMention is the universal data format that every collector produces.
Collector is the protocol that every collector must implement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable


@dataclass(slots=True)
class RawMention:
    """Universal mention record produced by every collector."""

    platform: str
    source_id: str
    symbol: str
    symbol_type: str  # "crypto" | "stock" | "etf"
    author: str
    content: str
    created_at: datetime
    collected_at: datetime
    url: str
    upvotes: int = 0
    reposts: int = 0
    replies: int = 0
    language: str = "en"
    tags: list[str] = field(default_factory=list)
    subreddit: str = ""
    sentiment_raw: float | None = None
    extra: dict = field(default_factory=dict)  # type: ignore[type-arg]


@runtime_checkable
class Collector(Protocol):
    """Protocol that every data collector must satisfy."""

    def collect_trending(self, limit: int = 100) -> list[RawMention]:
        """Collect trending / hot mentions across the platform."""
        ...

    def collect_symbol(self, symbol: str, days: int = 1) -> list[RawMention]:
        """Collect mentions for a specific symbol within *days* lookback."""
        ...

    def search(self, query: str, limit: int = 50) -> list[RawMention]:
        """Free-text search across the platform."""
        ...

    def health_check(self) -> dict:  # type: ignore[type-arg]
        """Return connectivity / credential status."""
        ...
