"""Douyin video downloader via iesdouyin.com SSR endpoint.

Uses the mobile share page which returns server-rendered data
without triggering captcha. Requires mainland China IP or proxy.
"""

import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import httpx

log = logging.getLogger(__name__)

MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/16.6 Mobile/15E148 Safari/604.1"
)
DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


@dataclass
class VideoInfo:
    video_id: str
    title: str
    description: str
    author: str
    url: str
    filepath: str
    duration: Optional[float] = None


def _load_cookies_as_dict(cookies_path: str) -> dict:
    """Load Netscape cookies.txt into a dict."""
    cookies = {}
    with open(cookies_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 7 and parts[5]:
                cookies[parts[5]] = parts[6]
    return cookies


def _build_client(cookies_path: str, proxy: str = None) -> httpx.Client:
    """Build an httpx client with cookies and optional proxy."""
    cookies = _load_cookies_as_dict(cookies_path)
    return httpx.Client(
        cookies=cookies,
        headers={
            "User-Agent": MOBILE_UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        },
        follow_redirects=True,
        timeout=30,
        proxy=proxy,
    )


def _extract_router_data(html: str) -> Optional[dict]:
    """Extract _ROUTER_DATA JSON from page HTML."""
    m = re.search(r'window\._ROUTER_DATA\s*=\s*(\{.*\})\s*</script>', html, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as e:
        log.warning("Failed to parse _ROUTER_DATA: %s", e)
        return None


def _extract_video_id(url: str) -> Optional[str]:
    """Extract video ID from various Douyin URL formats."""
    m = re.search(r"(?:video|note)/(\d+)", url)
    return m.group(1) if m else None


def _resolve_share_url(client: httpx.Client, url: str) -> str:
    """Resolve short share URLs (v.douyin.com) to full URLs."""
    if "v.douyin.com" in url or "vm.douyin.com" in url:
        log.info("Resolving short URL: %s", url)
        r = client.get(url)
        resolved = str(r.url)
        log.info("Resolved to: %s", resolved)
        return resolved
    return url


def _deep_find(obj, target_key, max_depth=10):
    """Recursively search for a key in nested dicts/lists."""
    if max_depth <= 0 or obj is None:
        return None
    if isinstance(obj, dict):
        if target_key in obj and obj[target_key] is not None:
            return obj[target_key]
        for v in obj.values():
            result = _deep_find(v, target_key, max_depth - 1)
            if result is not None:
                return result
    elif isinstance(obj, list):
        for item in obj:
            result = _deep_find(item, target_key, max_depth - 1)
            if result is not None:
                return result
    return None


def _try_no_watermark_url(url: str) -> str:
    """Rewrite playwm URL to play (no watermark) variant."""
    if "playwm" in url:
        return url.replace("playwm", "play")
    return url


def _extract_video_from_item(item: dict) -> dict:
    """Safely extract video info from an aweme/item dict."""
    video = item.get("video") or {}
    play_addr = video.get("play_addr") or {}
    url_list = play_addr.get("url_list") or []

    download_url = ""

    # Try bit_rate list for higher quality (may be null)
    bit_rate = video.get("bit_rate") or []
    for br in bit_rate:
        if not isinstance(br, dict):
            continue
        br_play = br.get("play_addr") or {}
        br_urls = br_play.get("url_list") or []
        if br_urls:
            download_url = br_urls[0]
            break

    # Fallback to play_addr
    if not download_url and url_list:
        download_url = url_list[0]

    # Fallback: check download_addr
    if not download_url:
        dl_addr = video.get("download_addr") or {}
        dl_urls = dl_addr.get("url_list") or []
        if dl_urls:
            download_url = dl_urls[0]

    # Try to get non-watermark URL
    if download_url:
        download_url = _try_no_watermark_url(download_url)

    desc = item.get("desc", "")
    author_info = item.get("author") or {}
    author = author_info.get("nickname", "") if isinstance(author_info, dict) else ""

    # duration: video.duration is in ms, music.duration is in seconds
    raw_duration = video.get("duration", 0) or 0
    if raw_duration > 10000:
        duration = raw_duration / 1000  # ms -> s
    else:
        duration = float(raw_duration) if raw_duration else None

    return {
        "video_url": download_url,
        "title": desc,
        "description": desc,
        "author": author,
        "duration": duration,
    }


def _fetch_video_detail(client: httpx.Client, video_id: str, output_dir: str = "") -> dict:
    """Fetch video detail from iesdouyin share page."""
    url = f"https://www.iesdouyin.com/share/video/{video_id}"
    log.info("Fetching video detail: %s", url)

    r = client.get(url)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code} fetching {url}")

    html = r.text

    # Check for captcha
    if "验证码中间页" in html[:1000] or "captcha" in html[:1000].lower():
        raise RuntimeError(
            "Captcha triggered. Possible causes:\n"
            "  1. Cookies expired — re-export from browser\n"
            "  2. Server IP blocked — use a mainland China proxy"
        )

    data = _extract_router_data(html)
    if not data:
        # Dump raw HTML for debugging
        if output_dir:
            dump_path = Path(output_dir) / f"{video_id}_debug.html"
            dump_path.write_text(html, encoding="utf-8")
            log.info("Debug HTML dumped to: %s", dump_path)
        raise RuntimeError("_ROUTER_DATA not found in page — page structure may have changed")

    # Dump full _ROUTER_DATA for debugging
    if output_dir:
        dump_path = Path(output_dir) / f"{video_id}_router_data.json"
        dump_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info("Debug _ROUTER_DATA dumped to: %s", dump_path)

    loader = data.get("loaderData") or {}
    log.debug("loaderData keys: %s", list(loader.keys()))

    # Strategy 1: Find videoInfoRes in loaderData values
    vinfo = None
    for key, val in loader.items():
        if not isinstance(val, dict):
            continue
        if "videoInfoRes" in val:
            vinfo = val["videoInfoRes"]
            log.debug("Found videoInfoRes under key: %s", key)
            break

    # Strategy 2: deep search for item_list
    item = None

    if isinstance(vinfo, dict):
        # Check for geo-restriction
        filters = vinfo.get("filter_list") or []
        if filters and isinstance(filters, list):
            reasons = []
            for f in filters:
                if isinstance(f, dict):
                    reasons.append(f.get("filter_reason", "unknown"))
            if vinfo.get("is_oversea"):
                raise RuntimeError(
                    f"Video geo-restricted (is_oversea=1). Filter: {reasons}\n"
                    "This server's IP is outside mainland China.\n"
                    "Solutions:\n"
                    "  1. Deploy on a server in mainland China\n"
                    "  2. Use a mainland China proxy (set proxy in config.yaml)"
                )
            if reasons and all(r != "0" for r in reasons):
                raise RuntimeError(f"Video filtered: {reasons}")

        items = vinfo.get("item_list") or []
        if items and isinstance(items, list):
            item = items[0]

    # Strategy 3: deep search for awemeDetail or aweme_detail
    if not item:
        for search_key in ("awemeDetail", "aweme_detail", "awemeInfo"):
            found = _deep_find(data, search_key)
            if isinstance(found, dict):
                item = found
                log.debug("Found video data via deep search key: %s", search_key)
                break

    # Strategy 4: deep search for item_list anywhere
    if not item:
        found_list = _deep_find(data, "item_list")
        if isinstance(found_list, list) and found_list:
            item = found_list[0]
            log.debug("Found video data via deep search for item_list")

    if not isinstance(item, dict):
        # Provide diagnostic info
        available_keys = []
        for key, val in loader.items():
            if isinstance(val, dict):
                available_keys.append(f"{key}: {list(val.keys())[:10]}")
        raise RuntimeError(
            f"Could not find video data in _ROUTER_DATA.\n"
            f"loaderData structure:\n  " + "\n  ".join(available_keys) + "\n"
            f"Check {video_id}_router_data.json in output dir for full dump."
        )

    return _extract_video_from_item(item)


def _fetch_user_videos(client: httpx.Client, sec_uid: str, max_videos: int) -> list[str]:
    """Fetch video IDs from user's post list via iesdouyin user page."""
    url = f"https://www.iesdouyin.com/share/user/{sec_uid}"
    log.info("Fetching user page: %s", url)

    r = client.get(url)
    html = r.text

    if "验证码中间页" in html[:1000]:
        raise RuntimeError("User page captcha triggered — try using direct video URLs instead")

    data = _extract_router_data(html)
    if not data:
        # Fallback: extract video IDs from HTML links
        video_ids = re.findall(r'/video/(\d+)', html)
        return list(dict.fromkeys(video_ids))[:max_videos]

    # Parse from loaderData
    loader = data.get("loaderData", {})
    video_ids = []
    for key, val in loader.items():
        if not isinstance(val, dict):
            continue
        # Look for post list
        post_data = val.get("post", {})
        aweme_list = post_data.get("data", post_data.get("aweme_list", []))
        for aweme in aweme_list:
            aid = aweme.get("awemeId") or aweme.get("aweme_id")
            if aid:
                video_ids.append(aid)

    return video_ids[:max_videos]


def _extract_sec_uid(url: str) -> Optional[str]:
    """Extract sec_uid from user homepage URL."""
    m = re.search(r'/user/([A-Za-z0-9_-]+)', url)
    return m.group(1) if m else None


def _download_video_file(client: httpx.Client, video_url: str, dest: str):
    """Download video file."""
    # Video CDN may need different headers
    headers = {
        "User-Agent": DESKTOP_UA,
        "Referer": "https://www.douyin.com/",
    }
    with client.stream("GET", video_url, headers=headers) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_bytes(chunk_size=8192):
                f.write(chunk)
    size = Path(dest).stat().st_size
    log.info("Downloaded: %s (%d bytes)", Path(dest).name, size)
    if size < 1000:
        raise RuntimeError(f"Downloaded file too small ({size} bytes) — likely not a valid video")


def download_videos(
    douyin_url: str,
    output_dir: str,
    cookies_path: str,
    max_videos: int = 1,
    proxy: str = None,
) -> list[VideoInfo]:
    """Download latest videos from a Douyin URL.

    Args:
        douyin_url: Douyin user homepage or single video URL.
        output_dir: Directory to save downloaded videos.
        cookies_path: Path to Netscape-format cookies.txt.
        max_videos: Number of latest videos to download.
        proxy: Optional HTTP proxy URL (e.g. http://127.0.0.1:7890).

    Returns:
        List of VideoInfo for successfully downloaded videos.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not Path(cookies_path).exists():
        raise FileNotFoundError(
            f"Cookies file not found: {cookies_path}\n"
            "Export cookies from your browser and save as cookies.txt"
        )

    client = _build_client(cookies_path, proxy=proxy)

    # Resolve short URLs
    douyin_url = _resolve_share_url(client, douyin_url)

    # Determine if this is a user homepage or single video
    video_ids = []
    sec_uid = _extract_sec_uid(douyin_url)
    vid = _extract_video_id(douyin_url)

    if vid:
        video_ids = [vid]
    elif sec_uid:
        log.info("User homepage detected (sec_uid=%s...)", sec_uid[:20])
        video_ids = _fetch_user_videos(client, sec_uid, max_videos)
    else:
        raise ValueError(
            f"Unsupported URL format: {douyin_url}\n"
            "Supported formats:\n"
            "  - https://www.douyin.com/video/VIDEO_ID\n"
            "  - https://www.douyin.com/user/SEC_UID\n"
            "  - https://v.douyin.com/SHORTCODE"
        )

    if not video_ids:
        raise RuntimeError("No video IDs found.")

    log.info("Processing %d video(s): %s", len(video_ids), video_ids)

    # Fetch and download each video
    videos = []
    for i, video_id in enumerate(video_ids[:max_videos]):
        log.info("[%d/%d] Video: %s", i + 1, min(len(video_ids), max_videos), video_id)

        try:
            detail = _fetch_video_detail(client, video_id, output_dir=output_dir)
            video_download_url = detail["video_url"]

            if not video_download_url:
                log.warning("No download URL for %s, skipping", video_id)
                continue

            filepath = str(out_dir / f"{video_id}.mp4")
            _download_video_file(client, video_download_url, filepath)

            # Save metadata
            meta_path = str(out_dir / f"{video_id}.meta.json")
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(detail, f, ensure_ascii=False, indent=2)

            videos.append(VideoInfo(
                video_id=video_id,
                title=detail["title"],
                description=detail["description"],
                author=detail["author"],
                url=f"https://www.douyin.com/video/{video_id}",
                filepath=filepath,
                duration=detail["duration"],
            ))

        except Exception as e:
            log.error("Failed to process video %s: %s", video_id, e)
            continue

        # Rate limit between videos
        if i < len(video_ids) - 1:
            time.sleep(2)

    client.close()

    if not videos:
        raise RuntimeError("No videos downloaded successfully.")

    log.info("Downloaded %d video(s)", len(videos))
    return videos
