# PyGraphy

A PyQt6 graphing application.

## Download

```bash
git clone https://github.com/Neotech3000/PyGraphy.git
cd PyGraphy
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
./.venv/bin/python main.py
```

The block above clones the project and starts it with `python main.py`. The next section installs a `pygraphy` command. The sample CSV does not open by itself.

## Install and launch

`pip install .` creates a `pygraphy` command inside the virtual environment. That command belongs to that copy of Python. It is not one program file that runs on Linux, macOS, and Windows. This folder does not contain a Windows `.exe` installer or a Mac `.app`. Those packages have to be built on Windows and on a Mac.

### Linux and macOS

```bash
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/pygraphy
```

### Windows

Use the `py` launcher in Command Prompt or PowerShell, from the project folder:

```bat
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\pygraphy.exe
```

### This Linux machine

```bash
cd . && ./.venv/bin/python -m pip install .
./.venv/bin/pygraphy
```

`./.venv/bin/python main.py` from the project folder still works.

### How to start it after install

Linux: `pygraphy.desktop` in this folder runs `./.venv/bin/pygraphy`. On another computer, change `Exec` and `Path` to that computer’s project folder before you open the file. You can also copy it to `~/.local/share/applications/`.

Windows: start PyGraphy by running `.\.venv\Scripts\pygraphy.exe` from the project folder. You can pin that program. A frozen Windows `.exe` is not built here. Build that package on Windows if you want one.

macOS: start PyGraphy from Terminal with `.venv/bin/pygraphy` after the install commands above. A Mac `.app` is not built here. Build that package on a Mac if you want one.

## Run

```bash
.venv/bin/pygraphy
```

Or, without the installed command:

```bash
.venv/bin/python main.py
```

## What the window does

Every launch opens an empty data table and an empty graph. The status bar says “No data set” and “0 rows”. The sample file stays closed until you choose File → Load sample CSV. **Clear table** sits on the data table, above the grid. File, Graph, and Help are the menus. All graph types offers Line, Scatter, Bar, Histogram, and Pie or donut. Each data-set tab keeps its own rows. The status bar shows the data-set name, the row count, and whether USB serial is connected. Closing the window does not write a session file.

Line, scatter, bar, and histogram use PyQtGraph. The pie is a donut drawn with `QPainter`, because `PyQt6.QtCharts` is not installed. The app plots one series.

## Sample file

`sample_data.csv` sits next to the Python files. Startup leaves it closed on purpose. `sample_csv_path()` in `dataset.py` finds it from the program, not from the shell’s current directory. File → Load sample CSV opens it. Clear table forgets the open tab in memory and does not change this file. The sample has `time_s`, `temperature_c`, `humidity_pct`, and `location`, plus one blank humidity cell and one `abc` temperature so every graph type has something to show or leave out.

## Live serial

The panel is labeled Live serial capture. It is separate from Record playback. The baud rate starts at 115200. A board should print a header line, then comma-separated rows, for example `millis,temperature` and then `1000,21.5`. Rows are appended to the active data-set tab. This copy has not been tested by opening `ttyACM0`.

## More documentation

- [docs/code_map.md](docs/code_map.md) — files, functions, and where to edit
- [docs/learning_notes.md](docs/learning_notes.md) — signals, the event loop, sorting, and n−1
- [docs/requirements_checklist.md](docs/requirements_checklist.md) — assignment items and what is unfinished
- [docs/presentation_guide.md](docs/presentation_guide.md) — a five-minute demo script
