// Bring-up 3: microSD in 4-bit SDMMC mode. Card must be FAT32.
// Wiring needs 10 kΩ pull-ups to 3.3 V on CMD and D0-D3 (not CLK), wires ~10 cm or shorter.
// Mounts the card at 20 MHz and 40 MHz, lists the root folder, and measures read speed
// on the largest file in it. Repeats every 10 s, or send "r".
#include <Arduino.h>
#include <SD_MMC.h>

#include "pins.h"

static void listRoot(String& largest, size_t& largestSize) {
  File root = SD_MMC.open("/");
  int shown = 0;
  for (File f = root.openNextFile(); f; f = root.openNextFile()) {
    if (shown++ < 30) Serial.printf("  %s %-40s %10u bytes\n", f.isDirectory() ? "DIR " : "    ", f.name(), f.size());
    if (!f.isDirectory() && f.size() > largestSize) {
      largestSize = f.size();
      largest = String("/") + f.name();
    }
  }
  if (shown > 30) Serial.printf("  ... %d entries in total\n", shown);
}

static void readSpeed(const String& path, size_t size) {
  static uint8_t buf[32 * 1024];
  File f = SD_MMC.open(path);
  size_t want = min(size, (size_t)8 * 1024 * 1024), got = 0;
  uint32_t t0 = micros();
  while (got < want) {
    size_t n = f.read(buf, sizeof(buf));
    if (!n) break;
    got += n;
  }
  uint32_t us = micros() - t0;
  f.close();
  Serial.printf("  Read %u KB of %s in %lu ms: %.2f MB/s (96/24 FLAC needs ~0.5 MB/s)\n", got / 1024, path.c_str(),
                us / 1000, got / (double)us);
}

static bool test(int freqKhz) {
  Serial.printf("\n--- Mount, 4-bit, %d MHz ---\n", freqKhz / 1000);
  if (!SD_MMC.begin("/sdcard", false, false, freqKhz)) {
    Serial.println("  Mount FAILED. Check: card is FAT32 (not exFAT), pull-ups on CMD/D0-D3, all 6 wires, shared GND.");
    return false;
  }
  static const char* kTypes[] = {"none", "MMC", "SD", "SDHC/SDXC", "unknown"};
  Serial.printf("  Card: %s, %llu MB, filesystem %llu MB, used %llu MB\n", kTypes[min((int)SD_MMC.cardType(), 4)],
                SD_MMC.cardSize() >> 20, SD_MMC.totalBytes() >> 20, SD_MMC.usedBytes() >> 20);
  String largest;
  size_t largestSize = 0;
  listRoot(largest, largestSize);
  if (largestSize) readSpeed(largest, largestSize);
  else Serial.println("  Root folder has no files to time; copy any large file onto the card.");
  SD_MMC.end();
  return true;
}

static void runAll() {
  Serial.println("\n===== Bring-up: microSD (SDMMC 4-bit) =====");
  if (test(SDMMC_FREQ_DEFAULT)) test(SDMMC_FREQ_HIGHSPEED);
}

void setup() {
  Serial.begin(115200);
  for (uint32_t start = millis(); !Serial && millis() - start < 3000;) delay(10);
  SD_MMC.setPins(PIN_SD_CLK, PIN_SD_CMD, PIN_SD_D0, PIN_SD_D1, PIN_SD_D2, PIN_SD_D3);
  runAll();
}

void loop() {
  static uint32_t last = millis();
  if ((Serial.available() && Serial.read() == 'r') || millis() - last >= 10000) {
    runAll();
    last = millis();
  }
  delay(10);
}
