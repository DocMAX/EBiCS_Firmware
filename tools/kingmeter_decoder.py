#!/usr/bin/env python3
"""
King-Meter 901U Protocol Decoder - Dashboard Mode
===================================================
Reads raw bytes from /dev/ttyUSB0 at 9600 baud and decodes the King-Meter
901U display protocol in a unified three-column dashboard.

The protocol frames are:
  0x3A 0x1A <Cmd> <DataSize> <Data...> <CRC_Lo> <CRC_Hi> 0x0D 0x0A

Commands:
  0x52 = Operation mode (display -> controller, during riding)
  0x53 = Settings mode (display -> controller, in settings menu)
  0x54 = DirectSetpoint (display -> controller, special)

    P01-P19 parameter mapping (from display documentation, sorted by payload byte order):
      Byte4  bit7 = PAS_DIR (P01 not in payload)
      Byte4  bit6 = P17
      Byte4  bits0-4 = P11 (PAS Sensitivity 1..24)
      Byte5        = P13 (PAS_MagType 5/8/12)
      Byte6  bit7 = P18 (Throttle)
      Byte6  bit6 = P19 (Auto)
      Byte6  bits5-6 = P12 (PAS Start Strength 0..3)
      Byte6  bits4-0 = P05/P07 (PAS_Level)
      Byte7  bit7 = HND_HL_Thr
      Byte7  bit6 = HND_HF_Thr
      Byte8  bits0-5 = P04/P14 (Auto-Off / CurLim)
      Byte9        = P10 (Drive Mode)
      Byte10       = P06/P08 (WheelSize/SpeedLim)
      Byte13-14    = P09 (Under-Voltage x10)

Features:
   - Unified three-column dashboard showing all message types simultaneously
   - Real-time refresh: clears screen and redraws latest decoded data
   - Message type counters (Op/Settings/Direct/Total)
   - Compact decoded fields for each message type

Author: DocMAX
"""

import sys
import time
import argparse
import serial
import os

SERIAL_PORT = "/dev/ttyUSB0"
SERIAL_BAUD = 9600
TIMEOUT = 0.1


def hex_dump(data: bytes, prefix="") -> str:
    """Format bytes as hex string."""
    return " ".join(f"{b:02X}" for b in data)


