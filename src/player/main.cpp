// Player skeleton for the bare board.
// - Audio task (core 1): feeds I2S and never waits on the UI.
// - Control task (core 0): owns player state, reads buttons and serial commands, and
//   "renders" by printing a status line, then blocking for as long as an e-ink refresh
//   would, to prove audio keeps flowing (underruns must stay 0).
// Until the SD card is wired, the tracks are test tones at different sample rates.
//
// Buttons: BOOT or Play short = play/pause, long = next. Vol+/Vol- short = volume,
// long = next/previous. Power toggles the lock (the bare board has nothing to switch
// off). Serial: type "h" for commands.
#include <Arduino.h>
#include <esp_timer.h>

#include <atomic>
#include <cmath>

#include "audio_out.h"
#include "buttons.h"
#include "pins.h"

struct Track {
  const char* title;
  uint32_t rate;
  uint32_t seconds;
  float toneHz;
};

static const Track kTracks[] = {
    {"Tone A 440 Hz", 44100, 20, 440.0f},
    {"Tone B 1 kHz", 48000, 15, 1000.0f},
    {"Tone C 2 kHz (hi-res)", 96000, 12, 2000.0f},
};
static constexpr int kTrackCount = sizeof(kTracks) / sizeof(kTracks[0]);

// Volume steps: 0 = mute, 1.5 dB per step, kVolMax = 0 dB. Starts low for sensitive IEMs.
static constexpr int kVolMax = 40;
static float volumeDb(int vol) { return (vol - kVolMax) * 1.5f; }

// Written by the control task, read by the audio task.
static std::atomic<bool> gPlaying{false};
static std::atomic<int> gVolume{10};
static std::atomic<int> gTrack{0};
static std::atomic<uint32_t> gTrackGen{0};  // bumped on every track start
static std::atomic<uint32_t> gStallMs{0};   // diagnostic: audio task sleeps this long once
// Written by the audio task, read by the control task.
static std::atomic<uint32_t> gFramesPlayed{0};
static std::atomic<uint32_t> gAudioLoadPermille{0};

static AudioOut audioOut;

static void audioTask(void*) {
  constexpr size_t kFrames = 256;
  static int32_t buf[kFrames * 2];
  audioOut.begin(kTracks[0].rate);
  uint32_t gen = ~0u;
  float phase = 0, step = 0;
  int64_t busyUs = 0, windowStart = esp_timer_get_time();
  for (;;) {
    uint32_t g = gTrackGen.load();
    if (g != gen) {
      gen = g;
      const Track& t = kTracks[gTrack.load()];
      audioOut.setRate(t.rate);
      step = 2 * PI * t.toneHz / t.rate;
      phase = 0;
      gFramesPlayed = 0;
    }

    int64_t t0 = esp_timer_get_time();
    bool playing = gPlaying.load();
    int vol = gVolume.load();
    // Tone at -12 dBFS, then volume.
    float amp = (playing && vol > 0) ? 0.25f * 2147483647.0f * powf(10.0f, volumeDb(vol) / 20) : 0.0f;
    for (size_t i = 0; i < kFrames; i++) {
      int32_t s = (int32_t)(sinf(phase) * amp);
      buf[2 * i] = s;
      buf[2 * i + 1] = s;
      phase += step;
      if (phase > 2 * PI) phase -= 2 * PI;
    }
    int64_t t1 = esp_timer_get_time();
    busyUs += t1 - t0;

    if (uint32_t stall = gStallMs.exchange(0)) vTaskDelay(pdMS_TO_TICKS(stall));
    audioOut.write(buf, kFrames);
    if (playing) gFramesPlayed += kFrames;
    if (t1 - windowStart >= 1000000) {
      gAudioLoadPermille = busyUs * 1000 / (t1 - windowStart);
      busyUs = 0;
      windowStart = t1;
    }
  }
}

// ---- Control task (core 0) ----

static bool locked = false;
// GxEPD2's timings for the GDEY037T03; adjust the full one with "refresh <ms>".
static uint32_t fullRefreshMs = 1500;
static uint32_t partialRefreshMs = 350;  // progress bar / lyrics line
static uint32_t underrunsAtBoot = 0;

static void busyFor(uint32_t ms) {  // like a refresh that polls the BUSY pin
  for (uint32_t start = millis(); millis() - start < ms;) {
  }
}

static void render(bool full) {
  const Track& t = kTracks[gTrack.load()];
  uint32_t pos = gFramesPlayed.load() / t.rate;
  uint32_t load = gAudioLoadPermille.load();
  int vol = gVolume.load();
  Serial.printf("[%s%s] %d/%d %-22s %6lu Hz  %lu:%02lu / %lu:%02lu  vol %2d/%d (%5.1f dB)  audio core%d %lu.%lu%%  underruns %lu  (%s refresh %lu ms)\n",
                gPlaying ? "PLAY " : "PAUSE", locked ? " LOCK" : "", gTrack.load() + 1, kTrackCount, t.title,
                audioOut.rate(), pos / 60, pos % 60, t.seconds / 60, t.seconds % 60, vol, kVolMax,
                vol ? volumeDb(vol) : -INFINITY, 1, load / 10, load % 10, audioOut.underruns() - underrunsAtBoot,
                full ? "full" : "partial", full ? fullRefreshMs : partialRefreshMs);
  busyFor(full ? fullRefreshMs : partialRefreshMs);
}

