# Changelog

All notable changes to this project are documented here. Versioning follows
[SemVer](https://semver.org/) (`MAJOR.MINOR.PATCH`): a version bump lands in `pyproject.toml`
as part of the PR that warrants it (features/fixes -> minor/patch; breaking changes -> major);
every merge to `master` that doesn't otherwise bump it gets an automatic patch/build bump via
the release workflow, so every merge produces a new tagged release either way.

## [Unreleased]

## [0.7.0]
- Replaced the history list's `QTreeWidget` with real `HistoryCard` widgets in a scroll area —
  the tree never sized itself correctly to wrapped multi-line content, which clipped text and
  overlapped the action buttons with the row underneath.
- Pull and show video descriptions (YouTube/Vimeo/SoundCloud/VK) and lyrics (Spotify, Yandex
  Music), with a "Сохранить как…" export to `.txt`.
- Subtitle fetch is now one language at a time, so a rate limit on one doesn't silently drop
  the other.
- Cleaned up HTML entities/tags SoundCloud sometimes returns in its description field.
- Real test coverage: helper-function tests (mocked, no network), `resolve_playlist` tests
  (mocked yt-dlp/spotdl), and GUI tests for `HistoryCard`/`PlaylistDialog`/`SettingsDialog`/
  `MainWindow` search+export, running headless (`QT_QPA_PLATFORM=offscreen`) in CI.
- Declared `Pillow` as an explicit dev dependency (it was already a transitive one, used by
  `icon/generate_icon.py`).

## [0.6.0]
- Light/dark glass theme (`theme.py`): color tokens, a QSS stylesheet, hand-drawn lucide-style
  SVG icons tinted per theme at render time. Header theme toggle, persisted.
- Real screenshots in the README, rendered off-screen (`QT_QPA_PLATFORM=offscreen` +
  `QWidget.grab()`) rather than a screen capture.
- Dependency versions bumped and verified current (PySide6, yt-dlp, spotdl, mutagen).

## [0.5.0]
- Embedded cover art + title/uploader/description metadata for yt-dlp downloads.
- Video downloads also fetch `.srt`/`.vtt` subtitles as a best-effort sidecar step.
- Yandex Music downloads tagged by hand with `mutagen` (ID3 + cover), since the library only
  saves raw audio.
- Playlist/album batches download into a subfolder named after the playlist/album.
- 🌐 button to open the current URL, or a history entry's original link, in the browser.

## [0.4.0]
- SoundCloud and VK support (free, via yt-dlp's existing generic extraction).
- Yandex Music: real downloads via the `yandex-music` library, gated behind a personal OAuth
  token set in Settings (Yandex has no anonymous API access like Spotify's).
- Playlist/album/multi-track links are resolved and offered as a checkbox pick-list before
  downloading.
- Fixed a real bug this surfaced: spotdl's `SpotifyClient` is a process-wide singleton that
  raised on a second `init()`, crashing every track after the first in a Spotify playlist batch.

## [0.3.0]
- Fixed Spotify downloads inside the packaged `.app`: moved off the `spotdl` CLI command (not on
  PATH in a frozen app) to its library API, and added the `--collect-data` PyInstaller flags
  `pykakasi`/`ytmusicapi` needed to ship their data files.
- Added structured logging (`structlog`): console + rotating JSON file.
- Spotify/Yandex Music URLs grey out the video format option (both are audio-only).

## [0.2.3] / [0.2.2]
- Dependabot version-update PRs (`actions/checkout`, `astral-sh/setup-uv`).

## [0.2.1]
- Fixed the CI status badge never updating: the workflow excluded `master` from its triggers,
  so the badge (which reads the `master` run) permanently showed "no status".
- Added `.github/dependabot.yml` for weekly pip + GitHub Actions version-update PRs.

## [0.2.0]
- MIT license, CI (`ruff` + `pytest`), `FUNDING.yml`, polished README with badges.
- `master` branch protection: PR required, CI must pass, no force-push/direct-push.

## [0.1.0]
- Initial release: download audio/video from YouTube, Vimeo and Spotify via `yt-dlp`/`spotdl`,
  PySide6 desktop UI with a built-in preview player and download history.

[Unreleased]: https://github.com/wwakabobik/media-grabber/compare/v0.7.0...HEAD
[0.7.0]: https://github.com/wwakabobik/media-grabber/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/wwakabobik/media-grabber/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/wwakabobik/media-grabber/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/wwakabobik/media-grabber/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/wwakabobik/media-grabber/compare/v0.2.3...v0.3.0
