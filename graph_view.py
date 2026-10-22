"""One graph series, plus record playback.

Line, scatter, area, step, bar, horizontal bar, and histogram use PyQtGraph.
PyQtGraph has no real pie chart, and PyQt6.QtCharts is not installed here,
so the donut is drawn with QPainter in DonutChart.

GraphBoard lays several GraphPanel widgets in a grid. Each panel owns its
own rows and its own QTimer. One panel's playback does not move another.
"""

import pyqtgraph as pg
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QImage, QPainter, QPalette, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from dataset import (
    exclusion_message,
    category_aggregate,
    column_stats,
    format_stat,
    histogram_bins,
    numeric_column_names,
    numeric_series,
    pie_values,
    xy_series,
)

pg.setConfigOption("antialias", True)

# Area and step use the same X/Y boxes as line and scatter.
# Horizontal bar uses the same category boxes as bar.
KIND_PAGE = {
    "line": 0,
    "scatter": 0,
    "area": 0,
    "step": 0,
    "histogram": 1,
    "bar": 2,
    "hbar": 2,
    "pie": 3,
}
# None means "use the desktop palette." The other entries are named
# choices for this one panel's marker or revealed line.
LOOK_COLORS = (
    ("Theme", "theme"),
    ("Red", QColor(Qt.GlobalColor.red)),
    ("Blue", QColor(Qt.GlobalColor.blue)),
    ("Green", QColor(Qt.GlobalColor.darkGreen)),
    ("Orange", QColor(Qt.GlobalColor.darkYellow)),
    ("Yellow", QColor(Qt.GlobalColor.yellow)),
)
LINE_KINDS = ("line", "area", "step")
XY_KINDS = ("line", "scatter", "area", "step")
# About 30 frames a second. Each frame moves a fraction of a row, then returns.
PLAYBACK_FRAME_MS = 33
PLAYBACK_ROWS_PER_SECOND = 2.0
# Extra space around the points, as a fraction of the span on each side.
FIT_PADDING = 0.08
# Used when this panel has no numbers left to show.
NEUTRAL_RANGE = (0.0, 1.0)


def _finite_span(low, high):
    """Return a range that is never a single point.

    A flat series still needs a visible height, or the axis collapses.
    """
    if low is None or high is None:
        return NEUTRAL_RANGE
    low = float(low)
    high = float(high)
    if high < low:
        low, high = high, low
    if high == low:
        extra = 1.0 if low == 0.0 else abs(low) * 0.5
        if extra == 0.0:
            extra = 1.0
        return (low - extra, high + extra)
    return (low, high)


def _palette():
    app = QApplication.instance()
    if app is None:
        return QPalette()
    return app.palette()


def _role_color(role):
    return _palette().color(role)


def slice_color(index):
    """One pie color, rotated from the desktop highlight so slices stay distinct."""
    base = _role_color(QPalette.ColorRole.Highlight)
    hue, sat, val, alpha = base.getHsv()
    if hue < 0:
        hue = 200
    if sat < 80:
        sat = 160
    if val < 90:
        val = 180
    return QColor.fromHsv((hue + index * 37) % 360, sat, val, alpha)


