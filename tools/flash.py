#!/usr/bin/env python3
import sys
import time
import serial
import signal
import glob
from tqdm import tqdm


def signal_handler(sig, frame):
    print("\nAborted by user")
    sys.exit(1)


signal.signal(signal.SIGINT, signal_handler)


def recv_until(ser, marker, timeout=30):
    response = b""
    start = time.time()
    while time.time() - start < timeout:
        chunk = ser.read(ser.in_waiting or 1)
        if not chunk:
            continue
        response += chunk
        if marker in response:
            return response
    raise TimeoutError("Timeout waiting for marker")


# Find serial port
serial_ports = glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*")
if not serial_ports:
    print("No serial device found")
    sys.exit(1)

serial_port = serial_ports[0]
lsh_path = "output/EBiCS_Firmware.lsh"

startup_message = bytes.fromhex("4D 50 43 18 0B 13 0D 28 2E")
start_bytes = b"\x44" * 20
end_bytes = b"\x55" * 20

with open(lsh_path, "r") as lsh_file:
    lsh_lines = lsh_file.readlines()

uart = serial.Serial(port=serial_port, baudrate=38400, timeout=None)

print(f"Using {serial_port}")
print("Turn on controller now")

recv_until(uart, startup_message)
time.sleep(0.02)

uart.write(start_bytes)
uart.flush()
time.sleep(0.09)

for i, line in enumerate(tqdm(lsh_lines)):
    data = bytes.fromhex(line.strip())
    uart.write(data)
    if (i % 64) == 0:
        uart.flush()
        time.sleep(0.06)

uart.write(end_bytes)

while True:
    response = uart.read_until(startup_message)
    if response[-len(startup_message):] == startup_message:
        break
print("Download successful")

uart.close()
