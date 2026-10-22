"""In-memory records for one data set.

Plots and record playback read ``rows`` from top to bottom. Sorting the
table uses a separate view, so it must not reorder this list.

``load_csv``, ``load_xlsx``, ``load_ods``, and ``load_delimited_text``
turn a file or a paste into lists of strings. They do not write the
source. Plot helpers parse those strings later and leave the stored
text alone.
"""

import csv
import io
import sys
from pathlib import Path


MISSING_WORDS = {"na", "n/a", "null", "none", "nan"}


def bundled_path(filename):
    """Find a file shipped with PyGraphy.

    Look next to this source file first. That is the project folder when
    you run ``python main.py``. After ``pip install .``, the same file is
    copied to ``share/pygraphy`` inside the virtual environment, and this
    function uses that copy when the file is not beside the source.
    """
    beside_source = Path(__file__).resolve().parent / filename
    if beside_source.is_file():
        return beside_source
    installed = Path(sys.prefix) / "share" / "pygraphy" / filename
    if installed.is_file():
        return installed
    return beside_source


def sample_csv_path():
    """Locate sample_data.csv from the program, not from the shell's folder.

    See ``bundled_path``. The file stays in the project folder. PyGraphy
    reads it only when you choose File → Load sample CSV.
    """
    return bundled_path("sample_data.csv")


def parse_cell(text):
    """Classify one CSV cell without changing the stored text.

    Returns ("number", float), ("blank", None), ("missing", None),
    or ("text", None).
    """
    raw = text.strip()
    if raw == "":
        return "blank", None
    if raw.lower() in MISSING_WORDS:
        return "missing", None
    try:
        return "number", float(raw)
    except ValueError:
        return "text", None


def _unique_headers(headers):
    seen = {}
    names = []
    renamed = False
    for header in headers:
        name = header.strip() or "column"
        seen[name] = seen.get(name, 0) + 1
        if seen[name] == 1:
            names.append(name)
        else:
            names.append(f"{name}_{seen[name]}")
            renamed = True
    return names, renamed


