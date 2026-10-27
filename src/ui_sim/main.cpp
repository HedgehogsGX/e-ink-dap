// The UI's screens drawn on the Mac, no board needed: runs lib/ui with the demo's books
// and fonts (ui_demo.nosync/card.pack, from tools/make_ui_demo.py) and saves screens as
// PNGs in ui_sim.nosync/, at 2x so the pixels are easy to see.
//   pio run -e ui_sim && .pio.nosync/build/ui_sim/program [step ...]
// Steps: "tap:X,Y" (screen pixels), "swipe:left" / "swipe:right", "key:play|volup|voldown|
// power[:long]", "shot:NAME" (saves NAME.png). Without steps it takes a tour of every screen.
#include <cstdio>
#include <fstream>
#include <iterator>
#include <map>
#include <string>
#include <vector>

#include "card_pack.h"
#include "dapfile.h"
#include "frame.h"
#include "ui_app.h"

namespace {

class MemoryStore : public KeyValueStore {
 public:
  std::string load(const char* key) override { return values[key]; }
  void save(const char* key, const std::string& value) override { values[key] = value; }
  std::map<std::string, std::string> values;
};

void be32(std::vector<uint8_t>& out, uint32_t v) {
  for (int s = 24; s >= 0; s -= 8) out.push_back((uint8_t)(v >> s));
}

void chunk(std::vector<uint8_t>& png, const char* type, const std::vector<uint8_t>& data) {
  be32(png, (uint32_t)data.size());
  size_t at = png.size();
  png.insert(png.end(), type, type + 4);
  png.insert(png.end(), data.begin(), data.end());
  be32(png, dap::crc32(png.data() + at, png.size() - at));
}

// A 1-bit grayscale PNG (stored, not compressed: no zlib needed), scaled up `scale` times.
bool writePng(const std::string& path, const Frame& f, int scale) {
  int w = Frame::kWidth * scale, h = Frame::kHeight * scale, stride = (w + 7) / 8;
  std::vector<uint8_t> raw;
  for (int y = 0; y < h; y++) {
    raw.push_back(0);  // filter: none
    std::vector<uint8_t> row(stride, 0xFF);  // PNG's 1 is white
    for (int x = 0; x < w; x++)
      if (f.black(x / scale, y / scale)) row[x / 8] &= ~(0x80 >> (x & 7));
    raw.insert(raw.end(), row.begin(), row.end());
  }
  std::vector<uint8_t> z = {0x78, 0x01};
  uint32_t a = 1, b = 0;
  for (uint8_t c : raw) a = (a + c) % 65521, b = (b + a) % 65521;
  for (size_t at = 0; at < raw.size(); at += 65535) {
    size_t n = std::min<size_t>(65535, raw.size() - at);
    z.push_back(at + n == raw.size());
    z.push_back((uint8_t)n), z.push_back((uint8_t)(n >> 8));
    z.push_back((uint8_t)~n), z.push_back((uint8_t)(~n >> 8));
    z.insert(z.end(), raw.begin() + at, raw.begin() + at + n);
  }
  be32(z, b << 16 | a);
  std::vector<uint8_t> png = {0x89, 'P', 'N', 'G', '\r', '\n', 0x1A, '\n'}, ihdr;
  be32(ihdr, w);
  be32(ihdr, h);
  ihdr.insert(ihdr.end(), {1, 0, 0, 0, 0});  // bit depth 1, grayscale
  chunk(png, "IHDR", ihdr);
  chunk(png, "IDAT", z);
  chunk(png, "IEND", {});
  std::ofstream out(path, std::ios::binary);
  out.write(reinterpret_cast<const char*>(png.data()), png.size());
  return (bool)out;
}

const char* const kTour[] = {
    "shot:01_home",
    "tap:120,200", "shot:02_shelf",
    "tap:120,367", "shot:03_page",  // the last row: 雾港来信
    "tap:200,200", "shot:04_page_next",
    "tap:120,200", "shot:05_menu",
    "tap:228,34", "tap:60,350", "shot:06_contents",
    "tap:180,30", "shot:07_bookmarks",
    "tap:120,63", "tap:120,200", "tap:110,390", "shot:08_menu_bigger",
    "tap:180,390", "shot:09_settings_reader",
    "tap:222,141", "shot:10_margins_large",
    "tap:40,30", "shot:11_settings",
    "tap:120,186", "shot:12_settings_display",
    "tap:40,30", "tap:120,294", "shot:13_about",
    "tap:40,10", "shot:14_home",
    "tap:120,200", "tap:40,34", "shot:15_shelf_recent",
    "tap:200,34", "shot:16_shelf_author",
    "tap:120,34", "tap:120,329", "swipe:left", "swipe:left", "shot:17_long_book",
    "tap:120,200", "tap:40,10", "tap:120,80", "shot:18_music",  // a page has no status bar: menu first
    "tap:120,320", "tap:120,300", "tap:120,190", "shot:19_calibration",  // Settings reopens on About
    // A touch panel turned a quarter and scaled (raw x = 415 - y, raw y = 1.5 x): after
    // calibrating with it, raw taps must land where they should: the Reader card (which
    // reopens on the menu), then "< Shelf" at (40, 34).
    "rawtap:391,36", "rawtap:391,322", "rawtap:24,36", "shot:20_after_calibration",
    "tap:40,10", "rawtap:215,180", "rawtap:381,60", "shot:21_shelf_via_raw",
};

}  // namespace

