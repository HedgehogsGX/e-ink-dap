// The player's screens, drawn into a Frame in answer to taps and key presses: the home
// screen, the Reader and Settings apps, and a stand-in for Music until the SD card and the
// DAC are wired. Layouts follow the mockups (docs/previews/, tools/render_previews.py),
// navigation lib/ui_nav. Plain C++17, no Arduino dependency: src/ui_demo runs it on the
// board (books and fonts in flash, settings in NVS) and src/ui_sim on the host.
#pragma once
#include <cstdint>
#include <string>
#include <string_view>
#include <vector>

#include "bitmap_font.h"
#include "book.h"
#include "frame.h"
#include "reader.h"
#include "settings.h"
#include "ui_nav.h"

// The card's files. Here a whole file at once, valid as long as the CardFiles lives;
// empty if missing. (The player will read books a section at a time from the SD card.)
class CardFiles {
 public:
  virtual ~CardFiles() = default;
  virtual std::string_view file(std::string_view path) const = 0;
};

// Small values kept across restarts: "settings" (ini), "reading" (reading state) and
// "touch" (calibration).
class KeyValueStore {
 public:
  virtual ~KeyValueStore() = default;
  virtual std::string load(const char* key) = 0;
  virtual void save(const char* key, const std::string& value) = 0;
};

enum class Refresh : uint8_t { None, Partial, Full };

class UiApp {
 public:
  static constexpr int W = Frame::kWidth, H = Frame::kHeight;

  // Opens the shelf and the fonts and loads what the store kept. False, with the reason, if
  // files are missing. Starts with the touch calibration if none is saved.
  bool begin(const CardFiles* card, KeyValueStore* store, std::string* error);

  // A finger down at (x0, y0) and up at (x1, y1), in the touch controller's coordinates;
  // the calibration maps them to the screen. A tap, or a swipe that turns pages.
  void touch(int x0, int y0, int x1, int y1);
  void key(Key k, KeyPress press);
  void calibrate();  // three targets to tap; redo from Settings > About
  bool calibrating() const { return calStep_ >= 0; }
  void redraw(Refresh r = Refresh::Full) { dirty(r); }

  Refresh pending() const { return pending_; }
  // Draws the current screen. Returns the refresh to show it with: partial, and a full
  // one after Settings' "full refresh every" partial ones (and when the look changes).
  Refresh render(Frame& frame);

  const Settings& settings() const { return settings_; }
  const char* screenName() const;
  // Panel coordinates of a touch point, after calibration and the "upside down" setting.
  void mapTouch(int rx, int ry, int* x, int* y) const;

 private:
  struct Fonts {
    BitmapFont s12, s13, s14, s15, b13, b14, b15, b17, b18, b20;
  };

  // Screens
  void drawHome(Frame& f);
  void drawMusic(Frame& f);
  void drawShelf(Frame& f);
  void drawPage(Frame& f);
  void drawMenu(Frame& f);
  void drawContents(Frame& f);
  void drawSettingsList(Frame& f);
  void drawSettingsPage(Frame& f);
  void drawAbout(Frame& f);
  void drawCalibration(Frame& f);
  // Laid-out lines of book text, the text area's top left at (left, top).
  static void drawLines(Frame& f, const PageLayout& page, std::string_view text, uint32_t base,
                        const LayoutStyle& style, int left, int top);
  void statusBar(Frame& f, bool home);

  void tap(int x, int y);
  void tapHome(int x, int y);
  void tapShelf(int x, int y);
  void tapMenu(int x, int y);
  void tapContents(int x, int y);
  void tapSettingsList(int x, int y);
  void tapSettingsPage(int x, int y);
  void swipe(bool forward);
  void calibrationTap(int rx, int ry);

  // Reader
  std::vector<uint32_t> shelfList(int tab, bool* withCurrent) const;  // shelf indices
  int shelfRowsTop(bool withCurrent) const { return withCurrent ? 161 : 48; }
  int shelfRowsPerPage(bool withCurrent) const { return (kListBottom - shelfRowsTop(withCurrent)) / kShelfRowH; }
  bool loadBook(uint32_t id, Book* book) const;
  void openBook(uint32_t shelfIndex);
  LayoutStyle makeStyle(bool cjkBook) const;
  void turnPage(bool forward);
  void savePosition();
  void changeSetting(const char* section, const char* key, int dir);
  std::string bookProgress(const Shelf::Entry& e) const;
  std::string snippetAt(uint32_t pos) const;  // a bookmark's text
  std::string previewText() const;            // for Settings > Reader
  int contentsCount() const;
  int contentsPageNow() const;
  const BitmapFont* readerFont(int px) const;  // the nearest size there is
  void saveSettings() { store_->save("settings", settings_.serialize()); }

  void dirty(Refresh r = Refresh::Partial) { pending_ = r > pending_ ? r : pending_; }

  static constexpr int kStatusH = 20, kStatusTap = 24;  // the bar is 20 px; a tap a little below it counts too
  static constexpr int kPageTop = 24, kPageBottom = 24;
  static constexpr int kShelfRowH = 38, kListBottom = 395;
  static constexpr int kContentsRowH = 30, kContentsRows = 11;
  static constexpr int kMenuTop = 282;

  const CardFiles* card_ = nullptr;
  KeyValueStore* store_ = nullptr;
  Fonts ui_;
  BitmapFont reader_[8];  // Settings::kFontSizes
  Shelf shelf_;
  Settings settings_;
  ReadingState reading_;
  Navigator nav_;

  uint32_t bookId_ = 0;
  Book book_;
  ReaderSession session_;
  bool styleDirty_ = false;  // settings changed: lay the open book out again

  int shelfTab_ = 0, shelfPage_[3] = {};
  int contentsTab_ = 0, contentsPage_ = 0;
  int settingsSection_ = 0;  // Music, Reader, Display, System, About
  bool locked_ = false;

  float cal_[6] = {1, 0, 0, 0, 1, 0};  // panel x = c0 rx + c1 ry + c2, y = c3 rx + c4 ry + c5
  bool calibrated_ = false;
  int calStep_ = -1, calRaw_[3][2] = {};
  bool calRetry_ = false;

  Refresh pending_ = Refresh::Full;
  int partialsSinceFull_ = 0;
  uint32_t partials_ = 0, fulls_ = 0;
};
