#!/usr/bin/env python3
"""
EBiCS UART Debug Dashboard
===========================
Real-time ncurses dashboard that connects to /dev/ttyUSB0 at 57600 baud
and parses the debug output of the EBiCS firmware.

Parsed values:
  - Phase current offsets (ph1, ph2, ph3)
  - Internal temperature raw value
  - Hall sensor order and angles
  - KV rating
  - Fast-loop CSV log: Ibus, IphA, IphB, IphC, angle, speed, Iq_setpoint, etc.

Controls:
  q        - quit
  c        - clear log
  p        - pause/resume live updates

Author: Cline
"""

import sys
import time
import curses
import serial
import threading
import re
import signal
from collections import deque
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SERIAL_PORT = "/dev/ttyUSB0"
SERIAL_BAUD = 57600
DISPLAY_REFRESH_MS = 80         # ncurses refresh interval in ms
MAX_LOG_LINES = 200             # max lines in the raw log window
BAR_WIDTH = 14                  # character width of value bars

# Unicode bar chars: index 0..8 = empty, 1/8 .. 7/8, full
BAR_CHARS = [' ', '▏', '▎', '▍', '▌', '▋', '▊', '▉', '█']
ARROW_RIGHT = '▶'
ARROW_LEFT = '◀'
GAUGE_MARKER = '●'
GAUGE_TRACK = '─'
GAUGE_CURSOR = '▼'

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------
state_lock = threading.Lock()


class DashboardState:
    """Holds all parsed values and raw log lines."""

    def __init__(self):
        self.raw_log = deque(maxlen=MAX_LOG_LINES)
        self.paused = False

        # --- Parsed startup parameters ---
        self.ph1_offset = 0
        self.ph2_offset = 0
        self.ph3_offset = 0
        self.int_temp_raw = 0
        self.hall_order = 0
        self.kv = 0
        self.hall_angles: dict[str, int] = {}

        # --- Real-time fast-loop values (from CSV log lines) ---
        # Typical CSV: Ibus, IphA, IphB, IphC, angle, speed, Iq_setpoint, ...
        self.ibus = 0.0
        self.iph_a = 0.0
        self.iph_b = 0.0
        self.iph_c = 0.0
        self.angle = 0
        self.speed_erps = 0
        self.iq_setpoint = 0.0
        self.fast_loop_counter = 0

        # --- Auto-scaling max tracking ---
        self.max_ibus = 1.0
        self.max_iph_a = 1.0
        self.max_iph_b = 1.0
        self.max_iph_c = 1.0
        self.max_speed = 1
        self.max_temp_raw = 1
        self.max_ph_offset = 1

        # --- Connection ---
        self.connected = False
        self.last_update = 0.0

    def _update_max(self, attr_max: str, value, decay: float = 0.999):
        """Track running maximum with decay so scale can shrink."""
        cur = getattr(self, attr_max)
        abs_val = abs(value)
        if abs_val > cur:
            setattr(self, attr_max, abs_val)
        else:
            # Slowly decay the max so the bar re-scales downward
            setattr(self, attr_max, max(cur * decay, 1.0))

    def update_from_line(self, line: str):
        """Parse one line of debug output."""
        line_stripped = line.strip()

        # Phase current offsets: "phase current offsets:  X, Y, Z"
        m = re.search(r"phase current offsets:\s*(-?\d+),\s*(-?\d+),\s*(-?\d+)", line)
        if m:
            self.ph1_offset = int(m.group(1))
            self.ph2_offset = int(m.group(2))
            self.ph3_offset = int(m.group(3))
            off_max = max(abs(self.ph1_offset), abs(self.ph2_offset), abs(self.ph3_offset))
            self._update_max('max_ph_offset', off_max)
            return

        # Internal temperature raw: "internal temperature raw reading:  X,"
        m = re.search(r"internal temperature raw reading:\s*(-?\d+)", line)
        if m:
            self.int_temp_raw = int(m.group(1))
            self._update_max('max_temp_raw', self.int_temp_raw)
            return

        # Hall order: "Hall_Order: X"
        m = re.search(r"Hall_Order:\s*(-?\d+)", line)
        if m:
            self.hall_order = int(m.group(1))
            return

        # Hall angles (degrees integer form): "Hall_45: -1234"
        m = re.search(r"Hall_(\d+):\s*(-?\d+)", line)
        if m:
            key = f"Hall_{m.group(1)}"
            self.hall_angles[key] = int(m.group(2))
            return

        # KV value: "KV: X"
        m = re.search(r"KV:\s*(-?\d+)", line)
        if m:
            self.kv = int(m.group(1))
            return

        # Fast-loop CSV log (comma-separated integers)
        # Format from firmware: "%d, %d, %d, %d, %d, %d\r\n"
        #   e_log[k][0..5] = Ibus, IphA, IphB, IphC, angle, speed (or similar)
        # But we also see longer lines with more fields.
        parts = [p.strip() for p in line_stripped.split(",") if p.strip()]
        if len(parts) >= 6 and all(p.lstrip("-").isdigit() for p in parts[:6]):
            try:
                self.ibus = int(parts[0])
                self.iph_a = int(parts[1])
                self.iph_b = int(parts[2])
                self.iph_c = int(parts[3])
                self.angle = int(parts[4])
                self.speed_erps = int(parts[5])
                if len(parts) >= 7:
                    self.iq_setpoint = int(parts[6])
                self.fast_loop_counter += 1

                # Update max tracking with decay
                self._update_max('max_ibus', self.ibus, 0.995)
                self._update_max('max_iph_a', self.iph_a, 0.995)
                self._update_max('max_iph_b', self.iph_b, 0.995)
                self._update_max('max_iph_c', self.iph_c, 0.995)
                self._update_max('max_speed', self.speed_erps, 0.995)
            except (ValueError, IndexError):
                pass
            return

        # Version banner
        if "Lishui FOC v" in line:
            return

        # Battery voltage warning
        m = re.search(r"Battery voltage too low!:\s*(-?\d+)", line)
        if m:
            return

    @property
    def age(self) -> float:
        return time.time() - self.last_update


