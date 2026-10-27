// UI demo: the home screen, the Reader and Settings on the e-paper, with touch. Books and
// fonts are carried in flash (tools/make_ui_demo.py), settings, reading positions and the
// touch calibration are kept in NVS. Needs only the screen and touch wired
// (docs/phase1_assembly.md step 2, once bringup_epd and bringup_touch pass).
//   uv run tools/make_ui_demo.py && pio run -e ui_demo -t upload
// On first start, tap the three crosses to calibrate touch. The side keys work too once
// they are wired (step 5). Serial: "c" calibrate touch again, "f" full refresh,
// "x" forget settings, reading positions and calibration (then restarts).
#include <Arduino.h>
#include <GxEPD2_BW.h>
#include <Preferences.h>
#include <SPI.h>
#include <Wire.h>

#include "buttons.h"
#include "card_pack.h"
#include "pins.h"
#include "ui_app.h"

extern const uint8_t packStart[] asm("_binary_ui_demo_nosync_card_pack_start");
extern const uint8_t packEnd[] asm("_binary_ui_demo_nosync_card_pack_end");

static GxEPD2_370_GDEY037T03 epd(PIN_EPD_CS, PIN_EPD_DC, PIN_EPD_RST, PIN_EPD_BUSY);
static constexpr uint8_t kTouchAddr = 0x38;
static constexpr int W = Frame::kWidth, H = Frame::kHeight;

class NvsStore : public KeyValueStore {
 public:
  void begin() { prefs_.begin("dap-ui", false); }
  std::string load(const char* key) override { return prefs_.getString(key, "").c_str(); }
  void save(const char* key, const std::string& value) override { prefs_.putString(key, value.c_str()); }
  void clear() { prefs_.clear(); }

 private:
  Preferences prefs_;
};

static CardPack pack;
static NvsStore store;
static UiApp app;
static Frame frame;
static uint8_t turned[Frame::kBytes];  // the frame turned 180°, for "Upside down"
static bool panelOn = false;
static uint32_t lastRefresh = 0;

struct SideKey {
  Key key;
  Button button;
};
static SideKey keys[] = {{Key::Play, Button(PIN_BTN_PLAY)},
                         {Key::VolUp, Button(PIN_BTN_VOL_UP)},
                         {Key::VolDown, Button(PIN_BTN_VOL_DOWN)},
                         {Key::Power, Button(PIN_BTN_POWER)}};

static int readTouchRegs(uint8_t reg, uint8_t* out, size_t len) {
  Wire.beginTransmission(kTouchAddr);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return -1;
  if (Wire.requestFrom(kTouchAddr, (uint8_t)len) != len) return -1;
  for (size_t i = 0; i < len; i++) out[i] = Wire.read();
  return 0;
}

static void show(Refresh r) {
  const uint8_t* image = frame.data();
  if (app.settings().rotate180) {  // 240 is a multiple of 8, so turning is reversing all bits
    for (size_t i = 0; i < Frame::kBytes; i++) {
      uint8_t b = image[i], rev = 0;
      for (int k = 0; k < 8; k++) rev |= ((b >> k) & 1) << (7 - k);
      turned[Frame::kBytes - 1 - i] = rev;
    }
    image = turned;
  }
  bool invert = !app.settings().invert;  // the frame's 1 is black, the panel's 1 is white
  uint32_t t0 = millis();
  if (r == Refresh::Full) {
    epd.writeImageForFullRefresh(image, 0, 0, W, H, invert);
    epd.refresh(false);
  } else {
    epd.writeImage(image, 0, 0, W, H, invert);
    epd.refresh(true);
  }
  epd.writeImageAgain(image, 0, 0, W, H, invert);  // the panel compares the next image with this
  panelOn = true;
  lastRefresh = millis();
  Serial.printf("%-18s %s refresh, %lu ms\n", app.screenName(), r == Refresh::Full ? "full" : "partial",
                (unsigned long)(lastRefresh - t0));
}

