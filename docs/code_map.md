# PyGraphy code map

Run the app with:

```bash
.venv/bin/python main.py
```

Or, after `pip install .`:

```bash
.venv/bin/pygraphy
```

The window starts in `main()`. That function builds a `QApplication`, applies the desktop theme, creates `PyGraphyWindow`, shows it, and calls `app.exec()` to start the event loop.

Startup does not load `sample_data.csv`. The graph board is empty until you add a graph or load a table.

## Source files

| File | Purpose |
| --- | --- |
| `main.py` | Entry point, menus, the three mode pages, data-set tabs, the read-only table, and the signal connections that join the other modules. |
| `appearance.py` | Desktop light/dark palette, the Omarchy theme file, and `load_style` for `style.qss`. |
| `dataset.py` | In-memory rows, CSV / xlsx / ods / paste reading, numeric parsing, aggregations, and statistics. Row order here is the order used by plots and playback. |
| `graph_view.py` | `GRAPH_KINDS`, one `GraphPanel` per graph, the board that holds several graphs (`GraphBoard`), and record playback. |
| `serial_panel.py` | Live USB serial capture with `QSerialPort`. This is not playback. |
| `sample_data.csv` | Bundled rows so every graph type works with no board attached. |
| `style.qss` | Fonts and spacing. Colors come from `palette()`, not from hex codes in this file. |

`requirements.txt` pins PyQt6, PyQtGraph, openpyxl, and odfpy, plus the libraries those packages need. `pyproject.toml` names the same Python modules and the `pygraphy` command.

## Main classes and functions

### `main.py`

- `main` creates the application, asks `appearance.py` to paint it, and shows `PyGraphyWindow`.
- `PyGraphyWindow` is the `QMainWindow`. Three modes (`_set_mode`) show Graph, Manual entry, or Microcontroller. `_choose_kind` sets the type on the selected graph. `_load_sample`, `_load_path`, `_import_into_panel`, and `_paste_table` fill that graph. `_on_serial_header` and `_on_serial_row` append live rows to it. `_connect_signals` is the list of signal-to-slot wires.
- `_add_manual_table` starts a blank table on the selected graph and stays on Manual entry. `_refresh_manual_switcher` rebuilds the Tables tabs from the open tables. `_manual_switcher_changed` switches which table the grid shows. `_screen_manual_tab` finds the table whose cells are in the grid right now, so a cell edit lands in that table and not the selected graph's.
- The window opens on the workspace with no rows and no graphs. `HomePage` is the "All graph types" screen. It offers one button per entry in `GRAPH_KINDS`.
- `DataSetTab` is one closable tab: a `DataSet` plus a table. The selected graph owns that tab.
- `RecordTableModel` reads `dataset.rows` and never reorders that list. Manual entry edits this model. The graph table turns editing off. `replaced` reloads the whole table. `added_row` inserts one new row.
- `RowOrderProxy` sorts only what you see. `lessThan` compares two cells. Numbers compare as numbers. Other text compares in lowercase.

### `dataset.py`

- `bundled_path` looks next to this file, then in the virtual environment's `share/pygraphy` folder. The shell's current directory is not used.
- `sample_csv_path` returns the path to `sample_data.csv` through `bundled_path`.
- `parse_cell` labels one stored string as `"number"`, `"blank"`, `"missing"`, or `"text"`. The stored string is not replaced with a float.
- `load_csv`, `load_xlsx`, and `load_ods` read a file and return headers, rows of strings, and a note. `load_table` picks the reader from the suffix. `load_delimited_text` reads a pasted table. None of them write the source.
- `write_records_csv` writes the active records in original order. The window refuses to write back onto the file that was loaded.
- `records_as_tsv` is the clipboard text for Copy table, in original order.
- `xy_series` builds one line or scatter series. If X or Y is not a number, that whole row is dropped.
- `numeric_series`, `histogram_bins`, and `category_aggregate` feed the histogram, bar, and pie. `category_aggregate` takes `count`, `sum`, or `mean`.
- `pie_values` refuses a negative total and a zero total.
- `column_stats` returns count, missing, min, max, mean, median, and sample standard deviation. `sample_standard_deviation` divides by n−1. `median` sorts a copy.
- `DataSet` is one named tab. `replace_table` loads rows. `clear_memory` drops them and does not touch a file. `adopt_header` accepts a serial header. `append_row` adds one serial row. `add_column`, `add_blank_row`, `delete_row`, and `set_cell` are manual entry. `rows` stays in file or arrival order.

