"""Extract crypto/stock symbols from text content."""

import re

CRYPTO_SYMBOLS = {
    "BTC": ["bitcoin", "btc", "$btc", "xbt"],
    "ETH": ["ethereum", "eth", "$eth", "ether"],
    "SOL": ["solana", "sol", "$sol"],
    "XRP": ["xrp", "$xrp", "ripple"],
    "BNB": ["bnb", "$bnb", "binance coin"],
    "DOGE": ["doge", "$doge", "dogecoin"],
    "ADA": ["ada", "$ada", "cardano"],
    "DOT": ["dot", "$dot", "polkadot"],
    "AVAX": ["avax", "$avax", "avalanche"],
    "MATIC": ["matic", "$matic", "polygon"],
    "LINK": ["link", "$link", "chainlink"],
    "UNI": ["uni", "$uni", "uniswap"],
    "AAVE": ["aave", "$aave"],
    "LDO": ["ldo", "$ldo", "lido"],
    "OP": ["$op", "optimism"],
    "ARB": ["$arb", "arbitrum"],
    "PEPE": ["pepe", "$pepe"],
    "SHIB": ["shib", "$shib", "shiba"],
    "TRX": ["trx", "$trx", "tron"],
    "ATOM": ["atom", "$atom", "cosmos"],
    "NEAR": ["near", "$near"],
    "FTM": ["ftm", "$ftm", "fantom"],
    "APT": ["apt", "$apt", "aptos"],
    "SUI": ["sui", "$sui"],
    "SEI": ["sei", "$sei"],
    "INJ": ["inj", "$inj", "injective"],
    "ONDO": ["ondo", "$ondo"],
    "WIF": ["wif", "$wif"],
    "BONK": ["bonk", "$bonk"],
    "FLOKI": ["floki", "$floki"],
    "ENA": ["ena", "$ena", "ethena"],
    "HYPE": ["hype", "$hype", "hyperliquid"],
}

STOCK_SYMBOLS = {
    "MSTR": ["mstr", "$mstr", "microstrategy"],
    "COIN": ["$coin", "coinbase"],
    "MARA": ["mara", "marathon digital"],
    "RIOT": ["riot", "riot platforms"],
    "HIVE": ["hive digital", "$hive"],
    "WULF": ["terawulf", "$wulf"],
    "HUT": ["hut 8", "$hut"],
}

_CRYPTO_LOOKUP: dict[str, str] = {}
for sym, aliases in CRYPTO_SYMBOLS.items():
    for alias in aliases:
        _CRYPTO_LOOKUP[alias.lower()] = sym

_STOCK_LOOKUP: dict[str, str] = {}
for sym, aliases in STOCK_SYMBOLS.items():
    for alias in aliases:
        _STOCK_LOOKUP[alias.lower()] = sym

_SYMBOL_RE = re.compile(
    r"\$([A-Z]{2,6})\b|"
    r"\b(bitcoin|ethereum|solana|xrp|ripple|bnb|dogecoin|cardano|polkadot|"
    r"avalanche|polygon|chainlink|uniswap|aave|lido|optimism|arbitrum|"
    r"tron|cosmos|fantom|aptos|ethena|hyperliquid|coinbase|microstrategy|"
    r"marathon digital|terawulf|hut 8)\b|"
    r"\b(BTC|ETH|SOL|XRP|BNB|DOGE|ADA|DOT|AVAX|MATIC|LINK|UNI|AAVE|LDO|"
    r"TRX|ATOM|NEAR|FTM|APT|SUI|SEI|INJ|ONDO|WIF|BONK|FLOKI|ENA|HYPE|"
    r"MSTR|COIN|MARA|RIOT|HIVE|WULF|HUT)\b",
    re.IGNORECASE,
)


def extract_symbols(text: str) -> list[tuple[str, str]]:
    """Extract (symbol, type) pairs from text. Returns list of unique matches."""
    found: dict[str, str] = {}
    text_lower = text.lower()

    for match in _SYMBOL_RE.finditer(text):
        dollar, name, ticker = match.groups()
        key = (dollar or name or ticker or "").lower()
        if not key:
            continue

        # Check crypto first
        if key in _CRYPTO_LOOKUP:
            sym = _CRYPTO_LOOKUP[key]
            if sym not in found:
                found[sym] = "crypto"
            continue

        # Check stocks
        if key in _STOCK_LOOKUP:
            sym = _STOCK_LOOKUP[key]
            if sym not in found:
                found[sym] = "stock"
            continue

        # Dollar-sign ticker ($XXX)
        if dollar:
            upper = dollar.upper()
            if upper in CRYPTO_SYMBOLS:
                found[upper] = "crypto"
            elif upper in STOCK_SYMBOLS:
                found[upper] = "stock"

        # Uppercase ticker
        if ticker:
            upper = ticker.upper()
            if upper in CRYPTO_SYMBOLS:
                found[upper] = "crypto"
            elif upper in STOCK_SYMBOLS:
                found[upper] = "stock"

    return list(found.items())
