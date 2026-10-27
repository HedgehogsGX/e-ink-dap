#include "ui_app.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <initializer_list>

#include "dapfile.h"
#include "g4image.h"
#include "text_layout.h"

namespace {

constexpr int W = UiApp::W, H = UiApp::H;
constexpr int kTargets[3][2] = {{24, 24}, {W - 25, 24}, {24, H - 25}};  // touch calibration
const char* const kSectionKeys[] = {"music", "reader", "display", "system", "about"};
const char* const kSectionNames[] = {"Music", "Reader", "Display", "System", "About"};
constexpr int kValueW = 66;  // the value between a stepper's - and +

// ---- Icons and controls, drawn as in tools/render_previews.py ----

void iconHome(Frame& f, int x, int y) {
  float roof[] = {x + 0.f, y + 5.f, x + 6.f, y + 0.f, x + 12.f, y + 5.f};
  f.fillPolygon(roof, 3);
  f.fill(x + 2, y + 5, x + 10, y + 11);
  f.fill(x + 5, y + 7, x + 7, y + 11, false);
}

void iconLock(Frame& f, int x, int y) {
  f.fill(x + 2, y, x + 7, y + 1);
  f.fill(x + 1, y + 1, x + 2, y + 6);
  f.fill(x + 7, y + 1, x + 8, y + 6);
  f.fill(x, y + 6, x + 9, y + 13);
}

void outline(Frame& f, const int* xy, int n, int width) {
  for (int i = 0; i < n; i++)
    f.line(xy[2 * i], xy[2 * i + 1], xy[2 * ((i + 1) % n)], xy[2 * ((i + 1) % n) + 1], width);
}

void iconAppMusic(Frame& f, int x, int y) {  // 32 x 32: two beamed eighth notes
  f.fillEllipse(x + 1, y + 21, x + 12, y + 29);
  f.fillEllipse(x + 18, y + 17, x + 29, y + 25);
  f.fill(x + 10, y + 7, x + 12, y + 25);
  f.fill(x + 27, y + 3, x + 29, y + 21);
  float beam[] = {x + 10.f, y + 7.f, x + 29.f, y + 2.f, x + 29.f, y + 8.f, x + 10.f, y + 13.f};
  f.fillPolygon(beam, 4);
}

void iconAppBook(Frame& f, int x, int y) {  // 32 x 32: an open book
  int left[] = {x + 1, y + 5, x + 15, y + 9, x + 15, y + 29, x + 1, y + 25};
  int right[] = {x + 17, y + 9, x + 31, y + 5, x + 31, y + 25, x + 17, y + 29};
  outline(f, left, 4, 2);
  outline(f, right, 4, 2);
  for (int i = 0; i < 3; i++) {
    f.line(x + 5, y + 12 + 5 * i, x + 12, y + 14 + 5 * i);
    f.line(x + 20, y + 14 + 5 * i, x + 27, y + 12 + 5 * i);
  }
}

void iconAppGear(Frame& f, int x, int y) {  // 32 x 32
  float pts[64], cx = x + 16.f, cy = y + 16.f;
  for (int i = 0; i < 32; i++) {
    float a = 2 * 3.14159265f * (i + 0.5f) / 32, r = i % 4 < 2 ? 15.f : 11.f;
    pts[2 * i] = cx + r * std::cos(a);
    pts[2 * i + 1] = cy + r * std::sin(a);
  }
  f.fillPolygon(pts, 32);
  f.fillEllipse(x + 11, y + 11, x + 21, y + 21, false);
}

void iconBookmark(Frame& f, int x, int y, bool filled) {
  int pts[] = {x, y, x + 9, y, x + 9, y + 13, x + 5, y + 9, x + 4, y + 9, x, y + 13};
  if (filled) {
    float fp[12];
    for (int i = 0; i < 12; i++) fp[i] = (float)pts[i];
    f.fillPolygon(fp, 6);
  } else {
    outline(f, pts, 6, 1);
  }
}

void iconList(Frame& f, int x, int y) {
  for (int i = 0; i < 3; i++) {
    f.fill(x, y + 1 + 4 * i, x + 1, y + 2 + 4 * i);
    f.fill(x + 4, y + 1 + 4 * i, x + 12, y + 2 + 4 * i);
  }
}

void chevron(Frame& f, int x, int y) {
  f.line(x, y, x + 4, y + 4, 2);
  f.line(x + 4, y + 4, x, y + 8, 2);
}

void backArrow(Frame& f, int x, int y) {
  f.line(x + 4, y, x, y + 4, 2);
  f.line(x, y + 4, x + 4, y + 8, 2);
}

void progress(Frame& f, int x, int y, int w, int h, double frac) {
  f.rect(x, y, x + w - 1, y + h - 1);
  f.fill(x, y, x + (int)std::lround((w - 1) * std::clamp(frac, 0.0, 1.0)), y + h - 1);
}

int metaWidth(const BitmapFont& font, std::initializer_list<std::string_view> parts) {
  int w = 0, n = 0;
  for (std::string_view p : parts)
    if (!p.empty()) w += Frame::width(font, p) + (n++ ? 12 : 0);
  return w;
}

// Parts separated by small drawn dots (the fonts' middle dot is full width in CJK faces).
void metaLine(Frame& f, const BitmapFont& font, int x, int y, std::initializer_list<std::string_view> parts,
              int width, bool black = true) {
  int end = x + width, dot = y + font.ascent() - font.size() / 3 - 1;
  bool first = true;
  for (std::string_view p : parts) {
    if (p.empty()) continue;
    if (!first) {
      f.fill(x + 5, dot, x + 6, dot + 1, black);
      x += 12;
    }
    first = false;
    x = f.text(font, x, y, Frame::fit(font, p, end - x), black);
    if (x >= end - 10) break;
  }
}

void metaCentered(Frame& f, const BitmapFont& font, int y, std::initializer_list<std::string_view> parts) {
  int w = std::min(metaWidth(font, parts), W - 24);
  metaLine(f, font, (W - w) / 2, y, parts, w);
}

int tabs(Frame& f, const BitmapFont& font, const char* const* names, int n, int selected, int y = 21, int h = 26) {
  for (int i = 0; i < n; i++) {
    int x0 = i * W / n, x1 = (i + 1) * W / n;
    if (i == selected)
      f.fill(x0, y, x1 - 1, y + h - 1);
    else if (i)
      f.vline(x0, y, y + h - 1);
    f.centered(font, x0, x1, y + 4, names[i], i != selected);
  }
  f.hline(0, W - 1, y + h);
  return y + h + 1;
}

void button(Frame& f, int x0, int y0, int x1, int y1, std::string_view label, const BitmapFont& font,
            void (*icon)(Frame&, int, int) = nullptr) {
  f.roundRect(x0, y0, x1, y1, 5);
  int tw = Frame::width(font, label) + (icon ? 18 : 0), tx = (x0 + x1 - tw) / 2;
  if (icon) {
    icon(f, tx, (y0 + y1) / 2 - 6);
    tx += 18;
  }
  f.text(font, tx, (y0 + y1) / 2 - font.size() / 2 - 1, label);
}

int badge(Frame& f, const BitmapFont& font, int x, int y, std::string_view label) {
  int bw = Frame::width(font, label) + 8;
  f.rect(x, y, x + bw, y + 14);
  f.text(font, x + 4, y + 1, label);
  return bw;
}

// A choice of a few values, right-aligned at `right`: where each option starts and how
// wide it is, narrower padding when they would take more than 150 px.
int segments(const BitmapFont& font, const std::vector<std::string>& options, int right, int* starts, int* widths) {
  int total = 0;
  for (int pad = 16; pad >= 8; pad -= 4) {
    total = 0;
    for (size_t i = 0; i < options.size(); i++) total += widths[i] = Frame::width(font, options[i]) + pad;
    if (total <= 150) break;
  }
  int x = right - total;
  for (size_t i = 0; i < options.size(); i++) starts[i] = x, x += widths[i];
  return right - total;
}

void segmented(Frame& f, const BitmapFont& font, int right, int y, const std::vector<std::string>& options,
               int selected, int h = 24) {
  int starts[4], widths[4], n = (int)options.size();
  f.roundRect(segments(font, options, right, starts, widths), y, right, y + h, 5);
  for (int i = 0; i < n; i++) {
    int x = starts[i], w = widths[i];
    if (i == selected)
      f.fill(x + (i == 0), y + 1, x + w - (i == n - 1), y + h - 1);
    else if (i && i != selected + 1)
      f.vline(x, y, y + h);
    f.text(font, x + (w - Frame::width(font, options[i])) / 2, y + 5, options[i], i != selected);
  }
}

void stepper(Frame& f, const BitmapFont& font, int right, int y, std::string_view value, int h = 24) {
  int x0 = right - 26;
  f.roundRect(x0, y, right, y + h, 5);
  f.fill(x0 + 8, y + 11, x0 + 18, y + 12);  // +
  f.fill(x0 + 12, y + 7, x0 + 13, y + 17);
  f.centered(font, x0 - kValueW, x0, y + 4, value);
  int m0 = x0 - kValueW - 26;
  f.roundRect(m0, y, x0 - kValueW, y + h, 5);
  f.fill(m0 + 8, y + 11, m0 + 18, y + 12);  // -
}

// How a setting is shown: a stepper with its value, or a choice of options.
struct Control {
  std::string label;
  std::vector<std::string> options;  // empty: a stepper
  int selected = 0;
  std::string value;
};

bool onIsFirst(const SettingInfo& s) { return strcmp(s.key, "volume_keys_turn_pages") != 0; }

Control controlFor(const SettingInfo& s, int v) {
  Control c;
  c.label = s.label;
  if (!onIsFirst(s)) {  // "Volume keys: Volume | Pages", as in the mockup
    c.label = "Volume keys";
    c.options = {"Volume", "Pages"};
    c.selected = v ? 1 : 0;
  } else if (s.kind == SettingInfo::Toggle) {
    c.options = {"On", "Off"};
    c.selected = v ? 0 : 1;
  } else if (s.kind == SettingInfo::Choice) {
    for (int i = 0; i < s.count; i++) c.options.push_back(s.labels[i]);
    c.selected = v;
  } else {
    c.value = formatSetting(s, v);
  }
  if (strcmp(s.key, "full_refresh_every") == 0) c.label = "Full refresh";
  return c;
}

std::string percent(uint64_t part, uint64_t whole) {
  return std::to_string(whole ? std::min<uint64_t>(100, part * 100 / whole) : 0) + "%";
}

std::string monthDay() {  // "Oct 26" from __DATE__ ("Oct 26 2026")
  std::string d = __DATE__;
  d = d.substr(0, 6);
  if (d.size() == 6 && d[4] == ' ') d.erase(4, 1);
  return d;
}

double det3(const double m[3][3]) {
  return m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1]) - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0]) +
         m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]);
}

}  // namespace