# ---------------------------------------------------------------------------
# Serial reader thread
# ---------------------------------------------------------------------------
def serial_reader(ser: serial.Serial, state: DashboardState, running: threading.Event):
    """Read lines from the serial port and update state."""
    buf = bytearray()
    while running.is_set():
        try:
            # Read whatever is available
            chunk = ser.read(ser.in_waiting or 1)
            if not chunk:
                time.sleep(0.005)
                continue

            buf.extend(chunk)

            # Process complete lines (terminated by \n)
            while b"\n" in buf:
                idx = buf.index(b"\n")
                line_bytes = bytes(buf[:idx])
                del buf[: idx + 1]

                # Strip \r and other control chars except newline
                line = line_bytes.decode("utf-8", errors="replace")
                line = line.replace("\r", "")
                # Remove backspace characters and anything before them in a simple way
                while "\b" in line:
                    pos = line.index("\b")
                    if pos > 0:
                        line = line[: pos - 1] + line[pos + 1 :]
                    else:
                        line = line[pos + 1 :]
                # Remove any remaining non-printable chars (except whitespace)
                line = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", line)
                line = line.strip()

                if not line:
                    continue

                with state_lock:
                    state.raw_log.append(line)
                    state.update_from_line(line)
                    state.last_update = time.time()

        except serial.SerialException:
            with state_lock:
                state.connected = False
            time.sleep(0.5)
        except Exception:
            time.sleep(0.1)


# ---------------------------------------------------------------------------
# ncurses UI helpers
# ---------------------------------------------------------------------------
def draw_bar(stdscr, y: int, x: int, width: int, value: float,
             max_value: float, color_pair: int, show_value: bool = True):
    """Draw a horizontal bar representing value/max_value at (y, x).

    Uses Unicode block characters for smooth rendering.
    """
    if max_value <= 0:
        max_value = 1.0
    fraction = min(abs(value) / max_value, 1.0)
    filled = fraction * width
    full_count = int(filled)
    frac_part = filled - full_count
    frac_index = int(round(frac_part * 8))

    bar_str_parts = []

    # Draw full blocks
    bar_str_parts.append(BAR_CHARS[8] * full_count)

    # Draw partial block
    if full_count < width:
        bar_str_parts.append(BAR_CHARS[frac_index])

    # Draw remaining empty space
    empty_count = width - full_count - (1 if full_count < width else 0)
    if empty_count > 0:
        bar_str_parts.append(' ' * empty_count)

    bar_str = ''.join(bar_str_parts)

    # Determine bar color: green for low, yellow for mid, red for high
    if fraction > 0.85:
        bar_color = curses.color_pair(4)  # red
    elif fraction > 0.6:
        bar_color = curses.color_pair(6)  # magenta as warning
    else:
        bar_color = curses.color_pair(color_pair)

    stdscr.attron(bar_color)
    try:
        stdscr.addstr(y, x, bar_str)
    except curses.error:
        pass
    stdscr.attroff(bar_color)

    if show_value:
        val_str = f"{value:>6d}" if isinstance(value, int) else f"{value:>7.1f}"
        stdscr.attron(curses.color_pair(2))
        try:
            stdscr.addstr(y, x + width + 1, val_str)
        except curses.error:
            pass
        stdscr.attroff(curses.color_pair(2))


