import json
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

from scanner import run_scan
from tracker import load_history, analyze_trends, get_top_sectors
from reporter import send_report
from news import get_headlines, format_headlines, generate_briefing


def main():
    today = datetime.now().strftime("%Y-%m-%d")
    os.makedirs("data", exist_ok=True)
    snapshot_path = f"data/{today}.json"

    # ── Load or scan ───────────────────────────────────────────────────────────
    if os.path.exists(snapshot_path):
        print(f"Found today's snapshot — loading {snapshot_path}")
        with open(snapshot_path) as f:
            all_results = json.load(f)
        print(f"  → {len(all_results)} stocks loaded from file")
    else:
        print("─" * 50)
        print(f"No snapshot for {today} — running full scan...")
        all_results = run_scan()
        with open(snapshot_path, "w") as f:
            json.dump(all_results, f, indent=2)
        print(f"  Saved {len(all_results)} stocks → {snapshot_path}")

    # ── Sector rotation ────────────────────────────────────────────────────────
    top_sectors = get_top_sectors(all_results, top_n=3)

    # ── Trends ────────────────────────────────────────────────────────────────
    print("Analysing trends...")
    history = load_history("data", days=6)
    trends  = analyze_trends(history, today)

    # ── Headlines + briefing ──────────────────────────────────────────────────
    print("Fetching headlines...")
    grouped        = get_headlines(max_per_source=6)
    headlines_text = format_headlines(grouped)

    print("Generating market briefing...")
    briefing = generate_briefing(all_results, grouped, today)

    # ── Report ────────────────────────────────────────────────────────────────
    print("Sending report...")
    send_report(all_results, trends, today,
                top_sectors=top_sectors,
                headlines_text=headlines_text,
                briefing=briefing)
    print("Done ✅")


if __name__ == "__main__":
    main()