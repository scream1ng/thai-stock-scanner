import feedparser
import time
from datetime import datetime, timezone

# ── RSS Sources ────────────────────────────────────────────────────────────────

FEEDS = [
    {
        "name": "Bloomberg",
        "url":  "https://feeds.bloomberg.com/markets/news.rss",
    },
    {
        "name": "Yahoo Finance",
        "url":  "https://finance.yahoo.com/rss/topfinstories",
    },
]

MAX_HEADLINES = 5   # total headlines across all sources
MAX_AGE_HOURS = 24  # ignore news older than this


# ── Helpers ────────────────────────────────────────────────────────────────────

def _parse_feed(feed_info: dict) -> list[dict]:
    """Fetch and parse a single RSS feed. Returns list of {title, source, age_h}."""
    try:
        feed = feedparser.parse(feed_info["url"])
        results = []
        now = datetime.now(timezone.utc)

        for entry in feed.entries[:10]:
            title = entry.get("title", "").strip()
            if not title:
                continue

            # Parse publish time if available
            published = entry.get("published_parsed") or entry.get("updated_parsed")
            if published:
                pub_dt  = datetime(*published[:6], tzinfo=timezone.utc)
                age_h   = (now - pub_dt).total_seconds() / 3600
            else:
                age_h = 0  # unknown age — include anyway

            # Format publish date as YYYY-MM-DD
            if published:
                from datetime import datetime as dt
                pub_date = dt(*published[:3]).strftime("%Y-%m-%d")
            else:
                pub_date = ""

            if age_h <= MAX_AGE_HOURS:
                results.append({
                    "title":     title,
                    "source":    feed_info["name"],
                    "age_h":     round(age_h, 1),
                    "published": pub_date,
                    "url":       entry.get("link", ""),
                })

        return results
    except Exception as e:
        print(f"  ⚠ News feed failed ({feed_info['name']}): {e}")
        return []


# ── Public entry point ─────────────────────────────────────────────────────────

def get_headlines(max_per_source: int = 5) -> dict[str, list[dict]]:
    """
    Fetch headlines grouped by source.
    Returns {source_name: [headlines]} dict.
    """
    grouped = {}
    for feed in FEEDS:
        items = _parse_feed(feed)
        # Deduplicate within source
        seen, unique = [], []
        for h in items:
            key = " ".join(h["title"].lower().split()[:6])
            if key not in seen:
                seen.append(key)
                unique.append(h)
        grouped[feed["name"]] = unique[:max_per_source]
        time.sleep(0.3)
    return grouped


def format_headlines(grouped: dict[str, list[dict]]) -> str:
    """Format headlines grouped by source for Discord."""
    if not grouped or all(len(v) == 0 for v in grouped.values()):
        return "📰 No recent headlines available"

    lines = ["📰 **Market Headlines**"]
    for source, headlines in grouped.items():
        if not headlines:
            continue
        lines.append(f"\n=== {source} ===")
        for h in headlines:
            # Show date only if available
            published = h.get("published", "")
            date_str  = f"  [{published}]" if published else ""
            lines.append(f"- {h['title']}{date_str}")

    return "\n".join(lines)