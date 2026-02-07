# podideas - Podcast Idea Extractor

A small, self-contained Python CLI tool that pulls YouTube comments from a playlist and uses Azure OpenAI (gpt-5-chat) to identify suggested podcast topics.

## Overview

`podideas` fetches comments from all videos in a YouTube playlist, analyzes them with Azure OpenAI to find suggested topics for future episodes, and maintains a local cache so only new comments are processed on subsequent runs.

## Prerequisites

- Python 3.9+
- A YouTube Data API v3 key
- Azure OpenAI endpoint and API key with access to the `gpt-5-chat` model

## Installation

```bash
cd podideas
pip install -r requirements.txt
```

## Usage

```bash
python podideas.py \
  --playlist "PL0M0zPgJ3HSf4XZvYgZPUXgSrfzBN26pf" \
  --yt-api-key "YOUR_YOUTUBE_API_KEY" \
  --aoai-endpoint "https://YOUR_RESOURCE.openai.azure.com/" \
  --aoai-api-key "YOUR_AZURE_OPENAI_KEY" \
  --aoai-deployment "gpt-5-chat"
```

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
| `--playlist`, `-p` | YouTube playlist ID(s) to process |
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