int main(int argc, char** argv) {
  std::ifstream in("ui_demo.nosync/card.pack", std::ios::binary);
  std::vector<uint8_t> data((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
  CardPack pack;
  if (!pack.open(data.data(), data.size())) {
    fprintf(stderr, "no ui_demo.nosync/card.pack: run uv run tools/make_ui_demo.py first\n");
    return 1;
  }
  MemoryStore store;
  store.values["touch"] = "1 0 0 0 1 0";  // the sim's taps are screen pixels
  UiApp app;
  std::string error;
  if (!app.begin(&pack, &store, &error)) {
    fprintf(stderr, "%s\n", error.c_str());
    return 1;
  }
  std::vector<std::string> steps(argv + 1, argv + argc);
  if (steps.empty()) steps.assign(std::begin(kTour), std::end(kTour));
  system("mkdir -p ui_sim.nosync");
  Frame frame;
  auto render = [&] {
    if (app.pending() == Refresh::None) return;
    Refresh r = app.render(frame);
    printf("  %-18s %s refresh\n", app.screenName(), r == Refresh::Full ? "full" : "partial");
  };
  render();
  for (const std::string& step : steps) {
    int x, y;
    char word[16] = {};
    printf("%s\n", step.c_str());
    if (sscanf(step.c_str(), "tap:%d,%d", &x, &y) == 2) {
      int rx, ry;  // screen pixels -> raw, through the current calibration's inverse
      for (rx = 0; rx < 1000; rx++) {
        int sx, sy;
        bool found = false;
        for (ry = 0; ry < 1000 && !found; ry++) app.mapTouch(rx, ry, &sx, &sy), found = sx == x && sy == y;
        if (found) {
          ry--;
          break;
        }
      }
      app.touch(rx, ry, rx, ry);
    } else if (sscanf(step.c_str(), "rawtap:%d,%d", &x, &y) == 2) {
      app.touch(x, y, x, y);
    } else if (step == "swipe:left" || step == "swipe:right") {
      bool left = step == "swipe:left";
      app.touch(left ? 180 : 60, 200, left ? 60 : 180, 205);
    } else if (sscanf(step.c_str(), "key:%15[a-z]", word) == 1) {
      std::string k = word;
      Key key = k == "play" ? Key::Play : k == "volup" ? Key::VolUp : k == "voldown" ? Key::VolDown : Key::Power;
      app.key(key, step.size() > 5 && step.substr(step.size() - 5) == ":long" ? KeyPress::Long : KeyPress::Short);
    } else if (step.rfind("shot:", 0) == 0) {
      std::string path = "ui_sim.nosync/" + step.substr(5) + ".png";
      if (!writePng(path, frame, 2)) fprintf(stderr, "cannot write %s\n", path.c_str());
      continue;
    } else {
      fprintf(stderr, "unknown step %s\n", step.c_str());
      return 1;
    }
    render();
  }
  printf("screens in ui_sim.nosync/\n");
  return 0;
}
