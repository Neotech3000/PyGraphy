"""Desktop theme for the PyGraphy window.

On Omarchy, the window uses the active theme's background, text, and
accent, and it updates when that theme file changes. On other Linux
desktops it follows the freedesktop light or dark setting and the
palette Qt got from the desktop. That path is unchanged.

Windows and macOS do not inherit the Linux theme. Their native styles
also ignore most palette roles, so buttons, fields, and tables would
stay the OS gray. They use Fusion and ``BUILTIN_DARK`` when the system
is dark or has no preference: a warm near-black window, lighter brown
panels, near-white text, and a muted periwinkle accent. A light system
setting uses ``BUILTIN_LIGHT`` with the same accent, so the window
still follows the OS.

``style.qss`` is applied after the palette and looks up ``palette()``
roles, so a theme change reloads that file. Do not put a hex color in
that file.

``main`` calls ``remember_desktop_palette``, then ``apply_active_palette``,
then ``load_style``. The watcher objects stay alive on the window so a
change during the session is picked up.
"""

import os
import re
import sys
from pathlib import Path

from PyQt6.QtCore import QFileSystemWatcher, QObject, Qt, QTimer, pyqtSlot
from PyQt6.QtGui import QColor, QPalette

from dataset import bundled_path


# Palette Qt received from the desktop at startup, before any replacement.
_desktop_palette = None
_desktop_scheme = None
# True only after this process calls setColorScheme. Unset is then safe.
_color_scheme_overridden = False
# Marks an application whose style this process already set to Fusion.
_FUSION_PROPERTY = "pygraphyFusionStyle"
# Remembers which palette path an application chose: omarchy, builtin,
# or system.
_PALETTE_KIND_PROPERTY = "pygraphyPaletteKind"

try:
    from PyQt6.QtDBus import QDBusVariant
except ImportError:
    QDBusVariant = None


def _palette_is_light(palette):
    """Window lightness at or above 128 counts as a light theme."""
    return palette.color(QPalette.ColorRole.Window).lightness() >= 128


def _copy_palette(palette):
    """Copy every color into a new palette.

    QPalette copies share hidden data. Later theme changes can rewrite
    that shared data. Building a new palette keeps the startup colors.
    """
    copy = QPalette()
    groups = (
        QPalette.ColorGroup.Active,
        QPalette.ColorGroup.Inactive,
        QPalette.ColorGroup.Disabled,
    )
    for group in groups:
        for role in QPalette.ColorRole:
            if role in (QPalette.ColorRole.NColorRoles, QPalette.ColorRole.NoRole):
                continue
            copy.setColor(group, role, QColor(palette.color(group, role)))
    return copy


def _install_palette(app, palette):
    """Put palette on the application and keep it if the style replaces it."""
    wanted = palette.color(QPalette.ColorRole.Window)
    app.setPalette(palette)
    if app.palette().color(QPalette.ColorRole.Window) == wanted:
        return
    sheet = app.styleSheet()
    app.setStyleSheet("")
    app.setPalette(QPalette(palette))
    if sheet:
        app.setStyleSheet(sheet)
    if app.palette().color(QPalette.ColorRole.Window) != wanted:
        app.setPalette(QPalette(palette))


_COLOR_LINE = re.compile(
    r"""^\s*([A-Za-z0-9_-]+)\s*=\s*["']?(#[0-9A-Fa-f]{6})"""
)
_MODE_LINE = re.compile(r"""^\s*mode\s*=\s*["']?(dark|light)\b""", re.IGNORECASE)


def omarchy_theme_dir():
    """Folder Omarchy rewrites when the active theme changes.

    XDG_STATE_HOME wins when it is set. Otherwise the folder is
    .local/state under the current user's home. Nothing here names
    one computer's folders.
    """
    state_home = os.environ.get("XDG_STATE_HOME")
    if state_home:
        root = Path(state_home)
    else:
        root = Path.home() / ".local" / "state"
    return root / "omarchy" / "current" / "theme"


def _hex_color(text):
    color = QColor(text)
    if not color.isValid():
        return None
    return color


