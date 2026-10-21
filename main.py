"""PyGraphy entry point.

Run this file with the project virtual environment:

    ./.venv/bin/python main.py

The window, menus, data-set tabs, and signal connections live here.
Records, graphs, and the serial port live in the sibling modules.
"""

import csv
import sys
from pathlib import Path

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, QObject, Qt, QSortFilterProxyModel, QTimer, pyqtSlot
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
from graph_view import GraphPanel
from serial_panel import SerialPanel


GRAPH_KINDS = (
    ("line", "Line"),
    ("scatter", "Scatter"),
    ("bar", "Bar"),
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
    """The first screen: pick Line, Scatter, Bar, Histogram, or Pie or donut."""

    def __init__(self, choose_kind):
        super().__init__()
        self.setObjectName("homePage")
        title = QLabel("PyGraphy")
        title.setObjectName("homeTitle")
        self.intro = QLabel(
            "No rows yet. Next: choose a graph, or use File → Load sample CSV. "
            "sample_data.csv is in this program's folder. "
            "PyGraphy does not open it until you ask."
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
        header = QHBoxLayout()
        self.view_label = QLabel("View: Line")
        self.view_label.setObjectName("sectionLabel")
        divider_hint = QLabel("Drag the divider between the table and the graph.")
        divider_hint.setObjectName("pageHint")
        home_button = QPushButton("All graph types")
        home_button.clicked.connect(self._show_home)
        header.addWidget(self.view_label)
        header.addStretch(1)
        header.addWidget(divider_hint)
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
        self.clear_button.clicked.connect(self._clear_table)
        table_tools.addWidget(table_label)
        table_tools.addStretch(1)
        table_tools.addWidget(self.clear_button)

        table_side = QWidget()
        table_side.setObjectName("dataTableSide")
        table_column = QVBoxLayout(table_side)
        table_column.setContentsMargins(0, 0, 0, 0)
        table_column.setSpacing(8)
        table_column.addLayout(table_tools)
        table_column.addWidget(self.table_holder, stretch=1)

        self.graph_panel = GraphPanel()
        self.graph_panel.setMinimumWidth(280)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setObjectName("tableGraphDivider")
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(10)
        self.splitter.setOpaqueResize(True)
        table_side.setMinimumWidth(260)
        self.splitter.addWidget(table_side)
        self.splitter.addWidget(self.graph_panel)
        self.splitter.setStretchFactor(0, 2)
        self.splitter.setStretchFactor(1, 3)
        self.splitter.setSizes([420, 580])
        handle = self.splitter.handle(1)
        handle.setToolTip("Drag this divider to resize the table and the graph.")

        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)
        layout.addLayout(header)
        layout.addWidget(self.splitter, stretch=1)
        layout.addWidget(self.graph_panel.playback_box)
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
            "No data set is open. Next: type a column name and press Add column. "
            "That starts a tab named Manual."
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
        self.graph_panel.grid_check.toggled.connect(self._set_grid)
        self.serial_panel.header_received.connect(self._on_serial_header)
        self.serial_panel.row_received.connect(self._on_serial_row)
        self.serial_panel.link_changed.connect(self._on_link_changed)
        self.serial_panel.failed.connect(self._show_error)

    def _choose_kind(self, kind):
        self._kind = kind
        label = dict(GRAPH_KINDS)[kind]
        self.view_label.setText(f"View: {label}")
        for key, action in self.kind_actions.items():
            action.blockSignals(True)
            action.setChecked(key == kind)
            action.blockSignals(False)
        self._set_mode("graph")
        self.stack.setCurrentWidget(self.workspace)
        current = self._current_dataset()
        if self.graph_panel.bound_dataset() is not current:
            self.graph_panel.show_dataset(current)
        self.graph_panel.set_kind(kind)
        self._update_status()

    def _show_home(self):
        self._set_mode("graph")
        self.stack.setCurrentWidget(self.home)

    def _set_grid(self, enabled):
        self.grid_action.blockSignals(True)
        self.grid_action.setChecked(enabled)
        self.grid_action.blockSignals(False)
        self.graph_panel.set_grid(enabled)

    def _current_tab(self):
        widget = self.tabs.currentWidget()
        if isinstance(widget, DataSetTab):
            return widget
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

    def _add_tab(self, dataset):
        dataset.name = self._unique_name(dataset.name)
        tab = DataSetTab(dataset)
        self.tabs.addTab(tab, dataset.name)
        self.tabs.setCurrentWidget(tab)
        self._sync_table_page()
        return tab

    def _new_dataset(self):
        name, accepted = QInputDialog.getText(self, "New data set", "Name this data set:")
        name = name.strip()
        if not accepted or not name:
            return
        self._add_tab(DataSet(name))
        self._choose_kind(self._kind)
        self._set_notice(f"Created {name}.")

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
        start = str(sample_csv_path().parent)
        path, _selected = QFileDialog.getOpenFileName(
            self,
            "Import table",
            start,
            "Spreadsheets (*.csv *.xlsx *.ods);;CSV (*.csv);;Excel (*.xlsx);;LibreOffice Calc (*.ods)",
        )
        if path:
            self._load_imported_file(Path(path))

    def _load_imported_file(self, path):
        try:
            headers, rows, note = load_table(path)
        except (OSError, ValueError, csv.Error) as error:
            self._show_error(f"Could not read {path.name}: {error}")
            return
        self._place_loaded_table(
            headers,
            rows,
            note,
            source_path=path,
            preferred_name=path.stem,
            from_home_starts_new=False,
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
        self._place_loaded_table(
            headers,
            rows,
            note,
            source_path=None,
            preferred_name="Pasted",
            from_home_starts_new=False,
            label="pasted table",
        )

    def _sync_table_page(self):
        """Show the empty grid when no tab is open, otherwise show the tabs."""
        if self.tabs.count() == 0:
            self.table_holder.setCurrentWidget(self.empty_table)
        else:
            self.table_holder.setCurrentWidget(self.tabs)

    def _clear_table(self):
        """Clear the open tab's rows and headers in memory.

        sample_data.csv and any file the user opened stay untouched.
        With no tab open, only the status bar changes.
        """
        tab = self._current_tab()
        if tab is None:
            self.dataset_status.setText("Nothing to clear.")
            self.row_status.setText("0 rows")
            return
        dataset = tab.dataset
        if dataset.rows:
            answer = QMessageBox.question(
                self,
                "Clear table",
                f"Clear every row and column in '{dataset.name}'?\n\n"
                "This forgets them in memory. It does not change the file on disk.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        dataset.clear_memory()
        tab.refresh_table()
        self.graph_panel.show_dataset(dataset)
        self._bind_manual_view()
        self._update_status()
        self._set_notice("Cleared the table in memory. No file was changed.")

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

        self._place_loaded_table(
            headers,
            rows,
            note,
            source_path=path,
            preferred_name=preferred_name or path.stem,
            from_home_starts_new=True,
            label=path.name,
        )

    def _on_home_page(self):
        return self.mode_stack.currentWidget() is self.stack and self.stack.currentWidget() is self.home

    def _place_loaded_table(
        self, headers, rows, note, source_path, preferred_name, from_home_starts_new, label
    ):
        target = self._choose_load_target(label, from_home_starts_new)
        if target == "cancel":
            return
        if target == "into":
            tab = self._current_tab()
            tab.dataset.source_path = source_path
            tab.dataset.replace_table(headers, rows)
            tab.refresh_table()
            self.graph_panel.show_dataset(tab.dataset)
        else:
            dataset = DataSet(preferred_name or "Data")
            dataset.source_path = source_path
            dataset.replace_table(headers, rows)
            self._add_tab(dataset)
        self._choose_kind(self._kind)
        self._bind_manual_view()
        self._set_notice(note)

    def _choose_load_target(self, filename, from_home_starts_new):
        tab = self._current_tab()
        if tab is None:
            return "new"
        if from_home_starts_new and self._on_home_page():
            return "new"
        if not tab.dataset.headers and not tab.dataset.rows:
            return "into"
        return self._ask_load_target(filename)

    def _ask_load_target(self, filename):
        tab = self._current_tab()
        box = QMessageBox(self)
        box.setWindowTitle("Load table")
        box.setText(
            f"Load {filename} into '{tab.dataset.name}'? "
            "That replaces the rows in memory. The original file is not modified."
        )
        into_button = box.addButton("Into this data set", QMessageBox.ButtonRole.AcceptRole)
        new_button = box.addButton("New data set", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        clicked = box.clickedButton()
        if clicked is into_button:
            return "into"
        if clicked is new_button:
            return "new"
        return "cancel"

    def _close_current_tab(self):
        index = self.tabs.currentIndex()
        if index >= 0:
            self._close_tab(index)

    def _close_tab(self, index):
        self.tabs.removeTab(index)
        if self.tabs.count() == 0:
            self.graph_panel.show_dataset(None)
        self._sync_table_page()
        self._bind_manual_view()
        self._update_status()

    def _tab_changed(self, _index):
        self._serial_hold = False
        dataset = self._current_dataset()
        self.graph_panel.show_dataset(dataset)
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
                "No data set is open. Next: type a column name and press Add column. "
                "That starts a tab named Manual."
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
        if self.graph_panel.bound_dataset() is not tab.dataset:
            self.graph_panel.show_dataset(tab.dataset)
        else:
            self.graph_panel.note_rows_changed(False)
        tab.update_empty()
        self._update_status()

    def _manual_tab(self):
        tab = self._current_tab()
        if tab is None:
            tab = self._add_tab(DataSet("Manual"))
        return tab

    def _add_manual_column(self):
        name = self.column_name_edit.text().strip()
        if not name:
            self._show_error("Type a column name, then press Add column.")
            return
        tab = self._manual_tab()
        added = tab.dataset.add_column(name)
        self.column_name_edit.clear()
        tab.refresh_table()
        self.graph_panel.show_dataset(tab.dataset)
        self.graph_panel.note_rows_changed(True)
        self._bind_manual_view()
        self._update_status()
        self._set_notice(
            f"Added column {added} to {tab.dataset.name}. "
            "It stays in memory until you export."
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
        if self.graph_panel.bound_dataset() is not tab.dataset:
            self.graph_panel.show_dataset(tab.dataset)
        else:
            self.graph_panel.note_rows_changed(False)
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
        self.graph_panel.note_rows_changed(False)
        self._update_status()
        self._set_notice(f"Deleted a row from {tab.dataset.name}.")

    def _copy_graph(self):
        try:
            image = self.graph_panel.image_of_current_graph()
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
            "Copied the current graph as a PNG image. "
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
        tab = self._current_tab()
        if tab is None:
            tab = self._add_tab(DataSet("Serial capture"))
            self._choose_kind(self._kind)
        before = list(tab.dataset.headers)
        message = tab.dataset.adopt_header(cells)
        if message:
            self._serial_hold = True
            self.serial_panel.show_notice(message)
            self._set_notice(message)
            return
        self._serial_hold = False
        tab.refresh_table()
        self.graph_panel.note_rows_changed(tab.dataset.headers != before)
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
        self.graph_panel.note_rows_changed(False)
        self._update_status()

    def _on_link_changed(self, text):
        self.link_status.setText(text)
        if text == "Disconnected":
            self._serial_hold = False

    def _export_png(self):
        if self._current_dataset() is None and self.stack.currentWidget() is self.home:
            self._show_error("Choose a graph view before exporting.")
            return
        path = self._choose_save_path("Export graph", "PNG image (*.png)", ".png")
        if not path:
            return
        self.graph_panel.save_png(str(path))
        self._set_notice(f"Saved the graph to {path.name}.")

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
            "PyGraphy plots one series from each data set.\n\n"
            "The window starts with no rows. Nothing is saved when you close it.\n"
            "File → Load sample CSV reads sample_data.csv from the program folder.\n"
            "Clear table forgets the open tab in memory and does not change that file.\n"
            "Drag the divider between the table and the graph to resize them.\n\n"
            "Graph mode shows the plot and, from All graph types, the home page.\n"
            "Manual entry edits the same in-memory rows. Closing the app does not save them.\n"
            "Microcontroller mode holds the serial controls, Copy graph, and Copy table.\n\n"
            "Line, scatter, bar, and histogram use PyQtGraph.\n"
            "Pie or donut is drawn with QPainter. PyQtGraph does not draw "
            "pies well, and PyQt6.QtCharts is not installed.\n\n"
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


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("PyGraphy")
    # Leave the platform style alone so Windows, macOS, and Linux
    # use the desktop theme. Do not call setStyle("Fusion").
    remember_desktop_palette(app)
    apply_system_color_scheme(app)
    sync_palette_to_color_scheme(app)
    load_style(app)
    window = PyGraphyWindow()
    hints = app.styleHints()
    if hasattr(hints, "colorSchemeChanged"):
        hints.colorSchemeChanged.connect(
            lambda *_args: _restyle_after_scheme_change(app, window)
        )
    # Kept on the window so the portal listener is not thrown away.
    window._scheme_watcher = _DesktopSchemeWatcher(app, window)
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
        sync_palette_to_color_scheme(app)
        load_style(app)
        sync_palette_to_color_scheme(app)
        panel = getattr(window, "graph_panel", None)
        if panel is not None:
            panel.apply_plot_palette()

    QTimer.singleShot(0, apply_when_ready)


if __name__ == "__main__":
    sys.exit(main())