def draw_angle_gauge(stdscr, y: int, x: int, width: int, angle_deg: int):
    """Draw a rotor angle gauge: ◀──────●────────▶ with marker at angle position."""
    # Normalize angle to 0-360
    angle_norm = angle_deg % 360
    fraction = angle_norm / 360.0
    pos = int(round(fraction * (width - 1)))
    pos = max(0, min(width - 1, pos))

    gauge_str = list(' ' * width)
    # Draw track
    for i in range(width):
        gauge_str[i] = GAUGE_TRACK

    # Draw marker
    gauge_str[pos] = GAUGE_CURSOR

    # Draw end markers
    gauge_str[0] = ARROW_LEFT
    gauge_str[width - 1] = ARROW_RIGHT

    gauge_line = ''.join(gauge_str)

    # Angle value display
    stdscr.attron(curses.color_pair(3))
    try:
        stdscr.addstr(y, x, f"Angle  ")
    except curses.error:
        pass
    stdscr.attroff(curses.color_pair(3))

    stdscr.attron(curses.color_pair(2))
    try:
        stdscr.addstr(y, x + 7, f"{angle_norm:3d}° ")
    except curses.error:
        pass
    stdscr.attroff(curses.color_pair(2))

    stdscr.attron(curses.color_pair(6))
    try:
        stdscr.addstr(y, x + 12, gauge_line)
    except curses.error:
        pass
    stdscr.attroff(curses.color_pair(6))


