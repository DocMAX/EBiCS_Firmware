#!/usr/bin/env python3
"""
EBiCS Graphical Dashboard
=========================
Real-time dashboard that connects to /dev/ttyUSB0 at 57600 baud
and displays the debug values from firmware.

Parsed values (from main.c:1114-1133):
  - i16_60deg_Hall_flag
  - ui8_hall_state
  - uint32_PAS
  - MS.Battery_Current
  - i16_ph_current_abs
  - int32_temp_current_target
  - MS.i_q
  - MS.u_abs
  - SystemState
  - ui16_torque
  - ui16_throttle
  - MS.Speed
  - ui16_speed_kmh
"""

import sys
import time
import threading
import signal
from typing import Optional

import serial
from PyQt5 import QtCore, QtWidgets

SERIAL_PORT = "/dev/ttyUSB0"
SERIAL_BAUD = 57600
UPDATE_INTERVAL_MS = 50

FIELDS = [
    ("i16_60deg_Hall_flag", "Hall Flag", "hall_flag"),
    ("ui8_hall_state", "Hall State", "hall_state"),
    ("uint32_PAS", "PAS", "pas"),
    ("MS.Battery_Current", "Battery Current", "battery_current"),
    ("i16_ph_current_abs", "PH Current", "ph_current"),
    ("int32_temp_current_target", "Temp Current Target", "temp_current_target"),
    ("MS.i_q", "Iq", "iq"),
    ("MS.u_abs", "U Abs", "u_abs"),
    ("SystemState", "System State", "system_state"),
    ("ui16_torque", "Torque", "torque"),
    ("ui16_throttle", "Throttle", "throttle"),
    ("MS.Speed", "Speed", "speed"),
    ("ui16_speed_kmh", "Speed km/h", "speed_kmh"),
]

state_lock = threading.Lock()


class DashboardState:
    def __init__(self):
        self.connected = False
        self.last_update = 0.0

        for _, _, attr in FIELDS:
            setattr(self, attr, 0)
            setattr(self, f"max_{attr}", 1.0)

    def _update_max(self, attr_max: str, value: int, decay: float = 0.995):
        cur = getattr(self, attr_max)
        abs_val = abs(value)
        if abs_val > cur:
            setattr(self, attr_max, float(abs_val))
        else:
            setattr(self, attr_max, max(cur * decay, 1.0))

    def update_from_line(self, line: str):
        line_stripped = line.strip()
        parts = [p.strip() for p in line_stripped.split(",") if p.strip()]

        if len(parts) < len(FIELDS):
            return

        try:
            values = [int(p) for p in parts[: len(FIELDS)]]
        except ValueError:
            return

        for (_, _, attr), value in zip(FIELDS, values):
            setattr(self, attr, value)
            self._update_max(f"max_{attr}", value)

        self.last_update = time.time()


def serial_reader(ser: serial.Serial, state: DashboardState, running: threading.Event):
    buf = bytearray()

    while running.is_set():
        try:
            chunk = ser.read(ser.in_waiting or 1)
            if not chunk:
                time.sleep(0.005)
                continue

            buf.extend(chunk)

            while b"\n" in buf:
                idx = buf.index(b"\n")
                line_bytes = bytes(buf[:idx])
                del buf[: idx + 1]
                line = line_bytes.decode("utf-8", errors="replace").replace("\r", "").strip()

                if not line:
                    continue

                with state_lock:
                    state.update_from_line(line)

        except serial.SerialException:
            with state_lock:
                state.connected = False
            time.sleep(0.5)
        except Exception:
            time.sleep(0.1)


