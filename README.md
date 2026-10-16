# media-grabber

Desktop app: paste a YouTube / Vimeo / Spotify link, pick a format, hit download, watch/listen
right in the window — no external player.

- YouTube / Vimeo (and anything yt-dlp supports): downloaded directly.
- Spotify: DRM-protected, can't be ripped from Spotify itself — spotdl reads the track's
  metadata and pulls the matching audio from YouTube instead.

Realistic format choices: MP4 / WebM video, MP3 audio. AVI isn't offered — none of these
sites serve it, there's nothing to download in that container.

## Run

```bash
uv sync
uv run python main.py
```

Requires `ffmpeg` on PATH (audio extraction / mux).

## What it has

- URL + format dropdown + destination folder (remembered between runs).
- Progress bar + status line fed by yt-dlp's real download progress.
- Built-in preview player (Qt Multimedia) for both video and audio — play/pause, seek.
- History (collapsible tree): every attempt, success or failure, with the error message kept
  for failed ones and a "open in player" button for successful ones. Persisted to
  `~/.config/media-grabber/state.json`.