// ---- Setup and input ----

bool UiApp::begin(const CardFiles* card, KeyValueStore* store, std::string* error) {
  card_ = card;
  store_ = store;
  auto openFont = [&](BitmapFont& font, const std::string& name) {
    std::string path = "/.dap/fonts/" + name;
    std::string_view d = card->file(path);
    if (font.open(reinterpret_cast<const uint8_t*>(d.data()), d.size()) == BitmapFont::Error::None) return true;
    if (error) *error = "missing or damaged " + path;
    return false;
  };
  struct {
    BitmapFont* font;
    const char* name;
  } ui[] = {{&ui_.s12, "ui-12.dfn"},   {&ui_.s13, "ui-13.dfn"},   {&ui_.s14, "ui-14.dfn"},   {&ui_.s15, "ui-15.dfn"},
            {&ui_.b13, "ui-13b.dfn"},  {&ui_.b14, "ui-14b.dfn"},  {&ui_.b15, "ui-15b.dfn"},  {&ui_.b17, "ui-17b.dfn"},
            {&ui_.b18, "ui-18b.dfn"},  {&ui_.b20, "ui-20b.dfn"}};
  for (auto& u : ui)
    if (!openFont(*u.font, u.name)) return false;
  for (int i = 0; i < 8; i++)
    if (!openFont(reader_[i], "reader-" + std::to_string(Settings::kFontSizes[i]) + ".dfn")) return false;
  std::string_view idx = card->file("/.dap/books.idx");
  if (shelf_.open(reinterpret_cast<const uint8_t*>(idx.data()), idx.size()) != Shelf::Error::None) {
    if (error) *error = "missing or damaged /.dap/books.idx";
    return false;
  }
  settings_.parse(store->load("settings"));
  reading_.parse(store->load("reading"));
  float c[6];
  if (sscanf(store->load("touch").c_str(), "%f %f %f %f %f %f", &c[0], &c[1], &c[2], &c[3], &c[4], &c[5]) == 6) {
    std::copy(c, c + 6, cal_);
    calibrated_ = true;
  }
  if (!calibrated_) calibrate();
  pending_ = Refresh::Full;
  return true;
}

