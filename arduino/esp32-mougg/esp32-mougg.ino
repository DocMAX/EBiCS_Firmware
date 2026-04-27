/**
 * ESP32 UART Bridge
 * ─────────────────────────────────────────────────────────────────────────────
 * Single-core design (no FreeRTOS tasks).
 *
 * At 9600 baud one byte takes ~1.04 ms. The loop() runs in a few
 * microseconds per iteration — fast enough to service all three UARTs
 * without any buffering lag, while keeping the WiFi/TCP stack fully
 * responsive (it runs in the background via esp_wifi interrupt + lwIP).
 *
 * The previous dual-core design pinned a high-priority task to Core 0,
 * starving the WiFi driver (which also lives on Core 0) → slow ping,
 * no TCP output.
 *
 * Monitor port framing (CRLF-delimited lines):
 *   Port 1000 — Controller:  "TX: " = ctrl→disp/batt,  "RX: " = disp/batt/net→ctrl
 *   Port 1001 — Display:     "TX: " = disp→ctrl,        "RX: " = ctrl/net→disp
 *   Port 1002 — Battery:     "TX: " = batt→ctrl,        "RX: " = ctrl/net→batt
 *   Port 1003 — Debug (controller output, KingMeter frames stripped)
 *   Port 1004 — Flasher passthrough (38400 baud, raw)
 *
 * NOTE: All structs/types must be defined before any functions in .ino
 * files to prevent Arduino IDE prototype-injection from breaking type
 * visibility.
 * ─────────────────────────────────────────────────────────────────────────────
 */

#include <Arduino.h>
#include <WiFi.h>
#include <ArduinoOTA.h>
#include <string.h>
#include "config.h"

// ─── Pins & Baud rates ───────────────────────────────────────────────────────
#define UART_CONTROLLER_RX   3
#define UART_CONTROLLER_TX   1
#define UART_DISPLAY_RX     16
#define UART_DISPLAY_TX     17
#define UART_BATTERY_RX     25
#define UART_BATTERY_TX     26
#define WIFI_LED_PIN         2

#define CONTROLLER_BAUD   9600
#define DISPLAY_BAUD      9600
#define BATTERY_BAUD      9600
#define FLASHER_BAUD     38400

#define KM_SOF 0x3A   // KingMeter 901U start-of-frame byte

// ─────────────────────────────────────────────────────────────────────────────
// Types — defined here so Arduino prototype injection cannot move them below
// the functions that reference them.
// ─────────────────────────────────────────────────────────────────────────────

// CRLF-framed line accumulator for monitor ports.
// Each writer direction gets its own instance to prevent frame interleaving.
struct FrameBuf {
  uint8_t data[512];
  int     len;
};

// KingMeter frame filter state-machine.
// Protocol: SOF(1) CMD(1) LEN(1) DATA[LEN] CHECKSUM(1)
// Reads LEN dynamically to skip exactly the right number of bytes.
struct KmFilter {
  enum State : uint8_t { HUNT, GOT_SOF, GOT_CMD, IN_DATA } state;
  uint8_t bytesLeft;
};

// ─── UART instances ───────────────────────────────────────────────────────────
HardwareSerial SerialController(0);
HardwareSerial SerialDisplay(2);
HardwareSerial SerialBattery(1);

// ─── TCP servers & clients ────────────────────────────────────────────────────
WiFiServer serverCtrl(1000);
WiFiServer serverDisp(1001);
WiFiServer serverBatt(1002);
WiFiServer serverDbg(1003);
WiFiServer serverFlasher(1004);

WiFiClient clientCtrl;
WiFiClient clientDisp;
WiFiClient clientBatt;
WiFiClient clientDbg;
WiFiClient clientFlasher;

// ─── Frame monitor buffers ───────────────────────────────────────────────────
// Port 1000 (Controller monitor)
static FrameBuf fb_ctrl_fromCtrl;  // ctrl output   → "TX: "
static FrameBuf fb_ctrl_fromDisp;  // disp→ctrl     → "RX: "
static FrameBuf fb_ctrl_fromBatt;  // batt→ctrl     → "RX: "
static FrameBuf fb_ctrl_fromNet;   // net→ctrl      → "RX: "
// Port 1001 (Display monitor)
static FrameBuf fb_disp_fromDisp;  // disp output   → "TX: "
static FrameBuf fb_disp_fromCtrl;  // ctrl→disp     → "RX: "
static FrameBuf fb_disp_fromNet;   // net→disp      → "RX: "
// Port 1002 (Battery monitor)
static FrameBuf fb_batt_fromBatt;  // batt output   → "TX: "
static FrameBuf fb_batt_fromCtrl;  // ctrl→batt     → "RX: "
static FrameBuf fb_batt_fromNet;   // net→batt      → "RX: "

