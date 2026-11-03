"""Every module must at least import (catches syntax errors in GUI/tray code)."""

import importlib

import pytest

MODULES = [
    "dailydeck.__main__", "dailydeck.app", "dailydeck.autostart", "dailydeck.fonts",
    "dailydeck.integration", "dailydeck.preview", "dailydeck.focus.x11",
]
QT_MODULES = ["dailydeck.gui", "dailydeck.tray"]


@pytest.mark.parametrize("name", MODULES)
def test_import(name):
    pytest.importorskip("StreamDeck")
    importlib.import_module(name)


@pytest.mark.parametrize("name", QT_MODULES)
def test_import_qt(name):
    pytest.importorskip("PySide6.QtWidgets")
    importlib.import_module(name)
