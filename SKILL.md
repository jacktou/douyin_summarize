---
name: douyin-summarize
description: Analyze Douyin videos — extract subtitles via BibiGPT API or local whisper, summarize with Kimi (theme, keywords, sentiment).
user-invocable: true
metadata:
  openclaw:
    requires:
      bins:
        - python3
      env:
        - KIMI_API_KEY
    os:
      - linux
      - darwin
---

# Douyin Video Summarizer

Analyze Douyin (抖音) short videos: extract subtitles → AI summarize.

## Two modes

### BibiGPT mode (default, recommended)
Uses BibiGPT cloud API to extract subtitles. **No video download, no ffmpeg, no whisper needed.** Works from any IP.

### Local mode
Downloads video → ffmpeg extracts audio → faster-whisper transcribes → Kimi summarizes. Requires mainland China IP and ffmpeg.

## Usage

When the user sends a Douyin link, run:

```bash
cd /root/workspace/jack/tool/douyin_summarize

# BibiGPT mode (default)
python3 main.py "<douyin_url>"

# Local mode
python3 main.py "<douyin_url>" --mode local

# Multiple videos from user homepage
python3 main.py "<homepage_url>" --max-videos 3
```

## Prerequisites

- `KIMI_API_KEY` — required for both modes
- `BIBIGPT_API_KEY` — required for bibigpt mode (get at https://bibigpt.co)
- For local mode only: `cookies.txt`, `ffmpeg`, `faster-whisper`

## Troubleshooting

- **BibiGPT 401/403**: API key invalid or quota exhausted
- **BibiGPT 422**: Video too long, auto-switches to async task mode
- **Local mode captcha**: Cookies expired, re-export from browser
- **Empty transcript**: Video is pure music/BGM, summary based on title only
