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

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

## Run

```bash
.venv/bin/python main.py
```

On this machine, from any folder:

```bash
cd . && ./.venv/bin/python main.py
```

## What the window does

The first screen says “No dataset loaded” and offers five views: Line, Scatter, Bar, Histogram, and Pie or donut. File, Graph, and Help are the menus. Each data-set tab keeps its own rows. The status bar shows the data-set name, the row count, and whether USB serial is connected.

Line, scatter, bar, and histogram use PyQtGraph. The pie is a donut drawn with `QPainter`, because `PyQt6.QtCharts` is not installed. The app plots one series.

## Sample file

`sample_data.csv` sits next to the Python files. `sample_csv_path()` in `dataset.py` finds it from this file’s folder, not from the shell’s current directory. File → Load sample CSV opens it. The sample has `time_s`, `temperature_c`, `humidity_pct`, and `location`, plus one blank humidity cell and one `abc` temperature so every graph type has something to show or leave out.

## Live serial

The panel is labeled Live serial capture. It is separate from Record playback. The baud rate starts at 115200. A board should print a header line, then comma-separated rows, for example `millis,temperature` and then `1000,21.5`. Rows are appended to the active data-set tab. This copy has not been tested by opening `ttyACM0`.

## More documentation

- [docs/code_map.md](docs/code_map.md) — files, functions, and where to edit
- [docs/learning_notes.md](docs/learning_notes.md) — signals, the event loop, sorting, and n−1
- [docs/requirements_checklist.md](docs/requirements_checklist.md) — assignment items and what is unfinished
- [docs/presentation_guide.md](docs/presentation_guide.md) — a five-minute demo script
