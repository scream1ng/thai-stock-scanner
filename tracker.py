import json
import os
from datetime import datetime, timedelta
from collections import defaultdict
from config import CFG

THRESHOLD = 75


# ── Helpers ────────────────────────────────────────────────────────────────────

def classify(rs_rating, rs_momentum):
    high_r = rs_rating   >= THRESHOLD
    high_m = rs_momentum >= THRESHOLD
    if high_r and high_m:      return "Leading"
    if not high_r and high_m:  return "Improving"
    if high_r and not high_m:  return "Weakening"
    return "Lagging"


def load_history(data_dir: str, days: int = 6) -> dict:
    """Load last `days` daily snapshots. Returns {date_str: {ticker: record}}."""
    history = {}
    today = datetime.now().date()

    for offset in range(days * 2):
        if len(history) >= days:
            break
        date = today - timedelta(days=offset)
        date_str = date.strftime("%Y-%m-%d")
        path = os.path.join(data_dir, f"{date_str}.json")
        if os.path.exists(path):
            with open(path) as f:
                records = json.load(f)
            history[date_str] = {r["ticker"]: r for r in records}

    return dict(sorted(history.items(), reverse=True))


# ── Sector rotation ────────────────────────────────────────────────────────────

def _turnover(item: dict) -> float:
    """Price x volume as market weight proxy."""
    tech = item["technical"]
    return tech["price"] * tech.get("volume_ratio", 1)


def _weighted_avg(values: list, weights: list) -> float:
    total_w = sum(weights)
    if total_w == 0:
        return 0.0
    return sum(v * w for v, w in zip(values, weights)) / total_w


def get_top_sectors(results: list, top_n: int = 3) -> list[str]:
    """
    Rank sectors by turnover-weighted RS momentum.
    Heavier stocks (price x volume) have more influence — mirrors how SET index moves.
    Requires at least 2 stocks to qualify.
    """
    sector_data = defaultdict(list)
    for item in results:
        sector = item.get("sector", "Unknown")
        tech   = item["technical"]
        sector_data[sector].append({
            "rs":       tech["rs_rating"],
            "mom":      tech["rs_momentum"],
            "turnover": _turnover(item),
        })

    ranked = []
    for sector, stocks in sector_data.items():
        if len(stocks) < 2:
            continue
        weights  = [s["turnover"] for s in stocks]
        avg_mom  = _weighted_avg([s["mom"] for s in stocks], weights)
        ranked.append((sector, avg_mom))

    ranked.sort(key=lambda x: -x[1])
    top = [s[0] for s in ranked[:top_n]]
    print(f"  Top {top_n} sectors (turnover-weighted MOM): {', '.join(top)}")
    return top


def get_sector_summary(results: list) -> list[dict]:
    """
    Return sectors ranked by turnover-weighted RS momentum.
    Shows both weighted MOM and weighted RS. Min 2 stocks to qualify.
    """
    sector_data = defaultdict(list)
    for item in results:
        sector = item.get("sector", "Unknown")
        tech   = item["technical"]
        sector_data[sector].append({
            "rs":       tech["rs_rating"],
            "mom":      tech["rs_momentum"],
            "turnover": _turnover(item),
            "ticker":   item["ticker"].replace(".BK", ""),
        })

    summary = []
    for sector, stocks in sector_data.items():
        if len(stocks) < 2:
            continue
        weights = [s["turnover"] for s in stocks]
        # Sort tickers by turnover descending for display
        suffix  = CFG["ticker_suffix"]
        tickers = [s["ticker"].replace(suffix, "") for s in sorted(stocks, key=lambda x: -x["turnover"])]
        summary.append({
            "sector":  sector,
            "avg_mom": round(_weighted_avg([s["mom"] for s in stocks], weights), 1),
            "avg_rs":  round(_weighted_avg([s["rs"]  for s in stocks], weights), 1),
            "count":   len(stocks),
            "tickers": tickers,
        })

    return sorted(summary, key=lambda x: -x["avg_mom"])


