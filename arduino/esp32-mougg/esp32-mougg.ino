#include <Arduino.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <ArduinoOTA.h>
#include <ESPmDNS.h>
#include <string.h>
#include "config.h"

#define UART_CONTROLLER_RX  3
#define UART_CONTROLLER_TX  1
#define UART_DISPLAY_RX    16
#define UART_DISPLAY_TX    17
#define UART_BATTERY_RX    25
#define UART_BATTERY_TX    26
#define WIFI_LED_PIN        2

#define UART_BAUD           9600
#define CONTROLLER_BAUD     9600
#define FLASHER_BAUD       38400

HardwareSerial SerialController(0);
HardwareSerial SerialDisplay(2);
HardwareSerial SerialBattery(1);

WiFiServer serverUart0(1000);
WiFiServer serverUart1(1001);
WiFiServer serverUart2(1002);
WiFiServer serverDebug(1003);
WiFiServer serverFlasher(1004);

WiFiClient clientUart0;
WiFiClient clientUart1;
WiFiClient clientUart2;
WiFiClient clientDebug;
WiFiClient clientFlasher;

uint8_t  frameState = 0;
uint16_t frameLen = 0;
bool     displayDisabled = false;
bool     flasherInit = false;
uint32_t lastReconnect = 0;
bool     debugEnabledOnSTM32 = false;
static bool lastDebugConnected = false;

uint8_t  buf[4096];

void handleClient(WiFiServer &server, WiFiClient &client) {
  if (server.hasClient()) {
    if (client && client.connected())
      server.accept().stop();
    else
      client = server.accept();
  }
}

void forwardToClients(WiFiClient &c1, WiFiClient &c2, uint8_t* buf, int len, const char* prefix) {
  if (prefix) {
    if(c1 && c1.connected()) { c1.write((uint8_t*)prefix, strlen(prefix)); c1.write(buf, len); }
    if(c2 && c2.connected()) { c2.write((uint8_t*)prefix, strlen(prefix)); c2.write(buf, len); }
  } else {
    if(c1 && c1.connected()) c1.write(buf, len);
    if(c2 && c2.connected()) c2.write(buf, len);
  }
}

void setup() {
  delay(1000);
  
  pinMode(WIFI_LED_PIN, OUTPUT);
  digitalWrite(WIFI_LED_PIN, LOW);

  SerialController.setRxBufferSize(2048);
  SerialController.setTxBufferSize(2048);
  SerialController.begin(CONTROLLER_BAUD, SERIAL_8N1, UART_CONTROLLER_RX, UART_CONTROLLER_TX);
  SerialDisplay.setRxBufferSize(256);
  SerialDisplay.begin(UART_BAUD, SERIAL_8N1, UART_DISPLAY_RX, UART_DISPLAY_TX);
  SerialBattery.setRxBufferSize(256);
  SerialBattery.begin(UART_BAUD, SERIAL_8N1, UART_BATTERY_RX, UART_BATTERY_TX);

  WiFi.persistent(false);
  WiFi.mode(WIFI_STA);
  WiFi.disconnect(true);
  // WiFi.config(INADDR_NONE, INADDR_NONE, INADDR_NONE);
  // WiFi.setTxPower(WIFI_POWER_19_5dBm);
  WiFi.setAutoReconnect(true);
  WiFi.setHostname("esp32-mougg");
  // MDNS.begin("esp32-mougg");
  // MDNS.setInstanceName("esp32-mougg");
  // MDNS.addService("_http._tcp", "tcp", 80);
  delay(100);

  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  uint32_t timeout = millis() + 30000;
  while (WiFi.status() != WL_CONNECTED && millis() < timeout) {
    delay(500);
  }
  lastReconnect = millis();

  serverUart0.begin();
  serverUart1.begin();
  serverUart2.begin();
  serverDebug.begin();
  serverFlasher.begin();

  ArduinoOTA.setHostname("esp32-mougg");
  ArduinoOTA.setRebootOnSuccess(true);
  ArduinoOTA.onEnd([]() {
    WiFi.mode(WIFI_STA);
    WiFi.setAutoReconnect(true);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  });
  ArduinoOTA.begin();
}

