"""Live USB serial capture for a generic ESP32 or Arduino.

This is not record playback. Bytes are read when Qt emits readyRead,
inside the window's event loop. The slot copies the bytes that are
already waiting and returns. It does not wait, and it does not sleep,
so the window can still repaint and handle clicks.
"""

from PyQt6.QtCore import QIODevice, pyqtSignal
from PyQt6.QtSerialPort import QSerialPort, QSerialPortInfo
from PyQt6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

BAUD_RATES = ["9600", "19200", "38400", "57600", "115200", "230400"]


class SerialPanel(QGroupBox):
    """Port list, baud rate, and Connect / Disconnect.

    The first complete line after Connect is the header. Later lines are
    comma-separated rows. ``header_received`` and ``row_received`` carry
    those cells. The window decides which data set they join.
    """

    header_received = pyqtSignal(list)
    row_received = pyqtSignal(list)
    link_changed = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self):
        super().__init__("Live serial capture")
        self.setObjectName("liveSerialPanel")
        self._port = QSerialPort(self)
        self._buffer = ""
        self._saw_header = False
        self._closing = False
        self._link_text = "Disconnected"

        intro = QLabel(
            "Gather readings from a generic ESP32 or Arduino over USB. "
            "The device should print a header line, then comma-separated rows, "
            "for example millis,temperature and then 1000,21.5. "
            "Rows are appended to the active data-set tab."
        )
        intro.setWordWrap(True)

        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(220)
        self.refresh_button = QPushButton("Refresh ports")
        self.refresh_button.clicked.connect(self.refresh_ports)

        self.baud_combo = QComboBox()
        self.baud_combo.addItems(BAUD_RATES)
        self.baud_combo.setCurrentText("115200")

        self.connect_button = QPushButton("Connect")
        self.connect_button.clicked.connect(self.connect_port)
        self.disconnect_button = QPushButton("Disconnect")
        self.disconnect_button.clicked.connect(self.disconnect_port)
        self.disconnect_button.setEnabled(False)

        self.status_label = QLabel(
            "Disconnected. Next: choose a port and baud, then press Connect."
        )
        self.status_label.setWordWrap(True)

        port_row = QHBoxLayout()
        port_row.setSpacing(10)
        port_row.addWidget(QLabel("Port"))
        port_row.addWidget(self.port_combo, stretch=1)
        port_row.addWidget(self.refresh_button)

        link_row = QHBoxLayout()
        link_row.setSpacing(10)
        link_row.addWidget(QLabel("Baud"))
        link_row.addWidget(self.baud_combo)
        link_row.addWidget(self.connect_button)
        link_row.addWidget(self.disconnect_button)
        link_row.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.addWidget(intro)
        layout.addLayout(port_row)
        layout.addLayout(link_row)
        layout.addWidget(self.status_label)

        self._port.readyRead.connect(self._read_available)
        self._port.errorOccurred.connect(self._on_port_error)
        self.refresh_ports()

    def link_text(self):
        return self._link_text

    def refresh_ports(self):
        current = self.port_combo.currentData()
        self.port_combo.blockSignals(True)
        self.port_combo.clear()
        for info in QSerialPortInfo.availablePorts():
            label = info.portName()
            description = info.description().strip()
            if description:
                label = f"{label} — {description}"
            self.port_combo.addItem(label, info.portName())
        if current:
            index = self.port_combo.findData(current)
            if index >= 0:
                self.port_combo.setCurrentIndex(index)
        self.port_combo.blockSignals(False)
        if self.port_combo.count() == 0:
            self.status_label.setText(
                "No serial ports found. Next: plug in a board, then press Refresh ports."
            )
        elif not self._port.isOpen():
            self.status_label.setText(
                "Disconnected. Next: choose a port and baud, then press Connect."
            )

    def connect_port(self):
        if self._port.isOpen():
            return
        name = self.port_combo.currentData()
        if not name:
            self.failed.emit(
                "No serial port selected. Plug in the board, then press Refresh ports."
            )
            return
        self._port.setPortName(name)
        self._port.setBaudRate(int(self.baud_combo.currentText()))
        self._port.setDataBits(QSerialPort.DataBits.Data8)
        self._port.setParity(QSerialPort.Parity.NoParity)
        self._port.setStopBits(QSerialPort.StopBits.OneStop)
        self._port.setFlowControl(QSerialPort.FlowControl.NoFlowControl)
        opened = self._port.open(QIODevice.OpenModeFlag.ReadWrite)
        if not opened:
            self.failed.emit(self._failure_text())
            return
        # Some boards stay in reset while DTR is held low. Release it so they can boot.
        self._port.setDataTerminalReady(True)
        self._buffer = ""
        self._saw_header = False
        self._set_connected(True, f"Connected to {name}")

    def disconnect_port(self):
        self._closing = True
        if self._port.isOpen():
            self._port.close()
        self._closing = False
        self._buffer = ""
        self._saw_header = False
        if self._link_text != "Disconnected":
            self._set_connected(
                False,
                "Disconnected. Next: choose a port and baud, then press Connect.",
            )

    def show_notice(self, text):
        self.status_label.setText(text)

    def _set_connected(self, connected, text):
        self._link_text = "Connected" if connected else "Disconnected"
        self.status_label.setText(text)
        self.connect_button.setEnabled(not connected)
        self.disconnect_button.setEnabled(connected)
        self.port_combo.setEnabled(not connected)
        self.baud_combo.setEnabled(not connected)
        self.refresh_button.setEnabled(not connected)
        self.link_changed.emit(self._link_text)

    def _failure_text(self):
        message = self._port.errorString() or "Could not open the serial port."
        error = self._port.error()
        permission = error == QSerialPort.SerialPortError.PermissionError
        if permission or "permission" in message.lower():
            message += (
                " Your user may need to be in the dialout group. "
                "Log out and back in after that change."
            )
        return message

    def _on_port_error(self, error):
        if self._closing or error == QSerialPort.SerialPortError.NoError:
            return
        if not self._port.isOpen() and error == QSerialPort.SerialPortError.DeviceNotFoundError:
            return
        message = self._failure_text()
        self.disconnect_port()
        self.failed.emit(message)

    def _read_available(self):
        # readyRead means bytes are already in Qt's buffer. Read them and return.
        data = self._port.readAll()
        if data.isEmpty():
            return
        self._buffer += bytes(data).decode("utf-8", errors="replace")
        self._buffer = self._buffer.replace("\r\n", "\n").replace("\r", "\n")
        if len(self._buffer) > 20000 and "\n" not in self._buffer:
            self._buffer = ""
            self.failed.emit("A serial line was extremely long and had no newline, so it was skipped.")
            return
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._handle_line(line.strip())

    def _handle_line(self, line):
        if not line:
            return
        cells = [cell.strip() for cell in line.split(",")]
        if not self._saw_header:
            self._saw_header = True
            self.header_received.emit(cells)
            return
        self.row_received.emit(cells)
