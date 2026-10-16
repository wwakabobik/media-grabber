"""structlog setup: console (human-readable) + rotating JSON file, same shape as the
logger.py used in fenix/python/tests and agi_assistant."""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import structlog
from structlog.contextvars import merge_contextvars
from structlog.processors import StackInfoRenderer, TimeStamper
from structlog.stdlib import (
    ExtraAdder,
    PositionalArgumentsFormatter,
    ProcessorFormatter,
    add_log_level,
    add_logger_name,
)
from structlog.types import Processor

LOG_DIR = Path.home() / ".config" / "media-grabber" / "logs"
LOG_FILE = LOG_DIR / "media-grabber.log"

# Logging levels for specific libraries
LOG_LEVELS = {
    "": "DEBUG",  # root
    "urllib3": "WARNING",
    "websockets": "WARNING",
    "spotipy": "INFO",
}


class ConsoleFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        noisy_libs = {"urllib3", "websockets"}
        return not (record.name.split(".")[0] in noisy_libs and record.levelno < logging.WARNING)


class FileFilter(logging.Filter):
    def __init__(self, log_levels: dict):
        super().__init__()
        self.log_levels = log_levels

    def filter(self, record: logging.LogRecord) -> bool:
        logger_name = record.name.split(".")[0]
        if logger_name in self.log_levels:
            target_level = logging.getLevelName(self.log_levels[logger_name])
            return record.levelno >= int(target_level)
        return True


DEFAULT_LOG_MAX_MB = 5
DEFAULT_LOG_BACKUP_COUNT = 5


def apply_log_rotation_settings(max_mb: int, backup_count: int) -> None:
    """Updates the already-installed RotatingFileHandler in place -- these are
    plain attributes on the handler, safe to change at runtime, so a Settings
    change takes effect on the next rollover without restarting the app."""
    for handler in logging.getLogger().handlers:
        if isinstance(handler, RotatingFileHandler):
            handler.maxBytes = max_mb * 1024 * 1024
            handler.backupCount = backup_count


def setup_logging(log_level: str = "DEBUG", max_mb: int = DEFAULT_LOG_MAX_MB, backup_count: int = DEFAULT_LOG_BACKUP_COUNT) -> None:
    timestamper = TimeStamper(fmt="iso")

    shared_processors: list[Processor] = [
        merge_contextvars,
        add_logger_name,
        add_log_level,
        PositionalArgumentsFormatter(),
        ExtraAdder(),
        timestamper,
        StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=[*shared_processors, ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    console_formatter = ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[ProcessorFormatter.remove_processors_meta, structlog.dev.ConsoleRenderer()],
    )
    file_formatter = ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[ProcessorFormatter.remove_processors_meta, structlog.processors.JSONRenderer()],
    )

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=max_mb * 1024 * 1024, backupCount=backup_count, encoding="utf-8"
    )
    file_handler.setFormatter(file_formatter)
    file_handler.setLevel(logging.DEBUG)
    file_handler.addFilter(FileFilter(LOG_LEVELS))

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(console_formatter)
    console_handler.setLevel(logging.DEBUG)
    console_handler.addFilter(ConsoleFilter())

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(log_level.upper())
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    for name in LOG_LEVELS:
        logging.getLogger(name).setLevel(logging.DEBUG)

    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        root_logger.error("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))

    sys.excepthook = handle_exception


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
