// Bring-up 2: e-paper. GDEY037T03-T02 on the ESP32-FTS02, resistor switch at 0.47 Ω (UC8253).
// Plug or unplug the panel's FPC only with the board unpowered.
// Shows a full-refresh "Hello" screen, then 5 partial updates of a counter, and prints
// how long each refresh took. Ends in hibernate (the panel keeps the image unpowered).
// Send "r" to run it again.
#include <Arduino.h>
#include <Fonts/FreeMonoBold12pt7b.h>
#include <Fonts/FreeSans9pt7b.h>
#include <GxEPD2_BW.h>
#include <SPI.h>

#include "pins.h"

using Panel = GxEPD2_370_GDEY037T03;
GxEPD2_BW<Panel, Panel::HEIGHT> display(Panel(PIN_EPD_CS, PIN_EPD_DC, PIN_EPD_RST, PIN_EPD_BUSY));

static void drawHello() {
  display.setFullWindow();
  display.firstPage();
  do {
    display.fillScreen(GxEPD_WHITE);
    display.setTextColor(GxEPD_BLACK);
    display.setFont(&FreeMonoBold12pt7b);
    display.setCursor(16, 40);
    display.print("Hello, E-ink DAP");
    display.setFont(&FreeSans9pt7b);
    display.setCursor(16, 80);
    display.printf("%u x %u, UC8253, partial update test below", display.width(), display.height());
    display.drawRect(16, 120, 200, 60, GxEPD_BLACK);
  } while (display.nextPage());
}

static void drawCounter(int n) {
  display.setPartialWindow(24, 128, 184, 44);
  display.firstPage();
  do {
    display.fillScreen(GxEPD_WHITE);
    display.setFont(&FreeMonoBold12pt7b);
    display.setCursor(32, 160);
    display.printf("partial %d", n);
  } while (display.nextPage());
}

static void runTest() {
  Serial.println("\n===== Bring-up: e-paper =====");
  uint32_t t0 = millis();
  drawHello();
  Serial.printf("Full refresh: %lu ms (expected ~1500). If it returned in ~0 ms or hung, check BUSY wiring.\n",
                millis() - t0);

  for (int i = 1; i <= 5; i++) {
    t0 = millis();
    drawCounter(i);
    Serial.printf("Partial refresh %d: %lu ms (expected ~350)\n", i, millis() - t0);
    delay(500);
  }
  display.hibernate();
  Serial.println("Done. The screen should show the Hello page with \"partial 5\" in the box.");
}

void setup() {
  Serial.begin(115200);
  for (uint32_t start = millis(); !Serial && millis() - start < 3000;) delay(10);
  SPI.begin(PIN_EPD_SCK, -1, PIN_EPD_MOSI, PIN_EPD_CS);  // GxEPD2's own SPI.begin() then keeps these pins
  display.init(115200, true, 10, false);
  display.setRotation(1);  // landscape, 416 x 240
  runTest();
}

void loop() {
  if (Serial.available() && Serial.read() == 'r') runTest();
  delay(10);
}
