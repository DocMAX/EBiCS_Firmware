import socket
import time
import os
import sys
import tty
import termios
import select

# Non blocking keyboard input setup
old_settings = termios.tcgetattr(sys.stdin)
tty.setcbreak(sys.stdin.fileno())

# Telnet setup to ESP32
esp_host = 'esp32-mougg.lan'
esp_port = 1003
ser = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
ser.connect((esp_host, esp_port))
ser.settimeout(0.01)

# System state names
SYSTEM_STATES = [
    "INIT",
    "IDLE",
    "ASSIST",
    "BRAKE",
    "ERROR",
    "CALIBRATION",
    "MANUAL",
    "WALK_ASSIST"
]

# Display parameter definitions P01-P19
DISPLAY_PARAMETERS = {
    "P01": "Backlight Brightness. 1: darkest; 3: brightest.",
    "P02": "System Unit. 0: km (metric); 1: mile (imperial).",
    "P03": "System Voltage: 24V/36V/48V/60V/72V.",
    "P04": "Auto-Off Time. 0: never; other value = auto-off minutes.",
    "P05": "Pedal Assist Level. Modes: 0-3, 0-5, 0-9 or 1-x (no Level 0).",
    "P06": "Wheel Size. Unit: inch; Increment: 0.1.",
    "P07": "Motor Magnets Number for Speed Gauge. Range: 1-100",
    "P08": "Speed Limit. Range: 0-100 km/h; Error Value: ±1 km/h.",
    "P09": "Direct Start / Kick-to-Start. 0: Direct Start; 1: Kick-to-Start.",
    "P10": "Drive Mode Setting. 0: PAS only; 1: Throttle only; 2: Both.",
    "P11": "Pedal Assist Sensitivity. Range: 1-24.",
    "P12": "Pedal Assist Starting Intensity. Range: 0-5.",
    "P13": "Magnets Number in Pedal Assist Sensor. Values: 5/8/12.",
    "P14": "Current Limit Value. Default: 12A. Range: 1-20A.",
    "P15": "Display Low Voltage Value.",
    "P16": "ODO Clearance. Hold Plus for 5s to clear ODO.",
    "P17": "Torque Override. 0: disabled; 1: enabled - Soft start ramp when torque > 1000.",
    "P18": "Throttle Enable/Disable. 0: disabled; 1: enabled.",
    "P19": "Autodetect Trigger. 1: trigger on rising edge for motor angle/KV detection."
}

# Min/Max tracking
min_vals = {}
max_vals = {}

# PAS and Speed tracking
last_pas_time = time.time()
last_pas_state = 0
last_speed_state = 0
pas_period = 3000

# Counters
pas_pulse_count = 0
speed_pulse_count = 0

# Assist level
current_assist_level = 0

# Last data for redraw
last_row = None

