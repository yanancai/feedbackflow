#!/usr/bin/env python3
"""podideas - Extract podcast topic suggestions from YouTube playlist comments.

A small, self-contained CLI tool that:
  1. Pulls comments from all videos in a YouTube playlist.
  2. Uses Azure OpenAI (gpt-5-chat) to identify suggested topics.
  3. Maintains a local cache so only new comments are processed incrementally.
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

from openai import AzureOpenAI

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
YT_API_BASE = "https://www.googleapis.com/youtube/v3"
DEFAULT_CACHE_DIR = ".podideas_cache"
DEFAULT_OUTPUT = "suggested_topics.json"
DEFAULT_DEPLOYMENT = "gpt-5-chat"

COMMENTS_CACHE_FILE = "comments_cache.json"
VIDEOS_CACHE_FILE = "videos_cache.json"
SUGGESTIONS_FILE = "suggestions.json"

# ---------------------------------------------------------------------------
# YouTube helpers
# ---------------------------------------------------------------------------

def _yt_get(path: str, params: dict) -> dict:
    """Make a GET request to the YouTube Data API v3."""
    qs = urllib.parse.urlencode(params)
    url = f"{YT_API_BASE}/{path}?{qs}"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req) as resp:  # noqa: S310 – URL is built from constant base
        return json.loads(resp.read().decode())


def fetch_video_ids(playlist_id: str, api_key: str) -> list[dict]:
    """Return a list of {id, title, url, uploadDate} for videos in a playlist."""
    videos: list[dict] = []
    page_token: str | None = None
    print(f"Fetching videos from playlist {playlist_id} ...")

    while True:
        params: dict = {
            "part": "snippet",
            "maxResults": 50,
            "playlistId": playlist_id,
            "key": api_key,
        }
        if page_token:
            params["pageToken"] = page_token

        data = _yt_get("playlistItems", params)

        for item in data.get("items", []):
            snippet = item.get("snippet", {})
            vid = snippet.get("resourceId", {}).get("videoId")
            if vid:
                videos.append({
                    "id": vid,
                    "title": snippet.get("title", ""),
                    "url": f"https://www.youtube.com/watch?v={vid}",
                    "uploadDate": snippet.get("publishedAt", ""),
                })

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    print(f"  Found {len(videos)} videos.")
    return videos


def fetch_comments(video_id: str, api_key: str) -> list[dict]:
    """Fetch all comments (including replies) for a video."""
    comments: list[dict] = []
    page_token: str | None = None

    while True:
        params: dict = {
            "part": "snippet,replies",
            "videoId": video_id,
            "key": api_key,
            "maxResults": 100,
        }
        if page_token:
            params["pageToken"] = page_token

        try:
            data = _yt_get("commentThreads", params)
        except urllib.error.HTTPError as exc:
            if exc.code == 403:
                print(f"  Comments disabled for video {video_id}, skipping.")
                return comments
            raise

        for item in data.get("items", []):
            top = item["snippet"]["topLevelComment"]
            comments.append({
                "id": top["id"],
                "author": top["snippet"].get("authorDisplayName", ""),
                "text": top["snippet"].get("textDisplay", ""),
                "publishedAt": top["snippet"].get("publishedAt", ""),
                "videoId": video_id,
            })

            for reply in item.get("replies", {}).get("comments", []):
                comments.append({
                    "id": reply["id"],
                    "author": reply["snippet"].get("authorDisplayName", ""),
                    "text": reply["snippet"].get("textDisplay", ""),
                    "publishedAt": reply["snippet"].get("publishedAt", ""),
                    "videoId": video_id,
                    "parentId": item["id"],
                })

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return comments


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> dict | list:
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_json(path: Path, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)


class Cache:
    """Simple file-backed cache for processed comments and suggestions."""

    def __init__(self, cache_dir: str) -> None:
        self.dir = Path(cache_dir)
        self.dir.mkdir(parents=True, exist_ok=True)

        self._comments_path = self.dir / COMMENTS_CACHE_FILE
        self._videos_path = self.dir / VIDEOS_CACHE_FILE
        self._suggestions_path = self.dir / SUGGESTIONS_FILE

        raw = _load_json(self._comments_path)
        self.processed_comment_ids: set[str] = set(raw.get("processed_ids", []) if isinstance(raw, dict) else [])

        self.videos: dict = _load_json(self._videos_path) if isinstance(_load_json(self._videos_path), dict) else {}
        self.suggestions: list[dict] = _load_json(self._suggestions_path) if isinstance(_load_json(self._suggestions_path), list) else []

    def is_comment_processed(self, comment_id: str) -> bool:
        return comment_id in self.processed_comment_ids

    def mark_comments_processed(self, comment_ids: list[str]) -> None:
        self.processed_comment_ids.update(comment_ids)

    def save(self) -> None:
        _save_json(self._comments_path, {"processed_ids": sorted(self.processed_comment_ids)})
        _save_json(self._videos_path, self.videos)
        _save_json(self._suggestions_path, self.suggestions)


# ---------------------------------------------------------------------------
# Azure OpenAI analysis
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are an assistant that reads YouTube comments and identifies suggestions \
for future podcast episode topics. For each suggestion you find, return a \
JSON object with these fields:
  - "topic": a short title for the suggested topic
  - "detail": a one-sentence summary of what the commenter is asking for
  - "source_comment_id": the comment ID that contains the suggestion
  - "source_author": the author who made the suggestion

Return a JSON array of suggestion objects. If there are no suggestions, \
return an empty array []. Do NOT include any text outside the JSON array.\
"""


