# PyGraphy code map

Run the app with:

```bash
cd . && ./.venv/bin/python main.py
```

The window starts in `main()`. That function builds a `QApplication`, creates `PyGraphyWindow`, shows it, and calls `app.exec()` to start the event loop.

## Source files

| File | Purpose |
| --- | --- |
| `main.py` | Entry point, home page, menus, data-set tabs, read-only table, status bar, and the signal connections that join the other modules. |
| `dataset.py` | In-memory rows, CSV reading and writing, numeric parsing, aggregations, and statistics. Row order here is the order used by plots and playback. |
| `graph_view.py` | One graph at a time: PyQtGraph for line, scatter, bar, and histogram; `DonutChart` for pie. Also record playback. |
| `serial_panel.py` | Live USB serial capture with `QSerialPort`. This is not playback. |
| `sample_data.csv` | Bundled rows so every graph type works with no board attached. |

`requirements.txt` pins PyQt6 6.11.0 and PyQtGraph 0.14.0, plus numpy and colorama because PyQtGraph needs them. `pyproject.toml` names the same Python modules.

## Main classes and functions

### `main.py`

- `main` creates the application and the window.
- `PyGraphyWindow` is the `QMainWindow`. `_choose_kind` switches Line, Scatter, Bar, Histogram, or Pie or donut and shows the workspace. `_load_sample` and `_load_path` fill a tab from a CSV. `_on_serial_header` and `_on_serial_row` append live rows to the active tab. `_connect_signals` is the list of signal-to-slot wires.
- The window opens on the workspace with `sample_data.csv` already loaded. `HomePage` is the “All graph types” screen. It names that file and offers one button per graph type.
- `DataSetTab` is one closable tab: a `DataSet` plus a table.
- `RecordTableModel` is read-only. It reads `dataset.rows` and never reorders that list. `replaced` reloads the whole table. `added_row` inserts one serial row.
- `RowOrderProxy` sorts only what you see. `lessThan` compares two cells. Numbers compare as numbers. Other text compares in lowercase.

### `dataset.py`

- `sample_csv_path` returns the path to `sample_data.csv` beside this file.
- `parse_cell` labels one stored string as `"number"`, `"blank"`, `"missing"`, or `"text"`. The stored string is not replaced with a float.
- `load_csv` reads a file and returns headers, rows of strings, and a note. The file is opened for reading only.
- `write_records_csv` writes the active records in original order. The window refuses to write back onto the file that was loaded.
- `xy_series` builds one line or scatter series. If X or Y is not a number, that whole row is dropped.
- `numeric_series`, `histogram_bins`, and `category_aggregate` feed the histogram, bar, and pie.
- `pie_values` refuses a negative total and a zero total.
- `column_stats` returns count, missing, min, max, mean, median, and sample standard deviation. `sample_standard_deviation` divides by n−1. `median` sorts a copy.
- `DataSet` is one named tab. `replace_table` loads a CSV. `adopt_header` accepts a serial header. `append_row` adds one serial row. `rows` stays in file or arrival order.

### `graph_view.py`

- `GraphPanel` holds the column controls, the plot, the stats line, and record playback.
- `set_kind` chooses the view. `KIND_PAGE` maps line and scatter to the X/Y controls, histogram and bar and pie to their own controls.
- `show_dataset` points the panel at one tab and stops playback. `note_rows_changed` does the same after a serial row arrives.
- `_redraw` asks `dataset.py` for numbers from `dataset.rows[:slider]`. It updates the same plot items with `setData` or `setOpts`. It does not create a new line on every tick.
- `DonutChart.paintEvent` draws the pie and the hole. `_draw_pie` calls `pie_values` and then `set_chart`.
- `_play`, `_pause`, `_reset`, and `_advance` are record playback. `_interval_ms` is the timer delay.

### `serial_panel.py`

- `SerialPanel` lists ports, chooses a baud rate, and connects or disconnects.
- `refresh_ports` uses `QSerialPortInfo.availablePorts()`.
- `connect_port` opens the port for read and write and releases DTR so a typical board can leave reset.
- `readyRead` is connected to `_read_available`. That slot copies bytes already in Qt’s buffer, splits complete lines, and returns.
- `_handle_line` treats the first line as a header (`header_received`) and later lines as rows (`row_received`).
- `_failure_text` adds a dialout-group hint when the error is a permission error.

## Data flow

```text
CSV file                         USB serial text
    |                                  |
    | load_csv                         | readyRead
    v                                  v
headers + rows of text          _read_available
    |                                  |
    | DataSet.replace_table            | header line, then comma-separated rows
    v                                  v
DataSet.rows  <----------------  adopt_header / append_row
    |
    +--> RecordTableModel --> RowOrderProxy --> QTableView
    |         (original order)    (sorted view only)
    |
    +--> GraphPanel._redraw
    |         xy_series / histogram_bins / category_aggregate / pie_values
    |         --> PyQtGraph items or DonutChart
    |
    +--> column_stats --> stats label
    |
    +--> QTimer --> _advance --> same plot items, a little further along the rows
```

Sorting the table calls `RowOrderProxy.lessThan`. That compares cells for display. `DataSet.rows` is the list playback and the plot read.

A serial header that does not match the open tab sets `_serial_hold` in the window. Later rows are skipped until the header matches. Switching tabs or disconnecting clears that hold. Changing tabs calls `show_dataset`, which stops the playback timer.

Blank, missing (`na`, `n/a`, `null`, `none`, `nan`), and other non-numeric text stay in the table as typed. Plot helpers count them and build a sentence with `exclusion_message`. For a line or scatter plot, one bad side of a pair drops both X and Y.

## Where to change things

**Window title.** In `PyGraphyWindow.__init__` in `main.py`, change `self.setWindowTitle("PyGraphy")`. The large word on the home page is a separate label, `QLabel("PyGraphy")`, inside `HomePage`. `main()` also calls `app.setApplicationName("PyGraphy")`.

**Sample path.** Change `sample_csv_path()` in `dataset.py`. It returns `Path(__file__).resolve().parent / "sample_data.csv"`. `__file__` is `dataset.py`, so the CSV is found next to the source even if the shell’s current directory is somewhere else. Keep the file beside the modules, or change both the string and the file you ship.

**Graph type.** The five choices live in `GRAPH_KINDS` at the top of `main.py`. Startup calls `_open_bundled_file`, which loads `sample_data.csv` and shows the line view. `_choose_kind` stores the choice, checks the Graph menu, and calls `GraphPanel.set_kind`. A new kind also needs a branch in `GraphPanel._redraw` and, if it needs different controls, an entry in `KIND_PAGE`.

**Serial baud.** The choices are `BAUD_RATES` in `serial_panel.py`. The default is `self.baud_combo.setCurrentText("115200")`. `connect_port` reads whatever the combo shows and passes it to `setBaudRate`. The expected device text is a header line, then comma-separated rows, such as `millis,temperature` followed by `1000,21.5`.

**Playback timer.** `GraphPanel._interval_ms` in `graph_view.py` returns `PLAYBACK_FRAME_MS` (33). At 1x, `_advance` moves `PLAYBACK_ROWS_PER_SECOND` (2) rows each second, a fraction of a row per tick. The speeds in the combo are 0.5x, 1x, 2x, and 4x. `GraphPanel.__init__` creates the `QTimer` and connects `timeout` to `_advance`. `_play` starts the timer. `_advance` updates the existing line, scatter, or marker with `setData`. It does not sleep, and it does not create a new plot item.