static void startTrack(int index, bool play) {
  gTrack = (index + kTrackCount) % kTrackCount;
  gFramesPlayed = 0;
  gPlaying = play;
  gTrackGen++;
  delay(20);  // let the audio task switch rate before rendering
  render(true);
}

enum class Cmd { None, PlayPause, Next, Prev, VolUp, VolDown, Lock, Status, Help };

static void apply(Cmd cmd) {
  switch (cmd) {
    case Cmd::PlayPause:
      gPlaying = !gPlaying;
      render(false);
      break;
    case Cmd::Next:
      startTrack(gTrack + 1, gPlaying);
      break;
    case Cmd::Prev:
      startTrack(gTrack - 1, gPlaying);
      break;
    case Cmd::VolUp:
      gVolume = min(gVolume + 1, kVolMax);
      render(false);
      break;
    case Cmd::VolDown:
      gVolume = max(gVolume - 1, 0);
      render(false);
      break;
    case Cmd::Lock:
      locked = !locked;
      render(false);
      break;
    case Cmd::Status:
      render(false);
      break;
    case Cmd::Help:
      Serial.println("Commands: p play/pause | n next | b previous | + / - volume | l lock | s status\n"
                     "          refresh <ms>  set full-refresh blocking time and do one\n"
                     "          stall <ms>    make the audio task late once (should count underruns)");
      break;
    case Cmd::None:
      break;
  }
}

static Cmd parseLine(String line) {
  line.trim();
  if (line.startsWith("refresh")) {
    long ms = line.substring(7).toInt();
    if (ms > 0) fullRefreshMs = ms;
    render(true);
    return Cmd::None;
  }
  if (line.startsWith("stall")) {
    gStallMs = max(line.substring(5).toInt(), 1L);
    delay(gStallMs + 50);
    render(false);
    return Cmd::None;
  }
  if (line == "p" || line == "play") return Cmd::PlayPause;
  if (line == "n" || line == "next") return Cmd::Next;
  if (line == "b" || line == "prev") return Cmd::Prev;
  if (line == "+") return Cmd::VolUp;
  if (line == "-") return Cmd::VolDown;
  if (line == "l" || line == "lock") return Cmd::Lock;
  if (line == "s" || line == "status") return Cmd::Status;
  if (line == "h" || line == "help") return Cmd::Help;
  if (line.length()) Serial.printf("Unknown command '%s', type h for help\n", line.c_str());
  return Cmd::None;
}

static Cmd fromButton(Press press, Cmd shortCmd, Cmd longCmd) {
  if (press == Press::None || (locked && shortCmd != Cmd::Lock)) return Cmd::None;
  return press == Press::Short ? shortCmd : longCmd;
}

static void controlTask(void*) {
  Button boot(0), play(PIN_BTN_PLAY), volUp(PIN_BTN_VOL_UP), volDown(PIN_BTN_VOL_DOWN), power(PIN_BTN_POWER);
  for (Button* b : {&boot, &play, &volUp, &volDown, &power}) b->begin();

  delay(200);
  underrunsAtBoot = audioOut.underruns();  // I2S start-up, before any audio was due
  Serial.printf("\nE-ink DAP player skeleton: audio task on core 1, control task on core %d. Type h for help.\n",
                xPortGetCoreID());
  startTrack(0, false);

  String line;
  uint32_t lastProgress = millis();
  for (;;) {
    uint32_t now = millis();
    apply(fromButton(boot.poll(now), Cmd::PlayPause, Cmd::Next));
    apply(fromButton(play.poll(now), Cmd::PlayPause, Cmd::Next));
    apply(fromButton(volUp.poll(now), Cmd::VolUp, Cmd::Next));
    apply(fromButton(volDown.poll(now), Cmd::VolDown, Cmd::Prev));
    apply(fromButton(power.poll(now), Cmd::Lock, Cmd::Lock));

    while (Serial.available()) {
      char c = Serial.read();
      if (c == '\n' || c == '\r') {
        apply(parseLine(line));
        line = "";
      } else {
        line += c;
      }
    }

    const Track& t = kTracks[gTrack.load()];
    if (gPlaying && gFramesPlayed.load() >= t.rate * t.seconds) {
      startTrack(gTrack + 1, true);
    } else if (gPlaying && millis() - lastProgress >= 5000) {
      lastProgress = millis();
      render(false);
    }
    delay(10);
  }
}

void setup() {
  Serial.begin(115200);
  for (uint32_t start = millis(); !Serial && millis() - start < 3000;) delay(10);
  xTaskCreatePinnedToCore(audioTask, "audio", 4096, nullptr, configMAX_PRIORITIES - 2, nullptr, 1);
  xTaskCreatePinnedToCore(controlTask, "control", 6144, nullptr, 5, nullptr, 0);
}

void loop() { vTaskDelay(portMAX_DELAY); }