def _cell_to_text(value):
    """Store a spreadsheet value as text. The data set does not keep floats."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value != value:
            return "nan"
        if value.is_integer() and abs(value) < 10**15:
            return str(int(value))
        return format(value, ".12g")
    return str(value).strip()


def _trim_trailing_blanks(cells):
    """Drop empty cells at the end of a spreadsheet row.

    Excel and Calc often pad a row out to the sheet width. Those padding
    cells are not columns the user typed.
    """
    trimmed = list(cells)
    while trimmed and not str(trimmed[-1]).strip():
        trimmed.pop()
    return trimmed


def _table_from_rows(raw_rows, source_name, untouched):
    """Build headers and string rows. ``untouched`` says the source was not written."""
    if not raw_rows or not any(str(cell).strip() for cell in raw_rows[0]):
        raise ValueError("The table has no header row.")

    header_cells = [str(cell) for cell in raw_rows[0]]
    headers, renamed = _unique_headers(header_cells)
    width = len(headers)
    rows = []
    short_rows = 0
    long_rows = 0
    for raw in raw_rows[1:]:
        raw = [str(cell) for cell in raw]
        if not any(cell.strip() for cell in raw):
            continue
        if len(raw) < width:
            short_rows += 1
        elif len(raw) > width:
            long_rows += 1
        cells = []
        for index in range(width):
            cells.append(raw[index].strip() if index < len(raw) else "")
        rows.append(cells)

    note = (
        f"Loaded {len(rows)} rows and {len(headers)} columns from {source_name}. "
        f"The first row is the header. {untouched}"
    )
    if renamed:
        note += " Duplicate column names were made unique."
    if short_rows:
        note += f" {short_rows} row(s) were short, so the missing cells are blank."
    if long_rows:
        note += f" {long_rows} row(s) had extra cells, which were ignored."
    return headers, rows, note


def load_csv(path):
    """Read a CSV. The file is opened for reading only and is never written.

    Returns (headers, rows, note). Each row is a list of original strings.
    """
    path = Path(path)
    with path.open(newline="", encoding="utf-8-sig") as handle:
        raw_rows = list(csv.reader(handle))
    return _table_from_rows(raw_rows, path.name, "The file was not modified.")


def load_xlsx(path):
    """Read the first sheet of an .xlsx file. The workbook is never saved.

    ``data_only=True`` uses the values Excel or Google Sheets saved in the
    file. A formula with no saved value becomes a blank cell.
    """
    path = Path(path)
    try:
        import openpyxl
    except ImportError as error:
        raise ValueError("openpyxl is not installed, so .xlsx files cannot be read.") from error
    try:
        book = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except (OSError, ValueError) as error:
        raise ValueError(str(error)) from error
    except Exception as error:
        raise ValueError(str(error)) from error
    try:
        sheet = book.active
        if sheet is None:
            raise ValueError("The workbook has no sheet.")
        raw_rows = []
        for row in sheet.iter_rows(values_only=True):
            raw_rows.append(_trim_trailing_blanks([_cell_to_text(value) for value in row]))
    finally:
        book.close()
    while raw_rows and not any(cell.strip() for cell in raw_rows[0]):
        raw_rows.pop(0)
    return _table_from_rows(raw_rows, path.name, "The file was not modified.")


def _ods_cell_text(cell):
    value_type = cell.getAttribute("valuetype") or ""
    if value_type in ("float", "currency", "percentage"):
        raw = cell.getAttribute("value") or ""
        if raw:
            try:
                return _cell_to_text(float(raw))
            except ValueError:
                return raw.strip()
    if value_type == "boolean":
        raw = (cell.getAttribute("booleanvalue") or "").strip().lower()
        if raw == "true":
            return "TRUE"
        if raw == "false":
            return "FALSE"
    if value_type == "date":
        raw = cell.getAttribute("datevalue") or ""
        if raw:
            return raw.strip()
    if value_type == "time":
        raw = cell.getAttribute("timevalue") or ""
        if raw:
            return raw.strip()
    from odf.teletype import extractText

    return extractText(cell).strip()


def _ods_repeat(cell, attribute):
    raw = cell.getAttribute(attribute)
    if not raw:
        return 1
    try:
        return max(1, int(raw))
    except ValueError:
        return 1


def load_ods(path):
    """Read the first sheet of an .ods file. The file is never saved."""
    path = Path(path)
    try:
        from odf.opendocument import load
        from odf.table import CoveredTableCell, Table, TableCell, TableRow
    except ImportError as error:
        raise ValueError("odfpy is not installed, so .ods files cannot be read.") from error
    try:
        document = load(str(path))
    except (OSError, ValueError) as error:
        raise ValueError(str(error)) from error
    except Exception as error:
        raise ValueError(str(error)) from error

    sheets = document.spreadsheet.getElementsByType(Table)
    if not sheets:
        raise ValueError("The spreadsheet has no table.")
    sheet = sheets[0]
    row_tag = TableRow().qname
    cell_tag = TableCell().qname
    covered_tag = CoveredTableCell().qname
    raw_rows = []
    for node in sheet.childNodes:
        if getattr(node, "qname", None) != row_tag:
            continue
        pieces = []
        for child in node.childNodes:
            child_tag = getattr(child, "qname", None)
            if child_tag == covered_tag:
                pieces.append(("", _ods_repeat(child, "numbercolumnsrepeated")))
                continue
            if child_tag != cell_tag:
                continue
            text = _ods_cell_text(child)
            repeat = _ods_repeat(child, "numbercolumnsrepeated")
            pieces.append((text, repeat))
        while pieces and pieces[-1][0] == "":
            pieces.pop()
        cells = []
        for text, repeat in pieces:
            count = repeat
            if count > 256:
                count = 256
            cells.extend([text] * count)
        if not cells:
            continue
        row_repeat = _ods_repeat(node, "numberrowsrepeated")
        if row_repeat > 100:
            row_repeat = 100
        for _copy in range(row_repeat):
            raw_rows.append(list(cells))
    while raw_rows and not any(cell.strip() for cell in raw_rows[0]):
        raw_rows.pop(0)
    return _table_from_rows(raw_rows, path.name, "The file was not modified.")


def load_table(path):
    """Read a table. The suffix picks the reader. The source file is not written.

    .csv uses the standard-library csv module.
    .xlsx uses openpyxl (Excel, or a Google Sheets download).
    .ods uses odfpy (LibreOffice Calc).
    """
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return load_csv(path)
    if suffix == ".xlsx":
        return load_xlsx(path)
    if suffix == ".ods":
        return load_ods(path)
    extension = suffix or "no extension"
    raise ValueError(
        "Import table accepts .csv, .xlsx, and .ods files. "
        f"This file has {extension}."
    )


def load_delimited_text(text, source_name="pasted table"):
    """Read tab-separated cells copied from Calc, Excel, or Google Sheets.

    Returns (headers, rows, note). Nothing is written to a file.
    """
    if text is None or not str(text).strip():
        raise ValueError("The clipboard has no table text.")
    raw_rows = list(csv.reader(io.StringIO(str(text)), delimiter="\t"))
    return _table_from_rows(raw_rows, source_name, "Nothing was written to a file.")


def records_as_tsv(dataset):
    """Tab-separated text in original row order, for pasting into a spreadsheet."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter="\t", lineterminator="\n")
    if dataset.headers:
        writer.writerow(dataset.headers)
    writer.writerows(dataset.rows)
    return buffer.getvalue()


