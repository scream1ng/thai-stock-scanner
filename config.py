"""
config.py
---------
Market configuration. Set MARKET env var to switch markets.
  MARKET=th   → Thai SET (default)
  MARKET=us   → US S&P 500
  MARKET=asx  → Australian ASX
"""

import os

MARKET = os.getenv("MARKET", "th").lower()

MARKETS = {
    "th": {
        "name":          "TH Market",
        "tv_market":     "thailand",
        "tv_exchange":   "SET",
        "benchmark":     "^SET.BK",
        "ticker_suffix": ".BK",
        "min_turnover":  5_000_000,       # THB
        "cron":          "0 10 * * 1-5",  # 5PM Bangkok
        "briefing_lang": "thai",
    },
    "us": {
        "name":          "US Market",
        "tv_market":     "america",
        "tv_exchange":   "NASDAQ",        # fallback — TV uses per-stock exchange
        "benchmark":     "^GSPC",
        "ticker_suffix": "",
        "min_turnover":  10_000_000,      # USD
        "cron":          "0 22 * * 1-5",  # 5PM EST
        "briefing_lang": "english",
    },
    "asx": {
        "name":          "AU Market",
        "tv_market":     "australia",
        "tv_exchange":   "ASX",
        "benchmark":     "^AXJO",
        "ticker_suffix": ".AX",
        "min_turnover":  2_000_000,       # AUD
        "cron":          "0 7 * * 1-5",   # 5PM AEST (UTC+10)
        "briefing_lang": "english",
    },
}

if MARKET not in MARKETS:
    raise ValueError(f"Unknown MARKET={MARKET!r}. Choose from: {list(MARKETS)}")

CFG = MARKETS[MARKET]