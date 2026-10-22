"""Palette paths for Linux, Windows, and macOS.

Linux must keep the desktop theme. Windows and macOS use the built-in
warm dark colors, and a light OS scheme uses the light set.
"""

import os
import re
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication

import appearance
from appearance import (
    BUILTIN_DARK,
    BUILTIN_LIGHT,
    apply_active_palette,
    builtin_palette,
    load_style,
    palette_from_omarchy,
    prefers_builtin_palette,
    remember_desktop_palette,
)


def setUpModule():
    global _app
    _app = QApplication.instance() or QApplication([])
    remember_desktop_palette(_app)


def _role(palette, name):
    return palette.color(getattr(QPalette.ColorRole, name)).name()


def _image_has_color(image, hex_name):
    target = QColor(hex_name)
    for y in range(0, image.height(), 3):
        for x in range(0, image.width(), 3):
            if image.pixelColor(x, y) == target:
                return True
    return False


def _empty_state_home():
    path = tempfile.mkdtemp()
    os.environ["XDG_STATE_HOME"] = path
    return path


class PalettePathTests(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("XDG_STATE_HOME", None)
        appearance._color_scheme_overridden = False
        hints = _app.styleHints()
        if hasattr(hints, "unsetColorScheme"):
            hints.unsetColorScheme()

    def test_platform_gate(self):
        self.assertTrue(prefers_builtin_palette("win32"))
        self.assertTrue(prefers_builtin_palette("darwin"))
        self.assertFalse(prefers_builtin_palette("linux"))

    def test_linux_does_not_install_the_builtin_palette(self):
        _empty_state_home()
        _app.setStyle("Windows")
        sentinel = QPalette(_app.palette())
        sentinel.setColor(QPalette.ColorRole.Window, QColor("#123456"))
        _app.setPalette(sentinel)
        kind = apply_active_palette(_app, platform="linux")
        self.assertEqual(kind, "system")
        self.assertEqual(_app.style().objectName().lower(), "windows")
        scheme = _app.styleHints().colorScheme()
        if scheme not in (Qt.ColorScheme.Light, Qt.ColorScheme.Dark):
            self.assertEqual(_role(_app.palette(), "Window"), "#123456")

    def test_windows_and_mac_use_the_dark_default(self):
        _empty_state_home()
        for platform in ("win32", "darwin"):
            _app.setStyle("Windows")
            kind = apply_active_palette(_app, platform=platform)
            self.assertEqual(kind, "builtin")
            self.assertEqual(_app.style().objectName().lower(), "fusion")
            palette = _app.palette()
            self.assertEqual(_role(palette, "Window"), BUILTIN_DARK["background"])
            self.assertEqual(_role(palette, "Button"), BUILTIN_DARK["button"])
            self.assertEqual(_role(palette, "Base"), BUILTIN_DARK["base"])
            self.assertEqual(_role(palette, "AlternateBase"), BUILTIN_DARK["alternate"])
            self.assertEqual(_role(palette, "Text"), BUILTIN_DARK["foreground"])
            self.assertEqual(_role(palette, "Highlight"), BUILTIN_DARK["accent"])
            self.assertEqual(_role(palette, "Accent"), BUILTIN_DARK["accent"])
            self.assertLess(QColor(BUILTIN_DARK["background"]).lightness(), 128)
            self.assertGreater(QColor(BUILTIN_DARK["foreground"]).lightness(), 200)

    def test_light_scheme_keeps_the_accent(self):
        palette = builtin_palette(Qt.ColorScheme.Light)
        self.assertEqual(_role(palette, "Window"), BUILTIN_LIGHT["background"])
        self.assertEqual(_role(palette, "Text"), BUILTIN_LIGHT["foreground"])
        self.assertEqual(_role(palette, "Highlight"), "#7b8fc9")
        self.assertEqual(_role(palette, "Accent"), "#7b8fc9")
        self.assertGreaterEqual(
            palette.color(QPalette.ColorRole.Window).lightness(),
            128,
        )
        unknown = builtin_palette(Qt.ColorScheme.Unknown)
        dark = builtin_palette(Qt.ColorScheme.Dark)
        self.assertEqual(_role(unknown, "Window"), BUILTIN_DARK["background"])
        self.assertEqual(_role(dark, "Window"), BUILTIN_DARK["background"])

    def test_omarchy_still_wins_on_windows(self):
        root = Path(_empty_state_home())
        theme = root / "omarchy" / "current" / "theme"
        theme.mkdir(parents=True)
        (theme / "colors.toml").write_text(
            '\n'.join(
                [
                    'background = "#112233"',
                    'foreground = "#eeeeee"',
                    'accent = "#abcdef"',
                    'mode = "dark"',
                ]
            ),
            encoding="utf-8",
        )
        _app.setStyle("Windows")
        kind = apply_active_palette(_app, platform="win32")
        self.assertEqual(kind, "omarchy")
        self.assertEqual(_role(_app.palette(), "Window"), "#112233")
        self.assertEqual(_role(_app.palette(), "Highlight"), "#abcdef")
        self.assertEqual(_app.style().objectName().lower(), "windows")

    def test_omarchy_mapping_is_unchanged(self):
        palette = palette_from_omarchy(
            {
                "background": QColor("#000000"),
                "foreground": QColor("#ffffff"),
                "accent": QColor("#ff0000"),
            }
        )
        self.assertEqual(_role(palette, "Window"), "#000000")
        self.assertEqual(_role(palette, "Base"), "#000000")
        self.assertEqual(_role(palette, "Button"), "#141414")
        self.assertEqual(_role(palette, "AlternateBase"), "#232323")
        self.assertEqual(_role(palette, "Mid"), "#595959")
        self.assertEqual(_role(palette, "Highlight"), "#ff0000")
        # Pure red sits on the lightness boundary, so the text on it is
        # the black background. That is the same choice as before.
        self.assertEqual(_role(palette, "HighlightedText"), "#000000")
        disabled = palette.color(
            QPalette.ColorGroup.Disabled,
            QPalette.ColorRole.WindowText,
        ).name()
        self.assertEqual(disabled, "#8c8c8c")

    def test_stylesheet_uses_palette_roles(self):
        text = Path("style.qss").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"#[0-9A-Fa-f]{3,8}\b", text))
        for role in (
            "palette(window)",
            "palette(button)",
            "palette(highlight)",
            "palette(highlighted-text)",
            "palette(base)",
            "palette(alternate-base)",
            "palette(text)",
        ):
            self.assertIn(role, text)


