#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
build_digest.py
- 抓取 RSS（World / Technology / Business & Economy）
- 生成 digest.md（Markdown）
- 可选：使用 Gemini 生成“简单英语”要点（--use-gemini）

依赖：
  pip install feedparser python-dateutil google-genai

使用：
  python scripts/build_digest.py --out digest.md --hours 24 --max-per-section 8
  python scripts/build_digest.py --out digest.md --hours 24 --max-per-section 8 --use-gemini

工作流里需要注入环境变量：
  GEMINI_API_KEY=你的key
"""

import argparse
import os
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import List, Tuple, Optional

import feedparser

# -----------------------
# RSS 源（你可以自行增减）
# -----------------------
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

# Gemini 模型（可改成你想用的）
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"


def entry_datetime(entry) -> Optional[datetime]:
    """从 RSS entry 提取时间。"""
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


def safe_get(entry, attr: str, default: str = "") -> str:
    v = getattr(entry, attr, default)
    if v is None:
        return default
    return str(v).strip()


def gemini_summarize_simple_english(
    section_name: str,
    items: List[Tuple[str, str]],
    model: str = DEFAULT_GEMINI_MODEL,
) -> str:
    """
    用 Gemini 对一个 section 生成“简单英语”要点。
    items: [(title, link), ...]
    返回：Markdown 文本
    """
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Missing GEMINI_API_KEY environment variable")

    # 延迟导入，避免用户不用 gemini 时也必须装包
    from google import genai  # type: ignore

    client = genai.Client(api_key=api_key)

    # 控制输入长度：只给标题+链接
    src_lines = [f"- {title} ({link})" for title, link in items]
    source_block = "\n".join(src_lines)

    prompt = f"""You write a daily news digest in VERY SIMPLE English.

Section: {section_name}

Task:
1) Write exactly 3 bullet points for the main news.
   - Each bullet <= 12 words
   - Use simple words
2) Write one "Why it matters" sentence (<= 18 words).
3) Do NOT add any extra sections or commentary.

Items:
{source_block}
"""

    resp = client.models.generate_content(
        model=model,
        contents=prompt,
    )

    text = (resp.text or "").strip()
    if not text:
        raise RuntimeError("Gemini returned empty response")
    return text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="digest.md", help="output markdown file")
    ap.add_argument("--hours", type=int, default=24, help="lookback window in hours")
    ap.add_argument("--max-per-section", type=int, default=8, help="max items per section")
    ap.add_argument("--use-gemini", action="store_true", help="generate simple-English key points with Gemini")
    ap.add_argument("--gemini-model", default=DEFAULT_GEMINI_MODEL, help="Gemini model name")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=args.hours)

    seen_links = set()
    sections_md: List[str] = []

    # Header
    header_lines = [
        "# Daily News Digest",
        f"_Window: last {args.hours}h | Generated: {now.strftime('%Y-%m-%d %H:%M UTC')}_",
        "",
    ]

    total_items = 0

    for section, urls in FEEDS.items():
        collected: List[Tuple[datetime, str, str]] = []

        for url in urls:
            feed = feedparser.parse(url)
            for e in getattr(feed, "entries", []):
                link = safe_get(e, "link")
                title = safe_get(e, "title")
                dt = entry_datetime(e)

                if not link or not title or not dt:
                    continue
                if dt < since:
                    continue
                if link in seen_links:
                    continue

                seen_links.add(link)
                collected.append((dt, title, link))

        collected.sort(key=lambda x: x[0], reverse=True)
        collected = collected[: args.max_per_section]
        total_items += len(collected)

        lines: List[str] = [f"## {section}"]

        if not collected:
            lines.append("_No new items in the last window._")
            sections_md.append("\n".join(lines))
            continue

        # Gemini Key Points
        if args.use_gemini:
            simple_items = [(title, link) for (_, title, link) in collected]
            lines.append("### AI Key Points (Simple English)")
            try:
                ai_text = gemini_summarize_simple_english(
                    section_name=section,
                    items=simple_items,
                    model=args.gemini_model,
                )
                lines.append(ai_text)
            except Exception as ex:
                # 不让 AI 失败影响整封邮件
                lines.append(f"_AI summary failed: {ex}_")
            lines.append("")

        # Sources
        lines.append("### Sources")
        for dt, title, link in collected:
            # 只放链接，时间可选；这里不写时间更简洁
            lines.append(f"- [{title}]({link})")

        sections_md.append("\n".join(lines))

    footer_lines = [
        "",
        f"_Total items: {total_items}_",
        "",
    ]

    content = "\n\n".join(header_lines + sections_md + footer_lines) + "\n"

    out_path = args.out
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"Wrote {out_path} with {total_items} items.")


if __name__ == "__main__":
    main()
