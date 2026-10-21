Teach me how this PyGraphy program works. I am a student and I need to understand it and edit it myself.

Do not rewrite the project. Do not replace these files. Do not add a Google account, OAuth, or a cloud API. Do not invent functions that are not in the code I paste under this prompt. If you are not sure a function exists, say so. Explain the code that is already here.

## The four source files

`main.py` is the window. `PyGraphyWindow` builds the menus, the mode buttons, the tabs, and the signal connections.

`dataset.py` holds the rows. `DataSet` is one tab of records. `load_table` reads a file. `records_as_tsv` turns the active rows into tab-separated text.

`graph_view.py` draws the plot. `GraphPanel` owns the graph type, the playback slider, and `image_of_current_graph`. `DonutChart` paints the pie.

`serial_panel.py` talks to USB serial. `SerialPanel` owns the port list, the baud box, Connect, Disconnect, and the status line.

## Who owns each mode

The mode buttons are built in `PyGraphyWindow._build_mode_bar`. Their labels are Graph, Manual entry, and Microcontroller. Clicking one calls `PyGraphyWindow._set_mode`. That function only changes which page is visible. It does not call `replace_table` and it does not clear `dataset.rows`.

Graph mode shows `self.stack`. That stack has two pages: the workspace from `_build_workspace` (the tabs, the divider, the current plot, and record playback) and `HomePage` (All graph types). Startup shows the workspace with an empty table. It does not load `sample_data.csv`, and it does not read a hidden session file. File → Load sample CSV calls `_load_sample`. Clear table calls `_clear_table`, which calls `DataSet.clear_memory` and does not change the file on disk. Choosing Graph again shows whichever of those two pages was already open.

Manual entry mode shows the page from `_build_manual_page`. The column box is `column_name_edit`. The buttons call `_add_manual_column`, `_add_manual_row`, and `_delete_manual_row`. The editable grid is `manual_table`. `_bind_manual_view` points that grid at the active tab’s `RecordTableModel`, not at the sort proxy.

Microcontroller mode shows the page from `_build_serial_page`. That page contains one `SerialPanel` plus two buttons labeled “Copy graph” and “Copy table”. The serial controls (port, baud, Connect, Disconnect, status) live on `SerialPanel`, not on the graph page.

## Who owns manual editing

`_add_manual_column` reads the typed name and calls `DataSet.add_column`. That appends the name and a blank cell on every existing row. If no tab is open, `_manual_tab` creates a tab named Manual.

`_add_manual_row` calls `DataSet.add_blank_row`, which appends one empty row. If there is no column yet, it refuses.

A cell edit goes through `RecordTableModel.setData`, which calls `DataSet.set_cell`. The typed characters are stored as text. They are not converted to floats in the table. `dataChanged` is connected to `_on_manual_edited`, which tells `GraphPanel.note_rows_changed` to redraw.

Delete row calls `_delete_manual_row`, which calls `RecordTableModel.remove_row`, which calls `DataSet.delete_row` for that original row index.

The graph’s table is the other view of the same model. `DataSetTab` turns editing off with `NoEditTriggers`, and it sorts through `RowOrderProxy`. So the graph table stays read-only even though the model allows `setData`.

These rows stay in memory for the open tab. Closing the app does not write a hidden file. `closeEvent` only disconnects the serial port. A file is written only when I choose File → Export records as CSV, which calls `_export_csv` and `write_records_csv`.

## Who owns import and paste

File → Import table… calls `_import_table`, then `_load_imported_file`, then `load_table`. File → Paste table calls `_paste_table`, which reads `QApplication.clipboard().text()` and calls `load_delimited_text`.

`load_table` looks at the file suffix and nothing else:

- `.csv` calls `load_csv`, which uses the standard-library `csv` module.
- `.xlsx` calls `load_xlsx`, which uses openpyxl with `read_only=True` and `data_only=True`, then `book.close()`. A Google Sheets download saved as xlsx is just a local xlsx file. There is no Google login.
- `.ods` calls `load_ods`, which uses odfpy (`odf.opendocument.load`). That is a LibreOffice Calc file.
- Any other suffix raises `ValueError`.

