// I2S clock check, no DAC needed. Runs the I2S output the way the CS4398 board will
// see it (MCLK = 256 fs, 32-bit stereo slots so BCK = 64 fs) and counts the edges on
// the MCK/BCK/LRCK pins themselves with the pulse counter, at each sample rate.
// Send "r" over serial to repeat.
#include <Arduino.h>
#include <driver/i2s_std.h>
#include <driver/pulse_cnt.h>
#include <esp_timer.h>
#include <hal/gpio_ll.h>
#include "pins.h"

static constexpr int kMclkMultiple = 256;
static constexpr int kBckPerFrame = 64;
static const uint32_t kRates[] = {44100, 48000, 88200, 96000};

struct Probe {
  const char* name;
  int gpio;
  uint32_t perFrame;
  pcnt_unit_handle_t unit;
};

static Probe probes[] = {
    {"MCK", PIN_I2S_MCK, kMclkMultiple, nullptr},
    {"BCK", PIN_I2S_BCK, kBckPerFrame, nullptr},
    {"LRCK", PIN_I2S_LRCK, 1, nullptr},
};

static i2s_chan_handle_t tx;

static pcnt_unit_handle_t makeCounter(int gpio) {
  pcnt_unit_config_t unitCfg = {};
  unitCfg.low_limit = -1000;
  unitCfg.high_limit = 30000;
  unitCfg.flags.accum_count = 1;
  pcnt_unit_handle_t unit;
  ESP_ERROR_CHECK(pcnt_new_unit(&unitCfg, &unit));

  pcnt_chan_config_t chanCfg = {};
  chanCfg.edge_gpio_num = gpio;
  chanCfg.level_gpio_num = -1;
  pcnt_channel_handle_t chan;
  ESP_ERROR_CHECK(pcnt_new_channel(unit, &chanCfg, &chan));
  ESP_ERROR_CHECK(pcnt_channel_set_edge_action(chan, PCNT_CHANNEL_EDGE_ACTION_INCREASE,
                                               PCNT_CHANNEL_EDGE_ACTION_HOLD));
  ESP_ERROR_CHECK(pcnt_unit_add_watch_point(unit, unitCfg.high_limit));
  ESP_ERROR_CHECK(pcnt_unit_enable(unit));
  return unit;
}

static void startI2s(uint32_t rate) {
  i2s_chan_config_t chanCfg = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
  chanCfg.auto_clear = true;  // send silence when nothing is written
  ESP_ERROR_CHECK(i2s_new_channel(&chanCfg, &tx, nullptr));

  i2s_std_config_t stdCfg = {
      .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(rate),
      .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_STEREO),
      .gpio_cfg = {
          .mclk = (gpio_num_t)PIN_I2S_MCK,
          .bclk = (gpio_num_t)PIN_I2S_BCK,
          .ws = (gpio_num_t)PIN_I2S_LRCK,
          .dout = (gpio_num_t)PIN_I2S_DATA,
          .din = I2S_GPIO_UNUSED,
          .invert_flags = {},
      },
  };
  stdCfg.clk_cfg.mclk_multiple = (i2s_mclk_multiple_t)kMclkMultiple;
  ESP_ERROR_CHECK(i2s_channel_init_std_mode(tx, &stdCfg));
  ESP_ERROR_CHECK(i2s_channel_enable(tx));
}

static void setRate(uint32_t rate) {
  i2s_std_clk_config_t clk = I2S_STD_CLK_DEFAULT_CONFIG(rate);
  clk.mclk_multiple = (i2s_mclk_multiple_t)kMclkMultiple;
  ESP_ERROR_CHECK(i2s_channel_disable(tx));
  ESP_ERROR_CHECK(i2s_channel_reconfig_std_clock(tx, &clk));
  ESP_ERROR_CHECK(i2s_channel_enable(tx));
}

// Counts all probes over the same gate time; returns the gate length in seconds.
static double countEdges(uint32_t gateUs, int counts[]) {
  for (Probe& p : probes) pcnt_unit_clear_count(p.unit);
  for (Probe& p : probes) pcnt_unit_start(p.unit);
  int64_t t0 = esp_timer_get_time();
  while (esp_timer_get_time() - t0 < gateUs) {
  }
  for (Probe& p : probes) pcnt_unit_stop(p.unit);
  int64_t t1 = esp_timer_get_time();
  for (size_t i = 0; i < 3; i++) pcnt_unit_get_count(probes[i].unit, &counts[i]);
  return (t1 - t0) / 1e6;
}

static void runCheck() {
  Serial.printf("\n===== I2S clock check (MCLK %d fs, BCK %d fs) =====\n", kMclkMultiple, kBckPerFrame);
  int failures = 0;
  for (uint32_t rate : kRates) {
    setRate(rate);
    delay(20);
    int counts[3];
    double gate = countEdges(200000, counts);
    Serial.printf("%6lu Hz:", rate);
    for (size_t i = 0; i < 3; i++) {
      double expected = (double)rate * probes[i].perFrame;
      double measured = counts[i] / gate;
      double ppm = (measured - expected) / expected * 1e6;
      bool ok = fabs(ppm) < 200;
      if (!ok) failures++;
      Serial.printf("  %s %.4f MHz (%+.0f ppm)%s", probes[i].name, measured / 1e6, ppm, ok ? "" : " FAIL");
    }
    Serial.println();
  }
  Serial.printf("RESULT: %s\n", failures ? "FAIL" : "PASS");
}

void setup() {
  Serial.begin(115200);
  for (uint32_t start = millis(); !Serial && millis() - start < 3000;) delay(10);
  // Counters first: their GPIO setup would otherwise take the pins away from I2S.
  for (Probe& p : probes) p.unit = makeCounter(p.gpio);
  startI2s(kRates[0]);
  // I2S claims the pads as outputs; turn the input buffers back on so the counters see them.
  for (Probe& p : probes) gpio_ll_input_enable(&GPIO, (gpio_num_t)p.gpio);
  runCheck();
}

void loop() {
  if (Serial.available() && Serial.read() == 'r') runCheck();
  delay(10);
}
