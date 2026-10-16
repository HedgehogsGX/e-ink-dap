// Bring-up 5a: buttons. Each button: one leg to its GPIO, the other to GND.
// Prints every short and long press, so you can check each button reaches the right pin.
#include <Arduino.h>

#include "buttons.h"
#include "pins.h"

struct NamedButton {
  const char* name;
  Button button;
};

static NamedButton buttons[] = {
    {"BOOT (GPIO0)", Button(0)},
    {"Play", Button(PIN_BTN_PLAY)},
    {"Vol+", Button(PIN_BTN_VOL_UP)},
    {"Vol-", Button(PIN_BTN_VOL_DOWN)},
    {"Lock", Button(PIN_BTN_LOCK)},
};

void setup() {
  Serial.begin(115200);
  for (uint32_t start = millis(); !Serial && millis() - start < 3000;) delay(10);
  Serial.println("\n===== Bring-up: buttons (press each one, short and long) =====");
  for (NamedButton& b : buttons) b.button.begin();
}

void loop() {
  uint32_t now = millis();
  for (NamedButton& b : buttons) {
    Press p = b.button.poll(now);
    if (p != Press::None) Serial.printf("%-13s %s press\n", b.name, p == Press::Short ? "short" : "LONG");
  }
  delay(10);
}
