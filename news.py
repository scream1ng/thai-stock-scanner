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

# ── Keyword filter ─────────────────────────────────────────────────────────────

RELEVANT_KEYWORDS = [
    "thailand", "thai", "baht", "set index", "asean",
    "fed", "federal reserve", "rate", "interest rate", "inflation", "cpi",
    "gdp", "recession", "us economy", "dollar", "dxy", "treasury", "yield",
    "tariff", "trade war", "sanction", "powell",
    "china", "chinese", "yuan", "pmi", "asia", "emerging market",
    "japan", "yen", "korea", "vietnam",
    "oil", "crude", "opec", "energy", "gas", "lng",
    "gold", "copper", "commodity", "supply chain",
    "rubber", "rice", "sugar", "palm",
    "war", "conflict", "attack", "iran", "israel",
    "russia", "ukraine", "taiwan", "strait", "blockade", "middle east", "hormuz",
    "rally", "crash", "selloff", "volatility", "risk off", "risk on",
    "tourism", "tourist", "travel", "airline",
]


def _is_relevant(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in RELEVANT_KEYWORDS)


def get_relevant_flat(grouped: dict[str, list[dict]]) -> str:
    """Return filtered headlines as a flat string for Gemini prompt."""
    lines = []
    for source, headlines in grouped.items():
        relevant = [h for h in headlines if _is_relevant(h["title"])]
        if not relevant:
            continue
        lines.append(f"=== {source} ===")
        for h in relevant:
            lines.append(f"- {h['title']}")
    return "\n".join(lines) if lines else "No relevant headlines today"


# ── Gemini briefing ────────────────────────────────────────────────────────────

import os
from collections import defaultdict

try:
    import google.generativeai as genai
    _api_key = os.getenv("GEMINI_API_KEY")
    if _api_key:
        genai.configure(api_key=_api_key)
        _model = genai.GenerativeModel("gemini-2.5-flash-lite")
    else:
        _model = None
except ImportError:
    _model = None


def _summarize(stocks: list) -> dict:
    quadrants   = {"Leading": [], "Improving": [], "Weakening": [], "Lagging": []}
    sector_data = defaultdict(list)

    for s in stocks:
        tech   = s["technical"]
        rs, mom = tech["rs_rating"], tech["rs_momentum"]
        ticker = s["ticker"].replace(".BK", "")

        if   rs >= 75 and mom >= 75: q = "Leading"
        elif rs <  75 and mom >= 75: q = "Improving"
        elif rs >= 75 and mom <  75: q = "Weakening"
        else:                        q = "Lagging"

        entry = {
            "ticker": ticker, "rs": rs, "mom": mom,
            "vol":   tech.get("volume_ratio",    0),
            "prox":  tech.get("proximity_52w",   0),
            "tight": tech.get("tightness_score", 0),
            "str":   tech.get("stretch_factor",  0),
        }
        quadrants[q].append(entry)
        sector_data[s.get("sector", "Unknown")].append(entry)

    def top(group, n=5):
        return sorted(
            [s for s in group if s["vol"] >= 1.0 and s["str"] < 7],
            key=lambda x: -x["mom"]
        )[:n]

    stretched = sorted(
        [s for s in quadrants["Leading"] + quadrants["Improving"] if s["str"] >= 7],
        key=lambda x: -x["str"]
    )

    sector_ranked = []
    for sec, stks in sector_data.items():
        if len(stks) < 2:
            continue
        avg_mom     = round(sum(s["mom"] for s in stks) / len(stks), 1)
        top_tickers = [s["ticker"] for s in sorted(stks, key=lambda x: -x["mom"])[:4]]
        sector_ranked.append((sec, avg_mom, top_tickers))
    sector_ranked.sort(key=lambda x: -x[1])

    return {
        "counts":        {k: len(v) for k, v in quadrants.items()},
        "top_leading":   top(quadrants["Leading"]),
        "top_improving": top(quadrants["Improving"]),
        "overstretched": stretched,
        "top_sectors":   sector_ranked[:5],
    }