static void halt(const char* message) {
  for (;;) {
    Serial.println(message);
    delay(5000);
  }
}

void setup() {
  Serial.begin(115200);
  for (uint32_t start = millis(); !Serial && millis() - start < 3000;) delay(10);
  Serial.println("\n===== UI demo =====");
  if (!pack.open(packStart, packEnd - packStart))
    halt("No books and fonts in this firmware: run  uv run tools/make_ui_demo.py  and upload again.");
  Serial.printf("%u files, %u KB of books and fonts in flash.\n", (unsigned)pack.count(), (unsigned)(pack.size() / 1024));
  store.begin();

  SPI.begin(PIN_EPD_SCK, -1, PIN_EPD_MOSI, PIN_EPD_CS);  // GxEPD2's own SPI.begin() then keeps these pins
  epd.init(0, true, 10, false);

  pinMode(PIN_TOUCH_INT, INPUT_PULLUP);
  Wire.begin(PIN_TOUCH_SDA, PIN_TOUCH_SCL, 400000);
  pinMode(PIN_TOUCH_RST, OUTPUT);
  digitalWrite(PIN_TOUCH_RST, LOW);
  delay(10);
  digitalWrite(PIN_TOUCH_RST, HIGH);
  delay(300);  // controller boot time
  uint8_t vendor;
  if (readTouchRegs(0xA8, &vendor, 1) == 0)
    Serial.printf("Touch controller found (vendor id 0x%02X).\n", vendor);
  else
    Serial.println("Touch controller does not answer at 0x38: run bringup_touch and check wires 10-13.");

  for (SideKey& k : keys) k.button.begin();

  std::string error;
  if (!app.begin(&pack, &store, &error)) {
    Serial.printf("%s. Run tools/make_ui_demo.py and upload again.\n", error.c_str());
    halt("Stopped.");
  }
  if (app.calibrating()) Serial.println("Touch calibration: tap the centre of each cross.");
  Serial.println("Serial: c = calibrate touch, f = full refresh, x = forget settings and positions.");
}

void loop() {
  uint32_t now = millis();

  // Touch: a finger down, then up. The panel is polled every 20 ms.
  static uint32_t lastPoll = 0;
  static bool down = false;
  static int x0, y0, x1, y1;
  if (now - lastPoll >= 20) {
    lastPoll = now;
    uint8_t d[5];  // TD_STATUS, P1_XH, P1_XL, P1_YH, P1_YL
    if (readTouchRegs(0x02, d, sizeof d) == 0) {
      int points = d[0] & 0x0F;
      if (points > 0 && points <= 2) {
        x1 = ((d[1] & 0x0F) << 8) | d[2];
        y1 = ((d[3] & 0x0F) << 8) | d[4];
        if (!down) x0 = x1, y0 = y1;
        down = true;
      } else if (down) {
        down = false;
        int sx, sy;
        app.mapTouch(x0, y0, &sx, &sy);
        Serial.printf("touch at raw %d,%d -> screen %d,%d\n", x0, y0, sx, sy);
        app.touch(x0, y0, x1, y1);
      }
    }
  }

  for (SideKey& k : keys) {
    Press p = k.button.poll(now);
    if (p != Press::None) app.key(k.key, p == Press::Long ? KeyPress::Long : KeyPress::Short);
  }

  if (Serial.available()) {
    char c = Serial.read();
    if (c == 'c') app.calibrate();
    if (c == 'f') app.redraw(Refresh::Full);
    if (c == 'x') {
      store.clear();
      Serial.println("Forgotten. Restarting.");
      delay(100);
      ESP.restart();
    }
  }

  if (app.pending() != Refresh::None) {
    Refresh r = app.render(frame);
    show(r);
  } else if (panelOn && now - lastRefresh > 2000) {
    epd.powerOff();  // don't leave the panel's driving voltages on while nothing changes
    panelOn = false;
  }
  delay(5);
}
