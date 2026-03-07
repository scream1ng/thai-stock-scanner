import json
import os
from datetime import datetime, timedelta


THRESHOLD = 75  # RS rating / momentum threshold for quadrant classification


# ── Helpers ────────────────────────────────────────────────────────────────────

def classify(rs_rating, rs_momentum):
    high_r = rs_rating   >= THRESHOLD
    high_m = rs_momentum >= THRESHOLD
    if high_r and high_m:      return "Leading"
    if not high_r and high_m:  return "Improving"
    if high_r and not high_m:  return "Weakening"
    return "Lagging"


def load_history(data_dir: str, days: int = 6) -> dict[str, dict]:
    """
    Load the last `days` daily JSON snapshots.
    Returns {date_str: {ticker: record}} sorted newest→oldest.
    Only trading days with saved files are included.
    """
    history = {}
    today = datetime.now().date()

    # Walk backwards up to days*2 calendar days to account for weekends/holidays
    checked = 0
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
        checked += 1

    return dict(sorted(history.items(), reverse=True))  # newest first


# ── Trend analysis ─────────────────────────────────────────────────────────────

def analyze_trends(history: dict, today: str) -> dict:
    """
    Returns a dict with four alert categories:
      - momentum_streak:    stocks with RS momentum rising ≥3 consecutive days
      - quadrant_changes:   stocks that moved between quadrants vs yesterday
      - threshold_crossings: stocks whose RS rating or momentum just crossed 75
      - entries:            stocks new to today's scan (above SMA50 + filters)
      - exits:              stocks that disappeared since yesterday
    """
    sorted_dates = sorted(history.keys(), reverse=True)  # newest first

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

    # ── New entries & exits ────────────────────────────────────────────────────
    entries = []
    for ticker in today_data:
        if ticker not in yesterday_data:
            rec  = today_data[ticker]
            tech = rec["technical"]
            entries.append({
                "ticker":       ticker,
                "sector":       rec.get("sector", ""),
                "rs_rating":    tech["rs_rating"],
                "rs_momentum":  tech["rs_momentum"],
                "stretch_factor": tech.get("stretch_factor", 0),
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
                "from":        yest_q,
                "to":          today_q,
                "rs_rating":   tech["rs_rating"],
                "rs_momentum": tech["rs_momentum"],
            })

        # RS rating crossed 75 upward
        if yest_tech["rs_rating"] < THRESHOLD <= tech["rs_rating"]:
            threshold_crossings.append({
                "ticker": ticker,
                "sector": rec.get("sector", ""),
                "metric": "RS Rating",
                "from":   yest_tech["rs_rating"],
                "to":     tech["rs_rating"],
            })

        # RS momentum crossed 75 upward
        if yest_tech["rs_momentum"] < THRESHOLD <= tech["rs_momentum"]:
            threshold_crossings.append({
                "ticker": ticker,
                "sector": rec.get("sector", ""),
                "metric": "RS Momentum",
                "from":   yest_tech["rs_momentum"],
                "to":     tech["rs_momentum"],
            })

    # ── RS Momentum rising streak ──────────────────────────────────────────────
    momentum_streaks = []

    for ticker in today_data:
        # Collect momentum values oldest→newest across available history
        values = []
        for date in reversed(sorted_dates):  # oldest first
            day = history.get(date, {})
            if ticker in day:
                values.append(day[ticker]["technical"]["rs_momentum"])
            else:
                values = []  # reset if ticker missing on an intermediate day

        if len(values) < 2:
            continue

        # Count consecutive rising days from the end
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