class ValueCard(QtWidgets.QWidget):
    def __init__(self, title: str, source_field: str, parent=None):
        super().__init__(parent)
        self.title = title
        self.source_field = source_field
        self.value = 0
        self.max_value = 1.0
        self.setObjectName("card")
        self.setProperty("class", "card")
        self._setup_ui()

    def _setup_ui(self):
        self.layout = QtWidgets.QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        self.title_label = QtWidgets.QLabel(self.title)
        self.title_label.setObjectName("title_label")
        self.value_label = QtWidgets.QLabel("--")
        self.value_label.setObjectName("value_label")
        self.value_label.setAlignment(QtCore.Qt.AlignCenter)

        self.bar = QtWidgets.QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setRange(0, 1000)
        self.bar.setValue(0)

        self.source_label = QtWidgets.QLabel(self.source_field)
        self.source_label.setObjectName("source_label")
        self.source_label.setAlignment(QtCore.Qt.AlignCenter)

        self.layout.addWidget(self.title_label)
        self.layout.addWidget(self.value_label, 1)
        self.layout.addWidget(self.bar)
        self.layout.addWidget(self.source_label)

    def update_style(self, scale: float):
        self.scale = scale
        self.setStyleSheet(
            "QWidget#card {"
            "background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #171b2f, stop:1 #0d1020);"
            "border: 3px solid #2b3550;"
            "border-radius: 26px;"
            "padding: 22px;"
            "}"
        )

        self.title_label.setStyleSheet(
            f"font-family: DejaVu Sans Mono, Consolas, monospace; "
            f"color: #9fb0d0; "
            f"font-size: {int(28 * scale)}px; "
            f"font-weight: 700;"
        )
        self.value_label.setStyleSheet(
            f"font-family: DejaVu Sans Mono, Consolas, monospace; "
            f"color: #ffffff; "
            f"font-size: {int(100 * scale)}px; "
            f"font-weight: 800;"
        )
        self.source_label.setStyleSheet(
            f"font-family: DejaVu Sans Mono, Consolas, monospace; "
            f"color: #68768f; "
            f"font-size: {int(18 * scale)}px;"
        )
        self.bar.setStyleSheet(
            f"QProgressBar {{ "
            f"border: none; border-radius: {int(14 * scale)}px; "
            f"background: #151a2b; height: {int(42 * scale)}px; "
            f"}}"
            f"QProgressBar::chunk {{ "
            f"background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #00d4ff, stop:0.6 #00ff88, stop:1 #ffcc00); "
            f"border-radius: {int(14 * scale)}px;"
            f"}}"
        )

    def setValue(self, value: int, max_value: float):
        self.value = value
        self.max_value = max(max_value, 1.0)
        fraction = min(abs(self.value) / self.max_value, 1.0)
        self.bar.setValue(int(fraction * 1000))
        self.value_label.setText(f"{self.value:,}")


