# media-grabber

[![Lint & Test](https://github.com/wwakabobik/media-grabber/actions/workflows/lint.yml/badge.svg?branch=master)](https://github.com/wwakabobik/media-grabber/actions/workflows/lint.yml)
[![License: MIT](https://img.shields.io/github/license/wwakabobik/media-grabber)](LICENSE)
![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![Platform](https://img.shields.io/badge/platform-macOS-lightgrey)
[![PySide6](https://img.shields.io/badge/UI-PySide6%20(Qt)-41cd52)](https://doc.qt.io/qtforpython/)

A small desktop app: paste a YouTube / Vimeo / SoundCloud / VK / Spotify / Yandex Music link
(including a playlist or album), pick a format and quality, hit download, and watch or listen
right in the window — no browser, no external player.

## How it gets the media

- **YouTube / Vimeo / SoundCloud / VK** (and anything [yt-dlp](https://github.com/yt-dlp/yt-dlp)
  supports) are downloaded directly.
- **Spotify** streams are DRM-protected and can't be ripped from Spotify itself.
  [spotdl](https://github.com/spotDL/spotify-downloader) reads the track's metadata from Spotify
  and pulls the matching audio from YouTube instead — Spotify is only ever used for the lookup.
- **Yandex Music** tracks download for real (no YouTube-matching detour), but Yandex's API has no
  anonymous access like Spotify's — you need your own account's OAuth token, set once in
  **⚙ Настройки**.
- **Playlists / albums / multi-track links** (YouTube playlists, SoundCloud sets, Spotify
  albums/playlists, Yandex Music albums/playlists) are detected before downloading: a picker
  dialog lists every track/video with a checkbox so you choose what actually gets downloaded,
  then they're fetched one by one with per-item progress.

Realistic format choices: **MP4 / WebM** video, **MP3** audio. AVI isn't offered — none of these
sites serve it, so there'd be nothing to download into that container. Spotify and Yandex Music
are audio-only — picking one of those links greys out the video option instead of letting you
hit an error.

## Features

- URL + format dropdown (video/audio) + quality picker (Best / 1080p / 720p / 480p / 360p) +
  destination folder, remembered between runs.
- Progress bar and status line fed by yt-dlp's real download progress, with an overlay that
  blocks the controls while a download is in flight.
- Built-in preview player ([Qt Multimedia](https://doc.qt.io/qt-6/qtmultimedia-index.html)) for
  both video and audio — play/pause, seek — so nothing needs to be opened in another app.
- History with multi-select: every attempt (success or failure) is kept, with the error message
  for failed ones. Delete selected entries from the list only, or from disk as well. An entry
  whose file was removed outside the app is shown greyed out instead of crashing or lying about
  its status. A repeat download of the same title never overwrites the previous file — it gets
  a `(1)`, `(2)`, ... suffix, like a browser's download manager.
- Playlist/album links open a checkbox picker instead of downloading blind; picked items queue
  up and download one at a time, each landing in the history individually.
- Persisted to `~/.config/media-grabber/state.json`.
- Structured logging ([structlog](https://www.structlog.org/)): human-readable in the console,
  JSON with keyword context (url, kind, path, errors...) in a rotating file at
  `~/.config/media-grabber/logs/media-grabber.log` (5 MB x 5 backups).

## Known limitations

- YouTube's highest-quality streams are often encoded in **AV1**, which `QtMultimedia`'s bundled
  ffmpeg backend can't hardware-decode on most machines (plays audio with no picture). The app
  explicitly prefers H.264 (`avc1`) for video downloads to avoid this.
- Spotify downloads are a metadata-driven YouTube search (via spotdl), not an actual rip of
  Spotify's own audio stream — quality and match accuracy depend on what's available on YouTube.
- Yandex Music needs your personal account's OAuth token (there's no public client-credentials
  flow like Spotify's) — without one, Yandex links fail with a clear "add a token" error.
- SoundCloud's *original* (highest-quality) format needs login too; without it yt-dlp falls back
  to the standard transcoded stream, which works fine but isn't the uploader's original file.

## Quickstart

```bash
uv sync
uv run python main.py
```

Requires `ffmpeg` on `PATH` (used for audio extraction and video muxing).

### Building a standalone `.app` (macOS)

```bash
uv run pyinstaller --windowed --name "MediaGrabber" --icon=icon/AppIcon.icns \
  --collect-data pykakasi --collect-data ytmusicapi --noconfirm main.py
```

The `--collect-data` flags are required: spotdl's dependency chain (`pykakasi`, `ytmusicapi`)
ships data files (dictionaries, locale `.mo` files) that PyInstaller doesn't pick up on its own —
without them Spotify downloads fail inside the bundled `.app` with a missing-file error, even
though `uv run python main.py` works fine (it reads straight from the dev venv's site-packages).

The result is in `dist/MediaGrabber.app` — copy it to `/Applications` to install.

## Tech stack

- **UI**: [PySide6](https://doc.qt.io/qtforpython/) (Qt for Python), incl. Qt Multimedia for the
  in-app player
- **Download backends**: [yt-dlp](https://github.com/yt-dlp/yt-dlp),
  [spotdl](https://github.com/spotDL/spotify-downloader)
- **Packaging**: [uv](https://docs.astral.sh/uv/) for dependency management,
  [PyInstaller](https://pyinstaller.org/) for the `.app` bundle
- **Python**: 3.12+

## Contributing

`master` is protected — all changes land via pull request and must pass CI (`ruff` + `pytest`)
before they can be merged.

```bash
uv sync --all-groups
uv run ruff check .
uv run pytest -q
```

## Donations

If you like this project, you can support it by donating via
[DonationAlerts](https://www.donationalerts.com/r/rocketsciencegeek),
[Buy me a coffee](https://www.buymeacoffee.com/wwakabobik) or
[Thanks Dev](https://thanksdev.com/wwakabobik).

## License

[MIT](LICENSE)
