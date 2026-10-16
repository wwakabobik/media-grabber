"""media-grabber: paste a URL, pick a format, download, preview in-app.

YouTube/Vimeo/SoundCloud/VK (and anything yt-dlp supports) download directly.
Spotify and Yandex Music are DRM-protected and can't be ripped from the
service itself: Spotify links go through spotdl (metadata from Spotify, audio
matched on YouTube); Yandex Music links download for real, but need your own
account token (Settings) since Yandex has no anonymous API access. Playlist
and album/multi-track links are resolved to a pick-list before downloading.
"""
from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

os.environ.setdefault("QT_MAC_WANTS_LAYER", "1")  # frozen/signed .app: video widget renders black without this

def _ensure_ffmpeg_on_path() -> None:
    """A frozen .app launched from Finder/LaunchServices gets a minimal PATH
    (just /usr/bin:/bin:/usr/sbin:/sbin -- no Homebrew), so yt-dlp's ffmpeg
    check fails with "ffmpeg is not installed" even on a machine that
    genuinely has it installed, confirmed via a real report with Homebrew's
    ffmpeg present at /opt/homebrew/bin. Extends PATH with the common
    Homebrew locations if ffmpeg isn't already reachable -- a no-op
    everywhere else (Terminal/dev venv already has the right PATH, so
    shutil.which succeeds and this never runs)."""
    if sys.platform != "darwin" or shutil.which("ffmpeg") is not None:
        return
    for brew_bin in ("/opt/homebrew/bin", "/usr/local/bin"):
        if Path(brew_bin, "ffmpeg").exists():
            os.environ["PATH"] = f"{brew_bin}:{os.environ.get('PATH', '')}"
            return


_ensure_ffmpeg_on_path()

import yt_dlp
from PySide6.QtCore import Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
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
    QScrollArea,
    QSlider,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from i18n import LANGUAGES, get_language, set_language, tr
from logger import (
    DEFAULT_LOG_BACKUP_COUNT,
    DEFAULT_LOG_MAX_MB,
    LOG_FILE,
    apply_log_rotation_settings,
    get_logger,
    setup_logging,
)
from theme import TOKENS, icon, stylesheet

log = get_logger(__name__)

STATE_PATH = Path.home() / ".config" / "media-grabber" / "state.json"
DEFAULT_DEST = str(Path.home() / "Downloads")

# Stable internal keys -> (kind, container); display text is tr("format.<key>"),
# looked up by key (QComboBox userData) rather than currentText() so the combo
# can be relabeled on a language switch without losing the selection.
FORMATS = {
    "video_mp4": ("video", "mp4"),
    "video_webm": ("video", "webm"),
    "audio_mp3": ("audio", "mp3"),
}

QUALITIES = {
    "best": None,
    "1080p": 1080,
    "720p": 720,
    "480p": 480,
    "360p": 360,
}

THEME_OPTIONS = ["light", "dark", "system"]
THEME_ICONS = {"light": "sun", "dark": "moon", "system": "monitor"}


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


class _SpotdlHandle:
    """Thin per-call stand-in for spotdl's Spotdl class, deliberately never
    shared across threads -- see _get_spotdl_client for why."""

    def __init__(self, downloader):
        self.downloader = downloader

    def search(self, query: list[str]):
        from spotdl.utils.search import parse_query

        s = self.downloader.settings
        return parse_query(
            query=query,
            threads=s["threads"],
            use_ytm_data=s["ytm_data"],
            playlist_numbering=s["playlist_numbering"],
            album_type=s["album_type"],
            playlist_retain_track_cover=s["playlist_retain_track_cover"],
        )

    def download(self, song):
        return self.downloader.download_song(song)


def _get_spotdl_client(output_template: str) -> _SpotdlHandle:
    """Returns a fresh, thread-private handle for talking to spotdl.

    Previous attempts reused one Spotdl/Downloader across calls (a module-level
    singleton, rebuilt per call to dodge the next problem). Both failed because
    DownloadWorker, ResolveWorker and the debounced PreviewWorker are each their
    own QThread, started close together by normal use (e.g. typing a URL fires
    a preview fetch ~700ms later, often overlapping a Download click) -- and
    reproduced directly, two such calls racing on a shared singleton throw any
    of: "There is no current event loop in thread 'Dummy-N'", "The future
    belongs to a different loop", "A spotify client has already been
    initialized", or "cannot schedule new futures after shutdown" (one thread's
    rebuild tearing down a Downloader the other thread is still using).

    The only part of spotdl that must truly be one-per-process is SpotifyClient
    (the Spotify auth; spotipy's own global, raises if initialized twice) --
    and that's fine to leave initialized and shared read-only. The Downloader
    (event loop + semaphore + thread pool) is rebuilt fresh on every single
    call instead, so no two threads ever touch the same one.

    simple_tui=True is required: a non-simple Downloader opens a
    rich.progress.Progress "Live" display in its ProgressHandler.__init__, and
    only one Live may be active per process -- building more than one without
    it raises "Only one live display may be active at once". This app has its
    own Qt progress bar; spotdl's console TUI was never wired to anything here.
    """
    from spotdl.download.downloader import Downloader
    from spotdl.utils.config import DEFAULT_CONFIG
    from spotdl.utils.spotify import SpotifyClient, SpotifyError

    try:
        SpotifyClient.init(
            client_id=DEFAULT_CONFIG["client_id"],
            client_secret=DEFAULT_CONFIG["client_secret"],
        )
    except SpotifyError:
        pass  # already initialized by an earlier call -- that's exactly the point

    downloader = Downloader(settings={"output": output_template, "simple_tui": True})
    return _SpotdlHandle(downloader)


def read_media_info(path: str) -> dict:
    """Best-effort read of duration + embedded cover art from an already-downloaded file,
    for display in the history list. Never raises -- returns whatever it could get."""
    info: dict = {}
    try:
        from mutagen import File as MutagenFile

        probe = MutagenFile(path)
        if probe and probe.info and getattr(probe.info, "length", None):
            info["duration"] = probe.info.length
    except Exception as e:  # noqa: BLE001 -- metadata is a nice-to-have, never fatal
        log.debug("media_info.duration_failed", path=path, error=str(e))

    try:
        ext = Path(path).suffix.lower()
        cover_bytes = None
        if ext == ".mp3":
            from mutagen.id3 import ID3

            apics = ID3(path).getall("APIC")
            if apics:
                cover_bytes = apics[0].data
        elif ext in (".mp4", ".m4a"):
            from mutagen.mp4 import MP4

            covers = MP4(path).get("covr")
            if covers:
                cover_bytes = bytes(covers[0])
        if cover_bytes:
            info["cover"] = cover_bytes
    except Exception as e:  # noqa: BLE001 -- same as above
        log.debug("media_info.cover_failed", path=path, error=str(e))
    return info


def format_duration(seconds: float | None) -> str:
    if not seconds:
        return "?"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def format_chapters(chapters: list[dict] | None) -> str | None:
    """YouTube's auto/uploader chapters -- timestamped key moments. Can't reuse
    format_duration(): a chapter legitimately starts at 0, but format_duration
    treats 0 as "unknown" and prints "?" (by design, for missing media info)."""
    if not chapters:
        return None

    def _timestamp(seconds) -> str:
        m, s = divmod(int(seconds or 0), 60)
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

    lines = [f"{_timestamp(c.get('start_time'))}  {c.get('title', '?')}" for c in chapters]
    return tr("chapters.header") + "\n" + "\n".join(lines)


def clean_description(text: str | None) -> str | None:
    """SoundCloud (and some others) hand back raw HTML in the description field;
    everyone else already gives plain text, where this is a no-op."""
    if not text:
        return None
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).replace("\xa0", " ").strip() or None


def friendly_error(url: str, message: str) -> str:
    """Vimeo's web client refuses yt-dlp entirely without a logged-in session
    cookie (confirmed against several real public Vimeo videos, not just a
    guess) -- translate that one well-known, unfixable-without-cookies case
    instead of surfacing yt-dlp's raw English wall of text."""
    if "vimeo.com" in url and "only works when logged-in" in message:
        return tr("error.vimeo_login_wall")
    return message


def reveal_in_finder(path: str) -> None:
    if sys.platform == "darwin":
        subprocess.run(["open", "-R", path], check=False)
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))


