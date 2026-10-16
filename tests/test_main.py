import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import DownloadWorker, is_spotify


def test_is_spotify():
    assert is_spotify("https://open.spotify.com/track/abc")
    assert not is_spotify("https://www.youtube.com/watch?v=abc")
    assert not is_spotify("https://vimeo.com/123")


def test_make_unique_adds_incrementing_suffix(tmp_path):
    target = tmp_path / "video.mp4"
    assert DownloadWorker._make_unique(target) == target

    target.write_text("x")
    first = DownloadWorker._make_unique(target)
    assert first == tmp_path / "video (1).mp4"

    first.write_text("x")
    second = DownloadWorker._make_unique(target)
    assert second == tmp_path / "video (2).mp4"
