// Bring-up 5b: FT6336U touch controller on the GDEY037T03-T02, via the FTS02 touch connector.
// Scans the I2C bus and reads the controller's IDs (retrying every 3 s until it answers),
// then prints every touch in raw panel coordinates.
#include <Arduino.h>
#include <Wire.h>

#include "pins.h"

static constexpr uint8_t kAddr = 0x38;

static int readReg(uint8_t reg, uint8_t* out, size_t len) {
  Wire.beginTransmission(kAddr);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return -1;
  if (Wire.requestFrom(kAddr, (uint8_t)len) != len) return -1;
  for (size_t i = 0; i < len; i++) out[i] = Wire.read();
  return 0;
}

static bool initTouch() {
  Serial.println("\n===== Bring-up: touch (FT6336U) =====");
  if (PIN_TOUCH_RST >= 0) {
    pinMode(PIN_TOUCH_RST, OUTPUT);
    digitalWrite(PIN_TOUCH_RST, LOW);
    delay(10);
    digitalWrite(PIN_TOUCH_RST, HIGH);
    delay(300);  // controller boot time
  } else {
    Serial.println("DEVKITC_REV not set in pins.h, so touch RST is not driven (relying on the adapter's pull-up).");
  }
  Serial.print("I2C devices:");
  int found = 0;
  for (uint8_t a = 1; a < 127; a++) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() == 0) {
      Serial.printf(" 0x%02X", a);
      found++;
    }
  }
  Serial.println(found ? "" : " none. Check SDA/SCL wiring, 3.3 V and GND to the touch connector.");

  uint8_t vendor, chip, fw;
  if (!found || readReg(0xA8, &vendor, 1) || readReg(0xA3, &chip, 1) || readReg(0xA6, &fw, 1)) {
    Serial.println("No answer at 0x38, retrying in 3 s.");
    return false;
  }
  Serial.printf("FocalTech vendor id 0x%02X (expect 0x11), chip id 0x%02X, firmware 0x%02X\n", vendor, chip, fw);
  Serial.println("Touch the screen...");
  return true;
}

void setup() {
  Serial.begin(115200);
  for (uint32_t start = millis(); !Serial && millis() - start < 3000;) delay(10);
  pinMode(PIN_TOUCH_INT, INPUT_PULLUP);
  Wire.begin(PIN_TOUCH_SDA, PIN_TOUCH_SCL, 400000);
}

void loop() {
  static bool ready = false;
  static uint32_t lastTry = 0;
  if (!ready) {
    if (lastTry == 0 || millis() - lastTry >= 3000) {
      ready = initTouch();
      lastTry = millis();
    }
    delay(10);
    return;
  }
  static bool wasDown = false;
  uint8_t d[5];  // TD_STATUS, P1_XH, P1_XL, P1_YH, P1_YL
  if (readReg(0x02, d, sizeof(d)) == 0) {
    bool down = (d[0] & 0x0F) > 0;
    if (down) {
      int x = ((d[1] & 0x0F) << 8) | d[2];
      int y = ((d[3] & 0x0F) << 8) | d[4];
      Serial.printf("%s x=%3d y=%3d  INT=%d\n", wasDown ? "move " : "DOWN ", x, y, digitalRead(PIN_TOUCH_INT));
    } else if (wasDown) {
      Serial.println("UP");
    }
    wasDown = down;
  }
  delay(30);
}
