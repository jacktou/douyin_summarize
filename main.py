#!/usr/bin/env python3
"""Douyin video batch analysis workflow.

Modes (--mode):
  bibigpt (default)  BibiGPT API extracts content (cloud, any IP)
  local              Download video → whisper transcribes (needs China IP)

Summarizers (--summarizer):
  kimi (default)     Kimi API — structured output (theme/keywords/sentiment)
  bibigpt            BibiGPT built-in summary — one API call, no Kimi needed

Usage:
    python main.py <url>                              # bibigpt + kimi
    python main.py <url> --summarizer bibigpt          # bibigpt only, no kimi
    python main.py <url> --mode local                  # local + kimi
    python main.py <url> --mode local --summarizer bibigpt  # (invalid combo)
"""

import argparse
import json
import logging
import sys
import traceback
from datetime import datetime
from pathlib import Path

from config import load_config

log = logging.getLogger(__name__)


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


# ── Summarization helpers ──────────────────────────────────────

def _summarize_with_kimi(title, description, transcript, author, cfg) -> dict:
    """Call Kimi API, return structured analysis dict."""
    from summarizer import summarize
    s = summarize(
        title=title,
        description=description,
        transcript=transcript,
        author=author,
        api_key=cfg.kimi_api_key,
        base_url=cfg.kimi_base_url,
        model=cfg.kimi_model,
    )
    return {
        "theme": s.theme,
        "keywords": s.keywords,
        "sentiment": s.sentiment,
        "abstract": s.abstract,
        "audience": s.audience,
    }


def _analysis_from_bibigpt_summary(summary_text: str) -> dict:
    """Wrap BibiGPT's plain-text summary into our analysis structure."""
    return {
        "theme": "",
        "keywords": [],
        "sentiment": "",
        "abstract": summary_text,
        "audience": "",
    }


# ── BibiGPT mode ──────────────────────────────────────────────

def process_bibigpt(url: str, cfg, summarizer: str) -> list[dict]:
    """Process URL(s) via BibiGPT API."""
    from bibigpt import fetch_subtitle, fetch_summary

    if not cfg.bibigpt_api_key:
        raise RuntimeError(
            "BIBIGPT_API_KEY not set. Get your token at https://bibigpt.co\n"
            "Then add to config.yaml or env: BIBIGPT_API_KEY=xxx"
        )

    results = []
    urls = _expand_urls(url, cfg)

    for i, vurl in enumerate(urls):
        log.info("[%d/%d] Processing: %s", i + 1, len(urls), vurl)
        try:
            if summarizer == "bibigpt":
                # One call — BibiGPT does both extraction and summarization
                bib = fetch_summary(cfg.bibigpt_api_key, vurl)
                analysis = _analysis_from_bibigpt_summary(bib.summary)
            else:
                # Two calls — BibiGPT extracts, Kimi summarizes
                bib = fetch_subtitle(cfg.bibigpt_api_key, vurl)
                log.info("  Summarizing with Kimi...")
                analysis = _summarize_with_kimi(
                    bib.title, bib.description, bib.transcript, bib.author, cfg,
                )

            log.info("  Title: %s | Author: %s", bib.title, bib.author)

            results.append({
                "video_id": bib.video_id,
                "title": bib.title,
                "author": bib.author,
                "url": bib.url,
                "duration": bib.duration,
                "transcript": bib.transcript,
                "analysis": analysis,
            })

        except Exception as e:
            log.error("Failed: %s: %s", vurl, e)
            log.error("Traceback:\n%s", traceback.format_exc())
            continue

    return results


def _expand_urls(url: str, cfg) -> list[str]:
    """Expand a user homepage URL into individual video URLs if needed."""
    if "/video/" in url or "/note/" in url:
        return [url]

    if "v.douyin.com" in url or "vm.douyin.com" in url:
        return [url]

    if "/user/" in url:
        log.info("User homepage detected — fetching video list")
        try:
            from downloader import _build_client, _extract_sec_uid, _fetch_user_videos
            sec_uid = _extract_sec_uid(url)
            if sec_uid:
                client = _build_client(cfg.cookies_path, proxy=cfg.proxy or None)
                video_ids = _fetch_user_videos(client, sec_uid, cfg.max_videos)
                client.close()
                if video_ids:
                    return [f"https://www.douyin.com/video/{vid}" for vid in video_ids]
        except Exception as e:
            log.warning("Failed to fetch video list: %s", e)

        return [url]

    return [url]


# ── Local mode ─────────────────────────────────────────────────

def process_local(url: str, cfg) -> list[dict]:
    """Process via local download → whisper → Kimi."""
    from downloader import download_videos
    from transcriber import transcribe

    log.info("[Download] Fetching up to %d video(s): %s", cfg.max_videos, url)
    proxy = cfg.proxy or None
    videos = download_videos(
        douyin_url=url,
        output_dir=cfg.output_dir,
        cookies_path=cfg.cookies_path,
        max_videos=cfg.max_videos,
        proxy=proxy,
    )

    results = []
    for video in videos:
        log.info("=" * 50)
        log.info("Processing: %s", video.title or video.video_id)

        log.info("[Step 1/2] Transcribing...")
        try:
            t = transcribe(
                video_path=video.filepath,
                model_size=cfg.whisper_model,
                device=cfg.whisper_device,
                compute_type=cfg.whisper_compute_type,
            )
            transcript_text = t.text
        except Exception as e:
            log.warning("Transcription failed: %s — using title only", e)
            transcript_text = ""

        log.info("[Step 2/2] Summarizing with Kimi...")
        try:
            analysis = _summarize_with_kimi(
                video.title, video.description, transcript_text, video.author, cfg,
            )
            results.append({
                "video_id": video.video_id,
                "title": video.title,
                "author": video.author,
                "url": video.url,
                "duration": video.duration,
                "transcript": transcript_text,
                "analysis": analysis,
            })
        except Exception as e:
            log.error("Failed: %s: %s", video.video_id, e)
            log.error("Traceback:\n%s", traceback.format_exc())
            continue

    return results


