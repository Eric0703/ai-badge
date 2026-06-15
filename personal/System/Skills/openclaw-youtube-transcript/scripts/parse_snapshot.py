#!/usr/bin/env python3
"""Parse a Playwright accessibility snapshot to extract YouTube transcript.

After clicking "Show transcript" / "内容转文字" on YouTube, the Playwright
accessibility snapshot contains all transcript data as button elements.

This script extracts timestamps and text, outputs clean Markdown.

Usage:
    python3 parse_snapshot.py --input snapshot.txt --output transcript.md \
        --title "Video Title" --url "https://youtube.com/watch?v=..."
"""

import argparse
import json
import re
import sys
from datetime import date


def parse_chinese_timestamp(text):
    """Parse Chinese timestamp like '3小时17分钟55秒钟' into (h, m, s, content)."""
    match = re.match(r'(?:(\d+)小时)?(?:(\d+)分钟)?(?:(\d+)秒钟)?\s*(.*)', text)
    if not match:
        return 0, 0, 0, text
    h = int(match.group(1) or 0)
    m = int(match.group(2) or 0)
    s = int(match.group(3) or 0)
    content = match.group(4)
    return h, m, s, content


def parse_english_timestamp(text):
    """Parse English timestamp like '1 minute, 8 seconds TEXT' into (h, m, s, content)."""
    # Patterns: "8 seconds TEXT", "1 minute, 8 seconds TEXT", "1 hour, 2 minutes, 3 seconds TEXT"
    match = re.match(
        r'(?:(\d+)\s*hours?)?,?\s*(?:(\d+)\s*minutes?)?,?\s*(?:(\d+)\s*seconds?)?\s*(.*)',
        text, re.IGNORECASE
    )
    if not match:
        return 0, 0, 0, text
    h = int(match.group(1) or 0)
    m = int(match.group(2) or 0)
    s = int(match.group(3) or 0)
    content = match.group(4)
    return h, m, s, content


def format_timestamp(h, m, s):
    """Format to [H:MM:SS] or [M:SS]."""
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    elif m > 0:
        return f"{m}:{s:02d}"
    elif s > 0:
        return f"0:{s:02d}"
    else:
        return "0:00"


def extract_transcript(text, min_ref=2800):
    """Extract chapters and transcript segments from snapshot text."""
    lines = text.split('\n')
    output_lines = []
    seen_chapters = set()

    for line in lines:
        # Chapter headers
        ch_match = re.search(r'heading "(第 \d+ 章：[^"]+)"', line)
        if ch_match:
            ch_text = ch_match.group(1)
            if ch_text not in seen_chapters:
                seen_chapters.add(ch_text)
                output_lines.append(('chapter', ch_text))
            continue

        # Transcript segments: button "TEXT" [ref=eNNNN]
        seg_match = re.search(r'button "([^"]{10,})" \[ref=e(\d{4,})\]', line)
        if seg_match:
            full_text = seg_match.group(1)
            ref_num = int(seg_match.group(2))

            if ref_num < min_ref:
                continue

            # Skip chapter buttons
            if full_text.startswith('第 ') and '章：' in full_text:
                continue

            # Try Chinese timestamp first, then English
            h, m, s, content = parse_chinese_timestamp(full_text)
            if h == 0 and m == 0 and s == 0 and content == full_text:
                h, m, s, content = parse_english_timestamp(full_text)

            ts = format_timestamp(h, m, s)

            if h == 0 and m == 0 and s == 0 and content == full_text:
                output_lines.append(('segment', '0:00', full_text))
            else:
                output_lines.append(('segment', ts, content))

    return output_lines, len(seen_chapters)


def build_markdown(entries, title=None, url=None, duration=None, channel=None, chapter_count=0):
    """Build Markdown output."""
    today = date.today().isoformat()

    lines = []
    if title:
        lines.append(f"# {title} — YouTube 逐字稿")
    else:
        lines.append("# YouTube 逐字稿")

    lines.append(f"> **创建者**：Moxt · **创建时间**：{today} · **最后更新**：{today}")
    lines.append("")

    meta = []
    if url:
        display_title = title or "YouTube Video"
        meta.append(f"**来源**：[YouTube - {display_title}]({url})")
    if duration:
        meta.append(f"**时长**：{duration}")
    if channel:
        meta.append(f"**频道**：{channel}")
    if chapter_count > 0:
        meta.append(f"**章节数**：{chapter_count}")

    if meta:
        lines.append(" · ".join(meta))
        lines.append("")

    lines.append("---")
    lines.append("")

    for entry in entries:
        if entry[0] == 'chapter':
            lines.append(f"\n## {entry[1]}\n")
        elif entry[0] == 'segment':
            lines.append(f"[{entry[1]}] {entry[2]}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description='Parse YouTube transcript from Playwright snapshot')
    parser.add_argument('--input', '-i', help='Snapshot file. Reads stdin if omitted.')
    parser.add_argument('--output', '-o', help='Output markdown file')
    parser.add_argument('--title', '-t', help='Video title')
    parser.add_argument('--url', '-u', help='YouTube URL')
    parser.add_argument('--duration', '-d', help='Video duration')
    parser.add_argument('--channel', '-c', help='Channel name')
    parser.add_argument('--min-ref', type=int, default=2800,
                        help='Minimum ref number for transcript buttons (default: 2800)')
    args = parser.parse_args()

    if args.input:
        with open(args.input, 'r') as f:
            raw = f.read()
    else:
        raw = sys.stdin.read()

    # Handle JSON array format (tool results)
    try:
        data = json.loads(raw)
        if isinstance(data, list) and len(data) > 0:
            text = data[0].get('text', raw)
        else:
            text = raw
    except (json.JSONDecodeError, AttributeError):
        text = raw

    entries, chapter_count = extract_transcript(text, min_ref=args.min_ref)

    if not entries:
        print("Error: No transcript data found in snapshot.", file=sys.stderr)
        print("Hint: Make sure you clicked 'Show transcript' and saved the full snapshot.", file=sys.stderr)
        sys.exit(1)

    segment_count = sum(1 for e in entries if e[0] == 'segment')
    print(f"Extracted: {chapter_count} chapters, {segment_count} segments", file=sys.stderr)

    md = build_markdown(entries, title=args.title, url=args.url,
                        duration=args.duration, channel=args.channel,
                        chapter_count=chapter_count)

    if args.output:
        with open(args.output, 'w') as f:
            f.write(md)
        print(f"Saved to: {args.output}", file=sys.stderr)
    else:
        print(md)


if __name__ == '__main__':
    main()
