#include "audio_out.h"

#include <driver/i2s_std.h>
#include <esp_attr.h>
#include <esp_err.h>
#include <freertos/FreeRTOS.h>

#include "pins.h"

static constexpr i2s_mclk_multiple_t kMclkMultiple = I2S_MCLK_MULTIPLE_256;

struct AudioOutCallbacks {
  static bool IRAM_ATTR onSendQueueOverflow(i2s_chan_handle_t, i2s_event_data_t*, void* ctx) {
    static_cast<AudioOut*>(ctx)->underruns_.fetch_add(1, std::memory_order_relaxed);
    return false;
  }
};

void AudioOut::begin(uint32_t sampleRate) {
  i2s_chan_config_t chanCfg = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
  chanCfg.dma_desc_num = 8;
  chanCfg.dma_frame_num = 511;  // largest that fits one DMA descriptor at 8 bytes/frame
  chanCfg.auto_clear = true;    // silence, not a repeated buffer, if we fall behind
  i2s_chan_handle_t tx;
  ESP_ERROR_CHECK(i2s_new_channel(&chanCfg, &tx, nullptr));

  i2s_std_config_t stdCfg = {
      .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(sampleRate),
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
  stdCfg.clk_cfg.mclk_multiple = kMclkMultiple;
  ESP_ERROR_CHECK(i2s_channel_init_std_mode(tx, &stdCfg));

  i2s_event_callbacks_t cbs = {};
  cbs.on_send_q_ovf = AudioOutCallbacks::onSendQueueOverflow;
  ESP_ERROR_CHECK(i2s_channel_register_event_callback(tx, &cbs, this));
  ESP_ERROR_CHECK(i2s_channel_enable(tx));
  tx_ = tx;
  rate_ = sampleRate;
}

void AudioOut::setRate(uint32_t sampleRate) {
  if (sampleRate == rate_) return;
  auto tx = static_cast<i2s_chan_handle_t>(tx_);
  i2s_std_clk_config_t clk = I2S_STD_CLK_DEFAULT_CONFIG(sampleRate);
  clk.mclk_multiple = kMclkMultiple;
  ESP_ERROR_CHECK(i2s_channel_disable(tx));
  ESP_ERROR_CHECK(i2s_channel_reconfig_std_clock(tx, &clk));
  ESP_ERROR_CHECK(i2s_channel_enable(tx));
  rate_ = sampleRate;
}

void AudioOut::write(const int32_t* frames, size_t count) {
  size_t written = 0;
  i2s_channel_write(static_cast<i2s_chan_handle_t>(tx_), frames, count * 2 * sizeof(int32_t), &written,
                    portMAX_DELAY);
}
