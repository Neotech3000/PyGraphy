"""A serial row must land in the data set the header named.

The device sends one header line and then rows. The rows belong to the
columns that header named. Switching graphs in the middle of a capture
must not send a row to a different data set.
"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

import appearance
from dataset import DataSet
from main import PyGraphyWindow


def setUpModule():
    global _app
    _app = QApplication.instance() or QApplication([])
    appearance.remember_desktop_palette(_app)
    appearance.load_style(_app)


def _settle():
    QApplication.instance().processEvents()


class SerialRowsLandInOneDataSet(unittest.TestCase):
    def setUp(self):
        self.window = PyGraphyWindow()
        self.addCleanup(self.window.close)
        self.window.show()
        _settle()

    def _two_tables(self):
        """Two data sets with the same number of columns."""
        window = self.window
        panel_a = window.graph_board.add_panel("A")
        tab_a = window._add_tab(DataSet("A"), panel_a)
        panel_a.show_dataset(tab_a.dataset)
        panel_b = window.graph_board.add_panel("B")
        tab_b = window._add_tab(DataSet("B"), panel_b)
        panel_b.show_dataset(tab_b.dataset)
        tab_a.dataset.replace_table(["millis", "temperature"], [["1", "2"]])
        tab_b.dataset.replace_table(["left", "right"], [["1", "2"]])
        window.graph_board.select_panel(panel_a)
        _settle()
        return tab_a, tab_b

    def test_a_row_goes_to_the_table_the_header_named(self):
        tab_a, tab_b = self._two_tables()
        self.window._on_serial_header(["millis", "temperature"])
        self.window._on_serial_row(["9", "8"])
        _settle()
        self.assertEqual(tab_a.dataset.rows, [["1", "2"], ["9", "8"]])
        self.assertEqual(tab_b.dataset.rows, [["1", "2"]])

    def test_a_row_does_not_land_in_another_data_set(self):
        tab_a, tab_b = self._two_tables()
        # The device names its columns for table A.
        self.window._on_serial_header(["millis", "temperature"])
        # A different header arrives, so the rows no longer fit table A.
        self.window._on_serial_header(["only_one"])
        # The user switches to table B with the tab widget.
        self.window.tabs.setCurrentIndex(self.window.tabs.indexOf(tab_b))
        _settle()
        # The next line is not table B's row, even though the widths match.
        self.window._on_serial_row(["9", "8"])
        _settle()
        self.assertEqual(tab_a.dataset.rows, [["1", "2"]])
        self.assertEqual(tab_b.dataset.rows, [["1", "2"]])

    def test_switching_graphs_does_not_send_a_row_to_the_wrong_table(self):
        tab_a, tab_b = self._two_tables()
        self.window._on_serial_header(["millis", "temperature"])
        # The user looks at table B and then goes back to table A.
        self.window.graph_board.select_panel(self.window.graph_board.panel_for_tab(tab_b))
        _settle()
        self.window.graph_board.select_panel(self.window.graph_board.panel_for_tab(tab_a))
        _settle()
        self.window._on_serial_row(["9", "8"])
        _settle()
        self.assertEqual(tab_a.dataset.rows, [["1", "2"], ["9", "8"]])
        self.assertEqual(tab_b.dataset.rows, [["1", "2"]])

    def test_an_empty_table_takes_the_device_header(self):
        window = self.window
        # The device names its columns for the table that is open now.
        window._on_serial_header(["millis", "temperature"])
        # The user picks a fresh graph that has no columns yet.
        panel = window.graph_board.add_panel("Fresh")
        tab = window._add_tab(DataSet("Fresh"), panel)
        panel.show_dataset(tab.dataset)
        window.graph_board.select_panel(panel)
        _settle()
        window._on_serial_row(["9", "8"])
        _settle()
        self.assertEqual(tab.dataset.headers, ["millis", "temperature"])
        self.assertEqual(tab.dataset.rows, [["9", "8"]])

    def test_a_disconnect_forgets_the_header(self):
        window = self.window
        window._on_serial_header(["millis", "temperature"])
        window._on_link_changed("Disconnected")
        self.assertIsNone(window._serial_header)


if __name__ == "__main__":
    unittest.main()
