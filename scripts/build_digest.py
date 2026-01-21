#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
scripts/build_digest.py

功能：
- 抓取 RSS（World / Technology / Business & Economy）
- 生成 digest.md（Markdown）
- 可选：只调用 1 次 Gemini，把三个栏目合并生成“今日要点”（--use-gemini）

依赖：
  pip install feedparser python-dateutil google-genai

用法：
  python scripts/build_digest.py --out digest.md --hours 24 --max-per-section 8
  python scripts/build_digest.py --out digest.md --hours 24 --max-per-section 8 --use-gemini

工作流里需要注入环境变量（只有使用 --use-gemini 才需要）：
  GEMINI_API_KEY=你的key
"""

import argparse
import os
from zoneinfo import ZoneInfo
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Dict, List, Optional, Tuple

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

# Gemini 模型（可改）
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


def gemini_summarize_whole_digest_simple_english(
    items_by_section: Dict[str, List[Tuple[str, str]]],
    model: str = DEFAULT_GEMINI_MODEL,
) -> str:
    """
    只调用 1 次 Gemini，总结整个 digest 的要点（简单英语）。
    items_by_section: {"World":[(title, link),...], "Technology":[...], ...}
    返回：Markdown 文本
    """
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Missing GEMINI_API_KEY environment variable")

    # 延迟导入：不用 gemini 时不要求安装 SDK
    from google import genai  # type: ignore

    client = genai.Client(api_key=api_key)

    # 控制输入长度：只给标题 + 链接
    blocks: List[str] = []
    for sec, items in items_by_section.items():
        if not items:
            continue
        # 这里可以按需要进一步截断，比如每个 section 只给前 N 条
        lines = "\n".join([f"- {t} ({l})" for t, l in items])
        blocks.append(f"{sec}:\n{lines}")
    source_block = "\n\n".join(blocks)

    prompt = f"""You write a daily news digest in VERY SIMPLE English.

From the items below, produce exactly the following sections and nothing else:

Top 5 Today:
- (exactly 5 bullets, each <= 12 words, simple words)

Why it matters:
(exactly 2 short sentences, each <= 16 words)

Watch next:
- (exactly 3 bullets, each <= 10 words)

Rules:
- Use easy words.
- Do NOT add extra commentary.
- Do NOT add extra headings beyond the required ones.

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
    ap.add_argument("--use-gemini", action="store_true", help="generate simple-English key points with Gemini (1 call)")
    ap.add_argument("--gemini-model", default=DEFAULT_GEMINI_MODEL, help="Gemini model name")
    args = ap.parse_args()

    # ---- 只在柏林时间 07:00 执行（全年固定）----
    berlin_now = datetime.now(ZoneInfo("Europe/Berlin"))
    if not (berlin_now.hour == 7 and berlin_now.minute == 0):
        print(f"Skip: Berlin time is {berlin_now.strftime('%H:%M')}, not 07:00.")
        return


    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=args.hours)

    seen_links = set()

    # 先收集所有 section 的新闻
    collected_by_section: Dict[str, List[Tuple[datetime, str, str]]] = {}
    items_by_section_for_ai: Dict[str, List[Tuple[str, str]]] = {}

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

        collected_by_section[section] = collected
        items_by_section_for_ai[section] = [(title, link) for (_, title, link) in collected]
        total_items += len(collected)

    # Header
    header_lines = [
        "# Daily News Digest",
        f"_Window: last {args.hours}h | Generated: {now.strftime('%Y-%m-%d %H:%M UTC')}_",
        "",
    ]

    # 只调用一次 Gemini，生成总览要点，插在邮件最顶部
    ai_block: List[str] = []
    if args.use_gemini:
        ai_block.append("## AI Key Points (Simple English)")
        try:
            ai_text = gemini_summarize_whole_digest_simple_english(
                items_by_section=items_by_section_for_ai,
                model=args.gemini_model,
            )
            ai_block.append(ai_text)
        except Exception as ex:
            # AI 失败不影响整封邮件
            ai_block.append(f"_AI summary failed: {ex}_")
        ai_block.append("")

    # 各栏目 Sources
    sections_md: List[str] = []
    for section in FEEDS.keys():
        lines: List[str] = [f"## {section}"]
        collected = collected_by_section.get(section, [])

        if not collected:
            lines.append("_No new items in the last window._")
            sections_md.append("\n".join(lines))
            continue

        lines.append("### Sources")
        for _, title, link in collected:
            lines.append(f"- [{title}]({link})")

        sections_md.append("\n".join(lines))

    footer_lines = [
        "",
        f"_Total items: {total_items}_",
        "",
    ]

    content = "\n\n".join(header_lines + ai_block + sections_md + footer_lines) + "\n"

    out_path = args.out
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"Wrote {out_path} with {total_items} items.")


if __name__ == "__main__":
    main()
