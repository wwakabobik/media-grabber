from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from main import HistoryCard, MainWindow, PlaylistDialog, SettingsDialog
from theme import TOKENS


def test_history_card_ok_entry_shows_play_and_finder_buttons(qtbot, tmp_path):
    f = tmp_path / "track.mp3"
    f.write_bytes(b"not a real mp3, just needs to exist")
    entry = {
        "ts": "2026-01-01 00:00",
        "url": "https://x",
        "title": "A Track",
        "kind": "audio",
        "container": "mp3",
        "site": "yt-dlp",
        "status": "ok",
        "path": str(f),
    }
    card = HistoryCard(entry, 0, TOKENS["dark"], load_into_player_cb=lambda *a: None)
    qtbot.addWidget(card)
    # Detail/actions widgets are built lazily, on first expand, not at construction.
    assert card.detail_widget is None
    card._toggle()
    assert card.detail_widget.isHidden() is False
    assert card.actions_widget.isHidden() is False


def test_history_card_does_not_read_media_info_until_expanded(qtbot, tmp_path):
    f = tmp_path / "track.mp3"
    f.write_bytes(b"x")
    entry = {
        "ts": "now", "url": "https://x", "title": "T", "kind": "audio", "container": "mp3",
        "site": "yt-dlp", "status": "ok", "path": str(f),
    }
    with patch("main.read_media_info", return_value={}) as mocked:
        card = HistoryCard(entry, 0, TOKENS["dark"], load_into_player_cb=lambda *a: None)
        qtbot.addWidget(card)
        mocked.assert_not_called()
        card._toggle()
        mocked.assert_called_once()


def test_history_card_missing_file_has_no_play_button(qtbot, tmp_path):
    entry = {
        "ts": "2026-01-01 00:00",
        "url": "https://x",
        "title": "Gone",
        "kind": "audio",
        "container": "mp3",
        "site": "yt-dlp",
        "status": "ok",
        "path": str(tmp_path / "does-not-exist.mp3"),
    }
    card = HistoryCard(entry, 0, TOKENS["dark"], load_into_player_cb=lambda *a: None)
    qtbot.addWidget(card)
    card._toggle()
    # "Показать в Finder" / "Открыть в плеере" only make sense for a file that exists
    button_texts = [w.text() for w in card.actions_widget.findChildren(type(card.toggle_btn))]
    assert not any("плеере" in t or "Finder" in t for t in button_texts)


def test_history_card_shows_description_box_when_present(qtbot, tmp_path):
    f = tmp_path / "track.mp3"
    f.write_bytes(b"x")
    entry = {
        "ts": "now", "url": "https://x", "title": "T", "kind": "audio", "container": "mp3",
        "site": "yt-dlp", "status": "ok", "path": str(f), "description": "hello world",
    }
    card = HistoryCard(entry, 0, TOKENS["dark"], load_into_player_cb=lambda *a: None)
    qtbot.addWidget(card)
    card._toggle()
    assert card.extra_box is not None
    assert card.extra_box.toPlainText() == "hello world"


def test_history_card_error_entry_has_no_extra_box(qtbot):
    entry = {
        "ts": "now", "url": "https://x", "title": "T", "kind": "audio", "container": "mp3",
        "site": "yt-dlp", "status": "error", "error": "boom",
    }
    card = HistoryCard(entry, 0, TOKENS["dark"], load_into_player_cb=lambda *a: None)
    qtbot.addWidget(card)
    card._toggle()
    assert card.extra_box is None


def test_playlist_dialog_select_all_and_none(qtbot):
    items = [("Track 1", "u1"), ("Track 2", "u2"), ("Track 3", "u3")]
    dlg = PlaylistDialog("My Playlist", items)
    qtbot.addWidget(dlg)
    assert dlg.windowTitle() == "My Playlist"
    assert len(dlg.selected_items()) == 3  # all checked by default

    dlg._set_all(Qt.Unchecked)
    assert dlg.selected_items() == []

    dlg._set_all(Qt.Checked)
    assert dlg.selected_items() == items


