// I2S output to the DAC: MCLK = 256 fs, 32-bit stereo slots (BCK = 64 fs), Philips format.
// Owned by the audio task; only underruns() is safe to read from other tasks.
#pragma once
#include <atomic>
#include <cstddef>
#include <cstdint>

class AudioOut {
 public:
  void begin(uint32_t sampleRate);
  void setRate(uint32_t sampleRate);
  uint32_t rate() const { return rate_; }
  // Blocks until all frames (interleaved L/R, 32-bit) are queued for DMA.
  void write(const int32_t* frames, size_t count);
  // Times the DMA ran dry and sent silence because write() was late.
  uint32_t underruns() const { return underruns_.load(); }

 private:
  void* tx_ = nullptr;
  uint32_t rate_ = 0;
  std::atomic<uint32_t> underruns_{0};
  friend struct AudioOutCallbacks;
};
