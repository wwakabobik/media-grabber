# Contributing

## Workflow

`master` is protected: every change lands via pull request, and CI (`ruff` + `pytest`, job
`lint-and-test`) has to be green before it can be merged — this is enforced by branch
protection, not just convention, including for the repo owner.

```bash
git checkout -b feat/your-thing
# ... make changes ...
uv sync --all-groups
uv run ruff check .
uv run pytest -q
git push -u origin feat/your-thing
gh pr create
```

## Versioning

[SemVer](https://semver.org/) (`MAJOR.MINOR.PATCH`), tracked in `pyproject.toml`'s
`[project].version`. If your PR is a real feature or a breaking change, bump it there as part
of the PR (minor for a feature, major for a breaking change) and add an entry to
[`CHANGELOG.md`](CHANGELOG.md) under a new version heading. If you don't touch the version,
the release workflow bumps the patch number automatically on merge — every merge to `master`
gets a tag and a GitHub Release either way, so this is a safety net, not a requirement to
remember on every PR.

## Tests

- `tests/test_helpers.py` — pure functions (string/regex/formatting helpers), mocked where they
  touch `mutagen`/`subprocess`. No network.
- `tests/test_resolve.py` — `resolve_playlist()` against mocked `yt_dlp.YoutubeDL` / spotdl
  client. No network.
- `tests/test_gui.py` — widget-level tests (`HistoryCard`, `PlaylistDialog`, `SettingsDialog`,
  `MainWindow`'s search/export), run headless via `QT_QPA_PLATFORM=offscreen` (set in CI; set it
  yourself locally if you don't have a display available, e.g. over SSH).

Prefer a mocked test over a live-network one: this project talks to YouTube/Spotify/SoundCloud/
Yandex Music, all of which rate-limit, and a flaky CI from an external 429 is worse than a test
that doesn't catch a real-world edge case. If you do need to verify something end-to-end, do it
locally and describe what you ran in the PR description instead of adding it to the suite.

## Code style

`ruff check .` is the only gate; there's no separate formatter config. Follow the existing
docstring/comment style (comments explain *why*, not *what*) and keep new UI strings in Russian
to match the rest of the app.

## Building the `.app` (macOS)

```bash
uv run pyinstaller --windowed --name "MediaGrabber" --icon=icon/AppIcon.icns \
  --collect-data pykakasi --collect-data ytmusicapi --noconfirm main.py
```

The two `--collect-data` flags are required — see the README's Quickstart section for why.