// ─── Global state ────────────────────────────────────────────────────────────
static bool     flasherMode      = false;
static bool     lastFlasherConn  = false;
static bool     displayDisabled  = false;
static bool     debugEnabled     = false;
static bool     lastDbgConnected = false;
static uint32_t lastReconnect    = 0;
static uint32_t lastLedToggle    = 0;
static bool     ledState         = false;

static KmFilter kmFilter;

// Shared scratch buffer for UART/network reads (single-threaded)
static uint8_t ioBuf[1024];
static uint8_t dbgBuf[512]; static int dLen = 0;

// Magic sequences for STM32 debug enable/disable
static const uint8_t DBG_ENABLE[]  = {0xDE, 0xAD, 0xBE, 0xEF};
static const uint8_t DBG_DISABLE[] = {0xDE, 0xAD, 0xBE, 0xEE};

// ─────────────────────────────────────────────────────────────────────────────
// KmFilter operations
// ─────────────────────────────────────────────────────────────────────────────

static void kmFilterInit(KmFilter &f) {
  f.state     = KmFilter::HUNT;
  f.bytesLeft = 0;
}

// Returns true if the byte is NOT part of a KingMeter frame (i.e. forward it)
static bool kmFilterProcess(KmFilter &f, uint8_t b) {
  switch (f.state) {
    case KmFilter::HUNT:
      if (b == KM_SOF) { f.state = KmFilter::GOT_SOF; return false; }
      return true;
    case KmFilter::GOT_SOF:
      f.state = KmFilter::GOT_CMD;
      return false;
    case KmFilter::GOT_CMD:
      // b is the LEN byte — only proceed if it's a reasonable frame size
      if (b >= 11 && b <= 127) {
        f.bytesLeft = b + 1;  // DATA[LEN] + CHECKSUM(1)
        f.state = KmFilter::IN_DATA;
      } else {
        // Not a valid frame, forward this byte and hunt again
        f.state = KmFilter::HUNT;
        return true;
      }
      return false;
    case KmFilter::IN_DATA:
      if (--f.bytesLeft == 0) f.state = KmFilter::HUNT;
      return false;
  }
  return true;
}

// ─────────────────────────────────────────────────────────────────────────────
// FrameBuf operations
// ─────────────────────────────────────────────────────────────────────────────

static void fbInit(FrameBuf &fb) {
  fb.len = 0;
}

static void fbAppend(FrameBuf &fb, const uint8_t *src, int n) {
  int cap = (int)sizeof(fb.data);
  if (fb.len + n > cap) {
    int drop = fb.len + n - cap;
    memmove(fb.data, fb.data + drop, fb.len - drop);
    fb.len -= drop;
  }
  memcpy(fb.data + fb.len, src, n);
  fb.len += n;
}

// Emit all complete CRLF-delimited frames to client with a 4-char label.
// Non-blocking: defers to next loop() if TCP send buffer is too small.
static void emitFrames(FrameBuf &fb, WiFiClient &cli, const char *lbl) {
  if (fb.len < 2 || !cli || !cli.connected()) return;
  while (fb.len >= 2) {
    int end = -1;
    for (int i = 0; i < fb.len - 1; i++) {
      if (fb.data[i] == '\r' && fb.data[i + 1] == '\n') { end = i; break; }
    }
    if (end < 0) {
      // No complete frame yet. Discard if buffer is completely full.
      if (fb.len >= (int)sizeof(fb.data) - 1) fb.len = 0;
      break;
    }
    // Non-blocking guard: don't write if TCP buffer can't fit the whole frame
    int avail = cli.availableForWrite();
    if (avail > 0 && avail < 4 + end + 2) break;  // retry next loop()

    cli.write((const uint8_t *)lbl, 4);
    cli.write(fb.data, end);
    cli.write((const uint8_t *)"\r\n", 2);

    int consumed = end + 2;
    fb.len -= consumed;
    if (fb.len > 0) memmove(fb.data, fb.data + consumed, fb.len);
  }
}