All three readers finish in `_table_from_rows`. For a CSV, the first row of the file is the header and the cell text is kept (after stripping spaces). `load_xlsx` and `load_ods` skip leading blank rows, then treat the next row as the header. Numbers from those spreadsheets are stored as decimal text, so 21.0 becomes the string `21`. An xlsx formula is read as the value saved in the file (`data_only=True`); if no value was saved, the cell is blank. None of these functions save the workbook or write the source file.

`_place_loaded_table` decides where the rows go. `_choose_load_target` returns a new tab when no tab is open. If the active tab already has headers or rows, `_ask_load_target` asks: Into this data set, New data set, or Cancel. It does not silently replace a tab that already has rows. Open CSV and Load sample CSV still start a new tab when the home page is showing (`from_home_starts_new`). Import and paste do not use that shortcut. They follow the active tab.

Invalid X/Y pairs are not removed at import time. They stay in `dataset.rows` as text. When a line or scatter is drawn, `xy_series` drops a whole row if either side is not a number, and `exclusion_message` builds the sentence that starts with “Left out”.

## Who owns the two copy buttons

Both buttons are created in `_build_serial_page`. They are not live acquisition.

Copy graph calls `_copy_graph`. That calls `GraphPanel.image_of_current_graph`. That function remembers the playback slider, jumps to the last row so the picture includes every row captured so far, draws the current graph type (`self._kind`), then puts the slider back. The image goes on the clipboard with `setImage`. If the clipboard does not keep an image, `_copy_graph` shows the error and then calls the existing `_export_png` so I can still save a PNG through `GraphPanel.save_png`.

Copy table calls `_copy_table`. That calls `records_as_tsv`, which writes the header and `dataset.rows` in original row order as tab-separated text, then `setText`. It does not copy the sorted view. It does not copy a picture.

## Data flow, in plain words

Typed cells, a CSV, an xlsx, an ods, a pasted table, and serial lines all become lists of strings on one `DataSet`. A tab owns that object. `dataset.rows` stays in the order the rows arrived: file order, paste order, or serial order.

The graph table can sort. `RowOrderProxy.lessThan` compares the visible cells and reorders only that view. Manual entry shows the source model, so it stays in original order. The plot and record playback read `dataset.rows`, not the proxy. Playback walks a prefix of that list. `_reveal` in `GraphPanel` is how far the animation has moved, and `_visible_rows` still uses the slider when the graph is redrawn all at once.

Switching Line, Scatter, Bar, Histogram, or Pie calls `_choose_kind`, which stores the kind and calls `GraphPanel.set_kind`. It does not replace the `DataSet` and it does not delete rows. The same list is drawn again with the new graph type. A bad pair is skipped by `xy_series` for line and scatter, but the text remains in the table.

A serial line is different only in how it arrives. `SerialPanel._read_available` is connected to `readyRead`. The first complete line is emitted as `header_received` and handled by `_on_serial_header` (`DataSet.adopt_header`). Later lines are `row_received`, handled by `_on_serial_row` (`DataSet.append_row`). Those rows are the same `DataSet` the graph uses.

## Please explain these three things from the pasted code

1. Signals and slots. Use the real `connect` calls: the mode button `clicked` signal to `_set_mode`, `readyRead` to `_read_available`, `header_received` and `row_received` in `_connect_signals`, and `dataChanged` to `_on_manual_edited`. Tell me what “connect” means in one plain sentence, then show which function runs.

2. Why `readyRead` must return immediately. Look at `_read_available`. It copies the bytes that are already waiting, splits finished lines, and returns. It does not sleep. Explain what would freeze if that function waited.

3. Where I should edit a specific behavior, naming the function and the file:
   - Add a column: the Add column button, `_add_manual_column`, and `DataSet.add_column`.
   - Change the starting baud: `BAUD_RATES` and `baud_combo.setCurrentText("115200")` in `SerialPanel.__init__`. `connect_port` reads whatever the box says.
   - Change a graph color: the line pen `"#2563eb"` where `line_item` is created in `GraphPanel.__init__`. The scatter and bar brushes use that same blue. The last-point marker uses `"#f59e0b"`. Pie slices use the list `SLICE_COLORS` in `graph_view.py`.

After you explain, give me one small edit I can make myself, and say which function to change. Do not print a whole new project.

## What I will paste next

: under this prompt, paste the full text of these four files, in this order, each in its own code block:

1. `main.py`
2. `dataset.py`
3. `graph_view.py`
4. `serial_panel.py`

Paste the files from the PyGraphy folder you are running. Do not paste an older copy.