def write_records_csv(dataset, path):
    """Write the active records in original row order."""
    path = Path(path)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        if dataset.headers:
            writer.writerow(dataset.headers)
        writer.writerows(dataset.rows)


def numeric_column_names(headers, rows):
    """A column is numeric when at least one cell parses as a number.

    Blank and missing cells do not disqualify it. Words still show up here
    if the column also contains a number; plot functions then leave those
    cells out and say why.
    """
    names = []
    for index, name in enumerate(headers):
        for row in rows:
            kind, _value = parse_cell(row[index] if index < len(row) else "")
            if kind == "number":
                names.append(name)
                break
    return names


def _cell(headers, row, name):
    index = headers.index(name)
    if index >= len(row):
        return ""
    return row[index]


def exclusion_message(blank, missing, text):
    parts = []
    if blank:
        parts.append(f"{blank} blank")
    if missing:
        parts.append(f"{missing} missing")
    if text:
        parts.append(f"{text} not a number")
    if not parts:
        return ""
    return "Left out " + ", ".join(parts) + "."


class XYSeries:
    """Numbers for one line or scatter series, in original row order."""

    def __init__(self):
        self.x_values = []
        self.y_values = []
        self.left_out = 0
        self.message = ""


def xy_series(headers, rows, x_name, y_name):
    """Pair X and Y. If either cell is not a number, drop the whole row."""
    series = XYSeries()
    blank = missing = text = 0
    if x_name not in headers or y_name not in headers:
        series.message = "Choose both an X column and a Y column."
        return series
    for row in rows:
        x_kind, x_value = parse_cell(_cell(headers, row, x_name))
        y_kind, y_value = parse_cell(_cell(headers, row, y_name))
        if x_kind == "number" and y_kind == "number":
            series.x_values.append(x_value)
            series.y_values.append(y_value)
            continue
        series.left_out += 1
        kinds = {x_kind, y_kind} - {"number"}
        if "text" in kinds:
            text += 1
        elif "missing" in kinds:
            missing += 1
        elif "blank" in kinds:
            blank += 1
    series.message = exclusion_message(blank, missing, text)
    if series.left_out and series.message:
        series.message += " An invalid X/Y pair is dropped together."
    return series


def numeric_series(headers, rows, name):
    """Return (values, blank_count, missing_count, text_count) for one column."""
    values = []
    blank = missing = text = 0
    if name not in headers:
        return values, 0, 0, 0
    for row in rows:
        kind, value = parse_cell(_cell(headers, row, name))
        if kind == "number":
            values.append(value)
        elif kind == "blank":
            blank += 1
        elif kind == "missing":
            missing += 1
        else:
            text += 1
    return values, blank, missing, text


