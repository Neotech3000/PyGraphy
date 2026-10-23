"""Rules for reading rows into a data set.

These tests cover the number handling, the header naming, and the .ods
reader. They do not need a window.
"""

import math
import tempfile
import unittest
from pathlib import Path

import dataset
from dataset import (
    adopt_header_of,
    column_stats,
    histogram_bins,
    load_ods,
    numeric_column_names,
    numeric_series,
    parse_cell,
    unique_headers,
)


def _write_ods(path, rows):
    """Write a small .ods file. Each row is (text, row_repeat, cell_repeat)."""
    from odf.opendocument import OpenDocumentSpreadsheet
    from odf.table import Table, TableCell, TableRow
    from odf.text import P

    document = OpenDocumentSpreadsheet()
    sheet = Table(name="Sheet1")
    document.spreadsheet.addElement(sheet)
    for text, row_repeat, cell_repeat in rows:
        row = TableRow()
        if row_repeat != 1:
            row.setAttribute("numberrowsrepeated", str(row_repeat))
        cell = TableCell(valuetype="string")
        cell.setAttribute("numbercolumnsrepeated", str(cell_repeat))
        cell.addElement(P(text=text))
        row.addElement(cell)
        sheet.addElement(row)
    document.save(str(path))


class NonFiniteNumbers(unittest.TestCase):
    """A value that cannot be drawn is a missing value, not a number.

    "inf" used to be stored as a number. A graph then had an infinite
    axis range and the whole program stopped with an error.
    """

    def test_infinity_is_missing(self):
        for raw in ("inf", "+inf", "-inf", "Infinity", "infinity", "1e309", "-1e309"):
            with self.subTest(raw=raw):
                self.assertEqual(parse_cell(raw), ("missing", None))

    def test_signed_nan_is_missing(self):
        for raw in ("nan", "NaN", "+nan", "-nan"):
            with self.subTest(raw=raw):
                self.assertEqual(parse_cell(raw), ("missing", None))

    def test_ordinary_numbers_still_work(self):
        self.assertEqual(parse_cell("12.5"), ("number", 12.5))
        self.assertEqual(parse_cell("-3"), ("number", -3.0))
        self.assertEqual(parse_cell("  7  "), ("number", 7.0))

    def test_blank_and_text_are_unchanged(self):
        self.assertEqual(parse_cell("   "), ("blank", None))
        self.assertEqual(parse_cell("n/a"), ("missing", None))
        self.assertEqual(parse_cell("lab"), ("text", None))

    def test_a_column_of_infinity_has_no_numbers(self):
        headers = ["value"]
        rows = [["1.0"], ["inf"], ["3.0"]]
        values, blank, missing, text = numeric_series(headers, rows, "value")
        self.assertEqual(values, [1.0, 3.0])
        self.assertEqual(missing, 1)
        self.assertEqual(blank, 0)
        self.assertEqual(text, 0)

    def test_histogram_bins_survive_the_column(self):
        headers = ["value"]
        rows = [["1.0"], ["inf"], ["3.0"]]
        values, _blank, _missing, _text = numeric_series(headers, rows, "value")
        centers, counts, _width = histogram_bins(values, 10)
        self.assertEqual(len(centers), 10)
        self.assertEqual(sum(counts), 2)
        self.assertTrue(all(math.isfinite(center) for center in centers))

    def test_stats_stay_finite(self):
        headers = ["value"]
        rows = [["1.0"], ["inf"], ["3.0"]]
        stats = column_stats(headers, rows, "value")
        self.assertEqual(stats["count"], 2)
        self.assertEqual(stats["missing"], 1)
        for key in ("min", "max", "mean", "median", "sample_stdev"):
            with self.subTest(key=key):
                self.assertTrue(math.isfinite(stats[key]), f"{key} was {stats[key]}")

    def test_the_column_is_not_numeric_when_every_value_is_infinite(self):
        headers = ["value"]
        rows = [["inf"], ["-inf"]]
        self.assertEqual(numeric_column_names(headers, rows), [])


class HeaderNames(unittest.TestCase):
    """Two columns must never end up with the same name."""

    def test_a_name_that_is_already_used_gets_another_number(self):
        names, renamed = unique_headers(["a", "a_2", "a"])
        self.assertEqual(names, ["a", "a_2", "a_3"])
        self.assertTrue(renamed)
        self.assertEqual(len(set(names)), len(names))

    def test_a_repeated_name_gets_a_number(self):
        names, renamed = unique_headers(["a", "a", "a"])
        self.assertEqual(names, ["a", "a_2", "a_3"])
        self.assertTrue(renamed)

    def test_different_names_are_left_alone(self):
        names, renamed = unique_headers(["a", "b", "c"])
        self.assertEqual(names, ["a", "b", "c"])
        self.assertFalse(renamed)

    def test_a_blank_name_becomes_column(self):
        names, _renamed = unique_headers(["", "  ", "b"])
        self.assertEqual(names, ["column", "column_2", "b"])
        self.assertEqual(len(set(names)), 3)

    def test_a_serial_header_does_not_duplicate_an_existing_name(self):
        names = adopt_header_of(["a", "a_2", "a"])
        self.assertEqual(names, ["a", "a_2", "a_3"])
        self.assertEqual(len(set(names)), 3)


class OdsRepeatedRows(unittest.TestCase):
    """A repeated row is read as many rows as the file says.

    Very large repeats are still read as themselves, but the sheet is
    cut short at a limit and the note says so.
    """

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "sheet.ods"

    def test_a_small_repeat_is_read_exactly(self):
        _write_ods(self.path, [("head", 1, 1), ("value", 3, 1)])
        headers, rows, _note = load_ods(self.path)
        self.assertEqual(headers, ["head"])
        self.assertEqual(rows, [["value"], ["value"], ["value"]])

    def test_a_large_repeat_is_read_exactly(self):
        _write_ods(self.path, [("head", 1, 1), ("value", 500, 1)])
        headers, rows, _note = load_ods(self.path)
        self.assertEqual(headers, ["head"])
        self.assertEqual(len(rows), 500)

    def test_the_total_is_capped_and_the_note_says_so(self):
        _write_ods(self.path, [("head", 1, 1), ("value", dataset.ODS_MAX_ROWS + 50, 1)])
        _headers, rows, note = load_ods(self.path)
        # The limit counts every row read, and the header is one of them.
        self.assertEqual(len(rows), dataset.ODS_MAX_ROWS - 1)
        self.assertIn("left out", note)

    def test_an_empty_padding_row_is_skipped(self):
        _write_ods(self.path, [("head", 1, 1), ("", 1000, 1), ("value", 1, 1)])
        headers, rows, _note = load_ods(self.path)
        self.assertEqual(headers, ["head"])
        self.assertEqual(rows, [["value"]])

    def test_a_wide_row_is_capped_and_the_note_says_so(self):
        _write_ods(self.path, [("head", 1, 4), ("value", 1, dataset.ODS_MAX_COLUMNS + 20)])
        headers, _rows, note = load_ods(self.path)
        self.assertLessEqual(len(headers), dataset.ODS_MAX_COLUMNS)
        self.assertIn("left out", note)


if __name__ == "__main__":
    unittest.main()