void UiApp::mapTouch(int rx, int ry, int* x, int* y) const {
  int px = (int)std::lround(cal_[0] * rx + cal_[1] * ry + cal_[2]);
  int py = (int)std::lround(cal_[3] * rx + cal_[4] * ry + cal_[5]);
  if (settings_.rotate180) px = W - 1 - px, py = H - 1 - py;
  *x = px;
  *y = py;
}

void UiApp::touch(int rx0, int ry0, int rx1, int ry1) {
  if (calStep_ >= 0) return calibrationTap(rx0, ry0);
  if (locked_) return;
  int x0, y0, x1, y1;
  mapTouch(rx0, ry0, &x0, &y0);
  mapTouch(rx1, ry1, &x1, &y1);
  int dx = x1 - x0, dy = y1 - y0;
  if (std::abs(dx) >= 40 && std::abs(dx) > 2 * std::abs(dy)) return swipe(dx < 0);
  if (std::abs(dx) > 24 || std::abs(dy) > 24) return;  // a drag, not a tap
  tap(x0, y0);
}

void UiApp::key(Key k, KeyPress press) {
  if (calStep_ >= 0) return;
  InputContext ctx{nav_.current(), locked_, settings_.volumeKeysTurnPages != 0};
  switch (routeKey(k, press, ctx)) {
    case Command::NextPage: turnPage(true); break;
    case Command::PrevPage: turnPage(false); break;
    case Command::Lock: locked_ = true, dirty(); break;
    case Command::Unlock: locked_ = false, dirty(); break;
    default: break;  // music and power off: not in this demo
  }
}

void UiApp::calibrate() {
  calStep_ = 0;
  calRetry_ = false;
  dirty(Refresh::Full);
}

void UiApp::calibrationTap(int rx, int ry) {
  calRaw_[calStep_][0] = rx;
  calRaw_[calStep_][1] = ry;
  if (++calStep_ < 3) return dirty();
  // Solve panel = c0 rx + c1 ry + c2 (and the same for y) through the three targets, which
  // were drawn at panel coordinates turned with the "upside down" setting.
  double m[3][3], px[3], py[3];
  for (int i = 0; i < 3; i++) {
    m[i][0] = calRaw_[i][0], m[i][1] = calRaw_[i][1], m[i][2] = 1;
    px[i] = settings_.rotate180 ? W - 1 - kTargets[i][0] : kTargets[i][0];
    py[i] = settings_.rotate180 ? H - 1 - kTargets[i][1] : kTargets[i][1];
  }
  double det = det3(m), c[6];
  for (int k = 0; k < 3; k++) {
    double a[3][3], b[3][3];
    for (int i = 0; i < 3; i++)
      for (int j = 0; j < 3; j++) a[i][j] = b[i][j] = j == k ? 0 : m[i][j];
    for (int i = 0; i < 3; i++) a[i][k] = px[i], b[i][k] = py[i];
    c[k] = std::fabs(det) > 1e-9 ? det3(a) / det : 0;
    c[3 + k] = std::fabs(det) > 1e-9 ? det3(b) / det : 0;
  }
  // Taps that nearly line up (|det| is twice the triangle's area), or a wild scale, mean a
  // missed target: start again.
  double sx = std::hypot(c[0], c[1]), sy = std::hypot(c[3], c[4]);
  if (std::fabs(det) < 2000 || sx < 0.2 || sx > 5 || sy < 0.2 || sy > 5) {
    calStep_ = 0;
    calRetry_ = true;
    return dirty();
  }
  for (int i = 0; i < 6; i++) cal_[i] = (float)c[i];
  calibrated_ = true;
  calStep_ = -1;
  char text[96];
  snprintf(text, sizeof text, "%.6f %.6f %.3f %.6f %.6f %.3f", c[0], c[1], c[2], c[3], c[4], c[5]);
  store_->save("touch", text);
  dirty(Refresh::Full);
}

void UiApp::tap(int x, int y) {
  InputContext ctx{nav_.current(), locked_, settings_.volumeKeysTurnPages != 0};
  switch (routeTap(x, y, ctx, W, kStatusTap)) {
    case Command::Home: nav_.goHome(); return dirty();
    case Command::PrevPage: return turnPage(false);
    case Command::NextPage: return turnPage(true);
    case Command::Menu: nav_.push(Screen::ReaderMenu); return dirty();
    default: break;
  }
  switch (nav_.current()) {
    case Screen::Home: return tapHome(x, y);
    case Screen::Library:
    case Screen::NowPlaying:
    case Screen::Lyrics:
      if (y >= 300 && y <= 340) nav_.goHome(), dirty();
      return;
    case Screen::Shelf: return tapShelf(x, y);
    case Screen::ReaderMenu: return tapMenu(x, y);
    case Screen::Contents: return tapContents(x, y);
    case Screen::SettingsList: return tapSettingsList(x, y);
    case Screen::SettingsPage: return tapSettingsPage(x, y);
    default: return;
  }
}

void UiApp::swipe(bool forward) {
  int dir = forward ? 1 : -1;
  switch (nav_.current()) {
    case Screen::Page: return turnPage(forward);
    case Screen::Shelf: shelfPage_[shelfTab_] = std::max(0, shelfPage_[shelfTab_] + dir); return dirty();
    case Screen::Contents: contentsPage_ = std::max(0, contentsPageNow() + dir); return dirty();
    default: return;
  }
}

// ---- Rendering ----

Refresh UiApp::render(Frame& f) {
  Refresh r = pending_ == Refresh::None ? Refresh::Partial : pending_;
  pending_ = Refresh::None;
  if (styleDirty_ && session_.isOpen()) session_.setStyle(makeStyle(book_.mostlyCjk()));
  styleDirty_ = false;
  f.clear();
  if (calStep_ >= 0) {
    drawCalibration(f);
  } else {
    switch (nav_.current()) {
      case Screen::Home: drawHome(f); break;
      case Screen::Library:
      case Screen::NowPlaying:
      case Screen::Lyrics: drawMusic(f); break;
      case Screen::Shelf: drawShelf(f); break;
      case Screen::Page: drawPage(f); break;
      case Screen::ReaderMenu: drawMenu(f); break;
      case Screen::Contents: drawContents(f); break;
      case Screen::SettingsList: drawSettingsList(f); break;
      case Screen::SettingsPage: drawSettingsPage(f); break;
    }
  }
  if (r == Refresh::Partial && partialsSinceFull_ >= settings_.fullRefreshEvery) r = Refresh::Full;
  if (r == Refresh::Full)
    partialsSinceFull_ = 0, fulls_++;
  else
    partialsSinceFull_++, partials_++;
  return r;
}