def histogram_bins(values, bin_count):
    """Equal-width bins. Returns (centers, counts, bar_width)."""
    if not values:
        return [], [], 0
    bin_count = max(1, int(bin_count))
    low = min(values)
    high = max(values)
    if low == high:
        return [low], [len(values)], 0.8
    width = (high - low) / bin_count
    counts = [0] * bin_count
    for value in values:
        index = int((value - low) / width)
        if index >= bin_count:
            index = bin_count - 1
        if index < 0:
            index = 0
        counts[index] += 1
    centers = [low + width * (index + 0.5) for index in range(bin_count)]
    return centers, counts, width * 0.9


def category_aggregate(headers, rows, category, value_name, aggregation):
    """Group rows by category. ``aggregation`` is count, sum, or mean.

    Category labels stay in the order they first appear, which follows
    the original file order rather than alphabetical order.
    Returns (labels, numbers, message).
    """
    if category not in headers:
        return [], [], "Choose a category column."
    if aggregation != "count" and value_name not in headers:
        return [], [], "Choose a value column."

    totals = {}
    counts = {}
    order = []
    blank = missing = text = 0
    for row in rows:
        label = _cell(headers, row, category).strip() or "(blank)"
        if label not in totals:
            totals[label] = 0.0
            counts[label] = 0
            order.append(label)
        if aggregation == "count":
            counts[label] += 1
            continue
        kind, number = parse_cell(_cell(headers, row, value_name))
        if kind != "number":
            if kind == "blank":
                blank += 1
            elif kind == "missing":
                missing += 1
            else:
                text += 1
            continue
        totals[label] += number
        counts[label] += 1

    labels = []
    numbers = []
    for label in order:
        if aggregation == "count":
            labels.append(label)
            numbers.append(float(counts[label]))
        elif counts[label] == 0:
            continue
        elif aggregation == "sum":
            labels.append(label)
            numbers.append(totals[label])
        else:
            labels.append(label)
            numbers.append(totals[label] / counts[label])
    message = exclusion_message(blank, missing, text)
    return labels, numbers, message


def pie_values(headers, rows, category, mode, value_name):
    """Category totals for a pie or donut. Negatives and a zero total are refused."""
    aggregation = "count" if mode == "count" else "sum"
    labels, numbers, message = category_aggregate(
        headers, rows, category, value_name, aggregation
    )
    if any(number < 0 for number in numbers):
        return [], [], (
            "Pie and donut charts cannot show a negative total. "
            "Remove the negative numbers or choose a bar chart."
        )
    if not numbers or sum(numbers) == 0:
        return [], [], "The total is 0, so there is no slice to draw."
    return labels, numbers, message


def median(values):
    """Median of a copy. The data set itself is not sorted."""
    if not values:
        return None
    ordered = sorted(values)
    count = len(ordered)
    middle = count // 2
    if count % 2 == 1:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def sample_standard_deviation(values):
    """Sample standard deviation: divide by n - 1, not by n.

    n - 1 (Bessel's correction) estimates spread in a larger population
    from this sample. The result is undefined when fewer than two numbers
    are present, so this returns None in that case.
    """
    count = len(values)
    if count < 2:
        return None
    mean = sum(values) / count
    squared = sum((value - mean) ** 2 for value in values)
    return (squared / (count - 1)) ** 0.5


def column_stats(headers, rows, name):
    """Stats for one numeric column. Missing covers blank, missing, and text cells."""
    values, blank, missing, text = numeric_series(headers, rows, name)
    unusable = blank + missing + text
    if not values:
        mean = None
        low = None
        high = None
    else:
        mean = sum(values) / len(values)
        low = min(values)
        high = max(values)
    return {
        "count": len(values),
        "missing": unusable,
        "min": low,
        "max": high,
        "mean": mean,
        "median": median(values),
        "sample_stdev": sample_standard_deviation(values),
    }


def format_stat(value):
    if value is None:
        return "—"
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text or "0"


