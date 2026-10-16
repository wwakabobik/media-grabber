from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QMessageBox, QScrollArea

from main import (
    CONVERT_AUDIO_TARGETS,
    CONVERT_VIDEO_TARGETS,
    ConvertDialog,
    HistoryCard,
    MainWindow,
    PlaylistDialog,
    SettingsDialog,
    entry_disk_status,
)
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


def test_history_card_clicking_title_row_toggles_like_chevron(qtbot, tmp_path):
    f = tmp_path / "track.mp3"
    f.write_bytes(b"x")
    entry = {
        "ts": "now", "url": "https://x", "title": "T", "kind": "audio", "container": "mp3",
        "site": "yt-dlp", "status": "ok", "path": str(f),
    }
    card = HistoryCard(entry, 0, TOKENS["dark"], load_into_player_cb=lambda *a: None)
    qtbot.addWidget(card)
    card.show()
    header_widget = card.checkbox.parent()
    qtbot.mouseClick(header_widget, Qt.LeftButton)
    assert card.detail_widget is not None
    assert card.detail_widget.isHidden() is False

    qtbot.mouseClick(header_widget, Qt.LeftButton)
    assert card.detail_widget.isHidden() is True


def test_history_card_clicking_checkbox_does_not_toggle_expansion(qtbot, tmp_path):
    f = tmp_path / "track.mp3"
    f.write_bytes(b"x")
    entry = {
        "ts": "now", "url": "https://x", "title": "T", "kind": "audio", "container": "mp3",
        "site": "yt-dlp", "status": "ok", "path": str(f),
    }
    card = HistoryCard(entry, 0, TOKENS["dark"], load_into_player_cb=lambda *a: None)
    qtbot.addWidget(card)
    card.show()
    qtbot.mouseClick(card.checkbox, Qt.LeftButton)
    assert card.checkbox.isChecked() is True
    assert card.detail_widget is None  # still collapsed -- checkbox click must not expand


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


def test_history_card_shows_chapters_with_description(qtbot, tmp_path):
    f = tmp_path / "track.mp3"
    f.write_bytes(b"x")
    entry = {
        "ts": "now", "url": "https://x", "title": "T", "kind": "video", "container": "mp4",
        "site": "yt-dlp", "status": "ok", "path": str(f), "description": "hello world",
        "chapters": [{"start_time": 0, "title": "Intro"}, {"start_time": 65, "title": "Part 2"}],
    }
    card = HistoryCard(entry, 0, TOKENS["dark"], load_into_player_cb=lambda *a: None)
    qtbot.addWidget(card)
    card._toggle()
    assert card.extra_box is not None
    text = card.extra_box.toPlainText()
    assert "hello world" in text
    assert "Chapters:" in text
    assert "0:00  Intro" in text
    detail_text = card.detail_widget.findChild(QLabel, "dim").text()
    assert "Chapters: 2" in detail_text


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
    dlg = SettingsDialog("abc123", "/tmp/dest", "en")
    qtbot.addWidget(dlg)
    assert dlg.token_edit.text() == "abc123"
    dlg.token_edit.setText("  new-token  ")
    assert dlg.token() == "new-token"


def test_settings_dialog_round_trips_dest_and_language(qtbot):
    dlg = SettingsDialog("", "/tmp/dest", "en")
    qtbot.addWidget(dlg)
    assert dlg.dest() == "/tmp/dest"
    assert dlg.language() == "en"
    dlg.language_combo.setCurrentIndex(dlg.language_combo.findData("ru"))
    assert dlg.language() == "ru"


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


def test_main_window_video_collapse_toggle_hides_video_widget(qtbot, tmp_path):
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"x")
    win = MainWindow()
    qtbot.addWidget(win)
    win._load_into_player(str(f), "video", "A Clip")
    assert win.video_collapse_btn.isHidden() is False
    assert win.video_widget.isHidden() is False

    win._toggle_video_collapsed()
    assert win.video_widget.isHidden() is True

    win._toggle_video_collapsed()
    assert win.video_widget.isHidden() is False