const char* UiApp::screenName() const {
  if (calStep_ >= 0) return "touch calibration";
  switch (nav_.current()) {
    case Screen::Home: return "home";
    case Screen::Library:
    case Screen::NowPlaying:
    case Screen::Lyrics: return "music";
    case Screen::Shelf: return "shelf";
    case Screen::Page: return "book page";
    case Screen::ReaderMenu: return "reader menu";
    case Screen::Contents: return "contents";
    case Screen::SettingsList: return "settings";
    case Screen::SettingsPage: return "settings page";
  }
  return "?";
}

void UiApp::statusBar(Frame& f, bool home) {
  int x0 = 6;
  if (home) {
    iconHome(f, 5, 4);
    f.vline(23, 4, 15);
    x0 = 29;
  }
  f.text(ui_.s12, x0, 3, "UI demo");
  if (locked_) iconLock(f, W - 16, 3);
  f.hline(0, W - 1, kStatusH);
}

void UiApp::drawCalibration(Frame& f) {
  int tx = kTargets[calStep_][0], ty = kTargets[calStep_][1];
  f.fill(tx - 14, ty - 1, tx + 14, ty + 1);
  f.fill(tx - 1, ty - 14, tx + 1, ty + 14);
  f.roundRect(tx - 8, ty - 8, tx + 8, ty + 8, 8);
  f.centered(ui_.b18, 0, W, 150, "Touch calibration");
  f.centered(ui_.s15, 0, W, 186, "Tap the centre of the cross");
  char step[24];
  snprintf(step, sizeof step, "%d of 3", calStep_ + 1);
  f.centered(ui_.s14, 0, W, 208, step);
  if (calRetry_) f.centered(ui_.b14, 0, W, 240, "Missed one, once more please");
  f.centered(ui_.s12, 0, W, 300, "Redo any time: Settings > About");
}

void UiApp::drawHome(Frame& f) {
  statusBar(f, false);
  const int x = 60, tw = W - 18 - x;

  int y = 30;  // Music: nothing to play until the SD card and the DAC are wired
  f.roundRect(8, y, W - 9, y + 116, 7);
  iconAppMusic(f, 17, y + 12);
  f.text(ui_.b18, x, y + 10, "Music");
  f.text(ui_.b14, x, y + 40, "Nothing playing");
  f.text(ui_.s12, x, y + 62, Frame::fit(ui_.s12, "Needs the SD card and", tw));
  f.text(ui_.s12, x, y + 78, Frame::fit(ui_.s12, "the DAC: steps 3 and 4", tw));

  y = 154;  // Reader: the book you are in
  f.roundRect(8, y, W - 9, y + 116, 7);
  iconAppBook(f, 17, y + 12);
  f.text(ui_.b18, x, y + 10, "Reader");
  uint32_t index = Shelf::kNone;
  for (uint32_t id : reading_.recent())
    if ((index = shelf_.find(id)) != Shelf::kNone) break;
  if (index != Shelf::kNone) {
    Shelf::Entry e = shelf_.book(index);
    uint32_t pos = reading_.position(e.id);
    std::string chapter;
    Book b;
    if (loadBook(e.id, &b) && b.tocAt(pos) >= 0) chapter = b.toc(b.tocAt(pos)).title;
    f.text(ui_.b14, x, y + 40, Frame::fit(ui_.b14, e.title, tw));
    metaLine(f, ui_.s12, x, y + 60, {e.author, chapter}, tw);
    progress(f, x, y + 84, tw, 5, e.textSize ? (double)pos / e.textSize : 0);
    f.text(ui_.s12, x, y + 93, bookProgress(e));
  } else {
    f.text(ui_.b14, x, y + 40, "No book open yet");
    f.text(ui_.s12, x, y + 62, "Tap to choose one");
  }

  y = 278;
  f.roundRect(8, y, W - 9, y + 70, 7);
  iconAppGear(f, 17, y + 19);
  f.text(ui_.b18, x, y + 9, "Settings");
  metaLine(f, ui_.s12, x, y + 36, {"Music", "Reader"}, tw);
  metaLine(f, ui_.s12, x, y + 52, {"Display", "System"}, tw);

  f.dottedHline(16, W - 16, 364);
  std::string books = std::to_string(shelf_.count()) + (shelf_.count() == 1 ? " book" : " books");
  metaCentered(f, ui_.s12, 374, {books, "no music yet"});
  f.centered(ui_.s12, 0, W, 392, "UI demo: screen and touch only");
}

void UiApp::tapHome(int, int y) {
  if (y >= 30 && y <= 146) nav_.openApp(App::Music);
  else if (y >= 154 && y <= 270) nav_.openApp(App::Reader);
  else if (y >= 278 && y <= 348) nav_.openApp(App::Settings);
  else return;
  dirty();
}

void UiApp::drawMusic(Frame& f) {
  statusBar(f, true);
  f.text(ui_.b17, 10, 26, "Music");
  f.hline(0, W - 1, 50);
  int y = 66;
  for (const char* para : {"Music needs the microSD card and the DAC board (bring-up steps 3 and 4).",
                           "This demo has the screen and touch only: try the Reader and Settings."}) {
    std::string lines[6];
    int n = wrapText(ui_.s14, para, W - 24, 6, lines);
    for (int i = 0; i < n; i++, y += 21) f.text(ui_.s14, 12, y, lines[i]);
    y += 12;
  }
  button(f, 60, 300, W - 61, 340, "Home", ui_.b15);
}

// ---- Reader: shelf ----

std::string UiApp::bookProgress(const Shelf::Entry& e) const {
  const ReadingState::Entry* r = reading_.find(e.id);
  if (!r) return "New";
  if (r->finished) return "Done";
  return percent(r->position, e.textSize);
}

std::vector<uint32_t> UiApp::shelfList(int tab, bool* withCurrent) const {
  std::vector<uint32_t> out;
  *withCurrent = false;
  if (tab == 0) {  // recently read first, then the rest by title
    std::vector<bool> seen(shelf_.count());
    for (uint32_t id : reading_.recent()) {
      uint32_t i = shelf_.find(id);
      if (i != Shelf::kNone && !seen[i]) out.push_back(i), seen[i] = true;
    }
    *withCurrent = !out.empty();
    for (uint32_t i = 0; i < shelf_.count(); i++)
      if (!seen[i]) out.push_back(i);
  } else {
    for (uint32_t i = 0; i < shelf_.count(); i++) out.push_back(tab == 1 ? i : shelf_.byAuthor(i));
  }
  return out;
}