def read_omarchy_colors():
    """Read background, text, and accent from the active Omarchy theme.

    The file is colors.toml in omarchy_theme_dir(). Text is the
    foreground key. Older themes use color0, color7, and color4 for
    the same three jobs. Returns None when this is not an Omarchy
    machine or the file has no colors.
    """
    path = omarchy_theme_dir() / "colors.toml"
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    found = {}
    mode = None
    for line in raw.splitlines():
        color_match = _COLOR_LINE.match(line)
        if color_match:
            found[color_match.group(1)] = color_match.group(2)
            continue
        mode_match = _MODE_LINE.match(line)
        if mode_match:
            mode = mode_match.group(1).lower()
    background = _hex_color(found.get("background") or found.get("color0") or "")
    text = _hex_color(found.get("foreground") or found.get("color7") or "")
    accent = _hex_color(found.get("accent") or found.get("color4") or "")
    if background is None or text is None or accent is None:
        return None
    return {
        "background": background,
        "foreground": text,
        "accent": accent,
        "mode": mode,
    }


def _mix_colors(start, end, amount):
    """Blend start toward end. amount 0 keeps start."""
    amount = max(0.0, min(1.0, amount))
    return QColor(
        int(start.red() + (end.red() - start.red()) * amount),
        int(start.green() + (end.green() - start.green()) * amount),
        int(start.blue() + (end.blue() - start.blue()) * amount),
    )


def _text_on(accent, background, text):
    """Pick background or text, whichever stands out more on accent."""
    accent_light = accent.lightness()
    if abs(background.lightness() - accent_light) >= abs(text.lightness() - accent_light):
        return QColor(background)
    return QColor(text)


def _palette_with_colors(background, text, accent, button, alternate, mid, base):
    """Fill the roles plots, tables, tabs, and buttons read.

    ``base`` is the field and table color. Omarchy passes the window
    background for it. The built-in palette passes a lighter panel
    color so inputs sit above the window.
    """
    quiet = _mix_colors(text, background, 0.45)
    on_accent = _text_on(accent, background, text)
    dark = _mix_colors(background, text, 0.55)
    palette = QPalette()
    groups = (
        QPalette.ColorGroup.Active,
        QPalette.ColorGroup.Inactive,
        QPalette.ColorGroup.Disabled,
    )
    for group in groups:
        disabled = group == QPalette.ColorGroup.Disabled
        ink = quiet if disabled else text
        palette.setColor(group, QPalette.ColorRole.Window, background)
        palette.setColor(group, QPalette.ColorRole.WindowText, ink)
        palette.setColor(group, QPalette.ColorRole.Base, base)
        palette.setColor(group, QPalette.ColorRole.AlternateBase, alternate)
        palette.setColor(group, QPalette.ColorRole.Text, ink)
        palette.setColor(group, QPalette.ColorRole.Button, button)
        palette.setColor(group, QPalette.ColorRole.ButtonText, ink)
        palette.setColor(group, QPalette.ColorRole.Highlight, accent)
        palette.setColor(group, QPalette.ColorRole.HighlightedText, on_accent)
        palette.setColor(group, QPalette.ColorRole.Accent, accent)
        palette.setColor(group, QPalette.ColorRole.ToolTipBase, button)
        palette.setColor(group, QPalette.ColorRole.ToolTipText, text)
        palette.setColor(group, QPalette.ColorRole.PlaceholderText, quiet)
        palette.setColor(group, QPalette.ColorRole.Link, accent)
        palette.setColor(group, QPalette.ColorRole.Light, alternate)
        palette.setColor(group, QPalette.ColorRole.Mid, mid)
        palette.setColor(group, QPalette.ColorRole.Dark, dark)
        palette.setColor(group, QPalette.ColorRole.Shadow, background)
    return palette


def palette_from_omarchy(colors):
    """Map Omarchy background, text, and accent onto Qt palette roles.

    Edit the role lines in ``_palette_with_colors`` to change which
    color paints a part of the window. The mixes below are the Omarchy
    mapping: fields match the window, and buttons are a short step
    toward the text color. PyQtGraph reads Base, Text, Highlight, and
    Accent. style.qss looks up the same roles with palette().
    """
    background = QColor(colors["background"])
    text = QColor(colors["foreground"])
    accent = QColor(colors["accent"])
    return _palette_with_colors(
        background,
        text,
        accent,
        _mix_colors(background, text, 0.08),
        _mix_colors(background, text, 0.14),
        _mix_colors(background, text, 0.35),
        background,
    )


# The Linux desktop paints this warm dark set from its own theme.
# Windows and macOS do not have that theme, so these are their default
# dark colors. background is in #140d0d–#1a1212. button, base, and
# alternate are in #2a2222–#3a3030. accent is the muted periwinkle.
BUILTIN_DARK = {
    "background": "#1a1212",
    "foreground": "#f0ecec",
    "accent": "#7b8fc9",
    "button": "#322a2a",
    "base": "#2a2222",
    "alternate": "#3a3030",
    "mid": "#5a504c",
    "midlight": "#403836",
}