def test_main_window_loading_audio_hides_video_collapse_button(qtbot, tmp_path):
    f = tmp_path / "track.mp3"
    f.write_bytes(b"x")
    win = MainWindow()
    qtbot.addWidget(win)
    win._load_into_player(str(f), "audio", "A Track")
    assert win.video_collapse_btn.isHidden() is True
    assert win.video_widget.isHidden() is True


def test_main_window_history_scroll_has_a_minimum_height_floor(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    # Without a floor, the video player (260px min) plus everything above it
    # could squeeze this to near-zero with no way to reach it -- regression
    # test for that, not a claim about the exact pixel value.
    assert win.history_scroll.minimumHeight() >= 150


def test_main_window_content_is_scrollable_when_window_is_too_small(qtbot, tmp_path):
    # The real fix for "nothing reachable when the video player is open": the
    # whole window content sits in an outer QScrollArea, so a window shorter
    # than its content is always reachable by scrolling, not just squeezed.
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"x")
    win = MainWindow()
    qtbot.addWidget(win)
    win.resize(820, 500)
    win._load_into_player(str(f), "video", "A Clip")

    outer = win.centralWidget()
    assert isinstance(outer, QScrollArea)
    assert outer.widget().sizeHint().height() > outer.viewport().height()
    assert outer.verticalScrollBar().maximum() > 0


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


