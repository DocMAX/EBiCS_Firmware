# EBiCS Android Dashboard - Implementation Notes

## Overview
This Android application provides a real-time graphical dashboard for monitoring the EBiCS motor controller, mirroring the functionality of the Python `Logaufbereitung.py` script but with a modern mobile interface.

## Architecture

### Components

1. **MainActivity.kt** - Main application controller
   - Manages telnet connection to ESP32 (port 1003)
   - Parses incoming CSV data (30 fields)
   - Updates UI on main thread
   - Handles assist level control commands

2. **GaugeView.kt** - Custom circular gauge widget
   - Displays values with animated arcs
   - Shows current value, min/max range
   - Configurable colors and ranges
   - Used for: Throttle, Torque, Brake, Cadence, Voltage, Speed

3. **ProgressBarView.kt** - Custom horizontal progress bar
   - Displays values as filled bars
   - Shows title and value text
   - Used for: Throttle, Torque, Assist Level

### Data Flow

```
ESP32 (port 1003)
    ↓
Socket Connection (background thread)
    ↓
BufferedReader → Line parsing
    ↓
CSV Split (30 fields) → Integer conversion
    ↓
Unit Conversions (raw → physical)
    ↓
Min/Max Tracking
    ↓
Main Thread (Handler)
    ↓
UI Update (Gauges, Bars, Text)
```

## Data Format

The ESP32 sends 30 comma-separated integer values per line:

| Index | Field | Description | Conversion |
|-------|-------|-------------|------------|
| 0 | raw_voltage | Battery voltage (raw) | / 40.26 → V |
| 1 | raw_throttle | Throttle ADC (raw) | / 1000 → V |
| 2 | raw_current1 | Phase 1 current (raw) | - |
| 3 | raw_current2 | Phase 2 current (raw) | - |
| 4 | raw_current3 | Phase 3 current (raw) | - |
| 5 | raw_brake_adc | Brake ADC (raw) | / 1000 → V |
| 6 | raw_torque | Motor torque (raw) | / 1000 → V |
| 7 | raw_temperature | Temperature (raw) | - |
| 8 | hall1 | Hall sensor A | - |
| 9 | hall2 | Hall sensor B | - |
| 10 | hall3 | Hall sensor C | - |
| 11 | brake | Brake state | - |
| 12 | pas | PAS state | - |
| 13 | speed | Speed state | - |
| 14 | led | LED state | - |
| 15 | light | Light state | - |
| 16 | brake_light | Brake light state | - |
| 17 | firmware_assist | Firmware assist level | - |
| 18 | speed_kmh_x100 | Speed (raw × 100) | / 100 → km/h |
| 19 | p17 | Parameter 17 (Torque override) | - |
| 20 | p18 | Parameter 18 (Throttle enable) | - |
| 21 | p19 | Parameter 19 (Autodetect) | - |
| 22 | p03 | Parameter 3 (System voltage) | - |
| 23 | p06 | Parameter 6 (Wheel size) | - |
| 24 | p07 | Parameter 7 (Speed magnet) | - |
| 25 | p08 | Parameter 8 (Speed limit) | - |
| 26 | p11 | Parameter 11 (PAS sensitivity) | - |
| 27 | p12 | Parameter 12 (Slow start) | - |
| 28 | p13 | Parameter 13 (PAS magnets) | - |
| 29 | p14 | Parameter 14 (Current limit) | - |

## UI Layout

### Header Section
- App title
- Connection status indicator (Green=Connected, Red=Disconnected)

### Assist Level Display
- Current firmware assist level
- Local assist level setting
- PAS pulse counter
- Speed pulse counter

### Control Buttons
- Assist 0, 1, 2, 3 buttons (send command to ESP32)
- Reset Counters button (clears min/max and pulse counts)

### Gauges Row 1
- **Throttle**: 0-5V range
- **Torque**: 0-5V range (orange)
- **Brake**: 0-5V range (red)

### Progress Bars
- **Throttle**: 0-5V (orange)
- **Torque**: 0-5V (yellow)
- **Assist**: 0-3 levels (green)

### Gauges Row 2
- **Cadence**: 0-120 RPM (green)
- **Voltage**: 20-60V (yellow)
- **Speed**: 0-100 km/h (blue)

## Network Configuration

### Default Settings
- Host: `esp32-mougg.lan`
- Port: `1003`
- Protocol: TCP (Telnet)

### Customization
Edit `MainActivity.kt` constants:
```kotlin
private const val ESP_HOST = "esp32-mougg.lan"
private const val ESP_PORT = 1003
```

### Network Requirements
- Android device and ESP32 on same network
- ESP32 hostname must be resolvable (or use IP address)
- Port 1003 open on ESP32
- INTERNET permission granted

## Building

### Prerequisites
- Android Studio (recommended)
- Android SDK 34
- Kotlin 1.9.0+
- Gradle 8.1.4+

### Command Line Build
```bash
cd android
./gradlew assembleDebug  # Debug build
./gradlew assembleRelease  # Release build
```

### Android Studio
1. File → Open → Select `android` folder
2. Wait for Gradle sync
3. Build → Make Project
4. Run → Run 'app'

## Testing

### Without ESP32
The app will show "Disconnected" status. To test UI:
1. Modify `MainActivity.kt` to use mock data
2. Comment out network connection code
3. Add timer-based data generator

### With ESP32
1. Ensure ESP32 is running and accessible
2. Verify telnet on port 1003 works
3. Install app on Android device
4. Open app and verify connection
5. Check data updates in real-time

## Features Comparison

| Feature | Python Script | Android App |
|---------|--------------|-------------|
| Real-time data | ✓ | ✓ |
| Gauge displays | ✗ | ✓ |
| Progress bars | ✗ | ✓ |
| Min/Max tracking | ✓ | ✓ |
| Assist control | ✓ | ✓ |
| Counter reset | ✓ | ✓ |
| Touch interface | ✗ | ✓ |
| Portability | ✗ | ✓ |
| Battery powered | ✗ | ✓ |

## Performance

- Update rate: Limited by network (~10-50ms per line)
- UI refresh: Main thread via Handler
- Network thread: Single background thread
- Memory: Minimal (no data buffering beyond one line)

## Error Handling

- Connection failures: Toast notification, status update
- Parse errors: Logged, line skipped
- Network errors: Automatic disconnect, status update
- Send errors: Logged, no crash

## Security

- No authentication (same as Python script)
- Network traffic unencrypted (same as Python script)
- INTERNET permission required
- Consider VPN for untrusted networks

## Future Enhancements

1. Data logging to file
2. Graph/history view
3. Parameter configuration
4. Multiple ESP32 support
5. Bluetooth LE support
6. Dark/light theme toggle
7. Custom gauge ranges
8. Export data (CSV)
9. Alarm thresholds
10. Widget support

## Troubleshooting

### Connection Failed
- Verify ESP32 is powered
- Check network connectivity
- Confirm hostname resolves (try IP address)
- Verify port 1003 is open

### No Data Updates
- Check ESP32 is sending data
- Verify baud rate matches
- Check network latency
- Review Logcat for errors

### UI Not Updating
- Verify Handler is posting to main thread
- Check for exceptions in Logcat
- Ensure data parsing succeeds

### App Crashes
- Check Logcat for stack trace
- Verify all views are initialized
- Check resource IDs match

## License

GNU GPL v3 (same as project)

## References

- Original Python script: `Documentation/Logaufbereitung.py`
- ESP32 firmware: EBiCS motor controller
- Protocol: CSV over TCP (port 1003)