def decode_settings(data: bytes, prev_data: bytes = None) -> str:
    """Decode Settings mode (0x53) message with P01-P19 parameters."""
    lines = []
    if len(data) < 6:
        return "  (too short)"
    
    datasize = data[3]
    payload = data[4:4 + datasize]
    lines.append(f"  DataSize  = {datasize}")
    lines.append(f"  Raw payload: {' '.join(f'{b:02X}' for b in payload)}")
    
    if len(payload) >= 5:
        b4 = payload[0]
        b5 = payload[1]
        b6 = payload[2]
        b7 = payload[3]
        b8 = payload[4]
        
        pas_dir = (b4 >> 7) & 1
        p17 = (b4 >> 6) & 1
        pas_tolerance = b5
        p18 = (b6 >> 7) & 1
        p19 = (b6 >> 6) & 1
        reverse = (b6 >> 5) & 1
        pas_n_ratio = b6 & 0x1F
        hnd_hl = (b7 >> 7) & 1
        hnd_hf = (b7 >> 6) & 1
        slow_start = b8 & 0x3F
        cur_limit = (b8 & 0x3F) * 500
        b9 = payload[5] if len(payload) >= 6 else 0
        vol = ((payload[9] << 8) | payload[10]) if len(payload) >= 11 else 0
        
        lines.append(f"  ─── P01-P19 Parameters ───")
        lines.append(f"  P03 PAS_Dir:       {'FWD' if pas_dir == 0 else 'BWD'}  (payload[0] bit 7)")
        lines.append(f"  P17 P17:           {p17}  (payload[0] bit 6)")
        lines.append(f"  P11 PAS_Sens:      {b4 & 0x1F}  (payload[0] bits 0-4, 1..24)")
        lines.append(f"  P13 PAS_MagType:   {pas_tolerance}  (payload[1] | 5/8/12)")
        lines.append(f"  P12 PAS_StartStr:  {((b6 >> 5) & 0x03)}  (payload[2] bits 5-6, 0-3)")
        lines.append(f"  P05 PAS_Level:     {pas_n_ratio}  (payload[2] bits 4-0)")
        lines.append(f"  P18 Throttle:      {'ON' if p18 else 'OFF'}  (payload[2] bit 7)")
        lines.append(f"  P19 Auto:          {'auto' if p19 else 'fix'}  (payload[2] bit 6)")
        lines.append(f"  Reverse:           {'ON' if reverse else 'OFF'}  (payload[2] bit 5)")
        lines.append(f"  HND_HL_Thr:        {hnd_hl}  (payload[3] bit 7, kein Pxx)")
        lines.append(f"  HND_HF_Thr:        {hnd_hf}  (payload[3] bit 6, kein Pxx)")
        lines.append(f"  P04 AutoOff:       {slow_start}  (payload[4] bits 0-5, 0=off)")
        lines.append(f"  P14 CurLim:        {cur_limit}mA  (payload[4] bits 0-5, NICHT im Code)")
        lines.append(f"  P10 DriveMode:     {b9 & 0x03}  (payload[5] bits 0-1)")
        lines.append(f"  P12_alt:           {(b9 >> 2) & 0x03}  (payload[5] bits 2-3)")
        lines.append(f"  P13_alt:           {(b9 >> 4) & 0x03}  (payload[5] bits 4-5)")
        if len(payload) >= 7:
            lines.append(f"  P06 WheelSize:     {payload[6]}  (payload[6], 28\"=0xFF, 16\"=0xF8)")
        lines.append(f"  P07 MotorMag:      ???  (nicht in diesem Frame / unbekannt)")
    
    # Show each payload byte separately
    for i in range(len(payload)):
        byte_val = payload[i]
        byte_name = ""
        if i == 0:
            byte_name = "  (PAS_DIR bit7, P17 bit6, P11 bits 0-4)"
        elif i == 1:
            byte_name = "  (PAS_SCN_Tolerance)"
        elif i == 2:
            byte_name = "  (P18 bit7, P19 bit6, P12 bit5+6, PAS_N_Ratio bits 4-0)"
        elif i == 3:
            byte_name = "  (HND_HL bit7, HND_HF bit6, rest bits 5-0)"
        elif i == 4:
            byte_name = "  (SYS_SSP_SlowStart bits 5-0, CUR_Limit bits 0-5)"
        elif i == 5:
            byte_name = "  (P10 bits 0-1, P12 bits 2-3, P13 bits 4-5, P14 bits 6-7)"
        elif i == 6:
            byte_name = "  (SPEEDMAX_Limit)"
        elif i == 7:
            byte_name = "  (WheelSize high byte)"
        elif i == 8:
            byte_name = "  (WheelSize low byte)"
        elif i == 9:
            byte_name = "  (VOL_1_UnderVolt high byte)"
        elif i == 10:
            byte_name = "  (VOL_1_UnderVolt low byte)"
        else:
            byte_name = "  (unknown)"
        lines.append(f"  Byte[{4+i}] (payload[{i}]): 0x{byte_val:02X}  {byte_name}")
    
    # Show P10-P13 from payload[5] if present
    if len(payload) >= 6:
        b9 = payload[5]
        p10 = b9 & 0x03
        p12 = (b9 >> 2) & 0x03
        p13 = (b9 >> 4) & 0x03
        lines.append(f"  Byte[9] (payload[5]) details:")
        lines.append(f"    bits0-1 P10:       {p10}  (Drive Mode)")
        lines.append(f"    bits2-3 P12_alt:   {p12}  (PAS Start Str)")
        lines.append(f"    bits4-5 P13:       {p13}  (PAS Mag Type)")
    
    # Show P12 from payload[2] bits 5-6 if present (confirmed by raw frames)
    if len(payload) >= 3:
        b6 = payload[2]
        p12_b6 = ((b6 >> 5) & 1) * 2 + ((b6 >> 6) & 1)
        lines.append(f"  P12 (payload[2]): {p12_b6}  (bits 5-6: bit5=val2, bit6=val1)")
    
    # Show diff with previous message
    if prev_data is not None and len(prev_data) >= 6 and len(payload) > 0:
        prev_datasize = prev_data[3]
        prev_payload = prev_data[4:4 + prev_datasize]
        max_len = max(len(payload), len(prev_payload))
        diff_found = False
        for i in range(max_len):
            old = prev_payload[i] if i < len(prev_payload) else None
            new = payload[i] if i < len(payload) else None
            if old != new:
                diff_found = True
                old_s = f"{old:02X}" if old is not None else "  --"
                new_s = f"{new:02X}" if new is not None else "  --"
                lines.append(f"  *** CHANGED byte[{i}]: {old_s} -> {new_s}")
        if not diff_found:
            lines.append(f"  (no changes)")
    
    return "\n".join(lines)