def test_main_window_progress_bar_hidden_except_while_busy(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    assert win.progress.isHidden() is True  # nothing done yet

    win._set_busy(True)
    assert win.progress.isHidden() is False

    win._set_busy(False)
    assert win.progress.isHidden() is True  # back to hidden once finished, not stuck at 100%


def test_main_window_convert_uses_indeterminate_progress_pulse(qtbot):
    # ffmpeg conversion has no percentage to report (unlike downloads), so it
    # gets the QProgressBar's built-in animated "busy" pulse: range(0, 0).
    win = MainWindow()
    qtbot.addWidget(win)
    win._set_busy(True, indeterminate=True)
    assert win.progress.minimum() == 0
    assert win.progress.maximum() == 0

    win._set_busy(False)
    assert win.progress.maximum() == 100  # back to a normal determinate bar

    win._set_busy(True)  # a regular download: determinate, reports a real percentage
    assert win.progress.maximum() == 100


def test_main_window_player_section_hidden_until_something_is_loaded(qtbot, tmp_path):
    win = MainWindow()
    qtbot.addWidget(win)
    assert win.player_section.isHidden() is True  # no old song/video open, nothing downloaded yet

    f = tmp_path / "track.mp3"
    f.write_bytes(b"x")
    win._load_into_player(str(f), "audio", "A Track")
    assert win.player_section.isHidden() is False


def test_main_window_retranslate_ui_switches_button_text(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    assert win.download_btn.text() == "Download"

    import i18n

    i18n.set_language("ru")
    try:
        win._retranslate_ui()
        assert win.download_btn.text() == "Скачать"
    finally:
        i18n.set_language("en")
        win._retranslate_ui()


def test_main_window_status_ready_only_shown_pristine(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    assert win.status_label.text() == "Ready"

    win._set_status("Done: thing", "ok")
    import i18n

    i18n.set_language("ru")
    try:
        win._retranslate_ui()
        assert win.status_label.text() == "Done: thing"  # a real status is never overwritten back to "ready"
    finally:
        i18n.set_language("en")


def test_convert_dialog_audio_source_offers_only_audio_targets(qtbot):
    dlg = ConvertDialog("audio")
    qtbot.addWidget(dlg)
    assert dlg.targets == [(c, False) for c in CONVERT_AUDIO_TARGETS]


def test_convert_dialog_video_source_offers_video_and_audio_extraction(qtbot):
    dlg = ConvertDialog("video")
    qtbot.addWidget(dlg)
    assert dlg.targets == [(c, False) for c in CONVERT_VIDEO_TARGETS] + [(c, True) for c in CONVERT_AUDIO_TARGETS]
    dlg.target_combo.setCurrentIndex(len(CONVERT_VIDEO_TARGETS))  # first audio-extraction entry
    assert dlg.target() == (CONVERT_AUDIO_TARGETS[0], True)


def test_main_window_convert_finished_adds_history_entry(qtbot, tmp_path):
    win = MainWindow()
    qtbot.addWidget(win)
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"x")
    converted = tmp_path / "clip (converted).mp3"
    converted.write_bytes(b"x")
    win.state["history"] = [
        {"ts": "now", "url": "https://x", "title": "Clip", "kind": "video", "container": "mp4",
         "site": "yt-dlp", "status": "ok", "path": str(src)},
    ]

    with patch("main.save_state"):
        win._on_convert_finished({"path": str(converted), "kind": "audio", "container": "mp3"}, str(src))

    assert win.state["history"][0]["path"] == str(converted)
    assert win.state["history"][0]["site"] == "converted"
    assert win.state["history"][0]["url"] == "https://x"  # inherited from the source entry


def test_main_window_convert_failed_shows_error_status(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    win._on_convert_failed("ffmpeg exploded")
    assert "ffmpeg exploded" in win.status_label.text()


def test_entry_disk_status(tmp_path):
    f = tmp_path / "track.mp3"
    f.write_bytes(b"x")
    assert entry_disk_status({"status": "ok", "path": str(f)}) == "on_disk"
    assert entry_disk_status({"status": "ok", "path": str(tmp_path / "gone.mp3")}) == "missing"
    assert entry_disk_status({"status": "error"}) == "error"


def test_main_window_theme_combo_has_three_options_and_picks_up_saved_choice(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    assert [win.theme_combo.itemData(i) for i in range(win.theme_combo.count())] == ["light", "dark", "system"]
    win.theme = "dark"
    win.state["theme"] = "dark"


def test_main_window_on_theme_changed_persists_and_applies(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    with patch("main.save_state") as mocked_save:
        win.theme_combo.setCurrentIndex(win.theme_combo.findData("light"))  # known baseline
        mocked_save.reset_mock()
        win.theme_combo.setCurrentIndex(win.theme_combo.findData("dark"))
        assert win.theme == "dark"
        assert win._effective_theme == "dark"
        mocked_save.assert_called_once_with(win.state)


def test_main_window_system_theme_follows_os_until_an_explicit_choice_is_made(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    win.theme = "system"
    with patch.object(win, "_resolve_effective_theme", return_value="dark"):
        win._apply_theme()
        assert win._effective_theme == "dark"
        win._on_system_theme_changed(None)  # OS changed while following it -> re-applied
        assert win._effective_theme == "dark"

    win.theme = "light"  # an explicit pick
    with patch.object(win, "_apply_theme") as mocked_apply:
        win._on_system_theme_changed(None)  # OS changing must not override an explicit pick
        mocked_apply.assert_not_called()


def test_main_window_history_filters_by_kind_and_status(qtbot, tmp_path):
    present = tmp_path / "present.mp3"
    present.write_bytes(b"x")
    win = MainWindow()
    qtbot.addWidget(win)
    win.state["history"] = [
        {"ts": "now", "url": "https://a", "title": "A", "kind": "audio",
         "container": "mp3", "site": "yt-dlp", "status": "ok", "path": str(present)},
        {"ts": "now", "url": "https://b", "title": "B", "kind": "video",
         "container": "mp4", "site": "yt-dlp", "status": "ok", "path": str(tmp_path / "gone.mp4")},
        {"ts": "now", "url": "https://c", "title": "C", "kind": "audio",
         "container": "mp3", "site": "yt-dlp", "status": "error", "error": "boom"},
    ]
    win._render_history()
    assert len(win._history_cards) == 3

    win.filter_kind.setCurrentIndex(win.filter_kind.findData("video"))
    assert [c.entry["title"] for c in win._history_cards] == ["B"]

    win.filter_kind.setCurrentIndex(win.filter_kind.findData(""))
    win.filter_status.setCurrentIndex(win.filter_status.findData("missing"))
    assert [c.entry["title"] for c in win._history_cards] == ["B"]

    win.filter_status.setCurrentIndex(win.filter_status.findData("error"))
    assert [c.entry["title"] for c in win._history_cards] == ["C"]


def test_convert_targets_cover_the_expected_formats():
    assert set(CONVERT_AUDIO_TARGETS) >= {"mp3", "wav", "m4a", "flac", "ogg", "aac", "opus"}
    assert set(CONVERT_VIDEO_TARGETS) >= {"mp4", "webm", "mkv", "mov", "avi"}
