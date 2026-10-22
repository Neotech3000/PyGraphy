# Learning notes

These notes match the code in this folder. Run the window with:

```bash
.venv/bin/python main.py
```

## Signals and slots

A signal is a named event. A slot is the function that should run when the event happens. `connect` joins them.

`PyGraphyWindow._connect_signals` is the place to read the window's wires. For example, `self.tabs.currentChanged.connect(self._tab_changed)` means "when the user picks another data-set tab, call `_tab_changed`." `self.serial_panel.row_received.connect(self._on_serial_row)` means "when the serial panel has a full data row, append it." `self.graph_board.selection_changed.connect(self._on_selection_changed)` means "when another graph is selected, refresh the table and the status bar."

You do not call `_on_serial_row` from the serial port yourself. The panel emits `row_received` after it has copied a line. Qt then calls the connected function on the same event loop that paints the window.

Buttons use the same idea. Each mode button's `clicked` signal calls `_set_mode` with `"graph"`, `"manual"`, or `"serial"`. That only changes which page is visible. Each home-page button's `clicked` signal calls `_choose_kind` with one of the names in `GRAPH_KINDS`: `"line"`, `"scatter"`, `"area"`, `"step"`, `"bar"`, `"hbar"`, `"histogram"`, or `"pie"`.

A typed cell is another wire. Manual entry shows the source model, and `dataChanged` is connected to `_on_manual_edited`, which tells that graph to redraw. The Tables tabs are a `QTabBar`, and `currentChanged` is connected to `_manual_switcher_changed`. That slot picks which table the grid shows, so the graph that redraws is the one whose table is on screen.

## Layouts

Widgets sit in layouts, not at fixed pixel positions.

- The shell is a `QVBoxLayout`: the mode buttons, the notice, then a `QStackedWidget` for the three modes.
- Graph mode has its own stack. One page is `HomePage`. The other is the workspace.
- `HomePage` uses a `QVBoxLayout` for the title and the empty-state sentence, and a `QGridLayout` for the graph buttons, three across.
- The workspace uses a header row (`QHBoxLayout`) and a `QSplitter` named `tableGraphDivider`. The table is on the left. `GraphBoard` is on the right.
- `GraphBoard` puts each `GraphPanel` in a `QGridLayout`, two across when the area is wide. Playback, stats, and the plot live inside the panel, not under the whole window.
- Manual entry and Microcontroller are the other two mode pages. The serial panel is not under the graph.
- Graph controls use `QFormLayout`, so each label stays next to its combo box.
- Inside a panel, `QStackedWidget` swaps the control pages, and another stack swaps the PyQtGraph plot and the donut.

If the window gets narrower, the layouts reflow. A tiled window can clip long column titles. The full header is still the tooltip from `RecordTableModel.headerData`.

## The event loop

`main()` builds the application, shows the window, and then calls `app.exec()`. That call is the event loop. Until it returns, Qt waits for clicks, key presses, timers, and serial bytes, and it calls the matching slot.

Your slot must return. While it is running, the loop cannot paint or notice the next click. Record playback uses a `QTimer` for the same reason: `_advance` moves the line a fraction of a row and returns. The timer fires about 30 times a second. Nothing in the app calls `time.sleep`.

Each graph has its own timer. Playing on one panel does not move another panel. `show_dataset` stops the timer of the panel whose rows just changed.

## Why sorting the table does not change row order

`DataSet.rows` is the original list. CSV rows are stored there from top to bottom. Serial rows are appended at the end. Typed rows are appended there too.

The table's model is `RecordTableModel`. Its `data` method indexes that same list. The graph view does not use the model directly. It uses `RowOrderProxy`, and `setSortingEnabled(True)` lets a column header sort the proxy. Manual entry binds the model itself, so that grid stays in original order and accepts edits. With more than one table open, the model in that grid is the one of the table on screen, not always the selected graph's.

`RowOrderProxy.lessThan` decides which of two cells should appear first. It does not assign back into `dataset.rows`. The plot and the playback slider both read `dataset.rows`. After a sort, the vertical header can still show the original row number because `headerData` numbers the source row.

`median` also sorts a copy (`ordered = sorted(values)`). That copy is thrown away. The data set stays in file order.

The stats line is also the full column. Playback can draw only a prefix of the rows. `_redraw_stats` still calls `column_stats` on `dataset.rows`.

## Why `readyRead` must return quickly

`SerialPanel` connects `readyRead` to `_read_available`. Qt emits `readyRead` when bytes are already sitting in the port's buffer. The slot calls `readAll()`, turns those bytes into text, splits off any complete lines, emits `header_received` or `row_received`, and returns.

The first complete line after Connect is the header. Later lines are comma-separated values, such as a header `millis,temperature` and a row `1000,21.5`. The baud rate starts at 115200. The port is whichever one you pick in the list. The list is whatever the computer exposes.

If `_read_available` waited in a loop until the next reading, the event loop would be stuck inside that function. The window would not repaint, and Play would not respond. The serial docstring at the top of `serial_panel.py` says the slot does not wait and does not sleep. An unfinished line stays in `self._buffer` until the next `readyRead` brings the newline.

The window can also refuse a header that does not match the selected data set. `_on_serial_header` sets `_serial_hold`, and `_on_serial_row` skips lines until the header matches, you select another graph, or you disconnect. That hold is why two shapes of data are not mixed in one tab.

Record playback is a different path. It never reads the port. It only walks rows that are already in that graph's `DataSet`.

## Sample standard deviation

`sample_standard_deviation` in `dataset.py` is the spread used on the stats line. The docstring names the convention: divide by n−1, not by n. That n−1 is Bessel's correction. It estimates how spread out a larger population is when you only measured this sample.

The steps in the function are:

1. If there are fewer than two numbers, return `None`. The stats label shows an em dash, because a sample spread is undefined for one point.
2. Compute the mean.
3. Add up each `(value - mean) ** 2`.
4. Divide that sum by `count - 1`.
5. Take the square root.

`column_stats` calls this function and also reports count, missing, min, max, mean, and median. Missing includes blank cells, the words in `MISSING_WORDS` (`na`, `n/a`, `null`, `none`, `nan`), and any other text that is not a number. The graph label says "divide by n-1" so the convention is visible without opening the file.

## Exercise

Open `dataset.py` and find `sample_standard_deviation`. Do not change it.

In the app, use File → Load sample CSV and look at the stats line for `temperature_c`. The count is 11 because the cell `abc` is missing, not a number. With those 11 numbers, the function divides by 10, which is n−1.

Then, from the project folder, ask that function what it does with too few numbers:

```bash
.venv/bin/python -c "from dataset import sample_standard_deviation; print(sample_standard_deviation([21.5]))"
```

The print should be `None`. That is the `if count < 2` branch. One temperature is a real measurement, and it still has no sample standard deviation until a second number exists.