# Same accent on warm light surfaces. Used when the OS scheme is light,
# so Windows and macOS still follow that setting.
BUILTIN_LIGHT = {
    "background": "#f4f0ec",
    "foreground": "#1a1212",
    "accent": "#7b8fc9",
    "button": "#e6ddd6",
    "base": "#fffcf9",
    "alternate": "#efe6df",
    "mid": "#c9beb6",
    "midlight": "#faf7f4",
}


def prefers_builtin_palette(platform=None):
    """Windows and macOS do not inherit the Linux desktop theme.

    Linux returns False, so Omarchy and the freedesktop setting stay
    in charge there. ``platform`` defaults to this process.
    """
    if platform is None:
        platform = sys.platform
    return platform in ("win32", "darwin")


def builtin_palette(scheme):
    """The Windows and macOS palette for one color scheme.

    Dark, and no preference, use ``BUILTIN_DARK``. That is the default
    appearance, and it matches the Linux window. Light uses
    ``BUILTIN_LIGHT`` so an OS light setting still restyles the window.
    The accent is ``#7b8fc9`` in both.
    """
    colors = BUILTIN_LIGHT if scheme == Qt.ColorScheme.Light else BUILTIN_DARK
    background = QColor(colors["background"])
    text = QColor(colors["foreground"])
    accent = QColor(colors["accent"])
    palette = _palette_with_colors(
        background,
        text,
        accent,
        QColor(colors["button"]),
        QColor(colors["alternate"]),
        QColor(colors["mid"]),
        QColor(colors["base"]),
    )
    # Fusion bevels read Midlight and BrightText. Leaving the defaults
    # puts a white edge on a dark button.
    groups = (
        QPalette.ColorGroup.Active,
        QPalette.ColorGroup.Inactive,
        QPalette.ColorGroup.Disabled,
    )
    midlight = QColor(colors["midlight"])
    for group in groups:
        palette.setColor(group, QPalette.ColorRole.Midlight, midlight)
        palette.setColor(group, QPalette.ColorRole.BrightText, text)
        palette.setColor(group, QPalette.ColorRole.LinkVisited, accent)
    return palette


def _use_fusion_style(app):
    """Use Fusion so palette roles reach buttons, fields, tables, and tabs.

    Windows and macOS native styles draw those controls from the OS
    theme and skip the palette. Linux must not call this. Its desktop
    style is what paints the Omarchy colors.

    A stylesheet wraps the style in QStyleSheetStyle, and that wrapper
    hides the name of the style underneath it. Once style.qss is loaded
    the name reads as an empty string, so the name alone cannot tell
    Fusion from another style. The name is trusted when it is readable.
    While it is hidden, this remembers that it already installed
    Fusion, so the style is not built again on every theme change.
    """
    style = app.style()
    name = style.objectName().lower() if style is not None else ""
    if name == "fusion":
        app.setProperty(_FUSION_PROPERTY, True)
        return
    if name == "" and app.property(_FUSION_PROPERTY):
        # The name is hidden by the stylesheet wrapper. This process
        # installed Fusion already, so the hidden style is Fusion.
        return
    app.setStyle("Fusion")
    app.setProperty(_FUSION_PROPERTY, True)


def apply_builtin_palette(app):
    """Install the built-in palette for the current OS color scheme.

    Call this on Windows and macOS only. It switches the style to
    Fusion, then paints ``builtin_palette``. It does not call
    setColorScheme, so a later OS change can still be read.
    """
    _use_fusion_style(app)
    _install_palette(app, builtin_palette(app.styleHints().colorScheme()))


