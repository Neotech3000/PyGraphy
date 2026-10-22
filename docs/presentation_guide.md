# Five-minute demo

Practice once with the sample file before you present. You do not need a board.

```bash
./.venv/bin/python main.py
```

Have these four spots ready in the editor:

1. `load_csv` in `dataset.py`
2. `_choose_kind` in `main.py`
3. `_read_available` in `serial_panel.py`
4. `_advance` in `graph_view.py`

## What to show, in order

**0:00 — Empty start, then the local file.** The window opens with no rows. Point at Clear table and the empty grid. The status bar says “No data set” and “0 rows”. Then choose File → Load sample CSV. Point at the Sample tab, the table columns `time_s`, `temperature_c`, `humidity_pct`, and `location`, and the status bar row count. Drag the divider between the table and the graph. Mention File, Graph, and Help.

**0:30 — Where that file lives.** Say the path comes from `sample_csv_path()`, next to the program, not from whichever folder the terminal was in. The notice names `sample_data.csv` and says the file was not modified. All graph types is the screen with the five graph buttons.

**1:10 — Line and the left-out row.** The table still shows `abc` in `temperature_c`. The graph note says that row was left out and that a bad X and Y are dropped together. The line uses the original time order.

**1:40 — Sorting is only a view.** Click the `temperature_c` header. The rows on screen move. Say the plot did not reorder, because `RowOrderProxy` sorts the view and `DataSet.rows` stays put.

**2:10 — The other views.** Graph → Scatter, then Bar (location and mean of temperature), then Histogram. Then Pie or donut. The ring is lab 3, roof 4, field 5 when Values is count. Say this donut is `DonutChart` in `graph_view.py`, painted with `QPainter`, because QtCharts is not installed.

**3:00 — Stats.** Leave the stats column on `temperature_c`. Read count, missing, min, max, mean, median, and sample stdev. The label says “divide by n-1”. That is `sample_standard_deviation`.

**3:30 — Record playback.** Press Reset, then Play, then Pause. The marker glides along the original rows and the line stays on screen. Change speed. This timer is not the serial port.

**4:10 — Live serial, without connecting.** Press Microcontroller. Show the port list, baud 115200, Connect, and Disconnect. Read the example on the panel: a header line, then comma-separated rows (`millis,temperature`, then `1000,21.5`). If a port is listed, say you are not opening it in the demo.

**4:40 — The four functions.** Open them in the order below and read one sentence from each. Stop at five minutes even if a question starts. Take questions after.

## Functions to open

**`load_csv` (`dataset.py`).** “This opens the CSV for reading only. The first row becomes the headers. Every later row stays a list of strings. Floats are parsed later, when we plot.”

**`_choose_kind` (`main.py`).** “A home button or the Graph menu calls this with a short name like `'line'` or `'pie'`. It flips the stacked widget to the workspace and tells `GraphPanel.set_kind` which controls and which drawing function to use.”

**`_read_available` (`serial_panel.py`).** “`readyRead` means bytes are already here. This copies them, splits lines on newlines, and returns. The first line is the header. The next lines are the comma-separated rows. It does not sleep, so the window can still paint.”

**`_advance` (`graph_view.py`).** “The playback timer calls this about 30 times a second. Each call moves a fraction of a row and returns. The same plot items get new points, so the line stays continuous. Switching data sets stops the timer in `show_dataset`.”

## Design choices worth saying out loud

- PyQtGraph draws line, scatter, bar, and histogram inside the Qt window. Matplotlib was not added.
- A pie needs slices and a hole. PyQtGraph is a poor fit, and `PyQt6.QtCharts` does not import here, so `DonutChart.paintEvent` draws the ring.
- USB serial uses `QSerialPort` because that module imports. pyserial is not installed. `readyRead` stays on the GUI thread and returns immediately.
- The table and the graph disagree on purpose when you sort. The proxy is allowed to reorder cells on screen. The data set is not.
- The sample path uses `Path(__file__)`, so Load sample CSV works even if you started Python from another directory.
- Text and numbers are stored separately. The table shows what the file said. Plot code calls `parse_cell` on a copy of that text.
- One series keeps the controls small enough to read: one X, one Y, one category, one value.

## Likely questions

**Did you test a connected board?** No. The panel lists whatever ports the computer exposes. Connect was not used, so this demo does not claim live numbers from a device. A permission failure would mention the dialout group, in `_failure_text`, but that message was not proven against a real port.

**Why isn’t the pie a Qt chart?** `PyQt6.QtCharts` is not installed, so the import does not succeed. The assignment said to draw the donut ourselves in that case. `DonutChart` is that drawing.

**Why not matplotlib?** The charts that matplotlib would usually draw are PyQtGraph plots, which stay inside this window. A second plotting library was out of scope.

**Why does sorting not move the line?** `RowOrderProxy.lessThan` only answers “which cell comes first in the view?” `GraphPanel` reads `dataset.rows` from index 0 upward.

**What is n−1?** `sample_standard_deviation` divides the squared differences by `count - 1`. That is the sample convention, Bessel’s correction. With fewer than two numbers the function returns `None`.

**What does the board have to print?** A header line, then comma-separated rows, at 115200 baud unless you change the combo. Example: `millis,temperature` and then `1000,21.5`. The panel is for a generic ESP32 or Arduino, not one sensor board.

**Can I plot two columns at once?** Not in this version. One series is all `GraphPanel` draws.

**Will export destroy my CSV?** Export of records refuses the path you loaded. Any other existing file asks “Replace it?” before writing. `load_csv` never opens the source for writing.

**What if the serial header does not match the tab?** `DataSet.adopt_header` returns an error. The window sets a hold and skips following rows instead of mixing two shapes of data.

## Future improvements

- A second series, with a clear legend, once one series is easy to explain.
- `PyQt6.QtCharts` for the pie if that package is added later. Keep `DonutChart` as the fallback.
- A recorded serial session against a board you are allowed to open, including a permission-denied case for the dialout hint.
- Remembered column widths so long names such as `humidity_pct` stay readable when the window is tiled.
- Playback that can loop, and a marker on the bar and pie views as well as on the line and scatter.
- Optional numeric sort already exists; a “show original order” button would make the proxy easier to demonstrate.
