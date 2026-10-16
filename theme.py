"""Design system: light/dark color tokens, a QSS stylesheet built from them, and a small
set of lucide-style (minimalist, round-stroke) SVG icons rendered to QIcon on demand."""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

TOKENS = {
    "dark": {
        "bg": "#0f1016",
        "bg_gradient_top": "#15161f",
        "bg_gradient_bottom": "#0f1016",
        "surface": "rgba(255, 255, 255, 18)",
        "surface_solid": "#1b1c26",
        "border": "rgba(255, 255, 255, 46)",
        "text": "#eef0f7",
        "text_dim": "#9a9db3",
        "accent": "#7c6cf0",
        "accent_hover": "#8d7ef7",
        "accent_text": "#ffffff",
        "success": "#4ade80",
        "danger": "#fb7185",
        "warning": "#fbbf24",
        "icon": "#cfd1e6",
    },
    "light": {
        "bg": "#eef0f6",
        "bg_gradient_top": "#f7f8fc",
        "bg_gradient_bottom": "#e7e9f3",
        "surface": "rgba(255, 255, 255, 190)",
        "surface_solid": "#ffffff",
        "border": "rgba(20, 20, 40, 40)",
        "text": "#1b1d2a",
        "text_dim": "#6b6e85",
        "accent": "#6c5ce7",
        "accent_hover": "#7d6ff0",
        "accent_text": "#ffffff",
        "success": "#16a34a",
        "danger": "#e11d48",
        "warning": "#d97706",
        "icon": "#44475c",
    },
}


def stylesheet(theme: str) -> str:
    t = TOKENS[theme]
    # Order matters: the generic QWidget rule must come first so the more specific
    # QMainWindow rule below actually wins and paints the gradient (otherwise the
    # window ends up transparent, showing the native white backing through it).
    return f"""
QWidget {{ color: {t["text"]}; font-size: 13px; background: transparent; }}

QMainWindow {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {t["bg_gradient_top"]}, stop:1 {t["bg_gradient_bottom"]});
}}

QWidget#card {{
    background-color: {t["surface"]};
    border: 1px solid {t["border"]};
    border-radius: 14px;
}}

QLineEdit, QComboBox, QTreeWidget, QListWidget {{
    background-color: {t["surface_solid"]};
    border: 1px solid {t["border"]};
    border-radius: 10px;
    padding: 7px 10px;
    color: {t["text"]};
    selection-background-color: {t["accent"]};
}}
QLineEdit:focus, QComboBox:focus {{ border: 1px solid {t["accent"]}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{
    background-color: {t["surface_solid"]};
    border: 1px solid {t["border"]};
    border-radius: 10px;
    selection-background-color: {t["accent"]};
    outline: none;
}}

QPushButton {{
    background-color: {t["accent"]};
    border: none;
    border-radius: 10px;
    padding: 9px 16px;
    min-height: 18px;
    font-weight: 600;
    color: {t["accent_text"]};
}}
QPushButton:hover {{ background-color: {t["accent_hover"]}; }}
QPushButton:pressed {{ padding-top: 10px; padding-bottom: 8px; }}
QPushButton:disabled {{ background-color: {t["border"]}; color: {t["text_dim"]}; }}

QPushButton#secondary, QPushButton#ghost {{
    background-color: {t["surface_solid"]};
    color: {t["text"]};
    border: 1px solid {t["border"]};
}}
QPushButton#secondary:hover, QPushButton#ghost:hover {{ background-color: {t["surface"]}; }}
QPushButton#iconBtn {{
    background-color: transparent;
    border: 1px solid {t["border"]};
    border-radius: 10px;
    padding: 6px;
    min-width: 18px;
}}
QPushButton#iconBtn:hover {{ background-color: {t["surface"]}; }}

QProgressBar {{
    background-color: {t["surface_solid"]};
    border: 1px solid {t["border"]};
    border-radius: 7px;
    height: 12px;
    text-align: center;
    color: {t["text"]};
    font-weight: 600;
}}
QProgressBar::chunk {{ background-color: {t["accent"]}; border-radius: 6px; }}

QLabel#status_ok {{ color: {t["success"]}; font-weight: 600; }}
QLabel#status_err {{ color: {t["danger"]}; font-weight: 600; }}
QLabel#status_busy {{ color: {t["warning"]}; font-weight: 600; }}
QLabel#heading {{ font-size: 15px; font-weight: 700; }}
QLabel#dim {{ color: {t["text_dim"]}; }}

QTreeWidget::item, QListWidget::item {{ padding: 6px; border-radius: 8px; }}
QTreeWidget::item:selected, QListWidget::item:selected {{
    background-color: {t["accent"]}; color: {t["accent_text"]};
}}
QTreeWidget, QListWidget {{ alternate-background-color: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {t["border"]}; border-radius: 5px; min-height: 24px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}

QDialog {{ background-color: {t["bg"]}; }}
QSlider::groove:horizontal {{ background: {t["border"]}; height: 5px; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: {t["accent"]}; width: 15px; height: 15px; margin: -5px 0; border-radius: 7px;
}}
QSlider::sub-page:horizontal {{ background: {t["accent"]}; border-radius: 2px; }}
"""


