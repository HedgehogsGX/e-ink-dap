// The player's settings, saved on the card as /.dap/settings.ini (docs/formats.md). Plain
// C++17, no Arduino dependency.
//
// Every setting is described once in settingsTable(): its section and key in the file,
// its label and range for the Settings screens. Values are ints (on/off is 1/0, a choice
// is its index), so the table can point at them. A missing or damaged file just means
// defaults: start volume stays low, which matters with sensitive IEMs.
#pragma once
#include <cstddef>
#include <string>
#include <string_view>
#include <vector>

struct Settings {
  enum Repeat { kRepeatOff, kRepeatAll, kRepeatOne };
  enum Margins { kMarginsSmall, kMarginsMedium, kMarginsLarge };
  enum Indent { kIndentAuto, kIndentOn, kIndentOff };
  enum Language { kEnglish, kChinese, kJapanese };

  // Music. Volume is in steps of 1.5 dB, 40 = 0 dB (as in the player).
  int startVolume = 10;
  int volumeLimit = 40;
  int resume = 1;  // reopen the last song, paused, at its position
  int repeat = kRepeatOff;
  int shuffle = 0;
  int lyricTranslations = 1;  // show the translation lines under the lyrics
  // Reader
  int fontSize = 18;  // px, one of kFontSizes
  int lineSpacing = 150;  // percent
  int margins = kMarginsMedium;
  int indent = kIndentAuto;  // auto: indent Chinese/Japanese books, not Latin ones
  int justify = 1;
  int volumeKeysTurnPages = 0;  // in a book; holding them still changes the volume
  // Display
  int fullRefreshEvery = 10;  // partial refreshes (page turns) between two full ones
  int invert = 0;             // white text on black
  int rotate180 = 0;          // for a case that mounts the panel upside down
  // System
  int autoLockMinutes = 2;  // 0 = never
  int sleepMinutes = 15;    // idle and not playing; 0 = never
  int language = kEnglish;

  static constexpr int kFontSizes[] = {14, 16, 18, 20, 22, 24, 28, 32};  // the sizes tools/fonts.py makes

  // Reads an ini file over the current values. Unknown keys and bad values are skipped and
  // reported in `problems` (if given); every value is then fixed into its range.
  void parse(std::string_view ini, std::vector<std::string>* problems = nullptr);
  std::string serialize() const;
  // Clamps every value into its range and keeps the start volume at or below the limit.
  void fix();

  int marginPx() const;               // left and right of the text: 6, 14 or 22 px
  int indentEms(bool cjkBook) const;  // first-line indent for a book
  int headingSize() const;            // the next font size up, for chapter titles
};

struct SettingInfo {
  enum Kind { Number, Toggle, Choice };
  const char* section;  // [section] in the file, and the Settings page it is on
  const char* key;
  const char* label;
  Kind kind;
  int Settings::*field;
  int min = 0, max = 1, step = 1;   // Number
  const int* steps = nullptr;       // Number: only these values (font sizes), if given
  int stepCount = 0;
  int divisor = 1;                  // Number: shown divided by this (150 -> "1.5")
  const char* unit = "";            // Number: shown after the value
  const char* const* values = nullptr;  // Choice: words in the file
  const char* const* labels = nullptr;  // Choice: what the screen shows
  int count = 0;                        // Choice: how many
};

const SettingInfo* settingsTable(size_t* count);
const SettingInfo* findSetting(const char* section, const char* key);
// The value one step up (dir > 0) or down from the current one, kept in range.
int stepSetting(const SettingInfo& info, int value, int dir);
// The value as the Settings screen shows it: "18 px", "1.5", "On", "Medium".
std::string formatSetting(const SettingInfo& info, int value);
