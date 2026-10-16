"""media-grabber: paste a URL, pick a format, download, preview in-app.

YouTube/Vimeo/SoundCloud/VK (and anything yt-dlp supports) download directly.
Spotify and Yandex Music are DRM-protected and can't be ripped from the
service itself: Spotify links go through spotdl (metadata from Spotify, audio
matched on YouTube); Yandex Music links download for real, but need your own
account token (Settings) since Yandex has no anonymous API access. Playlist
and album/multi-track links are resolved to a pick-list before downloading.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

os.environ.setdefault("QT_MAC_WANTS_LAYER", "1")  # frozen/signed .app: video widget renders black without this

import yt_dlp
from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
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

from logger import get_logger, setup_logging
from theme import TOKENS, icon, stylesheet

log = get_logger(__name__)

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


YANDEX_TRACK_RE = re.compile(r"music\.yandex\.\w+/album/(\d+)/track/(\d+)")
YANDEX_ALBUM_RE = re.compile(r"music\.yandex\.\w+/album/(\d+)/?(?:[?#]|$)")
YANDEX_PLAYLIST_RE = re.compile(r"music\.yandex\.\w+/users/([^/]+)/playlists/(\d+)")


def is_spotify(url: str) -> bool:
    return "spotify.com" in url


def is_yandex_music(url: str) -> bool:
    return "music.yandex." in url or url.startswith("yandex:")


def _yandex_track_title(track) -> str:
    artists = ", ".join(a.name for a in track.artists) if track.artists else "Unknown"
    return f"{artists} - {track.title}"


_spotdl_client = None  # spotdl's SpotifyClient is a process-wide singleton; re-init raises


def _get_spotdl_client(output_template: str):
    global _spotdl_client
    if _spotdl_client is None:
        from spotdl import Spotdl
        from spotdl.utils.config import DEFAULT_CONFIG

        _spotdl_client = Spotdl(
            client_id=DEFAULT_CONFIG["client_id"],
            client_secret=DEFAULT_CONFIG["client_secret"],
            downloader_settings={"output": output_template},
        )
    else:
        _spotdl_client.downloader.settings["output"] = output_template
    return _spotdl_client


def resolve_playlist(url: str, yandex_token: str) -> tuple[str, list[tuple[str, str]]] | None:
    """If `url` points at a playlist/album/multi-track link, return (collection_title,
    [(title, item_url), ...]) so the UI can offer a pick-list and file things into a
    subfolder named after it. Returns None for an ordinary single-item link."""
    if is_spotify(url):
        client = _get_spotdl_client("{artists} - {title}.{output-ext}")
        songs = client.search([url])
        if len(songs) <= 1:
            return None
        name = songs[0].list_name or songs[0].album_name or "Spotify playlist"
        return name, [(s.display_name, s.url) for s in songs]

    if is_yandex_music(url):
        if YANDEX_TRACK_RE.search(url):
            return None  # single track, nothing to expand
        from yandex_music import Client

        client = Client(yandex_token).init()
        m = YANDEX_ALBUM_RE.search(url)
        if m:
            album = client.albums_with_tracks(m.group(1))
            tracks = [t for volume in (album.volumes or []) for t in volume]
            name = album.title if album else "Yandex album"
        else:
            m = YANDEX_PLAYLIST_RE.search(url)
            if not m:
                return None
            playlist = client.users_playlists(m.group(2), m.group(1))
            tracks = [ts.fetch_track() for ts in playlist.tracks] if playlist else []
            name = playlist.title if playlist else "Yandex playlist"
        items = [(_yandex_track_title(t), f"yandex:{t.id}") for t in tracks]
        return (name, items) if items else None

    # Generic yt-dlp sources (YouTube, Vimeo, SoundCloud, VK, ...)
    # playlistend caps it so an accidentally-pasted channel/feed URL (thousands of videos)
    # can't hang the resolve step or flood the picker dialog.
    with yt_dlp.YoutubeDL({"extract_flat": True, "quiet": True, "skip_download": True, "playlistend": 200}) as ydl:
        info = ydl.extract_info(url, download=False)
    entries = [e for e in (info.get("entries") or []) if e]
    if not entries:
        return None
    items = [(e.get("title") or e.get("id"), e.get("url") or e.get("webpage_url")) for e in entries]
    return info.get("title") or "Playlist", items


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"last_dest": DEFAULT_DEST, "history": []}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2))


class DownloadWorker(QThread):
    progress = Signal(int, str)
    finished_ok = Signal(dict)
    failed = Signal(str)

    def __init__(
        self,
        url: str,
        kind: str,
        container: str,
        dest_dir: str,
        max_height: int | None = None,
        yandex_token: str = "",
    ):
        super().__init__()
        self.url = url
        self.kind = kind
        self.container = container
        self.dest_dir = dest_dir
        self.max_height = max_height
        self.yandex_token = yandex_token

    def run(self) -> None:
        log.info(
            "download.start",
            url=self.url,
            kind=self.kind,
            container=self.container,
            dest_dir=self.dest_dir,
            max_height=self.max_height,
        )
        try:
            if is_spotify(self.url):
                if self.kind == "video":
                    raise ValueError("У Spotify нет видео — выбери «Аудио (MP3)».")
                result = self._spotdl()
            elif is_yandex_music(self.url):
                if self.kind == "video":
                    raise ValueError("У Яндекс.Музыки нет видео — выбери «Аудио (MP3)».")
                result = self._yandex()
            else:
                result = self._ytdlp()
            log.info("download.ok", url=self.url, title=result.get("title"), path=result.get("path"))
            self.finished_ok.emit(result)
        except Exception as e:  # noqa: BLE001 -- yt-dlp/spotdl raise all sorts; surface whatever it is to the UI
            log.error("download.failed", url=self.url, kind=self.kind, error=str(e))
            self.failed.emit(str(e))

    def _hook(self, d: dict) -> None:
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes", 0)
            pct = int(done / total * 95) if total else 0
            self.progress.emit(pct, "Скачивание…")
        elif d["status"] == "finished":
            self.progress.emit(96, "Обработка файла…")

    @staticmethod
    def _make_unique(path: Path) -> Path:
        if not path.exists():
            return path
        n = 1
        while True:
            candidate = path.with_name(f"{path.stem} ({n}){path.suffix}")
            if not candidate.exists():
                return candidate
            n += 1

    def _ytdlp(self) -> dict:
        Path(self.dest_dir).mkdir(parents=True, exist_ok=True)
        ext = "mp3" if self.kind == "audio" else self.container

        # Resolve the title first (no download) so a repeat download of the same
        # video gets "Title (1).ext" instead of silently overwriting the first file.
        probe_opts = {
            "skip_download": True,
            "quiet": True,
            "noplaylist": True,
            "outtmpl": f"{self.dest_dir}/%(title)s.%(ext)s",
        }
        with yt_dlp.YoutubeDL(probe_opts) as probe:
            probe_info = probe.extract_info(self.url, download=False)
        default_path = Path(probe.prepare_filename(probe_info)).with_suffix(f".{ext}")
        unique_stem = self._make_unique(Path(self.dest_dir) / default_path.name).stem
        log.debug("ytdlp.title_resolved", url=self.url, title=probe_info.get("title"), unique_stem=unique_stem)

        opts: dict = {
            "outtmpl": f"{self.dest_dir}/{unique_stem}.%(ext)s",
            "noplaylist": True,
            "progress_hooks": [self._hook],
            "overwrites": True,
            "writethumbnail": True,
            # embed cover art + title/uploader/description/upload_date as container tags
            "postprocessors": [
                {"key": "EmbedThumbnail"},
                {"key": "FFmpegMetadata", "add_metadata": True},
            ],
        }
        if self.kind == "audio":
            opts["format"] = "bestaudio/best"
            opts["postprocessors"].insert(0, {"key": "FFmpegExtractAudio", "preferredcodec": "mp3"})
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

        if self.kind == "video":
            self._fetch_subtitles(unique_stem)

        return {
            "title": info.get("title") or self.url,
            "path": path,
            "kind": self.kind,
            "site": "yt-dlp",
        }

    def _fetch_subtitles(self, stem: str) -> None:
        # A separate, best-effort pass: subtitle fetching (rate limits, missing
        # tracks, etc.) must never take down a video download that already succeeded.
        try:
            sub_opts = {
                "skip_download": True,
                "quiet": True,
                "writesubtitles": True,
                "writeautomaticsub": True,
                "subtitleslangs": ["ru", "en"],
                "outtmpl": f"{self.dest_dir}/{stem}.%(ext)s",
            }
            with yt_dlp.YoutubeDL(sub_opts) as ydl:
                ydl.extract_info(self.url, download=True)
        except Exception as e:  # noqa: BLE001 -- subtitles are a bonus, never fatal
            log.warning("ytdlp.subtitles_skipped", url=self.url, error=str(e))

    def _spotdl(self) -> dict:
        # Drive spotdl's library API in-process rather than shelling out to the "spotdl"
        # CLI command: that command only exists on PATH in the dev venv, not in the
        # frozen .app, where there's no separate spotdl executable to find. The client is
        # a process-wide singleton (spotdl raises on a second init), so it's shared/reused
        # across every item in a playlist batch rather than rebuilt per download.
        Path(self.dest_dir).mkdir(parents=True, exist_ok=True)
        self.progress.emit(10, "Поиск трека через Spotify…")
        client = _get_spotdl_client(f"{self.dest_dir}/{{artists}} - {{title}}.{{output-ext}}")
        songs = client.search([self.url])
        if not songs:
            log.error("spotdl.not_found", url=self.url)
            raise RuntimeError("Spotify: трек не найден")
        log.debug("spotdl.matched", url=self.url, song=songs[0].display_name)
        self.progress.emit(30, "Скачивание через spotdl…")
        song, path = client.download(songs[0])
        if path is None:
            log.error("spotdl.download_failed", url=self.url, song=song.display_name)
            raise RuntimeError("spotdl не смог скачать трек")
        return {"title": song.display_name, "path": str(path), "kind": "audio", "site": "spotify"}

    def _yandex(self) -> dict:
        if not self.yandex_token:
            raise ValueError("Нужен токен Яндекс.Музыки — добавь его в Настройках.")
        from yandex_music import Client

        if self.url.startswith("yandex:"):
            track_id = self.url.split(":", 1)[1]
        else:
            m = YANDEX_TRACK_RE.search(self.url)
            if not m:
                raise ValueError("Не похоже на ссылку на трек Яндекс.Музыки.")
            track_id = m.group(2)

        self.progress.emit(10, "Получение трека с Яндекс.Музыки…")
        client = Client(self.yandex_token).init()
        track = client.tracks([track_id])[0]
        title = _yandex_track_title(track)
        log.debug("yandex.matched", url=self.url, track_id=track_id, title=title)

        Path(self.dest_dir).mkdir(parents=True, exist_ok=True)
        target = self._make_unique(Path(self.dest_dir) / f"{title}.mp3")
        self.progress.emit(40, "Скачивание с Яндекс.Музыки…")
        track.download(str(target))
        self._tag_yandex_track(target, track)
        return {"title": title, "path": str(target), "kind": "audio", "site": "yandex-music"}

    @staticmethod
    def _tag_yandex_track(path: Path, track) -> None:
        # Track.download() only saves raw audio -- unlike spotdl, yandex-music doesn't
        # embed ID3 tags or cover art itself, so do it ourselves.
        from mutagen.id3 import APIC, ID3, TALB, TDRC, TIT2, TPE1, ID3NoHeaderError

        try:
            tags = ID3(path)
        except ID3NoHeaderError:
            tags = ID3()
        tags["TIT2"] = TIT2(encoding=3, text=track.title)
        if track.artists:
            tags["TPE1"] = TPE1(encoding=3, text=", ".join(a.name for a in track.artists))
        if track.albums:
            album = track.albums[0]
            tags["TALB"] = TALB(encoding=3, text=album.title)
            year = getattr(album, "year", None)
            if year:
                tags["TDRC"] = TDRC(encoding=3, text=str(year))
        try:
            cover = track.download_cover_bytes(size="400x400")
            tags["APIC"] = APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=cover)
        except Exception as e:  # noqa: BLE001 -- cover art is a bonus, never fatal
            log.warning("yandex.cover_skipped", error=str(e))
        tags.save(path)


class ResolveWorker(QThread):
    """Checks whether a URL is a playlist/album before the real download starts."""

    resolved = Signal(str, list)  # ("", []) if not a playlist, else (collection_title, [(title, item_url), ...])
    failed = Signal(str)

    def __init__(self, url: str, yandex_token: str):
        super().__init__()
        self.url = url
        self.yandex_token = yandex_token

    def run(self) -> None:
        try:
            result = resolve_playlist(self.url, self.yandex_token)
            name, items = result if result else ("", [])
            self.resolved.emit(name, items)
        except Exception as e:  # noqa: BLE001 -- surfaced to the UI as a plain error, not fatal
            log.error("resolve.failed", url=self.url, error=str(e))
            self.failed.emit(str(e))


class PlaylistDialog(QDialog):
    def __init__(self, name: str, items: list[tuple[str, str]], parent=None):
        super().__init__(parent)
        self.setWindowTitle(name or "Плейлист / альбом")
        self.resize(480, 420)
        self.items = items

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"«{name}» — найдено {len(items)}. Выбери, что скачать:"))
        layout.addWidget(QLabel(f"Сохранится в подпапку «{name}»."))

        self.list_widget = QListWidget()
        for title, _ref in items:
            item = QListWidgetItem(title)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self.list_widget.addItem(item)
        layout.addWidget(self.list_widget)

        select_row = QHBoxLayout()
        all_btn = QPushButton("Выбрать всё")
        all_btn.setObjectName("secondary")
        all_btn.clicked.connect(lambda: self._set_all(Qt.Checked))
        none_btn = QPushButton("Снять всё")
        none_btn.setObjectName("secondary")
        none_btn.clicked.connect(lambda: self._set_all(Qt.Unchecked))
        select_row.addWidget(all_btn)
        select_row.addWidget(none_btn)
        layout.addLayout(select_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _set_all(self, state) -> None:
        for i in range(self.list_widget.count()):
            self.list_widget.item(i).setCheckState(state)

    def selected_items(self) -> list[tuple[str, str]]:
        return [
            self.items[i] for i in range(self.list_widget.count()) if self.list_widget.item(i).checkState() == Qt.Checked
        ]


class SettingsDialog(QDialog):
    def __init__(self, yandex_token: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройки")
        self.resize(420, 140)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Токен Яндекс.Музыки (нужен для скачивания — своей учётки, без него API анонимно не отдаёт треки):"))
        self.token_edit = QLineEdit(yandex_token)
        self.token_edit.setPlaceholderText("OAuth-токен аккаунта Яндекс.Музыки")
        layout.addWidget(self.token_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def token(self) -> str:
        return self.token_edit.text().strip()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("media-grabber")
        self.resize(820, 700)
        self.state = load_state()
        self.worker: DownloadWorker | None = None
        self.theme = self.state.get("theme", "dark")

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setSpacing(12)
        layout.setContentsMargins(18, 16, 18, 16)

        # Header: title + theme switch
        header = QHBoxLayout()
        title_label = QLabel("media-grabber")
        title_label.setObjectName("heading")
        header.addWidget(title_label)
        header.addStretch()
        self.theme_btn = QPushButton()
        self.theme_btn.setObjectName("iconBtn")
        self.theme_btn.setToolTip("Светлая / тёмная тема")
        self.theme_btn.clicked.connect(self._toggle_theme)
        header.addWidget(self.theme_btn)
        layout.addLayout(header)

        # URL + format row
        row1 = QHBoxLayout()
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText(
            "Ссылка на YouTube / Vimeo / SoundCloud / VK / Spotify / Яндекс.Музыку… (в т.ч. плейлист/альбом)"
        )
        self.format_combo = QComboBox()
        self.format_combo.addItems(FORMATS.keys())
        self.format_combo.currentTextChanged.connect(self._on_format_changed)
        self.url_edit.textChanged.connect(self._on_url_changed)
        self.quality_combo = QComboBox()
        self.quality_combo.addItems(QUALITIES.keys())
        self.open_browser_btn = QPushButton()
        self.open_browser_btn.setObjectName("iconBtn")
        self.open_browser_btn.setToolTip("Открыть ссылку в браузере")
        self.open_browser_btn.clicked.connect(self._open_current_url)
        row1.addWidget(self.url_edit, 3)
        row1.addWidget(self.format_combo, 1)
        row1.addWidget(self.quality_combo, 1)
        row1.addWidget(self.open_browser_btn)
        layout.addLayout(row1)

        # Destination row
        row2 = QHBoxLayout()
        self.dest_edit = QLineEdit(self.state.get("last_dest", DEFAULT_DEST))
        self.browse_btn = QPushButton("Папка…")
        self.browse_btn.setObjectName("secondary")
        self.browse_btn.clicked.connect(self._pick_dest)
        self.settings_btn = QPushButton("Настройки")
        self.settings_btn.setObjectName("secondary")
        self.settings_btn.clicked.connect(self._open_settings)
        row2.addWidget(self.dest_edit, 3)
        row2.addWidget(self.browse_btn, 1)
        row2.addWidget(self.settings_btn, 1)
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
        self.video_widget.setObjectName("card")
        self.video_widget.setMinimumHeight(260)
        self.video_widget.hide()
        layout.addWidget(self.video_widget)

        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)
        self.player.setVideoOutput(self.video_widget)

        controls = QHBoxLayout()
        self.play_btn = QPushButton()
        self.play_btn.setObjectName("iconBtn")
        self.play_btn.clicked.connect(self._toggle_play)
        self.seek_slider = QSlider(Qt.Horizontal)
        self.seek_slider.sliderMoved.connect(self.player.setPosition)
        self.now_playing_label = QLabel("")
        self.now_playing_label.setObjectName("dim")
        controls.addWidget(self.play_btn)
        controls.addWidget(self.seek_slider, 3)
        layout.addLayout(controls)
        layout.addWidget(self.now_playing_label)

        self.player.positionChanged.connect(self._on_position)
        self.player.durationChanged.connect(lambda d: self.seek_slider.setRange(0, d))
        self.player.playbackStateChanged.connect(self._on_playback_state)

        # History
        history_header = QHBoxLayout()
        history_title = QLabel("История")
        history_title.setObjectName("heading")
        history_header.addWidget(history_title)
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
        overlay_layout = QVBoxLayout(self.overlay)
        self.overlay_label = QLabel("Скачивание…")
        self.overlay_label.setAlignment(Qt.AlignCenter)
        self.overlay_label.setStyleSheet("font-size: 18px; font-weight: 700; background: transparent;")
        overlay_layout.addStretch()
        overlay_layout.addWidget(self.overlay_label)
        overlay_layout.addStretch()
        self.overlay.hide()

        self._apply_theme()

        self._inputs = [
            self.url_edit,
            self.format_combo,
            self.quality_combo,
            self.dest_edit,
            self.browse_btn,
            self.settings_btn,
            self.download_btn,
            self.delete_history_btn,
        ]
        self._on_format_changed(self.format_combo.currentText())
        self._queue: list[tuple[str, str]] = []  # (title, ref_url) still to download
        self._queue_kind = ""
        self._queue_container = ""
        self._queue_max_height: int | None = None
        self._queue_total = 0

    def _on_format_changed(self, text: str) -> None:
        kind, _ = FORMATS[text]
        self.quality_combo.setEnabled(kind == "video")

    def _on_url_changed(self, text: str) -> None:
        # Spotify/Yandex Music are audio-only: there's no video to offer, so grey that
        # choice out instead of letting the user pick it and hit an error on download.
        audio_only = is_spotify(text) or is_yandex_music(text)
        model = self.format_combo.model()
        for i in range(self.format_combo.count()):
            kind, _ = FORMATS[self.format_combo.itemText(i)]
            model.item(i).setEnabled(not (audio_only and kind == "video"))
        if audio_only and FORMATS[self.format_combo.currentText()][0] == "video":
            audio_key = next(k for k, (kind, _) in FORMATS.items() if kind == "audio")
            self.format_combo.setCurrentText(audio_key)

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self.state.get("yandex_token", ""), self)
        if dlg.exec() == QDialog.Accepted:
            self.state["yandex_token"] = dlg.token()
            save_state(self.state)

    def _open_current_url(self) -> None:
        url = self.url_edit.text().strip()
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def _toggle_theme(self) -> None:
        self.theme = "light" if self.theme == "dark" else "dark"
        self.state["theme"] = self.theme
        save_state(self.state)
        self._apply_theme()
        self._render_history()

    def _apply_theme(self) -> None:
        t = TOKENS[self.theme]
        QApplication.instance().setStyleSheet(stylesheet(self.theme))
        self.theme_btn.setIcon(icon("sun" if self.theme == "dark" else "moon", t["icon"]))
        self.open_browser_btn.setIcon(icon("globe", t["icon"]))
        self.play_btn.setIcon(icon("pause" if self._is_playing() else "play", t["icon"]))
        self.browse_btn.setIcon(icon("folder", t["icon"]))
        self.settings_btn.setIcon(icon("settings", t["icon"]))
        self.delete_history_btn.setIcon(icon("trash", t["icon"]))
        self.download_btn.setIcon(icon("download", t["accent_text"]))
        self.overlay.setStyleSheet(f"background-color: {('rgba(10, 10, 15, 200)' if self.theme == 'dark' else 'rgba(255, 255, 255, 215)')};")

    def _is_playing(self) -> bool:
        return self.player.playbackState() == QMediaPlayer.PlayingState

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

        log.info("ui.download_clicked", url=url, kind=kind, container=container, dest=dest, max_height=max_height)
        self._set_busy(True, "Проверяю ссылку…")

        self._resolver = ResolveWorker(url, self.state.get("yandex_token", ""))
        self._resolver.resolved.connect(
            lambda name, items: self._on_resolved(name, items, url, kind, container, dest, max_height)
        )
        self._resolver.failed.connect(self._on_resolve_failed)
        self._resolver.start()

    def _on_resolve_failed(self, message: str) -> None:
        self._set_busy(False)
        self._set_status(f"Ошибка: {message}", "err")

    def _on_resolved(
        self, name: str, items: list, url: str, kind: str, container: str, dest: str, max_height: int | None
    ) -> None:
        if not items:
            self._begin_single(url, kind, container, dest, max_height)
            return

        self._set_busy(False)
        dlg = PlaylistDialog(name, items, self)
        if dlg.exec() != QDialog.Accepted:
            self._set_status("Отменено", "err")
            return
        chosen = dlg.selected_items()
        if not chosen:
            self._set_status("Ничего не выбрано", "err")
            return
        subfolder = re.sub(r'[\\/:*?"<>|]', "_", name).strip() or "Playlist"
        self._start_batch(chosen, kind, container, str(Path(dest) / subfolder), max_height)

    def _begin_single(self, url: str, kind: str, container: str, dest: str, max_height: int | None) -> None:
        self._queue_total = 0
        self.progress.setValue(0)
        self._set_status("Запуск…", "busy")
        self._set_busy(True, "Скачивание…")

        self.worker = DownloadWorker(url, kind, container, dest, max_height, self.state.get("yandex_token", ""))
        self.worker.progress.connect(self._on_progress)
        self.worker.finished_ok.connect(lambda r: self._on_finished(r, url, kind, container))
        self.worker.failed.connect(lambda e: self._on_failed(e, url, kind, container))
        self.worker.start()

    def _start_batch(self, items: list[tuple[str, str]], kind: str, container: str, dest: str, max_height) -> None:
        self._queue = list(items)
        self._queue_kind = kind
        self._queue_container = container
        self._queue_dest = dest
        self._queue_max_height = max_height
        self._queue_total = len(items)
        self._queue_done = 0
        self._set_busy(True, f"Плейлист: 0/{self._queue_total}")
        self._download_next_in_queue()

    def _download_next_in_queue(self) -> None:
        if not self._queue:
            self._set_busy(False)
            self._set_status(f"Готово: плейлист ({self._queue_done}/{self._queue_total})", "ok")
            return
        title, ref = self._queue.pop(0)
        self.progress.setValue(0)
        self.worker = DownloadWorker(
            ref, self._queue_kind, self._queue_container, self._queue_dest, self._queue_max_height,
            self.state.get("yandex_token", ""),
        )
        self.worker.progress.connect(self._on_progress)
        self.worker.finished_ok.connect(lambda r: self._on_queue_item_finished(r, ref, title))
        self.worker.failed.connect(lambda e: self._on_queue_item_failed(e, ref, title))
        self.worker.start()

    def _on_queue_item_finished(self, result: dict, url: str, title: str) -> None:
        self._queue_done += 1
        self._add_history(
            {
                "ts": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "url": url,
                "title": result["title"],
                "kind": result["kind"],
                "container": self._queue_container,
                "site": result["site"],
                "status": "ok",
                "path": result["path"],
            }
        )
        self._download_next_in_queue()

    def _on_queue_item_failed(self, message: str, url: str, title: str) -> None:
        self._queue_done += 1
        self._add_history(
            {
                "ts": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "url": url,
                "title": title or url,
                "kind": self._queue_kind,
                "container": self._queue_container,
                "site": "yt-dlp",
                "status": "error",
                "error": message,
            }
        )
        self._download_next_in_queue()

    def _on_progress(self, pct: int, text: str) -> None:
        prefix = f"[{self._queue_done + 1}/{self._queue_total}] " if self._queue_total else ""
        full_text = f"{prefix}{text}"
        self.progress.setValue(pct)
        self._set_status(full_text, "busy")
        self.overlay_label.setText(f"{full_text} {pct}%" if pct else full_text)

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
                "site": "yandex-music" if is_yandex_music(url) else ("spotify" if is_spotify(url) else "yt-dlp"),
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
        name = "pause" if state == QMediaPlayer.PlayingState else "play"
        self.play_btn.setIcon(icon(name, TOKENS[self.theme]["icon"]))

    def _on_position(self, pos: int) -> None:
        if not self.seek_slider.isSliderDown():
            self.seek_slider.setValue(pos)

    # -- history ---------------------------------------------------------
    def _add_history(self, entry: dict) -> None:
        self.state.setdefault("history", []).insert(0, entry)
        save_state(self.state)
        self._render_history()

    def _render_history(self) -> None:
        t = TOKENS[self.theme]
        self.history_tree.clear()
        for idx, entry in enumerate(self.state.get("history", [])):
            kind_word = "видео" if entry.get("kind") == "video" else "аудио"
            on_disk = entry.get("status") == "ok" and Path(entry.get("path", "")).exists()
            missing = entry.get("status") == "ok" and not on_disk
            if on_disk:
                status_icon, status_color = "check", t["success"]
            elif missing:
                status_icon, status_color = "trash", t["text_dim"]
            else:
                status_icon, status_color = "alert", t["danger"]

            top = QTreeWidgetItem([f"{entry['title']}  —  {kind_word}  —  {entry['ts']}"])
            top.setIcon(0, icon(status_icon, status_color))
            top.setData(0, Qt.UserRole, idx)
            self.history_tree.addTopLevelItem(top)
            if missing:
                # file gone from disk: grey it out (no play button below), but keep it
                # selectable so it can still be picked and removed from the list
                top.setForeground(0, QColor(t["text_dim"]))

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

            actions_child = QTreeWidgetItem([""])
            top.addChild(actions_child)
            actions_row = QWidget()
            actions_layout = QHBoxLayout(actions_row)
            actions_layout.setContentsMargins(0, 0, 0, 0)
            if on_disk:
                play_btn = QPushButton(" Открыть в плеере")
                play_btn.setObjectName("secondary")
                play_btn.setIcon(icon("play", t["icon"]))
                path, kind, title = entry["path"], entry["kind"], entry["title"]
                play_btn.clicked.connect(lambda _=None, p=path, k=kind, t=title: self._load_into_player(p, k, t))
                actions_layout.addWidget(play_btn)
            link_btn = QPushButton(" Открыть ссылку")
            link_btn.setIcon(icon("globe", t["icon"]))
            link_btn.setObjectName("secondary")
            entry_url = entry["url"]
            link_btn.clicked.connect(lambda _=None, u=entry_url: QDesktopServices.openUrl(QUrl(u)))
            actions_layout.addWidget(link_btn)
            actions_layout.addStretch()
            self.history_tree.setItemWidget(actions_child, 0, actions_row)

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
        delete_from_disk = clicked is with_disk_btn
        log.info("ui.history_delete", count=len(indices), delete_from_disk=delete_from_disk)
        for idx in indices:
            entry = history[idx]
            if delete_from_disk and entry.get("status") == "ok":
                try:
                    Path(entry["path"]).unlink(missing_ok=True)
                except OSError as e:
                    log.error("ui.history_delete_file_failed", path=entry["path"], error=str(e))
                    QMessageBox.warning(self, "media-grabber", f"Не удалось удалить файл {entry['path']}: {e}")
            del history[idx]
        save_state(self.state)
        self._render_history()


def main() -> None:
    setup_logging()
    log.info("app.start")
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
