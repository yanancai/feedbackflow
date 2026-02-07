#!/usr/bin/env python3
"""ytdump (Python) - Dump YouTube comments to JSON.

A Python port of the .NET ytdump tool.  Collects comments from YouTube videos
and playlists and writes them to a JSON file matching the same output schema.

Usage:
    python ytdump.py -v VIDEO_ID [-v VIDEO_ID ...] -k API_KEY
    python ytdump.py -p PLAYLIST_ID -k API_KEY
    python ytdump.py -f yt.json -k API_KEY
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path

from dotenv import load_dotenv

# Load .env file if present
load_dotenv()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
YT_API_BASE = "https://www.googleapis.com/youtube/v3"


# ---------------------------------------------------------------------------
# YouTube API helpers
# ---------------------------------------------------------------------------

def _yt_get(path: str, params: dict) -> dict:
    """Make a GET request to the YouTube Data API v3."""
    qs = urllib.parse.urlencode(params)
    url = f"{YT_API_BASE}/{path}?{qs}"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req) as resp:  # noqa: S310 – URL built from constant base
        return json.loads(resp.read().decode())


def get_video_ids_from_playlist(playlist_id: str, api_key: str) -> list[str]:
    """Fetch all video IDs from a YouTube playlist."""
    video_ids: list[str] = []
    page_token: str | None = None

    print(f"Fetching videos from playlist {playlist_id}")

    while True:
        params: dict = {
            "part": "snippet",
            "maxResults": 50,
            "playlistId": playlist_id,
            "key": api_key,
        }
        if page_token:
            params["pageToken"] = page_token

        try:
            data = _yt_get("playlistItems", params)
        except urllib.error.HTTPError as exc:
            print(f"Error fetching playlist {playlist_id}: {exc}")
            return video_ids

        for item in data.get("items", []):
            vid = item.get("snippet", {}).get("resourceId", {}).get("videoId")
            if vid:
                video_ids.append(vid)

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    print(f"Found {len(video_ids)} videos in playlist {playlist_id}")
    return video_ids


def get_video_info(video_id: str, api_key: str) -> dict | None:
    """Fetch video snippet (title, publishedAt) via the /videos endpoint."""
    try:
        data = _yt_get("videos", {
            "part": "snippet",
            "id": video_id,
            "key": api_key,
        })
    except urllib.error.HTTPError as exc:
        print(f"Error fetching video info for {video_id}: {exc}")
        return None

    items = data.get("items", [])
    if not items:
        return None

    snippet = items[0].get("snippet", {})
    return {
        "id": video_id,
        "title": snippet.get("title", ""),
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "uploadDate": snippet.get("publishedAt", ""),
    }


def get_video_comments(video_id: str, api_key: str) -> list[dict]:
    """Fetch all comment threads (with replies) for a video."""
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
            })

            for reply in item.get("replies", {}).get("comments", []):
                comments.append({
                    "id": reply["id"],
                    "author": reply["snippet"].get("authorDisplayName", ""),
                    "text": reply["snippet"].get("textDisplay", ""),
                    "publishedAt": reply["snippet"].get("publishedAt", ""),
                    "parentId": item["id"],
                })

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return comments


def process_video(video_id: str, api_key: str) -> dict | None:
    """Fetch info + comments for a single video and return an output dict."""
    print(f"Processing Video {video_id}")

    info = get_video_info(video_id, api_key)
    if info is None:
        print(f"Could not fetch video info for video {video_id}")
        return None

    print(f"Video Title: {info['title']}")
    print(f"Video URL: {info['url']}")

    comments = get_video_comments(video_id, api_key)
    info["comments"] = comments
    return info


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ytdump",
        description="Dump YouTube video comments to JSON.",
    )
    parser.add_argument(
        "-v", "--video",
        action="append",
        help="Video ID to process (can be specified multiple times).",
    )
    parser.add_argument(
        "-p", "--playlist",
        action="append",
        help="Playlist ID to process (can be specified multiple times).",
    )
    parser.add_argument(
        "-f", "--file",
        help="JSON config file with Videos and Playlists arrays.",
    )
    parser.add_argument(
        "-k", "--key",
        default=os.environ.get("YT_APIKEY"),
        help="YouTube Data API key (env: YT_APIKEY).",
    )
    parser.add_argument(
        "-o", "--output",
        default="comments.json",
        help="Output file path (default: comments.json).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.key:
        parser.error(
            "A YouTube API key is required. Please specify it via -k/--key "
            "or by using the environment variable YT_APIKEY"
        )

    video_ids: list[str] = list(args.video or [])
    playlist_ids: list[str] = list(args.playlist or [])

    # Load from config file if specified
    if args.file:
        print(f"Config: {args.file}")
        with open(args.file, encoding="utf-8") as f:
            cfg = json.load(f)
        video_ids = list(cfg.get("Videos", []))
        playlist_ids = list(cfg.get("Playlists", []))

    if not video_ids and not playlist_ids:
        parser.error("No videos, playlists or configuration file specified")

    # Print inputs
    if not args.file:
        if playlist_ids:
            print(f"Playlists: {', '.join(playlist_ids)}")
        else:
            print("No playlists specified")
        if video_ids:
            print(f"Videos: {', '.join(video_ids)}")
        else:
            print("No videos specified")

    start = time.monotonic()

    # Expand playlists into video IDs
    for pl_id in playlist_ids:
        video_ids.extend(get_video_ids_from_playlist(pl_id, args.key))

    # Deduplicate video IDs while preserving order
    video_ids = list(dict.fromkeys(video_ids))

    # Process each video
    results: list[dict] = []
    for vid in video_ids:
        result = process_video(vid, args.key)
        if result is not None:
            results.append(result)

    elapsed = time.monotonic() - start

    if results:
        output_path = os.path.abspath(args.output)
        output_dir = os.path.dirname(output_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

        print()
        print(f"Processed {len(results)} videos in {elapsed:.1f}s")
        print(f"Wrote output to {output_path}")
    else:
        print()
        print("No videos processed.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
