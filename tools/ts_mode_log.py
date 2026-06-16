#!/usr/bin/env python3
"""
TS_MODE debug log reader.
Reads /dev/ttyUSB0 at 57600 baud and parses the debug CSV line from main.c:
  "%d, %d, %d, %d, %d, %d, %d, %d, %d, %d, %d, %d, %d\r\n"
  0: i16_60deg_Hall_flag
  1: ui8_hall_state
  2: uint32_PAS
  3: MS.Battery_Current
  4: i16_ph_current_abs
  5: int32_temp_current_target
  6: MS.i_q
  7: MS.u_abs
  8: SystemState
  9: ui16_torque
  10: ui16_throttle
  11: MS.Speed
  12: ui16_speed_kmh

Writes output to /tmp/ts_mode_log.csv
"""

import serial
import sys
import time
import csv
import os
import signal

SERIAL_PORT = "/dev/ttyUSB0"
SERIAL_BAUD = 57600
OUTPUT_FILE = "/tmp/ts_mode_log.csv"

FIELDNAMES = [
    "timestamp",
    "hall_flag",
    "hall_state",
    "uint32_PAS",
    "battery_current",
    "ph_current_abs",
    "current_target",
    "i_q",
    "u_abs",
    "system_state",
    "torque",
    "throttle",
    "MS_Speed",
    "speed_kmh",
    "assist_level",
]

running = True

def handle_signal(sig, frame):
    global running
    running = False

signal.signal(signal.SIGINT, handle_signal)
signal.signal(signal.SIGTERM, handle_signal)

def main():
    print(f"Reading {SERIAL_PORT} @ {SERIAL_BAUD}...")
    print(f"Output: {OUTPUT_FILE}")
    print("Press Ctrl+C to stop.\n")

    try:
        ser = serial.Serial(SERIAL_PORT, SERIAL_BAUD, timeout=0)
    except Exception as e:
        print(f"Error opening serial port: {e}", file=sys.stderr)
        sys.exit(1)

    csv_fp = open(OUTPUT_FILE, "w", newline="")
    writer = csv.DictWriter(csv_fp, fieldnames=FIELDNAMES)
    writer.writeheader()

    buf = ""
    start_time = time.time()

    try:
        while running:
            chunk = ser.read(ser.in_waiting or 1)
            if not chunk:
                time.sleep(0.01)
                continue

            buf += chunk.decode("utf-8", errors="replace")

            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                line = line.strip().replace("\r", "")

                # Skip non-CSV lines
                parts = [p.strip() for p in line.split(",") if p.strip()]
                if len(parts) != 14:
                    continue

                try:
                    vals = [int(x) for x in parts]
                except ValueError:
                    continue

                elapsed = time.time() - start_time
                row = {
                    "timestamp": f"{elapsed:.3f}",
                    "hall_flag": vals[0],
                    "hall_state": vals[1],
                    "uint32_PAS": vals[2],
                    "battery_current": vals[3],
                    "ph_current_abs": vals[4],
                    "current_target": vals[5],
                    "i_q": vals[6],
                    "u_abs": vals[7],
                    "system_state": vals[8],
                    "torque": vals[9],
                    "throttle": vals[10],
                    "MS_Speed": vals[11],
                    "speed_kmh": vals[12],
                    "assist_level": vals[13],
                }
                writer.writerow(row)
                csv_fp.flush()

                # Live preview (every 50 lines)
                if int(row["timestamp"].replace(".", "")) % 50000 < 1000:
                    print(f"t={row['timestamp']}s  PAS={row['uint32_PAS']:>6d}  "
                          f"Torque={row['torque']:>5d}  Speed={row['MS_Speed']:>6d}  "
                          f"Target={row['current_target']:>6d}  Iq={row['i_q']:>6d}  "
                          f"km/h={row['speed_kmh']:.1f}  Assist={row['assist_level']}")
    except KeyboardInterrupt:
        pass
    finally:
        csv_fp.close()
        ser.close()
        print(f"\nLog saved to {OUTPUT_FILE}")
        print(f"Total lines: {sum(1 for _ in open(OUTPUT_FILE)) - 1}")

if __name__ == "__main__":
    main()
