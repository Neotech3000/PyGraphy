"""PyGraphy entry point.

Run this file with the project virtual environment:

    ./.venv/bin/python main.py

The window, menus, data-set tabs, and signal connections live here.
Records, graphs, and the serial port live in the sibling modules.
"""

import csv
import os
import re
import sys
from pathlib import Path

from PyQt6.QtCore import (
    QAbstractTableModel,
    QFileSystemWatcher,
    QModelIndex,
    QObject,
    Qt,
    QSortFilterProxyModel,
    QTimer,
    pyqtSlot,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QHeaderView,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtGui import QAction, QActionGroup, QColor, QPalette

from dataset import (
    DataSet,
    bundled_path,
    load_csv,
    load_delimited_text,
    load_table,
    parse_cell,
    records_as_tsv,
    sample_csv_path,
    write_records_csv,
)
from graph_view import GraphBoard
from serial_panel import SerialPanel


# Area fills a line down to zero. Step draws the same points as stairs.
# Horizontal bar uses PyQtGraph's BarGraphItem. Box plots and candlesticks
# are not listed: PyQtGraph does not draw those from one line or one bar
# item. Matplotlib and QtCharts are not used.
GRAPH_KINDS = (
    ("line", "Line"),
    ("scatter", "Scatter"),
    ("area", "Area"),
    ("step", "Step"),
    ("bar", "Bar"),
    ("hbar", "Horizontal bar"),
    ("histogram", "Histogram"),
    ("pie", "Pie or donut"),
)


class RecordTableModel(QAbstractTableModel):
    """Rows for one data set.

    The graph table sorts through RowOrderProxy and turns editing off.
    Manual entry edits this same model, so a typed cell is a real row.
    dataset.rows stay in the original order that plots and playback use.
    """

    def __init__(self, dataset):
        super().__init__()
        self.dataset = dataset

    def rowCount(self, parent=None):
        parent = QModelIndex() if parent is None else parent
        if parent.isValid():
            return 0
        return len(self.dataset.rows)

    def columnCount(self, parent=None):
        parent = QModelIndex() if parent is None else parent
        if parent.isValid():
            return 0
        return len(self.dataset.headers)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.ToolTipRole and orientation == Qt.Orientation.Horizontal:
            if 0 <= section < len(self.dataset.headers):
                return self.dataset.headers[section]
            return None
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            if 0 <= section < len(self.dataset.headers):
                return self.dataset.headers[section]
            return None
        return str(section + 1)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        if role not in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return None
        row = self.dataset.rows[index.row()]
        if index.column() >= len(row):
            return ""
        return row[index.column()]

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role != Qt.ItemDataRole.EditRole or not index.isValid():
            return False
        message = self.dataset.set_cell(index.row(), index.column(), value)
        if message:
            return False
        self.dataChanged.emit(
            index,
            index,
            [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole],
        )
        return True

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return (
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsEditable
        )

    def remove_row(self, row):
        if row < 0 or row >= len(self.dataset.rows):
            return False
        self.beginRemoveRows(QModelIndex(), row, row)
        self.dataset.delete_row(row)
        self.endRemoveRows()
        return True

    def replaced(self):
        self.beginResetModel()
        self.endResetModel()

    def added_row(self):
        row = len(self.dataset.rows) - 1
        self.beginInsertRows(QModelIndex(), row, row)
        self.endInsertRows()


class RowOrderProxy(QSortFilterProxyModel):
    """Sort the visible table. lessThan does not reorder the source rows."""

    def lessThan(self, left, right):
        left_text = str(left.data(Qt.ItemDataRole.DisplayRole) or "")
        right_text = str(right.data(Qt.ItemDataRole.DisplayRole) or "")
        left_kind, left_value = parse_cell(left_text)
        right_kind, right_value = parse_cell(right_text)
        if left_kind == "number" and right_kind == "number":
            return left_value < right_value
        return left_text.lower() < right_text.lower()


class DataSetTab(QWidget):
    """One tab: its own DataSet and a read-only sortable table."""

    def __init__(self, dataset):
        super().__init__()
        self.dataset = dataset
        self.model = RecordTableModel(dataset)
        self.proxy = RowOrderProxy(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setDynamicSortFilter(True)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        self.proxy.sort(-1)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(True)

        self.empty_label = QLabel(
            "No rows yet. Next: add a row in Manual entry, import a table, "
            "or capture rows in Microcontroller mode."
        )
        self.empty_label.setObjectName("emptyState")
        self.empty_label.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.empty_label)
        layout.addWidget(self.table, stretch=1)
        self.update_empty()

    def update_empty(self):
        if not self.dataset.headers:
            self.empty_label.setText(
                "No columns yet. Next: open Manual entry, type a column name, "
                "and press Add column. Or use File → Import table."
            )
            self.empty_label.setVisible(True)
        elif not self.dataset.rows:
            self.empty_label.setText(
                "No rows yet. Next: press Add row in Manual entry, use File → Import table, "
                "or capture rows in Microcontroller mode."
            )
            self.empty_label.setVisible(True)
        else:
            self.empty_label.setVisible(False)

    def refresh_table(self):
        self.model.replaced()
        self.update_empty()

    def note_appended(self):
        self.model.added_row()
        self.update_empty()


class HomePage(QWidget):
    """Pick a graph type for the selected comparison panel."""

    def __init__(self, choose_kind):
        super().__init__()
        self.setObjectName("homePage")
        title = QLabel("PyGraphy")
        title.setObjectName("homeTitle")
        self.intro = QLabel(
            "No rows yet. Next: press Add graph, or use File → Load sample CSV. "
            "sample_data.csv is in this program's folder. "
            "PyGraphy does not open it until you ask. "
            "Each graph keeps its own rows."
        )
        self.intro.setObjectName("emptyState")
        self.intro.setWordWrap(True)
        hint = QLabel(
            "The buttons above switch among Graph, Manual entry, and Microcontroller. "
            "Graph shows this page and the current plot."
        )
        hint.setObjectName("pageHint")
        hint.setWordWrap(True)

        choices = QGroupBox("Choose a graph")
        grid = QGridLayout(choices)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(16)
        for index, (kind, label) in enumerate(GRAPH_KINDS):
            button = QPushButton(label)
            button.setObjectName(f"choose-{kind}")
            button.setProperty("graphChoice", True)
            button.clicked.connect(lambda _checked=False, kind=kind: choose_kind(kind))
            grid.addWidget(button, index // 3, index % 3)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 20, 28, 24)
        layout.setSpacing(14)
        layout.addStretch(1)
        layout.addWidget(title)
        layout.addWidget(self.intro)
        layout.addWidget(hint)
        layout.addWidget(choices)
        layout.addStretch(2)


class PyGraphyWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PyGraphy")
        self.resize(1100, 700)
        self.setMinimumSize(860, 560)
        self._kind = "line"
        self._mode = "graph"
        self._serial_hold = False
        self._manual_model = None

        self.home = HomePage(self._choose_kind)
        self.workspace = self._build_workspace()
        self.stack = QStackedWidget()
        self.stack.addWidget(self.home)
        self.stack.addWidget(self.workspace)

        self.serial_panel = SerialPanel()
        self.manual_page = self._build_manual_page()
        self.serial_page = self._build_serial_page()
        self.mode_stack = QStackedWidget()
        self.mode_stack.addWidget(self.stack)
        self.mode_stack.addWidget(self.manual_page)
        self.mode_stack.addWidget(self.serial_page)

        self.notice = QLabel("")
        self.notice.setObjectName("noticeLabel")
        self.notice.setWordWrap(True)
        self.notice.setVisible(False)

        shell = QWidget()
        shell.setObjectName("appShell")
        shell.setAutoFillBackground(True)
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(16, 12, 16, 12)
        shell_layout.setSpacing(12)
        shell_layout.addWidget(self._build_mode_bar())
        shell_layout.addWidget(self.notice)
        shell_layout.addWidget(self.mode_stack, stretch=1)
        self.setCentralWidget(shell)

        self._build_menus()
        self._build_status()
        self._connect_signals()
        self._set_mode("graph")
        # Every launch starts empty. Nothing is read back from a previous session.
        self.stack.setCurrentWidget(self.workspace)
        self._sync_table_page()
        self._update_status()

    def _build_workspace(self):
        page = QWidget()
        page.setObjectName("workspacePage")
        header = QHBoxLayout()
        self.view_label = QLabel("No graph selected")
        self.view_label.setObjectName("sectionLabel")
        divider_hint = QLabel("Drag the divider between the table and the graphs.")
        divider_hint.setObjectName("pageHint")
        add_graph = QPushButton("Add graph")
        add_graph.setObjectName("addGraph")
        add_graph.clicked.connect(self._add_graph)
        home_button = QPushButton("All graph types")
        home_button.clicked.connect(self._show_home)
        header.addWidget(self.view_label)
        header.addStretch(1)
        header.addWidget(divider_hint)
        header.addWidget(add_graph)
        header.addWidget(home_button)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("dataSetTabs")
        self.tabs.setTabsClosable(True)
        self.tabs.setDocumentMode(True)

        self.empty_table = QTableView()
        self.empty_table.setObjectName("emptyDataTable")
        self.empty_table.setAlternatingRowColors(True)
        self.empty_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table_holder = QStackedWidget()
        self.table_holder.addWidget(self.empty_table)
        self.table_holder.addWidget(self.tabs)

        table_tools = QHBoxLayout()
        table_label = QLabel("Data table")
        table_label.setObjectName("sectionLabel")
        self.clear_button = QPushButton("Clear table")
        self.clear_button.setObjectName("clearTable")
        self.clear_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.clear_button.clicked.connect(self._clear_table)
        # The button used to sit after the stretch, on the splitter edge.
        # Dragging the divider then slid Clear table with the handle.
        # The stretch stays after the button so the button stays put.
        table_tools.addWidget(table_label)
        table_tools.addWidget(self.clear_button)
        table_tools.addStretch(1)

        table_side = QWidget()
        table_side.setObjectName("dataTableSide")
        table_column = QVBoxLayout(table_side)
        table_column.setContentsMargins(0, 0, 0, 0)
        table_column.setSpacing(8)
        table_column.addLayout(table_tools)
        table_column.addWidget(self.table_holder, stretch=1)

        self.graph_board = GraphBoard()
        self.graph_board.setMinimumWidth(320)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setObjectName("tableGraphDivider")
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(10)
        self.splitter.setOpaqueResize(True)
        table_side.setMinimumWidth(260)
        self.splitter.addWidget(table_side)
        self.splitter.addWidget(self.graph_board)
        self.splitter.setStretchFactor(0, 2)
        self.splitter.setStretchFactor(1, 3)
        self.splitter.setSizes([340, 760])
        handle = self.splitter.handle(1)
        handle.setToolTip("Drag this divider to resize the table and the graphs.")

        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)
        layout.addLayout(header)
        layout.addWidget(self.splitter, stretch=1)
        return page

    def _build_mode_bar(self):
        box = QGroupBox("Mode")
        box.setObjectName("modeBox")
        row = QHBoxLayout(box)
        row.setSpacing(12)
        self.mode_buttons = {}
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        for mode, text in (
            ("graph", "Graph"),
            ("manual", "Manual entry"),
            ("serial", "Microcontroller"),
        ):
            button = QPushButton(text)
            button.setObjectName(f"mode-{mode}")
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, mode=mode: self._set_mode(mode))
            self.mode_group.addButton(button)
            self.mode_buttons[mode] = button
            row.addWidget(button)
        row.addStretch(1)
        return box

    def _build_manual_page(self):
        page = QWidget()
        page.setObjectName("manualPage")
        self.manual_caption = QLabel(
            "Type a small table. The cells are the same data set the graph uses. "
            "They stay in memory for this tab. Closing PyGraphy does not write a hidden file. "
            "File → Export records as CSV saves them when you ask."
        )
        self.manual_caption.setObjectName("pageHint")
        self.manual_caption.setWordWrap(True)

        self.column_name_edit = QLineEdit()
        self.column_name_edit.setObjectName("columnName")
        self.column_name_edit.setPlaceholderText("Column name")
        add_table = QPushButton("Add table")
        add_table.setObjectName("addTable")
        add_table.clicked.connect(self._add_manual_table)
        add_column = QPushButton("Add column")
        add_column.setObjectName("addColumn")
        add_column.clicked.connect(self._add_manual_column)
        add_row = QPushButton("Add row")
        add_row.setObjectName("addRow")
        add_row.clicked.connect(self._add_manual_row)
        delete_row = QPushButton("Delete row")
        delete_row.setObjectName("deleteRow")
        delete_row.clicked.connect(self._delete_manual_row)
        tools = QGroupBox("Table tools")
        controls = QHBoxLayout(tools)
        controls.setSpacing(12)
        controls.addWidget(self.column_name_edit, stretch=1)
        controls.addWidget(add_table)
        controls.addWidget(add_column)
        controls.addWidget(add_row)
        controls.addWidget(delete_row)

        self.manual_table = QTableView()
        self.manual_table.setObjectName("manualTable")
        self.manual_table.setAlternatingRowColors(True)
        self.manual_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.manual_table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.AnyKeyPressed
        )
        header = self.manual_table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.manual_table.verticalHeader().setVisible(True)

        self.manual_empty = QLabel(
            "No data set is open. Next: press Add table, then type a column name "
            "and press Add column."
        )
        self.manual_empty.setObjectName("emptyState")
        self.manual_empty.setWordWrap(True)

        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(14)
        layout.addWidget(self.manual_caption)
        layout.addWidget(tools)
        layout.addWidget(self.manual_empty)
        layout.addWidget(self.manual_table, stretch=1)
        return page

    def _build_serial_page(self):
        page = QWidget()
        page.setObjectName("serialPage")
        copy_box = QGroupBox("Copy what you have so far")
        copy_note = QLabel(
            "Copy graph puts a PNG of the current graph type on the clipboard, "
            "using the rows captured so far. This is not live acquisition. "
            "Copy table puts those same rows on the clipboard as tab-separated text."
        )
        copy_note.setObjectName("pageHint")
        copy_note.setWordWrap(True)
        copy_graph = QPushButton("Copy graph")
        copy_graph.setObjectName("copyGraph")
        copy_graph.clicked.connect(self._copy_graph)
        copy_table = QPushButton("Copy table")
        copy_table.setObjectName("copyTable")
        copy_table.clicked.connect(self._copy_table)
        copies = QHBoxLayout()
        copies.setSpacing(12)
        copies.addWidget(copy_graph)
        copies.addWidget(copy_table)
        copies.addStretch(1)
        copy_layout = QVBoxLayout(copy_box)
        copy_layout.setSpacing(12)
        copy_layout.addWidget(copy_note)
        copy_layout.addLayout(copies)

        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(16)
        layout.addWidget(self.serial_panel)
        layout.addWidget(copy_box)
        layout.addStretch(1)
        return page

    def _set_mode(self, mode):
        """Show one page. This does not replace or delete the active tab's rows."""
        self._mode = mode
        pages = {
            "graph": self.stack,
            "manual": self.manual_page,
            "serial": self.serial_page,
        }
        self.mode_stack.setCurrentWidget(pages[mode])
        if mode == "manual":
            self._bind_manual_view()
        for key, button in self.mode_buttons.items():
            button.blockSignals(True)
            button.setChecked(key == mode)
            button.blockSignals(False)

    def _build_menus(self):
        file_menu = self.menuBar().addMenu("File")
        graph_menu = self.menuBar().addMenu("Graph")
        help_menu = self.menuBar().addMenu("Help")

        new_action = QAction("New data set", self)
        new_action.setShortcut("Ctrl+N")
        new_action.triggered.connect(self._new_dataset)
        open_action = QAction("Open CSV…", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self._open_csv_dialog)
        import_action = QAction("Import table…", self)
        import_action.triggered.connect(self._import_table)
        paste_action = QAction("Paste table", self)
        paste_action.triggered.connect(self._paste_table)
        sample_action = QAction("Load sample CSV", self)
        sample_action.triggered.connect(self._load_sample)
        export_png = QAction("Export graph as PNG…", self)
        export_png.triggered.connect(self._export_png)
        export_csv = QAction("Export records as CSV…", self)
        export_csv.triggered.connect(self._export_csv)
        close_action = QAction("Close data set", self)
        close_action.triggered.connect(self._close_current_tab)
        quit_action = QAction("Quit", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)

        for action in (
            new_action,
            open_action,
            import_action,
            paste_action,
            sample_action,
            export_png,
            export_csv,
            close_action,
            quit_action,
        ):
            file_menu.addAction(action)
            if action in (sample_action, export_csv, close_action):
                file_menu.addSeparator()

        self.kind_actions = {}
        kind_group = QActionGroup(self)
        kind_group.setExclusive(True)
        for kind, label in GRAPH_KINDS:
            action = QAction(label, self)
            action.setCheckable(True)
            action.setChecked(kind == self._kind)
            action.triggered.connect(lambda _checked=False, kind=kind: self._choose_kind(kind))
            kind_group.addAction(action)
            graph_menu.addAction(action)
            self.kind_actions[kind] = action

        graph_menu.addSeparator()
        self.grid_action = QAction("Show grid", self)
        self.grid_action.setCheckable(True)
        self.grid_action.setChecked(True)
        graph_menu.addAction(self.grid_action)

        about_action = QAction("About PyGraphy", self)
        about_action.triggered.connect(self._about)
        help_menu.addAction(about_action)

    def _build_status(self):
        status = QStatusBar()
        status.setContentsMargins(8, 0, 18, 0)
        self.setStatusBar(status)
        self.dataset_status = QLabel("No data set")
        self.row_status = QLabel("0 rows")
        self.link_status = QLabel("Disconnected")
        for label in (self.dataset_status, self.row_status, self.link_status):
            status.addPermanentWidget(label)

    def _connect_signals(self):
        # connect() means: when this signal happens, call that function.
        # SerialPanel emits row_received after readyRead has already copied
        # waiting bytes. The slot runs on the GUI event loop and returns,
        # so a slow board cannot freeze painting or button clicks.
        self.tabs.currentChanged.connect(self._tab_changed)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        self.grid_action.toggled.connect(self._set_grid)
        self.graph_board.selection_changed.connect(self._on_selection_changed)
        self.graph_board.import_requested.connect(self._import_into_panel)
        self.graph_board.remove_requested.connect(self._forget_panel_tab)
        self.serial_panel.header_received.connect(self._on_serial_header)
        self.serial_panel.row_received.connect(self._on_serial_row)
        self.serial_panel.link_changed.connect(self._on_link_changed)
        self.serial_panel.failed.connect(self._show_error)

    def _add_graph(self):
        """Add one comparison panel. It does not copy another panel's rows."""
        panel = self.graph_board.add_panel()
        self._set_notice(
            f"Added {panel.name}. It has its own type, columns, rows, and playback."
        )
        return panel

    def _panel(self):
        return self.graph_board.selected_panel()

    def _target_panel(self):
        panel = self._panel()
        if panel is None:
            panel = self.graph_board.add_panel()
        return panel

    def _choose_kind(self, kind):
        """Set the graph type on the selected panel only."""
        panel = self._target_panel()
        self._kind = kind
        label = dict(GRAPH_KINDS)[kind]
        self.view_label.setText(f"Selected: {panel.name} · {label}")
        for key, action in self.kind_actions.items():
            action.blockSignals(True)
            action.setChecked(key == kind)
            action.blockSignals(False)
        self._set_mode("graph")
        self.stack.setCurrentWidget(self.workspace)
        panel.set_kind(kind)
        self._update_status()

    def _show_home(self):
        self._set_mode("graph")
        self.stack.setCurrentWidget(self.home)

    def _set_grid(self, enabled):
        self.grid_action.blockSignals(True)
        self.grid_action.setChecked(enabled)
        self.grid_action.blockSignals(False)
        panel = self._panel()
        if panel is not None:
            panel.set_grid(enabled)

    def _current_tab(self):
        """The table that belongs to the selected graph, if it has rows loaded."""
        panel = self._panel()
        if panel is None or panel.tab is None:
            return None
        if isinstance(panel.tab, DataSetTab):
            return panel.tab
        return None

    def _current_dataset(self):
        tab = self._current_tab()
        if tab is None:
            return None
        return tab.dataset

    def _unique_name(self, name):
        existing = {self.tabs.tabText(i) for i in range(self.tabs.count())}
        if name not in existing:
            return name
        number = 2
        while f"{name} ({number})" in existing:
            number += 1
        return f"{name} ({number})"

    def _add_tab(self, dataset, panel=None):
        dataset.name = self._unique_name(dataset.name)
        tab = DataSetTab(dataset)
        if panel is not None:
            panel.attach_tab(tab)
            panel.set_name(dataset.name)
        self.tabs.blockSignals(True)
        self.tabs.addTab(tab, dataset.name)
        self.tabs.setCurrentWidget(tab)
        self.tabs.blockSignals(False)
        self._sync_table_page()
        return tab

    def _new_dataset(self):
        name, accepted = QInputDialog.getText(self, "New data set", "Name this data set:")
        name = name.strip()
        if not accepted or not name:
            return
        panel = self.graph_board.add_panel(name)
        self._add_tab(DataSet(name), panel)
        panel.show_dataset(panel.tab.dataset)
        self._on_selection_changed()
        self._set_notice(f"Added {panel.name}. Its table is empty until you type or import.")

    def _open_csv_dialog(self):
        start = str(sample_csv_path().parent)
        path, _selected = QFileDialog.getOpenFileName(
            self,
            "Open CSV",
            start,
            "CSV files (*.csv);;All files (*)",
        )
        if path:
            self._load_path(Path(path))

    def _import_table(self):
        """File menu import loads into the selected graph only."""
        self._import_into_panel(self._target_panel())

    def _import_into_panel(self, panel):
        """Open a csv, xlsx, or ods file into this one panel."""
        if panel is None:
            return
        if panel is not self._panel():
            self.graph_board.select_panel(panel)
        start = str(sample_csv_path().parent)
        path, _selected = QFileDialog.getOpenFileName(
            self,
            f"Import table into {panel.name}",
            start,
            "Spreadsheets (*.csv *.xlsx *.ods);;CSV (*.csv);;Excel (*.xlsx);;LibreOffice Calc (*.ods)",
        )
        if path:
            self._load_imported_file(Path(path), panel)

    def _load_imported_file(self, path, panel=None):
        try:
            headers, rows, note = load_table(path)
        except (OSError, ValueError, csv.Error) as error:
            self._show_error(f"Could not read {path.name}: {error}")
            return
        self._replace_panel_rows(
            panel or self._target_panel(),
            headers,
            rows,
            note,
            source_path=path,
            preferred_name=path.stem,
            label=path.name,
        )

    def _paste_table(self):
        text = QApplication.clipboard().text()
        if text is None or not str(text).strip():
            self._show_error(
                "The clipboard has no table text. "
                "Copy cells from LibreOffice Calc, Excel, or Google Sheets first."
            )
            return
        try:
            headers, rows, note = load_delimited_text(text, "pasted table")
        except (ValueError, csv.Error) as error:
            self._show_error(f"Could not read the pasted table: {error}")
            return
        panel = self._target_panel()
        self._replace_panel_rows(
            panel,
            headers,
            rows,
            note,
            source_path=None,
            preferred_name="Pasted",
            label="pasted table",
        )

    def _sync_table_page(self):
        """Show the selected graph's table. Other graphs' tables stay put."""
        tab = self._current_tab()
        if tab is None:
            self.table_holder.setCurrentWidget(self.empty_table)
            return
        self.tabs.blockSignals(True)
        self.tabs.setCurrentWidget(tab)
        self.tabs.blockSignals(False)
        self.table_holder.setCurrentWidget(self.tabs)

    def _clear_table(self):
        """Clear the selected graph's rows and headers in memory.

        sample_data.csv and any file the user opened stay untouched.
        Other graphs are not cleared. With no table, only the status bar changes.
        """
        panel = self._panel()
        tab = self._current_tab()
        if panel is None or tab is None:
            self.dataset_status.setText("Nothing to clear.")
            self.row_status.setText("0 rows")
            return
        dataset = tab.dataset
        if dataset.rows:
            answer = QMessageBox.question(
                self,
                "Clear table",
                f"Clear every row and column in '{panel.name}'?\n\n"
                "This forgets them in memory. Other graphs stay as they are. "
                "It does not change the file on disk.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        dataset.clear_memory()
        tab.refresh_table()
        panel.show_dataset(dataset)
        self._bind_manual_view()
        self._update_status()
        self._set_notice(f"Cleared {panel.name} in memory. Other graphs were not changed.")

    def _load_sample(self):
        path = sample_csv_path()
        if not path.is_file():
            self._show_error(f"Could not find the sample file at {path}.")
            return
        self._load_path(path, preferred_name="Sample")

    def _load_path(self, path, preferred_name=None):
        try:
            headers, rows, note = load_csv(path)
        except (OSError, ValueError, csv.Error) as error:
            self._show_error(f"Could not read {path.name}: {error}")
            return

        self._replace_panel_rows(
            self._target_panel(),
            headers,
            rows,
            note,
            source_path=path,
            preferred_name=preferred_name or path.stem,
            label=path.name,
        )

    def _replace_panel_rows(self, panel, headers, rows, note, source_path, preferred_name, label):
        """Load rows into one graph. Ask first when that graph already has rows."""
        if panel is None:
            return
        dataset = panel.bound_dataset()
        if dataset is not None and dataset.rows:
            answer = QMessageBox.question(
                self,
                "Replace rows?",
                f"Replace every row in {panel.name} with {label}?\n\n"
                "Only this graph changes. The other graphs keep their rows. "
                "The file on disk is not modified.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        if dataset is None:
            dataset = DataSet(preferred_name or panel.name)
            self._add_tab(dataset, panel)
        elif not dataset.headers and preferred_name:
            dataset.name = self._unique_name(preferred_name)
            panel.set_name(dataset.name)
            index = self.tabs.indexOf(panel.tab)
            if index >= 0:
                self.tabs.setTabText(index, dataset.name)
        dataset.source_path = source_path
        dataset.replace_table(headers, rows)
        panel.tab.refresh_table()
        panel.show_dataset(dataset)
        if panel is not self._panel():
            self.graph_board.select_panel(panel)
        else:
            self._on_selection_changed()
        self._set_notice(f"{note} Loaded into {panel.name}. Other graphs were not changed.")

    def _forget_panel_tab(self, panel):
        """Drop the table that belonged to a graph that is being removed."""
        tab = panel.tab
        panel.tab = None
        if tab is None:
            return
        index = self.tabs.indexOf(tab)
        if index < 0:
            return
        self.tabs.blockSignals(True)
        self.tabs.removeTab(index)
        self.tabs.blockSignals(False)

    def _on_selection_changed(self):
        panel = self._panel()
        if panel is None:
            self.view_label.setText("No graph selected")
            self._sync_table_page()
            self._bind_manual_view()
            self._update_status()
            return
        self._kind = panel.kind()
        label = dict(GRAPH_KINDS).get(self._kind, self._kind)
        self.view_label.setText(f"Selected: {panel.name} · {label}")
        for key, action in self.kind_actions.items():
            action.blockSignals(True)
            action.setChecked(key == self._kind)
            action.blockSignals(False)
        self.grid_action.blockSignals(True)
        self.grid_action.setChecked(panel.grid_enabled())
        self.grid_action.blockSignals(False)
        self._sync_table_page()
        self._bind_manual_view()
        self._update_status()

    def _close_current_tab(self):
        panel = self._panel()
        if panel is None:
            return
        self.graph_board.remove_panel(panel)

    def _close_tab(self, index):
        tab = self.tabs.widget(index)
        panel = self.graph_board.panel_for_tab(tab)
        if panel is not None:
            self.graph_board.remove_panel(panel)
            return
        self.tabs.removeTab(index)
        self._sync_table_page()
        self._bind_manual_view()
        self._update_status()

    def _tab_changed(self, _index):
        self._serial_hold = False
        tab = self.tabs.currentWidget()
        panel = self.graph_board.panel_for_tab(tab) if isinstance(tab, DataSetTab) else None
        if panel is not None and panel is not self._panel():
            self.graph_board.select_panel(panel)
            return
        if self._mode == "manual":
            self._bind_manual_view()
        self._update_status()

    def _bind_manual_view(self):
        if self._manual_model is not None:
            try:
                self._manual_model.dataChanged.disconnect(self._on_manual_edited)
            except TypeError:
                pass
            self._manual_model = None
        tab = self._current_tab()
        if tab is None:
            self.manual_table.setModel(None)
            self.manual_empty.setText(
                "No data set is open. Next: press Add table, then type a column name "
                "and press Add column."
            )
            self.manual_empty.setVisible(True)
            self.manual_caption.setText(
                "Type a small table. The cells are the same data set the graph uses. "
                "They stay in memory for this tab. Closing PyGraphy does not write a hidden file. "
                "File → Export records as CSV saves them when you ask."
            )
            return
        self._manual_model = tab.model
        self.manual_table.setModel(tab.model)
        tab.model.dataChanged.connect(self._on_manual_edited)
        if tab.dataset.headers:
            self.manual_empty.setVisible(False)
        else:
            self.manual_empty.setText(
                f"{tab.dataset.name} has no columns yet. Type a column name and press Add column."
            )
            self.manual_empty.setVisible(True)
        self.manual_caption.setText(
            f"Editing {tab.dataset.name} in memory. "
            "These cells are the same rows the graph uses. "
            "Closing PyGraphy does not write a hidden file. "
            "File → Export records as CSV saves them when you ask."
        )

    def _on_manual_edited(self, _top_left, _bottom_right, _roles=None):
        tab = self._current_tab()
        if tab is None:
            return
        self._refresh_panel(tab, False)
        tab.update_empty()
        self._update_status()

    def _refresh_panel(self, tab, headers_changed):
        """Redraw the graph that owns this table. Leave the other graphs alone."""
        panel = self.graph_board.panel_for_tab(tab)
        if panel is None:
            return
        if panel.bound_dataset() is not tab.dataset:
            panel.show_dataset(tab.dataset)
        else:
            panel.note_rows_changed(headers_changed)

    def _add_manual_table(self):
        """Open a new empty table and stay on Manual entry.

        The new table does not copy another table's rows. Add column,
        Add row, and Delete row then apply to this table.
        """
        panel = self.graph_board.add_panel()
        dataset = DataSet(panel.name)
        self._add_tab(dataset, panel)
        panel.show_dataset(dataset)
        self._bind_manual_view()
        self._update_status()
        self._set_notice(
            f"Added an empty table on {panel.name}. "
            "Other tables were not copied. Type a column name, then press Add column."
        )

    def _manual_tab(self):
        panel = self._target_panel()
        if panel.tab is None:
            self._add_tab(DataSet(panel.name), panel)
            panel.show_dataset(panel.tab.dataset)
            self._on_selection_changed()
        return panel.tab

    def _add_manual_column(self):
        name = self.column_name_edit.text().strip()
        if not name:
            self._show_error("Type a column name, then press Add column.")
            return
        tab = self._manual_tab()
        added = tab.dataset.add_column(name)
        self.column_name_edit.clear()
        tab.refresh_table()
        self._refresh_panel(tab, True)
        self._bind_manual_view()
        self._update_status()
        self._set_notice(
            f"Added column {added} to {tab.dataset.name}. "
            "It stays in memory until you export. Other graphs were not changed."
        )

    def _add_manual_row(self):
        tab = self._current_tab()
        if tab is None or not tab.dataset.headers:
            self._show_error("Add a column name before adding a row.")
            return
        message = tab.dataset.add_blank_row()
        if message:
            self._show_error(message)
            return
        tab.note_appended()
        self._refresh_panel(tab, False)
        self._update_status()
        self._set_notice(f"Added a blank row to {tab.dataset.name}. Type the cell values.")

    def _delete_manual_row(self):
        tab = self._current_tab()
        if tab is None:
            self._show_error("Open a data set before deleting a row.")
            return
        index = self.manual_table.currentIndex()
        if not index.isValid():
            self._show_error("Select a row in the manual table, then press Delete row.")
            return
        if not tab.model.remove_row(index.row()):
            self._show_error("That row is not in this data set.")
            return
        tab.update_empty()
        self._refresh_panel(tab, False)
        self._update_status()
        self._set_notice(f"Deleted a row from {tab.dataset.name}.")

    def _copy_graph(self):
        panel = self._panel()
        if panel is None:
            self._show_error("Add a graph before copying one.")
            return
        try:
            image = panel.image_of_current_graph()
        except Exception as error:
            self._show_error(f"Could not copy the graph image: {error}")
            self._export_png()
            return
        if image is None or image.isNull() or image.width() < 2:
            self._show_error("The graph image was empty, so it was not placed on the clipboard.")
            self._export_png()
            return
        clipboard = QApplication.clipboard()
        clipboard.setImage(image)
        mime = clipboard.mimeData()
        kept = mime is not None and mime.hasImage() and not clipboard.image().isNull()
        if not kept:
            self._show_error(
                "The clipboard did not keep the graph image. You can still save a PNG file."
            )
            self._export_png()
            return
        self._set_notice(
            f"Copied {panel.name} as a PNG image. "
            "Paste it into LibreOffice Writer, Microsoft Word, or a Google Doc."
        )

    def _copy_table(self):
        dataset = self._current_dataset()
        if dataset is None or (not dataset.headers and not dataset.rows):
            self._show_error("There is no table to copy. Add rows in Manual entry, or load a file.")
            return
        QApplication.clipboard().setText(records_as_tsv(dataset))
        count = len(dataset.rows)
        noun = "row" if count == 1 else "rows"
        self._set_notice(
            f"Copied {count} {noun} as tab-separated text, in original row order. "
            "Paste into LibreOffice Calc, Excel, or Google Sheets."
        )

    def _on_serial_header(self, cells):
        panel = self._target_panel()
        if panel.tab is None:
            self._add_tab(DataSet(panel.name), panel)
            panel.show_dataset(panel.tab.dataset)
        tab = panel.tab
        before = list(tab.dataset.headers)
        message = tab.dataset.adopt_header(cells)
        if message:
            self._serial_hold = True
            self.serial_panel.show_notice(message)
            self._set_notice(message)
            return
        self._serial_hold = False
        tab.refresh_table()
        self._refresh_panel(tab, tab.dataset.headers != before)
        self._update_status()
        self.serial_panel.show_notice(f"Connected. Columns: {', '.join(tab.dataset.headers)}.")

    def _on_serial_row(self, cells):
        if self._serial_hold:
            self.serial_panel.show_notice("Skipped a row because the header did not match.")
            return
        tab = self._current_tab()
        if tab is None:
            self.serial_panel.show_notice("Add a data set before capturing rows.")
            return
        message = tab.dataset.append_row(cells)
        if message:
            self.serial_panel.show_notice(message)
            return
        tab.note_appended()
        self._refresh_panel(tab, False)
        self._update_status()

    def _on_link_changed(self, text):
        self.link_status.setText(text)
        if text == "Disconnected":
            self._serial_hold = False

    def _export_png(self):
        panel = self._panel()
        if panel is None:
            self._show_error("Add a graph before exporting.")
            return
        path = self._choose_save_path("Export graph", "PNG image (*.png)", ".png")
        if not path:
            return
        panel.save_png(str(path))
        self._set_notice(f"Saved {panel.name} to {path.name}.")

    def _export_csv(self):
        dataset = self._current_dataset()
        if dataset is None:
            self._show_error("Open a data set before exporting records.")
            return
        path = self._choose_save_path("Export records", "CSV files (*.csv)", ".csv")
        if not path:
            return
        if dataset.source_path and path.resolve() == dataset.source_path.resolve():
            self._show_error(
                "PyGraphy will not modify the CSV you loaded. Choose a different file name."
            )
            return
        try:
            write_records_csv(dataset, path)
        except OSError as error:
            self._show_error(f"Could not write {path.name}: {error}")
            return
        self._set_notice(
            f"Exported {len(dataset.rows)} rows in original order to {path.name}."
        )

    def _choose_save_path(self, title, name_filter, suffix):
        dialog = QFileDialog(self, title, str(sample_csv_path().parent))
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        dialog.setNameFilter(name_filter)
        dialog.setOption(QFileDialog.Option.DontConfirmOverwrite, True)
        if suffix:
            dialog.setDefaultSuffix(suffix.lstrip("."))
        if not dialog.exec():
            return None
        selected = dialog.selectedFiles()
        if not selected:
            return None
        path = Path(selected[0])
        if path.suffix.lower() != suffix:
            path = path.with_suffix(suffix)
        if path.exists() and not self._confirm_overwrite(path):
            return None
        return path

    def _confirm_overwrite(self, path):
        answer = QMessageBox.question(
            self,
            "Overwrite file?",
            f"{path} already exists. Replace it?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _update_status(self):
        dataset = self._current_dataset()
        if dataset is None:
            self.dataset_status.setText("No data set")
            self.row_status.setText("0 rows")
        else:
            self.dataset_status.setText(dataset.name)
            count = len(dataset.rows)
            noun = "row" if count == 1 else "rows"
            self.row_status.setText(f"{count} {noun}")
        self.link_status.setText(self.serial_panel.link_text())

    def _set_notice(self, text):
        self.notice.setText(text)
        self.notice.setVisible(bool(text))

    def _show_error(self, text):
        QMessageBox.warning(self, "PyGraphy", text)

    def _about(self):
        QMessageBox.about(
            self,
            "About PyGraphy",
            "PyGraphy plots one series on each comparison graph.\n\n"
            "The window starts with no rows. Nothing is saved when you close it.\n"
            "Add graph puts another graph beside the others. Each one has its own rows.\n"
            "Import table on a graph loads a csv, xlsx, or ods file into that graph only.\n"
            "File → Paste table goes into the selected graph. The label says Selected.\n"
            "File → Load sample CSV reads sample_data.csv from the program folder.\n"
            "Clear table forgets the selected graph's table and does not change that file.\n"
            "Drag the divider between the table and the graphs to resize them.\n\n"
            "Graph mode shows the graphs and, from All graph types, the home page.\n"
            "Manual entry edits the table you are looking at. Add table starts an empty one.\n"
            "Microcontroller mode holds the serial controls, Copy graph, and Copy table.\n\n"
            "Line, scatter, area, step, bar, horizontal bar, and histogram use PyQtGraph.\n"
            "Pie or donut is drawn with QPainter. PyQtGraph does not draw "
            "pies well, and PyQt6.QtCharts is not installed.\n"
            "Box plots and candlesticks are not included, because PyQtGraph "
            "does not draw them from one line or one bar item.\n\n"
            "USB serial is read in the window's event loop. "
            "Record playback only replays rows already in the active data set. "
            "Copy graph is a still picture of the current graph type, not live acquisition.\n\n"
            "Sorting the graph table does not change the row order used for the graph. "
            "Sample standard deviation divides by n-1.",
        )

    def closeEvent(self, event):
        self.serial_panel.disconnect_port()
        super().closeEvent(event)


# Palette Qt received from the desktop at startup, before any replacement.
_desktop_palette = None
_desktop_scheme = None
# True only after this process calls setColorScheme. Unset is then safe.
_color_scheme_overridden = False

try:
    from PyQt6.QtDBus import QDBusVariant
except ImportError:
    QDBusVariant = None


def _palette_is_light(palette):
    """Window lightness at or above 128 counts as a light theme."""
    return palette.color(QPalette.ColorRole.Window).lightness() >= 128


def _copy_palette(palette):
    """Copy every color into a new palette.

    QPalette copies share hidden data. Later theme changes can rewrite
    that shared data. Building a new palette keeps the startup colors.
    """
    copy = QPalette()
    groups = (
        QPalette.ColorGroup.Active,
        QPalette.ColorGroup.Inactive,
        QPalette.ColorGroup.Disabled,
    )
    for group in groups:
        for role in QPalette.ColorRole:
            if role in (QPalette.ColorRole.NColorRoles, QPalette.ColorRole.NoRole):
                continue
            copy.setColor(group, role, QColor(palette.color(group, role)))
    return copy


def _install_palette(app, palette):
    """Put palette on the application and keep it if the style replaces it."""
    wanted = palette.color(QPalette.ColorRole.Window)
    app.setPalette(palette)
    if app.palette().color(QPalette.ColorRole.Window) == wanted:
        return
    sheet = app.styleSheet()
    app.setStyleSheet("")
    app.setPalette(QPalette(palette))
    if sheet:
        app.setStyleSheet(sheet)
    if app.palette().color(QPalette.ColorRole.Window) != wanted:
        app.setPalette(QPalette(palette))


_COLOR_LINE = re.compile(
    r"""^\s*([A-Za-z0-9_-]+)\s*=\s*["']?(#[0-9A-Fa-f]{6})"""
)
_MODE_LINE = re.compile(r"""^\s*mode\s*=\s*["']?(dark|light)\b""", re.IGNORECASE)


def omarchy_theme_dir():
    """Folder Omarchy rewrites when the active theme changes.

    XDG_STATE_HOME wins when it is set. Otherwise the folder is
    .local/state under the current user's home. Nothing here names
    one computer's folders.
    """
    state_home = os.environ.get("XDG_STATE_HOME")
    if state_home:
        root = Path(state_home)
    else:
        root = Path.home() / ".local" / "state"
    return root / "omarchy" / "current" / "theme"


def _hex_color(text):
    color = QColor(text)
    if not color.isValid():
        return None
    return color


def read_omarchy_colors():
    """Read background, text, and accent from the active Omarchy theme.

    The file is colors.toml in omarchy_theme_dir(). Text is the
    foreground key. Older themes use color0, color7, and color4 for
    the same three jobs. Returns None when this is not an Omarchy
    machine or the file has no colors.
    """
    path = omarchy_theme_dir() / "colors.toml"
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    found = {}
    mode = None
    for line in raw.splitlines():
        color_match = _COLOR_LINE.match(line)
        if color_match:
            found[color_match.group(1)] = color_match.group(2)
            continue
        mode_match = _MODE_LINE.match(line)
        if mode_match:
            mode = mode_match.group(1).lower()
    background = _hex_color(found.get("background") or found.get("color0") or "")
    text = _hex_color(found.get("foreground") or found.get("color7") or "")
    accent = _hex_color(found.get("accent") or found.get("color4") or "")
    if background is None or text is None or accent is None:
        return None
    return {
        "background": background,
        "foreground": text,
        "accent": accent,
        "mode": mode,
    }


def _mix_colors(start, end, amount):
    """Blend start toward end. amount 0 keeps start."""
    amount = max(0.0, min(1.0, amount))
    return QColor(
        int(start.red() + (end.red() - start.red()) * amount),
        int(start.green() + (end.green() - start.green()) * amount),
        int(start.blue() + (end.blue() - start.blue()) * amount),
    )


def _text_on(accent, background, text):
    """Pick background or text, whichever stands out more on accent."""
    accent_light = accent.lightness()
    if abs(background.lightness() - accent_light) >= abs(text.lightness() - accent_light):
        return QColor(background)
    return QColor(text)


def palette_from_omarchy(colors):
    """Map Omarchy background, text, and accent onto Qt palette roles.

    Edit the role lines in this function to change which Omarchy color
    paints a part of the window. PyQtGraph reads Base, Text, Highlight,
    and Accent from this palette. style.qss looks up the same roles
    with palette().
    """
    background = QColor(colors["background"])
    text = QColor(colors["foreground"])
    accent = QColor(colors["accent"])
    # Window and Base stay the theme background with no blend.
    # A blend made the window a step away from the theme color.
    button = _mix_colors(background, text, 0.08)
    alternate = _mix_colors(background, text, 0.14)
    mid = _mix_colors(background, text, 0.35)
    quiet = _mix_colors(text, background, 0.45)
    on_accent = _text_on(accent, background, text)
    palette = QPalette()
    groups = (
        QPalette.ColorGroup.Active,
        QPalette.ColorGroup.Inactive,
        QPalette.ColorGroup.Disabled,
    )
    for group in groups:
        disabled = group == QPalette.ColorGroup.Disabled
        ink = quiet if disabled else text
        palette.setColor(group, QPalette.ColorRole.Window, background)
        palette.setColor(group, QPalette.ColorRole.WindowText, ink)
        palette.setColor(group, QPalette.ColorRole.Base, background)
        palette.setColor(group, QPalette.ColorRole.AlternateBase, alternate)
        palette.setColor(group, QPalette.ColorRole.Text, ink)
        palette.setColor(group, QPalette.ColorRole.Button, button)
        palette.setColor(group, QPalette.ColorRole.ButtonText, ink)
        palette.setColor(group, QPalette.ColorRole.Highlight, accent)
        palette.setColor(group, QPalette.ColorRole.HighlightedText, on_accent)
        palette.setColor(group, QPalette.ColorRole.Accent, accent)
        palette.setColor(group, QPalette.ColorRole.ToolTipBase, button)
        palette.setColor(group, QPalette.ColorRole.ToolTipText, text)
        palette.setColor(group, QPalette.ColorRole.PlaceholderText, quiet)
        palette.setColor(group, QPalette.ColorRole.Link, accent)
        palette.setColor(group, QPalette.ColorRole.Light, alternate)
        palette.setColor(group, QPalette.ColorRole.Mid, mid)
        palette.setColor(group, QPalette.ColorRole.Dark, _mix_colors(background, text, 0.55))
        palette.setColor(group, QPalette.ColorRole.Shadow, background)
    return palette


def apply_omarchy_palette(app):
    """Use the Omarchy theme when colors.toml is present.

    Returns False on machines that are not Omarchy so the caller can
    keep the freedesktop light/dark behavior.
    """
    global _color_scheme_overridden
    colors = read_omarchy_colors()
    if colors is None:
        return False
    mode = colors.get("mode")
    if mode == "light":
        scheme = Qt.ColorScheme.Light
    elif mode == "dark":
        scheme = Qt.ColorScheme.Dark
    elif colors["background"].lightness() >= 128:
        scheme = Qt.ColorScheme.Light
    else:
        scheme = Qt.ColorScheme.Dark
    hints = app.styleHints()
    if hints.colorScheme() != scheme:
        hints.setColorScheme(scheme)
        _color_scheme_overridden = True
    palette = palette_from_omarchy(colors)
    _install_palette(app, palette)
    for widget in app.topLevelWidgets():
        widget.setPalette(QPalette(palette))
    return True


def remember_desktop_palette(app):
    """Save the startup palette so a return to that scheme can restore it."""
    global _desktop_palette, _desktop_scheme
    _desktop_palette = _copy_palette(app.palette())
    if _palette_is_light(_desktop_palette):
        _desktop_scheme = Qt.ColorScheme.Light
    else:
        _desktop_scheme = Qt.ColorScheme.Dark


def _unwrap_dbus(value):
    for _ in range(5):
        if not hasattr(value, "variant"):
            break
        value = value.variant()
    return value


def _qt_scheme_from_portal_number(number):
    """Translate a portal color-scheme int into a Qt color scheme.

    The portal and Qt do not share numbers. Portal 1 is dark and portal
    2 is light. Qt's Light is 1 and Qt's Dark is 2.
    """
    try:
        number = int(number)
    except (TypeError, ValueError):
        return None
    if number == 0:
        return Qt.ColorScheme.Unknown
    if number == 1:
        return Qt.ColorScheme.Dark
    if number == 2:
        return Qt.ColorScheme.Light
    return None


def read_portal_color_scheme():
    """Read org.freedesktop.appearance color-scheme from the settings portal.

    Returns a Qt.ColorScheme, or None when this is not Linux or the
    portal cannot be asked. Portal 0 becomes Unknown (no preference).
    """
    if not sys.platform.startswith("linux") or QDBusVariant is None:
        return None
    from PyQt6.QtDBus import QDBusConnection, QDBusInterface, QDBusMessage

    bus = QDBusConnection.sessionBus()
    if not bus.isConnected():
        return None
    iface = QDBusInterface(
        "org.freedesktop.portal.Desktop",
        "/org/freedesktop/portal/desktop",
        "org.freedesktop.portal.Settings",
        bus,
    )
    if not iface.isValid():
        return None
    reply = iface.call("Read", "org.freedesktop.appearance", "color-scheme")
    if reply.type() != QDBusMessage.MessageType.ReplyMessage:
        return None
    arguments = reply.arguments()
    if not arguments:
        return None
    return _qt_scheme_from_portal_number(_unwrap_dbus(arguments[0]))


def apply_system_color_scheme(app):
    """Point Qt at the portal scheme when Qt is not already following it.

    Matching schemes are left alone. setColorScheme would lock the
    choice and stop later desktop changes until unsetColorScheme.
    """
    global _color_scheme_overridden
    portal = read_portal_color_scheme()
    if portal is None:
        return
    hints = app.styleHints()
    if portal in (Qt.ColorScheme.Light, Qt.ColorScheme.Dark):
        if hints.colorScheme() != portal:
            hints.setColorScheme(portal)
            _color_scheme_overridden = True
        return
    if (
        portal == Qt.ColorScheme.Unknown
        and _color_scheme_overridden
        and hasattr(hints, "unsetColorScheme")
    ):
        hints.unsetColorScheme()
        _color_scheme_overridden = False


def sync_palette_to_color_scheme(app):
    """Give the window a light or dark palette that matches the scheme.

    Qt on this desktop updates the scheme name and leaves the old
    colors in place. style.qss looks those colors up with palette(),
    so the palette has to change before load_style runs again.

    The palette saved at startup is put back when the scheme returns
    to the one the computer used then. The other side comes from the
    current widget style, not from a color typed in this file.
    """
    if _desktop_palette is None:
        return
    scheme = app.styleHints().colorScheme()
    if scheme not in (Qt.ColorScheme.Light, Qt.ColorScheme.Dark):
        return
    window = app.palette().color(QPalette.ColorRole.Window)
    saved = _desktop_palette.color(QPalette.ColorRole.Window)
    if scheme == _desktop_scheme:
        # Qt may already have swapped in a generic dark or light palette.
        # Put the desktop colors back when the scheme matches startup.
        if window != saved:
            _install_palette(app, _copy_palette(_desktop_palette))
        return
    want_light = scheme == Qt.ColorScheme.Light
    if _palette_is_light(app.palette()) == want_light:
        return
    _install_palette(app, app.style().standardPalette())


def load_style(app):
    """Read style.qss and apply it to the whole window.

    Edit style.qss to change a font, spacing, or which palette role a
    widget uses. Edit this function only to change how that file is
    found or loaded. Call it again after a light or dark change so
    palette() roles are looked up on the new colors.
    """
    path = bundled_path("style.qss")
    if not path.is_file():
        app.setStyleSheet("")
        return
    app.setStyleSheet(path.read_text(encoding="utf-8"))


class _DesktopSchemeWatcher(QObject):
    """Hear freedesktop color-scheme changes while the window is open."""

    def __init__(self, app, window):
        super().__init__(app)
        self._app = app
        self._window = window
        if QDBusVariant is None or not sys.platform.startswith("linux"):
            return
        from PyQt6.QtDBus import QDBusConnection

        bus = QDBusConnection.sessionBus()
        if not bus.isConnected():
            return
        bus.connect(
            "org.freedesktop.portal.Desktop",
            "/org/freedesktop/portal/desktop",
            "org.freedesktop.portal.Settings",
            "SettingChanged",
            "ssv",
            self._on_setting_changed,
        )

    if QDBusVariant is not None:
        @pyqtSlot(str, str, QDBusVariant)
        def _on_setting_changed(self, namespace, key, value):
            if namespace != "org.freedesktop.appearance" or key != "color-scheme":
                return
            apply_system_color_scheme(self._app)
            _restyle_after_scheme_change(self._app, self._window)
    else:
        def _on_setting_changed(self, *_args):
            return None


class _OmarchyThemeWatcher(QObject):
    """Re-read colors.toml when Omarchy writes a new theme."""

    def __init__(self, app, window):
        super().__init__(app)
        self._app = app
        self._window = window
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._changed)
        self._watcher.directoryChanged.connect(self._changed)
        self._arm()

    def _arm(self):
        """Watch the theme folder and colors.toml. A replaced file needs a new watch."""
        theme_dir = omarchy_theme_dir()
        colors = theme_dir / "colors.toml"
        if theme_dir.is_dir():
            self._watcher.addPath(str(theme_dir))
        if colors.is_file():
            self._watcher.addPath(str(colors))

    def _changed(self, _path):
        self._arm()
        _restyle_after_scheme_change(self._app, self._window)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("PyGraphy")
    # Leave the platform style alone so Windows, macOS, and Linux
    # use the desktop theme. Do not call setStyle("Fusion").
    remember_desktop_palette(app)
    if not apply_omarchy_palette(app):
        apply_system_color_scheme(app)
        sync_palette_to_color_scheme(app)
    load_style(app)
    window = PyGraphyWindow()
    hints = app.styleHints()
    if hasattr(hints, "colorSchemeChanged"):
        hints.colorSchemeChanged.connect(
            lambda *_args: _restyle_after_scheme_change(app, window)
        )
    # Kept on the window so the listeners are not thrown away.
    window._scheme_watcher = _DesktopSchemeWatcher(app, window)
    window._omarchy_watcher = _OmarchyThemeWatcher(app, window)
    window.show()
    return app.exec()


_restyle_queued = False


def _restyle_after_scheme_change(app, window):
    """Apply a theme change after Qt finishes delivering the signal.

    Setting the palette from inside colorSchemeChanged is overwritten
    by Qt before the signal returns. One queued call reads the scheme
    that is current at that later moment, then updates the window and
    the plot.
    """
    global _restyle_queued
    if _restyle_queued:
        return
    _restyle_queued = True

    def apply_when_ready():
        global _restyle_queued
        _restyle_queued = False
        if apply_omarchy_palette(app):
            load_style(app)
        else:
            apply_system_color_scheme(app)
            sync_palette_to_color_scheme(app)
            load_style(app)
            sync_palette_to_color_scheme(app)
        board = getattr(window, "graph_board", None)
        if board is not None:
            board.apply_plot_palette()

    QTimer.singleShot(0, apply_when_ready)


if __name__ == "__main__":
    sys.exit(main())