static void resetAllFrameBufs() {
  fbInit(fb_ctrl_fromCtrl); fbInit(fb_ctrl_fromDisp);
  fbInit(fb_ctrl_fromBatt); fbInit(fb_ctrl_fromNet);
  fbInit(fb_disp_fromDisp); fbInit(fb_disp_fromCtrl); fbInit(fb_disp_fromNet);
  fbInit(fb_batt_fromBatt); fbInit(fb_batt_fromCtrl); fbInit(fb_batt_fromNet);
}

// ─────────────────────────────────────────────────────────────────────────────
// Misc helpers
// ─────────────────────────────────────────────────────────────────────────────

static void handleClient(WiFiServer &srv, WiFiClient &cli) {
  if (srv.hasClient()) {
    WiFiClient nc = srv.accept();
    if (cli && cli.connected())
      nc.stop();
    else
      cli = nc;
  }
}

static void restartController(uint32_t baud, int rxBuf, int txBuf) {
  SerialController.end();
  pinMode(UART_CONTROLLER_TX, OUTPUT);
  digitalWrite(UART_CONTROLLER_TX, HIGH);
  delay(5);
  SerialController.setRxBufferSize(rxBuf);
  SerialController.setTxBufferSize(txBuf);
  SerialController.setDebugOutput(false);
  SerialController.begin(baud, SERIAL_8N1, UART_CONTROLLER_RX, UART_CONTROLLER_TX);
}

// ─────────────────────────────────────────────────────────────────────────────
// Setup
// ─────────────────────────────────────────────────────────────────────────────