### `graph_view.py`

- `GRAPH_KINDS` is the single list of graph types. `KIND_PAGE` says which control page each type uses. Area and step share the X/Y page with line and scatter. Horizontal bar shares the category page with bar.
- `GraphBoard` lays `GraphPanel` widgets in a grid, two across when the board is wide. `add_panel` creates an empty graph with its own `QTimer`. Removing one panel does not touch the others.
- `GraphPanel` holds the column controls, the plot, the stats line, and record playback for one graph.
- `set_kind` chooses the view. `show_dataset` points the panel at one tab and stops playback. `note_rows_changed` does the same after a row arrives or a cell is typed.
- `fit_data` sets that panel's axis range from its own rows. The Fit data button calls it. Auto-range stays off, so a later frame or another panel cannot move this view.
- `_redraw` asks `dataset.py` for numbers from `dataset.rows[:slider]`. It updates the same plot items with `setData` or `setOpts`. It does not create a new line on every tick. `_redraw_stats` uses the full column, not the slider prefix.
- `DonutChart.paintEvent` draws the pie and the hole. `_draw_pie` calls `pie_values` and then `set_chart`.
- `_play`, `_pause`, `_reset`, and `_advance` are record playback. `_interval_ms` is the timer delay. `_draw_xy_moving` glides the marker between points. "Reveal the line" and "Marker on the full line" are the two playback looks.

### `serial_panel.py`

- `SerialPanel` lists ports, chooses a baud rate, and connects or disconnects.
- `refresh_ports` uses `QSerialPortInfo.availablePorts()`. The names are whatever that computer exposes.
- `connect_port` opens the port for read and write and releases DTR so a typical board can leave reset.
- `readyRead` is connected to `_read_available`. That slot copies bytes already in Qt's buffer, splits complete lines, and returns.
- `_handle_line` treats the first line as a header (`header_received`) and later lines as rows (`row_received`).
- `_failure_text` adds a dialout-group hint when the error is a permission error.

### `appearance.py`

- `remember_desktop_palette` keeps the colors Qt had at startup.
- `apply_omarchy_palette` reads `colors.toml` from `omarchy_theme_dir()` when that file exists. The folder comes from `XDG_STATE_HOME` or the home directory's `.local/state`. It does not name one computer.
- `apply_system_color_scheme` and `sync_palette_to_color_scheme` follow the freedesktop light/dark setting on other machines.
- `load_style` reads `style.qss` through `bundled_path`.
- `_DesktopSchemeWatcher` and `_OmarchyThemeWatcher` call `_restyle_after_scheme_change` when the theme changes while the window is open. `main` keeps both objects on the window so they are not thrown away.

## Data flow

```text
CSV / xlsx / ods / paste          typed cells              USB serial text
        |                              |                          |
        | load_table / load_delimited  | set_cell                 | readyRead
        v                              v                          v
                          DataSet.rows  <--------------  adopt_header / append_row
                                  |
          +-----------------------+------------------------+
          |                       |                        |
          v                       v                        v
 RecordTableModel          GraphPanel._redraw         column_stats
 (original order)          xy_series / histogram /    (the whole column)
          |                category_aggregate /
          v                pie_values
   RowOrderProxy                  |
   (sorted view only)             v
          |                PyQtGraph items or DonutChart
          v
     QTableView              QTimer -> _advance
                             (a prefix of the same rows)
```

Sorting the table calls `RowOrderProxy.lessThan`. That compares cells for display. `DataSet.rows` is the list playback and the plot read.

A serial header that does not match the selected tab sets `_serial_hold` in the window. Later rows are skipped until the header matches. Switching graphs or disconnecting clears that hold.

