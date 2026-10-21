# Requirements checklist

Each row is something the assignment asked for, the file that implements it, and a check a person can do by hand. Status is about this tree as it stands.

Run:

```bash
cd . && ./.venv/bin/python main.py
```

## Official PDF “Must include”

These four rows are the certificate PDF. The longer table under them is the rest of this project.

| Status | PDF requirement | Where | Manual check |
| --- | --- | --- | --- |
| Done | Local data file in the same folder as the program. The file is bundled and loaded on request. Startup is intentionally empty. The path comes from the application file, not the terminal’s folder. | `sample_data.csv`. `dataset.py`: `sample_csv_path`. `main.py`: `_load_sample` (File → Load sample CSV). Startup does not load a file. | Launch the command above. The table has no rows. Then File → Load sample CSV. The Sample tab shows `time_s`, `temperature_c`, `humidity_pct`, and `location`, including `lab` and `abc`. The notice names `sample_data.csv`. The status bar shows 12 rows. |
| Done | Navigational controls: tabs, a divider the user can drag, buttons, and menus. Actions stay labeled, not icon-only. | `main.py`: `QTabWidget` in `_build_workspace`, `QSplitter` named `tableGraphDivider`, mode buttons in `_build_mode_bar`, `_build_menus`, Clear table button | Drag the bar between the table and the graph. Both panes stay visible and change width. After File → Load sample CSV, the open tab is named Sample. Press Graph, Manual entry, and Microcontroller. Open File, Graph, and Help. |
| Done | Functional graphs, a chart, and a table, all using that local file. No extra plotting library. | `graph_view.py`: `_draw_xy`, `_draw_histogram`, `_draw_bars`, `_draw_pie`, `DonutChart`. `main.py`: `DataSetTab` | File → Load sample CSV, then use the Graph menu for Line, Scatter, Bar, Histogram, and Pie or donut. Each one shows `sample_data.csv`. The table on the left stays that same file. |
| Done | An animation that visualizes the data. It moves smoothly, reuses plot items, stays on the GUI timer, and does not call `time.sleep`. The line stays continuous. | `graph_view.py`: `_play`, `_advance`, `_paint_smooth`, `_draw_xy_moving`, `PLAYBACK_FRAME_MS` | Press Reset, then Play. The marker glides along the line for a few seconds. Pause still leaves the line on screen. The window still accepts clicks while it plays. |

## Rest of this project