void setup() {
  delay(500);
  pinMode(WIFI_LED_PIN, OUTPUT);
  digitalWrite(WIFI_LED_PIN, LOW);

  resetAllFrameBufs();
  kmFilterInit(kmFilter);

  SerialController.setRxBufferSize(2048);
  SerialController.setTxBufferSize(512);
  SerialController.setDebugOutput(false);
  SerialController.begin(CONTROLLER_BAUD, SERIAL_8N1, UART_CONTROLLER_RX, UART_CONTROLLER_TX);

  SerialDisplay.setRxBufferSize(1024);
  SerialDisplay.setTxBufferSize(512);
  SerialDisplay.setDebugOutput(false);
  SerialDisplay.begin(DISPLAY_BAUD, SERIAL_8N1, UART_DISPLAY_RX, UART_DISPLAY_TX);

  SerialBattery.setRxBufferSize(512);
  SerialBattery.setTxBufferSize(512);
  SerialBattery.setDebugOutput(false);
  SerialBattery.begin(BATTERY_BAUD, SERIAL_8N1, UART_BATTERY_RX, UART_BATTERY_TX);

  WiFi.persistent(false);
  WiFi.mode(WIFI_STA);
  WiFi.disconnect(true);
  WiFi.setAutoReconnect(true);
  WiFi.setHostname("esp32-mougg");
  delay(100);

  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  uint32_t timeout = millis() + 30000;
  while (WiFi.status() != WL_CONNECTED && millis() < timeout) {
    delay(200);
    digitalWrite(WIFI_LED_PIN, !digitalRead(WIFI_LED_PIN));
  }
  lastReconnect = millis();

  serverCtrl.begin();
  serverDisp.begin();
  serverBatt.begin();
  serverDbg.begin();
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

// ─────────────────────────────────────────────────────────────────────────────
// Loop
// ─────────────────────────────────────────────────────────────────────────────

void loop() {
  int n;

  // ── Non-blocking LED blink ───────────────────────────────────────────────
  {
    uint32_t now      = millis();
    uint32_t interval = (WiFi.status() == WL_CONNECTED) ? 2000u : 150u;
    if (now - lastLedToggle >= interval) {
      ledState = !ledState;
      digitalWrite(WIFI_LED_PIN, ledState ? HIGH : LOW);
      lastLedToggle = now;
    }
  }

  // ── OTA & WiFi watchdog ──────────────────────────────────────────────────
  ArduinoOTA.handle();
  if (WiFi.status() != WL_CONNECTED && millis() - lastReconnect > 10000) {
    WiFi.reconnect();
    lastReconnect = millis();
  }

  // ── Flasher: accept new connection ──────────────────────────────────────
  if (serverFlasher.hasClient()) {
    if (clientFlasher && clientFlasher.connected()) {
      serverFlasher.accept().stop();  // reject duplicate
    } else {
      if (clientCtrl) clientCtrl.stop();
      if (clientDisp) clientDisp.stop();
      if (clientBatt) clientBatt.stop();
      if (clientDbg)  clientDbg.stop();

      restartController(FLASHER_BAUD, 256, 256);
      while (SerialController.available()) SerialController.read();
      SerialController.flush();
      resetAllFrameBufs();
      kmFilterInit(kmFilter);

      displayDisabled  = true;
      flasherMode      = true;
      lastFlasherConn  = true;
      lastDbgConnected = false;
      clientFlasher    = serverFlasher.accept();
    }
  }

  // ── Flasher mode: raw bidirectional passthrough ──────────────────────────
  if (flasherMode && clientFlasher && clientFlasher.connected()) {
    n = clientFlasher.available();
    if (n > 0) {
      n = clientFlasher.readBytes(ioBuf, min(n, (int)sizeof(ioBuf)));
      SerialController.write(ioBuf, n);
    }
    n = SerialController.available();
    if (n > 0) {
      n = SerialController.readBytes(ioBuf, min(n, (int)sizeof(ioBuf)));
      clientFlasher.write(ioBuf, n);
    }
    yield();
    return;
  }

  // ── Flasher disconnect: restore normal mode ──────────────────────────────
  bool flasherNow = clientFlasher && clientFlasher.connected();
  if (lastFlasherConn && !flasherNow) {
    restartController(CONTROLLER_BAUD, 2048, 512);
    resetAllFrameBufs();
    kmFilterInit(kmFilter);
    displayDisabled = false;
    flasherMode     = false;
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    lastReconnect = millis();
  }
  lastFlasherConn = flasherNow;

  // ── Accept normal TCP clients ────────────────────────────────────────────
  handleClient(serverCtrl, clientCtrl);
  handleClient(serverDisp, clientDisp);
  handleClient(serverBatt, clientBatt);
  handleClient(serverDbg,  clientDbg);

  // ── Debug port connect/disconnect → control sequence to STM32 ────────────
  // delay() here is acceptable: only runs once on connect/disconnect events,
  // not every loop iteration.
  {
    bool dbgNow = clientDbg && clientDbg.connected();
    if (dbgNow && !lastDbgConnected) {
      for (int i = 0; i < 3; i++) {
        SerialController.write(DBG_ENABLE, sizeof(DBG_ENABLE));
        delay(15);
      }
      debugEnabled = true;
    } else if (!dbgNow && lastDbgConnected) {
      for (int i = 0; i < 3; i++) {
        SerialController.write(DBG_DISABLE, sizeof(DBG_DISABLE));
        delay(15);
      }
      debugEnabled = false;
    }
    lastDbgConnected = dbgNow;
  }

  // ═════════════════════════════════════════════════════════════════════════
  // CRITICAL PATH 1: Display → Controller
  // Read all available bytes and forward immediately — zero extra latency.
  // ═════════════════════════════════════════════════════════════════════════
  n = SerialDisplay.available();
  if (n > 0) {
    n = SerialDisplay.readBytes(ioBuf, min(n, (int)sizeof(ioBuf)));
    SerialController.write(ioBuf, n);                   // forward immediately

    fbAppend(fb_disp_fromDisp, ioBuf, n);              // port1001 "TX:"
    fbAppend(fb_ctrl_fromDisp, ioBuf, n);              // port1000 "RX:"
  }

  // ═════════════════════════════════════════════════════════════════════════
  // CRITICAL PATH 2: Controller → Display + Battery
  // ═════════════════════════════════════════════════════════════════════════
  n = SerialController.available();
  if (n > 0) {
    n = SerialController.readBytes(ioBuf, min(n, (int)sizeof(ioBuf)));
    if (!displayDisabled) SerialDisplay.write(ioBuf, n);
    SerialBattery.write(ioBuf, n);

    fbAppend(fb_ctrl_fromCtrl, ioBuf, n);              // port1000 "TX:"
    fbAppend(fb_disp_fromCtrl, ioBuf, n);              // port1001 "RX:"
    fbAppend(fb_batt_fromCtrl, ioBuf, n);              // port1002 "RX:"

    // Debug port: buffer capture (extraction deferred)
    if (debugEnabled && clientDbg && clientDbg.connected()) {
      if (dLen + n > (int)sizeof(dbgBuf)) {
        int drop = dLen + n - sizeof(dbgBuf);
        if (drop < dLen) { memmove(dbgBuf, dbgBuf + drop, dLen - drop); dLen -= drop; }
        else dLen = 0;
      }
      if (dLen + n <= (int)sizeof(dbgBuf)) { memcpy(dbgBuf + dLen, ioBuf, n); dLen += n; }
    }
  }

  // ═════════════════════════════════════════════════════════════════════════
  // Battery → Controller
  // ═════════════════════════════════════════════════════════════════════════
  n = SerialBattery.available();
  if (n > 0) {
    n = SerialBattery.readBytes(ioBuf, min(n, (int)sizeof(ioBuf)));
    SerialController.write(ioBuf, n);

    fbAppend(fb_batt_fromBatt, ioBuf, n);              // port1002 "TX:"
    fbAppend(fb_ctrl_fromBatt, ioBuf, n);              // port1000 "RX:"
  }

  // ═════════════════════════════════════════════════════════════════════════
  // Network → UART (commands injected from monitoring clients)
  // ═════════════════════════════════════════════════════════════════════════

  // Port 1000 → Controller
  n = clientCtrl.available();
  if (n > 0) {
    n = clientCtrl.readBytes(ioBuf, min(n, (int)sizeof(ioBuf)));
    SerialController.write(ioBuf, n);
    fbAppend(fb_ctrl_fromNet, ioBuf, n);
  }

  // Port 1001 → Display
  n = clientDisp.available();
  if (n > 0) {
    n = clientDisp.readBytes(ioBuf, min(n, (int)sizeof(ioBuf)));
    SerialDisplay.write(ioBuf, n);
    fbAppend(fb_disp_fromNet, ioBuf, n);
  }

  // Port 1002 → Battery
  n = clientBatt.available();
  if (n > 0) {
    n = clientBatt.readBytes(ioBuf, min(n, (int)sizeof(ioBuf)));
    SerialBattery.write(ioBuf, n);
    fbAppend(fb_batt_fromNet, ioBuf, n);
  }


  // ── DEFERRED: TCP frame emission ──────────────────────────────
  emitFrames(fb_ctrl_fromCtrl, clientCtrl, "TX: ");
  emitFrames(fb_ctrl_fromDisp, clientCtrl, "RX: ");
  emitFrames(fb_ctrl_fromBatt, clientCtrl, "RX: ");
  emitFrames(fb_ctrl_fromNet,  clientCtrl, "RX: ");

  emitFrames(fb_disp_fromDisp, clientDisp, "TX: ");
  emitFrames(fb_disp_fromCtrl, clientDisp, "RX: ");
  emitFrames(fb_disp_fromNet,  clientDisp, "RX: ");

  emitFrames(fb_batt_fromBatt, clientBatt, "TX: ");
  emitFrames(fb_batt_fromCtrl, clientBatt, "RX: ");
  emitFrames(fb_batt_fromNet,  clientBatt, "RX: ");


  // ── DEFERRED: Debug extraction ────────────────────────────────────
  if (debugEnabled && clientDbg && clientDbg.connected() && dLen > 0) {
    int k=0,j=0,kept=0;
    for (int p=0; dLen>0 && p<dLen-4; p++) {
      if(dbgBuf[p]=='$'&&dbgBuf[p+1]=='D'&&dbgBuf[p+2]=='B'&&dbgBuf[p+3]=='G'){
        for(k=p+4,j=-1;j<0&&k<dLen;k++)if(dbgBuf[k]=='\n')j=k;if(j<0)break;
        clientDbg.write(dbgBuf+p+4,j-p-4+1);kept=dLen-(j+1);
        if(kept>0)memmove(dbgBuf,dbgBuf+j+1,kept);dLen=kept;p=-1;
      }
    }
  }

  yield();
}