class DonutChart(QWidget):
    """A pie with a hole, painted by this widget. One series of category totals."""

    def __init__(self):
        super().__init__()
        self._title = ""
        self._labels = []
        self._values = []
        self._message = "No rows yet."
        self.setMinimumHeight(220)

    def set_chart(self, title, labels, values, message):
        self._title = title
        self._labels = list(labels)
        self._values = list(values)
        self._message = message
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        background = _role_color(QPalette.ColorRole.Window)
        ink = _role_color(QPalette.ColorRole.Text)
        painter.fillRect(self.rect(), background)
        painter.setPen(ink)
        title_font = QFont()
        title_font.setPointSize(12)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.drawText(
            12,
            8,
            self.width() - 24,
            28,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            self._title or "Pie or donut",
        )

        if self._message and not self._values:
            painter.setFont(QFont())
            painter.drawText(
                16,
                48,
                self.width() - 32,
                self.height() - 64,
                int(Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignCenter),
                self._message,
            )
            painter.end()
            return

        total = sum(self._values) or 1
        side = min(self.width() - 220, self.height() - 56)
        side = max(80, side)
        left = 16
        top = 44
        painter.setPen(QPen(background, 1))
        start = 90 * 16
        remaining = 360 * 16
        for index, value in enumerate(self._values):
            if index == len(self._values) - 1:
                span = remaining
            else:
                span = int(round(value / total * 360 * 16))
                remaining -= span
            color = slice_color(index)
            painter.setBrush(QBrush(color))
            painter.drawPie(left, top, side, side, start, span)
            start += span

        hole = int(side * 0.58)
        hole_origin = int((side - hole) / 2)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(background))
        painter.drawEllipse(left + hole_origin, top + hole_origin, hole, hole)

        painter.setPen(ink)
        body = QFont()
        body.setPointSize(9)
        painter.setFont(body)
        legend_x = left + side + 16
        legend_y = 52
        for index, (label, value) in enumerate(zip(self._labels, self._values)):
            color = slice_color(index)
            painter.setBrush(QBrush(color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRect(legend_x, legend_y, 12, 12)
            painter.setPen(ink)
            percent = value / total * 100
            painter.drawText(
                legend_x + 18,
                legend_y + 11,
                f"{label}: {format_stat(value)} ({percent:.0f}%)",
            )
            legend_y += 20
            if legend_y > self.height() - 24:
                break
        if self._message:
            painter.drawText(16, self.height() - 8, self._message)
        painter.end()


class GraphPanel(QFrame):
    """One comparison graph: its own rows, type, columns, and timer.

    The plot items are created once in __init__ and reused. Playback
    never builds a new line or bar, and it never sleeps.
    """

    import_requested = pyqtSignal(object)
    remove_requested = pyqtSignal(object)
    select_requested = pyqtSignal(object)
    panel_changed = pyqtSignal(object)

    def __init__(self, name):
        super().__init__()
        self.name = name
        self.tab = None
        self.setObjectName("graphPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumWidth(280)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._dataset = None
        self._kind = "line"
        self._grid = True
        self._playing = False
        self._reveal = 0.0
        self._painted_whole = -1
        self._column_signature = None
        self._play_style = "reveal"
        self._marker_size = 16
        self._marker_color = None
        self._reveal_color = None

        self.option_stack = QStackedWidget()
        self.option_stack.addWidget(self._build_xy_page())
        self.option_stack.addWidget(self._build_histogram_page())
        self.option_stack.addWidget(self._build_bar_page())
        self.option_stack.addWidget(self._build_pie_page())

        self.title_edit = self._line_edit(self._remember_text)
        self.xlabel_edit = self._line_edit(self._remember_text)
        self.ylabel_edit = self._line_edit(self._remember_text)
        self.label_form = QFormLayout()
        self.label_form.addRow("Title", self.title_edit)
        self.label_form.addRow("X axis label", self.xlabel_edit)
        self.label_form.addRow("Y axis label", self.ylabel_edit)

        self.grid_check = QCheckBox("Show grid")
        self.grid_check.setChecked(True)
        self.grid_check.toggled.connect(self._grid_toggled)

        self.note_label = QLabel(
            "No rows on this graph yet. Next: press Import table on this graph. "
            "Other graphs keep their own rows."
        )
        self.note_label.setWordWrap(True)

        self.plot = pg.PlotWidget()
        self.plot.setMinimumHeight(150)
        self.plot.showGrid(x=True, y=True, alpha=0.25)
        self.line_item = self.plot.plot([], [], pen=pg.mkPen(width=2))
        self.full_line_item = self.plot.plot([], [], pen=pg.mkPen(width=2))
        self.scatter_item = pg.ScatterPlotItem(size=9)
        self.bar_item = pg.BarGraphItem(x=[], height=[], width=0.8)
        self.hbar_item = pg.BarGraphItem(y=[0], x0=[0], width=[0], height=0.6)
        self.marker_item = pg.ScatterPlotItem(size=16, symbol="o")
        self.plot.addItem(self.scatter_item)
        self.plot.addItem(self.bar_item)
        self.plot.addItem(self.hbar_item)
        self.plot.addItem(self.marker_item)
        self.hbar_item.setVisible(False)
        # Drag-to-zoom stays on. Auto-range stays off so a later frame,
        # or another panel, cannot move this view.
        self.plot.getViewBox().disableAutoRange()
        self.donut = DonutChart()

        self.chart_stack = QStackedWidget()
        self.chart_stack.addWidget(self.plot)
        self.chart_stack.addWidget(self.donut)

        self.stats_column = QComboBox()
        self.stats_column.currentTextChanged.connect(self._stats_column_changed)
        self.stats_label = QLabel("Stats appear after a numeric column has numbers.")
        self.stats_label.setWordWrap(True)
        stats_row = QHBoxLayout()
        stats_row.addWidget(QLabel("Stats column"))
        stats_row.addWidget(self.stats_column, stretch=1)

        self._build_playback()
        self._build_header()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        layout.addLayout(self._header)
        layout.addWidget(self.option_stack)
        layout.addLayout(self.label_form)
        layout.addWidget(self.grid_check)
        layout.addWidget(self.note_label)
        layout.addWidget(self.chart_stack, stretch=1)
        layout.addLayout(stats_row)
        layout.addWidget(self.stats_label)
        layout.addWidget(self.playback_box)
        layout.addLayout(self._look_row)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance)
        self._show_kind_page()
        self.set_selected(False)
        self.apply_plot_palette()
        self.fit_data()

    def _build_header(self):
        """Name, graph type, import, and remove. These belong to this panel only."""
        self.name_label = QLabel(self.name)
        self.name_label.setObjectName("sectionLabel")
        self.selected_label = QLabel("Selected")
        self.selected_label.setObjectName("pageHint")
        self.type_combo = QComboBox()
        self.type_combo.setObjectName("graphType")
        for kind, label in (
            ("line", "Line"),
            ("scatter", "Scatter"),
            ("area", "Area"),
            ("step", "Step"),
            ("bar", "Bar"),
            ("hbar", "Horizontal bar"),
            ("histogram", "Histogram"),
            ("pie", "Pie or donut"),
        ):
            self.type_combo.addItem(label, kind)
        self.type_combo.currentIndexChanged.connect(self._type_changed)
        import_button = QPushButton("Import table")
        import_button.setObjectName("importTable")
        import_button.setToolTip("Load a csv, xlsx, or ods file into this graph only.")
        import_button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        import_button.clicked.connect(lambda: self.import_requested.emit(self))
        remove_button = QPushButton("Remove")
        remove_button.setObjectName("removeGraph")
        remove_button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        remove_button.clicked.connect(lambda: self.remove_requested.emit(self))

        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title_row.addWidget(self.name_label)
        title_row.addWidget(self.selected_label)
        title_row.addStretch(1)
        self.fit_button = QPushButton("Fit data")
        self.fit_button.setObjectName("fitData")
        self.fit_button.setToolTip("Zoom this graph so its own rows fill the panel.")
        self.fit_button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.fit_button.clicked.connect(self.fit_data)
        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        button_row.addWidget(import_button, stretch=1)
        button_row.addWidget(self.fit_button, stretch=1)
        button_row.addWidget(remove_button, stretch=1)
        type_row = QHBoxLayout()
        type_row.setSpacing(8)
        type_row.addWidget(QLabel("Graph type"))
        type_row.addWidget(self.type_combo, stretch=1)
        self._header = QVBoxLayout()
        self._header.setSpacing(6)
        self._header.addLayout(title_row)
        self._header.addLayout(button_row)
        self._header.addLayout(type_row)

    def kind(self):
        return self._kind

    def set_name(self, name):
        self.name = name
        self.name_label.setText(name)

    def set_selected(self, selected):
        self.selected_label.setVisible(bool(selected))
        self.setProperty("selected", bool(selected))
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def attach_tab(self, tab):
        """Remember the table that shows this panel's rows."""
        self.tab = tab

    def mousePressEvent(self, event):
        self.select_requested.emit(self)
        super().mousePressEvent(event)

    def _type_changed(self, _index):
        kind = self.type_combo.currentData()
        if not kind or kind == self._kind:
            return
        self._kind = kind
        self._show_kind_page()
        self._redraw()
        self.fit_data()
        self.panel_changed.emit(self)

    def _line_edit(self, callback):
        from PyQt6.QtWidgets import QLineEdit

        edit = QLineEdit()
        edit.textEdited.connect(callback)
        return edit

    def _build_xy_page(self):
        page = QWidget()
        form = QFormLayout(page)
        self.x_combo = QComboBox()
        self.y_combo = QComboBox()
        self.x_combo.currentTextChanged.connect(self._axis_changed)
        self.y_combo.currentTextChanged.connect(self._axis_changed)
        form.addRow("X column", self.x_combo)
        form.addRow("Y column", self.y_combo)
        return page

    def _build_histogram_page(self):
        page = QWidget()
        form = QFormLayout(page)
        self.hist_combo = QComboBox()
        self.hist_combo.currentTextChanged.connect(self._axis_changed)
        self.bin_spin = QSpinBox()
        self.bin_spin.setRange(1, 100)
        self.bin_spin.setValue(10)
        self.bin_spin.valueChanged.connect(self._bins_changed)
        form.addRow("Numeric column", self.hist_combo)
        form.addRow("Bin count", self.bin_spin)
        return page

    def _build_bar_page(self):
        page = QWidget()
        form = QFormLayout(page)
        self.bar_category = QComboBox()
        self.bar_value = QComboBox()
        self.bar_how = QComboBox()
        self.bar_how.addItems(["count", "sum", "mean"])
        self.bar_category.currentTextChanged.connect(self._axis_changed)
        self.bar_value.currentTextChanged.connect(self._axis_changed)
        self.bar_how.currentTextChanged.connect(self._bar_how_changed)
        form.addRow("Category", self.bar_category)
        form.addRow("Value", self.bar_value)
        form.addRow("Aggregation", self.bar_how)
        self.bar_form = form
        return page

    def _build_pie_page(self):
        page = QWidget()
        form = QFormLayout(page)
        self.pie_category = QComboBox()
        self.pie_mode = QComboBox()
        self.pie_mode.addItems(["count", "sum"])
        self.pie_value = QComboBox()
        self.pie_category.currentTextChanged.connect(self._axis_changed)
        self.pie_mode.currentTextChanged.connect(self._pie_mode_changed)
        self.pie_value.currentTextChanged.connect(self._axis_changed)
        form.addRow("Category", self.pie_category)
        form.addRow("Values", self.pie_mode)
        form.addRow("Sum this column", self.pie_value)
        self.pie_form = form
        return page

    def _build_playback(self):
        self.playback_box = QWidget()
        self.playback_box.setObjectName("recordPlayback")
        row = QHBoxLayout(self.playback_box)
        row.setContentsMargins(0, 0, 0, 0)
        title = QLabel("Record playback")
        title.setObjectName("sectionLabel")
        self.play_button = QPushButton("Play")
        self.pause_button = QPushButton("Pause")
        self.reset_button = QPushButton("Reset")
        self.pause_button.setEnabled(False)
        self.play_button.clicked.connect(self._play)
        self.pause_button.clicked.connect(self._pause)
        self.reset_button.clicked.connect(self._reset)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.setMinimumWidth(160)
        self.slider.valueChanged.connect(self._slider_moved)
        self.slider.sliderPressed.connect(self._pause)
        self.speed_combo = QComboBox()
        self.speed_combo.addItem("0.5x", 0.5)
        self.speed_combo.addItem("1x", 1.0)
        self.speed_combo.addItem("2x", 2.0)
        self.speed_combo.addItem("4x", 4.0)
        self.speed_combo.setCurrentText("1x")
        self.speed_combo.currentIndexChanged.connect(self._speed_changed)
        self.playback_label = QLabel("All rows")
        row.addWidget(title)
        row.addWidget(self.play_button)
        row.addWidget(self.pause_button)
        row.addWidget(self.reset_button)
        row.addWidget(self.slider, stretch=1)
        row.addWidget(self.speed_combo)
        row.addWidget(self.playback_label)

        self.marker_size_spin = QSpinBox()
        self.marker_size_spin.setRange(4, 48)
        self.marker_size_spin.setValue(self._marker_size)
        self.marker_size_spin.setPrefix("")
        self.marker_size_spin.valueChanged.connect(self._marker_size_changed)
        self.marker_color_combo = QComboBox()
        self.reveal_color_combo = QComboBox()
        for combo in (self.marker_color_combo, self.reveal_color_combo):
            for label, color in LOOK_COLORS:
                combo.addItem(label, color)
        self.marker_color_combo.currentIndexChanged.connect(self._look_changed)
        self.reveal_color_combo.currentIndexChanged.connect(self._look_changed)
        self.play_style_combo = QComboBox()
        self.play_style_combo.setObjectName("playbackLook")
        self.play_style_combo.addItem("Reveal the line", "reveal")
        self.play_style_combo.addItem("Marker on the full line", "marker")
        self.play_style_combo.currentIndexChanged.connect(self._look_changed)

        self._look_row = QHBoxLayout()
        self._look_row.setSpacing(8)
        self._look_row.addWidget(QLabel("Marker size"))
        self._look_row.addWidget(self.marker_size_spin)
        self._look_row.addWidget(QLabel("Marker color"))
        self._look_row.addWidget(self.marker_color_combo)
        self._look_row.addWidget(QLabel("Playback"))
        self._look_row.addWidget(self.play_style_combo)
        self._look_row.addWidget(QLabel("Revealed color"))
        self._look_row.addWidget(self.reveal_color_combo)
        self._look_row.addStretch(1)

    def bound_dataset(self):
        return self._dataset

    def show_dataset(self, dataset):
        """Switch tabs. Record playback stops so the old position is not reused."""
        self._dataset = dataset
        self._stop_timer()
        self._reload_controls()
        self._jump_slider_to_end()
        self._redraw()
        self.fit_data()

    def note_rows_changed(self, headers_changed):
        self._stop_timer()
        if headers_changed or self._columns_changed():
            self._reload_controls()
        self._jump_slider_to_end()
        self._redraw()
        self.fit_data()

    def set_kind(self, kind):
        """Change this panel's graph type. Other panels are not updated."""
        if kind not in KIND_PAGE:
            return
        self._kind = kind
        index = self.type_combo.findData(kind)
        if index >= 0:
            self.type_combo.blockSignals(True)
            self.type_combo.setCurrentIndex(index)
            self.type_combo.blockSignals(False)
        self._show_kind_page()
        self._redraw()
        self.fit_data()

    def fit_data(self):
        """Zoom this panel so its own rows fill the axes, with a small margin.

        The range comes from every row on this panel, not from the rows
        revealed so far and not from any other panel. Empty data returns
        to a neutral range. A donut has no axes, so it is left alone.
        Dragging the plot still zooms until this is pressed again.
        """
        if self._kind == "pie":
            return
        x_range, y_range = self._fitted_ranges()
        self.plot.getViewBox().setRange(
            xRange=x_range,
            yRange=y_range,
            padding=FIT_PADDING,
        )

    def _fitted_ranges(self):
        """Axis limits for this panel's full data set."""
        dataset = self._dataset
        if dataset is None or not dataset.headers or not dataset.rows:
            return NEUTRAL_RANGE, NEUTRAL_RANGE
        headers = dataset.headers
        rows = dataset.rows
        if self._kind in XY_KINDS:
            series = xy_series(
                headers,
                rows,
                self.x_combo.currentText(),
                self.y_combo.currentText(),
            )
            if not series.x_values:
                return NEUTRAL_RANGE, NEUTRAL_RANGE
            y_low = min(series.y_values)
            y_high = max(series.y_values)
            if self._kind == "area":
                y_low = min(y_low, 0.0)
                y_high = max(y_high, 0.0)
            return (
                _finite_span(min(series.x_values), max(series.x_values)),
                _finite_span(y_low, y_high),
            )
        if self._kind == "histogram":
            values, _blank, _missing, _text = numeric_series(
                headers, rows, self.hist_combo.currentText()
            )
            centers, counts, width = histogram_bins(values, self.bin_spin.value())
            if not centers or not counts:
                return NEUTRAL_RANGE, NEUTRAL_RANGE
            half = (width or 0.8) / 2.0
            return (
                _finite_span(min(centers) - half, max(centers) + half),
                _finite_span(0.0, max(counts)),
            )
        if self._kind in ("bar", "hbar"):
            _labels, numbers, _message = category_aggregate(
                headers,
                rows,
                self.bar_category.currentText(),
                self.bar_value.currentText(),
                self.bar_how.currentText() or "mean",
            )
            if not numbers:
                return NEUTRAL_RANGE, NEUTRAL_RANGE
            along = _finite_span(-0.5, len(numbers) - 0.5)
            across = _finite_span(min(0.0, min(numbers)), max(0.0, max(numbers)))
            if self._kind == "hbar":
                return across, along
            return along, across
        return NEUTRAL_RANGE, NEUTRAL_RANGE

    def _marker_size_changed(self, value):
        self._marker_size = int(value)
        self.marker_item.setSize(self._marker_size)
        if self._playing:
            self._paint_smooth()
        else:
            self._redraw()

    def _look_changed(self, _index):
        self._play_style = self.play_style_combo.currentData() or "reveal"
        self._marker_color = self.marker_color_combo.currentData()
        self._reveal_color = self.reveal_color_combo.currentData()
        if self._playing:
            self._paint_smooth()
        else:
            self._redraw()

    def _series_color(self):
        return _role_color(QPalette.ColorRole.Highlight)

    def _marker_qcolor(self):
        if not isinstance(self._marker_color, QColor):
            return _role_color(QPalette.ColorRole.Accent)
        return self._marker_color

    def _revealed_qcolor(self):
        if not isinstance(self._reveal_color, QColor):
            return _role_color(QPalette.ColorRole.Highlight)
        return self._reveal_color

    def set_grid(self, enabled):
        self._grid = enabled
        self.grid_check.blockSignals(True)
        self.grid_check.setChecked(enabled)
        self.grid_check.blockSignals(False)
        self._redraw()

    def grid_enabled(self):
        return self._grid

    def save_png(self, path):
        widget = self.chart_stack.currentWidget()
        pixmap = widget.grab()
        if widget.isVisible() and not pixmap.isNull() and pixmap.width() >= 2 and pixmap.height() >= 2:
            pixmap.save(path, "PNG")
            return
        self._render_current_chart().save(path, "PNG")

    def image_of_current_graph(self):
        """Still image of the current graph type, using every captured row.

        Record playback is put back where it was. This is not live acquisition.
        """
        remembered = self._reveal
        was_playing = self._playing
        self._stop_timer()
        self._jump_slider_to_end()
        self._redraw()
        try:
            return self._render_current_chart()
        finally:
            count = 0 if self._dataset is None else len(self._dataset.rows)
            self._set_slider_quiet(min(remembered, count))
            self._redraw()
            if was_playing and count > 0:
                self._playing = True
                self.play_button.setEnabled(False)
                self.pause_button.setEnabled(True)
                self._timer.start(self._interval_ms())

    def _render_current_chart(self):
        if self._kind == "pie":
            return self._render_widget(self.donut)
        try:
            return self._render_plot()
        except Exception:
            return self._render_widget(self.plot)

    def _render_plot(self):
        from pyqtgraph.exporters import ImageExporter

        exporter = ImageExporter(self.plot.plotItem)
        if int(exporter.parameters()["width"]) < 2:
            exporter.parameters()["width"] = 640
        image = exporter.export(toBytes=True)
        if image is None or image.isNull() or image.width() < 2:
            raise RuntimeError("PyQtGraph did not produce a graph image.")
        return image

    def _render_widget(self, widget):
        width = widget.width()
        height = widget.height()
        if width < 320 or height < 240:
            width = max(width, 640)
            height = max(height, 360)
            widget.resize(width, height)
        image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(_role_color(QPalette.ColorRole.Base))
        widget.render(image)
        if image.isNull() or image.width() < 2:
            raise RuntimeError("The graph image was empty.")
        return image

    def _columns_changed(self):
        if self._dataset is None:
            return False
        signature = (
            tuple(self._dataset.headers),
            tuple(numeric_column_names(self._dataset.headers, self._dataset.rows)),
        )
        return signature != self._column_signature

    def _reload_controls(self):
        dataset = self._dataset
        if dataset is None:
            self._fill(self.x_combo, [])
            self._fill(self.y_combo, [])
            self._fill(self.hist_combo, [])
            self._fill(self.bar_category, [])
            self._fill(self.bar_value, [])
            self._fill(self.pie_category, [])
            self._fill(self.pie_value, [])
            self._fill(self.stats_column, [])
            self._column_signature = None
            return
        numbers = numeric_column_names(dataset.headers, dataset.rows)
        names = list(dataset.headers)
        self._fill(self.x_combo, numbers, dataset.view["x"])
        self._fill(self.y_combo, numbers, dataset.view["y"])
        self._fill(self.hist_combo, numbers, dataset.view["hist_column"])
        self._fill(self.bar_category, names, dataset.view["bar_category"])
        self._fill(self.bar_value, numbers, dataset.view["bar_value"])
        self._fill(self.pie_category, names, dataset.view["pie_category"])
        self._fill(self.pie_value, numbers, dataset.view["pie_value"])
        self._fill(self.stats_column, numbers, dataset.view["stats"])
        self._set_combo_text(self.bar_how, dataset.view["aggregation"])
        self._set_combo_text(self.pie_mode, dataset.view["pie_mode"])
        self.bin_spin.blockSignals(True)
        self.bin_spin.setValue(int(dataset.view["bins"]))
        self.bin_spin.blockSignals(False)
        self._show_optional_rows()
        self._column_signature = (tuple(dataset.headers), tuple(numbers))
        self._apply_saved_labels()

    def _fill(self, combo, names, selected=""):
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(names)
        if selected in names:
            combo.setCurrentText(selected)
        combo.blockSignals(False)

    def _set_combo_text(self, combo, text):
        combo.blockSignals(True)
        if text:
            combo.setCurrentText(text)
        combo.blockSignals(False)

    def _remember_from_combos(self):
        dataset = self._dataset
        if dataset is None:
            return
        view = dataset.view
        view["x"] = self.x_combo.currentText()
        view["y"] = self.y_combo.currentText()
        view["hist_column"] = self.hist_combo.currentText()
        view["bar_category"] = self.bar_category.currentText()
        view["bar_value"] = self.bar_value.currentText()
        view["aggregation"] = self.bar_how.currentText() or "mean"
        view["pie_category"] = self.pie_category.currentText()
        view["pie_mode"] = self.pie_mode.currentText() or "count"
        view["pie_value"] = self.pie_value.currentText()
        view["stats"] = self.stats_column.currentText()
        view["bins"] = self.bin_spin.value()

    def _apply_saved_labels(self):
        dataset = self._dataset
        if dataset is None:
            return
        self.title_edit.blockSignals(True)
        self.xlabel_edit.blockSignals(True)
        self.ylabel_edit.blockSignals(True)
        self.title_edit.setText(dataset.view["title"])
        self.xlabel_edit.setText(dataset.view["xlabel"])
        self.ylabel_edit.setText(dataset.view["ylabel"])
        self.title_edit.blockSignals(False)
        self.xlabel_edit.blockSignals(False)
        self.ylabel_edit.blockSignals(False)

    def _remember_text(self):
        if self._dataset is None:
            return
        view = self._dataset.view
        view["title"] = self.title_edit.text()
        view["xlabel"] = self.xlabel_edit.text()
        view["ylabel"] = self.ylabel_edit.text()
        view["title_auto"] = view["title"] == ""
        view["xlabel_auto"] = view["xlabel"] == ""
        view["ylabel_auto"] = view["ylabel"] == ""
        self._redraw()

    def _axis_changed(self, _text):
        self._remember_from_combos()
        self._redraw()
        self.fit_data()

    def _bins_changed(self, _value):
        self._remember_from_combos()
        self._redraw()
        self.fit_data()

    def _bar_how_changed(self, _text):
        self._remember_from_combos()
        self._show_optional_rows()
        self._redraw()
        self.fit_data()

    def _pie_mode_changed(self, _text):
        self._remember_from_combos()
        self._show_optional_rows()
        self._redraw()
        self.fit_data()

    def _set_row_visible(self, form, field, visible):
        label = form.labelForField(field)
        if label is not None:
            label.setVisible(visible)
        field.setVisible(visible)

    def _show_optional_rows(self):
        show_value = self.bar_how.currentText() != "count"
        self._set_row_visible(self.bar_form, self.bar_value, show_value)
        show_sum = self.pie_mode.currentText() != "count"
        self._set_row_visible(self.pie_form, self.pie_value, show_sum)

    def _stats_column_changed(self, _text):
        self._remember_from_combos()
        self._redraw_stats()

    def _grid_toggled(self, checked):
        self._grid = checked
        self._redraw()
        self.panel_changed.emit(self)

    def _show_kind_page(self):
        self.option_stack.setCurrentIndex(KIND_PAGE.get(self._kind, 0))
        axes = self._kind != "pie"
        self._set_row_visible(self.label_form, self.xlabel_edit, axes)
        self._set_row_visible(self.label_form, self.ylabel_edit, axes)
        self.grid_check.setVisible(axes)
        if self._kind == "pie":
            self.chart_stack.setCurrentWidget(self.donut)
        else:
            self.chart_stack.setCurrentWidget(self.plot)

    def _visible_rows(self):
        if self._dataset is None:
            return []
        limit = self.slider.value()
        return self._dataset.rows[:limit]

    def _suggest_labels(self, title, xlabel, ylabel):
        if self._dataset is None:
            return title, xlabel, ylabel
        view = self._dataset.view
        if view.get("title_auto", True):
            view["title"] = title
        if self._kind != "pie" and view.get("xlabel_auto", True):
            view["xlabel"] = xlabel
        if self._kind != "pie" and view.get("ylabel_auto", True):
            view["ylabel"] = ylabel
        self._set_edit(self.title_edit, view["title"])
        self._set_edit(self.xlabel_edit, view["xlabel"])
        self._set_edit(self.ylabel_edit, view["ylabel"])
        return view["title"], view["xlabel"], view["ylabel"]

    def _set_edit(self, edit, text):
        if edit.text() == text:
            return
        edit.blockSignals(True)
        edit.setText(text)
        edit.blockSignals(False)

    def apply_plot_palette(self):
        """Paint the plot with the desktop palette. No fixed black or white."""
        background = _role_color(QPalette.ColorRole.Window)
        ink = _role_color(QPalette.ColorRole.Text)
        series = _role_color(QPalette.ColorRole.Highlight)
        marker = _role_color(QPalette.ColorRole.Accent)
        self.plot.setBackground(background)
        for name in ("bottom", "left", "top", "right"):
            axis = self.plot.getAxis(name)
            axis.setPen(ink)
            axis.setTextPen(ink)
            label = getattr(axis, "label", None)
            label_text = getattr(label, "text", None)
            if isinstance(label_text, str) and label_text:
                label.setText(label_text, color=ink)
        title = self.plot.plotItem.titleLabel
        title_text = getattr(title, "text", None)
        if isinstance(title_text, str) and title_text:
            title.setText(title_text, color=ink)
        self.line_item.setPen(pg.mkPen(self._revealed_qcolor(), width=2))
        self.full_line_item.setPen(pg.mkPen(series, width=2))
        self.scatter_item.setBrush(pg.mkBrush(series))
        self.scatter_item.setPen(pg.mkPen(ink, width=1))
        self.bar_item.setOpts(brush=pg.mkBrush(series))
        self.hbar_item.setOpts(brush=pg.mkBrush(series))
        self.marker_item.setSize(self._marker_size)
        self.marker_item.setBrush(pg.mkBrush(self._marker_qcolor()))
        self.marker_item.setPen(pg.mkPen(ink, width=1))
        self.donut.update()

    def _redraw(self):
        self._show_kind_page()
        rows = self._visible_rows()
        self.line_item.setData([], [], stepMode=None, fillLevel=None)
        self.full_line_item.setData([], [], stepMode=None, fillLevel=None)
        self.full_line_item.setVisible(False)
        self.scatter_item.setData([], [])
        self.bar_item.setOpts(x=[], height=[], width=0.8, y=None, y0=None, x0=None, x1=None)
        self.hbar_item.setOpts(y=[], x0=[], width=[], height=0.6, x=None, y0=None, x1=None, y1=None)
        self.marker_item.setData([], [])
        self.plot.getAxis("bottom").setTicks(None)
        self.plot.getAxis("left").setTicks(None)
        self.line_item.setVisible(self._kind in LINE_KINDS)
        self.scatter_item.setVisible(self._kind == "scatter")
        self.bar_item.setVisible(self._kind in ("bar", "histogram"))
        self.hbar_item.setVisible(self._kind == "hbar")
        self.marker_item.setVisible(self._kind in XY_KINDS)

        if self._dataset is None:
            self.note_label.setText(
                "No rows on this graph yet. Next: press Import table on this graph, "
                "or use File → Load sample CSV. Other graphs keep their own rows."
            )
            self.donut.set_chart("", [], [], "No data set yet. Load or type some rows.")
            self._redraw_stats()
            self._update_playback_label()
            self.apply_plot_palette()
            return
        if not self._dataset.headers:
            self.note_label.setText(
                "This data set has no columns yet. Next: add one in Manual entry, "
                "or use File → Import table."
            )
            self.plot.setTitle("")
            self.donut.set_chart("", [], [], "No columns yet. Add a column next.")
            self._redraw_stats()
            self._update_playback_label()
            self.apply_plot_palette()
            return
        if not rows:
            self.note_label.setText(
                "No rows in view. Next: add or import rows, or move record playback off the start."
            )
            self.plot.setTitle(self.title_edit.text())
            self.donut.set_chart(self.title_edit.text(), [], [], "No rows in view.")
            self._redraw_stats()
            self._update_playback_label()
            self.apply_plot_palette()
            return

        headers = self._dataset.headers
        message = ""
        if self._kind in XY_KINDS:
            message = self._draw_xy(headers, rows, self._dataset.rows)
        elif self._kind == "histogram":
            message = self._draw_histogram(headers, rows)
        elif self._kind == "bar":
            message = self._draw_bars(headers, rows, horizontal=False)
        elif self._kind == "hbar":
            message = self._draw_bars(headers, rows, horizontal=True)
        else:
            message = self._draw_pie(headers, rows)

        shown = len(rows)
        total = len(self._dataset.rows)
        if shown != total:
            extra = f" Record playback is showing the first {shown} of {total} rows."
            message = (message + extra).strip()
        self.note_label.setText(message or "Showing every row in original order.")
        self._redraw_stats()
        self._update_playback_label()
        self.apply_plot_palette()

    def _draw_xy(self, headers, rows, full_rows=None):
        x_name = self.x_combo.currentText()
        y_name = self.y_combo.currentText()
        series = xy_series(headers, rows, x_name, y_name)
        prefix = {"area": "Area", "step": "Step"}.get(self._kind, "")
        title_text = f"{y_name} vs {x_name}"
        if prefix:
            title_text = f"{prefix}: {title_text}"
        title, xlabel, ylabel = self._suggest_labels(title_text, x_name, y_name)
        self.plot.setTitle(title)
        self.plot.setLabel("bottom", xlabel)
        self.plot.setLabel("left", ylabel)
        self.plot.showGrid(x=self._grid, y=self._grid, alpha=0.25)
        full_x = None
        full_y = None
        if self._play_style == "marker":
            source = full_rows if full_rows is not None else rows
            full = xy_series(headers, source, x_name, y_name)
            full_x = full.x_values
            full_y = full.y_values
        self._set_xy_points(series.x_values, series.y_values, full_x, full_y)
        return series.message

    def _set_xy_points(self, x_values, y_values, full_x=None, full_y=None):
        """Update the existing line, scatter, and marker. Do not create new items."""
        step = "right" if self._kind == "step" else None
        fill = 0 if self._kind == "area" else None
        revealed = self._revealed_qcolor()
        pen = pg.mkPen(revealed, width=2)
        brush = None
        if fill is not None:
            fill_color = QColor(revealed)
            fill_color.setAlpha(90)
            brush = pg.mkBrush(fill_color)
        show_full = (
            self._play_style == "marker"
            and full_x is not None
            and self._kind in LINE_KINDS
        )
        if show_full:
            self.full_line_item.setVisible(True)
            self.full_line_item.setData(
                full_x,
                full_y,
                pen=pg.mkPen(self._series_color(), width=2),
                stepMode=step,
                fillLevel=None,
            )
        else:
            self.full_line_item.setData([], [], stepMode=None, fillLevel=None)
            self.full_line_item.setVisible(False)
        if self._kind in LINE_KINDS:
            self.line_item.setVisible(True)
            self.line_item.setData(
                x_values,
                y_values,
                pen=pen,
                stepMode=step,
                fillLevel=fill,
                brush=brush,
            )
        else:
            self.line_item.setData([], [], stepMode=None, fillLevel=None)
            self.line_item.setVisible(False)
        if self._kind == "scatter":
            self.scatter_item.setVisible(True)
            if self._play_style == "marker" and full_x is not None:
                self.scatter_item.setData(full_x, full_y, brush=pg.mkBrush(self._series_color()))
            else:
                self.scatter_item.setData(x_values, y_values, brush=pg.mkBrush(revealed))
        else:
            self.scatter_item.setData([], [])
            self.scatter_item.setVisible(False)
        self.marker_item.setSize(self._marker_size)
        self.marker_item.setBrush(pg.mkBrush(self._marker_qcolor()))
        if x_values:
            self.marker_item.setData([x_values[-1]], [y_values[-1]])
        else:
            self.marker_item.setData([], [])

    def _draw_xy_moving(self, headers, rows, whole, frac):
        """Draw a continuous line or scatter, gliding toward the next valid point."""
        x_name = self.x_combo.currentText()
        y_name = self.y_combo.currentText()
        series = xy_series(headers, rows[:whole], x_name, y_name)
        xs = list(series.x_values)
        ys = list(series.y_values)
        if frac > 0 and whole < len(rows):
            nxt = xy_series(headers, [rows[whole]], x_name, y_name)
            if nxt.x_values:
                if xs:
                    xs.append(xs[-1] + (nxt.x_values[0] - xs[-1]) * frac)
                    ys.append(ys[-1] + (nxt.y_values[0] - ys[-1]) * frac)
                else:
                    xs.extend(nxt.x_values)
                    ys.extend(nxt.y_values)
        full_x = None
        full_y = None
        if self._play_style == "marker":
            full = xy_series(headers, rows, x_name, y_name)
            full_x = full.x_values
            full_y = full.y_values
        if whole != self._painted_whole:
            prefix = {"area": "Area", "step": "Step"}.get(self._kind, "")
            title_text = f"{y_name} vs {x_name}"
            if prefix:
                title_text = f"{prefix}: {title_text}"
            title, xlabel, ylabel = self._suggest_labels(title_text, x_name, y_name)
            self.plot.setTitle(title)
            self.plot.setLabel("bottom", xlabel)
            self.plot.setLabel("left", ylabel)
            self.plot.showGrid(x=self._grid, y=self._grid, alpha=0.25)
            total = len(rows)
            message = series.message
            if whole != total:
                extra = f" Record playback is showing the first {whole} of {total} rows."
                message = (message + extra).strip()
            self.note_label.setText(message or "Showing every row in original order.")
            self._painted_whole = whole
        self._set_xy_points(xs, ys, full_x, full_y)

    def _draw_histogram(self, headers, rows):
        name = self.hist_combo.currentText()
        values, blank, missing, text = numeric_series(headers, rows, name)
        centers, counts, width = histogram_bins(values, self.bin_spin.value())
        title, xlabel, ylabel = self._suggest_labels(
            f"Histogram of {name}",
            name,
            "count",
        )
        self.plot.setTitle(title)
        self.plot.setLabel("bottom", xlabel)
        self.plot.setLabel("left", ylabel)
        self.plot.showGrid(x=self._grid, y=self._grid, alpha=0.25)
        self.bar_item.setOpts(x=centers, height=counts, width=width or 0.8)
        return exclusion_message(blank, missing, text)

    def _draw_bars(self, headers, rows, horizontal=False):
        how = self.bar_how.currentText() or "mean"
        labels, numbers, message = category_aggregate(
            headers,
            rows,
            self.bar_category.currentText(),
            self.bar_value.currentText(),
            how,
        )
        title, xlabel, ylabel = self._suggest_labels(
            f"{how} of {self.bar_value.currentText() or 'rows'} by {self.bar_category.currentText()}",
            self.bar_category.currentText(),
            how,
        )
        self.plot.setTitle(title)
        self.plot.showGrid(x=self._grid, y=self._grid, alpha=0.25)
        spots = list(range(len(labels)))
        if horizontal:
            # BarGraphItem draws a horizontal bar when y is the category
            # and width is the length. No extra library is required.
            self.plot.setLabel("left", xlabel)
            self.plot.setLabel("bottom", ylabel)
            self.hbar_item.setVisible(True)
            self.bar_item.setVisible(False)
            self.hbar_item.setOpts(
                y=spots,
                x0=[0] * len(spots),
                width=list(numbers),
                height=0.6,
                x=None,
                y0=None,
                x1=None,
                y1=None,
            )
            if labels:
                self.plot.getAxis("left").setTicks([[(i, label) for i, label in enumerate(labels)]])
        else:
            self.plot.setLabel("bottom", xlabel)
            self.plot.setLabel("left", ylabel)
            self.bar_item.setVisible(True)
            self.hbar_item.setVisible(False)
            self.bar_item.setOpts(x=spots, height=numbers, width=0.7, y=None, y0=None, x0=None, x1=None)
            if labels:
                self.plot.getAxis("bottom").setTicks([[(i, label) for i, label in enumerate(labels)]])
        return message

    def _draw_pie(self, headers, rows):
        mode = self.pie_mode.currentText() or "count"
        labels, numbers, message = pie_values(
            headers,
            rows,
            self.pie_category.currentText(),
            mode,
            self.pie_value.currentText(),
        )
        title, _xlabel, _ylabel = self._suggest_labels(
            f"{mode} by {self.pie_category.currentText()}",
            "",
            "",
        )
        self.donut.set_chart(title, labels, numbers, message)
        return message

    def _redraw_stats(self):
        if self._dataset is None or not self.stats_column.currentText():
            self.stats_label.setText(
                "Stats appear after a numeric column has numbers. "
                "Sample standard deviation divides by n-1."
            )
            return
        name = self.stats_column.currentText()
        stats = column_stats(self._dataset.headers, self._dataset.rows, name)
        self.stats_label.setText(
            f"{name}: count {stats['count']}, missing {stats['missing']}, "
            f"min {format_stat(stats['min'])}, max {format_stat(stats['max'])}, "
            f"mean {format_stat(stats['mean'])}, median {format_stat(stats['median'])}, "
            f"sample stdev {format_stat(stats['sample_stdev'])} (divide by n-1)."
        )

    def _jump_slider_to_end(self):
        count = 0 if self._dataset is None else len(self._dataset.rows)
        self._painted_whole = -1
        self.slider.blockSignals(True)
        self.slider.setRange(0, count)
        self.slider.blockSignals(False)
        self._set_slider_quiet(count)

    def _set_slider_quiet(self, value):
        """Move the slider without asking _redraw to run."""
        count = 0 if self._dataset is None else len(self._dataset.rows)
        value = max(0, min(int(value), count))
        self.slider.blockSignals(True)
        self.slider.setValue(value)
        self.slider.blockSignals(False)
        self._reveal = float(value)

    def _stop_timer(self):
        self._timer.stop()
        self._playing = False
        self.play_button.setEnabled(True)
        self.pause_button.setEnabled(False)

    def _interval_ms(self):
        return PLAYBACK_FRAME_MS

    def _play(self):
        count = 0 if self._dataset is None else len(self._dataset.rows)
        if count == 0:
            self.playback_label.setText("Load rows before playing a recording.")
            return
        if self._reveal >= count - 0.001:
            self._painted_whole = -1
            self._set_slider_quiet(0)
            self._redraw()
        self._playing = True
        self.play_button.setEnabled(False)
        self.pause_button.setEnabled(True)
        self._timer.start(self._interval_ms())

    def _pause(self):
        if self._timer.isActive() or self._playing:
            self._stop_timer()
            self._update_playback_label()

    def _reset(self):
        self._stop_timer()
        self._painted_whole = -1
        self._set_slider_quiet(0)
        self._redraw()

    def _advance(self):
        """Move the drawing forward one small step, then return.

        The timer calls this. It must not sleep, and it must not build
        new plot items. Line and scatter glide between points. Bar,
        histogram, and pie update when another whole row is included.
        """
        if self._dataset is None:
            self._stop_timer()
            return
        count = len(self._dataset.rows)
        speed = float(self.speed_combo.currentData() or 1.0)
        step = PLAYBACK_ROWS_PER_SECOND * speed * (self._interval_ms() / 1000.0)
        self._reveal += step
        if self._reveal >= count:
            self._reveal = float(count)
            self._set_slider_quiet(count)
            self._stop_timer()
            self._painted_whole = -1
            self._redraw()
            return
        self.slider.blockSignals(True)
        self.slider.setValue(int(self._reveal))
        self.slider.blockSignals(False)
        self._paint_smooth()

    def _paint_smooth(self):
        """Refresh the current graph from _reveal without clearing it first."""
        if self._dataset is None:
            return
        headers = self._dataset.headers
        rows = self._dataset.rows
        whole = min(len(rows), int(self._reveal))
        frac = 0.0 if whole >= len(rows) else self._reveal - whole
        if self._kind in XY_KINDS:
            self._draw_xy_moving(headers, rows, whole, frac)
        elif whole != self._painted_whole:
            shown = rows[:whole]
            if self._kind == "histogram":
                message = self._draw_histogram(headers, shown)
            elif self._kind == "bar":
                message = self._draw_bars(headers, shown, horizontal=False)
            elif self._kind == "hbar":
                message = self._draw_bars(headers, shown, horizontal=True)
            else:
                message = self._draw_pie(headers, shown)
            total = len(rows)
            if whole != total:
                extra = f" Record playback is showing the first {whole} of {total} rows."
                message = (message + extra).strip()
            self.note_label.setText(message or "Showing every row in original order.")
            self._painted_whole = whole
        self._update_playback_label()

    def _speed_changed(self):
        if self._timer.isActive():
            self._timer.start(self._interval_ms())

    def _slider_moved(self, value):
        self._reveal = float(value)
        self._painted_whole = -1
        self._redraw()

    def _update_playback_label(self):
        count = 0 if self._dataset is None else len(self._dataset.rows)
        position = self.slider.value()
        if count == 0:
            self.playback_label.setText("No rows")
        elif self._playing:
            self.playback_label.setText(f"Playing {position} of {count}")
        elif position >= count:
            self.playback_label.setText(f"All {count} rows")
        else:
            self.playback_label.setText(f"Row {position} of {count}")


class GraphBoard(QWidget):
    """The comparison page: several GraphPanel widgets in a grid.

    add_panel is the function that creates one more graph. Two columns
    are used when this board is wide. Each panel keeps the DataSet and
    the QTimer it was given. Removing one panel does not touch the rest.
    """

    selection_changed = pyqtSignal()
    import_requested = pyqtSignal(object)
    remove_requested = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.setObjectName("graphBoard")
        self._panels = []
        self._selected = None
        self._next_number = 1
        self._columns = 2

        self._empty = QLabel(
            "No graphs yet. Press Add graph. Each graph keeps its own rows, "
            "its own type, and its own playback."
        )
        self._empty.setObjectName("emptyState")
        self._empty.setWordWrap(True)

        self._host = QWidget()
        self._grid = QGridLayout(self._host)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(12)
        self._grid.setVerticalSpacing(12)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setWidget(self._host)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._empty)
        layout.addWidget(self._scroll, stretch=1)
        self._reflow()

    def panels(self):
        return list(self._panels)

    def selected_panel(self):
        return self._selected

    def panel_for_tab(self, tab):
        for panel in self._panels:
            if panel.tab is tab:
                return panel
        return None

    def panel_for_dataset(self, dataset):
        for panel in self._panels:
            if panel.bound_dataset() is dataset:
                return panel
        return None

    def add_panel(self, name=None):
        """Add one independent graph panel and select it.

        The new panel does not copy another panel's rows. It starts
        empty. Its playback timer is its own QTimer.
        """
        if not name:
            name = f"Graph {self._next_number}"
        self._next_number += 1
        panel = GraphPanel(name)
        panel.import_requested.connect(self._on_import)
        panel.remove_requested.connect(self.remove_panel)
        panel.select_requested.connect(self.select_panel)
        panel.panel_changed.connect(self._on_panel_changed)
        self._panels.append(panel)
        self._columns = self._wanted_columns()
        self._reflow()
        self.select_panel(panel)
        return panel

    def remove_panel(self, panel):
        """Delete one panel. The other panels keep their rows and timers."""
        if panel not in self._panels:
            return
        self._panels.remove(panel)
        self.remove_requested.emit(panel)
        self._grid.removeWidget(panel)
        panel.hide()
        panel.deleteLater()
        if self._selected is panel:
            self._selected = None
            if self._panels:
                self.select_panel(self._panels[-1])
            else:
                self.selection_changed.emit()
        self._reflow()

    def select_panel(self, panel):
        if panel not in self._panels:
            return
        if panel is self._selected:
            return
        self._selected = panel
        for other in self._panels:
            other.set_selected(other is panel)
        self.selection_changed.emit()

    def apply_plot_palette(self):
        for panel in self._panels:
            panel.apply_plot_palette()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_columns()

    def showEvent(self, event):
        super().showEvent(event)
        self._fit_columns()

    def _wanted_columns(self):
        """Two across when the graph area is wide enough for both labels."""
        width = self._scroll.viewport().width()
        if width >= 760 and len(self._panels) >= 2:
            return 2
        return 1

    def _fit_columns(self):
        columns = self._wanted_columns()
        if columns != self._columns:
            self._columns = columns
            self._reflow()

    def _reflow(self):
        """Place panels with a grid layout. Two across when the board is wide."""
        while self._grid.count():
            self._grid.takeAt(0)
        for index, panel in enumerate(self._panels):
            row = index // self._columns
            column = index % self._columns
            self._grid.addWidget(panel, row, column)
        self._empty.setVisible(not self._panels)
        for column in range(self._columns):
            self._grid.setColumnStretch(column, 1)

    def _on_import(self, panel):
        self.select_panel(panel)
        self.import_requested.emit(panel)

    def _on_panel_changed(self, panel):
        if panel is self._selected:
            self.selection_changed.emit()