def decode_all(data: bytes, prev_data: bytes = None) -> str:
    """Decode any message type (0x52, 0x53, 0x54)."""
    lines = []
    if len(data) < 6:
        return "  (too short)"

    datasize = data[3]
    payload = data[4:4 + datasize]
    lines.append(f"  DataSize  = {datasize}")
    lines.append(f"  Raw payload: {hex_dump(payload)}")

    cmd = data[2]
    
    if cmd == 0x53:
        # Settings mode
        lines.append("  ─── Settings mode (P01-P19) ───")
    if len(payload) >= 5:
        b4 = payload[0]
        b5 = payload[1]
        b6 = payload[2]
        b7 = payload[3]
        b8 = payload[4]

        pas_dir = (b4 >> 7) & 1
        p17 = (b4 >> 6) & 1
        bits4_rest = b4 & 0x3F

        pas_tolerance = b5

        p18 = (b6 >> 7) & 1
        p19 = (b6 >> 6) & 1
        reverse = (b6 >> 5) & 1
        pas_n_ratio = b6 & 0x1F

        hnd_hl = (b7 >> 7) & 1
        hnd_hf = (b7 >> 6) & 1
        bits7_rest = b7 & 0x3F

        slow_start = b8 & 0x3F
        cur_limit = (b8 & 0x3F) * 500

        lines.append("  ─── P01-P19 Parameters ───")
        lines.append(f"  P01 PAS_Dir:       {pas_dir} ({'FWD' if pas_dir == 0 else 'BWD'})  (payload[0] bit 7)")
        lines.append(f"  P02 PAS_Tol:       {pas_tolerance}  (payload[1])")
        lines.append(f"  P03 PAS_N_Ratio:   {pas_n_ratio}  (payload[2] bits 4-0)")
        lines.append(f"  P04 SlowStart:     {slow_start}  (payload[4] bits 0-5)")
        lines.append(f"  P05 SpdMagnets:    {b8 & 0x3F}  (payload[4])")
        lines.append(f"  P07 SpeedMaxLim:   {b8 & 0x3F}  (payload[6])")
        lines.append(f"  P08 CurLimit:      {cur_limit}mA  (payload[4] * 500)")
        lines.append(f"  P17 P17_Function:  {p17}  (payload[0] bit 6)")
        lines.append(f"  P18 P18_Throttle:  {'ON' if p18 else 'OFF'}  (payload[2] bit 7)")
        lines.append(f"  P19 P19_Auto:      {'auto' if p19 else 'fix'}  (payload[2] bit 6)")
        lines.append(f"  ─── Other Fields ───")
        lines.append(f"  Reverse:           {'ON' if reverse else 'OFF'}  (payload[2] bit 5)")
        lines.append(f"  Hnd_HL_Thr:        {hnd_hl}  (payload[3] bit 7)")
        lines.append(f"  Hnd_HF_Thr:        {hnd_hf}  (payload[3] bit 6)")
        lines.append(f"  PAS_SCN_Tol:       {pas_tolerance}  (payload[1])")

        # Show each payload byte separately
        for i in range(len(payload)):
            byte_val = payload[i]
            byte_name = ""
            if i == 0:
                byte_name = "  (DIR bit7, P17 bit6, rest bits 5-0)"
            elif i == 1:
                byte_name = "  (PAS_SCN_Tolerance)"
            elif i == 2:
                byte_name = "  (P18 bit7, P19 bit6, Reverse bit5, PAS_N_Ratio bits 4-0)"
            elif i == 3:
                byte_name = "  (HND_HL bit7, HND_HF bit6, rest bits 5-0)"
            elif i == 4:
                byte_name = "  (SYS_SSP_SlowStart bits 5-0, CUR_Limit bits 0-5)"
            elif i == 5:
                byte_name = "  (SPS_SpdMagnets)"
            elif i == 6:
                byte_name = "  (SPEEDMAX_Limit)"
            elif i == 7:
                byte_name = "  (WheelSize high byte)"
            elif i == 8:
                byte_name = "  (WheelSize low byte)"
            elif i == 9:
                byte_name = "  (VOL_1_UnderVolt high byte)"
            elif i == 10:
                byte_name = "  (VOL_1_UnderVolt low byte)"
            else:
                byte_name = "  (unknown)"
            lines.append(f"  Byte[{4+i}] (payload[{i}]): 0x{byte_val:02X}  {byte_name}")

    elif cmd == 0x52:
        # Operation mode
        lines.append("  ─── Operation mode ───")
        if len(payload) >= 2:
            assist_level = payload[0]
            status = payload[1]
            headlight = (status >> 6) & 3
            battery = (status >> 5) & 1
            pushassist = (status >> 4) & 1
            powerassist = (status >> 3) & 1
            throttle = (status >> 2) & 1
            cruise = (status >> 1) & 1
            overspeed = status & 1

            lines.append(f"  AssistLevel  = {assist_level}")
            lines.append(f"  Headlight    = {headlight}")
            lines.append(f"  Battery      = {'LOW' if battery else 'OK'}")
            lines.append(f"  PushAssist   = {'ON' if pushassist else 'OFF'}")
            lines.append(f"  PowerAssist  = {'ON' if powerassist else 'OFF'}")
            lines.append(f"  Throttle     = {'ON' if throttle else 'OFF'}")
            lines.append(f"  CruiseControl= {'ON' if cruise else 'OFF'}")
            lines.append(f"  OverSpeed    = {'YES' if overspeed else 'NO'}")

    elif cmd == 0x54:
        # DirectSetpoint mode
        lines.append("  ─── DirectSetpoint mode ───")
        if len(payload) >= 1:
            lines.append(f"  DirectSetpoint = {payload[0]}")

    # Show diff with previous message
    if prev_data is not None and len(prev_data) >= 6:
        prev_datasize = prev_data[3]
        prev_payload = prev_data[4:4 + prev_datasize]
        max_len = max(len(payload), len(prev_payload))
        diff_found = False
        for i in range(max_len):
            old = prev_payload[i] if i < len(prev_payload) else None
            new = payload[i] if i < len(payload) else None
            if old != new:
                diff_found = True
                old_s = f"{old:02X}" if old is not None else "  --"
                new_s = f"{new:02X}" if new is not None else "  --"
                lines.append(f"  *** CHANGED byte[{i}]: {old_s} -> {new_s}")
        if not diff_found:
            lines.append(f"  (no changes)")

    return "\n".join(lines)