def apply_active_palette(app, platform=None):
    """Choose and install the palette for this computer.

    Returns ``"omarchy"``, ``"builtin"``, or ``"system"``. Does not
    reload style.qss. Call ``load_style`` after this so palette() roles
    are read again.

    Omarchy wins wherever colors.toml is present. Linux otherwise
    follows the freedesktop light/dark setting and the desktop palette.
    Windows and macOS use the built-in palette and still switch with
    the OS light or dark setting.

    The choice is remembered on the app. A theme change calls this
    again without a platform, and it reuses the remembered choice
    instead of asking the platform a second time. Without that, a
    window that was given the built-in palette would go back to the
    desktop palette on the next theme change. Pass ``platform`` to
    change the choice.
    """
    if apply_omarchy_palette(app):
        app.setProperty(_PALETTE_KIND_PROPERTY, "omarchy")
        return "omarchy"
    if platform is not None:
        kind = "builtin" if prefers_builtin_palette(platform) else "system"
        app.setProperty(_PALETTE_KIND_PROPERTY, kind)
    else:
        kind = app.property(_PALETTE_KIND_PROPERTY)
        if kind not in ("builtin", "system"):
            kind = "builtin" if prefers_builtin_palette() else "system"
            app.setProperty(_PALETTE_KIND_PROPERTY, kind)
    if kind == "builtin":
        apply_builtin_palette(app)
    else:
        apply_system_color_scheme(app)
        sync_palette_to_color_scheme(app)
    return kind


def apply_omarchy_palette(app):
    """Use the Omarchy theme when colors.toml is present.

    Returns False on machines that are not Omarchy so the caller can
    keep the freedesktop light/dark behavior.
    """
    global _color_scheme_overridden
    colors = read_omarchy_colors()
    if colors is None:
        return False
    mode = colors.get("mode")
    if mode == "light":
        scheme = Qt.ColorScheme.Light
    elif mode == "dark":
        scheme = Qt.ColorScheme.Dark
    elif colors["background"].lightness() >= 128:
        scheme = Qt.ColorScheme.Light
    else:
        scheme = Qt.ColorScheme.Dark
    hints = app.styleHints()
    if hints.colorScheme() != scheme:
        hints.setColorScheme(scheme)
        _color_scheme_overridden = True
    _install_palette(app, palette_from_omarchy(colors))
    return True


def remember_desktop_palette(app):
    """Save the startup palette so a return to that scheme can restore it."""
    global _desktop_palette, _desktop_scheme
    _desktop_palette = _copy_palette(app.palette())
    if _palette_is_light(_desktop_palette):
        _desktop_scheme = Qt.ColorScheme.Light
    else:
        _desktop_scheme = Qt.ColorScheme.Dark


def _unwrap_dbus(value):
    for _ in range(5):
        if not hasattr(value, "variant"):
            break
        value = value.variant()
    return value


def _qt_scheme_from_portal_number(number):
    """Translate a portal color-scheme int into a Qt color scheme.

    The portal and Qt do not share numbers. Portal 1 is dark and portal
    2 is light. Qt's Light is 1 and Qt's Dark is 2.
    """
    try:
        number = int(number)
    except (TypeError, ValueError):
        return None
    if number == 0:
        return Qt.ColorScheme.Unknown
    if number == 1:
        return Qt.ColorScheme.Dark
    if number == 2:
        return Qt.ColorScheme.Light
    return None


def read_portal_color_scheme():
    """Read org.freedesktop.appearance color-scheme from the settings portal.

    Returns a Qt.ColorScheme, or None when this is not Linux or the
    portal cannot be asked. Portal 0 becomes Unknown (no preference).
    """
    if not sys.platform.startswith("linux") or QDBusVariant is None:
        return None
    from PyQt6.QtDBus import QDBusConnection, QDBusInterface, QDBusMessage

    bus = QDBusConnection.sessionBus()
    if not bus.isConnected():
        return None
    iface = QDBusInterface(
        "org.freedesktop.portal.Desktop",
        "/org/freedesktop/portal/desktop",
        "org.freedesktop.portal.Settings",
        bus,
    )
    if not iface.isValid():
        return None
    reply = iface.call("Read", "org.freedesktop.appearance", "color-scheme")
    if reply.type() != QDBusMessage.MessageType.ReplyMessage:
        return None
    arguments = reply.arguments()
    if not arguments:
        return None
    return _qt_scheme_from_portal_number(_unwrap_dbus(arguments[0]))


def apply_system_color_scheme(app):
    """Point Qt at the portal scheme when Qt is not already following it.

    Matching schemes are left alone. setColorScheme would lock the
    choice and stop later desktop changes until unsetColorScheme.
    """
    global _color_scheme_overridden
    portal = read_portal_color_scheme()
    if portal is None:
        return
    hints = app.styleHints()
    if portal in (Qt.ColorScheme.Light, Qt.ColorScheme.Dark):
        if hints.colorScheme() != portal:
            hints.setColorScheme(portal)
            _color_scheme_overridden = True
        return
    if (
        portal == Qt.ColorScheme.Unknown
        and _color_scheme_overridden
        and hasattr(hints, "unsetColorScheme")
    ):
        hints.unsetColorScheme()
        _color_scheme_overridden = False