def make_unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    n = 1
    while True:
        candidate = path.with_name(f"{path.stem} ({n}){path.suffix}")
        if not candidate.exists():
            return candidate
        n += 1


def entry_disk_status(entry: dict) -> str:
    """"on_disk" (downloaded and still there), "missing" (downloaded, file
    gone since -- deleted outside the app) or "error" (download itself failed)."""
    if entry.get("status") != "ok":
        return "error"
    return "on_disk" if Path(entry.get("path", "")).exists() else "missing"


# Audio-only containers a file can be converted to. Video can additionally
# convert to another video container (CONVERT_VIDEO_TARGETS) or have its
# audio extracted into one of these -- never the other way around (no app
# here can synthesize video from audio).
CONVERT_AUDIO_TARGETS = ["mp3", "wav", "m4a", "flac", "ogg", "aac", "opus"]
CONVERT_VIDEO_TARGETS = ["mp4", "webm", "mkv", "mov", "avi"]


class ConvertWorker(QThread):
    """Runs ffmpeg directly (not through yt-dlp) to transcode an already
    downloaded file, or pull just the audio out of a video, into a separate
    new file -- the source is never modified or removed."""

    finished_ok = Signal(dict)
    failed = Signal(str)

    def __init__(self, src_path: str, target_container: str, audio_only: bool):
        super().__init__()
        self.src_path = src_path
        self.target_container = target_container
        self.audio_only = audio_only

    def run(self) -> None:
        src = Path(self.src_path)
        dest = make_unique_path(src.with_name(f"{src.stem} (converted).{self.target_container}"))
        cmd = ["ffmpeg", "-y", "-i", str(src)]
        if self.audio_only:
            cmd.append("-vn")
        cmd.append(str(dest))
        log.info("convert.start", src=self.src_path, dest=str(dest))
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            log.error("convert.failed", src=self.src_path, error=e.stderr[-500:] if e.stderr else str(e))
            self.failed.emit(e.stderr.strip().splitlines()[-1] if e.stderr else str(e))
            return
        except FileNotFoundError:
            self.failed.emit("ffmpeg not found")
            return
        kind = "audio" if self.audio_only else ("audio" if self.target_container in CONVERT_AUDIO_TARGETS else "video")
        log.info("convert.ok", dest=str(dest))
        self.finished_ok.emit({"path": str(dest), "kind": kind, "container": self.target_container})


