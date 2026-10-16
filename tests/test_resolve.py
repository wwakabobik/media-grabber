from unittest.mock import MagicMock, patch

from main import resolve_playlist


def test_resolve_playlist_generic_playlist_detected():
    fake_entries = [
        {"title": "Track One", "url": "https://y/1"},
        {"title": "Track Two", "webpage_url": "https://y/2"},
        None,  # yt-dlp can hand back None entries for unavailable videos; must be skipped
    ]
    fake_info = {"title": "My Playlist", "entries": fake_entries}
    fake_ydl = MagicMock()
    fake_ydl.__enter__.return_value.extract_info.return_value = fake_info

    with patch("yt_dlp.YoutubeDL", return_value=fake_ydl):
        result = resolve_playlist("https://www.youtube.com/playlist?list=xyz", "")

    assert result is not None
    name, items = result
    assert name == "My Playlist"
    assert items == [("Track One", "https://y/1"), ("Track Two", "https://y/2")]


def test_resolve_playlist_single_video_returns_none():
    fake_info = {"title": "Just One Video"}  # no "entries" key at all
    fake_ydl = MagicMock()
    fake_ydl.__enter__.return_value.extract_info.return_value = fake_info

    with patch("yt_dlp.YoutubeDL", return_value=fake_ydl):
        result = resolve_playlist("https://www.youtube.com/watch?v=abc", "")

    assert result is None


def test_resolve_playlist_spotify_single_track_returns_none():
    fake_song = MagicMock()
    fake_client = MagicMock()
    fake_client.search.return_value = [fake_song]

    with patch("main._get_spotdl_client", return_value=fake_client):
        result = resolve_playlist("https://open.spotify.com/track/abc", "")

    assert result is None


def test_resolve_playlist_spotify_album_returns_all_tracks():
    songs = []
    for i in range(3):
        s = MagicMock()
        s.display_name = f"Song {i}"
        s.url = f"https://open.spotify.com/track/{i}"
        s.list_name = "The Album"
        s.album_name = "The Album"
        songs.append(s)
    fake_client = MagicMock()
    fake_client.search.return_value = songs

    with patch("main._get_spotdl_client", return_value=fake_client):
        result = resolve_playlist("https://open.spotify.com/album/xyz", "")

    assert result is not None
    name, items = result
    assert name == "The Album"
    assert items == [(f"Song {i}", f"https://open.spotify.com/track/{i}") for i in range(3)]


def test_resolve_playlist_yandex_track_returns_none():
    # a /album/<id>/track/<id> URL is a single track, nothing to expand -- and this
    # must not even try to reach Yandex, which is why no token/client is mocked here.
    result = resolve_playlist("https://music.yandex.ru/album/1/track/2", "ignored-token")
    assert result is None
