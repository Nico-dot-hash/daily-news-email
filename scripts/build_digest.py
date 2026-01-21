#!/usr/bin/env python3
import argparse
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import feedparser

FEEDS = {
    "World": [
        "http://newsrss.bbc.co.uk/rss/newsonline_uk_edition/world/rss.xml",
    ],
    "Technology": [
        "http://newsrss.bbc.co.uk/rss/newsonline_uk_edition/technology/rss.xml",
    ],
    "Business & Economy": [
        "http://newsrss.bbc.co.uk/rss/newsonline_uk_edition/business/rss.xml",
    ],
}

def entry_datetime(entry):
    for key in ("published", "updated"):
        if key in entry and entry[key]:
            try:
                dt = parsedate_to_datetime(entry[key])
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except Exception:
                pass
    return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="digest.md")
    ap.add_argument("--hours", type=int, default=24)
    ap.add_argument("--max-per-section", type=int, default=8)
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=args.hours)

    sections = []
    seen_links = set()

    for section, urls in FEEDS.items():
        items = []
        for url in urls:
            feed = feedparser.parse(url)
            for e in getattr(feed, "entries", []):
                link = getattr(e, "link", None)
                title = getattr(e, "title", "").strip()
                dt = entry_datetime(e)

                if not link or not title or not dt:
                    continue
                if dt < since:
                    continue
                if link in seen_links:
                    continue

                seen_links.add(link)
                items.append((dt, title, link))

        items.sort(key=lambda x: x[0], reverse=True)
        items = items[: args.max_per_section]

        lines = [f"## {section}"]
        if not items:
            lines.append("_No new items in the last 24 hours._")
        else:
            for dt, title, link in items:
                lines.append(f"- [{title}]({link}) ({dt.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')})")
        sections.append("\n".join(lines))

    header = [
        "# Daily News Digest",
        f"_Window: last {args.hours}h | Generated: {now.strftime('%Y-%m-%d %H:%M UTC')}_",
        "",
    ]

    content = "\n\n".join(header + sections) + "\n"
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"Wrote {args.out}")

if __name__ == "__main__":
    main()
