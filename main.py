"""media-grabber: paste a URL, pick a format, download, preview in-app.

YouTube/Vimeo (and anything yt-dlp supports) download directly. Spotify is
DRM-protected and can't be ripped from Spotify itself, so spotify.com links
go through spotdl: it reads the track's metadata and downloads the matching
audio from YouTube.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

os.environ.setdefault("QT_MAC_WANTS_LAYER", "1")  # frozen/signed .app: video widget renders black without this

import yt_dlp
from PySide6.QtCore import QThread, QUrl, Qt, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSlider,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

STATE_PATH = Path.home() / ".config" / "media-grabber" / "state.json"
DEFAULT_DEST = str(Path.home() / "Downloads")

FORMATS = {
    "Видео (MP4)": ("video", "mp4"),
    "Видео (WebM)": ("video", "webm"),
    "Аудио (MP3)": ("audio", "mp3"),
}

QUALITIES = {
    "Лучшее": None,
    "1080p": 1080,
    "720p": 720,
    "480p": 480,
    "360p": 360,
}


def is_spotify(url: str) -> bool:
    return "spotify.com" in url


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except Exception:
            pass
    return {"last_dest": DEFAULT_DEST, "history": []}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2))


class DownloadWorker(QThread):
    progress = Signal(int, str)
    finished_ok = Signal(dict)
    failed = Signal(str)

    def __init__(self, url: str, kind: str, container: str, dest_dir: str, max_height: int | None = None):
        super().__init__()
        self.url = url
        self.kind = kind
        self.container = container
        self.dest_dir = dest_dir
        self.max_height = max_height

    def run(self) -> None:
        try:
            if is_spotify(self.url):
                if self.kind == "video":
                    raise ValueError("У Spotify нет видео — выбери «Аудио (MP3)».")
                result = self._spotdl()
            else:
                result = self._ytdlp()
            self.finished_ok.emit(result)
        except Exception as e:
            self.failed.emit(str(e))

    def _hook(self, d: dict) -> None:
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes", 0)
            pct = int(done / total * 95) if total else 0
            self.progress.emit(pct, "Скачивание…")
        elif d["status"] == "finished":
            self.progress.emit(96, "Обработка файла…")

    def _ytdlp(self) -> dict:
        Path(self.dest_dir).mkdir(parents=True, exist_ok=True)
        opts: dict = {
            "outtmpl": f"{self.dest_dir}/%(title)s.%(ext)s",
            "noplaylist": True,
            "progress_hooks": [self._hook],
            "overwrites": True,  # otherwise yt-dlp reuses a stale file of the same name as-is
        }
        if self.kind == "audio":
            opts["format"] = "bestaudio/best"
            opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}]
        else:
            # Prefer H.264: Qt Multimedia's bundled ffmpeg can't hw-decode AV1/VP9 on
            # this platform, which yt-dlp's plain "bestvideo" would otherwise pick.
            h = f"[height<={self.max_height}]" if self.max_height else ""
            opts["format"] = (
                f"bestvideo{h}[vcodec^=avc1]+bestaudio/best{h}[vcodec^=avc1]/bestvideo{h}+bestaudio/best{h}"
            )
            opts["merge_output_format"] = self.container

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(self.url, download=True)
            path = ydl.prepare_filename(info)
            ext = "mp3" if self.kind == "audio" else self.container
            path = str(Path(path).with_suffix(f".{ext}"))
        return {
            "title": info.get("title") or self.url,
            "path": path,
            "kind": self.kind,
            "site": "yt-dlp",
        }

    def _spotdl(self) -> dict:
        Path(self.dest_dir).mkdir(parents=True, exist_ok=True)
        before = set(Path(self.dest_dir).glob("*"))
        self.progress.emit(10, "Поиск трека через spotdl…")
        result = subprocess.run(
            ["spotdl", "download", self.url, "--output", f"{self.dest_dir}/{{title}}.{{output-ext}}"],
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr[-1500:] or "spotdl завершился с ошибкой")
        new_files = list(set(Path(self.dest_dir).glob("*")) - before)
        if not new_files:
            raise RuntimeError("spotdl не скачал ни одного файла")
        path = str(new_files[0])
        return {"title": Path(path).stem, "path": path, "kind": "audio", "site": "spotify"}


STYLE = """
QMainWindow, QWidget { background-color: #15161d; color: #e6e6f0; font-size: 13px; }
QLineEdit, QComboBox, QTreeWidget {
    background-color: #1f2129; border: 1px solid #30323d; border-radius: 8px;
    padding: 6px 10px; color: #e6e6f0;
}
QPushButton {
    background-color: #6c5ce7; border: none; border-radius: 8px;
    padding: 8px 16px; font-weight: 600; color: white;
}
QPushButton:hover { background-color: #7d6ff0; }
QPushButton:disabled { background-color: #3a3b45; color: #8a8a95; }
QPushButton#secondary { background-color: #2a2c36; color: #cfcfe0; }
QPushButton#secondary:hover { background-color: #343642; }
QProgressBar {
    background-color: #1f2129; border: none; border-radius: 6px; height: 10px; text-align: center;
}
QProgressBar::chunk { background-color: #6c5ce7; border-radius: 6px; }
QLabel#status_ok { color: #5ee6a3; }
QLabel#status_err { color: #ff6b6b; }
QLabel#status_busy { color: #ffd166; }
QTreeWidget::item { padding: 4px; }
"""


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("media-grabber")
        self.resize(760, 640)
        self.state = load_state()
        self.worker: DownloadWorker | None = None

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        # URL + format row
        row1 = QHBoxLayout()
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("Ссылка на YouTube / Vimeo / Spotify…")
        self.format_combo = QComboBox()
        self.format_combo.addItems(FORMATS.keys())
        self.format_combo.currentTextChanged.connect(self._on_format_changed)
        self.quality_combo = QComboBox()
        self.quality_combo.addItems(QUALITIES.keys())
        row1.addWidget(self.url_edit, 3)
        row1.addWidget(self.format_combo, 1)
        row1.addWidget(self.quality_combo, 1)
        layout.addLayout(row1)

        # Destination row
        row2 = QHBoxLayout()
        self.dest_edit = QLineEdit(self.state.get("last_dest", DEFAULT_DEST))
        self.browse_btn = QPushButton("Папка…")
        self.browse_btn.setObjectName("secondary")
        self.browse_btn.clicked.connect(self._pick_dest)
        row2.addWidget(self.dest_edit, 3)
        row2.addWidget(self.browse_btn, 1)
        layout.addLayout(row2)

        # Download button + progress
        self.download_btn = QPushButton("Скачать")
        self.download_btn.clicked.connect(self._start_download)
        layout.addWidget(self.download_btn)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        self.status_label = QLabel("Готов к работе")
        layout.addWidget(self.status_label)

        # Preview player
        self.video_widget = QVideoWidget()
        self.video_widget.setMinimumHeight(260)
        self.video_widget.hide()
        layout.addWidget(self.video_widget)

        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)
        self.player.setVideoOutput(self.video_widget)

        controls = QHBoxLayout()
        self.play_btn = QPushButton("▶")
        self.play_btn.setObjectName("secondary")
        self.play_btn.setFixedWidth(44)
        self.play_btn.clicked.connect(self._toggle_play)
        self.seek_slider = QSlider(Qt.Horizontal)
        self.seek_slider.sliderMoved.connect(self.player.setPosition)
        self.now_playing_label = QLabel("")
        controls.addWidget(self.play_btn)
        controls.addWidget(self.seek_slider, 3)
        layout.addLayout(controls)
        layout.addWidget(self.now_playing_label)

        self.player.positionChanged.connect(self._on_position)
        self.player.durationChanged.connect(lambda d: self.seek_slider.setRange(0, d))
        self.player.playbackStateChanged.connect(self._on_playback_state)

        # History
        history_header = QHBoxLayout()
        history_header.addWidget(QLabel("История"))
        history_header.addStretch()
        self.delete_history_btn = QPushButton("Удалить выбранное")
        self.delete_history_btn.setObjectName("secondary")
        self.delete_history_btn.clicked.connect(self._delete_selected_history)
        history_header.addWidget(self.delete_history_btn)
        layout.addLayout(history_header)

        self.history_tree = QTreeWidget()
        self.history_tree.setHeaderHidden(True)
        self.history_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        layout.addWidget(self.history_tree, 2)
        self._render_history()

        # Overlay shown during a download, blocking input controls
        self.overlay = QWidget(root)
        self.overlay.setStyleSheet("background-color: rgba(10, 10, 15, 190);")
        overlay_layout = QVBoxLayout(self.overlay)
        self.overlay_label = QLabel("Скачивание…")
        self.overlay_label.setAlignment(Qt.AlignCenter)
        self.overlay_label.setStyleSheet("color: #e6e6f0; font-size: 18px; font-weight: 600; background: transparent;")
        overlay_layout.addStretch()
        overlay_layout.addWidget(self.overlay_label)
        overlay_layout.addStretch()
        self.overlay.hide()

        self._inputs = [
            self.url_edit,
            self.format_combo,
            self.quality_combo,
            self.dest_edit,
            self.browse_btn,
            self.download_btn,
            self.delete_history_btn,
        ]
        self._on_format_changed(self.format_combo.currentText())

    def _on_format_changed(self, text: str) -> None:
        kind, _ = FORMATS[text]
        self.quality_combo.setEnabled(kind == "video")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.overlay.setGeometry(self.centralWidget().rect())

    def _set_busy(self, busy: bool, text: str = "Скачивание…") -> None:
        for w in self._inputs:
            w.setEnabled(not busy)
        if busy:
            self.overlay_label.setText(text)
            self.overlay.setGeometry(self.centralWidget().rect())
            self.overlay.show()
            self.overlay.raise_()
        else:
            self.overlay.hide()

    # -- UI actions ---------------------------------------------------
    def _pick_dest(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Папка для загрузок", self.dest_edit.text())
        if folder:
            self.dest_edit.setText(folder)

    def _start_download(self) -> None:
        url = self.url_edit.text().strip()
        if not url:
            QMessageBox.warning(self, "media-grabber", "Вставь ссылку.")
            return
        kind, container = FORMATS[self.format_combo.currentText()]
        max_height = QUALITIES[self.quality_combo.currentText()]
        dest = self.dest_edit.text().strip() or DEFAULT_DEST
        self.state["last_dest"] = dest
        save_state(self.state)

        self.progress.setValue(0)
        self._set_status("Запуск…", "busy")
        self._set_busy(True, "Скачивание…")

        self.worker = DownloadWorker(url, kind, container, dest, max_height)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished_ok.connect(lambda r: self._on_finished(r, url, kind, container))
        self.worker.failed.connect(lambda e: self._on_failed(e, url, kind, container))
        self.worker.start()

    def _on_progress(self, pct: int, text: str) -> None:
        self.progress.setValue(pct)
        self._set_status(text, "busy")
        self.overlay_label.setText(f"{text} {pct}%" if pct else text)

    def _on_finished(self, result: dict, url: str, kind: str, container: str) -> None:
        self.progress.setValue(100)
        self._set_status(f"Готово: {result['title']}", "ok")
        self._set_busy(False)
        self._add_history(
            {
                "ts": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "url": url,
                "title": result["title"],
                "kind": result["kind"],
                "container": container,
                "site": result["site"],
                "status": "ok",
                "path": result["path"],
            }
        )
        self._load_into_player(result["path"], result["kind"], result["title"])

    def _on_failed(self, message: str, url: str, kind: str, container: str) -> None:
        self.progress.setValue(0)
        self._set_status(f"Ошибка: {message}", "err")
        self._set_busy(False)
        self._add_history(
            {
                "ts": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "url": url,
                "title": url,
                "kind": kind,
                "container": container,
                "site": "spotify" if is_spotify(url) else "yt-dlp",
                "status": "error",
                "error": message,
            }
        )

    def _set_status(self, text: str, kind: str) -> None:
        self.status_label.setText(text)
        self.status_label.setObjectName(f"status_{kind}")
        self.status_label.setStyleSheet("")  # force re-polish of the objectName style

    # -- preview player -------------------------------------------------
    def _load_into_player(self, path: str, kind: str, title: str) -> None:
        self.player.pause()
        self.video_widget.setVisible(kind == "video")
        self.player.setSource(QUrl.fromLocalFile(path))
        self.now_playing_label.setText(f"{'🎬' if kind == 'video' else '🎵'} {title} (готово — нажми ▶)")

    def _toggle_play(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _on_playback_state(self, state: QMediaPlayer.PlaybackState) -> None:
        self.play_btn.setText("⏸" if state == QMediaPlayer.PlayingState else "▶")

    def _on_position(self, pos: int) -> None:
        if not self.seek_slider.isSliderDown():
            self.seek_slider.setValue(pos)

    # -- history ---------------------------------------------------------
    def _add_history(self, entry: dict) -> None:
        self.state.setdefault("history", []).insert(0, entry)
        save_state(self.state)
        self._render_history()

    def _render_history(self) -> None:
        self.history_tree.clear()
        for idx, entry in enumerate(self.state.get("history", [])):
            icon = "🎬" if entry.get("kind") == "video" else "🎵"
            on_disk = entry.get("status") == "ok" and Path(entry.get("path", "")).exists()
            missing = entry.get("status") == "ok" and not on_disk
            mark = "✅" if on_disk else ("🗑" if missing else "⚠️")

            top = QTreeWidgetItem([f"{mark} {icon} {entry['title']}  —  {entry['ts']}"])
            top.setData(0, Qt.UserRole, idx)
            self.history_tree.addTopLevelItem(top)
            if missing:
                top.setDisabled(True)  # file gone from disk: show as info only, no actions

            detail_lines = [f"URL: {entry['url']}", f"Формат: {entry.get('container', '?')}", f"Источник: {entry.get('site', '?')}"]
            if entry.get("status") == "ok":
                detail_lines.append(f"Файл: {entry.get('path', '?')}")
                if missing:
                    detail_lines.append("(файл удалён с диска)")
            else:
                detail_lines.append(f"Ошибка: {entry.get('error', '?')}")
            child = QTreeWidgetItem(["\n".join(detail_lines)])
            top.addChild(child)
            top.setExpanded(False)

            if on_disk:
                play_child = QTreeWidgetItem([""])
                top.addChild(play_child)
                btn = QPushButton("▶ Открыть в плеере")
                btn.setObjectName("secondary")
                path, kind, title = entry["path"], entry["kind"], entry["title"]
                btn.clicked.connect(lambda _=None, p=path, k=kind, t=title: self._load_into_player(p, k, t))
                self.history_tree.setItemWidget(play_child, 0, btn)

    def _delete_selected_history(self) -> None:
        top_items = [it for it in self.history_tree.selectedItems() if it.parent() is None]
        if not top_items:
            QMessageBox.information(self, "media-grabber", "Выбери хотя бы одну запись в истории.")
            return

        box = QMessageBox(self)
        box.setWindowTitle("media-grabber")
        box.setText(f"Удалить {len(top_items)} запись(ей) из истории?")
        only_list_btn = box.addButton("Только из списка", QMessageBox.AcceptRole)
        with_disk_btn = box.addButton("И с диска", QMessageBox.DestructiveRole)
        box.addButton("Отмена", QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked not in (only_list_btn, with_disk_btn):
            return

        history = self.state.get("history", [])
        indices = sorted({it.data(0, Qt.UserRole) for it in top_items}, reverse=True)
        for idx in indices:
            entry = history[idx]
            if clicked is with_disk_btn and entry.get("status") == "ok":
                try:
                    Path(entry["path"]).unlink(missing_ok=True)
                except OSError as e:
                    QMessageBox.warning(self, "media-grabber", f"Не удалось удалить файл {entry['path']}: {e}")
            del history[idx]
        save_state(self.state)
        self._render_history()


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