| Status | Requirement | Where | Manual check |
| --- | --- | --- | --- |
| Done | Project virtual environment and pinned PyQt6, plus PyQtGraph for the charts that use it | `.venv`, `requirements.txt` | `./.venv/bin/python -c "import PyQt6, pyqtgraph"` from the project folder. |
| Done | Window titled PyGraphy. Every launch starts with no rows, including after a previous session. Nothing is written to a hidden session file. Status bar names the data set and the row count when a tab is open | `main.py`: `PyGraphyWindow` (startup does not load a file), `_clear_table`, `_build_status` | Launch twice. Both times the title is PyGraphy, the table has 0 rows, and the status bar says “No data set” and “0 rows”. The Clear table button is visible. |
| Done | Five graph choices: Line, Scatter, Bar, Histogram, Pie or donut. Choosing one shows that view | `main.py`: `GRAPH_KINDS`, `HomePage`, `_choose_kind`. `graph_view.py`: `GraphPanel.set_kind` | Click each home button, or use the Graph menu. The workspace label should read `View:` plus that name. |
| Done | Line, scatter, bar, and histogram drawn with PyQtGraph. One series | `graph_view.py`: `_draw_xy`, `_draw_histogram`, `_draw_bars` | Load the sample. Switch those four views. Each plot has a single color and one set of values. |
| Incomplete | Pie or donut via `PyQt6.QtCharts` | Not available. Fallback is `graph_view.py`: `DonutChart` | `import PyQt6.QtCharts` fails in this environment. Help → About PyGraphy says the donut is `QPainter`. Load the sample, choose Pie or donut, and confirm a ring with lab, roof, and field. |
| Done | Named data-set tabs, each with its own records. Add, load a CSV, and close | `main.py`: `_new_dataset`, `_add_tab`, `_load_path`, `_close_tab`. `dataset.py`: `DataSet` | File → New data set. Load the sample into a second tab. Close one tab. The other tab’s rows should still be there. |
| Done | Read-only table with headers and sorting. Sorting must not change plot or playback order | `main.py`: `RecordTableModel`, `RowOrderProxy`. `dataset.py`: `DataSet.rows` | Load the sample. Click the `time_s` header twice so large times are on top. The line graph should still run from 0 toward 11. The table cells are not editable. |
| Done | CSV file dialog, plus `sample_data.csv` resolved from the application file, not the shell’s current directory | `dataset.py`: `sample_csv_path`, `load_csv`. `main.py`: `_open_csv_dialog`, `_load_sample` | File → Load sample CSV. The notice should name `sample_data.csv`. `sample_csv_path` uses `Path(__file__).resolve().parent`. |
| Done | Arbitrary column names, numeric columns detected, original text kept separate from plotting numbers | `dataset.py`: `parse_cell`, `numeric_column_names`, `load_csv` | The sample header is `time_s,temperature_c,humidity_pct,location`. The table still shows `abc`. The line chart does not plot that cell as a number. |
| Done | Blank, missing, and non-numeric cells get a message and a count of rows left out. An invalid X/Y pair is dropped together | `dataset.py`: `xy_series`, `exclusion_message`, `MISSING_WORDS` | On the sample line chart the note says one row was left out because a value was not a number, and that an invalid X/Y pair is dropped together. Row 6 (time 5) has a blank humidity. Row 8 (time 7) has `abc`. |
| Done | Loading a CSV never modifies that file. Export asks before replacing a different file, and refuses the loaded path | `dataset.py`: `load_csv`, `write_records_csv`. `main.py`: `_export_csv`, `_confirm_overwrite` | Load the sample, then File → Export records as CSV and try to pick `sample_data.csv`. The warning should say PyGraphy will not modify the file you loaded. |
| Done | Line and scatter: X and Y selectors. Histogram: numeric column and bin count. Bar: category, value, and count, sum, or mean. Title, axis labels, grid | `graph_view.py`: the control pages and `_redraw`. `main.py`: `_set_grid` | After loading the sample, change Y, the histogram column, the bin count, and the bar aggregation. Toggle Graph → Show grid. Pie hides the axis labels and the grid checkbox because a pie has neither. |
| Done | Pie uses category counts or sums, rejects negatives, and explains a zero total | `dataset.py`: `pie_values`. `graph_view.py`: `_draw_pie` | Sample pie on count shows lab 3, roof 4, field 5. A column of zeros should say “The total is 0, so there is no slice to draw.” A negative total should say a pie cannot show a negative total. |
| Done | One series is all the plotters draw | `graph_view.py`: `GraphPanel`, `DonutChart` | There is no control for a second series. See the incomplete row below. |
| Done | Visible live serial panel: port list, baud default 115200, connect and disconnect. Separate from record playback | `serial_panel.py`: `SerialPanel`, `BAUD_RATES`. `main.py`: `_build_serial_page` | Press Microcontroller. “Live serial capture” is on that page. Baud shows 115200. Record playback stays on the Graph page. |
| Done | Device text is a header line, then comma-separated rows. Rows append to the active tab. No `time.sleep`. GUI thread is not blocked | `serial_panel.py`: `_read_available`, `_handle_line`. `main.py`: `_on_serial_header`, `_on_serial_row` | Read `_read_available`: it copies waiting bytes and returns. The panel text shows the example `millis,temperature` then `1000,21.5`. |
| Done | Prefer `PyQt6.QtSerialPort` when it imports. On failure, show the error and a dialout hint | `serial_panel.py`: `connect_port`, `_failure_text` | The module imports `QSerialPort` directly. pyserial is not in `requirements.txt`. A permission error string gains the dialout-group sentence. |
| Not tested | Hardware session against a real board, including the `ttyACM0` port that can appear in the list | `serial_panel.py` | Refresh ports. If `ttyACM0` is listed, leave it alone unless the board is yours. Connect was not used as a hardware test, so capture, baud match, and dialout behavior on that port are unverified. |
| Done | Record playback: `QTimer` at 33 ms, play, pause, reset, slider, speed. The marker glides. Plot items are reused. Stop when the data set changes. Named record playback. No `time.sleep` | `graph_view.py`: `_build_playback`, `_play`, `_advance`, `_paint_smooth`, `show_dataset` | Press Reset, then Play. The line grows smoothly in file order. Change tabs or load another set and the timer stops. The label says “Record playback”. |
| Done | Side-by-side graphs. Each panel has its own type, columns, rows, import, and playback timer. Startup stays empty. One panel’s timer does not move another panel. | `graph_view.py`: `GraphBoard.add_panel`, `GraphPanel`. `main.py`: Add graph, `_replace_panel_rows`, `_clear_table` | Press Add graph twice. Set the two Graph type boxes to different types. Import a table on one panel. The other panel’s rows stay as they were. Clear table clears only the selected panel. |
| Done | Stats for one numeric column: count, missing, min, max, mean, median, sample standard deviation with n−1 in the docstring | `dataset.py`: `column_stats`, `sample_standard_deviation`. `graph_view.py`: `_redraw_stats` | Stats for `temperature_c` on the sample leave out `abc`. The label ends with “divide by n-1”. The docstring on `sample_standard_deviation` says the same thing. |
| Done | Export the current graph as PNG and the active records as CSV. Confirm before overwriting | `main.py`: `_export_png`, `_export_csv`, `_confirm_overwrite`. `graph_view.py`: `save_png` | Export each, point at an existing file, and confirm the question “Replace it?” appears. Cancel should leave that file alone. |
| Done | Menus are only File, Graph, and Help. Empty state before any rows. Layouts, not fixed positions | `main.py`: `_build_menus`, `HomePage`, `_build_workspace` | The menu bar has those three menus. A new data set with no rows says “No columns yet” or “No rows yet”. |
| Not built | More than one series | — | Incomplete on purpose for this version: one series was the assigned scope, and the plot code never adds a second one. |
| Not built | Cloud upload, 3D plots, an expression evaluator, plugins, or hardware other than this serial panel | — | Those were out of scope. Nothing in the four Python modules implements them. |

## How to read the incomplete rows

The donut works. It is not a `QtCharts` series, because that module does not import, and the assignment said to use `QPainter` in that case.

The serial panel works as a control. A listed `ttyACM0` port was not opened, so this checklist does not claim a successful reading from that device.

One series is what the plots do today. A second line, a second bar group, or a second pie series is future work.