# ── Output ─────────────────────────────────────────────────────

def save_results(results: list[dict], output_dir: str) -> str:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    json_path = out / f"analysis_{ts}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    md_path = out / f"analysis_{ts}.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# 抖音视频分析报告\n\n")
        f.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

        for i, r in enumerate(results, 1):
            a = r["analysis"]
            f.write(f"---\n\n## {i}. {r['title']}\n\n")
            f.write(f"- **作者**: {r['author']}\n")
            f.write(f"- **链接**: {r['url']}\n")
            if r.get("duration"):
                f.write(f"- **时长**: {r['duration']:.0f}s\n")

            # Structured fields (Kimi mode)
            if a.get("theme"):
                f.write(f"\n### 分析结果\n\n")
                f.write(f"| 维度 | 内容 |\n|------|------|\n")
                f.write(f"| 主题 | {a['theme']} |\n")
                f.write(f"| 关键词 | {', '.join(a['keywords']) if a['keywords'] else '-'} |\n")
                f.write(f"| 情绪基调 | {a['sentiment']} |\n")
                f.write(f"| 目标受众 | {a['audience']} |\n")
                f.write(f"\n**内容摘要**: {a['abstract']}\n\n")
            elif a.get("abstract"):
                # Plain summary (BibiGPT summarizer mode)
                f.write(f"\n### AI 总结\n\n{a['abstract']}\n\n")

            if r.get("transcript"):
                preview = r["transcript"][:300]
                if len(r["transcript"]) > 300:
                    preview += "..."
                f.write(f"<details><summary>语音转录（前300字）</summary>\n\n")
                f.write(f"{preview}\n\n</details>\n\n")

    log.info("JSON: %s", json_path)
    log.info("Report: %s", md_path)
    return str(json_path)


def print_summary(results: list[dict], output_path: str):
    print("\n" + "=" * 60)
    print("ANALYSIS COMPLETE")
    print("=" * 60)
    for r in results:
        a = r["analysis"]
        print(f"\n[{r['title']}]")
        if r.get("author"):
            print(f"  Author:    {r['author']}")
        if a.get("theme"):
            print(f"  Theme:     {a['theme']}")
            print(f"  Keywords:  {', '.join(a['keywords']) if a['keywords'] else '-'}")
            print(f"  Sentiment: {a['sentiment']}")
        if a.get("abstract"):
            # Truncate long BibiGPT summaries for terminal display
            abstract = a["abstract"]
            if len(abstract) > 300:
                abstract = abstract[:300] + "..."
            print(f"  Summary:   {abstract}")
    print(f"\nFull report: {output_path}")


# ── CLI ────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Douyin video analysis: subtitle extraction → AI summary"
    )
    parser.add_argument("url", help="Douyin video URL, user homepage, or short link")
    parser.add_argument(
        "--mode", "-m",
        choices=["bibigpt", "local"],
        default="bibigpt",
        help="Content extraction: bibigpt (cloud API, default) or local (download+whisper)",
    )
    parser.add_argument(
        "--summarizer", "-s",
        choices=["kimi", "bibigpt"],
        default="kimi",
        help="Summarizer: kimi (structured, default) or bibigpt (built-in, no Kimi key needed)",
    )
    parser.add_argument("--max-videos", "-n", type=int, default=None)
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--proxy", default=None)

    args = parser.parse_args()
    setup_logging(args.verbose)

    # Validate combos
    if args.mode == "local" and args.summarizer == "bibigpt":
        log.error("Invalid: --mode local --summarizer bibigpt. "
                  "Local mode requires --summarizer kimi.")
        sys.exit(1)

    cfg = load_config()
    if args.max_videos is not None:
        cfg.max_videos = args.max_videos

    # Check required API keys
    if args.summarizer == "kimi" and not cfg.kimi_api_key:
        log.error("KIMI_API_KEY not set. Use --summarizer bibigpt or configure Kimi key.")
        sys.exit(1)

    mode = args.mode
    summarizer = args.summarizer
    log.info("Mode: %s | Summarizer: %s", mode, summarizer)

    try:
        if mode == "bibigpt":
            results = process_bibigpt(args.url, cfg, summarizer)
        else:
            results = process_local(args.url, cfg)
    except Exception as e:
        log.error("%s", e)
        log.error("Traceback:\n%s", traceback.format_exc())
        sys.exit(1)

    if not results:
        log.error("No videos processed successfully.")
        sys.exit(1)

    output_path = save_results(results, cfg.output_dir)
    print_summary(results, output_path)


if __name__ == "__main__":
    main()
