import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# pytest-qt (installed as a dev dependency) auto-registers itself and supplies the
# `qapp` / `qtbot` fixtures used throughout tests/test_gui.py (QT_QPA_PLATFORM=offscreen
# above makes QApplication creation work with no real display). qtbot.addWidget() hands
# Qt widget teardown to pytest-qt in the order it expects -- letting Python's GC do it
# at interpreter exit instead segfaults on exit even when every test already passed.