void UiApp::drawShelf(Frame& f) {
  statusBar(f, true);
  static const char* const kTabs[] = {"Recent", "Title", "Author"};
  int top = tabs(f, ui_.b14, kTabs, 3, shelfTab_);
  bool current;
  std::vector<uint32_t> list = shelfList(shelfTab_, &current);
  if (list.empty()) {
    f.centered(ui_.b15, 0, W, 120, "No books");
    f.centered(ui_.s13, 0, W, 146, "Run tools/make_ui_demo.py");
    return;
  }
  if (current) {  // the book you are in, with its cover
    Shelf::Entry e = shelf_.book(list[0]);
    int cy = top + 8, ch = 96;
    char path[32];
    Shelf::coverPath(e.id, path);
    std::string_view d = card_->file(path);
    G4Image cover;
    if (cover.open(reinterpret_cast<const uint8_t*>(d.data()), d.size())) {
      for (int y = 0; y < cover.height() && y < ch; y++)
        for (int x = 0; x < cover.width() && x < 72; x++) f.pixel(10 + x, cy + y, cover.blackInBw(x, y));
    }
    f.rect(9, cy - 1, 10 + 72, cy + ch);
    int x = 94, tw = W - 10 - x, y = cy - 1;
    std::string lines[2];
    int n = wrapText(ui_.b17, e.title, tw, 2, lines);
    for (int i = 0; i < n; i++, y += 23) f.text(ui_.b17, x, y, lines[i]);
    f.text(ui_.s13, x, y + 1, Frame::fit(ui_.s13, e.author, tw));
    badge(f, ui_.s12, x, y + 24, bookFormatName(e.format));
    uint32_t pos = reading_.position(e.id);
    std::string chapter;
    Book b;
    if (loadBook(e.id, &b) && b.tocAt(pos) >= 0) chapter = b.toc(b.tocAt(pos)).title;
    progress(f, x, cy + ch - 24, tw, 6, e.textSize ? (double)pos / e.textSize : 0);
    metaLine(f, ui_.s12, x, cy + ch - 13, {bookProgress(e), chapter}, tw);
    f.hline(0, W - 1, cy + ch + 8);
  }
  size_t first = current ? 1 : 0;
  int per = shelfRowsPerPage(current), total = (int)(list.size() - first);
  int pages = std::max(1, (total + per - 1) / per);
  int& page = shelfPage_[shelfTab_];
  page = std::min(page, pages - 1);
  int y = shelfRowsTop(current);
  for (int r = 0; r < per; r++, y += kShelfRowH) {
    size_t k = first + (size_t)(page * per + r);
    if (k >= list.size()) break;
    Shelf::Entry e = shelf_.book(list[k]);
    const char* fmt = bookFormatName(e.format);
    int bw = Frame::width(ui_.s12, fmt) + 8;
    f.text(ui_.b14, 10, y + 2, Frame::fit(ui_.b14, e.title, W - 20 - bw - 12));
    metaLine(f, ui_.s12, 10, y + 21, {e.author, bookProgress(e)}, W - 20);
    badge(f, ui_.s12, W - 10 - bw, y + 4, fmt);
    if (r + 1 < per && k + 1 < list.size()) f.dottedHline(10, W - 10, y + kShelfRowH - 1);
  }
  f.hline(0, W - 1, kListBottom);
  std::string where = std::to_string(page * per + first + 1) + "–" +
                      std::to_string(std::min<size_t>(list.size(), first + (size_t)(page + 1) * per)) + " / " +
                      std::to_string(list.size());
  f.centered(ui_.s12, 0, W, kListBottom + 4, where);
  if (page > 0) backArrow(f, 12, kListBottom + 6);
  if (page + 1 < pages) chevron(f, W - 18, kListBottom + 6);
}

void UiApp::tapShelf(int x, int y) {
  if (y < 48) {
    if (y >= 21) shelfTab_ = std::clamp(x * 3 / W, 0, 2), dirty();
    return;
  }
  bool current;
  std::vector<uint32_t> list = shelfList(shelfTab_, &current);
  if (list.empty()) return;
  if (current && y < shelfRowsTop(true)) return openBook(list[0]);
  int per = shelfRowsPerPage(current);
  if (y >= kListBottom) {
    if (x < W / 3) swipe(false);
    else if (x >= W - W / 3) swipe(true);
    return;
  }
  int r = (y - shelfRowsTop(current)) / kShelfRowH;
  size_t k = (current ? 1 : 0) + (size_t)(shelfPage_[shelfTab_] * per + r);
  if (r >= 0 && r < per && k < list.size()) openBook(list[k]);
}

// ---- Reader: the book ----

const BitmapFont* UiApp::readerFont(int px) const {
  int best = 0;
  for (int i = 0; i < 8; i++)
    if (std::abs(Settings::kFontSizes[i] - px) < std::abs(Settings::kFontSizes[best] - px)) best = i;
  return &reader_[best];
}

LayoutStyle UiApp::makeStyle(bool cjk) const {
  LayoutStyle s;
  s.body = readerFont(settings_.fontSize);
  s.heading = readerFont(settings_.headingSize());
  s.bodySize = settings_.fontSize;
  s.headingSize = settings_.headingSize();
  s.width = W - 2 * settings_.marginPx();
  s.height = H - kPageTop - kPageBottom;
  s.lineSpacing = settings_.lineSpacing;
  s.indentEms = settings_.indentEms(cjk);
  s.justify = settings_.justify != 0;
  return s;
}

bool UiApp::loadBook(uint32_t id, Book* book) const {
  char path[32];
  Shelf::bookPath(id, path);
  std::string_view d = card_->file(path);
  return !d.empty() && book->open(reinterpret_cast<const uint8_t*>(d.data()), d.size(), (uint32_t)d.size()) ==
                           Book::Error::None;
}

void UiApp::openBook(uint32_t shelfIndex) {
  Shelf::Entry e = shelf_.book(shelfIndex);
  if (!loadBook(e.id, &book_)) return;
  bookId_ = e.id;
  session_.open(&book_,
                [this](uint32_t s) {
                  uint32_t a = book_.sectionStart(s), b = book_.sectionEnd(s);
                  return a == Book::kNone ? std::string_view() : book_.text().substr(a, b - a);
                },
                makeStyle(book_.mostlyCjk()), reading_.position(e.id));
  reading_.opened(e.id);
  savePosition();
  nav_.push(Screen::Page);
  dirty();
}