Blank, missing (`na`, `n/a`, `null`, `none`, `nan`), and other non-numeric text stay in the table as typed. Plot helpers count them and build a sentence with `exclusion_message`. For a line or scatter plot, one bad side of a pair drops both X and Y.

Manual entry and the graph table share one `RecordTableModel`. The graph view puts a sort proxy in front and turns editing off. Manual entry uses the model directly, so a typed cell is a real row and the manual grid stays in original order. The Tables tabs pick which table the grid shows, so the model in the grid is the one of the table on screen, not always the selected graph's.

## Where to change things

**Window title.** In `PyGraphyWindow.__init__` in `main.py`, change `self.setWindowTitle("PyGraphy")`. The large word on the home page is a separate label, `QLabel("PyGraphy")`, inside `HomePage`. `main()` also calls `app.setApplicationName("PyGraphy")`.

**Sample path.** Change `sample_csv_path()` in `dataset.py`. It calls `bundled_path("sample_data.csv")`. That looks next to `dataset.py` first, then in the virtual environment's `share/pygraphy` folder after `pip install .`. The shell's current directory is not used. Startup does not open the file. File → Load sample CSV calls `_load_sample`.

**Graph type.** The eight choices live in `GRAPH_KINDS` at the top of `graph_view.py`. The home page, the Graph menu, and each panel's type box all read that tuple. `KIND_PAGE` must have one entry per kind, or that type has no controls. A new kind also needs a branch in `GraphPanel._redraw`. `_choose_kind` in `main.py` stores the choice on the selected panel only. Clear table calls `_clear_table`, which calls `DataSet.clear_memory` and does not write a file.

**Add a graph.** The button calls `PyGraphyWindow._add_graph`, which calls `GraphBoard.add_panel`. The new panel does not copy another panel's rows. Its playback timer is its own `QTimer`.

**Serial baud.** The choices are `BAUD_RATES` in `serial_panel.py`. The default is `self.baud_combo.setCurrentText("115200")`. `connect_port` reads whatever the combo shows and passes it to `setBaudRate`. The expected device text is a header line, then comma-separated rows, such as `millis,temperature` followed by `1000,21.5`.

**Playback timer.** `GraphPanel._interval_ms` in `graph_view.py` returns `PLAYBACK_FRAME_MS` (33). At 1x, `_advance` moves `PLAYBACK_ROWS_PER_SECOND` (2) rows each second, a fraction of a row per tick. The speeds in the combo are 0.5x, 1x, 2x, and 4x. `GraphPanel.__init__` creates the `QTimer` and connects `timeout` to `_advance`. `_play` starts the timer. `_advance` updates the existing line, scatter, or marker with `setData`. It does not sleep, and it does not create a new plot item. `show_dataset` stops that panel's timer.

**Colors.** Do not type a hex color into `style.qss`. Palette roles are filled in `appearance.py` (`palette_from_omarchy` on Omarchy, the desktop palette otherwise). Pie slices come from `slice_color` in `graph_view.py`, rotated from the highlight color. The playback marker and the revealed line can be set per graph from `LOOK_COLORS`. The "Theme" choice uses the desktop accent and highlight.

**A column, by hand.** Manual entry's Add column button calls `_add_manual_column`, which calls `DataSet.add_column`. Add row calls `DataSet.add_blank_row`. A cell edit calls `RecordTableModel.setData`, which calls `DataSet.set_cell`.

**A table, by hand.** Manual entry's Add table button calls `_add_manual_table`. That makes a new `DataSet`, adds one blank column and one blank row, and gives it a panel on the board. It does not copy another table's rows. The Tables tabs are a `QTabBar` named `manualTableTabs`, rebuilt by `_refresh_manual_switcher` from the open tables. `_manual_switcher_changed` selects the matching graph so the grid and the graph show the same table. `style.qss` styles the tabs under `QTabBar#manualTableTabs`.

**Fitting a graph to its rows.** The Fit data button on each panel calls `GraphPanel.fit_data` in `graph_view.py`. It reads that panel's own rows and sets the axis range, with `FIT_PADDING` space around the points. `_finite_span` keeps a flat series from collapsing the axis. `NEUTRAL_RANGE` is the fallback when the panel has no numbers.