def clear_screen():
    """Clear terminal screen for real-time refresh."""
    os.system('cls' if os.name == 'nt' else 'clear')


def print_dashboard(op_data, settings_data, direct_data, timestamp, counts):
    """Print vertical dashboard with all message types stacked."""
    clear_screen()
    print(f"King-Meter 901U Protocol Decoder  [DASHBOARD]  Press Ctrl+C to quit")
    print(f"P01-Backlight  P02-MileUnit  P03-VoltClass  P04-AutoOff  P05-PAS_Level  P06-WheelSize  P07-MotorMag  P08-SpeedLim(0-41kmh)")
    print(f"P09-StartMode  P10-DriveMode  P11-PASSens  P12-PAS_StartStr  P13-PASMagType  P14-CurLim  P15  P16-ODOClear")
    print(f"{'='*60}")
    print(f"  Time: {timestamp}  |  Op={counts['op']}  Settings={counts['settings']}  Direct={counts['direct']}  Total={counts['total']}")
    print(f"{'='*60}")
    
    print(f"  OPERATION MODE (0x52)")
    print(f"  {'-'*56}")
    op_lines = op_data.split('\n') if op_data else ['(no data yet)']
    for line in op_lines:
        print(f"  {line}")
    
    print()
    print(f"  SETTINGS MODE (0x53)")
    print(f"  {'-'*56}")
    st_lines = settings_data.split('\n') if settings_data else ['(no data yet)']
    for line in st_lines:
        print(f"  {line}")
    
    print()
    print(f"  DIRECT SETPOINT (0x54)")
    print(f"  {'-'*56}")
    dt_lines = direct_data.split('\n') if direct_data else ['(no data yet)']
    for line in dt_lines:
        print(f"  {line}")
    
    print(f"{'='*60}")
    sys.stdout.flush()


