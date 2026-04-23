#!/usr/bin/env python3
import sys
import time
import serial
import signal
import argparse
from tqdm import tqdm


def signal_handler(sig, frame):
    print("\nAborted by user")
    sys.exit(1)


signal.signal(signal.SIGINT, signal_handler)


def recv_until(ser, marker, timeout=30, verbose=False):
    response = b""
    start = time.time()
    while time.time() - start < timeout:
        chunk = ser.read(ser.in_waiting or 1)
        if not chunk:
            continue
        if verbose:
            print(f"  Received {len(chunk)} bytes: {chunk.hex()}")
        response += chunk
        if marker in response:
            return response
    raise TimeoutError("Timeout waiting for marker")


try:
    parser = argparse.ArgumentParser()
    parser.add_argument("serial_port")
    parser.add_argument("lsh_file")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("-t", "--timing", action="store_true", help="Show timing details for comparison with telnet flasher")
    args = parser.parse_args()

    serial_port = args.serial_port
    lsh_path = args.lsh_file
    verbose = args.verbose
    show_timing = args.timing

    startup_message = bytes.fromhex("4D 50 43 18 0B 13 0D 28 2E")
    start_bytes = b"\x44" * 20
    end_bytes = b"\x55" * 20

    with open(lsh_path, "r") as lsh_file:
        lsh_lines = lsh_file.readlines()
        lsh_number_of_lines = len(lsh_lines)

    uart = serial.Serial(port=serial_port, baudrate=38400, timeout=None)

    print("Turn on controller now" + (" (verbose mode)" if verbose else ""))
    recv_until(uart, startup_message, verbose=verbose)
    time.sleep(0.02)

    uart.write(start_bytes)
    uart.flush()
    time.sleep(0.09)

    total_start = time.time()
    line_times = []
    
    for i, line in enumerate(tqdm(lsh_lines)):
        data = bytes.fromhex(line.strip())
        
        # Record timing if enabled
        if show_timing:
            t0 = time.time()
            
        uart.write(data)
        if (i % 64) == 0:
            uart.flush()
            time.sleep(0.03)
            
        if show_timing:
            line_times.append((time.time() - t0) * 1000)

    total_time = (time.time() - total_start) * 1000
    
    if show_timing:
        avg_line_time = sum(line_times) / len(line_times) if line_times else 0
        print(f"\n=== SERIAL FLASHER TIMING ===")
        print(f"Total time: {total_time:.2f}ms for {len(lsh_lines)} lines")
        print(f"Avg per-line: {avg_line_time:.3f}ms (expected ~4.2ms at 38400 baud)")
        print(f"Min: {min(line_times):.3f}ms, Max: {max(line_times):.3f}ms")

    uart.write(end_bytes)

    while True:
        response = uart.read_until(startup_message)
        if response[-len(startup_message) :] == startup_message:
            break
    print("Download successful")

    uart.close()

except ValueError as e:
    print("Invalid arguments!")
except TimeoutError as e:
    print("Timeout!")