def sync_palette_to_color_scheme(app):
    """Give the window a light or dark palette that matches the scheme.

    Qt on this desktop updates the scheme name and leaves the old
    colors in place. style.qss looks those colors up with palette(),
    so the palette has to change before load_style runs again.

    The palette saved at startup is put back when the scheme returns
    to the one the computer used then. The other side comes from the
    current widget style, not from a color typed in this file.
    """
    if _desktop_palette is None:
        return
    scheme = app.styleHints().colorScheme()
    if scheme not in (Qt.ColorScheme.Light, Qt.ColorScheme.Dark):
        return
    window = app.palette().color(QPalette.ColorRole.Window)
    saved = _desktop_palette.color(QPalette.ColorRole.Window)
    if scheme == _desktop_scheme:
        # Qt may already have swapped in a generic dark or light palette.
        # Put the desktop colors back when the scheme matches startup.
        if window != saved:
            _install_palette(app, _copy_palette(_desktop_palette))
        return
    want_light = scheme == Qt.ColorScheme.Light
    if _palette_is_light(app.palette()) == want_light:
        return
    _install_palette(app, app.style().standardPalette())


def load_style(app):
    """Read style.qss and apply it to the whole window.

    Edit style.qss to change a font, spacing, or which palette role a
    widget uses. Edit this function only to change how that file is
    found or loaded. Call it again after a light or dark change so
    palette() roles are looked up on the new colors.
    """
    path = bundled_path("style.qss")
    if not path.is_file():
        app.setStyleSheet("")
        return
    app.setStyleSheet(path.read_text(encoding="utf-8"))


class _DesktopSchemeWatcher(QObject):
    """Hear freedesktop color-scheme changes while the window is open."""

    def __init__(self, app, window):
        super().__init__(app)
        self._app = app
        self._window = window
        if QDBusVariant is None or not sys.platform.startswith("linux"):
            return
        from PyQt6.QtDBus import QDBusConnection

        bus = QDBusConnection.sessionBus()
        if not bus.isConnected():
            return
        bus.connect(
            "org.freedesktop.portal.Desktop",
            "/org/freedesktop/portal/desktop",
            "org.freedesktop.portal.Settings",
            "SettingChanged",
            "ssv",
            self._on_setting_changed,
        )

    if QDBusVariant is not None:
        @pyqtSlot(str, str, QDBusVariant)
        def _on_setting_changed(self, namespace, key, value):
            if namespace != "org.freedesktop.appearance" or key != "color-scheme":
                return
            apply_system_color_scheme(self._app)
            _restyle_after_scheme_change(self._app, self._window)
    else:
        def _on_setting_changed(self, *_args):
            return None


class _OmarchyThemeWatcher(QObject):
    """Re-read colors.toml when Omarchy writes a new theme."""

    def __init__(self, app, window):
        super().__init__(app)
        self._app = app
        self._window = window
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._changed)
        self._watcher.directoryChanged.connect(self._changed)
        self._arm()

    def _arm(self):
        """Watch the theme folder and colors.toml. A replaced file needs a new watch."""
        theme_dir = omarchy_theme_dir()
        colors = theme_dir / "colors.toml"
        if theme_dir.is_dir():
            self._watcher.addPath(str(theme_dir))
        if colors.is_file():
            self._watcher.addPath(str(colors))

    def _changed(self, _path):
        self._arm()
        _restyle_after_scheme_change(self._app, self._window)



_restyle_queued = False


def _restyle_after_scheme_change(app, window):
    """Apply a theme change after Qt finishes delivering the signal.

    Setting the palette from inside colorSchemeChanged is overwritten
    by Qt before the signal returns. One queued call reads the scheme
    that is current at that later moment, then updates the window and
    the plot.
    """
    global _restyle_queued
    if _restyle_queued:
        return
    _restyle_queued = True

    def apply_when_ready():
        global _restyle_queued
        _restyle_queued = False
        # apply_active_palette installs the palette, and load_style
        # reads the palette roles back out of it. Installing the
        # palette a second time after that only repeats work: the
        # stylesheet does not change the palette, and _install_palette
        # already repairs a palette the style replaced.
        apply_active_palette(app)
        load_style(app)
        board = getattr(window, "graph_board", None)
        if board is not None:
            board.apply_plot_palette()

    QTimer.singleShot(0, apply_when_ready)


