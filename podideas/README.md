# podideas - Podcast Idea Extractor

A small, self-contained Python CLI toolkit that pulls YouTube comments and uses Azure OpenAI (gpt-5-chat) to identify suggested podcast topics.

## Tools

| Script | Description |
|---|---|
| `ytdump.py` | Dump YouTube video/playlist comments to JSON (Python port of the .NET `ytdump`) |
| `podideas.py` | Analyze comments with Azure OpenAI to extract podcast topic suggestions |

## Prerequisites

- Python 3.9+
- A YouTube Data API v3 key
- Azure OpenAI endpoint and API key with access to the `gpt-5-chat` model (for `podideas.py`)

## Installation

```bash
cd podideas
pip install -r requirements.txt
```

## ytdump.py — YouTube Comment Dumper

A Python port of the .NET `ytdump` tool. Dumps all comments from YouTube videos
and playlists into a JSON file with the same output format.

### Usage

```bash
# Dump comments for specific videos
python ytdump.py -v VIDEO_ID -k YOUR_API_KEY

# Dump comments for all videos in a playlist
python ytdump.py -p PLAYLIST_ID -k YOUR_API_KEY

# Use a config file (same format as the .NET ytdump yt.json)
python ytdump.py -f yt.json -k YOUR_API_KEY

# API key can also come from .env or YT_APIKEY env var
python ytdump.py -p PLAYLIST_ID
```

### Options

| Flag | Description |
|---|---|
| `-v`, `--video` | Video ID to process (can be specified multiple times) |
| `-p`, `--playlist` | Playlist ID to process (can be specified multiple times) |
| `-f`, `--file` | JSON config file with `Videos` and `Playlists` arrays |
| `-k`, `--key` | YouTube Data API key (env: `YT_APIKEY`) |
| `-o`, `--output` | Output file path (default: `comments.json`) |

### Output Format

The output is a JSON array of video objects:

```json
[
  {
    "id": "VIDEO_ID",
    "title": "Video Title",
    "url": "https://www.youtube.com/watch?v=VIDEO_ID",
    "uploadDate": "2024-01-01T00:00:00Z",
    "comments": [
      {
        "id": "COMMENT_ID",
        "author": "User Name",
        "text": "Comment text",
        "publishedAt": "2024-01-02T00:00:00Z"
      },
      {
        "id": "REPLY_ID",
        "author": "Another User",
        "text": "Reply text",
        "publishedAt": "2024-01-03T00:00:00Z",
        "parentId": "COMMENT_THREAD_ID"
      }
    ]
  }
]
```

## podideas.py — Podcast Idea Extractor

Analyzes YouTube comments with Azure OpenAI to find suggested topics for future
podcast episodes. Maintains a local cache so only new comments are processed on
subsequent runs.

### Usage

The simplest way to get started is to edit `podideas.config.json` with your
playlist URL(s) and set API keys in a `.env` file, then run:

```bash
python podideas.py
```

You can also pass playlists on the command line (full URLs or bare IDs both work):

```bash
python podideas.py \
  -p "https://www.youtube.com/watch?v=A-3I1mLYkxU&list=PL0M0zPgJ3HSf4XZvYgZPUXgSrfzBN26pf"
```

Playlists from the config file and CLI are merged and deduplicated.

### Config File

`podideas.config.json` stores playlist URLs so you don't need to pass them every
time. Edit the `playlists` array to add or remove playlists:

```json
{
  "playlists": [
    "https://www.youtube.com/watch?v=A-3I1mLYkxU&list=PL0M0zPgJ3HSf4XZvYgZPUXgSrfzBN26pf"
  ]
}
```

Both full YouTube URLs and bare playlist IDs are accepted.

### Environment Variables

Instead of passing keys on the command line, you can set environment variables or
place them in a `.env` file in the working directory. The tool loads `.env`
automatically on startup.

| Variable | Description |
|---|---|
| `YT_APIKEY` | YouTube Data API v3 key |
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI endpoint URL |
| `AZURE_OPENAI_API_KEY` | Azure OpenAI API key |
| `AZURE_OPENAI_DEPLOYMENT` | Deployment name (defaults to `gpt-5-chat`) |

Example `.env` file:

```
YT_APIKEY=your_youtube_api_key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_KEY=your_azure_openai_key
AZURE_OPENAI_DEPLOYMENT=gpt-5-chat
```

### Options

| Flag | Description |
|---|---|
| `--playlist`, `-p` | YouTube playlist ID or URL (can be specified multiple times) |
| `--config`, `-c` | JSON config file with playlist URLs (default: `podideas.config.json`) |
| `--yt-api-key` | YouTube Data API key |
| `--aoai-endpoint` | Azure OpenAI endpoint URL |
| `--aoai-api-key` | Azure OpenAI API key |
| `--aoai-deployment` | Azure OpenAI deployment name (default: `gpt-5-chat`) |
| `--cache-dir` | Directory for local cache files (default: `.podideas_cache`) |
| `--output`, `-o` | Output file for suggested topics (default: `suggested_topics.json`) |

## How It Works

1. Fetches all video IDs from the specified playlist(s) using the YouTube Data API.
2. For each video, fetches all comments (top-level and replies).
3. Checks the local cache to skip already-processed comments.
4. Sends new (unprocessed) comments to Azure OpenAI to identify podcast topic suggestions.
5. Updates the cache and writes all discovered suggestions to the output file.

## Cache

The tool stores its cache in `.podideas_cache/` (configurable via `--cache-dir`):

- `videos_cache.json` — Tracks processed video metadata.
- `comments_cache.json` — Tracks processed comment IDs.
- `suggestions.json` — Accumulated topic suggestions from all runs.

On subsequent runs, only new comments are sent to Azure OpenAI for analysis.
