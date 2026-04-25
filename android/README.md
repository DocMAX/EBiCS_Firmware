# EBiCS Android Dashboard

A real-time graphical dashboard for monitoring EBiCS motor controller data via telnet connection.

## Features

- **Real-time Data Visualization**: Live updates from ESP32 motor controller
- **Gauge Displays**: Visual gauges for throttle, torque, brake, cadence, voltage, and speed
- **Progress Bars**: Horizontal bars for throttle, torque, and assist level
- **Assist Level Control**: Buttons to set assist levels 0-3
- **Counter Reset**: Reset PAS and speed pulse counters
- **Min/Max Tracking**: Track minimum and maximum values for all parameters
- **Connection Status**: Visual indicator for connection state

## Architecture

- **MainActivity**: Handles UI and telnet connection to ESP32
- **GaugeView**: Custom view for circular gauge displays
- **ProgressBarView**: Custom view for horizontal progress bars
- **Network Thread**: Background thread for socket communication
- **Data Parser**: Parses 30-field CSV data from ESP32

## Data Format

The app expects comma-separated values (30 fields) from the ESP32:

```
raw_voltage, raw_throttle, raw_current1, raw_current2, raw_current3,
raw_brake_adc, raw_torque, raw_temperature,
hall1, hall2, hall3, brake, pas, speed, led, light, brake_light, firmware_assist_level,
speed_kmh_x100, p17, p18, p19, p03, p06, p07, p08, p11, p12, p13, p14
```

## Configuration

Edit `MainActivity.kt` to change:
- `ESP_HOST`: ESP32 hostname (default: "esp32-mougg.lan")
- `ESP_PORT`: Telnet port (default: 1003)

## Building

```bash
cd android
./gradlew assembleDebug
```

Or use Android Studio to open the project.

## Requirements

- Android SDK 34 (Android 14)
- Minimum SDK: 24 (Android 7.0)
- INTERNET permission

## Network Setup

Ensure your Android device is on the same network as the ESP32 and can resolve the hostname "esp32-mougg.lan" (or modify the host in code).

## UI Components

### Gauges
- **Throttle**: Motor throttle voltage (0-5V)
- **Torque**: Motor torque voltage (0-5V)
- **Brake**: Brake ADC voltage (0-5V)
- **Cadence**: Pedal cadence in RPM (0-120)
- **Voltage**: Battery voltage (20-60V)
- **Speed**: Current speed in km/h (0-100)

### Progress Bars
- **Throttle**: Throttle level (0-5V)
- **Torque**: Torque level (0-5V)
- **Assist**: Current assist level (0-3)

### Controls
- **Assist 0-3**: Set motor assist level
- **Reset Counters**: Reset PAS and speed pulse counters

## License

GNU GPL v3 (see project LICENSE)