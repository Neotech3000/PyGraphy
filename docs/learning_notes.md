# Learning notes

These notes match the code in this folder. Run the window with:

```bash
cd . && ./.venv/bin/python main.py
```

## Signals and slots

A signal is a named event. A slot is the function that should run when the event happens. `connect` joins them.

`PyGraphyWindow._connect_signals` is the place to read the window’s wires. For example, `self.tabs.currentChanged.connect(self._tab_changed)` means “when the user picks another data-set tab, call `_tab_changed`.” `self.serial_panel.row_received.connect(self._on_serial_row)` means “when the serial panel has a full data row, append it.”

You do not call `_on_serial_row` from the serial port yourself. The panel emits `row_received` after it has copied a line. Qt then calls the connected function on the same event loop that paints the window.

Buttons use the same idea. Each home-page button’s `clicked` signal calls `_choose_kind` with one of `"line"`, `"scatter"`, `"bar"`, `"histogram"`, or `"pie"`.

## Layouts

Widgets sit in layouts, not at fixed pixel positions.

- `HomePage` uses a `QVBoxLayout` for the title and the empty-state sentence, and a `QGridLayout` for the five graph buttons.
- The workspace uses a `QVBoxLayout`: a header row (`QHBoxLayout`), a notice, a `QSplitter` with the tabs on the left and `GraphPanel` on the right, then record playback, then the serial panel.
- Graph controls use `QFormLayout`, so each label stays next to its combo box.
- `QStackedWidget` swaps the home page and the workspace, and inside the graph it swaps the PyQtGraph plot and the donut.

If the window gets narrower, the layouts reflow. A tiled window can clip long column titles. The full header is still the tooltip from `RecordTableModel.headerData`.

## The event loop

`main()` builds the application, shows the window, and then calls `app.exec()`. That call is the event loop. Until it returns, Qt waits for clicks, key presses, timers, and serial bytes, and it calls the matching slot.

Your slot must return. While it is running, the loop cannot paint or notice the next click. Record playback uses a `QTimer` for the same reason: `_advance` moves one row and returns, and the timer fires again later. Nothing in the app calls `time.sleep`.

## Why sorting the table does not change row order

`DataSet.rows` is the original list. CSV rows are stored there from top to bottom. Serial rows are appended at the end.

The table’s model is `RecordTableModel`. Its `data` method indexes that same list. The view does not use the model directly. It uses `RowOrderProxy`, and `setSortingEnabled(True)` lets a column header sort the proxy.

`RowOrderProxy.lessThan` decides which of two cells should appear first. It does not assign back into `dataset.rows`. The plot and the playback slider both read `dataset.rows`. After a sort, the vertical header can still show the original row number because `headerData` numbers the source row.

`median` also sorts a copy (`ordered = sorted(values)`). That copy is thrown away. The data set stays in file order.

## Why `readyRead` must return quickly

`SerialPanel` connects `readyRead` to `_read_available`. Qt emits `readyRead` when bytes are already sitting in the port’s buffer. The slot calls `readAll()`, turns those bytes into text, splits off any complete lines, emits `header_received` or `row_received`, and returns.

The first complete line after Connect is the header. Later lines are comma-separated values, such as a header `millis,temperature` and a row `1000,21.5`. The baud rate starts at 115200.

If `_read_available` waited in a loop until the next reading, the event loop would be stuck inside that function. The window would not repaint, and Play would not respond. The serial docstring at the top of `serial_panel.py` says the slot does not wait and does not sleep. An unfinished line stays in `self._buffer` until the next `readyRead` brings the newline.

Record playback is a different path. It never reads the port. It only walks rows that are already in the active `DataSet`.

## Sample standard deviation

`sample_standard_deviation` in `dataset.py` is the spread used on the stats line. The docstring names the convention: divide by n−1, not by n. That n−1 is Bessel’s correction. It estimates how spread out a larger population is when you only measured this sample.

The steps in the function are:

1. If there are fewer than two numbers, return `None`. The stats label shows an em dash, because a sample spread is undefined for one point.
2. Compute the mean.
3. Add up each `(value - mean) ** 2`.
4. Divide that sum by `count - 1`.
5. Take the square root.

`column_stats` calls this function and also reports count, missing, min, max, mean, and median. Missing includes blank cells, the words in `MISSING_WORDS` (`na`, `n/a`, `null`, `none`, `nan`), and any other text that is not a number. The graph label says “divide by n-1” so the convention is visible without opening the file.

## Exercise

Open `dataset.py` and find `sample_standard_deviation`. Do not change it.

In the app, use File → Load sample CSV and look at the stats line for `temperature_c`. The count is 11 because the cell `abc` is missing, not a number. With those 11 numbers, the function divides by 10, which is n−1.

Then, from the project folder, ask that function what it does with too few numbers:

```bash
cd . && ./.venv/bin/python -c "from dataset import sample_standard_deviation; print(sample_standard_deviation([21.5]))"
```

The print should be `None`. That is the `if count < 2` branch. One temperature is a real measurement, and it still has no sample standard deviation until a second number exists.
