#!/bin/bash

# EBiCS Firmware Flash Script
# Usage: ./flash.sh [serial|telnet|esp32-ota|esp32] [-b] <target>
#
# Flashes output/EBiCS_Firmware.lsh to the STM32 controller via ESP32 bridge
# esp32 and esp32-ota modes update the ESP32 bridge itself
# Options:
#   -b  Build firmware before flashing (for esp32 and esp32-ota modes)

BUILD=0
POSITIONAL=()

# Parse arguments in any position
while [[ $# -gt 0 ]]; do
    case "$1" in
        -b)
            BUILD=1
            shift
            ;;
        *)
            POSITIONAL+=("$1")
            shift
            ;;
    esac
done

set -- "${POSITIONAL[@]}"

MODE=$1
TARGET=$2

if [ -z "$MODE" ]; then
    echo "Usage: $0 [serial|telnet|esp32-ota|esp32] [-b] <target>"
    echo ""
    echo "Options:"
    echo "  -b  Build firmware before flashing (for esp32 and esp32-ota modes)"
    echo ""
    echo "Examples:"
    echo "  $0 serial /dev/ttyUSB0"
    echo "  $0 telnet 192.168.1.123"
    echo "  $0 esp32-ota 192.168.1.123"
    echo "  $0 esp32-ota -b 192.168.1.123"
    echo "  $0 esp32 -b /dev/ttyUSB0"
    exit 1
fi

if [ -z "$TARGET" ]; then
    echo "Error: Target required"
    echo ""
    echo "For serial: provide tty device, e.g. /dev/ttyUSB0"
    echo "For telnet: provide ESP32 hostname/IP"
    echo "For esp32-ota: provide ESP32 hostname/IP"
    echo "For esp32: provide tty device, e.g. /dev/ttyUSB0"
    exit 1
fi

cd "$(dirname "$0")"

case $MODE in
    serial)
        python3 ./serial_flasher.py "$TARGET" ../output/EBiCS_Firmware.lsh
        ;;
    telnet)
        python3 ./telnet_flasher.py "$TARGET" ../output/EBiCS_Firmware.lsh -d 0.0042
        ;;
    esp32-ota)
        if [ "$BUILD" = "1" ]; then
            echo "Building ESP32 firmware..."
            # Ensure sketch directory structure matches arduino-cli requirements
            if [ -f "../arduino/esp32-mougg.ino" ] && [ ! -f "../arduino/esp32-mougg/esp32-mougg.ino" ]; then
                mkdir -p ../arduino/esp32-mougg
                mv ../arduino/esp32-mougg.ino ../arduino/esp32-mougg/
                [ -f "../arduino/config.h" ] && ln -sf ../config.h ../arduino/esp32-mougg/
            fi
            # Touch the sketch to force rebuild
            touch ../arduino/esp32-mougg/esp32-mougg.ino
            arduino-cli compile --fqbn esp32:esp32:esp32 -e ../arduino/esp32-mougg/
            if [ $? -ne 0 ]; then
                echo "Build failed! Aborting."
                exit 1
            fi
            BIN="../arduino/esp32-mougg/build/esp32.esp32.esp32/esp32-mougg.ino.bin"
        else
            BIN="../arduino/esp32-mougg/build/esp32.esp32.esp32/esp32-mougg.ino.bin"
        fi
        
        if [ ! -f "$BIN" ]; then
            echo "Error: Binary not found: $BIN"
            exit 1
        fi
        
        echo "Flashing ESP32 via OTA to $TARGET..."
        echo "  File: $BIN"
        echo "  Modified: $(stat -c '%y' "$BIN" | cut -d'.' -f1)"
        python3 ./espota.py -r -i "$TARGET" -f "$BIN"
        ;;
    esp32)
        if [ "$BUILD" = "1" ]; then
            echo "Building ESP32 firmware..."
            # Ensure sketch directory structure matches arduino-cli requirements
            if [ -f "../arduino/esp32-mougg.ino" ] && [ ! -f "../arduino/esp32-mougg/esp32-mougg.ino" ]; then
                mkdir -p ../arduino/esp32-mougg
                mv ../arduino/esp32-mougg.ino ../arduino/esp32-mougg/
                [ -f "../arduino/config.h" ] && ln -sf ../config.h ../arduino/esp32-mougg/
            fi
            # Touch the sketch to force rebuild
            touch ../arduino/esp32-mougg/esp32-mougg.ino
            arduino-cli compile --fqbn esp32:esp32:esp32 -e ../arduino/esp32-mougg/
            if [ $? -ne 0 ]; then
                echo "Build failed! Aborting."
                exit 1
            fi
        fi
        
        echo "Flashing ESP32 via serial port $TARGET..."
        echo "  Sketch: ../arduino/esp32-mougg/"
        echo "  Modified: $(stat -c '%y' ../arduino/esp32-mougg/esp32-mougg.ino | cut -d'.' -f1)"
        arduino-cli upload --fqbn esp32:esp32:esp32 -p "$TARGET" ../arduino/esp32-mougg/
        ;;
    *)
        echo "Unknown mode: $MODE"
        echo "Valid modes: serial, telnet, esp32-ota, esp32"
        exit 1
        ;;
esac