# ── Trend analysis ─────────────────────────────────────────────────────────────

def analyze_trends(history: dict, today: str) -> dict:
    """Detect all trend signals across historical snapshots."""
    sorted_dates = sorted(history.keys(), reverse=True)

    empty = {
        "momentum_streak":     [],
        "quadrant_changes":    [],
        "threshold_crossings": [],
        "entries":             [],
        "exits":               [],
    }

    if len(sorted_dates) < 2:
        return empty

    today_data     = history[sorted_dates[0]]
    yesterday_data = history[sorted_dates[1]]

    # ── Entries & exits ────────────────────────────────────────────────────────
    entries = []
    for ticker in today_data:
        if ticker not in yesterday_data:
            rec  = today_data[ticker]
            tech = rec["technical"]
            entries.append({
                "ticker":         ticker,
                "sector":         rec.get("sector", ""),
                "rs_rating":      tech["rs_rating"],
                "rs_momentum":    tech["rs_momentum"],
                "stretch_factor": tech.get("stretch_factor", 0),
                "volume_ratio":   tech.get("volume_ratio", 0),
                "proximity_52w":  tech.get("proximity_52w", 0),
            })

    exits = [t for t in yesterday_data if t not in today_data]

    # ── Quadrant changes & threshold crossings ─────────────────────────────────
    quadrant_changes    = []
    threshold_crossings = []

    for ticker, rec in today_data.items():
        if ticker not in yesterday_data:
            continue

        tech      = rec["technical"]
        yest_tech = yesterday_data[ticker]["technical"]

        today_q = classify(tech["rs_rating"], tech["rs_momentum"])
        yest_q  = classify(yest_tech["rs_rating"], yest_tech["rs_momentum"])

        if today_q != yest_q:
            quadrant_changes.append({
                "ticker":      ticker,
                "sector":      rec.get("sector", ""),
                "from_q":      yest_q,
                "to_q":        today_q,
                "rs_rating":   tech["rs_rating"],
                "rs_momentum": tech["rs_momentum"],
            })

        if yest_tech["rs_rating"] < THRESHOLD <= tech["rs_rating"]:
            threshold_crossings.append({
                "ticker":   ticker,
                "sector":   rec.get("sector", ""),
                "metric":   "RS Rating",
                "from_val": yest_tech["rs_rating"],
                "to_val":   tech["rs_rating"],
            })

        if yest_tech["rs_momentum"] < THRESHOLD <= tech["rs_momentum"]:
            threshold_crossings.append({
                "ticker":   ticker,
                "sector":   rec.get("sector", ""),
                "metric":   "RS Momentum",
                "from_val": yest_tech["rs_momentum"],
                "to_val":   tech["rs_momentum"],
            })

    # ── RS Momentum rising streak ──────────────────────────────────────────────
    momentum_streaks = []

    for ticker in today_data:
        values = []
        for date in reversed(sorted_dates):
            day = history.get(date, {})
            if ticker in day:
                values.append(day[ticker]["technical"]["rs_momentum"])
            else:
                values = []

        if len(values) < 2:
            continue

        streak = 1
        for i in range(len(values) - 1, 0, -1):
            if values[i] > values[i - 1]:
                streak += 1
            else:
                break

        if streak >= 3:
            tech = today_data[ticker]["technical"]
            momentum_streaks.append({
                "ticker":      ticker,
                "sector":      today_data[ticker].get("sector", ""),
                "streak":      streak,
                "rs_momentum": tech["rs_momentum"],
                "rs_rating":   tech["rs_rating"],
            })

    momentum_streaks.sort(key=lambda x: (-x["streak"], -x["rs_momentum"]))

    return {
        "momentum_streak":     momentum_streaks,
        "quadrant_changes":    quadrant_changes,
        "threshold_crossings": threshold_crossings,
        "entries":             entries,
        "exits":               exits,
    }