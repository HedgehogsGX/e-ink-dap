// Bare-board self-test. Nothing needs to be wired.
//  1. Chip, flash and PSRAM: confirms this is an N16R8 and the PSRAM setting is right.
//  2. Pins: checks every planned pin with the internal pull-up and pull-down only
//     (never drives a pin), so a dead pin or something already attached shows up.
//  3. RGB LED: blinks GPIO38 red and GPIO48 green in turn. Whichever colour you see
//     tells the board revision (red = v1.1, green = v1.0); set DEVKITC_REV in pins.h.
// Send "r" over serial to print the report again.
#include <Arduino.h>
#include <esp_chip_info.h>
#include <esp_flash.h>
#include <stdarg.h>
#include "pins.h"

static char report[4096];
static size_t reportLen = 0;

static void out(const char* fmt, ...) {
  va_list args;
  va_start(args, fmt);
  int n = vsnprintf(report + reportLen, sizeof(report) - reportLen, fmt, args);
  va_end(args);
  if (n > 0) reportLen = min(reportLen + n, sizeof(report) - 1);
}

static int failures = 0;

static void checkChip() {
  esp_chip_info_t info;
  esp_chip_info(&info);
  out("Chip:   %s rev v%d.%d, %d cores, %lu MHz\n", ESP.getChipModel(),
      info.revision / 100, info.revision % 100, info.cores, ESP.getCpuFreqMHz());

  uint32_t flashId = 0, flashSize = 0;
  esp_flash_read_id(nullptr, &flashId);
  esp_flash_get_physical_size(nullptr, &flashSize);
  bool flashOk = flashSize == 16u * 1024 * 1024;
  out("Flash:  %lu MB physical (JEDEC id %06lX), image built for %lu MB  [%s]\n",
      flashSize >> 20, flashId, ESP.getFlashChipSize() >> 20, flashOk ? "OK" : "FAIL");
  if (!flashOk) failures++;

  size_t psram = ESP.getPsramSize();
  bool psramOk = psram >= 8u * 1024 * 1024 - 512 * 1024;  // allocator keeps a little
  out("PSRAM:  %u KB total, %u KB free  [%s]\n", psram / 1024, ESP.getFreePsram() / 1024,
      psramOk ? "OK" : "FAIL - check OPI PSRAM setting");
  if (!psramOk) {
    failures++;
    return;
  }

  // Write and verify 4 MB, timing both passes.
  const size_t words = 1024 * 1024;
  uint32_t* buf = (uint32_t*)ps_malloc(words * sizeof(uint32_t));
  if (!buf) {
    out("PSRAM:  4 MB allocation failed  [FAIL]\n");
    failures++;
    return;
  }
  uint32_t t0 = micros();
  for (size_t i = 0; i < words; i++) buf[i] = i ^ 0xA5A5A5A5u;
  uint32_t t1 = micros();
  size_t bad = 0;
  for (size_t i = 0; i < words; i++) bad += buf[i] != (i ^ 0xA5A5A5A5u);
  uint32_t t2 = micros();
  free(buf);
  out("PSRAM:  4 MB pattern test, %u bad words, write %.0f MB/s, read %.0f MB/s  [%s]\n", bad,
      4.0e6 / (t1 - t0), 4.0e6 / (t2 - t1), bad ? "FAIL" : "OK");
  if (bad) failures++;
}

struct NamedPin {
  const char* name;
  int gpio;
};

static const NamedPin kPins[] = {
    {"EPD_CS", PIN_EPD_CS},       {"EPD_MOSI", PIN_EPD_MOSI},     {"EPD_SCK", PIN_EPD_SCK},
    {"EPD_DC", PIN_EPD_DC},       {"EPD_RST", PIN_EPD_RST},       {"EPD_BUSY", PIN_EPD_BUSY},
    {"TOUCH_SDA", PIN_TOUCH_SDA}, {"TOUCH_SCL", PIN_TOUCH_SCL},   {"TOUCH_INT", PIN_TOUCH_INT},
    {"SD_CLK", PIN_SD_CLK},       {"SD_CMD", PIN_SD_CMD},         {"SD_D0", PIN_SD_D0},
    {"SD_D1", PIN_SD_D1},         {"SD_D2", PIN_SD_D2},           {"SD_D3", PIN_SD_D3},
    {"I2S_MCK", PIN_I2S_MCK},     {"I2S_BCK", PIN_I2S_BCK},       {"I2S_LRCK", PIN_I2S_LRCK},
    {"I2S_DATA", PIN_I2S_DATA},   {"BTN_PLAY", PIN_BTN_PLAY},     {"BTN_VOL_UP", PIN_BTN_VOL_UP},
    {"BTN_VOL_DOWN", PIN_BTN_VOL_DOWN}, {"BTN_POWER", PIN_BTN_POWER},
    {"GPIO38 (LED or TOUCH_RST)", 38}, {"GPIO48 (LED or TOUCH_RST)", 48},
};

static void checkPins() {
  out("\nPins (internal pulls only; 'free' = nothing attached, as expected on a bare board):\n");
  int attached = 0, faults = 0;
  for (const NamedPin& p : kPins) {
    pinMode(p.gpio, INPUT_PULLUP);
    delayMicroseconds(300);
    int up = digitalRead(p.gpio);
    pinMode(p.gpio, INPUT_PULLDOWN);
    delayMicroseconds(300);
    int down = digitalRead(p.gpio);
    pinMode(p.gpio, INPUT);

    const char* verdict;
    if (up == 1 && down == 0) {
      verdict = "free";
    } else if (up == 1 && down == 1) {
      verdict = "held HIGH by something attached";
      attached++;
    } else if (up == 0 && down == 0) {
      verdict = "held LOW by something attached";
      attached++;
    } else {
      verdict = "FAULT (reads opposite of the pull)";
      faults++;
    }
    out("  GPIO%-2d %-26s %s\n", p.gpio, p.name, verdict);
  }
  out("Pins:   %d free, %d with something attached, %d faults  [%s]\n",
      (int)(sizeof(kPins) / sizeof(kPins[0])) - attached - faults, attached, faults,
      faults ? "FAIL" : "OK");
  failures += faults;
}

static void printReport() {
  Serial.print("\n===== E-ink DAP self-test =====\n");
  Serial.print(report);
  Serial.printf("RESULT: %s\n", failures ? "FAIL" : "PASS");
  Serial.print("LED test running: GPIO38 = red, GPIO48 = green (1.5 s each)\n");
}

void setup() {
  Serial.begin(115200);
  for (uint32_t start = millis(); !Serial && millis() - start < 3000;) delay(10);
  checkChip();
  checkPins();
  printReport();
}

void loop() {
  static const struct { int gpio; uint8_t r, g; } kLeds[] = {{38, 40, 0}, {48, 0, 40}};
  for (const auto& led : kLeds) {
    if (PIN_BOARD_LED >= 0 && led.gpio != PIN_BOARD_LED) continue;
    Serial.printf("LED: driving GPIO%d (%s)\n", led.gpio, led.r ? "red" : "green");
    rgbLedWrite(led.gpio, led.r, led.g, 0);
    for (uint32_t start = millis(); millis() - start < 1500;) {
      if (Serial.available() && Serial.read() == 'r') printReport();
      delay(10);
    }
    rgbLedWrite(led.gpio, 0, 0, 0);
  }
}
