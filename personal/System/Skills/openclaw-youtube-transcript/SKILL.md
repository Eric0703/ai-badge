---
name: youtube-transcript
description: "Transcribe YouTube videos to text. Four-level fallback: Python API → yt-dlp subtitles → browser subtitle extraction → audio download + Whisper speech-to-text. Handles both cloud IP blocking and videos without subtitles."
Keywords: [YouTube, transcribe, transcript, subtitles, captions, browser, playwright, whisper, audio]
license: MIT
allowed-tools: Bash Read
---

# YouTube Transcript

Extract transcripts from YouTube videos with a four-level fallback. Handles two common failure modes: cloud IP blocking by YouTube, and videos that have no subtitles at all.

## When to Use

- Get a transcript or text version of a YouTube video
- Extract spoken content for summarization, analysis, or quoting
- Save captions or subtitles from a video to a file

## Execution Flow

**Try in order — move to the next method only if the previous one fails:**

| Method | Approach | Handles IP block? | Handles no subtitles? |
|--------|----------|-------------------|-----------------------|
| 1 | Python API | No | No |
| 2 | yt-dlp CLI | No | No |
| 3 | Browser subtitle extraction | Yes | No |
| 4 | Browser audio download + Whisper | Yes | Yes |

### Method 1: Python API (fastest, no browser needed)

```bash
pip install youtube-transcript-api  # first-time setup
python3 {baseDir}/scripts/transcribe.py "VIDEO_URL" --timestamps
python3 {baseDir}/scripts/transcribe.py "VIDEO_URL" --timestamps --output transcript.txt
```

| Flag | Default | Description |
|------|---------|-------------|
| `--timestamps` | off | Include timestamps in output |
| `--language` | `en` | Subtitle language code (e.g. `en`, `es`, `fr`) |
| `--output` | stdout | Save transcript to file instead of printing |

If this fails with an IP blocking error, proceed to Method 2.

### Method 2: yt-dlp CLI (fallback)

```bash
pip install yt-dlp  # first-time setup
python3 {baseDir}/scripts/transcribe.py "VIDEO_URL" --timestamps --method ytdlp
```

If this also fails with a bot detection error, proceed to Method 3.

### Method 3: Browser Subtitle Extraction (bypasses IP blocking)

YouTube's IP blocking only targets API/CLI HTTP requests — **not browser rendering**. Even when the video itself cannot play, the transcript panel still loads normally — but only if the video has subtitles.

#### Step 1: Launch browser

```
dispatch ensure-browser-ready
```

If the sandbox browser is unavailable, use `start-cdp-relay` to connect the user's browser.

#### Step 2: Navigate and check subtitle availability

```
1. browser_navigate → https://www.youtube.com/watch?v=VIDEO_ID
2. browser_wait_for → wait 3 seconds for page load
3. browser_snapshot → capture page snapshot, note the video title
```

**IMPORTANT — Check for subtitles before proceeding:**
In the snapshot, look for the subtitles button. If you see:
- `"Subtitles/closed captions unavailable"` → **No subtitles exist. Skip to Method 4.**
- `"Subtitles/closed captions (1)"` or similar → Subtitles available, continue below.

Also check: after clicking "...more", if there is no "Show transcript" button in the expanded description → **Skip to Method 4.**

#### Step 3: Open transcript panel

```
1. Find the "...more" button → browser_click
2. In the expanded description, find "Show transcript" / "内容转文字" button → browser_click
```

**Key**: After clicking "Show transcript", the Playwright accessibility snapshot contains **all transcript data** — no scrolling or pagination needed.

#### Step 4: Extract transcript from snapshot

Transcript data in the snapshot follows this pattern:

```yaml
# Chapter headers
- heading "Chapter X: CHAPTER_TITLE" [level=3] [ref=eNNNN]

# Transcript segments (each is a button element)
- button "TIMESTAMP TEXT_CONTENT" [ref=eNNNN] [cursor=pointer]
  - generic:
    - generic: "0:13"           # numeric timestamp
    - generic: "13 seconds"     # descriptive timestamp (or Chinese "13秒钟")
    - text: "Actual transcript text"  # this is what to extract
```

**Extraction logic**: Iterate button elements in the snapshot. For each button:
- First generic child text → timestamp (e.g. "0:13")
- Last text content → transcript text

Parse directly in the AI agent, or save snapshot to file and use the parsing script:

```bash
python3 {baseDir}/scripts/parse_snapshot.py \
  --input SNAPSHOT_FILE \
  --output OUTPUT_FILE \
  --title "VIDEO_TITLE" \
  --url "YOUTUBE_URL"
```

### Method 4: Audio Download + Whisper (for videos without subtitles)

When a video has **no subtitles/captions at all**, the only option is to download the audio and run speech-to-text. This method uses yt-dlp to download audio through a browser cookie workaround, then transcribes with OpenAI Whisper.

#### Step 1: Ensure browser is ready (reuse from Method 3 if already started)

```
dispatch ensure-browser-ready
```

#### Step 2: Download audio via yt-dlp with cookies

On cloud servers, yt-dlp alone is IP-blocked. But we can extract cookies from the browser session to authenticate:

```bash
# Install dependencies
pip install yt-dlp openai-whisper

# Export cookies from the browser, then download audio only
yt-dlp --cookies-from-browser chromium \
  --extract-audio --audio-format mp3 --audio-quality 5 \
  -o "/tmp/%(id)s.%(ext)s" \
  "VIDEO_URL"
```

If `--cookies-from-browser` fails (e.g. browser profile not accessible), try downloading directly — some videos are less restricted:

```bash
yt-dlp --extract-audio --audio-format mp3 --audio-quality 5 \
  -o "/tmp/%(id)s.%(ext)s" \
  "VIDEO_URL"
```

If both fail, inform the user that the video cannot be transcribed in the cloud environment and suggest running locally.

#### Step 3: Transcribe audio with Whisper

```bash
# For short videos (< 30 min), use the "base" model for speed
whisper "/tmp/VIDEO_ID.mp3" --model base --language auto --output_format txt --output_dir /tmp/

# For longer videos or better accuracy, use "small" or "medium"
whisper "/tmp/VIDEO_ID.mp3" --model small --language auto --output_format txt --output_dir /tmp/
```

Whisper auto-detects the language. For explicitly Chinese videos, add `--language zh`.

The output file will be at `/tmp/VIDEO_ID.txt`. Read it and format into the standard output template.

**Note**: Whisper output does not include per-line timestamps by default. Use `--output_format vtt` or `--output_format srt` if timestamps are needed, then parse accordingly.

#### Step 4: Format output

Read the Whisper output and format it into the standard Markdown template (see Output Format below).

## Output Format

```markdown
# VIDEO_TITLE — YouTube Transcript
> **Creator**: NAME & Moxt · **Created**: YYYY-MM-DD · **Last updated**: YYYY-MM-DD

**Source**: [YouTube - VIDEO_TITLE](URL)
**Duration**: DURATION · **Channel**: CHANNEL

---

[0:00] First line of transcript
[0:13] Second line of transcript
```

## Output Rules

- **NEVER modify the returned transcript content**
- Timestamps: always use numeric format `[M:SS]` or `[H:MM:SS]`
- Chapters: preserve as `## Chapter X: TITLE`
- If the user specifies an output path, save there
- If no output path specified, save as `{VIDEO_ID}-transcript.md`
- If transcribed via Whisper (Method 4), add a note: `**Transcription method**: Audio speech-to-text (Whisper)`