void UiApp::savePosition() {
  reading_.setPosition(bookId_, session_.position());
  if (session_.atEnd()) reading_.setFinished(bookId_, true);
  store_->save("reading", reading_.serialize());
}

void UiApp::turnPage(bool forward) {
  if (!session_.isOpen() || !(forward ? session_.next() : session_.prev())) return;
  savePosition();
  dirty();
}

void UiApp::drawLines(Frame& f, const PageLayout& page, std::string_view text, uint32_t base,
                      const LayoutStyle& style, int left, int top) {
  for (const Line& line : page.lines) {
    auto* font = static_cast<const BitmapFont*>(line.heading && style.heading ? style.heading : style.body);
    int baseline = top + line.y + (line.height + font->ascent() - font->descent()) / 2;
    TextLayout::forEachGlyph(text, base, line, style, [&](uint32_t cp, int x, bool bold) {
      font->draw(cp, left + x, baseline, [&](int px, int py) { f.pixel(px, py); }, bold);
    });
  }
}

void UiApp::drawPage(Frame& f) {
  int margin = settings_.marginPx();
  drawLines(f, session_.page(), session_.sectionText(), session_.sectionBase(), session_.style(), margin, kPageTop);
  int c = session_.chapter();
  std::string_view chapter = c >= 0 ? book_.toc(c).title : book_.title();
  f.text(ui_.s12, margin, 3, Frame::fit(ui_.s12, chapter, W - 2 * margin - 16));
  if (locked_) iconLock(f, W - margin - 10, 3);
  f.text(ui_.s12, margin, H - 19, std::to_string((session_.permille() + 5) / 10) + "%");
  std::string pages = std::to_string(session_.pageInSection() + 1) + " / " + std::to_string(session_.pagesInSection());
  f.rightAligned(ui_.s12, W - margin, H - 19, pages);
}

void UiApp::drawMenu(Frame& f) {
  drawPage(f);
  int cover = 48;  // hide lines the top bar would cut, not just their tops
  for (const Line& line : session_.page().lines)
    if (kPageTop + line.y < 50) cover = std::max(cover, kPageTop + line.y + line.height);
  f.fill(0, 0, W - 1, cover, false);
  statusBar(f, true);
  backArrow(f, 9, 30);
  f.text(ui_.b14, 18, 25, "Shelf");
  f.centered(ui_.s13, 66, W - 34, 26, book_.title());
  const PageLayout& page = session_.page();
  iconBookmark(f, W - 22, 27, reading_.hasBookmark(bookId_, page.start, page.end));
  f.fill(0, 48, W - 1, 49);

  int top = kMenuTop, y = top + 9;
  f.fill(0, top, W - 1, H - 1, false);
  f.fill(0, top, W - 1, top + 1);
  int c = session_.chapter();
  std::string number = c >= 0 ? std::to_string(c + 1) : "";
  std::string_view title = c >= 0 ? book_.toc(c).title : book_.title();
  metaLine(f, ui_.b13, 10, y, {number, title}, 150);
  std::string pages = std::to_string(session_.pageInSection() + 1) + " / " + std::to_string(session_.pagesInSection());
  f.rightAligned(ui_.s12, W - 10, y + 1, pages);

  y += 26;  // where you are in the book, with the chapters as ticks
  int x0 = 12, x1 = W - 12;
  double size = std::max<uint32_t>(1, book_.textSize());
  f.fill(x0, y, x1, y + 1);
  int px = x0 + (int)std::lround((x1 - x0) * std::min(1.0, session_.position() / size));
  f.fill(x0, y - 1, px, y + 2);
  f.fill(px - 3, y - 6, px + 3, y + 7);
  for (uint32_t i = 0; i < book_.tocCount(); i++) {
    Book::TocEntry t = book_.toc(i);
    if (t.level <= 1) f.vline(x0 + (int)std::lround((x1 - x0) * (t.pos / size)), y + 5, y + 8);
  }
  y += 18;
  button(f, 8, y, W / 2 - 4, y + 30, "Contents", ui_.b13, iconList);
  button(f, W / 2 + 4, y, W - 9, y + 30, "Bookmarks", ui_.b13,
         [](Frame& fr, int bx, int by) { iconBookmark(fr, bx, by - 1, false); });
  y += 40;
  button(f, 8, y, 44, y + 30, "A", ui_.b13);
  f.centered(ui_.s13, 44, 96, y + 7, std::to_string(settings_.fontSize) + " px");
  button(f, 96, y, 132, y + 30, "A", ui_.b17);
  button(f, 140, y, W - 9, y + 30, "Aa  More", ui_.b13);
}

void UiApp::tapMenu(int x, int y) {
  if (y < 48) {
    if (x < 70) {
      nav_.backTo(Screen::Shelf);
      dirty();
    } else if (x >= W - 40) {
      reading_.toggleBookmark(bookId_, session_.page().start, session_.page().end);
      store_->save("reading", reading_.serialize());
      dirty();
    }
    return;
  }
  if (y < kMenuTop) {  // the page: close the menu
    nav_.back();
    return dirty();
  }
  if (y >= 304 && y < 332) {  // the slider: jump there
    double frac = std::clamp((x - 12) / (double)(W - 24), 0.0, 1.0);
    session_.goTo(std::min<uint32_t>((uint32_t)(frac * book_.textSize()), book_.textSize() ? book_.textSize() - 1 : 0));
    savePosition();
    return dirty();
  }
  if (y >= 335 && y <= 365) {
    contentsTab_ = x < W / 2 ? 0 : 1;
    contentsPage_ = -1;
    nav_.push(Screen::Contents);
    return dirty();
  }
  if (y >= 375 && y <= 405) {
    if (x < 46) {
      changeSetting("reader", "font_size", -1);
    } else if (x >= 94 && x < 136) {
      changeSetting("reader", "font_size", 1);
    } else if (x >= 140) {
      settingsSection_ = 1;
      nav_.openApp(App::Settings);
      nav_.push(Screen::SettingsPage);
      dirty();
    }
  }
}

// ---- Reader: contents and bookmarks ----

int UiApp::contentsCount() const {
  if (contentsTab_ == 0) return (int)book_.tocCount();
  const ReadingState::Entry* e = reading_.find(bookId_);
  return e ? (int)e->bookmarks.size() : 0;
}

int UiApp::contentsPageNow() const {
  int pages = std::max(1, (contentsCount() + kContentsRows - 1) / kContentsRows);
  int page = contentsPage_;
  if (page < 0) page = contentsTab_ == 0 && session_.chapter() >= 0 ? session_.chapter() / kContentsRows : 0;
  return std::min(page, pages - 1);
}

