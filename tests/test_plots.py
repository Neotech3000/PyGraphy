"""The graph must show the columns that were picked.

A serial header arrives before any numbers. The data set has no numeric
column at that point, so its X and Y choices are still empty. When the
rows arrive, the graph must pick two different columns instead of
falling back to the first one twice.
"""

import contextlib
import io
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

import appearance
from dataset import DataSet
from graph_view import GRAPH_KINDS, DonutChart
from main import PyGraphyWindow


def setUpModule():
    global _app
    _app = QApplication.instance() or QApplication([])
    appearance.remember_desktop_palette(_app)
    appearance.load_style(_app)


def _settle():
    QApplication.instance().processEvents()


class PickedColumns(unittest.TestCase):
    def setUp(self):
        self.window = PyGraphyWindow()
        self.addCleanup(self.window.close)
        self.window.show()
        _settle()

    def test_a_serial_capture_picks_two_different_columns(self):
        window = self.window
        window._on_serial_header(["millis", "temperature"])
        window._on_serial_row(["1000", "21.5"])
        window._on_serial_row(["2000", "22.0"])
        _settle()
        panel = window.graph_board.selected_panel()
        panel.set_kind("line")
        _settle()
        self.assertEqual(panel.x_combo.currentText(), "millis")
        self.assertEqual(panel.y_combo.currentText(), "temperature")
        self.assertEqual(panel.hist_combo.currentText(), "temperature")
        xs, ys = panel.line_item.getData()
        self.assertEqual(list(xs), [1000.0, 2000.0])
        self.assertEqual(list(ys), [21.5, 22.0])

    def test_a_typed_table_picks_two_different_columns(self):
        window = self.window
        window._add_manual_table()
        _settle()
        tab = window._current_tab()
        tab.dataset.add_column("time")
        tab.dataset.add_column("temp")
        tab.dataset.add_blank_row()
        tab.dataset.set_cell(0, 0, "1")
        tab.dataset.set_cell(0, 1, "5")
        window._refresh_panel(tab, False)
        _settle()
        panel = window.graph_board.selected_panel()
        panel.set_kind("line")
        _settle()
        self.assertNotEqual(panel.x_combo.currentText(), panel.y_combo.currentText())
        xs, ys = panel.line_item.getData()
        self.assertNotEqual(list(xs), list(ys))

    def test_a_chosen_column_is_kept(self):
        window = self.window
        window._on_serial_header(["millis", "temperature"])
        window._on_serial_row(["1000", "21.5"])
        _settle()
        panel = window.graph_board.selected_panel()
        panel.y_combo.setCurrentText("millis")
        _settle()
        # A later row must not move the choice back.
        window._on_serial_row(["2000", "22.0"])
        _settle()
        self.assertEqual(panel.y_combo.currentText(), "millis")


class ValuesThatCannotBeDrawn(unittest.TestCase):
    """A value like "inf" is a missing reading, not a number.

    An infinite value used to give the axis an infinite range and stop
    the whole program with an error.
    """

    def setUp(self):
        self.window = PyGraphyWindow()
        self.addCleanup(self.window.close)
        self.window.show()
        _settle()

    def test_no_graph_type_stops_on_an_infinite_value(self):
        window = self.window
        for kind, _label in GRAPH_KINDS:
            with self.subTest(kind=kind):
                panel = window.graph_board.add_panel(f"inf-{kind}")
                data = DataSet(f"inf-{kind}")
                window._add_tab(data, panel)
                data.replace_table(["k", "v"], [["a", "1.0"], ["b", "inf"]])
                panel.show_dataset(data)
                panel.set_kind(kind)
                _settle()

    def test_the_donut_paints_without_an_error(self):
        chart = DonutChart()
        self.addCleanup(chart.close)
        chart.resize(400, 300)
        chart.set_chart("Donut of value", ["a", "b"], [float("inf"), 1.0], "")
        chart.show()
        _settle()
        noise = io.StringIO()
        with contextlib.redirect_stderr(noise):
            chart.grab().toImage()
        self.assertNotIn("Traceback", noise.getvalue())
        self.assertNotIn("ValueError", noise.getvalue())


if __name__ == "__main__":
    unittest.main()