class DataSet:
    """One named tab of records. ``rows`` stay in arrival / file order."""

    def __init__(self, name):
        self.name = name
        self.headers = []
        self.rows = []
        self.source_path = None
        self.view = {
            "x": "",
            "y": "",
            "hist_column": "",
            "bins": 10,
            "bar_category": "",
            "bar_value": "",
            "aggregation": "mean",
            "pie_category": "",
            "pie_mode": "count",
            "pie_value": "",
            "stats": "",
            "title": "",
            "xlabel": "",
            "ylabel": "",
            "title_auto": True,
            "xlabel_auto": True,
            "ylabel_auto": True,
        }

    def replace_table(self, headers, rows):
        self.headers = list(headers)
        self.rows = [list(row) for row in rows]
        self._prefer_default_columns()

    def clear_memory(self):
        """Drop this tab's rows and headers. Does not open or write a file."""
        self.headers = []
        self.rows = []
        self.view["x"] = ""
        self.view["y"] = ""
        self.view["hist_column"] = ""
        self.view["bar_category"] = ""
        self.view["bar_value"] = ""
        self.view["pie_category"] = ""
        self.view["pie_value"] = ""
        self.view["stats"] = ""
        self.view["title"] = ""
        self.view["xlabel"] = ""
        self.view["ylabel"] = ""
        self.view["bins"] = 10
        self.view["aggregation"] = "mean"
        self.view["pie_mode"] = "count"
        self.view["title_auto"] = True
        self.view["xlabel_auto"] = True
        self.view["ylabel_auto"] = True

    def adopt_header(self, cells):
        """Use a serial header line. Return an error message, or None."""
        headers = [cell.strip() for cell in cells]
        if not headers or not any(headers):
            return "The serial header line was empty."
        headers, _renamed = _unique_headers(headers)
        if not self.headers:
            self.headers = headers
            self._prefer_default_columns()
            return None
        if headers == self.headers:
            return None
        return (
            "The serial header does not match this data set: "
            + ", ".join(headers)
        )

    def append_row(self, cells):
        """Append one serial row of original text. Return an error, or None."""
        if not self.headers:
            return "This data set has no column headers yet."
        values = [cell.strip() for cell in cells]
        if len(values) != len(self.headers):
            return (
                f"Expected {len(self.headers)} values "
                f"({', '.join(self.headers)}), got {len(values)}."
            )
        self.rows.append(values)
        return None

    def add_column(self, name):
        """Append one column of blank cells. The name is made unique if needed."""
        raw = (name or "").strip() or "column"
        candidate = raw
        used = set(self.headers)
        if candidate in used:
            number = 2
            while f"{raw}_{number}" in used:
                number += 1
            candidate = f"{raw}_{number}"
        self.headers.append(candidate)
        for row in self.rows:
            row.append("")
        self._prefer_default_columns()
        return candidate

    def add_blank_row(self):
        """Append one empty row. Returns an error message, or None."""
        if not self.headers:
            return "Add a column name before adding a row."
        self.rows.append([""] * len(self.headers))
        return None

    def delete_row(self, index):
        """Remove one row by its original index. Returns an error message, or None."""
        if index < 0 or index >= len(self.rows):
            return "That row is not in this data set."
        del self.rows[index]
        return None

    def set_cell(self, row_index, column_index, text):
        """Store typed text in one cell. Numbers stay text until a graph parses them."""
        if row_index < 0 or row_index >= len(self.rows):
            return "That row is not in this data set."
        if column_index < 0 or column_index >= len(self.headers):
            return "That column is not in this data set."
        row = self.rows[row_index]
        while len(row) < len(self.headers):
            row.append("")
        row[column_index] = "" if text is None else str(text)
        return None

    def _prefer_default_columns(self):
        numbers = numeric_column_names(self.headers, self.rows)
        words = [name for name in self.headers if name not in numbers]
        measure = numbers[1] if len(numbers) > 1 else (numbers[0] if numbers else "")
        category = words[0] if words else (self.headers[-1] if self.headers else "")
        if not self.view["x"] and numbers:
            self.view["x"] = numbers[0]
        if not self.view["y"] and measure:
            self.view["y"] = measure
        if not self.view["hist_column"] and measure:
            self.view["hist_column"] = measure
        if not self.view["bar_category"] and category:
            self.view["bar_category"] = category
        if not self.view["bar_value"] and measure:
            self.view["bar_value"] = measure
        if not self.view["pie_category"] and category:
            self.view["pie_category"] = category
        if not self.view["pie_value"] and measure:
            self.view["pie_value"] = measure
        if not self.view["stats"] and measure:
            self.view["stats"] = measure