void loop() {
  int pos = 0;
  static bool lastFlasherState = false;

  // Static buffers for CRLF framing per direction
  static uint8_t ctrlRxBuf[2048]; static int ctrlRxPos = 0;  // Controller → Port1000 TX
  static uint8_t ctrlTxBuf[2048]; static int ctrlTxPos = 0;  // Port1000 RX → Controller
  static uint8_t displayBuf[256];  static int displayPos = 0; // Display → Port1001 TX
  static uint8_t displayTxBuf[256]; static int displayTxPos = 0; // Port1001 RX → Display
  static uint8_t ctrlToDispEchoBuf[2048]; static int ctrlToDispEchoPos = 0; // Controller → Display echo to Port1001 RX
  static uint8_t batteryRxBuf[256]; static int batteryRxPos = 0; // Battery → Port1002 TX
  static uint8_t batteryTxBuf[256]; static int batteryTxPos = 0; // Port1002 RX → Battery

  // Accept new flasher connection and configure hardware
  if (serverFlasher.hasClient()) {
    if (clientFlasher && clientFlasher.connected()) {
      serverFlasher.accept().stop();
    } else {
      if (clientUart0 && clientUart0.connected()) { clientUart0.stop(); }
      if (clientUart1 && clientUart1.connected()) { clientUart1.stop(); }
      if (clientUart2 && clientUart2.connected()) { clientUart2.stop(); }
      if (clientDebug && clientDebug.connected()) { clientDebug.stop(); }

      clientFlasher = serverFlasher.accept();
      SerialController.end();
      pinMode(UART_CONTROLLER_TX, OUTPUT);
      digitalWrite(UART_CONTROLLER_TX, HIGH);
      delayMicroseconds(100);
      SerialController.setRxBufferSize(2048);
      SerialController.setTxBufferSize(2048);
      SerialController.begin(FLASHER_BAUD, SERIAL_8N1, UART_CONTROLLER_RX, UART_CONTROLLER_TX);
      frameState = 0;
      frameLen = 0;
      displayDisabled = true;
      flasherInit = true;
      lastFlasherState = true;
      lastDebugConnected = false; // Reset debug state during flashing
      while (SerialController.available()) SerialController.read();
      SerialController.flush();
    }
  }

  // FLASHER MODE: bidirectional passthrough at 38400 baud
  if (clientFlasher && clientFlasher.connected()) {
    while (clientFlasher.available()) {
      SerialController.write(clientFlasher.read());
    }
    while (SerialController.available()) {
      clientFlasher.write(SerialController.read());
    }
    yield();
    return;
  }

  // Handle flasher disconnect: restore controller baud (9600) and reset state
  bool currentFlasherState = (clientFlasher && clientFlasher.connected());
  if (lastFlasherState && !currentFlasherState) {
    flasherInit = false;
    SerialController.end();
    pinMode(UART_CONTROLLER_TX, OUTPUT);
    digitalWrite(UART_CONTROLLER_TX, HIGH);
    delay(100);
    SerialController.setRxBufferSize(2048);
    SerialController.setTxBufferSize(2048);
    SerialController.begin(CONTROLLER_BAUD, SERIAL_8N1, UART_CONTROLLER_RX, UART_CONTROLLER_TX);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    lastReconnect = millis();
    displayDisabled = false;
    frameState = 0;
    frameLen = 0;
    ctrlRxPos = ctrlTxPos = displayPos = displayTxPos = ctrlToDispEchoPos = batteryRxPos = batteryTxPos = 0;
  }
  lastFlasherState = currentFlasherState;

  ArduinoOTA.handle();

  if (WiFi.status() != WL_CONNECTED && millis() - lastReconnect > 10000) {
    WiFi.reconnect();
    lastReconnect = millis();
  }

  handleClient(serverUart0, clientUart0);
  handleClient(serverUart1, clientUart1);
  handleClient(serverUart2, clientUart2);
  handleClient(serverDebug, clientDebug);

  // Detect Debug port connection state
  bool currentDebugConnected = clientDebug.connected();
  
  // Unique 4-byte control sequences to avoid false triggers
  // These are unlikely to appear in normal display protocol data
  const uint8_t DEBUG_ENABLE_SEQ[] = {0xDE, 0xAD, 0xBE, 0xEF};
  const uint8_t DEBUG_DISABLE_SEQ[] = {0xDE, 0xAD, 0xBE, 0xEE};
  
  if (currentDebugConnected && !lastDebugConnected) {
      // Connected — enable debug on STM32
      // Send multiple times to ensure it gets through
      for (int i = 0; i < 5; i++) {
          SerialController.write(DEBUG_ENABLE_SEQ, 4);
          delay(20);
      }
      debugEnabledOnSTM32 = true;
  }
  if (!currentDebugConnected && lastDebugConnected) {
      // Disconnected — disable debug on STM32
      // Send multiple times to ensure it gets through
      for (int i = 0; i < 5; i++) {
          SerialController.write(DEBUG_DISABLE_SEQ, 4);
          delay(20);
      }
      debugEnabledOnSTM32 = false;
  }
  lastDebugConnected = currentDebugConnected;

  // Helper: extract frames delimited by CRLF, send with label - process ALL frames
  auto emitFrames = [&](uint8_t* pb, int& pp, WiFiClient& cl, const char* lbl, int cap) {
    int processed = 0;
    while (processed < pp - 1) {
      if (pb[processed] == '\r' && pb[processed+1] == '\n') {
        int flen = processed;
        if (cl && cl.connected()) {
          cl.write((uint8_t*)lbl, 4);
          cl.write(pb, flen);
          cl.write((uint8_t*)"\r\n", 2);
        }
        int rem = pp - (processed + 2);
        for (int j = 0; j < rem; j++) pb[j] = pb[processed + 2 + j];
        pp = rem;
        processed = 0;
      } else {
        processed++;
      }
    }
    if (pp >= cap) pp = 0;  // overflow guard
  };

  // PRIORITY 1: Display → Controller (Display sends request)
  pos = 0;
  while (SerialDisplay.available() && pos < 32) buf[pos++] = SerialDisplay.read();
  if (pos > 0) {
    if (!flasherInit) {
      SerialController.write(buf, pos);
      for (int i = 0; i < pos; i++) if (ctrlTxPos < sizeof(ctrlTxBuf)) ctrlTxBuf[ctrlTxPos++] = buf[i];
      emitFrames(ctrlTxBuf, ctrlTxPos, clientUart0, "RX: ", 2048);
    }
    for (int i = 0; i < pos; i++) if (displayPos < sizeof(displayBuf)) displayBuf[displayPos++] = buf[i];
    emitFrames(displayBuf, displayPos, clientUart1, "TX: ", 256);
  }

   // PRIORITY 2: Controller → Display (Controller responds)
   pos = 0;
   while (SerialController.available() && pos < 32) buf[pos++] = SerialController.read();
   if (pos > 0) {
     if (!displayDisabled) {
       if (!flasherInit) {
         SerialDisplay.write(buf, pos);
         for (int i = 0; i < pos; i++) if (ctrlToDispEchoPos < sizeof(ctrlToDispEchoBuf)) ctrlToDispEchoBuf[ctrlToDispEchoPos++] = buf[i];
         emitFrames(ctrlToDispEchoBuf, ctrlToDispEchoPos, clientUart1, "RX: ", sizeof(ctrlToDispEchoBuf));
       }
     }
     if (!flasherInit) SerialBattery.write(buf, pos);
     for (int i = 0; i < pos; i++) {
       if (ctrlRxPos < sizeof(ctrlRxBuf)) ctrlRxBuf[ctrlRxPos++] = buf[i];
     }
     emitFrames(ctrlRxBuf, ctrlRxPos, clientUart0, "TX: ", 2048);
     // Forward debug data to debug client on port 1003 (skip KingMeter protocol frames)
     if (clientDebug && clientDebug.connected()) {
       static uint8_t skipBytes = 0;
       for (int i = 0; i < pos; i++) {
         if (skipBytes > 0) {
           // Skip this byte (part of KingMeter frame)
           skipBytes--;
         } else if (buf[i] == 0x3A) {
           // Start of KingMeter frame detected (0x3A)
           // Skip this byte and the rest of the frame
           // KingMeter 901U frames are max 13 bytes total
           // So skip up to 12 more bytes after 0x3A
           skipBytes = 12;
           // Don't forward the 0x3A byte
         } else {
           // Not part of a KingMeter frame, forward the byte
           clientDebug.write(buf[i]);
         }
       }
     }
   }

  // LOWER PRIORITY: Battery traffic
  pos = 0;
  while (SerialBattery.available() && pos < 64) buf[pos++] = SerialBattery.read();
  if (pos > 0) {
    for (int i = 0; i < pos; i++) {
      if (batteryRxPos < sizeof(batteryRxBuf)) batteryRxBuf[batteryRxPos++] = buf[i];
      if (!flasherInit && ctrlTxPos < sizeof(ctrlTxBuf)) ctrlTxBuf[ctrlTxPos++] = buf[i];
    }
    emitFrames(batteryRxBuf, batteryRxPos, clientUart2, "TX: ", 256);
    if (!flasherInit) emitFrames(ctrlTxBuf, ctrlTxPos, clientUart0, "RX: ", 2048);
  }

  // Network clients to UARTs
  pos = 0;
  while (clientUart0.available() && pos < 64) buf[pos++] = clientUart0.read();
  if (pos > 0) {
    SerialController.write(buf, pos);
    for (int i = 0; i < pos; i++) if (ctrlTxPos < sizeof(ctrlTxBuf)) ctrlTxBuf[ctrlTxPos++] = buf[i];
    emitFrames(ctrlTxBuf, ctrlTxPos, clientUart0, "RX: ", 2048);
  }

  pos = 0;
  while (clientUart1.available() && pos < 64) buf[pos++] = clientUart1.read();
  if (pos > 0) {
    SerialDisplay.write(buf, pos);
    for (int i = 0; i < pos; i++) if (displayTxPos < sizeof(displayTxBuf)) displayTxBuf[displayTxPos++] = buf[i];
    emitFrames(displayTxBuf, displayTxPos, clientUart1, "RX: ", 256);
  }

  pos = 0;
  while (clientUart2.available() && pos < 64) buf[pos++] = clientUart2.read();
  if (pos > 0) {
    SerialBattery.write(buf, pos);
    for (int i = 0; i < pos; i++) if (batteryTxPos < sizeof(batteryTxBuf)) batteryTxBuf[batteryTxPos++] = buf[i];
    emitFrames(batteryTxBuf, batteryTxPos, clientUart2, "RX: ", 256);
  }
  yield();
}

