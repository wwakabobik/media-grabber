"""Minimal i18n: a key -> {lang: text} dict and a tr() lookup. No gettext/.po
or Qt Linguist/.ts build step -- the string count here is small enough that a
plain dict is simpler to maintain than adding a translation toolchain.
"""
from __future__ import annotations

_current_lang = "en"

LANGUAGES = {"en": "English", "ru": "Русский"}

STRINGS: dict[str, dict[str, str]] = {
    "format.video_mp4": {"en": "Video (MP4)", "ru": "Видео (MP4)"},
    "format.video_webm": {"en": "Video (WebM)", "ru": "Видео (WebM)"},
    "format.audio_mp3": {"en": "Audio (MP3)", "ru": "Аудио (MP3)"},
    "quality.best": {"en": "Best", "ru": "Лучшее"},
    "theme.light": {"en": "Light", "ru": "Светлая"},
    "theme.dark": {"en": "Dark", "ru": "Тёмная"},
    "theme.system": {"en": "System", "ru": "Системная"},
    "chapters.header": {"en": "Chapters:", "ru": "Главы:"},
    "error.vimeo_login_wall": {
        "en": "Vimeo requires a login even for this video -- yt-dlp can't download it without a "
        "logged-in account's cookies (a Vimeo limitation, not this app's).",
        "ru": "Vimeo требует авторизации даже для этого видео — без куки залогиненного аккаунта "
        "yt-dlp скачать не может (ограничение самого Vimeo, не этого приложения).",
    },
    "error.spotify_no_video": {
        "en": "Spotify has no video -- pick “Audio (MP3)”.",
        "ru": "У Spotify нет видео — выбери «Аудио (MP3)».",
    },
    "error.yandex_no_video": {
        "en": "Yandex Music has no video -- pick “Audio (MP3)”.",
        "ru": "У Яндекс.Музыки нет видео — выбери «Аудио (MP3)».",
    },
    "progress.downloading": {"en": "Downloading…", "ru": "Скачивание…"},
    "progress.processing_file": {"en": "Processing file…", "ru": "Обработка файла…"},
    "progress.spotify_search": {"en": "Searching the track on Spotify…", "ru": "Поиск трека через Spotify…"},
    "error.spotify_not_found": {"en": "Spotify: track not found", "ru": "Spotify: трек не найден"},
    "progress.spotify_downloading": {"en": "Downloading via spotdl…", "ru": "Скачивание через spotdl…"},
    "error.spotdl_failed": {"en": "spotdl failed to download the track", "ru": "spotdl не смог скачать трек"},
    "error.yandex_token_needed": {
        "en": "Yandex Music needs a token -- add it in Settings.",
        "ru": "Нужен токен Яндекс.Музыки — добавь его в Настройках.",
    },
    "error.yandex_bad_url": {
        "en": "Doesn't look like a Yandex Music track link.",
        "ru": "Не похоже на ссылку на трек Яндекс.Музыки.",
    },
    "progress.yandex_fetching": {"en": "Fetching the track from Yandex Music…", "ru": "Получение трека с Яндекс.Музыки…"},
    "progress.yandex_downloading": {"en": "Downloading from Yandex Music…", "ru": "Скачивание с Яндекс.Музыки…"},
    "dialog.playlist_default_title": {"en": "Playlist / album", "ru": "Плейлист / альбом"},
    "dialog.playlist_found": {
        "en": "“{name}” -- found {count}. Pick what to download:",
        "ru": "«{name}» — найдено {count}. Выбери, что скачать:",
    },
    "dialog.playlist_subfolder": {
        "en": "Will be saved into a subfolder “{name}”.",
        "ru": "Сохранится в подпапку «{name}».",
    },
    "button.select_all": {"en": "Select all", "ru": "Выбрать всё"},
    "button.select_none": {"en": "Clear all", "ru": "Снять всё"},
    "dialog.settings_title": {"en": "Settings", "ru": "Настройки"},
    "settings.yandex_token_label": {
        "en": "Yandex Music token (needed for downloads from your own account -- without it, the "
        "API won't serve tracks anonymously):",
        "ru": "Токен Яндекс.Музыки (нужен для скачивания — своей учётки, без него API анонимно не "
        "отдаёт треки):",
    },
    "settings.yandex_token_placeholder": {
        "en": "Yandex Music account OAuth token",
        "ru": "OAuth-токен аккаунта Яндекс.Музыки",
    },
    "settings.dest_label": {"en": "Download folder:", "ru": "Папка для загрузок:"},
    "button.browse_folder": {"en": "Browse…", "ru": "Обзор…"},
    "settings.language_label": {"en": "Language:", "ru": "Язык:"},
    "settings.log_rotation_label": {
        "en": "Log file: max size per file, how many old files to keep, or open it:",
        "ru": "Лог-файл: макс. размер файла, сколько старых хранить, или открыть его:",
    },
    "button.open_log_file": {"en": "Open log file", "ru": "Открыть лог-файл"},
    "kind.video": {"en": "video", "ru": "видео"},
    "kind.audio": {"en": "audio", "ru": "аудио"},
    "card.downloaded": {"en": "Downloaded: {v}", "ru": "Скачано: {v}"},
    "card.format": {"en": "Format: {v}", "ru": "Формат: {v}"},
    "card.source": {"en": "Source: {v}", "ru": "Источник: {v}"},
    "card.duration": {"en": "Duration: {v}", "ru": "Длительность: {v}"},
    "card.file": {"en": "File: {v}", "ru": "Файл: {v}"},
    "card.subtitles": {"en": "Subtitles: {n} file(s) next to the video", "ru": "Субтитры: {n} файл(ов) рядом с видео"},
    "card.chapters_count": {"en": "Chapters: {n}", "ru": "Главы: {n}"},
    "card.missing_from_disk": {"en": "(file was deleted from disk)", "ru": "(файл удалён с диска)"},
    "card.error": {"en": "Error: {v}", "ru": "Ошибка: {v}"},
    "button.open_in_player": {"en": " Open in player", "ru": " Открыть в плеере"},
    "button.show_in_finder": {"en": " Show in Finder", "ru": " Показать в Finder"},
    "button.open_link": {"en": " Open link", "ru": " Открыть ссылку"},
    "button.convert": {"en": " Convert…", "ru": " Конвертировать…"},
    "tooltip.theme_toggle": {"en": "Light / dark theme", "ru": "Светлая / тёмная тема"},
    "url.placeholder": {
        "en": "Link to YouTube / Vimeo / SoundCloud / VK / Spotify / Yandex Music… (playlists/albums too)",
        "ru": "Ссылка на YouTube / Vimeo / SoundCloud / VK / Spotify / Яндекс.Музыку… (в т.ч. плейлист/альбом)",
    },
    "tooltip.open_in_browser": {"en": "Open the link in a browser", "ru": "Открыть ссылку в браузере"},
    "button.settings": {"en": "Settings", "ru": "Настройки"},
    "button.download": {"en": "Download", "ru": "Скачать"},
    "status.ready": {"en": "Ready", "ru": "Готов к работе"},
    "tooltip.collapse_video": {"en": "Collapse/expand video", "ru": "Свернуть/развернуть видео"},
    "button.description_lyrics": {"en": "Description / lyrics", "ru": "Описание / текст песни"},
    "button.save_as": {"en": " Save as…", "ru": " Сохранить как…"},
    "heading.history": {"en": "History", "ru": "История"},
    "button.delete_selected": {"en": "Delete selected", "ru": "Удалить выбранное"},
    "button.select_all_filtered": {"en": "Select all", "ru": "Выбрать всё"},
    "button.select_none_filtered": {"en": "Clear selection", "ru": "Снять выделение"},
    "search.history_placeholder": {
        "en": "Search history -- title, link, source…",
        "ru": "Поиск по истории — название, ссылка, источник…",
    },
    "filter.source_label": {"en": "Source:", "ru": "Источник:"},
    "filter.format_label": {"en": "Format:", "ru": "Формат:"},
    "filter.folder_label": {"en": "Folder:", "ru": "Папка:"},
    "filter.kind_label": {"en": "Type:", "ru": "Тип:"},
    "filter.status_label": {"en": "Status:", "ru": "Статус:"},
    "disk_status.on_disk": {"en": "On disk", "ru": "На диске"},
    "disk_status.missing": {"en": "Missing", "ru": "Удалён с диска"},
    "disk_status.error": {"en": "Error", "ru": "Ошибка"},
    "filter.all": {"en": "All", "ru": "Все"},
    "dialog.close_confirm": {
        "en": "A download is in progress. Close the app and cancel it?",
        "ru": "Идёт скачивание. Закрыть приложение и прервать его?",
    },
    "dialog.pick_dest_folder_title": {"en": "Download folder", "ru": "Папка для загрузок"},
    "warning.need_url": {"en": "Paste a link.", "ru": "Вставь ссылку."},
    "status.checking_link": {"en": "Checking the link…", "ru": "Проверяю ссылку…"},
    "status.error_prefix": {"en": "Error: {msg}", "ru": "Ошибка: {msg}"},
    "status.cancelled": {"en": "Cancelled", "ru": "Отменено"},
    "status.nothing_selected": {"en": "Nothing selected", "ru": "Ничего не выбрано"},
    "status.starting": {"en": "Starting…", "ru": "Запуск…"},
    "status.playlist_progress": {"en": "Playlist: {done}/{total}", "ru": "Плейлист: {done}/{total}"},
    "status.playlist_done": {"en": "Done: playlist ({done}/{total})", "ru": "Готово: плейлист ({done}/{total})"},
    "status.done_title": {"en": "Done: {title}", "ru": "Готово: {title}"},
    "dialog.save_as_title": {"en": "Save as…", "ru": "Сохранить как…"},
    "dialog.save_as_filter": {"en": "Text (*.txt)", "ru": "Текст (*.txt)"},
    "msgbox.select_one_history": {
        "en": "Select at least one history entry.",
        "ru": "Выбери хотя бы одну запись в истории.",
    },
    "dialog.delete_confirm": {"en": "Delete {n} entries from history?", "ru": "Удалить {n} запись(ей) из истории?"},
    "button.delete_list_only": {"en": "From the list only", "ru": "Только из списка"},
    "button.delete_with_disk": {"en": "And from disk", "ru": "И с диска"},
    "button.cancel": {"en": "Cancel", "ru": "Отмена"},
    "msgbox.delete_failed": {"en": "Couldn't delete file {path}: {err}", "ru": "Не удалось удалить файл {path}: {err}"},
    "player.ready_to_play": {"en": "{icon} {title} (ready -- press ▶)", "ru": "{icon} {title} (готово — нажми ▶)"},
    "dialog.convert_title": {"en": "Convert", "ru": "Конвертация"},
    "convert.target_label": {"en": "Convert to:", "ru": "Конвертировать в:"},
    "convert.button": {"en": "Convert", "ru": "Конвертировать"},
    "status.converting": {"en": "Converting…", "ru": "Конвертация…"},
    "status.convert_done": {"en": "Converted: {title}", "ru": "Готово: {title}"},
    "status.convert_failed": {"en": "Conversion error: {msg}", "ru": "Ошибка конвертации: {msg}"},
}


def set_language(lang: str) -> None:
    global _current_lang
    _current_lang = lang if lang in LANGUAGES else "en"


def get_language() -> str:
    return _current_lang


def tr(key: str, **kwargs) -> str:
    entry = STRINGS.get(key)
    text = (entry.get(_current_lang) or entry.get("en")) if entry else key
    return text.format(**kwargs) if kwargs else text