def _build_prompt(summary: dict, headlines: str, date: str) -> str:

    def fmt(stocks, n=6):
        rows = []
        for s in stocks[:n]:
            flags = []
            if s["prox"] >= 95:   flags.append("AT 52W HIGH")
            elif s["prox"] >= 85: flags.append("NEAR 52W HIGH")
            if s["tight"] >= 70:  flags.append("TIGHT BASE")
            flag_str = f"  [{', '.join(flags)}]" if flags else ""
            rows.append(
                f"  {s['ticker']:<12} RS:{s['rs']:>5.1f}  MOM:{s['mom']:>5.1f}  "
                f"VOL:{s['vol']:>4.1f}x  52W:{s['prox']:>5.1f}%  STR:{s['str']:>5.2f}{flag_str}"
            )
        return "\n".join(rows) or "  (none)"

    sectors   = "\n".join(
        f"  {s[0]:<30} MOM: {s[1]}  tickers: {', '.join(s[2])}"
        for s in summary["top_sectors"]
    )
    stretched = "\n".join(
        f"  {s['ticker']:<12} STR:{s['str']:>5.2f}  VOL:{s['vol']:>4.1f}x  52W:{s['prox']:>5.1f}%"
        for s in summary["overstretched"]
    ) or "  (none)"

    return f"""
คุณคือนักเทรดหุ้นไทยที่มีประสบการณ์ กำลังสรุปตลาดให้ตัวเองก่อนดูกราฟ
วันที่ {date}

กฎเด็ดขาด:
- ตอบเป็นภาษาไทยเท่านั้น
- ห้ามใช้ ** หรือ ## หรือ markdown ใดๆ
- ใช้ - สำหรับ bullet, : สำหรับหัวข้อ
- ใช้เฉพาะข้อมูลที่ให้มา ห้ามพูดถึง RSI, MACD, Overbought, Oversold
- เวลาพูดถึง Volume ต้องบอกตัวเลขเสมอ ห้ามพูดว่า "Volume สูง" หรือ "พร้อม Volume"
- ห้ามใช้ประโยคซ้ำกันระหว่างหุ้น

บทบาท: เราจะนั่งดูกราฟทุกตัวใน watchlist อยู่แล้ว ต้องการเฉพาะสิ่งที่อาจมองข้ามถ้าไม่บอก
ห้ามมีหัวข้อ "สิ่งที่ต้องจำขณะดูกราฟ" หรือ "สิ่งที่ถ้าไม่บอกอาจมองข้าม" ในคำตอบ
ให้เริ่มต้นด้วย Market Tone: ทันที

## ข้อมูล (คัดกรองเฉพาะหุ้นที่ราคา > SMA50 และ turnover ผ่านเกณฑ์)

Market Structure:
- Leading  (RS≥75, MOM≥75): {summary['counts']['Leading']} stocks
- Improving (RS<75, MOM≥75): {summary['counts']['Improving']} stocks
- Weakening (RS≥75, MOM<75): {summary['counts']['Weakening']} stocks
- Lagging:                    {summary['counts']['Lagging']} stocks

Top Leading (VOL≥1.0x, STR<7):
{fmt(summary['top_leading'])}

Top Improving (VOL≥1.0x, STR<7):
{fmt(summary['top_improving'])}

Overstretched (STR≥7 — ห้ามไล่ราคา):
{stretched}

Sector Momentum Ranking:
{sectors}

Global Headlines:
{headlines}

---

โครงสร้าง (หัวข้อภาษาอังกฤษ เนื้อหาภาษาไทย):

Market Tone:
- Leading xx | Improving xx | Weakening xx | Lagging xx
- [อัตราส่วน Leading:Weakening บอกอะไร]
- [Improving vs Lagging บอกอะไร — ย้ำว่าข้อมูลนี้ไม่ใช่ภาพรวมตลาดทั้งหมด]

Rotation Alert:
- ชื่อเซกเตอร์ MOM xx.x — TICKER1, TICKER2, TICKER3
(แสดง 3 เซกเตอร์ ไม่ต้องมีคำอธิบายเพิ่ม)

Avoid Today:
- TICKER STR xx.xx — เหตุผลสั้นที่แตกต่างกันแต่ละตัว ใช้ค่า STR จริง ห้ามปัดเลข

Macro Flag:
- [ประเด็นข่าว] — กระทบ TICKER1, TICKER2 [บวก/ลบ]

Start Here:
(ห้ามใส่หุ้นที่อยู่ใน Avoid Today เด็ดขาด เหตุผลต้องแตกต่างกันแต่ละตัว)
- TICKER RS: xx.x MOM: xx.x VOL: x.xx STR: x.xx — [เหตุผลเฉพาะตัว ห้ามพูดว่า Volume สูง]
""".strip()


def generate_briefing(stocks: list, grouped_headlines: dict, date: str) -> str:
    """Generate Gemini market briefing. Returns plain text or empty string."""
    if not _model:
        print("  ⚠ Gemini not available (no GEMINI_API_KEY) — skipping briefing")
        return ""
    try:
        summary   = _summarize(stocks)
        headlines = get_relevant_flat(grouped_headlines)
        prompt    = _build_prompt(summary, headlines, date)
        response  = _model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        print(f"  ⚠ Gemini briefing failed: {e}")
        return ""