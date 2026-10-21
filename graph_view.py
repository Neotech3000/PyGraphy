"""One graph series, plus record playback.

Line, scatter, bar, and histogram use PyQtGraph. PyQtGraph has no real pie
chart, and PyQt6.QtCharts is not installed here, so the donut is drawn
with QPainter in DonutChart.
"""

import pyqtgraph as pg
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QImage, QPainter, QPalette, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
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

KIND_PAGE = {"line": 0, "scatter": 0, "histogram": 1, "bar": 2, "pie": 3}
# About 30 frames a second. Each frame moves a fraction of a row, then returns.
PLAYBACK_FRAME_MS = 33
PLAYBACK_ROWS_PER_SECOND = 2.0


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
        background = _role_color(QPalette.ColorRole.Base)
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


class GraphPanel(QWidget):
    """Controls and one plot. Playback reuses the same plot items."""

    def __init__(self):
        super().__init__()
        self._dataset = None
        self._kind = "line"
        self._grid = True
        self._playing = False
        self._reveal = 0.0
        self._painted_whole = -1
        self._column_signature = None

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
            "No rows yet. Next: type them in Manual entry, load a table, "
            "or capture serial data in Microcontroller mode."
        )
        self.note_label.setWordWrap(True)

        self.plot = pg.PlotWidget()
        self.plot.setMinimumHeight(200)
        self.plot.showGrid(x=True, y=True, alpha=0.25)
        self.line_item = self.plot.plot([], [], pen=pg.mkPen(width=2))
        self.scatter_item = pg.ScatterPlotItem(size=9)
        self.bar_item = pg.BarGraphItem(x=[], height=[], width=0.8)
        self.marker_item = pg.ScatterPlotItem(size=16, symbol="o")
        self.plot.addItem(self.scatter_item)
        self.plot.addItem(self.bar_item)
        self.plot.addItem(self.marker_item)
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

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.option_stack)
        layout.addLayout(self.label_form)
        layout.addWidget(self.grid_check)
        layout.addWidget(self.note_label)
        layout.addWidget(self.chart_stack, stretch=1)
        layout.addLayout(stats_row)
        layout.addWidget(self.stats_label)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance)
        self._show_kind_page()
        self.apply_plot_palette()

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

    def bound_dataset(self):
        return self._dataset

    def show_dataset(self, dataset):
        """Switch tabs. Record playback stops so the old position is not reused."""
        self._dataset = dataset
        self._stop_timer()
        self._reload_controls()
        self._jump_slider_to_end()
        self._redraw()

    def note_rows_changed(self, headers_changed):
        self._stop_timer()
        if headers_changed or self._columns_changed():
            self._reload_controls()
        self._jump_slider_to_end()
        self._redraw()

    def set_kind(self, kind):
        self._kind = kind
        self._show_kind_page()
        self._redraw()

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

    def _bins_changed(self, _value):
        self._remember_from_combos()
        self._redraw()

    def _bar_how_changed(self, _text):
        self._remember_from_combos()
        self._show_optional_rows()
        self._redraw()

    def _pie_mode_changed(self, _text):
        self._remember_from_combos()
        self._show_optional_rows()
        self._redraw()

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
        background = _role_color(QPalette.ColorRole.Base)
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
        self.line_item.setPen(pg.mkPen(series, width=2))
        self.scatter_item.setBrush(pg.mkBrush(series))
        self.scatter_item.setPen(pg.mkPen(ink, width=1))
        self.bar_item.setOpts(brush=pg.mkBrush(series))
        self.marker_item.setBrush(pg.mkBrush(marker))
        self.marker_item.setPen(pg.mkPen(ink, width=1))
        self.donut.update()

    def _redraw(self):
        self._show_kind_page()
        rows = self._visible_rows()
        self.line_item.setData([], [])
        self.scatter_item.setData([], [])
        self.bar_item.setOpts(x=[], height=[], width=0.8)
        self.marker_item.setData([], [])
        self.plot.getAxis("bottom").setTicks(None)
        self.line_item.setVisible(self._kind == "line")
        self.scatter_item.setVisible(self._kind == "scatter")
        self.bar_item.setVisible(self._kind in ("bar", "histogram"))
        self.marker_item.setVisible(self._kind in ("line", "scatter"))

        if self._dataset is None:
            self.note_label.setText(
                "No data set yet. Next: use File → New data set, or File → Load sample CSV."
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
        if self._kind in ("line", "scatter"):
            message = self._draw_xy(headers, rows)
        elif self._kind == "histogram":
            message = self._draw_histogram(headers, rows)
        elif self._kind == "bar":
            message = self._draw_bars(headers, rows)
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

    def _draw_xy(self, headers, rows):
        x_name = self.x_combo.currentText()
        y_name = self.y_combo.currentText()
        series = xy_series(headers, rows, x_name, y_name)
        title, xlabel, ylabel = self._suggest_labels(
            f"{y_name} vs {x_name}",
            x_name,
            y_name,
        )
        self.plot.setTitle(title)
        self.plot.setLabel("bottom", xlabel)
        self.plot.setLabel("left", ylabel)
        self.plot.showGrid(x=self._grid, y=self._grid, alpha=0.25)
        self._set_xy_points(series.x_values, series.y_values)
        return series.message

    def _set_xy_points(self, x_values, y_values):
        """Update the existing line, scatter, and marker. Do not create new items."""
        if self._kind == "line":
            self.line_item.setData(x_values, y_values)
        else:
            self.scatter_item.setData(x_values, y_values)
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
        if whole != self._painted_whole:
            title, xlabel, ylabel = self._suggest_labels(
                f"{y_name} vs {x_name}",
                x_name,
                y_name,
            )
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
        self._set_xy_points(xs, ys)

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

    def _draw_bars(self, headers, rows):
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
        self.plot.setLabel("bottom", xlabel)
        self.plot.setLabel("left", ylabel)
        self.plot.showGrid(x=self._grid, y=self._grid, alpha=0.25)
        xs = list(range(len(labels)))
        self.bar_item.setOpts(x=xs, height=numbers, width=0.7)
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
        if self._kind in ("line", "scatter"):
            self._draw_xy_moving(headers, rows, whole, frac)
        elif whole != self._painted_whole:
            shown = rows[:whole]
            if self._kind == "histogram":
                message = self._draw_histogram(headers, shown)
            elif self._kind == "bar":
                message = self._draw_bars(headers, shown)
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
