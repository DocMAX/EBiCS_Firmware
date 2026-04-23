#!/usr/bin/env python3
import sys
import time
import socket
import select
import signal
import argparse
import subprocess
from tqdm import tqdm


def signal_handler(sig, frame):
    print("\nAborted by user")
    sys.exit(1)


signal.signal(signal.SIGINT, signal_handler)


def drain(sock):
    start = time.time()
    while time.time() - start < 0.005:
        ready, _, _ = select.select([sock], [], [], 0.001)
        if ready:
            sock.recv(4096)
            # Drain all available
            while True:
                ready, _, _ = select.select([sock], [], [], 0)
                if not ready:
                    break
                sock.recv(4096)
            break

def recv_until(sock, marker, timeout=30, verbose=False):
    response = b""
    start_time = time.time()
    while True:
        ready, _, _ = select.select([sock], [], [], timeout)
        if not ready:
            if time.time() - start_time >= timeout:
                raise TimeoutError("Timeout waiting for marker")
            continue
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("Connection closed")
        if verbose:
            print(f"  Received {len(chunk)} bytes: {chunk.hex()}")
        response += chunk
        if marker in response:
            return response


try:
    parser = argparse.ArgumentParser()
    parser.add_argument("ip_address")
    parser.add_argument("lsh_file")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("-d", "--delay", type=float, default=0.0, help="Delay between lines in seconds (default: 0.0, to match serial speed)")
    parser.add_argument("-t", "--timing", action="store_true", help="Show timing details for comparison with serial flasher")
    args = parser.parse_args()

    ip_address = args.ip_address
    lsh_path = args.lsh_file
    verbose = args.verbose
    show_timing = args.timing

    startup_message = bytes.fromhex("4D 50 43 18 0B 13 0D 28 2E")
    start_bytes = b"\x44" * 20
    end_bytes = b"\x55" * 20

    with open(lsh_path, "r") as lsh_file:
        lsh_lines = lsh_file.readlines()

    uart = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # Disable Nagle's algorithm - critical for timing-sensitive flashing
    uart.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    # Small send buffer to prevent kernel buffering delays
    uart.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
    uart.settimeout(30)

    print(f"Checking if {ip_address} is reachable...")
    try:
        ping_result = subprocess.run(
            ["ping", "-c", "1", "-W", "2", ip_address],
            capture_output=True,
            text=True
        )
        if ping_result.returncode != 0:
            print(f"Error: {ip_address} is not responding to ping.")
            print("This indicates network issues or the controller is off.")
            sys.exit(1)
    except Exception as e:
        print(f"Warning: Could not ping {ip_address}: {e}")
        print("Continuing anyway...\n")

    print("Turn on controller now" + (" (verbose mode)" if verbose else ""))
    while True:
        try:
            uart.connect((ip_address, 1004))
            break
        except Exception as e:
            time.sleep(1)

    # Wait for startup message (controller bootloader at 38400 baud)
    recv_until(uart, startup_message, verbose=verbose)
    time.sleep(0.02)

    # Send start command
    uart.sendall(start_bytes)
    time.sleep(0.09)

    total_start = time.time()
    line_times = []
    
    for i, line in enumerate(tqdm(lsh_lines)):
        data = bytes.fromhex(line.strip())
        
        # Record timing if enabled
        if show_timing:
            t0 = time.time()
            
        # Send entire line at once (like serial does - hardware handles FIFO)
        uart.sendall(data)
        
        if show_timing:
            line_times.append((time.time() - t0) * 1000)

        # Drain ACK and echo bytes to prevent buffer overflow over wifi
        drain(uart)

        # Wait exactly the time it takes to transmit one line at 38400 baud
        time.sleep(args.delay)

        # Extra delay every 64 lines like serial flush()
        if (i % 64) == 0:
            time.sleep(0.05)

    total_time = (time.time() - total_start) * 1000
    
    if show_timing:
        avg_line_time = sum(line_times) / len(line_times) if line_times else 0
        print(f"\n=== TELNET FLASHER TIMING ===")
        print(f"Total time: {total_time:.2f}ms for {len(lsh_lines)} lines")
        print(f"Avg per-line: {avg_line_time:.3f}ms (expected ~4.2ms at 38400 baud)")
        print(f"Min: {min(line_times):.3f}ms, Max: {max(line_times):.3f}ms")

    # Drain any remaining data before sending end command
    drain(uart)

    # Send end command
    uart.sendall(end_bytes)
    time.sleep(0.1)

    # Wait for controller to reboot and send startup message.
    # The ESP32 forwards ALL UART data including echo, so we scan
    # through it for the startup message marker.
    while True:
        try:
            response = recv_until(uart, startup_message, timeout=2, verbose=verbose)
            if startup_message in response:
                break
        except TimeoutError:
            continue
    print("Download successful")

    uart.close()

except ValueError as e:
    print("Invalid arguments!")
except TimeoutError as e:
    print(f"Error: {e}")
except ConnectionError as e:
    print(f"Error: {e}")