def decode_dashboard_op(payload: bytes) -> str:
    """Decode operation mode for dashboard display."""
    lines = []
    if len(payload) < 2:
        return "  (too short)"
    
    assist_level = payload[0]
    status = payload[1]
    headlight = (status >> 6) & 3
    battery = (status >> 5) & 1
    pushassist = (status >> 4) & 1
    powerassist = (status >> 3) & 1
    throttle = (status >> 2) & 1
    cruise = (status >> 1) & 1
    overspeed = status & 1
    
    lines.append(f"  AssistLevel: {assist_level}")
    lines.append(f"  Headlight: {headlight}")
    lines.append(f"  Battery: {'LOW' if battery else 'OK'}")
    lines.append(f"  PushAssist: {'ON' if pushassist else 'OFF'}")
    lines.append(f"  PowerAssist: {'ON' if powerassist else 'OFF'}")
    lines.append(f"  Throttle: {'ON' if throttle else 'OFF'}")
    lines.append(f"  CruiseCtrl: {'ON' if cruise else 'OFF'}")
    lines.append(f"  OverSpeed: {'YES' if overspeed else 'NO'}")
    return '\n'.join(lines)


def decode_dashboard_settings(data: bytes) -> str:
    """
    Decode settings mode for dashboard display.
    Fields sorted by payload byte order (matching C code decode order).
    """
    lines = []
    if len(data) < 6:
        return "  (too short)"
    
    datasize = data[3]
    payload = data[4:4 + datasize]
    
    if len(payload) >= 5:
        b4 = payload[0]
        b5 = payload[1]
        b6 = payload[2]
        b7 = payload[3]
        b8 = payload[4]
        
        pas_dir = (b4 >> 7) & 1
        p17 = (b4 >> 6) & 1
        p11 = b4 & 0x1F
        pas_tolerance = b5
        p18 = (b6 >> 7) & 1
        p19 = (b6 >> 6) & 1
        p12 = (b6 >> 4) & 0x03
        reverse = (b6 >> 5) & 1
        pas_n_ratio = b6 & 0x1F
        hnd_hl = (b7 >> 7) & 1
        hnd_hf = (b7 >> 6) & 1
        slow_start = b8 & 0x3F
        cur_limit = (b8 & 0x3F) * 500
        b9 = payload[5] if len(payload) >= 6 else 0
        vol = ((payload[9] << 8) | payload[10]) if len(payload) >= 11 else 0
        
        lines.append("  ─── Settings P07-P19 (sorted) ───")
        lines.append(f"  P07 PAS_Level:      {pas_n_ratio}  (payload[2] bits 4-0)")
        lines.append(f"  P08 SpeedLim:       {payload[6] if len(payload) >= 7 else '??'}  (payload[6], 0..41km/h)")
        lines.append(f"  P11 PAS_Sens:       {p11}  (payload[0] bits 0-4, 1..24)")
        lines.append(f"  P12 PAS_StartStr:   {p12}  (payload[2] bits 5-6, 0-3)")
        lines.append(f"  P13 PAS_MagType:    {pas_tolerance}  (payload[1] | 5/8/12)")
        lines.append(f"  P14 CurLim:         {cur_limit}mA  (payload[4] bits 0-5 | NICHT im Code)")
        lines.append(f"  P17 P17:            {p17}  (payload[0] bit 6)")
        lines.append(f"  P18 Throttle:       {'ON' if p18 else 'OFF'}  (payload[2] bit 7)")
        lines.append(f"  P19 Auto:           {'auto' if p19 else 'fix'}  (payload[2] bit 6)")
    
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description="King-Meter 901U Protocol Decoder")
    parser.add_argument("-p", "--port", default=SERIAL_PORT,
                        help=f"Serial port (default: {SERIAL_PORT})")
    parser.add_argument("-b", "--baud", type=int, default=SERIAL_BAUD,
                        help=f"Baud rate (default: {SERIAL_BAUD})")
    args = parser.parse_args()

    port = args.port
    baud = args.baud

    print(f"King-Meter 901U Protocol Decoder - Dashboard Mode")
    print(f"Connecting to {port} @ {baud} baud...")
    print(f"Press Ctrl+C to quit.\n")

    try:
        ser = serial.Serial(port=port, baudrate=baud, timeout=TIMEOUT)
    except serial.SerialException as e:
        print(f"ERROR: Cannot open {port}: {e}")
        print("Try: sudo chmod 666 /dev/ttyUSB0")
        sys.exit(1)

    print(f"Connected! Waiting for data...\n")

    buf = bytearray()
    msg_count = 0
    counts = {'op': 0, 'settings': 0, 'direct': 0, 'total': 0}
    
    # Latest decoded data for each type
    latest_op = ""
    latest_settings = ""
    latest_direct = ""
    prev_data = None

    try:
        while True:
            chunk = ser.read(ser.in_waiting or 1)
            if chunk:
                buf.extend(chunk)
                while True:
                    idx = buf.find(0x3A)
                    if idx < 0:
                        buf.clear()
                        break

                    if idx > 0:
                        del buf[:idx]

                    if len(buf) < 4:
                        break

                    cmd = buf[2]
                    datasize = buf[3]

                    crlf_pos = buf.find(b'\x0d\x0a')
                    if crlf_pos < 0:
                        if len(buf) > 200:
                            del buf[:20]
                        break

                    msg = buf[:crlf_pos]
                    del buf[:crlf_pos + 2]

                    msg_count += 1
                    counts['total'] += 1
                    timestamp = time.strftime("%H:%M:%S")

                    # Extract CRC
                    if len(msg) >= 6:
                        crc_low = msg[-2]
                        crc_high = msg[-1]
                        msg_body = msg[:-2]
                        checksum_calc = 0
                        for b in msg_body[1:]:
                            checksum_calc += b
                        checksum_calc -= (crc_low | (crc_high << 8))
                        checksum_valid = (checksum_calc == 0)
                    else:
                        crc_low = crc_high = 0
                        msg_body = msg
                        checksum_valid = False

                    payload = msg_body[4:] if len(msg_body) > 4 else b''
                    cmd_name = {0x52: "Operation", 0x53: "Settings", 0x54: "DirectSetpoint"}.get(cmd, f"Unknown(0x{cmd:02X})")

                    # Decode based on command type
                    if cmd == 0x52:
                        counts['op'] += 1
                        latest_op = decode_dashboard_op(payload)
                    elif cmd == 0x53:
                        counts['settings'] += 1
                        latest_settings = decode_dashboard_settings(msg_body)
                        prev_data = bytes(msg_body)
                    elif cmd == 0x54:
                        counts['direct'] += 1
                        if len(payload) >= 1:
                            latest_direct = f"  DirectSetpoint: {payload[0]}"
                        else:
                            latest_direct = "  (no data)"

                    # Print dashboard
                    print_dashboard(latest_op, latest_settings, latest_direct, timestamp, counts)

            else:
                time.sleep(0.01)

    except KeyboardInterrupt:
        clear_screen()
        print(f"\n{'='*100}")
        print(f"  Stopped.  Op={counts['op']}  Settings={counts['settings']}  Direct={counts['direct']}  Total={counts['total']}")
        print(f"{'='*100}")
    finally:
        ser.close()


if __name__ == "__main__":
    main()