std::string UiApp::snippetAt(uint32_t pos) const {
  std::string_view text = book_.text();
  std::string out;
  size_t i = std::min<size_t>(pos, text.size());
  while (i < text.size() && out.size() < 120) {
    uint32_t c = dap::nextUtf8(text.data(), text.size(), i);
    if (c == '\n' || c == booktext::kLineBreak) {
      if (!out.empty() && out.back() != ' ') out += ' ';
    } else if (c >= 0x20) {
      size_t len = c < 0x80 ? 1 : c < 0x800 ? 2 : c < 0x10000 ? 3 : 4;
      out.append(text.data() + i - len, len);
    }
  }
  return out;
}

void UiApp::drawContents(Frame& f) {
  statusBar(f, true);
  const ReadingState::Entry* entry = reading_.find(bookId_);
  size_t marks = entry ? entry->bookmarks.size() : 0;
  std::string second = marks ? "Bookmarks " + std::to_string(marks) : "Bookmarks";
  const char* names[] = {"Contents", second.c_str()};
  int top = tabs(f, ui_.b14, names, 2, contentsTab_);
  int count = contentsCount(), page = contentsPageNow();
  int pages = std::max(1, (count + kContentsRows - 1) / kContentsRows);
  contentsPage_ = page;
  int current = contentsTab_ == 0 ? session_.chapter() : -1;
  double size = std::max<uint32_t>(1, book_.textSize());
  for (int r = 0; r < kContentsRows; r++) {
    int i = page * kContentsRows + r, y = top + r * kContentsRowH;
    if (i >= count) break;
    std::string title;
    uint32_t pos;
    int level = 1;
    if (contentsTab_ == 0) {
      Book::TocEntry t = book_.toc(i);
      title = std::string(t.title);
      pos = t.pos;
      level = t.level;
    } else {
      pos = entry->bookmarks[i];
      title = snippetAt(pos);
    }
    bool sel = i == current;
    if (sel) f.fill(0, y, W - 1, y + kContentsRowH - 2);
    int x = level <= 1 ? 12 : 26;
    // A bookmark shows book text, which only the reader fonts have every character of (the
    // UI fonts hold the titles, names and chapter titles).
    const BitmapFont& tf = contentsTab_ == 1 ? *readerFont(14) : sel ? ui_.b14 : ui_.s14;
    f.text(tf, x, y + 6, Frame::fit(tf, title, W - x - 50), !sel);
    f.rightAligned(ui_.s12, W - 12, y + 8, percent(pos, (uint64_t)size), !sel);
    if (!sel && i + 1 != current && r + 1 < kContentsRows && i + 1 < count)
      f.dottedHline(12, W - 12, y + kContentsRowH - 1);
  }
  if (count == 0 && contentsTab_ == 1) {
    f.centered(ui_.b15, 0, W, 90, "No bookmarks yet");
    f.centered(ui_.s13, 0, W, 116, "On a page, tap the middle for");
    f.centered(ui_.s13, 0, W, 134, "the menu, then the bookmark");
    f.centered(ui_.s13, 0, W, 152, "at its top right.");
  }
  int y = top + kContentsRows * kContentsRowH;
  f.hline(0, W - 1, y + 1);
  if (pages > 1) {
    f.centered(ui_.s12, 0, W, y + 7, std::to_string(page + 1) + " / " + std::to_string(pages));
    if (page > 0) backArrow(f, 12, y + 9);
    if (page + 1 < pages) chevron(f, W - 18, y + 9);
  } else if (contentsTab_ == 0) {
    std::string chapters = std::to_string(count) + (count == 1 ? " chapter" : " chapters");
    metaCentered(f, ui_.s12, y + 7, {book_.title(), chapters});
  }
}

void UiApp::tapContents(int x, int y) {
  if (y < 48) {
    if (y >= 21) contentsTab_ = x < W / 2 ? 0 : 1, contentsPage_ = -1, dirty();
    return;
  }
  int footer = 48 + kContentsRows * kContentsRowH;
  if (y >= footer) {
    if (x < W / 3) swipe(false);
    else if (x >= W - W / 3) swipe(true);
    return;
  }
  int i = contentsPageNow() * kContentsRows + (y - 48) / kContentsRowH;
  if (i >= contentsCount()) return;
  if (contentsTab_ == 0)
    session_.goToChapter((uint32_t)i);
  else
    session_.goTo(reading_.find(bookId_)->bookmarks[i]);
  savePosition();
  nav_.backTo(Screen::Page);
  dirty();
}

// ---- Settings ----

void UiApp::changeSetting(const char* section, const char* key, int dir) {
  const SettingInfo* info = findSetting(section, key);
  if (!info) return;
  int& v = settings_.*(info->field);
  v = stepSetting(*info, v, dir);
  settings_.fix();
  saveSettings();
  styleDirty_ = true;
  dirty();
}

void UiApp::drawSettingsList(Frame& f) {
  statusBar(f, true);
  f.text(ui_.b17, 10, 26, "Settings");
  f.hline(0, W - 1, 50);
  const Settings& s = settings_;
  std::string start = "Start volume " + std::to_string(s.startVolume), limit = "limit " + std::to_string(s.volumeLimit);
  std::string font = std::to_string(s.fontSize) + " px";
  std::string spacing = "line spacing " + formatSetting(*findSetting("reader", "line_spacing"), s.lineSpacing);
  std::string refresh = "Full refresh every " + std::to_string(s.fullRefreshEvery) + " pages";
  std::string lock = s.autoLockMinutes ? "Lock " + std::to_string(s.autoLockMinutes) + " min" : "Lock never";
  std::string sleep = s.sleepMinutes ? "sleep " + std::to_string(s.sleepMinutes) + " min" : "sleep never";
  std::string built = "built " + monthDay();
  for (int i = 0; i < 5; i++) {
    int y = 51 + i * 54;
    f.text(ui_.b15, 12, y + 8, kSectionNames[i]);
    switch (i) {
      case 0: metaLine(f, ui_.s12, 12, y + 30, {start, limit}, W - 44); break;
      case 1: metaLine(f, ui_.s12, 12, y + 30, {font, spacing}, W - 44); break;
      case 2: metaLine(f, ui_.s12, 12, y + 30, {refresh, s.invert ? "white on black" : ""}, W - 44); break;
      case 3: metaLine(f, ui_.s12, 12, y + 30, {lock, sleep}, W - 44); break;
      default: metaLine(f, ui_.s12, 12, y + 30, {"UI demo", built}, W - 44); break;
    }
    chevron(f, W - 18, y + 22);
    if (i < 4) f.dottedHline(12, W - 12, y + 53);
  }
  int y = 51 + 5 * 54;
  f.hline(0, W - 1, y);
  y += 12;
  f.text(ui_.b13, 12, y, "Storage");
  f.rightAligned(ui_.s12, W - 12, y + 1, "books in flash");
  std::string books = std::to_string(shelf_.count()) + " books";
  metaLine(f, ui_.s12, 12, y + 22, {books, "SD card: bring-up step 3"}, W - 24);
}

