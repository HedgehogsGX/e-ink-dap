// Decoder benchmark, no DAC needed. Loads each clip from flash (tools/make_bench_clips.sh,
// then `pio run -e decode_bench -t uploadfs`) into PSRAM and decodes it with dr_flac or
// dr_mp3, reporting how much of one 240 MHz core each format needs to play in real time.
// Send "r" over serial to repeat.
#include <Arduino.h>
#include <LittleFS.h>
#include <esp_timer.h>
#define DR_FLAC_NO_STDIO
#include "dr_flac.h"
#define DR_MP3_NO_STDIO
#include "dr_mp3.h"

static constexpr size_t kChunkFrames = 1024;
static drflac_int32 pcm[kChunkFrames * 2];  // stereo, internal RAM like a real output buffer

struct Result {
  uint32_t rate = 0, channels = 0, bits = 0;
  uint64_t frames = 0;
  int64_t us = 0;
};

static bool decodeFlac(const uint8_t* data, size_t size, Result& r) {
  drflac* f = drflac_open_memory(data, size, nullptr);
  if (!f) return false;
  r.rate = f->sampleRate;
  r.channels = f->channels;
  r.bits = f->bitsPerSample;
  if (r.channels > 2) {
    drflac_close(f);
    return false;
  }
  int64_t t0 = esp_timer_get_time();
  drflac_uint64 n;
  while ((n = drflac_read_pcm_frames_s32(f, kChunkFrames, pcm)) > 0) r.frames += n;
  r.us = esp_timer_get_time() - t0;
  drflac_close(f);
  return true;
}

static bool decodeMp3(const uint8_t* data, size_t size, Result& r) {
  drmp3* m = (drmp3*)malloc(sizeof(drmp3));
  if (!m || !drmp3_init_memory(m, data, size, nullptr)) {
    free(m);
    return false;
  }
  r.rate = m->sampleRate;
  r.channels = m->channels;
  r.bits = 16;
  int64_t t0 = esp_timer_get_time();
  drmp3_uint64 n;
  while ((n = drmp3_read_pcm_frames_s16(m, kChunkFrames, (int16_t*)pcm)) > 0) r.frames += n;
  r.us = esp_timer_get_time() - t0;
  drmp3_uninit(m);
  free(m);
  return true;
}

static void benchFile(const char* path) {
  File file = LittleFS.open(path);
  size_t size = file.size();
  uint8_t* data = (uint8_t*)ps_malloc(size);
  if (!data) {
    Serial.printf("%-24s cannot allocate %u bytes\n", path + 1, size);
    return;
  }
  file.read(data, size);
  file.close();

  Result r;
  bool isMp3 = strstr(path, ".mp3") != nullptr;
  bool ok = isMp3 ? decodeMp3(data, size, r) : decodeFlac(data, size, r);
  free(data);
  if (!ok || r.frames == 0) {
    Serial.printf("%-24s decode FAILED\n", path + 1);
    return;
  }
  double audioSec = (double)r.frames / r.rate;
  double cpuPct = r.us / 1e6 / audioSec * 100;
  Serial.printf("%-24s %6lu Hz %2lu-bit %5.0f kbps  %5.2f s audio in %6.0f ms  -> %5.1f%% of one core (%4.1fx real time)\n",
                path + 1, r.rate, r.bits, size * 8 / audioSec / 1000, audioSec, r.us / 1000.0, cpuPct,
                100 / cpuPct);
}

static void runBench() {
  Serial.printf("\n===== Decoder benchmark (CPU %lu MHz, decoding from PSRAM) =====\n", ESP.getCpuFreqMHz());
  File root = LittleFS.open("/");
  int count = 0;
  for (File f = root.openNextFile(); f; f = root.openNextFile()) {
    String path = String("/") + f.name();
    f.close();
    benchFile(path.c_str());
    count++;
  }
  if (!count) Serial.println("No clips in flash: run tools/make_bench_clips.sh, then uploadfs.");
}

void setup() {
  Serial.begin(115200);
  for (uint32_t start = millis(); !Serial && millis() - start < 3000;) delay(10);
  if (!LittleFS.begin(false)) {
    Serial.println("LittleFS mount failed: run `pio run -e decode_bench -t uploadfs` first.");
    return;
  }
  runBench();
}

void loop() {
  if (Serial.available() && Serial.read() == 'r') runBench();
  delay(10);
}
