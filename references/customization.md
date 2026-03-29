# Customization Guide

## Sentiment Word Lists

Edit the constants at the top of `scripts/x_sentiment.py`:

### Bullish (看多) Words
```python
BULLISH_WORDS = {
    "bull", "bullish", "pump", "moon", "breakout", "surge", "rally", "buy", "long",
    "看涨", "拉升", "暴涨", "上涨", "突破", "买入", "做多", "利好", "起飞",
}
```

### Bearish (看空) Words
```python
BEARISH_WORDS = {
    "bear", "bearish", "dump", "crash", "sell", "short", "drop", "panic", "liquidation",
    "看跌", "暴跌", "下跌", "崩盘", "卖出", "做空", "利空", "清算", "恐慌",
}
```

### Adding Custom Sentiment
```python
# Example: Tech industry
BULLISH_WORDS |= {"launch", "partnership", "funding", "growth", "发布", "合作", "融资"}
BEARISH_WORDS |= {"layoff", "lawsuit", "breach", "delay", "裁员", "诉讼", "泄露"}
```

## Topic Detection Keywords

`HOT_TOPICS` controls recurring theme detection:
```python
HOT_TOPICS = [
    "bitcoin", "btc", "ethereum", "eth", "solana", "sol", "doge", "xrp", "etf",
    "stablecoin", "defi", "airdrop", "memecoin", "比特币", "以太坊", "山寨币",
    "现货etf", "稳定币", "空投", "链上", "监管", "减半",
]
```

Replace entirely for non-crypto monitoring:
```python
# Example: AI industry
HOT_TOPICS = [
    "chatgpt", "claude", "openai", "anthropic", "llm", "gpu", "nvidia",
    "大模型", "人工智能", "算力", "AGI", "开源", "多模态",
]
```

## Stop Words

`STOP_WORDS` filters noise from topic frequency analysis. Add your monitoring keyword itself to avoid circular detection.

## Draft Templates

Three draft generators in `build_drafts()`:

| Draft | Variable | Default Tone |
|---|---|---|
| A (热点跟帖) | `draft_a` | Balanced, risk-aware follow-up |
| B (独立发稿) | `draft_b` | Analytical article structure |
| C (其他建议) | `draft_c` | Tactical action list |

Edit the f-string templates directly to change language or style.

## Engagement Scoring

```python
def engagement_score(item):
    return item.likes * 3 + item.reposts * 2 + item.replies
```

Adjust weights by use case:
- Content creators: weight replies higher (engagement quality)
- News tracking: weight reposts higher (spread velocity)
- Market sentiment: weight likes higher (agreement signal)

## Firefox Profile Auto-Detection

Default search paths:
- Windows: `%APPDATA%\Mozilla\Firefox\Profiles\*.default-release`
- macOS: `~/Library/Application Support/Firefox/Profiles/*.default-release`
- Linux: `~/.mozilla/firefox/*.default-release`

Use `--firefox-profile` to override.