def analyze_comments(
    comments: list[dict],
    client: AzureOpenAI,
    deployment: str,
) -> list[dict]:
    """Send a batch of comments to Azure OpenAI and extract topic suggestions."""
    if not comments:
        return []

    # Build a compact representation of comments for the prompt
    lines: list[str] = []
    for c in comments:
        lines.append(f"[{c['id']}] {c['author']}: {c['text']}")
    user_content = "\n".join(lines)

    response = client.chat.completions.create(
        model=deployment,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=0.3,
    )

    raw = response.choices[0].message.content or "[]"
    # Strip markdown code fences if present
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
    if raw.endswith("```"):
        raw = raw.rsplit("```", 1)[0]
    raw = raw.strip()

    try:
        suggestions = json.loads(raw)
        if isinstance(suggestions, list):
            return suggestions
    except json.JSONDecodeError:
        print(f"  Warning: Could not parse AI response as JSON:\n  {raw[:200]}")

    return []


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="podideas",
        description="Extract podcast topic suggestions from YouTube playlist comments.",
    )
    parser.add_argument(
        "-p", "--playlist",
        action="append",
        required=True,
        help="YouTube playlist ID (can be specified multiple times).",
    )
    parser.add_argument(
        "--yt-api-key",
        default=os.environ.get("YT_APIKEY"),
        help="YouTube Data API key (env: YT_APIKEY).",
    )
    parser.add_argument(
        "--aoai-endpoint",
        default=os.environ.get("AZURE_OPENAI_ENDPOINT"),
        help="Azure OpenAI endpoint URL (env: AZURE_OPENAI_ENDPOINT).",
    )
    parser.add_argument(
        "--aoai-api-key",
        default=os.environ.get("AZURE_OPENAI_API_KEY"),
        help="Azure OpenAI API key (env: AZURE_OPENAI_API_KEY).",
    )
    parser.add_argument(
        "--aoai-deployment",
        default=os.environ.get("AZURE_OPENAI_DEPLOYMENT", DEFAULT_DEPLOYMENT),
        help=f"Azure OpenAI deployment name (default: {DEFAULT_DEPLOYMENT}).",
    )
    parser.add_argument(
        "--cache-dir",
        default=DEFAULT_CACHE_DIR,
        help=f"Directory for local cache files (default: {DEFAULT_CACHE_DIR}).",
    )
    parser.add_argument(
        "-o", "--output",
        default=DEFAULT_OUTPUT,
        help=f"Output file for suggested topics (default: {DEFAULT_OUTPUT}).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # Validate required keys
    if not args.yt_api_key:
        parser.error("YouTube API key is required (--yt-api-key or YT_APIKEY env var).")
    if not args.aoai_endpoint:
        parser.error("Azure OpenAI endpoint is required (--aoai-endpoint or AZURE_OPENAI_ENDPOINT env var).")
    if not args.aoai_api_key:
        parser.error("Azure OpenAI API key is required (--aoai-api-key or AZURE_OPENAI_API_KEY env var).")

    cache = Cache(args.cache_dir)

    # --- 1. Fetch videos from playlists ---
    all_videos: dict[str, dict] = {}
    for pl_id in args.playlist:
        for v in fetch_video_ids(pl_id, args.yt_api_key):
            all_videos[v["id"]] = v
            cache.videos[v["id"]] = v

    print(f"\nTotal unique videos: {len(all_videos)}")

    # --- 2. Fetch comments per video, filtering already-processed ones ---
    new_comments: list[dict] = []
    for vid, info in all_videos.items():
        print(f"\nFetching comments for: {info.get('title', vid)}")
        comments = fetch_comments(vid, args.yt_api_key)
        fresh = [c for c in comments if not cache.is_comment_processed(c["id"])]
        print(f"  {len(comments)} total, {len(fresh)} new.")
        new_comments.extend(fresh)

    if not new_comments:
        print("\nNo new comments to process.")
        cache.save()
        _save_json(Path(args.output), cache.suggestions)
        print(f"Output written to {args.output} ({len(cache.suggestions)} suggestions total).")
        return 0

    print(f"\n{len(new_comments)} new comments to analyze with Azure OpenAI ...")

    # --- 3. Analyze with Azure OpenAI in batches ---
    client = AzureOpenAI(
        azure_endpoint=args.aoai_endpoint,
        api_key=args.aoai_api_key,
        api_version="2024-12-01-preview",
    )

    batch_size = 50
    new_suggestions: list[dict] = []
    for i in range(0, len(new_comments), batch_size):
        batch = new_comments[i : i + batch_size]
        print(f"  Analyzing batch {i // batch_size + 1} ({len(batch)} comments) ...")
        suggestions = analyze_comments(batch, client, args.aoai_deployment)
        if suggestions:
            # Attach video metadata to each suggestion
            for s in suggestions:
                cid = s.get("source_comment_id", "")
                matching = [c for c in batch if c["id"] == cid]
                if matching:
                    vid = matching[0]["videoId"]
                    s["video_id"] = vid
                    s["video_title"] = all_videos.get(vid, {}).get("title", "")
                    s["video_url"] = all_videos.get(vid, {}).get("url", "")
            new_suggestions.extend(suggestions)

    # Mark all new comments as processed
    cache.mark_comments_processed([c["id"] for c in new_comments])

    # Merge new suggestions
    if new_suggestions:
        timestamp = datetime.now(timezone.utc).isoformat()
        for s in new_suggestions:
            s["discovered_at"] = timestamp
        cache.suggestions.extend(new_suggestions)
        print(f"\n  Found {len(new_suggestions)} new topic suggestion(s).")
    else:
        print("\n  No new topic suggestions found in this batch.")

    # --- 4. Save ---
    cache.save()
    _save_json(Path(args.output), cache.suggestions)
    print(f"\nOutput written to {args.output} ({len(cache.suggestions)} suggestions total).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
