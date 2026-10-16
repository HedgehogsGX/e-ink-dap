// Bring-up 4: CS4398 DAC board through ESP32-audioI2S, playing files from the SD card.
// FIRST TEST: IEMs NOT in your ears. Start quiet; the volume begins at 3 of 21.
// Wiring: MCK/BCK/LRCK/DATA per pins.h, GND shared with the ESP32, DAC board powered from
// its own USB-C, its 3V3_OUT left unconnected.
// Copy test.wav, test.mp3 and test.flac (44.1 or 48 kHz) to the SD card's root.
// Serial: n next file, p pause/resume, + / - volume.
// Note: ESP32-audioI2S is GPL-3.0 and resamples to a fixed 44.1/48 kHz output; it is only
// used here to prove the DAC path, not in the player.
#include <Arduino.h>
#include <Audio.h>
#include <SD_MMC.h>

#include "pins.h"

static Audio audio;
static const char* kFiles[] = {"/test.wav", "/test.mp3", "/test.flac"};
static int current = -1;
static uint8_t volume = 3;

static void playNext() {
  for (int tries = 0; tries < 3; tries++) {
    current = (current + 1) % 3;
    if (SD_MMC.exists(kFiles[current])) {
      Serial.printf("\nPlaying %s\n", kFiles[current]);
      audio.connecttoFS(SD_MMC, kFiles[current]);
      return;
    }
    Serial.printf("%s not on the card, skipping\n", kFiles[current]);
  }
}

void setup() {
  Serial.begin(115200);
  for (uint32_t start = millis(); !Serial && millis() - start < 3000;) delay(10);
  Serial.println("\n===== Bring-up: DAC (CS4398 board) =====");

  SD_MMC.setPins(PIN_SD_CLK, PIN_SD_CMD, PIN_SD_D0, PIN_SD_D1, PIN_SD_D2, PIN_SD_D3);
  while (!SD_MMC.begin("/sdcard", false)) {
    Serial.println("SD mount failed: get bringup_sd passing first. Retrying in 3 s.");
    delay(3000);
  }
  Audio::audio_info_callback = [](Audio::msg_t m) { Serial.printf("  %s: %s\n", m.s, m.msg); };
  audio.setPinout(PIN_I2S_BCK, PIN_I2S_LRCK, PIN_I2S_DATA, PIN_I2S_MCK);  // MCLK is required by the CS4398
  audio.setVolume(volume);
  playNext();
}

void loop() {
  audio.loop();
  if (!audio.isRunning() && current >= 0) playNext();
  if (Serial.available()) {
    switch (Serial.read()) {
      case 'n': playNext(); break;
      case 'p': audio.pauseResume(); break;
      case '+': audio.setVolume(volume = min(volume + 1, 21)); Serial.printf("volume %u/21\n", volume); break;
      case '-': audio.setVolume(volume = max(volume - 1, 0)); Serial.printf("volume %u/21\n", volume); break;
    }
  }
}