# Buffer for assembling multi-line data
data_buffer = ""

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def print_dashboard(row, throttle, torque, brake_adc, cadence, voltage, hallstate, brake, pas, speed, led, light, brake_light, raw_voltage, raw_throttle, raw_current1, raw_current2, raw_current3, raw_brake_adc, raw_torque, raw_temperature, pas_period, pas_pulse_count, speed_pulse_count, firmware_assist_level, speed_kmh, p17, p18, p19, p03, p06, p07, p08, p11, p12, p13, p14):
    clear_screen()

    # Spaltenbreiten: Wert+Einheit je 10 Zeichen, RAW-Werte je 7 Zeichen
    W  = 10   # Breite für konvertierte Werte inkl. Einheit
    WR = 7    # Breite für RAW-Werte

    # Hilfsfunktionen für Min/Max mit Fallback
    def mn(key): return min_vals.get(key, 0)
    def mx(key): return max_vals.get(key, 0)

    print("=" * 92)
    print("                               EBiCS MOTOR CONTROLLER")
    print("=" * 92)
    print()
    print(f"  Mode: HARDWARE DEBUG")
    # Map firmware assist level back to 0-3 display range based on observed values
    # Display 0 -> firmware 0 -> level 0
    # Display 1 -> firmware 70 -> level 1
    # Display 2 -> firmware 150 -> level 2
    # Display 3 -> firmware 250 -> level 3
    if firmware_assist_level <= 10:
        display_level = 0
    elif firmware_assist_level <= 100:
        display_level = 1
    elif firmware_assist_level <= 200:
        display_level = 2
    else:
        display_level = 3

    print(f"  Assist Level: {display_level}  (Firmware: {firmware_assist_level})  Local: {current_assist_level}")
    print()
    #            Label        Aktuell          Min              Max          RAW-Min  RAW-Max  RAW
    print(f"  {'':13}  {'AKTUELL':>{W}}  {'MIN':>{W}}  {'MAX':>{W}}  {'RAW-MIN':>{WR}}  {'RAW-MAX':>{WR}}  {'RAW':>{WR}}")
    print(f"  {'-'*13}  {'-'*W}  {'-'*W}  {'-'*W}  {'-'*WR}  {'-'*WR}  {'-'*WR}")
    print(f"  {'Throttle:':<13}  {fv(throttle, 'V', W)}  {fv(mn('throttle'), 'V', W)}  {fv(mx('throttle'), 'V', W)}  {fi(int(mn('raw_throttle')), '', WR)}  {fi(int(mx('raw_throttle')), '', WR)}  {fi(raw_throttle, '', WR)}")
    print(f"  {'Torque:':<13}  {fv(torque,   'V', W)}  {fv(mn('torque'),   'V', W)}  {fv(mx('torque'),   'V', W)}  {fi(int(mn('raw_torque')),   '', WR)}  {fi(int(mx('raw_torque')),   '', WR)}  {fi(raw_torque,   '', WR)}")
    print(f"  {'Brake ADC:':<13}  {fv(brake_adc,'V', W)}  {'---':>{W}}  {'---':>{W}}  {'---':>{WR}}  {'---':>{WR}}  {fi(raw_brake_adc, '', WR)}")
    print(f"  {'Cadence:':<13}  {fi(cadence, 'RPM', W)}  {fi(int(mn('cadence')), 'RPM', W)}  {fi(int(mx('cadence')), 'RPM', W)}  {'---':>{WR}}  {'---':>{WR}}  {fi(pas_period, 'ms', WR)}")
    print()
    print(f"  {'Battery:':<13}  {fv(voltage,  'V', W, 1)}  {fv(mn('voltage'),  'V', W, 1)}  {fv(mx('voltage'),  'V', W, 1)}  {fi(int(mn('raw_voltage')),  '', WR)}  {fi(int(mx('raw_voltage')),  '', WR)}  {fi(raw_voltage,  '', WR)}")
    print(f"  {'Speed:':<13}  {fv(speed_kmh, 'km/h', W, 1)}  {fv(mn('speed'), 'km/h', W, 1)}  {fv(mx('speed'), 'km/h', W, 1)}  {'---':>{WR}}  {'---':>{WR}}  {'---':>{WR}}")
    print()
    print("  GPIO Status:")
    hall1, hall2, hall3 = (hallstate & 1), ((hallstate >> 1) & 1), ((hallstate >> 2) & 1)
    print(f"    Hall A: {'■' if hall1 else '□'} ({hall1})   Hall B: {'■' if hall2 else '□'} ({hall2})   Hall C: {'■' if hall3 else '□'} ({hall3})   =  0b{hallstate:03b}")
    print(f"    Brake:  {'ACTIVE  ' if brake else 'RELEASED'} ({brake})   PAS: {'HIGH' if pas else 'LOW '} ({pas})   Speed: {'ACTIVE' if speed else 'IDLE  '} ({speed})")
    print(f"    LED:    {'ON ' if led else 'OFF'} ({led})             Light: {'ON ' if light else 'OFF'} ({light})   Brake Light: {'ON ' if brake_light else 'OFF'} ({brake_light})")
    print()
    print("  Display Parameters P03/P06-P14 / P17-P19:")
    p17_text = "SOFTSTART" if p17 else "OFF"
    p18_text = "ENABLED" if p18 else "DISABLED"
    p19_text = "TRIGGERED" if p19 else "IDLE"
    print(f"    P03 (Voltage x10): {p03:4}   P06 (Wheel mm): {p06:4}   P07 (SpeedMag): {p07:2}   P08 (Limit kmh): {p08:2}")
    print(f"    P11 (Sensitivity): {p11:2}   P12 (SlowStart): {p12:2}   P13 (PASMag): {p13:2}    P14 (Curr mA): {p14:4}")
    print(f"    P17 (Torque): {p17_text:9}  P18 (Throttle): {p18_text:8}  P19 (AutoDetect): {p19_text:9}")
    print()
    print("  ALL RAW ADC VALUES:")
    print(f"    {'Battery:':<10} {raw_voltage:>5}   {'Throttle:':<10} {raw_throttle:>5}   {'Phase1:':<10} {raw_current1:>5}   {'Phase2:':<10} {raw_current2:>5}")
    print(f"    {'Phase3:':<10} {raw_current3:>5}   {'Brake:':<10} {raw_brake_adc:>5}   {'Torque:':<10} {raw_torque:>5}   {'Temp:':<10} {raw_temperature:>5}")
    print()
    print("  PULSE COUNTERS:")
    print(f"    {'PAS Pulses:':<20} {pas_pulse_count:>6}      {'Speed Pulses:':<20} {speed_pulse_count:>6}")
    print(f"    {'Pedal Rotations:':<20} {pas_pulse_count // 32:>6}      {'Wheel Rotations:':<20} {speed_pulse_count // 6:>6}")
    print()
    print("=" * 92)
    print("  Press Ctrl+C to exit  |  Press 'R' to reset counters  |  Press 0-3 to set assist level")