def test_settings_dialog_round_trips_token(qtbot):
    dlg = SettingsDialog("abc123")
    qtbot.addWidget(dlg)
    assert dlg.token_edit.text() == "abc123"
    dlg.token_edit.setText("  new-token  ")
    assert dlg.token() == "new-token"


def test_main_window_history_search_filters_by_title(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    win.state["history"] = [
        {"ts": "now", "url": "https://a", "title": "Pink Floyd - Time", "kind": "audio",
         "container": "mp3", "site": "spotify", "status": "ok", "path": "/nonexistent-a.mp3"},
        {"ts": "now", "url": "https://b", "title": "Dabeull - Fonk", "kind": "audio",
         "container": "mp3", "site": "yt-dlp", "status": "ok", "path": "/nonexistent-b.mp3"},
    ]
    win._render_history()
    assert len(win._history_cards) == 2

    win._on_history_search("pink")
    assert len(win._history_cards) == 1
    assert win._history_cards[0].entry["title"] == "Pink Floyd - Time"

    win._on_history_search("")
    assert len(win._history_cards) == 2


def test_main_window_history_filters_by_site_format_and_dir(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    win.state["history"] = [
        {"ts": "now", "url": "https://a", "title": "A", "kind": "audio",
         "container": "mp3", "site": "spotify", "status": "ok", "path": "/x/dirA/a.mp3"},
        {"ts": "now", "url": "https://b", "title": "B", "kind": "video",
         "container": "mp4", "site": "yt-dlp", "status": "ok", "path": "/x/dirB/b.mp4"},
    ]
    win._render_history()
    assert len(win._history_cards) == 2
    assert [win.filter_site.itemData(i) for i in range(win.filter_site.count())] == ["", "spotify", "yt-dlp"]

    win.filter_site.setCurrentIndex(win.filter_site.findData("spotify"))
    assert [c.entry["title"] for c in win._history_cards] == ["A"]

    win.filter_site.setCurrentIndex(win.filter_site.findData(""))
    win.filter_format.setCurrentIndex(win.filter_format.findData("mp4"))
    assert [c.entry["title"] for c in win._history_cards] == ["B"]

    win.filter_format.setCurrentIndex(win.filter_format.findData(""))
    win.filter_dir.setCurrentIndex(win.filter_dir.findData("/x/dirA"))
    assert [c.entry["title"] for c in win._history_cards] == ["A"]


def test_main_window_close_event_blocks_on_running_download_unless_confirmed(qtbot):
    from unittest.mock import MagicMock

    from PySide6.QtGui import QCloseEvent

    win = MainWindow()
    qtbot.addWidget(win)
    win.worker = MagicMock()
    win.worker.isRunning.return_value = True
    try:
        with patch("main.QMessageBox.exec", return_value=QMessageBox.No):
            event = QCloseEvent()
            win.closeEvent(event)
            assert event.isAccepted() is False

        with patch("main.QMessageBox.exec", return_value=QMessageBox.Yes):
            event = QCloseEvent()
            win.closeEvent(event)
            assert event.isAccepted() is True
            win.worker.terminate.assert_called_once()
    finally:
        win.worker = None  # otherwise qtbot's teardown close() re-triggers a real, unpatched dialog


def test_main_window_save_info_panel_writes_file(qtbot, tmp_path):
    win = MainWindow()
    qtbot.addWidget(win)
    win._current_media_text = "some lyrics or description"
    target = tmp_path / "out.txt"
    with patch("main.QFileDialog.getSaveFileName", return_value=(str(target), "")):
        win._save_info_panel()
    assert target.read_text(encoding="utf-8") == "some lyrics or description"


def test_main_window_save_info_panel_noop_without_text(qtbot, tmp_path):
    win = MainWindow()
    qtbot.addWidget(win)
    win._current_media_text = ""
    target = tmp_path / "should-not-appear.txt"
    with patch("main.QFileDialog.getSaveFileName", return_value=(str(target), "")):
        win._save_info_panel()
    assert not target.exists()