# Minimalist round-stroke icon paths, viewBox 0 0 24 24, lucide-inspired.
_ICON_PATHS: dict[str, str] = {
    "play": '<path d="M7 4l13 8-13 8z"/>',
    "pause": '<path d="M7 4h3v16H7zM14 4h3v16h-3z"/>',
    # "sliders" glyph, not a gear -- a gear/cog built from thin radiating spokes
    # ends up visually identical to the sun icon at this size, which is confusing
    # right next to the theme-toggle button.
    "settings": (
        '<path d="M3 6h7M14 6h7M3 12h3M10 12h11M3 18h7M14 18h7"/>'
        '<circle cx="10.5" cy="6" r="2.2"/>'
        '<circle cx="6.5" cy="12" r="2.2"/>'
        '<circle cx="10.5" cy="18" r="2.2"/>'
    ),
    "globe": (
        '<circle cx="12" cy="12" r="9"/>'
        '<path d="M3 12h18M12 3c3 3.5 3 14.5 0 18M12 3c-3 3.5-3 14.5 0 18"/>'
    ),
    "trash": '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v6M14 11v6"/>',
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "film": (
        '<rect x="3" y="4" width="18" height="16" rx="2"/>'
        '<path d="M3 9h18M3 15h18M8 4v16M16 4v16"/>'
    ),
    "music": '<path d="M9 18V5l11-2v13"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="17.5" cy="16" r="2.5"/>',
    "moon": '<path d="M20 14.5A8.5 8.5 0 1 1 9.5 4a7 7 0 0 0 10.5 10.5z"/>',
    "sun": (
        '<circle cx="12" cy="12" r="4.5"/>'
        '<path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3'
        'M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1"/>'
    ),
    "x": '<path d="M5 5l14 14M19 5L5 19"/>',
    "check": '<path d="M4 12l6 6L20 6"/>',
    "alert": '<path d="M12 3L2 20h20z"/><path d="M12 9v5"/><circle cx="12" cy="17" r="0.8" fill="currentColor"/>',
    "download": '<path d="M12 3v12M7 11l5 5 5-5M5 20h14"/>',
}


def icon(name: str, color: str, size: int = 22) -> QIcon:
    svg = _ICON_PATHS[name]
    doc = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="{color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{svg}</svg>'
    ).replace("currentColor", color)

    renderer = QSvgRenderer(QByteArray(doc.encode()))
    px = QPixmap(QSize(size, size) * 2)  # render at 2x for crisp retina icons
    px.fill(Qt.transparent)
    painter = QPainter(px)
    painter.setRenderHint(QPainter.Antialiasing)
    renderer.render(painter)
    painter.end()
    px.setDevicePixelRatio(2)
    return QIcon(px)
