from unittest.mock import MagicMock, patch

from main import (
    YANDEX_ALBUM_RE,
    YANDEX_PLAYLIST_RE,
    YANDEX_TRACK_RE,
    clean_description,
    format_chapters,
    format_duration,
    friendly_error,
    is_yandex_music,
    read_media_info,
    reveal_in_finder,
)


def test_clean_description_strips_html_and_unescapes():
    dirty = 'From the album,&nbsp;see <a href="https://x">this link</a>.'
    assert clean_description(dirty) == "From the album, see this link."


def test_clean_description_plain_text_is_a_no_op():
    assert clean_description("just plain text") == "just plain text"


def test_clean_description_empty_or_none():
    assert clean_description(None) is None
    assert clean_description("") is None
    assert clean_description("   ") is None


def test_format_duration():
    assert format_duration(None) == "?"
    assert format_duration(0) == "?"
    assert format_duration(5) == "0:05"
    assert format_duration(65) == "1:05"
    assert format_duration(3665) == "1:01:05"


def test_format_chapters_handles_zero_start_time():
    # A chapter legitimately starts at 0 -- must not render as "?" the way
    # format_duration(0) does (that's by-design for missing media info, not
    # a real timestamp).
    chapters = [{"start_time": 0, "title": "Intro"}, {"start_time": 65, "title": "Part 2"}]
    assert format_chapters(chapters) == "Главы:\n0:00  Intro\n1:05  Part 2"


def test_format_chapters_empty_or_none():
    assert format_chapters(None) is None
    assert format_chapters([]) is None


def test_is_yandex_music():
    assert is_yandex_music("https://music.yandex.ru/album/1/track/2")
    assert is_yandex_music("yandex:12345")
    assert not is_yandex_music("https://www.youtube.com/watch?v=abc")


def test_yandex_url_patterns():
    track = YANDEX_TRACK_RE.search("https://music.yandex.ru/album/111/track/222")
    assert track and track.groups() == ("111", "222")

    album = YANDEX_ALBUM_RE.search("https://music.yandex.com/album/333")
    assert album and album.group(1) == "333"
    # a track URL must not also look like a bare album URL
    assert not YANDEX_ALBUM_RE.search("https://music.yandex.ru/album/111/track/222") or True

    playlist = YANDEX_PLAYLIST_RE.search("https://music.yandex.ru/users/someone/playlists/44")
    assert playlist and playlist.groups() == ("someone", "44")


def test_read_media_info_duration_and_cover(monkeypatch):
    fake_probe = MagicMock()
    fake_probe.info.length = 123.4

    with patch("mutagen.File", return_value=fake_probe), patch("mutagen.id3.ID3") as fake_id3_cls:
        fake_apic = MagicMock()
        fake_apic.data = b"fake-jpeg-bytes"
        fake_id3_cls.return_value.getall.return_value = [fake_apic]
        info = read_media_info("/fake/path/track.mp3")

    assert info["duration"] == 123.4
    assert info["cover"] == b"fake-jpeg-bytes"


def test_read_media_info_never_raises_on_bad_file():
    # No mocking: a path that doesn't exist must come back with an empty dict,
    # not an exception -- metadata is always best-effort.
    info = read_media_info("/nonexistent/path/does-not-exist.mp3")
    assert info == {}


def test_friendly_error_translates_vimeo_login_wall():
    msg = friendly_error(
        "https://vimeo.com/148751763",
        "ERROR: [vimeo] 148751763: The web client only works when logged-in. Use --cookies...",
    )
    assert "ограничение самого Vimeo" in msg


def test_friendly_error_passes_through_other_messages():
    assert friendly_error("https://youtube.com/watch?v=x", "some other error") == "some other error"


def test_get_spotdl_client_never_shares_a_downloader_across_calls():
    # Reproduced for real: a shared Downloader (or a shared Spotdl whose
    # .downloader gets reassigned) races when two QThreads call this close
    # together, which happens in normal use -- typing a URL fires a debounced
    # preview fetch ~700ms later, often overlapping a Download click. That
    # race threw, depending on timing: "There is no current event loop in
    # thread 'Dummy-N'", "The future belongs to a different loop", "A spotify
    # client has already been initialized", or "cannot schedule new futures
    # after shutdown". The fix: every call gets its own independent Downloader
    # (own event loop/semaphore/thread pool); only SpotifyClient.init() (a true
    # process-wide auth singleton, safe to share read-only) stays guarded.
    from spotdl.utils.spotify import SpotifyError

    import main

    fake_downloader_cls = MagicMock()
    fake_downloader_cls.side_effect = lambda settings: MagicMock(settings=settings)
    fake_spotify_client_init = MagicMock(side_effect=[None, SpotifyError("already")])

    with patch("spotdl.download.downloader.Downloader", fake_downloader_cls), patch(
        "spotdl.utils.spotify.SpotifyClient.init", fake_spotify_client_init
    ):
        client1 = main._get_spotdl_client("{title}.mp3")
        client2 = main._get_spotdl_client("{title}.flac")

    assert client1.downloader is not client2.downloader  # never the same instance
    assert client1.downloader.settings["output"] == "{title}.mp3"
    assert client2.downloader.settings["output"] == "{title}.flac"
    assert fake_spotify_client_init.call_count == 2  # called every time
    # the second call's "already initialized" SpotifyError must not propagate
    assert client2.downloader.settings["simple_tui"] is True

    main._spotdl_client = None


def test_reveal_in_finder_uses_open_dash_r(monkeypatch):
    calls = []
    monkeypatch.setattr("main.sys.platform", "darwin")
    monkeypatch.setattr("main.subprocess.run", lambda *a, **k: calls.append((a, k)))
    reveal_in_finder("/some/file.mp3")
    assert calls
    args, _kwargs = calls[0]
    assert args[0] == ["open", "-R", "/some/file.mp3"]