class ConvertDialog(QDialog):
    def __init__(self, src_kind: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("dialog.convert_title"))
        self.resize(360, 140)
        # (container, audio_only) pairs the combo offers for this source kind.
        self.targets: list[tuple[str, bool]] = [(c, False) for c in CONVERT_AUDIO_TARGETS]
        if src_kind == "video":
            self.targets = [(c, False) for c in CONVERT_VIDEO_TARGETS] + [(c, True) for c in CONVERT_AUDIO_TARGETS]

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr("convert.target_label")))
        self.target_combo = QComboBox()
        for container, audio_only in self.targets:
            label = f"{container} ({tr('kind.audio')})" if audio_only else container
            self.target_combo.addItem(label)
        layout.addWidget(self.target_combo)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(tr("convert.button"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def target(self) -> tuple[str, bool]:
        return self.targets[self.target_combo.currentIndex()]


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
                    raise ValueError(tr("error.spotify_no_video"))
                result = self._spotdl()
            elif is_yandex_music(self.url):
                if self.kind == "video":
                    raise ValueError(tr("error.yandex_no_video"))
                result = self._yandex()
            else:
                result = self._ytdlp()
            log.info("download.ok", url=self.url, title=result.get("title"), path=result.get("path"))
            self.finished_ok.emit(result)
        except Exception as e:  # noqa: BLE001 -- yt-dlp/spotdl raise all sorts; surface whatever it is to the UI
            log.error("download.failed", url=self.url, kind=self.kind, error=str(e))
            self.failed.emit(friendly_error(self.url, str(e)))

    def _hook(self, d: dict) -> None:
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes", 0)
            pct = int(done / total * 95) if total else 0
            self.progress.emit(pct, tr("progress.downloading"))
        elif d["status"] == "finished":
            self.progress.emit(96, tr("progress.processing_file"))

    @staticmethod
    def _make_unique(path: Path) -> Path:
        return make_unique_path(path)

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

        subtitle_files = self._fetch_subtitles(unique_stem) if self.kind == "video" else []

        return {
            "title": info.get("title") or self.url,
            "path": path,
            "kind": self.kind,
            "site": "yt-dlp",
            "description": clean_description(info.get("description")),
            "subtitle_files": subtitle_files,
            # YouTube's auto/uploader chapters -- timestamped key moments, the
            # closest thing yt-dlp exposes to YouTube's "AI summary" chapter list.
            "chapters": info.get("chapters") or [],
        }

    def _fetch_subtitles(self, stem: str) -> list[str]:
        # A separate, best-effort pass: subtitle fetching (rate limits, missing
        # tracks, etc.) must never take down a video download that already succeeded.
        # One language at a time: yt-dlp aborts the whole subtitle step on the first
        # failing language in a batch request, which would silently drop a language
        # that was actually available just because another one got rate-limited.
        written: list[str] = []
        for lang in ("ru", "en"):
            try:
                before = set(Path(self.dest_dir).glob(f"{stem}.*"))
                sub_opts = {
                    "skip_download": True,
                    "quiet": True,
                    "writesubtitles": True,
                    "writeautomaticsub": True,
                    "subtitleslangs": [lang],
                    "outtmpl": f"{self.dest_dir}/{stem}.%(ext)s",
                }
                with yt_dlp.YoutubeDL(sub_opts) as ydl:
                    ydl.extract_info(self.url, download=True)
                written.extend(str(p) for p in (set(Path(self.dest_dir).glob(f"{stem}.*")) - before))
            except Exception as e:  # noqa: BLE001 -- subtitles are a bonus, never fatal
                log.warning("ytdlp.subtitles_skipped", url=self.url, lang=lang, error=str(e))
        return sorted(written)

    def _spotdl(self) -> dict:
        # Drive spotdl's library API in-process rather than shelling out to the "spotdl"
        # CLI command: that command only exists on PATH in the dev venv, not in the
        # frozen .app, where there's no separate spotdl executable to find. The client is
        # a process-wide singleton (spotdl raises on a second init), so it's shared/reused
        # across every item in a playlist batch rather than rebuilt per download.
        Path(self.dest_dir).mkdir(parents=True, exist_ok=True)
        self.progress.emit(10, tr("progress.spotify_search"))
        client = _get_spotdl_client(f"{self.dest_dir}/{{artists}} - {{title}}.{{output-ext}}")
        songs = client.search([self.url])
        if not songs:
            log.error("spotdl.not_found", url=self.url)
            raise RuntimeError(tr("error.spotify_not_found"))
        log.debug("spotdl.matched", url=self.url, song=songs[0].display_name)
        self.progress.emit(30, tr("progress.spotify_downloading"))
        song, path = client.download(songs[0])
        if path is None:
            log.error("spotdl.download_failed", url=self.url, song=song.display_name)
            raise RuntimeError(tr("error.spotdl_failed"))
        return {
            "title": song.display_name,
            "path": str(path),
            "kind": "audio",
            "site": "spotify",
            "lyrics": song.lyrics or None,
        }

    def _yandex(self) -> dict:
        if not self.yandex_token:
            raise ValueError(tr("error.yandex_token_needed"))
        from yandex_music import Client

        if self.url.startswith("yandex:"):
            track_id = self.url.split(":", 1)[1]
        else:
            m = YANDEX_TRACK_RE.search(self.url)
            if not m:
                raise ValueError(tr("error.yandex_bad_url"))
            track_id = m.group(2)

        self.progress.emit(10, tr("progress.yandex_fetching"))
        client = Client(self.yandex_token).init()
        track = client.tracks([track_id])[0]
        title = _yandex_track_title(track)
        log.debug("yandex.matched", url=self.url, track_id=track_id, title=title)

        Path(self.dest_dir).mkdir(parents=True, exist_ok=True)
        target = self._make_unique(Path(self.dest_dir) / f"{title}.mp3")
        self.progress.emit(40, tr("progress.yandex_downloading"))
        track.download(str(target))
        self._tag_yandex_track(target, track)
        lyrics = None
        try:
            lyrics_handle = track.get_lyrics()
            if lyrics_handle:
                lyrics = lyrics_handle.fetch_lyrics()
        except Exception as e:  # noqa: BLE001 -- lyrics are a bonus, never fatal
            log.debug("yandex.lyrics_failed", url=self.url, error=str(e))
        return {
            "title": title,
            "path": str(target),
            "kind": "audio",
            "site": "yandex-music",
            "lyrics": lyrics,
        }

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
            self.failed.emit(friendly_error(self.url, str(e)))


class PreviewWorker(QThread):
    """Fetches just enough (title/duration/cover) to show a live preview before the
    real download starts -- no download, no playlist expansion, best-effort only."""

    ready = Signal(dict)
    failed = Signal(str)

    def __init__(self, url: str, yandex_token: str):
        super().__init__()
        self.url = url
        self.yandex_token = yandex_token

    @staticmethod
    def _download_bytes(url: str) -> bytes | None:
        try:
            with urllib.request.urlopen(url, timeout=8) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001 -- a missing thumbnail is not a failure
            log.debug("preview.thumbnail_failed", url=url, error=str(e))
            return None

    def run(self) -> None:
        try:
            self.ready.emit(self._fetch())
        except Exception as e:  # noqa: BLE001 -- surfaced as "no preview", not fatal
            self.failed.emit(str(e))

    def _fetch(self) -> dict:
        if is_spotify(self.url):
            client = _get_spotdl_client("{artists} - {title}.{output-ext}")
            songs = client.search([self.url])
            if not songs:
                raise RuntimeError("Spotify: nothing found")  # never shown to the user, preview failures are silent
            song = songs[0]
            cover = self._download_bytes(song.cover_url) if song.cover_url else None
            return {"title": song.display_name, "duration": song.duration, "cover": cover}

        if is_yandex_music(self.url):
            if not self.yandex_token:
                raise RuntimeError("token needed")  # never shown to the user, preview failures are silent
            m = YANDEX_TRACK_RE.search(self.url)
            if not m:
                raise RuntimeError("doesn't look like a track")
            from yandex_music import Client

            client = Client(self.yandex_token).init()
            track = client.tracks([m.group(2)])[0]
            try:
                cover = track.download_cover_bytes(size="200x200")
            except Exception as e:  # noqa: BLE001 -- cover is optional
                log.debug("preview.yandex_cover_failed", error=str(e))
                cover = None
            duration = track.duration_ms / 1000 if getattr(track, "duration_ms", None) else None
            return {"title": _yandex_track_title(track), "duration": duration, "cover": cover}

        # Generic yt-dlp sources (YouTube, Vimeo, SoundCloud, VK, ...)
        with yt_dlp.YoutubeDL({"skip_download": True, "quiet": True, "noplaylist": True}) as ydl:
            info = ydl.extract_info(self.url, download=False)
        thumb = info.get("thumbnail")
        cover = self._download_bytes(thumb) if thumb else None
        return {"title": info.get("title"), "duration": info.get("duration"), "cover": cover}


class PlaylistDialog(QDialog):
    def __init__(self, name: str, items: list[tuple[str, str]], parent=None):
        super().__init__(parent)
        self.setWindowTitle(name or tr("dialog.playlist_default_title"))
        self.resize(480, 420)
        self.items = items

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr("dialog.playlist_found", name=name, count=len(items))))
        layout.addWidget(QLabel(tr("dialog.playlist_subfolder", name=name)))

        self.list_widget = QListWidget()
        for title, _ref in items:
            item = QListWidgetItem(title)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self.list_widget.addItem(item)
        layout.addWidget(self.list_widget)

        select_row = QHBoxLayout()
        all_btn = QPushButton(tr("button.select_all"))
        all_btn.setObjectName("secondary")
        all_btn.clicked.connect(lambda: self._set_all(Qt.Checked))
        none_btn = QPushButton(tr("button.select_none"))
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
    def __init__(
        self, yandex_token: str, dest: str, language: str, log_max_mb: int, log_backup_count: int, parent=None
    ):
        super().__init__(parent)
        self.setWindowTitle(tr("dialog.settings_title"))
        self.resize(460, 300)

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(tr("settings.dest_label")))
        dest_row = QHBoxLayout()
        self.dest_edit = QLineEdit(dest)
        browse_btn = QPushButton(tr("button.browse_folder"))
        browse_btn.setObjectName("secondary")
        browse_btn.clicked.connect(self._pick_dest)
        dest_row.addWidget(self.dest_edit, 1)
        dest_row.addWidget(browse_btn)
        layout.addLayout(dest_row)

        layout.addWidget(QLabel(tr("settings.language_label")))
        self.language_combo = QComboBox()
        for code, label in LANGUAGES.items():
            self.language_combo.addItem(label, code)
        self.language_combo.setCurrentIndex(self.language_combo.findData(language))
        layout.addWidget(self.language_combo)

        layout.addWidget(QLabel(tr("settings.yandex_token_label")))
        self.token_edit = QLineEdit(yandex_token)
        self.token_edit.setPlaceholderText(tr("settings.yandex_token_placeholder"))
        layout.addWidget(self.token_edit)

        layout.addWidget(QLabel(tr("settings.log_rotation_label")))
        log_row = QHBoxLayout()
        self.log_max_mb_spin = QSpinBox()
        self.log_max_mb_spin.setRange(1, 500)
        self.log_max_mb_spin.setSuffix(" MB")
        self.log_max_mb_spin.setValue(log_max_mb)
        self.log_backup_count_spin = QSpinBox()
        self.log_backup_count_spin.setRange(0, 50)
        self.log_backup_count_spin.setValue(log_backup_count)
        log_row.addWidget(self.log_max_mb_spin)
        log_row.addWidget(self.log_backup_count_spin)
        open_log_btn = QPushButton(tr("button.open_log_file"))
        open_log_btn.setObjectName("secondary")
        open_log_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(LOG_FILE))))
        log_row.addWidget(open_log_btn)
        layout.addLayout(log_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _pick_dest(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, tr("dialog.pick_dest_folder_title"), self.dest_edit.text())
        if folder:
            self.dest_edit.setText(folder)

    def token(self) -> str:
        return self.token_edit.text().strip()

    def dest(self) -> str:
        return self.dest_edit.text().strip() or DEFAULT_DEST

    def language(self) -> str:
        return self.language_combo.currentData()

    def log_max_mb(self) -> int:
        return self.log_max_mb_spin.value()

    def log_backup_count(self) -> int:
        return self.log_backup_count_spin.value()


class HistoryCard(QWidget):
    """One history entry, as a real self-sizing widget (not a QTreeWidgetItem --
    those don't resize correctly to wrapped multi-line content, which used to clip
    text and overlap the action buttons with the row underneath)."""

    def __init__(self, entry: dict, idx: int, theme_tokens: dict, load_into_player_cb, convert_requested_cb=None, parent=None):
        super().__init__(parent)
        self.entry = entry
        self.idx = idx
        self.theme_tokens = theme_tokens
        self.load_into_player_cb = load_into_player_cb
        self.convert_requested_cb = convert_requested_cb or (lambda *a: None)
        self.setObjectName("card")
        self.extra_box: QTextEdit | None = None
        self._populated = False
        t = theme_tokens

        kind_word = tr("kind.video") if entry.get("kind") == "video" else tr("kind.audio")
        disk_status = entry_disk_status(entry)
        self.on_disk = disk_status == "on_disk"
        missing = disk_status == "missing"
        if self.on_disk:
            status_icon, status_color = "check", t["success"]
        elif missing:
            status_icon, status_color = "trash", t["text_dim"]
        else:
            status_icon, status_color = "alert", t["danger"]

        self.outer = QVBoxLayout(self)
        self.outer.setContentsMargins(12, 10, 12, 10)
        self.outer.setSpacing(8)

        # A plain QWidget container (not just a layout) so clicking anywhere on the
        # row -- not just the chevron button -- toggles it too. QCheckBox/QPushButton
        # consume their own mouse presses, so this only fires for clicks that land on
        # the title/status/empty space, never stealing the checkbox or chevron click.
        header_widget = QWidget()
        header_widget.setCursor(Qt.PointingHandCursor)
        header_widget.mousePressEvent = lambda event: self._toggle()
        header = QHBoxLayout(header_widget)
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(16)
        self.checkbox = QCheckBox()
        header.addWidget(self.checkbox)
        status_label = QLabel()
        status_label.setPixmap(icon(status_icon, status_color).pixmap(18, 18))
        status_label.setContentsMargins(0, 0, 0, 0)
        header.addWidget(status_label)
        title_label = QLabel(f"{entry['title']}  —  {kind_word}  —  {entry['ts']}")
        title_label.setWordWrap(True)
        if missing:
            title_label.setStyleSheet(f"color: {t['text_dim']};")
        header.addWidget(title_label, 1)
        self.toggle_btn = QPushButton()
        self.toggle_btn.setObjectName("iconBtn")
        self.toggle_btn.setIcon(icon("chevron-right", t["icon"]))
        self.toggle_btn.clicked.connect(self._toggle)
        header.addWidget(self.toggle_btn)
        self.outer.addWidget(header_widget)

        # The expanded detail (cover art, duration, description/lyrics, action
        # buttons) is built lazily on first expand, not here: read_media_info()
        # does real file I/O (mutagen) per entry, and doing that for every card
        # up front made the whole window take seconds to appear with a sizeable
        # history -- noticeable, blocking, and for cards the user may never open.
        self.detail_widget: QWidget | None = None
        self.actions_widget: QWidget | None = None

    def _toggle(self) -> None:
        if not self._populated:
            self._populate()
            self._populated = True
        expanded = not self.detail_widget.isVisible()
        self.detail_widget.setVisible(expanded)
        self.actions_widget.setVisible(expanded)
        if self.extra_box:
            self.extra_box.setVisible(expanded)

    def _populate(self) -> None:
        entry, t = self.entry, self.theme_tokens
        missing = entry.get("status") == "ok" and not self.on_disk
        media = read_media_info(entry["path"]) if self.on_disk else {}

        self.detail_widget = QWidget()
        detail_layout = QHBoxLayout(self.detail_widget)
        detail_layout.setContentsMargins(0, 4, 0, 4)
        detail_layout.setSpacing(10)
        cover = media.get("cover")
        if cover:
            pix = QPixmap()
            pix.loadFromData(cover)
            cover_label = QLabel()
            cover_label.setPixmap(pix.scaled(56, 56, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
            cover_label.setFixedSize(56, 56)
            detail_layout.addWidget(cover_label)

        detail_lines = [
            tr("card.downloaded", v=entry["ts"]),
            f"URL: {entry['url']}",
            tr("card.format", v=entry.get("container", "?")),
            tr("card.source", v=entry.get("site", "?")),
        ]
        if entry.get("status") == "ok":
            if "duration" in media:
                detail_lines.append(tr("card.duration", v=format_duration(media["duration"])))
            detail_lines.append(tr("card.file", v=entry.get("path", "?")))
            if entry.get("subtitle_files"):
                detail_lines.append(tr("card.subtitles", n=len(entry["subtitle_files"])))
            if entry.get("chapters"):
                detail_lines.append(tr("card.chapters_count", n=len(entry["chapters"])))
            if missing:
                detail_lines.append(tr("card.missing_from_disk"))
        else:
            detail_lines.append(tr("card.error", v=entry.get("error", "?")))
        text_label = QLabel("\n".join(detail_lines))
        text_label.setObjectName("dim")
        text_label.setWordWrap(True)
        text_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        detail_layout.addWidget(text_label, 1)
        self.outer.addWidget(self.detail_widget)

        extra_parts = [entry.get("description") or entry.get("lyrics"), format_chapters(entry.get("chapters"))]
        extra_text = "\n\n".join(p for p in extra_parts if p) or None
        if extra_text:
            self.extra_box = QTextEdit()
            self.extra_box.setReadOnly(True)
            self.extra_box.setMaximumHeight(100)
            self.extra_box.setPlainText(extra_text)
            self.outer.addWidget(self.extra_box)

        self.actions_widget = QWidget()
        actions_layout = QHBoxLayout(self.actions_widget)
        actions_layout.setContentsMargins(0, 4, 0, 0)
        actions_layout.setSpacing(8)
        if self.on_disk:
            play_btn = QPushButton(tr("button.open_in_player"))
            play_btn.setObjectName("secondary")
            play_btn.setIcon(icon("play", t["icon"]))
            path, kind, title = entry["path"], entry["kind"], entry["title"]
            play_btn.clicked.connect(lambda _=None: self.load_into_player_cb(path, kind, title))
            actions_layout.addWidget(play_btn)

            finder_btn = QPushButton(tr("button.show_in_finder"))
            finder_btn.setObjectName("secondary")
            finder_btn.setIcon(icon("folder", t["icon"]))
            finder_btn.clicked.connect(lambda _=None, p=path: reveal_in_finder(p))
            actions_layout.addWidget(finder_btn)

            convert_btn = QPushButton(tr("button.convert"))
            convert_btn.setObjectName("secondary")
            convert_btn.setIcon(icon("film" if kind == "video" else "music", t["icon"]))
            convert_btn.clicked.connect(lambda _=None: self.convert_requested_cb(path, kind))
            actions_layout.addWidget(convert_btn)
        link_btn = QPushButton(tr("button.open_link"))
        link_btn.setIcon(icon("globe", t["icon"]))
        link_btn.setObjectName("secondary")
        entry_url = entry["url"]
        link_btn.clicked.connect(lambda _=None, u=entry_url: QDesktopServices.openUrl(QUrl(u)))
        actions_layout.addWidget(link_btn)
        actions_layout.addStretch()
        self.outer.addWidget(self.actions_widget)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("media-grabber")
        self.resize(820, 700)
        self.state = load_state()
        self.worker: DownloadWorker | None = None
        self.theme = self.state.get("theme", "system")
        self._effective_theme = "dark"
        QApplication.instance().styleHints().colorSchemeChanged.connect(self._on_system_theme_changed)
        set_language(self.state.get("language", "en"))

        # The whole window content sits inside a scroll area, not directly on
        # centralWidget: with the video player open, everything above it plus
        # the history list could need more height than the window has, with
        # nothing to shrink and no way to reach whatever got pushed out --
        # collapsing the video (added separately below) helps the common case,
        # but this is the actual floor: there's always a way to scroll down to
        # any control, regardless of window size or what else is open.
        outer_scroll = QScrollArea()
        outer_scroll.setWidgetResizable(True)
        outer_scroll.setFrameShape(QScrollArea.NoFrame)
        self.setCentralWidget(outer_scroll)
        root = QWidget()
        outer_scroll.setWidget(root)
        layout = QVBoxLayout(root)
        layout.setSpacing(12)
        layout.setContentsMargins(18, 16, 18, 16)

        # Header: title + theme switch + settings
        header = QHBoxLayout()
        title_label = QLabel("media-grabber")
        title_label.setObjectName("heading")
        header.addWidget(title_label)
        header.addStretch()
        # Icon-only, cycling through light -> dark -> system on each click --
        # tried a QComboBox with blank-text icon items first, but its built-in
        # padding + dropdown-arrow space clipped the icon badly at any
        # reasonable width (confirmed via a real screenshot). A plain button
        # matches every other icon-only control here (settings, video/history
        # collapse) and needs no special-casing.
        self.theme_btn = QPushButton()
        self.theme_btn.setObjectName("iconBtn")
        self.theme_btn.clicked.connect(self._on_theme_changed)
        header.addWidget(self.theme_btn)
        self.settings_btn = QPushButton()
        self.settings_btn.setObjectName("iconBtn")
        self.settings_btn.clicked.connect(self._open_settings)
        header.addWidget(self.settings_btn)
        layout.addLayout(header)

        # URL + format row
        row1 = QHBoxLayout()
        self.url_edit = QLineEdit()
        self.format_combo = QComboBox()
        for key in FORMATS:
            self.format_combo.addItem(tr(f"format.{key}"), key)
        self.format_combo.currentIndexChanged.connect(lambda _i: self._on_format_changed())
        self.url_edit.textChanged.connect(self._on_url_changed)
        self.quality_combo = QComboBox()
        for key in QUALITIES:
            self.quality_combo.addItem(tr(f"quality.{key}") if key == "best" else key, key)
        self.open_browser_btn = QPushButton()
        self.open_browser_btn.setObjectName("iconBtn")
        self.open_browser_btn.clicked.connect(self._open_current_url)
        row1.addWidget(self.url_edit, 3)
        row1.addWidget(self.format_combo, 1)
        row1.addWidget(self.quality_combo, 1)
        row1.addWidget(self.open_browser_btn)
        layout.addLayout(row1)

        # Live preview card: title/duration/cover, fetched shortly after the URL
        # settles -- lets you see *what* you're about to download before committing.
        self.preview_card = QWidget()
        self.preview_card.setObjectName("card")
        preview_layout = QHBoxLayout(self.preview_card)
        self.preview_cover = QLabel()
        self.preview_cover.setFixedSize(48, 48)
        preview_layout.addWidget(self.preview_cover)
        preview_text_box = QVBoxLayout()
        self.preview_title = QLabel()
        self.preview_title.setObjectName("heading")
        self.preview_title.setWordWrap(True)
        self.preview_duration = QLabel()
        self.preview_duration.setObjectName("dim")
        preview_text_box.addWidget(self.preview_title)
        preview_text_box.addWidget(self.preview_duration)
        preview_layout.addLayout(preview_text_box, 1)
        self.preview_card.hide()
        layout.addWidget(self.preview_card)

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self._start_preview)
        self._preview_worker: PreviewWorker | None = None
        self._preview_generation = 0

        # Download button + progress
        self.download_btn = QPushButton()
        self.download_btn.clicked.connect(self._start_download)
        layout.addWidget(self.download_btn)

        # Hidden until a download is actually running, and hidden again once
        # it finishes -- it used to sit there showing a stale 0%/100% even
        # when nothing was happening.
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.hide()
        layout.addWidget(self.progress)

        self.status_label = QLabel()
        self._status_is_pristine = True
        layout.addWidget(self.status_label)

        # Preview player -- the whole section (not just the video frame) stays
        # hidden until something is actually loaded into it: neither an old
        # song/video nor a fresh download, so there's nothing to show yet.
        self.player_section = QWidget()
        player_layout = QVBoxLayout(self.player_section)
        player_layout.setContentsMargins(0, 0, 0, 0)
        self._player_loaded = False

        self.video_widget = QVideoWidget()
        self.video_widget.setObjectName("card")
        self.video_widget.setMinimumHeight(260)
        self.video_widget.hide()
        player_layout.addWidget(self.video_widget)

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
        # The video frame (260px min height) plus everything else above it can
        # exceed the window's height with nothing to shrink -- history_scroll's
        # stretch area had no floor, so it could get squeezed to nothing with no
        # way to reach it. Letting video collapse back to just its controls
        # fixes the common case directly; history_scroll's own minimum height
        # (set below) is the floor for whatever's still too tall after that.
        self._video_collapsed = False
        self.video_collapse_btn = QPushButton()
        self.video_collapse_btn.setObjectName("iconBtn")
        self.video_collapse_btn.clicked.connect(self._toggle_video_collapsed)
        self.video_collapse_btn.hide()
        self.now_playing_label = QLabel()
        self.now_playing_label.setObjectName("dim")
        controls.addWidget(self.play_btn)
        controls.addWidget(self.seek_slider, 3)
        controls.addWidget(self.video_collapse_btn)
        player_layout.addLayout(controls)
        player_layout.addWidget(self.now_playing_label)

        # Description / lyrics for whatever's currently loaded in the player
        info_header = QHBoxLayout()
        self.info_toggle_btn = QPushButton()
        self.info_toggle_btn.setObjectName("secondary")
        self.info_toggle_btn.clicked.connect(self._toggle_info_panel)
        self.info_toggle_btn.hide()
        info_header.addWidget(self.info_toggle_btn)
        self.info_save_btn = QPushButton()
        self.info_save_btn.setObjectName("secondary")
        self.info_save_btn.setIcon(icon("download", TOKENS[self._effective_theme]["icon"]))
        self.info_save_btn.clicked.connect(self._save_info_panel)
        self.info_save_btn.hide()
        info_header.addWidget(self.info_save_btn)
        info_header.addStretch()
        player_layout.addLayout(info_header)

        self.info_panel = QTextEdit()
        self.info_panel.setReadOnly(True)
        self.info_panel.setObjectName("card")
        self.info_panel.setMaximumHeight(140)
        self.info_panel.hide()
        player_layout.addWidget(self.info_panel)
        self._current_media_text = ""

        self.player_section.hide()
        layout.addWidget(self.player_section)

        self.player.positionChanged.connect(self._on_position)
        self.player.durationChanged.connect(lambda d: self.seek_slider.setRange(0, d))
        self.player.playbackStateChanged.connect(self._on_playback_state)

        # History -- collapsed by default (the search/filters/list below live
        # in history_body, a separate widget toggled by this chevron), so the
        # window opens short instead of immediately showing a long list.
        history_header = QHBoxLayout()
        self._history_collapsed = True
        self.history_collapse_btn = QPushButton()
        self.history_collapse_btn.setObjectName("iconBtn")
        self.history_collapse_btn.clicked.connect(self._toggle_history_collapsed)
        history_header.addWidget(self.history_collapse_btn)
        self.history_title = QLabel()
        self.history_title.setObjectName("heading")
        history_header.addWidget(self.history_title)
        history_header.addStretch()
        # Select/clear act on whatever's currently rendered under the active
        # search/filters, not the whole history -- picking "missing" status
        # then "select all" is exactly the bulk-cleanup use case this is for.
        self.select_all_btn = QPushButton()
        self.select_all_btn.setObjectName("secondary")
        self.select_all_btn.clicked.connect(lambda: self._set_all_history_checked(True))
        history_header.addWidget(self.select_all_btn)
        self.select_none_btn = QPushButton()
        self.select_none_btn.setObjectName("secondary")
        self.select_none_btn.clicked.connect(lambda: self._set_all_history_checked(False))
        history_header.addWidget(self.select_none_btn)
        self.delete_history_btn = QPushButton()
        self.delete_history_btn.setObjectName("secondary")
        self.delete_history_btn.clicked.connect(self._delete_selected_history)
        history_header.addWidget(self.delete_history_btn)
        layout.addLayout(history_header)

        self.history_body = QWidget()
        history_body_layout = QVBoxLayout(self.history_body)
        history_body_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.history_body)

        self._history_filter = ""
        self.history_search = QLineEdit()
        self.history_search.textChanged.connect(self._on_history_search)
        history_body_layout.addWidget(self.history_search)

        filters_row = QHBoxLayout()
        self.filter_site = QComboBox()
        self.filter_site.currentIndexChanged.connect(self._on_history_filters_changed)
        self.filter_source_label = QLabel()
        filters_row.addWidget(self.filter_source_label)
        filters_row.addWidget(self.filter_site, 1)
        self.filter_format = QComboBox()
        self.filter_format.currentIndexChanged.connect(self._on_history_filters_changed)
        self.filter_format_label = QLabel()
        filters_row.addWidget(self.filter_format_label)
        filters_row.addWidget(self.filter_format, 1)
        self.filter_dir = QComboBox()
        self.filter_dir.currentIndexChanged.connect(self._on_history_filters_changed)
        self.filter_folder_label = QLabel()
        filters_row.addWidget(self.filter_folder_label)
        filters_row.addWidget(self.filter_dir, 1)
        history_body_layout.addLayout(filters_row)

        filters_row2 = QHBoxLayout()
        self.filter_kind = QComboBox()
        self.filter_kind.currentIndexChanged.connect(self._on_history_filters_changed)
        self.filter_kind_label = QLabel()
        filters_row2.addWidget(self.filter_kind_label)
        filters_row2.addWidget(self.filter_kind, 1)
        self.filter_status = QComboBox()
        self.filter_status.currentIndexChanged.connect(self._on_history_filters_changed)
        self.filter_status_label = QLabel()
        filters_row2.addWidget(self.filter_status_label)
        filters_row2.addWidget(self.filter_status, 1)
        history_body_layout.addLayout(filters_row2)

        # A scroll area of card widgets, not a QTreeWidget: word-wrapped multi-line
        # content inside QTreeWidgetItem rows doesn't get sized correctly by Qt once
        # the real column width is known, which clipped text and overlapped the action
        # buttons with the row below. Plain widgets in a QVBoxLayout size themselves
        # properly instead.
        self.history_scroll = QScrollArea()
        self.history_scroll.setWidgetResizable(True)
        self.history_scroll.setFrameShape(QScrollArea.NoFrame)
        # Bounded height so it keeps its own internal scrollbar (and a floor so
        # it's never squeezed to nothing) instead of expanding to fit every
        # card -- now that it's inside the outer scroll area above, nothing
        # would otherwise stop it from growing to the full height of the
        # history list.
        self.history_scroll.setMinimumHeight(180)
        self.history_scroll.setMaximumHeight(420)
        self.history_container = QWidget()
        self.history_container_layout = QVBoxLayout(self.history_container)
        self.history_container_layout.setSpacing(8)
        self.history_container_layout.addStretch(1)
        self.history_scroll.setWidget(self.history_container)
        history_body_layout.addWidget(self.history_scroll, 2)
        self._history_cards: list[HistoryCard] = []
        self._render_history()
        self.history_body.hide()

        # Absorbs whatever vertical space the visible widgets above don't need --
        # without it, a QVBoxLayout with no stretch distributes leftover space
        # (there's plenty once history/player default to hidden, or the outer
        # scroll area stretches root to fill a tall viewport) among whichever
        # widgets *can* grow, which blew the live-preview card's title label up
        # to 150+ px tall instead of one normal line. Reproduced in isolation
        # with a minimal QVBoxLayout containing only that one card and no
        # trailing stretch -- confirmed fixed by adding exactly this.
        layout.addStretch(1)

        # Overlay shown during a download, blocking input controls
        self.overlay = QWidget(root)
        overlay_layout = QVBoxLayout(self.overlay)
        self.overlay_label = QLabel()
        self.overlay_label.setAlignment(Qt.AlignCenter)
        self.overlay_label.setStyleSheet("font-size: 18px; font-weight: 700; background: transparent;")
        overlay_layout.addStretch()
        overlay_layout.addWidget(self.overlay_label)
        overlay_layout.addStretch()
        self.overlay.hide()

        self._apply_theme()
        self._retranslate_ui()

        self._inputs = [
            self.url_edit,
            self.format_combo,
            self.quality_combo,
            self.settings_btn,
            self.download_btn,
            self.delete_history_btn,
        ]
        self._on_format_changed()
        self._queue: list[tuple[str, str]] = []  # (title, ref_url) still to download
        self._queue_kind = ""
        self._queue_container = ""
        self._queue_max_height: int | None = None
        self._queue_total = 0

    def _on_format_changed(self) -> None:
        kind, _ = FORMATS[self.format_combo.currentData()]
        self.quality_combo.setEnabled(kind == "video")

    def _on_url_changed(self, text: str) -> None:
        # Spotify/Yandex Music are audio-only: there's no video to offer, so grey that
        # choice out instead of letting the user pick it and hit an error on download.
        audio_only = is_spotify(text) or is_yandex_music(text)
        model = self.format_combo.model()
        for i in range(self.format_combo.count()):
            kind, _ = FORMATS[self.format_combo.itemData(i)]
            model.item(i).setEnabled(not (audio_only and kind == "video"))
        if audio_only and FORMATS[self.format_combo.currentData()][0] == "video":
            audio_key = next(k for k, (kind, _) in FORMATS.items() if kind == "audio")
            self.format_combo.setCurrentIndex(self.format_combo.findData(audio_key))

        # Debounced live preview: wait for typing/pasting to settle before fetching.
        self._preview_generation += 1
        self.preview_card.hide()
        self._preview_timer.stop()
        if "http" in text:
            self._preview_timer.start(700)

        # Editing the URL invalidates whatever's in the player -- it belongs to
        # a different link (or none) now. It comes back once this download
        # finishes or a history entry is loaded, both through _load_into_player().
        if self._player_loaded:
            self.player_section.hide()

    def _start_preview(self) -> None:
        url = self.url_edit.text().strip()
        if "http" not in url:
            return
        generation = self._preview_generation
        self._preview_worker = PreviewWorker(url, self.state.get("yandex_token", ""))
        self._preview_worker.ready.connect(lambda info: self._on_preview_ready(info, generation))
        self._preview_worker.failed.connect(lambda _msg, g=generation: None)  # stale/failed: just stay hidden
        self._preview_worker.start()

    def _on_preview_ready(self, info: dict, generation: int) -> None:
        if generation != self._preview_generation:
            return  # URL changed again while this was in flight
        self.preview_title.setText(info.get("title") or "?")
        self.preview_duration.setText(format_duration(info.get("duration")))
        cover = info.get("cover")
        if cover:
            pix = QPixmap()
            pix.loadFromData(cover)
            self.preview_cover.setPixmap(
                pix.scaled(48, 48, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            )
        else:
            self.preview_cover.clear()
        self.preview_card.show()

    def _open_settings(self) -> None:
        dest = self.state.get("last_dest", DEFAULT_DEST)
        language = self.state.get("language", get_language())
        log_max_mb = self.state.get("log_max_mb", DEFAULT_LOG_MAX_MB)
        log_backup_count = self.state.get("log_backup_count", DEFAULT_LOG_BACKUP_COUNT)
        dlg = SettingsDialog(self.state.get("yandex_token", ""), dest, language, log_max_mb, log_backup_count, self)
        if dlg.exec() == QDialog.Accepted:
            self.state["yandex_token"] = dlg.token()
            self.state["last_dest"] = dlg.dest()
            language_changed = dlg.language() != language
            self.state["language"] = dlg.language()
            self.state["log_max_mb"] = dlg.log_max_mb()
            self.state["log_backup_count"] = dlg.log_backup_count()
            save_state(self.state)
            apply_log_rotation_settings(dlg.log_max_mb(), dlg.log_backup_count())
            log.info("settings.saved", dest=dlg.dest(), language=dlg.language(),
                      log_max_mb=dlg.log_max_mb(), log_backup_count=dlg.log_backup_count(),
                      yandex_token_set=bool(dlg.token()))
            if language_changed:
                set_language(dlg.language())
                self._retranslate_ui()

    def _open_current_url(self) -> None:
        url = self.url_edit.text().strip()
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def _resolve_effective_theme(self) -> str:
        if self.theme != "system":
            return self.theme
        scheme = QApplication.instance().styleHints().colorScheme()
        return "light" if scheme == Qt.ColorScheme.Light else "dark"

    def _on_theme_changed(self) -> None:
        self.theme = THEME_OPTIONS[(THEME_OPTIONS.index(self.theme) + 1) % len(THEME_OPTIONS)]
        self.state["theme"] = self.theme
        save_state(self.state)
        log.info("ui.theme_changed", theme=self.theme)
        self.theme_btn.setToolTip(tr(f"theme.{self.theme}"))
        self._apply_theme()
        self._render_history()

    def _on_system_theme_changed(self, _scheme) -> None:
        # Only matters while following the OS -- an explicit light/dark pick
        # is never overridden by the OS changing underneath it.
        if self.theme == "system":
            self._apply_theme()
            self._render_history()

    def _apply_theme(self) -> None:
        self._effective_theme = self._resolve_effective_theme()
        t = TOKENS[self._effective_theme]
        QApplication.instance().setStyleSheet(stylesheet(self._effective_theme))
        self.open_browser_btn.setIcon(icon("globe", t["icon"]))
        self.play_btn.setIcon(icon("pause" if self._is_playing() else "play", t["icon"]))
        self.video_collapse_btn.setIcon(icon("chevron-right" if self._video_collapsed else "chevron-down", t["icon"]))
        self.history_collapse_btn.setIcon(
            icon("chevron-right" if self._history_collapsed else "chevron-down", t["icon"])
        )
        self.settings_btn.setIcon(icon("settings", t["icon"]))
        self.delete_history_btn.setIcon(icon("trash", t["icon"]))
        self.select_all_btn.setIcon(icon("check", t["icon"]))
        self.select_none_btn.setIcon(icon("x", t["icon"]))
        self.download_btn.setIcon(icon("download", t["accent_text"]))
        self.theme_btn.setIcon(icon(THEME_ICONS[self.theme], t["icon"]))
        self.overlay.setStyleSheet(
            f"background-color: {('rgba(10, 10, 15, 200)' if self._effective_theme == 'dark' else 'rgba(255, 255, 255, 215)')};"
        )

    def _retranslate_ui(self) -> None:
        self.theme_btn.setToolTip(tr(f"theme.{self.theme}"))
        self.url_edit.setPlaceholderText(tr("url.placeholder"))
        self.open_browser_btn.setToolTip(tr("tooltip.open_in_browser"))
        self.settings_btn.setToolTip(tr("button.settings"))
        self.download_btn.setText(tr("button.download"))
        if self._status_is_pristine:
            self.status_label.setText(tr("status.ready"))
        self.video_collapse_btn.setToolTip(tr("tooltip.collapse_video"))
        self.history_collapse_btn.setToolTip(tr("tooltip.collapse_history"))
        self.info_toggle_btn.setText(tr("button.description_lyrics"))
        self.info_save_btn.setText(tr("button.save_as"))
        self.history_title.setText(tr("heading.history"))
        self.delete_history_btn.setText(tr("button.delete_selected"))
        self.select_all_btn.setText(tr("button.select_all_filtered"))
        self.select_none_btn.setText(tr("button.select_none_filtered"))
        self.history_search.setPlaceholderText(tr("search.history_placeholder"))
        self.filter_source_label.setText(tr("filter.source_label"))
        self.filter_format_label.setText(tr("filter.format_label"))
        self.filter_folder_label.setText(tr("filter.folder_label"))
        self.filter_kind_label.setText(tr("filter.kind_label"))
        self.filter_status_label.setText(tr("filter.status_label"))
        for key in FORMATS:
            self.format_combo.setItemText(self.format_combo.findData(key), tr(f"format.{key}"))
        best_idx = self.quality_combo.findData("best")
        self.quality_combo.setItemText(best_idx, tr("quality.best"))
        if self._player_loaded:
            self._update_now_playing_label()
        self._render_history()  # re-render cards and re-translate the "Все"/"All" filter items

    def _is_playing(self) -> bool:
        return self.player.playbackState() == QMediaPlayer.PlayingState

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.overlay.setGeometry(self.centralWidget().rect())

    def closeEvent(self, event) -> None:
        # Closing while a worker QThread is still running (mid-download, mid-resolve)
        # would otherwise destroy a running thread -- Qt logs "QThread: Destroyed
        # while thread is still running" and can crash, plus it can leave a
        # half-written file on disk. There's no cooperative cancel (yt-dlp/spotdl's
        # download call is a blocking call inside run()), so ask before terminating.
        running = [w for w in (self.worker, getattr(self, "_resolver", None)) if w and w.isRunning()]
        if running:
            box = QMessageBox(self)
            box.setWindowTitle("media-grabber")
            box.setText(tr("dialog.close_confirm"))
            box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            box.setDefaultButton(QMessageBox.No)
            if box.exec() != QMessageBox.Yes:
                event.ignore()
                return
            for w in running:
                w.terminate()
                w.wait(2000)
        event.accept()

    def _set_busy(self, busy: bool, text: str | None = None, indeterminate: bool = False) -> None:
        for w in self._inputs:
            w.setEnabled(not busy)
        self.progress.setVisible(busy)
        # range(0, 0) makes a QProgressBar run its built-in animated "busy"
        # pulse instead of showing a flat bar -- used for ffmpeg conversion,
        # which doesn't report a percentage (vs. downloads, which do).
        self.progress.setRange(0, 0 if (busy and indeterminate) else 100)
        if busy:
            self.overlay_label.setText(text or tr("progress.downloading"))
            self.overlay.setGeometry(self.centralWidget().rect())
            self.overlay.show()
            self.overlay.raise_()
        else:
            self.overlay.hide()

    # -- UI actions ---------------------------------------------------
    def _start_download(self) -> None:
        url = self.url_edit.text().strip()
        if not url:
            QMessageBox.warning(self, "media-grabber", tr("warning.need_url"))
            return
        kind, container = FORMATS[self.format_combo.currentData()]
        max_height = QUALITIES[self.quality_combo.currentData()]
        dest = self.state.get("last_dest", DEFAULT_DEST)

        log.info("ui.download_clicked", url=url, kind=kind, container=container, dest=dest, max_height=max_height)
        self._set_busy(True, tr("status.checking_link"))

        self._resolver = ResolveWorker(url, self.state.get("yandex_token", ""))
        self._resolver.resolved.connect(
            lambda name, items: self._on_resolved(name, items, url, kind, container, dest, max_height)
        )
        self._resolver.failed.connect(self._on_resolve_failed)
        self._resolver.start()

    def _on_resolve_failed(self, message: str) -> None:
        self._set_busy(False)
        self._set_status(tr("status.error_prefix", msg=message), "err")

    def _on_resolved(
        self, name: str, items: list, url: str, kind: str, container: str, dest: str, max_height: int | None
    ) -> None:
        if not items:
            self._begin_single(url, kind, container, dest, max_height)
            return

        self._set_busy(False)
        dlg = PlaylistDialog(name, items, self)
        if dlg.exec() != QDialog.Accepted:
            self._set_status(tr("status.cancelled"), "err")
            return
        chosen = dlg.selected_items()
        if not chosen:
            self._set_status(tr("status.nothing_selected"), "err")
            return
        subfolder = re.sub(r'[\\/:*?"<>|]', "_", name).strip() or "Playlist"
        self._start_batch(chosen, kind, container, str(Path(dest) / subfolder), max_height)

    def _begin_single(self, url: str, kind: str, container: str, dest: str, max_height: int | None) -> None:
        self._queue_total = 0
        self.progress.setValue(0)
        self._set_status(tr("status.starting"), "busy")
        self._set_busy(True, tr("progress.downloading"))

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
        self._set_busy(True, tr("status.playlist_progress", done=0, total=self._queue_total))
        self._download_next_in_queue()

    def _download_next_in_queue(self) -> None:
        if not self._queue:
            self._set_busy(False)
            self._set_status(tr("status.playlist_done", done=self._queue_done, total=self._queue_total), "ok")
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

    @staticmethod
    def _ok_history_entry(result: dict, url: str, container: str) -> dict:
        entry = {
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "url": url,
            "title": result["title"],
            "kind": result["kind"],
            "container": container,
            "site": result["site"],
            "status": "ok",
            "path": result["path"],
        }
        for key in ("description", "lyrics", "subtitle_files", "chapters"):
            if result.get(key):
                entry[key] = result[key]
        return entry

    def _on_queue_item_finished(self, result: dict, url: str, title: str) -> None:
        self._queue_done += 1
        self._add_history(self._ok_history_entry(result, url, self._queue_container))
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
        self._set_status(tr("status.done_title", title=result["title"]), "ok")
        self._set_busy(False)
        self._add_history(self._ok_history_entry(result, url, container))
        self._load_into_player(result["path"], result["kind"], result["title"])

    def _on_failed(self, message: str, url: str, kind: str, container: str) -> None:
        self.progress.setValue(0)
        self._set_status(tr("status.error_prefix", msg=message), "err")
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
        self._status_is_pristine = False
        self.status_label.setText(text)
        self.status_label.setObjectName(f"status_{kind}")
        self.status_label.setStyleSheet("")  # force re-polish of the objectName style

    # -- preview player -------------------------------------------------
    def _load_into_player(self, path: str, kind: str, title: str) -> None:
        self.url_edit.clear()  # also hides player_section via _on_url_changed; shown again right below
        self.player.pause()
        self._player_loaded = True
        self.player_section.show()
        self._current_player_kind = kind
        self._current_player_title = title
        self._video_collapsed = False
        self.video_collapse_btn.setVisible(kind == "video")
        self.video_collapse_btn.setIcon(icon("chevron-down", TOKENS[self._effective_theme]["icon"]))
        self.video_widget.setVisible(kind == "video")
        self.player.setSource(QUrl.fromLocalFile(path))
        self._update_now_playing_label()

        entry = next((e for e in self.state.get("history", []) if e.get("path") == path), None)
        text = (entry.get("description") or entry.get("lyrics")) if entry else None
        self._current_media_text = text or ""
        self.info_toggle_btn.setVisible(bool(text))
        self.info_save_btn.setVisible(bool(text))
        self.info_panel.setPlainText(self._current_media_text)
        self.info_panel.hide()

    def _update_now_playing_label(self) -> None:
        icon_char = "🎬" if self._current_player_kind == "video" else "🎵"
        self.now_playing_label.setText(
            tr("player.ready_to_play", icon=icon_char, title=self._current_player_title)
        )

    def _toggle_info_panel(self) -> None:
        self.info_panel.setVisible(not self.info_panel.isVisible())

    def _save_info_panel(self) -> None:
        if not self._current_media_text:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, tr("dialog.save_as_title"), "description.txt", tr("dialog.save_as_filter")
        )
        if path:
            Path(path).write_text(self._current_media_text, encoding="utf-8")

    def _toggle_play(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _on_playback_state(self, state: QMediaPlayer.PlaybackState) -> None:
        name = "pause" if state == QMediaPlayer.PlayingState else "play"
        self.play_btn.setIcon(icon(name, TOKENS[self._effective_theme]["icon"]))

    def _toggle_video_collapsed(self) -> None:
        # Playback (audio track, position, seek bar) keeps working collapsed --
        # this only hides the big video frame to free up vertical space.
        self._video_collapsed = not self._video_collapsed
        self.video_widget.setVisible(not self._video_collapsed)
        self.video_collapse_btn.setIcon(
            icon("chevron-right" if self._video_collapsed else "chevron-down", TOKENS[self._effective_theme]["icon"])
        )

    def _toggle_history_collapsed(self) -> None:
        self._history_collapsed = not self._history_collapsed
        self.history_body.setVisible(not self._history_collapsed)
        self.history_collapse_btn.setIcon(
            icon("chevron-right" if self._history_collapsed else "chevron-down", TOKENS[self._effective_theme]["icon"])
        )

    def _on_position(self, pos: int) -> None:
        if not self.seek_slider.isSliderDown():
            self.seek_slider.setValue(pos)

    # -- history ---------------------------------------------------------
    def _on_history_search(self, text: str) -> None:
        self._history_filter = text.strip()
        self._render_history()

    def _on_history_filters_changed(self) -> None:
        self._render_history()

    @staticmethod
    def _combo_set_options(combo: QComboBox, options: list[str], label=str) -> None:
        """Repopulate a filter combo with "All" + sorted values, keeping the current pick if
        still valid. `label` maps a raw value to its displayed text (translated, for options
        that aren't already human text -- e.g. "on_disk" -> "On disk" / "На диске")."""
        current = combo.currentData() if combo.count() else None
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(tr("filter.all"), "")
        for opt in sorted(options):
            combo.addItem(label(opt), opt)
        idx = combo.findData(current) if current else 0
        combo.setCurrentIndex(max(idx, 0))
        combo.blockSignals(False)

    def _add_history(self, entry: dict) -> None:
        self.state.setdefault("history", []).insert(0, entry)
        save_state(self.state)
        self._render_history()

    def _open_convert_dialog(self, path: str, kind: str) -> None:
        dlg = ConvertDialog(kind, self)
        if dlg.exec() != QDialog.Accepted:
            return
        container, audio_only = dlg.target()

        self._set_busy(True, tr("status.converting"), indeterminate=True)
        self._convert_worker = ConvertWorker(path, container, audio_only)
        self._convert_worker.finished_ok.connect(lambda r: self._on_convert_finished(r, path))
        self._convert_worker.failed.connect(self._on_convert_failed)
        self._convert_worker.start()

    def _on_convert_finished(self, result: dict, src_path: str) -> None:
        self._set_busy(False)
        title = f"{Path(result['path']).stem}"
        self._set_status(tr("status.convert_done", title=title), "ok")
        src_entry = next((e for e in self.state.get("history", []) if e.get("path") == src_path), None)
        self._add_history(
            {
                "ts": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "url": src_entry["url"] if src_entry else src_path,
                "title": title,
                "kind": result["kind"],
                "container": result["container"],
                "site": "converted",
                "status": "ok",
                "path": result["path"],
            }
        )

    def _on_convert_failed(self, message: str) -> None:
        self._set_busy(False)
        self._set_status(tr("status.convert_failed", msg=message), "err")

    def _render_history(self) -> None:
        t = TOKENS[self._effective_theme]
        for card in self._history_cards:
            card.setParent(None)
            card.deleteLater()
        self._history_cards = []

        history = self.state.get("history", [])
        self._combo_set_options(self.filter_site, {str(e.get("site", "?")) for e in history})
        self._combo_set_options(self.filter_format, {str(e.get("container", "?")) for e in history})
        self._combo_set_options(
            self.filter_dir, {str(Path(e["path"]).parent) for e in history if e.get("path")}
        )
        self._combo_set_options(
            self.filter_kind, {str(e.get("kind", "?")) for e in history},
            label=lambda k: tr("kind.video") if k == "video" else tr("kind.audio") if k == "audio" else k,
        )
        self._combo_set_options(
            self.filter_status, {entry_disk_status(e) for e in history}, label=lambda s: tr(f"disk_status.{s}")
        )

        query = self._history_filter.lower() if hasattr(self, "_history_filter") else ""
        site_filter = self.filter_site.currentData() or ""
        format_filter = self.filter_format.currentData() or ""
        dir_filter = self.filter_dir.currentData() or ""
        kind_filter = self.filter_kind.currentData() or ""
        status_filter = self.filter_status.currentData() or ""
        insert_at = self.history_container_layout.count() - 1  # keep the trailing stretch last
        for idx, entry in enumerate(history):
            haystack = " ".join(
                str(entry.get(k, "")) for k in ("title", "url", "site", "container", "kind")
            ).lower()
            if query and query not in haystack:
                continue
            if site_filter and str(entry.get("site", "?")) != site_filter:
                continue
            if format_filter and str(entry.get("container", "?")) != format_filter:
                continue
            if dir_filter and (not entry.get("path") or str(Path(entry["path"]).parent) != dir_filter):
                continue
            if kind_filter and str(entry.get("kind", "?")) != kind_filter:
                continue
            if status_filter and entry_disk_status(entry) != status_filter:
                continue
            card = HistoryCard(entry, idx, t, self._load_into_player, self._open_convert_dialog, self.history_container)
            self.history_container_layout.insertWidget(insert_at, card)
            insert_at += 1
            self._history_cards.append(card)

    def _set_all_history_checked(self, checked: bool) -> None:
        for card in self._history_cards:
            card.checkbox.setChecked(checked)

    def _delete_selected_history(self) -> None:
        selected = [c for c in self._history_cards if c.checkbox.isChecked()]
        if not selected:
            QMessageBox.information(self, "media-grabber", tr("msgbox.select_one_history"))
            return

        box = QMessageBox(self)
        box.setWindowTitle("media-grabber")
        box.setText(tr("dialog.delete_confirm", n=len(selected)))
        only_list_btn = box.addButton(tr("button.delete_list_only"), QMessageBox.AcceptRole)
        with_disk_btn = box.addButton(tr("button.delete_with_disk"), QMessageBox.DestructiveRole)
        box.addButton(tr("button.cancel"), QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked not in (only_list_btn, with_disk_btn):
            return

        history = self.state.get("history", [])
        indices = sorted({c.idx for c in selected}, reverse=True)
        delete_from_disk = clicked is with_disk_btn
        log.info("ui.history_delete", count=len(indices), delete_from_disk=delete_from_disk)
        for idx in indices:
            entry = history[idx]
            if delete_from_disk and entry.get("status") == "ok":
                try:
                    Path(entry["path"]).unlink(missing_ok=True)
                except OSError as e:
                    log.error("ui.history_delete_file_failed", path=entry["path"], error=str(e))
                    QMessageBox.warning(self, "media-grabber", tr("msgbox.delete_failed", path=entry["path"], err=e))
            del history[idx]
        save_state(self.state)
        self._render_history()


def main() -> None:
    state = load_state()
    setup_logging(
        max_mb=state.get("log_max_mb", DEFAULT_LOG_MAX_MB),
        backup_count=state.get("log_backup_count", DEFAULT_LOG_BACKUP_COUNT),
    )
    log.info("app.start")
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
