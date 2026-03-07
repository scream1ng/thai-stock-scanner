import os
import requests
from datetime import datetime

from tracker import classify

WEBHOOK_URL    = os.getenv("DISCORD_WEBHOOK")
print(f"[DEBUG] WEBHOOK_URL = '{WEBHOOK_URL}'")
CHAR_LIMIT     = 1900
QUADRANT_ORDER = ["Leading", "Improving", "Weakening"]
QUADRANT_EMOJI = {"Leading": "🟢", "Improving": "🔵", "Weakening": "🟠"}


# ── Discord primitives ─────────────────────────────────────────────────────────

def _create_thread(thread_name: str, content: str) -> str | None:
    """Create a new forum thread. Returns thread_id for follow-up messages."""
    if not WEBHOOK_URL:
        print(f"[THREAD] {thread_name}\n{content}")
        return None
    resp = requests.post(
        f"{WEBHOOK_URL}?wait=true",
        json={"thread_name": thread_name, "content": content},
        timeout=15,
    )
    if not resp.ok:
        print(f"[ERROR] Failed to create thread: {resp.status_code} {resp.text}")
        resp.raise_for_status()
    return resp.json().get("channel_id")


def _post(content: str, thread_id: str | None = None):
    """Send a follow-up message into an existing thread (or stdout if no webhook)."""
    if not content or not content.strip():
        return
    if not WEBHOOK_URL:
        print(content)
        return
    url = f"{WEBHOOK_URL}?thread_id={thread_id}" if thread_id else WEBHOOK_URL
    resp = requests.post(url, json={"content": content}, timeout=15)
    if not resp.ok:
        print(f"[ERROR] {resp.status_code}: {resp.text}")
        resp.raise_for_status()


def _send_chunked(header: str, lines: list[str], thread_id: str | None = None):
    """Send header then split lines into ≤CHAR_LIMIT code blocks."""
    _post(header, thread_id)
    if not lines:
        _post("```(none)```", thread_id)
        return
    chunk = ""
    for line in lines:
        candidate = chunk + line + "\n"
        if len(candidate) + 6 > CHAR_LIMIT:
            _post(f"```\n{chunk}```", thread_id)
            chunk = line + "\n"
        else:
            chunk = candidate
    if chunk.strip():
        _post(f"```\n{chunk}```", thread_id)


# ── Row formatters ─────────────────────────────────────────────────────────────

def _stock_row(ticker, rs_rating, rs_momentum, stretch_factor, sector, **_):
    return (
        f"{ticker:<12} "
        f"RS:{rs_rating:>5.1f}  "
        f"MOM:{rs_momentum:>5.1f}  "
        f"STR:{stretch_factor:>5.2f}  "
        f"{str(sector)[:22]}"
    )


def _streak_row(ticker, streak, rs_momentum, rs_rating, sector, **_):
    return (
        f"{ticker:<12} "
        f"🔥{streak}d  "
        f"MOM:{rs_momentum:>5.1f}  "
        f"RS:{rs_rating:>5.1f}  "
        f"{str(sector)[:22]}"
    )


def _change_row(ticker, from_q, to_q, rs_rating, rs_momentum, sector, **_):
    arrow = "↗" if to_q in ("Leading", "Improving") else "↘"
    return (
        f"{ticker:<12} "
        f"{from_q:<10} {arrow} {to_q:<10}  "
        f"RS:{rs_rating:>5.1f}  MOM:{rs_momentum:>5.1f}"
    )


def _crossing_row(ticker, metric, from_val, to_val, sector, **_):
    return (
        f"{ticker:<12} "
        f"{metric:<12} "
        f"{from_val:>5.1f} → {to_val:>5.1f}  "
        f"{str(sector)[:22]}"
    )


# ── Main report ────────────────────────────────────────────────────────────────

def send_report(results: list, trends: dict, today: str):
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Group results by quadrant
    groups: dict[str, list] = {q: [] for q in QUADRANT_ORDER}
    for item in results:
        tech = item["technical"]
        q = classify(tech["rs_rating"], tech["rs_momentum"])
        if q in groups:
            groups[q].append({
                "ticker":         item["ticker"],
                "sector":         item.get("sector", ""),
                "rs_rating":      tech["rs_rating"],
                "rs_momentum":    tech["rs_momentum"],
                "stretch_factor": tech.get("stretch_factor", 0),
            })

    total = sum(len(v) for v in groups.values())

    # ── Create forum thread (first message opens the thread) ──────────────────
    thread_id = _create_thread(
        thread_name=f"RS Report · {today}",
        content=(
            f"📊 **Thai RS Report** — {date_str}\n"
            f"🔎 {total} stocks above SMA50"
        ),
    )

    # ── Quadrant tables ───────────────────────────────────────────────────────
    for q in QUADRANT_ORDER:
        items = sorted(groups[q], key=lambda x: -x["rs_momentum"])
        if not items:
            continue
        header = f"{QUADRANT_EMOJI[q]} **{q.upper()}** — {len(items)} stocks"
        lines  = [_stock_row(**i) for i in items]
        _send_chunked(header, lines, thread_id)

    # ── Trend alerts ──────────────────────────────────────────────────────────
    _post("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n📈 **Trend Alerts**", thread_id)

    if trends["entries"]:
        lines = [_stock_row(**e) for e in trends["entries"]]
        _send_chunked(f"🆕 **New Entries** — {len(trends['entries'])} stocks", lines, thread_id)

    if trends["exits"]:
        tickers = ", ".join(trends["exits"])
        _post(f"🚪 **Exits**: {tickers}", thread_id)

    if trends["momentum_streak"]:
        lines = [_streak_row(**s) for s in trends["momentum_streak"]]
        _send_chunked(
            f"🔥 **RS Momentum Rising ≥3 Days** — {len(trends['momentum_streak'])} stocks",
            lines, thread_id,
        )

    if trends["quadrant_changes"]:
        lines = [_change_row(**c) for c in trends["quadrant_changes"]]
        _send_chunked(
            f"🔄 **Quadrant Changes** — {len(trends['quadrant_changes'])} stocks",
            lines, thread_id,
        )

    if trends["threshold_crossings"]:
        lines = [_crossing_row(**c) for c in trends["threshold_crossings"]]
        _send_chunked(
            f"⚡ **Crossed Threshold (75)** — {len(trends['threshold_crossings'])} events",
            lines, thread_id,
        )

    _post("✅ **End of report**", thread_id)