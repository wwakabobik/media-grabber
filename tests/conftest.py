import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# pytest-qt (installed as a dev dependency) auto-registers itself and supplies the
# `qapp` / `qtbot` fixtures used throughout tests/test_gui.py (QT_QPA_PLATFORM=offscreen
# above makes QApplication creation work with no real display). qtbot.addWidget() hands
# Qt widget teardown to pytest-qt in the order it expects -- letting Python's GC do it
# at interpreter exit instead segfaults on exit even when every test already passed.


@pytest.fixture(autouse=True)
def _reset_i18n_language():
    # i18n's current language is process-global state. MainWindow() picks it up from
    # the user's *real* ~/.config/media-grabber/state.json on construction -- if that
    # file has "language": "ru" (as it genuinely does once someone actually uses the
    # app), every test that builds a MainWindow leaks "ru" into every test after it.
    import i18n

    i18n.set_language("en")
    yield
    i18n.set_language("en")
