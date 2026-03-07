import json
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

from scanner import run_scan
from tracker import load_history, analyze_trends, get_top_sectors
from reporter import send_report


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

    # ── Sector rotation (for context only, not a filter) ──────────────────────
    top_sectors = get_top_sectors(all_results, top_n=3)

    # ── Trends ────────────────────────────────────────────────────────────────
    print("Analysing trends...")
    history = load_history("data", days=6)
    trends  = analyze_trends(history, today)

    # ── Report (all stocks, no sector filter) ─────────────────────────────────
    print("Sending report...")
    send_report(all_results, trends, today, top_sectors=top_sectors)
    print("Done ✅")


if __name__ == "__main__":
    main()