void UiApp::tapSettingsList(int, int y) {
  int i = (y - 51) / 54;
  if (y < 51 || i > 4) return;
  settingsSection_ = i;
  nav_.push(Screen::SettingsPage);
  dirty();
}

void UiApp::drawSettingsPage(Frame& f) {
  statusBar(f, true);
  backArrow(f, 9, 32);
  f.text(ui_.s13, 18, 27, "Settings");
  f.centered(ui_.b17, 80, W - 80, 26, kSectionNames[settingsSection_]);
  f.hline(0, W - 1, 50);
  if (settingsSection_ == 4) return drawAbout(f);
  size_t n;
  const SettingInfo* table = settingsTable(&n);
  std::vector<const SettingInfo*> rows;
  for (size_t i = 0; i < n; i++)
    if (strcmp(table[i].section, kSectionKeys[settingsSection_]) == 0) rows.push_back(&table[i]);
  for (size_t r = 0; r < rows.size(); r++) {
    int y = 51 + (int)r * 36, right = W - 10;
    Control c = controlFor(*rows[r], settings_.*(rows[r]->field));
    int left;
    if (c.options.empty()) {
      stepper(f, ui_.s13, right, y + 6, c.value);
      left = right - 26 - kValueW - 26;
    } else {
      int starts[4], widths[4];
      left = segments(ui_.s12, c.options, right, starts, widths);
      segmented(f, ui_.s12, right, y + 6, c.options, c.selected);
    }
    f.text(ui_.s13, 12, y + 10, Frame::fit(ui_.s13, c.label, left - 18));
    if (r + 1 < rows.size()) f.dottedHline(12, W - 12, y + 35);
  }
  if (settingsSection_ != 1) return;
  // Reader: a preview of the text with these settings, from the book you are in.
  int y = 51 + (int)rows.size() * 36 + 10;
  f.text(ui_.b13, 12, y, "Preview");
  int boxTop = y + 18, boxBottom = H - 8;
  f.roundRect(2, boxTop, W - 3, boxBottom, 6);
  std::string sample = previewText();
  LayoutStyle style = makeStyle(session_.isOpen() && book_.mostlyCjk());
  style.height = boxBottom - boxTop - 10;
  PageLayout layout;
  TextLayout::layoutPage(sample, 0, 0, style, &layout);
  drawLines(f, layout, sample, 0, style, settings_.marginPx(), boxTop + 4);
}

std::string UiApp::previewText() const {
  std::string out;  // body paragraphs from where you are in the book; headings would fill the box
  if (session_.isOpen()) {
    std::string_view t = book_.text();
    size_t i = std::min<size_t>(session_.position(), t.size()), limit = std::min(t.size(), i + 8000);
    while (i < limit && out.size() < 300) {
      size_t end = t.find('\n', i);
      if (end == std::string_view::npos || end >= limit) break;
      uint8_t first = (uint8_t)t[i];
      if (!(first >= booktext::kH1 && first <= booktext::kRule) && first != booktext::kLineBreak)
        out.append(t.substr(i, end + 1 - i));
      i = end + 1;
    }
  }
  if (out.empty())
    out = "The fog came in from the sea. Every evening the harbour lamps were lit one by one, like someone "
          "writing on the water, a line at a time.\n";
  return out;
}

void UiApp::drawAbout(Frame& f) {
  int y = 63;
  f.text(ui_.b15, 12, y, "E-ink DAP: UI demo");
  y += 26;
  std::string lines[] = {
      "Firmware built " + monthDay(),
      std::to_string(shelf_.count()) + " books and their fonts in flash",
      "Refreshes: " + std::to_string(partials_) + " partial, " + std::to_string(fulls_) + " full",
      calibrated_ ? "Touch: calibrated" : "Touch: not calibrated",
  };
  for (const std::string& line : lines) f.text(ui_.s13, 12, y, line), y += 19;
  button(f, 12, 176, W - 13, 210, "Calibrate touch", ui_.b15);
  std::string wrapped[4];
  int n = wrapText(ui_.s12, "Music, the microSD card and the side keys come with the next bring-up steps.", W - 24,
                   4, wrapped);
  for (int i = 0; i < n; i++) f.text(ui_.s12, 12, 228 + 17 * i, wrapped[i]);
}

void UiApp::tapSettingsPage(int x, int y) {
  if (y < 50) {
    if (y >= 20 && x < 100) nav_.back(), dirty();
    return;
  }
  if (settingsSection_ == 4) {
    if (y >= 172 && y <= 214) calibrate();
    return;
  }
  size_t n;
  const SettingInfo* table = settingsTable(&n);
  int row = (y - 51) / 36, r = 0;
  for (size_t i = 0; i < n; i++) {
    const SettingInfo& s = table[i];
    if (strcmp(s.section, kSectionKeys[settingsSection_]) != 0 || r++ != row) continue;
    int& v = settings_.*(s.field);
    Control c = controlFor(s, v);
    int right = W - 10, old = v;
    if (c.options.empty()) {
      int plus = right - 26, minus = plus - kValueW - 26;
      if (x >= plus - 4) v = stepSetting(s, v, 1);
      else if (x >= minus - 6 && x < minus + 30) v = stepSetting(s, v, -1);
    } else {
      int starts[4], widths[4];
      segments(ui_.s12, c.options, right, starts, widths);
      for (int k = 0; k < (int)c.options.size(); k++) {
        if (x < starts[k] - (k == 0 ? 6 : 0) || x >= starts[k] + widths[k] + 6) continue;
        v = s.kind == SettingInfo::Toggle ? (onIsFirst(s) ? k == 0 : k == 1) : k;
        break;
      }
    }
    if (v == old) return;
    settings_.fix();
    saveSettings();
    styleDirty_ = true;
    bool look = strcmp(s.key, "invert") == 0 || strcmp(s.key, "rotate_180") == 0;
    return dirty(look ? Refresh::Full : Refresh::Partial);
  }
}