def update_min_max(name, value):
    if name not in min_vals or value < min_vals[name]:
        min_vals[name] = value
    if name not in max_vals or value > max_vals[name]:
        max_vals[name] = value

# Formatierungshilfen: Wert + Einheit als fester Block
def fv(value, unit, width=10, decimals=3):
    """Float-Wert + Einheit als rechtsbündiger Block fester Breite."""
    s = f"{value:.{decimals}f}{unit}"
    return s.rjust(width)

def fi(value, unit, width=10):
    """Integer-Wert + Einheit als rechtsbündiger Block fester Breite."""
    s = f"{value}{unit}"
    return s.rjust(width)

print("EBiCS Realtime Dashboard")
print("Connecting...\n")

while True:
    try:
        try:
            chunk = ser.recv(1024).decode()
            if chunk:
                data_buffer += chunk
                while '\n' in data_buffer:
                    line, data_buffer = data_buffer.split('\n', 1)
                    line = line.strip()
                    if not line:
                        continue
                    
                    # Strip ESP32 TX:/RX: prefix if present at start of line
                    if line.startswith("TX: "):
                        line = line[4:]
                    elif line.startswith("RX: "):
                        continue
                    # Also strip prefix from middle of buffer (split packet case)
                    else:
                        # Remove any TX:/RX: prefix that may be embedded from packet boundary
                        for prefix in ["TX: ", "RX: "]:
                            idx = line.find(prefix)
                            if idx == 0:
                                line = line[len(prefix):]
                                break
                    
                    row = line.split(',')
                    if len(row) == 30:
                        try:
                            row = [int(x.strip()) for x in row]

                            # Raw hardware values - ALL 8 ADC channels
                            raw_voltage     = row[0]
                            raw_throttle    = row[1]
                            raw_current1    = row[2]
                            raw_current2    = row[3]
                            raw_current3    = row[4]
                            raw_brake_adc   = row[5]
                            raw_torque      = row[6]
                            raw_temperature = row[7]

                             # ALL 9 GPIO pins
                            hall1       = row[8]
                            hall2       = row[9]
                            hall3       = row[10]
                            brake       = row[11]
                            pas         = row[12]
                            speed       = row[13]
                            led         = row[14]
                            light       = row[15]
                            brake_light = row[16]
                            firmware_assist_level = row[17]
                            speed_kmh_x100 = row[18]
                            p17 = row[19]
                            p18 = row[20]
                            p19 = row[21]
                            p03 = row[22]
                            p06 = row[23]
                            p07 = row[24]
                            p08 = row[25]
                            p11 = row[26]
                            p12 = row[27]
                            p13 = row[28]
                            p14 = row[29]


                            # Unit conversions
                            throttle  = raw_throttle / 1000.0
                            torque    = raw_torque / 1000.0
                            brake_adc = raw_brake_adc / 1000.0
                            voltage   = raw_voltage / 40.26
                            speed_kmh = speed_kmh_x100 / 100.0

                            # PAS edge detection
                            current_time = time.time()
                            if pas != last_pas_state and pas == 1:
                                pas_period = int((current_time - last_pas_time) * 1000)
                                last_pas_time = current_time
                                pas_pulse_count += 1
                            last_pas_state = pas

                            # Speed edge detection
                            if speed != last_speed_state and speed == 1:
                                speed_pulse_count += 1
                            last_speed_state = speed

                            # Cadence calculation
                            time_since_last_pas = (current_time - last_pas_time) * 1000
                            if time_since_last_pas > 3000:
                                cadence = 0
                            elif pas_period < 3000:
                                cadence = int(60000 / pas_period / 32)
                            else:
                                cadence = 0

                            # Hallstate calculation
                            hallstate = hall1 | (hall2 << 1) | (hall3 << 2)

                            # Update min/max
                            update_min_max('throttle',     throttle)
                            update_min_max('cadence',      cadence)
                            update_min_max('voltage',      voltage)
                            update_min_max('torque',       torque)
                            update_min_max('speed',        speed_kmh)
                            update_min_max('raw_throttle', raw_throttle)
                            update_min_max('raw_torque',   raw_torque)
                            update_min_max('raw_voltage',  raw_voltage)

                            # Store last data
                            last_row = (row, throttle, torque, brake_adc, cadence, voltage, hallstate, brake, pas, speed, led, light, brake_light, raw_voltage, raw_throttle, raw_current1, raw_current2, raw_current3, raw_brake_adc, raw_torque, raw_temperature, pas_period, pas_pulse_count, speed_pulse_count, firmware_assist_level, speed_kmh, p17, p18, p19, p03, p06, p07, p08, p11, p12, p13, p14)

                            print_dashboard(*last_row)

                        except ValueError:
                            pass
                    else:
                        if len(row) > 1 and any(x.strip() for x in row if x.strip()):
                            print(f"Non-CSV ({len(row)} fields): {line}")
        except socket.timeout:
            pass

        # Check for hotkeys
        if select.select([sys.stdin], [], [], 0)[0]:
            key = sys.stdin.read(1).lower()
            if key == 'r':
                pas_pulse_count = 0
                speed_pulse_count = 0
                min_vals.clear()
                max_vals.clear()
            elif key in '0123':
                current_assist_level = int(key)
                try:
                    ser.sendall((key + "\n").encode())
                    print(f"Sent assist level {current_assist_level}")
                    if last_row:
                        print_dashboard(*last_row)
                except Exception as e:
                    pass  # Ignore send errors

    except KeyboardInterrupt:
        print("\nExiting...")
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
        ser.close()
        break
    except socket.timeout:
        pass
    except Exception as e:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