# ---------------------------------------------------------------------------
# ncurses UI
# ---------------------------------------------------------------------------
def draw_dashboard(stdscr, state: DashboardState):
    """Redraw the entire dashboard."""
    stdscr.erase()

    # Color pairs
    curses.init_pair(1, curses.COLOR_CYAN, curses.COLOR_BLACK)    # headers
    curses.init_pair(2, curses.COLOR_GREEN, curses.COLOR_BLACK)   # values / connected
    curses.init_pair(3, curses.COLOR_YELLOW, curses.COLOR_BLACK)  # labels
    curses.init_pair(4, curses.COLOR_RED, curses.COLOR_BLACK)     # warning / disconnected
    curses.init_pair(5, curses.COLOR_WHITE, curses.COLOR_BLUE)    # title bar
    curses.init_pair(6, curses.COLOR_MAGENTA, curses.COLOR_BLACK) # gauge / paused
    curses.init_pair(7, curses.COLOR_CYAN, curses.COLOR_BLACK)    # bar fill (reused)

    rows, cols = stdscr.getmaxyx()
    if rows < 10 or cols < 60:
        stdscr.addstr(0, 0, "Terminal too small (need >=60x10)")
        stdscr.refresh()
        return

    with state_lock:
        conn = state.connected
        paused = state.paused
        ph1, ph2, ph3 = state.ph1_offset, state.ph2_offset, state.ph3_offset
        t_raw = state.int_temp_raw
        h_order = state.hall_order
        kv_val = state.kv
        hall_angles = dict(state.hall_angles)
        ibus = state.ibus
        iph_a = state.iph_a
        iph_b = state.iph_b
        iph_c = state.iph_c
        angle = state.angle
        speed = state.speed_erps
        iq_sp = state.iq_setpoint
        fc = state.fast_loop_counter
        log_lines = list(state.raw_log)
        age = state.age

        # Max values for scaling
        m_ibus = state.max_ibus
        m_iph_a = state.max_iph_a
        m_iph_b = state.max_iph_b
        m_iph_c = state.max_iph_c
        m_speed = state.max_speed
        m_temp = state.max_temp_raw
        m_ph_off = state.max_ph_offset

    # ---- Title bar ----
    title = " EBiCS UART Debug Dashboard "
    stdscr.attron(curses.color_pair(5))
    stdscr.addstr(0, 0, f" {title:^{cols-2}} ")
    stdscr.attroff(curses.color_pair(5))

    # ---- Line 1: Connection status + pause ----
    status_color = curses.color_pair(2) if conn else curses.color_pair(4)
    status_text = "CONNECTED" if conn else "DISCONNECTED"
    stdscr.attron(status_color | curses.A_BOLD)
    stdscr.addstr(1, 2, f"[ {status_text} ]  {SERIAL_PORT} @ {SERIAL_BAUD}")
    stdscr.attroff(status_color | curses.A_BOLD)
    if conn:
        stdscr.addstr(1, 42, f"  Age: {age:.1f}s  Frames: {fc}")
    if paused:
        stdscr.attron(curses.color_pair(6) | curses.A_BOLD)
        stdscr.addstr(1, cols - 14, "  PAUSED  ")
        stdscr.attroff(curses.color_pair(6) | curses.A_BOLD)

    # ---- Left column: Startup parameters with bars ----
    col1_x = 2
    y = 3
    bar_w = BAR_WIDTH

    stdscr.attron(curses.color_pair(1) | curses.A_BOLD)
    stdscr.addstr(y, col1_x, "── Startup Parameters ──")
    stdscr.attroff(curses.color_pair(1) | curses.A_BOLD)
    y += 1

    left_fields = [
        ("Phase Off 1", ph1, m_ph_off),
        ("Phase Off 2", ph2, m_ph_off),
        ("Phase Off 3", ph3, m_ph_off),
    ]
    for label, val, mx in left_fields:
        if y >= rows - 2:
            break
        stdscr.attron(curses.color_pair(3))
        stdscr.addstr(y, col1_x + 2, f"{label:12s}: ")
        stdscr.attroff(curses.color_pair(3))
        draw_bar(stdscr, y, col1_x + 15, bar_w, val, mx, 2, show_value=True)
        y += 1

    # Temperature with bar
    if y < rows - 2:
        stdscr.attron(curses.color_pair(3))
        stdscr.addstr(y, col1_x + 2, f"{'Int Temp':12s}: ")
        stdscr.attroff(curses.color_pair(3))
        draw_bar(stdscr, y, col1_x + 15, bar_w, t_raw, m_temp, 2, show_value=True)
        y += 1

    if y < rows - 2:
        stdscr.attron(curses.color_pair(3))
        stdscr.addstr(y, col1_x + 2, f"{'Hall Order':12s}: ")
        stdscr.attroff(curses.color_pair(3))
        stdscr.attron(curses.color_pair(2))
        stdscr.addstr(f"{h_order}")
        stdscr.attroff(curses.color_pair(2))
        y += 1

    if y < rows - 2:
        stdscr.attron(curses.color_pair(3))
        stdscr.addstr(y, col1_x + 2, f"{'KV':12s}: ")
        stdscr.attroff(curses.color_pair(3))
        stdscr.attron(curses.color_pair(2))
        stdscr.addstr(f"{kv_val}")
        stdscr.attroff(curses.color_pair(2))
        y += 1

    # ---- Right column: Real-time values with bars ----
    col2_x = max(40, cols // 2 - 2)
    if col2_x + bar_w + 20 < cols:
        y_rt = 3
        stdscr.attron(curses.color_pair(1) | curses.A_BOLD)
        stdscr.addstr(y_rt, col2_x, "── Real-Time ──")
        stdscr.attroff(curses.color_pair(1) | curses.A_BOLD)
        y_rt += 1

        rt_fields = [
            ("Ibus", ibus, m_ibus),
            ("Iph A", iph_a, m_iph_a),
            ("Iph B", iph_b, m_iph_b),
            ("Iph C", iph_c, m_iph_c),
        ]
        for label, val, mx in rt_fields:
            if y_rt >= rows - 2:
                break
            stdscr.attron(curses.color_pair(3))
            stdscr.addstr(y_rt, col2_x + 2, f"{label:7s}: ")
            stdscr.attroff(curses.color_pair(3))
            draw_bar(stdscr, y_rt, col2_x + 10, bar_w, val, mx, 2, show_value=True)
            y_rt += 1

        # Speed bar
        if y_rt < rows - 2:
            stdscr.attron(curses.color_pair(3))
            stdscr.addstr(y_rt, col2_x + 2, f"{'Speed':7s}: ")
            stdscr.attroff(curses.color_pair(3))
            draw_bar(stdscr, y_rt, col2_x + 10, bar_w, speed, m_speed, 2, show_value=True)
            y_rt += 1

        # Iq Setpoint as plain value
        if y_rt < rows - 2:
            stdscr.attron(curses.color_pair(3))
            stdscr.addstr(y_rt, col2_x + 2, f"{'Iq Set':7s}: ")
            stdscr.attroff(curses.color_pair(3))
            stdscr.attron(curses.color_pair(2))
            stdscr.addstr(f"{iq_sp:>10.1f}")
            stdscr.attroff(curses.color_pair(2))
            y_rt += 1

        # Angle gauge
        if y_rt < rows - 2:
            gauge_width = min(26, cols - col2_x - 12)
            if gauge_width >= 10:
                draw_angle_gauge(stdscr, y_rt, col2_x + 2, gauge_width, angle)
                y_rt += 1

    # ---- Hall angles (below left column) ----
    hall_y = y + 1
    if hall_y + 3 < rows:
        stdscr.attron(curses.color_pair(1) | curses.A_BOLD)
        stdscr.addstr(hall_y, col1_x + 2, "Hall Angles:")
        stdscr.attroff(curses.color_pair(1) | curses.A_BOLD)
        hall_y += 1
        for key in sorted(hall_angles.keys()):
            if hall_y >= rows - 2:
                break
            val = hall_angles[key]
            stdscr.attron(curses.color_pair(3))
            stdscr.addstr(hall_y, col1_x + 4, f"{key:8s}: ")
            stdscr.attroff(curses.color_pair(3))
            stdscr.attron(curses.color_pair(2))
            stdscr.addstr(f"{val}")
            stdscr.attroff(curses.color_pair(2))
            hall_y += 1

    # ---- Raw log window (bottom) ----
    log_title_y = max(hall_y + 2, 16)
    if log_title_y + 3 < rows:
        stdscr.attron(curses.color_pair(1) | curses.A_BOLD)
        stdscr.addstr(log_title_y, 2, "── Raw Output ──")
        stdscr.attroff(curses.color_pair(1) | curses.A_BOLD)

        avail = rows - log_title_y - 2
        if avail > 0:
            # Show most recent lines that fit
            shown = log_lines[-avail:] if len(log_lines) > avail else log_lines
            for i, ln in enumerate(shown):
                wy = log_title_y + 1 + i
                if wy >= rows - 1:
                    break
                # Truncate to fit terminal width
                display = ln if len(ln) <= cols - 4 else ln[: cols - 7] + "..."
                # Filter out control chars for display safety
                display = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", display)
                try:
                    stdscr.addstr(wy, 2, display)
                except curses.error:
                    pass

    # ---- Footer ----
    if rows > 2:
        stdscr.attron(curses.color_pair(3))
        stdscr.addstr(rows - 1, 2, "q:quit  c:clear  p:pause")
        stdscr.attroff(curses.color_pair(3))

    stdscr.refresh()


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def main_loop(stdscr):
    curses.curs_set(0)
    stdscr.nodelay(1)
    stdscr.timeout(DISPLAY_REFRESH_MS)

    state = DashboardState()
    running = threading.Event()
    running.set()

    ser: Optional[serial.Serial] = None
    reader: Optional[threading.Thread] = None

    def open_serial():
        nonlocal ser, reader
        try:
            if ser and ser.is_open:
                ser.close()
        except Exception:
            pass
        try:
            s = serial.Serial(port=SERIAL_PORT, baudrate=SERIAL_BAUD, timeout=0)
            state.connected = True
            r = threading.Thread(target=serial_reader, args=(s, state, running), daemon=True)
            r.start()
            ser, reader = s, r
        except Exception:
            state.connected = False
            ser, reader = None, None

    open_serial()

    while True:
        # Auto-reconnect
        if not state.connected or (ser and not ser.is_open):
            time.sleep(1.0)
            open_serial()

        draw_dashboard(stdscr, state)

        key = stdscr.getch()
        if key == ord("q"):
            break
        elif key == ord("c"):
            with state_lock:
                state.raw_log.clear()
                state.fast_loop_counter = 0
        elif key == ord("p"):
            with state_lock:
                state.paused = not state.paused

    running.clear()
    if reader and reader.is_alive():
        reader.join(timeout=1.0)
    if ser and ser.is_open:
        ser.close()


def main():
    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
    try:
        curses.wrapper(main_loop)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()