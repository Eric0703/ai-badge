#!/usr/bin/env python3
"""YouTube video transcription with multi-method fallback.

Method 1 (default): youtube-transcript-api — fast Python API, no browser needed.
Method 2 (--method ytdlp): yt-dlp CLI — fetches subtitle files directly.

If both fail with IP blocking errors (common on cloud servers), the SKILL.md
instructs the AI agent to use Method 3: browser-based extraction via Playwright.
"""

import argparse
import glob
import os
import re
import subprocess
import sys
import tempfile


def extract_video_id(url_or_id: str) -> str:
    """Extract video ID from various YouTube URL formats."""
    patterns = [
        r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/|youtube\.com/v/)([a-zA-Z0-9_-]{11})',
        r'^([a-zA-Z0-9_-]{11})$'
    ]
    for pattern in patterns:
        match = re.search(pattern, url_or_id)
        if match:
            return match.group(1)
    raise ValueError(f"Could not extract video ID from: {url_or_id}")


# ── Method 1: youtube-transcript-api ──

def transcribe_api(url: str, language: str, with_timestamps: bool) -> str:
    """Fetch transcript using youtube-transcript-api Python library."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        print("Installing youtube-transcript-api...", file=sys.stderr)
        subprocess.check_call([sys.executable, "-m", "pip", "install", "youtube-transcript-api"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        from youtube_transcript_api import YouTubeTranscriptApi

    video_id = extract_video_id(url)
    api = YouTubeTranscriptApi()
    transcript = api.fetch(video_id, languages=[language])

    if with_timestamps:
        lines = []
        for snippet in transcript.snippets:
            ts = format_seconds(snippet.start)
            lines.append(f"[{ts}] {snippet.text}")
        return "\n".join(lines)
    else:
        return "\n".join(snippet.text for snippet in transcript.snippets)


def format_seconds(seconds: float) -> str:
    """Convert seconds to M:SS or H:MM:SS format."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


# ── Method 2: yt-dlp CLI ──

def transcribe_ytdlp(url: str, language: str, with_timestamps: bool) -> str:
    """Fetch transcript using yt-dlp CLI to download subtitle files."""
    # Ensure yt-dlp is installed
    if subprocess.run(["which", "yt-dlp"], capture_output=True).returncode != 0:
        print("Installing yt-dlp...", file=sys.stderr)
        subprocess.check_call([sys.executable, "-m", "pip", "install", "yt-dlp"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    with tempfile.TemporaryDirectory() as tmpdir:
        cmd = [
            "yt-dlp",
            "--skip-download",
            "--write-subs",
            "--write-auto-subs",
            "--sub-langs", language,
            "--sub-format", "vtt",
            "--output", os.path.join(tmpdir, "video.%(ext)s"),
            "--quiet",
            "--no-warnings",
            "--socket-timeout", "10",
            url,
        ]

        print(f"Fetching subtitles via yt-dlp from: {url}", file=sys.stderr)
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"yt-dlp failed:\n{result.stderr}")

        vtt_files = glob.glob(os.path.join(tmpdir, "*.vtt"))
        if not vtt_files:
            raise RuntimeError("No subtitles found for this video.")

        with open(vtt_files[0], encoding="utf-8") as f:
            raw = f.read()

    return strip_vtt(raw, with_timestamps)


def strip_vtt(text: str, with_timestamps: bool = False) -> str:
    """Extract text (and optionally timestamps) from WebVTT format."""
    lines = []
    seen = set()
    current_ts = None

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("WEBVTT"):
            continue

        # Timestamp line: 00:00:13.000 --> 00:00:17.000
        ts_match = re.match(r'^(\d{2}:\d{2}:\d{2})\.\d+\s*-->', line)
        if ts_match:
            raw_ts = ts_match.group(1)  # HH:MM:SS
            h, m, s = raw_ts.split(":")
            h, m, s = int(h), int(m), int(s)
            if h > 0:
                current_ts = f"{h}:{m:02d}:{s:02d}"
            else:
                current_ts = f"{m}:{s:02d}"
            continue

        if re.match(r'^\d{2}:\d{2}', line) or '-->' in line:
            continue

        line = re.sub(r'<[^>]+>', '', line)
        if line and line not in seen:
            seen.add(line)
            if with_timestamps and current_ts:
                lines.append(f"[{current_ts}] {line}")
                current_ts = None  # Only attach timestamp to first line of each cue
            else:
                lines.append(line)

    return "\n".join(lines)


# ── Main ──

def main():
    parser = argparse.ArgumentParser(
        description="Transcribe YouTube video. Tries Python API first, falls back to yt-dlp."
    )
    parser.add_argument("url", help="YouTube video URL or ID")
    parser.add_argument("--language", default="en", help="Subtitle language code (default: en)")
    parser.add_argument("--timestamps", action="store_true", help="Include timestamps in output")
    parser.add_argument("--output", default=None, help="Save to file instead of stdout")
    parser.add_argument("--method", choices=["api", "ytdlp"], default="api",
                        help="Force a specific method (default: api, auto-fallback to ytdlp)")
    args = parser.parse_args()

    transcript = None
    errors = []

    if args.method == "api":
        # Try API first
        try:
            print("Method 1: Trying youtube-transcript-api...", file=sys.stderr)
            transcript = transcribe_api(args.url, args.language, args.timestamps)
        except Exception as e:
            errors.append(f"[API] {e}")
            print(f"Method 1 failed: {e}", file=sys.stderr)

            # Auto-fallback to yt-dlp
            try:
                print("Method 2: Falling back to yt-dlp...", file=sys.stderr)
                transcript = transcribe_ytdlp(args.url, args.language, args.timestamps)
            except Exception as e2:
                errors.append(f"[yt-dlp] {e2}")
                print(f"Method 2 failed: {e2}", file=sys.stderr)

    elif args.method == "ytdlp":
        try:
            print("Trying yt-dlp...", file=sys.stderr)
            transcript = transcribe_ytdlp(args.url, args.language, args.timestamps)
        except Exception as e:
            errors.append(f"[yt-dlp] {e}")
            print(f"yt-dlp failed: {e}", file=sys.stderr)

    if transcript is None:
        print("\n".join([
            "Error: All transcription methods failed.",
            "This is usually caused by YouTube blocking cloud server IPs.",
            "",
            "→ Use Method 3 (browser-based extraction) as described in SKILL.md:",
            "  1. ensure-browser-ready (start Playwright browser)",
            "  2. Navigate to video URL",
            "  3. Click '...more' → 'Show transcript'",
            "  4. Extract from accessibility snapshot",
            "",
            "Errors encountered:",
            *[f"  {e}" for e in errors],
        ]), file=sys.stderr)
        sys.exit(1)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(transcript)
        print(f"Transcript saved to: {args.output}", file=sys.stderr)
    else:
        print(transcript)


if __name__ == "__main__":
    main()
