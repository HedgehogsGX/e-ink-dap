// Debounced push button wired GPIO -> button -> GND (INPUT_PULLUP, pressed = LOW).
// Call poll() every ~10 ms. Short press fires on release; long press fires once while held.
#pragma once
#include <Arduino.h>

enum class Press : uint8_t { None, Short, Long };

class Button {
 public:
  explicit Button(int pin) : pin_(pin) {}
  void begin() { pinMode(pin_, INPUT_PULLUP); }

  Press poll(uint32_t nowMs) {
    bool raw = digitalRead(pin_) == LOW;
    if (raw != raw_) {
      raw_ = raw;
      rawSince_ = nowMs;
    }
    if (raw_ != down_ && nowMs - rawSince_ >= kDebounceMs) {
      down_ = raw_;
      if (down_) {
        downSince_ = nowMs;
        longSent_ = false;
      } else if (!longSent_) {
        return Press::Short;
      }
    }
    if (down_ && !longSent_ && nowMs - downSince_ >= kLongMs) {
      longSent_ = true;
      return Press::Long;
    }
    return Press::None;
  }

 private:
  static constexpr uint32_t kDebounceMs = 25;
  static constexpr uint32_t kLongMs = 600;
  int pin_;
  bool raw_ = false, down_ = false, longSent_ = false;
  uint32_t rawSince_ = 0, downSince_ = 0;
};