class DashboardWindow(QtWidgets.QWidget):
    def __init__(self, state: DashboardState):
        super().__init__()
        self.state = state
        self.running = threading.Event()
        self.running.set()
        self.ser: Optional[serial.Serial] = None
        self.reader_thread: Optional[threading.Thread] = None

        self.setWindowTitle("EBiCS UART Values")
        self.scale = 2.5
        self._fit_to_screen()
        self._setup_ui()
        self._setup_serial()

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._update_dashboard)
        self.timer.start(UPDATE_INTERVAL_MS)

        self.timer.singleShot(100, self._apply_styles)

    def _fit_to_screen(self):
        screen = QtWidgets.QApplication.primaryScreen().availableGeometry()
        self.scale = max(1.0, min(screen.width(), screen.height()) / 1080.0)
        width = int(screen.width() * 0.96)
        height = int(screen.height() * 0.96)
        self.setGeometry(screen.left(), screen.top(), width, height)
        self.setMinimumSize(1024, 600)

    def _setup_ui(self):
        self.root_layout = QtWidgets.QVBoxLayout(self)
        self.root_layout.setContentsMargins(18, 18, 18, 18)
        self.root_layout.setSpacing(18)

        self.status_label = QtWidgets.QLabel("DISCONNECTED  /dev/ttyUSB0 @ 57600")
        self.status_label.setAlignment(QtCore.Qt.AlignCenter)
        self.root_layout.addWidget(self.status_label)

        self.grid = QtWidgets.QGridLayout()
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(18)
        self.root_layout.addLayout(self.grid, 1)

        self.cards = {}
        for title, source_field, attr in FIELDS:
            card = ValueCard(title, source_field)
            self.cards[attr] = card

        columns = self._column_count()
        for index, (_, _, attr) in enumerate(FIELDS):
            row = index // columns
            column = index % columns
            self.grid.addWidget(self.cards[attr], row, column)

    def _column_count(self) -> int:
        screen = QtWidgets.QApplication.primaryScreen().availableGeometry()

        if screen.width() >= 3840 and screen.height() >= 1200:
            return 4
        if screen.width() >= 2560 and screen.height() >= 1000:
            return 3
        if screen.width() >= 1440:
            return 2
        return 1

    def _apply_styles(self):
        screen = QtWidgets.QApplication.primaryScreen().availableGeometry()
        scale = max(1.0, min(screen.width(), screen.height()) / 1080.0)

        self.root_layout.setContentsMargins(int(18 * scale), int(18 * scale), int(18 * scale), int(18 * scale))
        self.root_layout.setSpacing(int(18 * scale))
        self.grid.setSpacing(int(18 * scale))

        self.status_label.setStyleSheet(
            f"font-family: DejaVu Sans Mono, Consolas, monospace; "
            f"font-size: {int(24 * scale)}px; "
            f"font-weight: 700; "
            f"padding: {int(12 * scale)}px;"
        )

        for card in self.cards.values():
            card.update_style(scale)

    def _setup_serial(self):
        try:
            self.ser = serial.Serial(port=SERIAL_PORT, baudrate=SERIAL_BAUD, timeout=0)
            with state_lock:
                self.state.connected = True
            self.running.set()
            self.reader_thread = threading.Thread(
                target=serial_reader,
                args=(self.ser, self.state, self.running),
                daemon=True,
            )
            self.reader_thread.start()
        except Exception:
            with state_lock:
                self.state.connected = False
            self.ser = None

    def _update_dashboard(self):
        with state_lock:
            connected = self.state.connected
            age = time.time() - self.state.last_update
            values = {attr: getattr(self.state, attr) for _, _, attr in FIELDS}
            max_values = {attr: getattr(self.state, f"max_{attr}", 1.0) for _, _, attr in FIELDS}

        if connected:
            self.status_label.setText(f"CONNECTED  {SERIAL_PORT} @ {SERIAL_BAUD}  Age: {age:.1f}s")
            self.status_label.setStyleSheet(
                f"font-family: DejaVu Sans Mono, Consolas, monospace; "
                f"font-size: {int(24 * self.scale)}px; "
                f"font-weight: 700; color: #00ff88; "
                f"padding: {int(12 * self.scale)}px;"
            )
        else:
            self.status_label.setText(f"DISCONNECTED  {SERIAL_PORT} @ {SERIAL_BAUD}")
            self.status_label.setStyleSheet(
                f"font-family: DejaVu Sans Mono, Consolas, monospace; "
                f"font-size: {int(24 * self.scale)}px; "
                f"font-weight: 700; color: #ff4444; "
                f"padding: {int(12 * self.scale)}px;"
            )

        for _, _, attr in FIELDS:
            self.cards[attr].setValue(values[attr], max_values[attr])

    def closeEvent(self, event):
        self.running.clear()
        if self.reader_thread and self.reader_thread.is_alive():
            self.reader_thread.join(timeout=1.0)
        if self.ser and self.ser.is_open:
            self.ser.close()
        event.accept()


def main():
    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))

    state = DashboardState()
    app = QtWidgets.QApplication(sys.argv)
    app.setStyle("Fusion")
    window = DashboardWindow(state)
    window.show()
    window.showMaximized()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()