class WidgetPaletteTests(unittest.TestCase):
    def test_plots_tables_tabs_and_buttons_pick_up_the_dark_palette(self):
        os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
        try:
            apply_active_palette(_app, platform="win32")
            load_style(_app)
            from main import PyGraphyWindow

            window = PyGraphyWindow()
            window.resize(1100, 700)
            window._load_sample()
            window.show()
            _app.processEvents()

            graph = window.mode_buttons["graph"]
            self.assertTrue(graph.isChecked())
            button_image = graph.grab().toImage()
            self.assertEqual(button_image.pixelColor(4, 4).name(), "#7b8fc9")

            manual = window.mode_buttons["manual"]
            manual_image = manual.grab().toImage()
            self.assertEqual(manual_image.pixelColor(4, 4).name(), "#322a2a")

            shell = window.centralWidget().grab().toImage()
            self.assertEqual(shell.pixelColor(2, 2).name(), "#1a1212")

            tab = window._current_tab()
            tab.table.selectRow(0)
            _app.processEvents()
            self.assertEqual(
                tab.table.palette().color(QPalette.ColorRole.Highlight).name(),
                "#7b8fc9",
            )
            self.assertEqual(
                tab.table.palette().color(QPalette.ColorRole.Base).name(),
                "#2a2222",
            )
            table_image = tab.table.grab().toImage()
            self.assertTrue(_image_has_color(table_image, "#7b8fc9"))

            panel = window.graph_board.selected_panel()
            self.assertEqual(panel.plot.backgroundBrush().color().name(), "#1a1212")
            self.assertEqual(panel.line_item.opts["pen"].color().name(), "#7b8fc9")
            self.assertEqual(panel.marker_item.opts["brush"].color().name(), "#7b8fc9")

            window._set_mode("manual")
            _app.processEvents()
            field = window.column_name_edit.grab().toImage()
            self.assertEqual(field.pixelColor(8, 8).name(), "#2a2222")
            self.assertGreaterEqual(window.manual_switcher.count(), 1)
            tab_image = window.manual_switcher.grab().toImage()
            self.assertEqual(tab_image.pixelColor(8, 8).name(), "#7b8fc9")
            window.close()
        finally:
            os.environ.pop("XDG_STATE_HOME", None)


if __name__ == "__main__":
    unittest.main()
