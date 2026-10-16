import logging
from logging.handlers import RotatingFileHandler

from logger import apply_log_rotation_settings


def test_apply_log_rotation_settings_updates_installed_handler(tmp_path):
    handler = RotatingFileHandler(tmp_path / "test.log", maxBytes=1, backupCount=1)
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        apply_log_rotation_settings(max_mb=20, backup_count=7)
        assert handler.maxBytes == 20 * 1024 * 1024
        assert handler.backupCount == 7
    finally:
        root.removeHandler(handler)
        handler.close()


def test_apply_log_rotation_settings_ignores_other_handler_types():
    stream_handler = logging.StreamHandler()
    root = logging.getLogger()
    root.addHandler(stream_handler)
    try:
        apply_log_rotation_settings(max_mb=1, backup_count=1)  # must not raise
    finally:
        root.removeHandler(stream_handler)
