#include "settings.h"

#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <cstring>

namespace {

SettingInfo number(const char* section, const char* key, const char* label, int Settings::*field, int min, int max,
                   int step, const char* unit = "", int divisor = 1) {
  SettingInfo s{section, key, label, SettingInfo::Number, field};
  s.min = min;
  s.max = max;
  s.step = step;
  s.unit = unit;
  s.divisor = divisor;
  return s;
}

SettingInfo toggle(const char* section, const char* key, const char* label, int Settings::*field) {
  return SettingInfo{section, key, label, SettingInfo::Toggle, field};
}

SettingInfo choice(const char* section, const char* key, const char* label, int Settings::*field,
                   const char* const* values, const char* const* labels, int count) {
  SettingInfo s{section, key, label, SettingInfo::Choice, field};
  s.max = count - 1;
  s.values = values;
  s.labels = labels;
  s.count = count;
  return s;
}

const char* const kRepeatValues[] = {"off", "all", "one"};
const char* const kRepeatLabels[] = {"Off", "All", "One"};
const char* const kMarginValues[] = {"small", "medium", "large"};
const char* const kMarginLabels[] = {"S", "M", "L"};
const char* const kIndentValues[] = {"auto", "on", "off"};
const char* const kIndentLabels[] = {"Auto", "On", "Off"};
const char* const kLanguageValues[] = {"en", "zh", "ja"};
const char* const kLanguageLabels[] = {"English", "中文", "日本語"};

std::vector<SettingInfo> makeTable() {
  using S = Settings;
  SettingInfo font = number("reader", "font_size", "Font size", &S::fontSize, 14, 32, 2, "px");
  font.steps = Settings::kFontSizes;
  font.stepCount = (int)(sizeof Settings::kFontSizes / sizeof Settings::kFontSizes[0]);
  return {
      number("music", "start_volume", "Start volume", &S::startVolume, 0, 40, 1),
      number("music", "volume_limit", "Volume limit", &S::volumeLimit, 0, 40, 1),
      toggle("music", "resume", "Resume last song", &S::resume),
      choice("music", "repeat", "Repeat", &S::repeat, kRepeatValues, kRepeatLabels, 3),
      toggle("music", "shuffle", "Shuffle", &S::shuffle),
      toggle("music", "lyric_translations", "Lyric translations", &S::lyricTranslations),
      font,
      number("reader", "line_spacing", "Line spacing", &S::lineSpacing, 120, 200, 10, "", 100),
      choice("reader", "margins", "Margins", &S::margins, kMarginValues, kMarginLabels, 3),
      choice("reader", "indent", "Indent", &S::indent, kIndentValues, kIndentLabels, 3),
      toggle("reader", "justify", "Justify", &S::justify),
      toggle("reader", "volume_keys_turn_pages", "Volume keys turn pages", &S::volumeKeysTurnPages),
      number("display", "full_refresh_every", "Full refresh every", &S::fullRefreshEvery, 1, 50, 1, "pages"),
      toggle("display", "invert", "White on black", &S::invert),
      toggle("display", "rotate_180", "Upside down", &S::rotate180),
      number("system", "auto_lock_minutes", "Lock after", &S::autoLockMinutes, 0, 30, 1, "min"),
      number("system", "sleep_minutes", "Sleep after", &S::sleepMinutes, 0, 120, 5, "min"),
      choice("system", "language", "Language", &S::language, kLanguageValues, kLanguageLabels, 3),
  };
}

const std::vector<SettingInfo>& table() {
  static const std::vector<SettingInfo> t = makeTable();
  return t;
}

std::string_view trim(std::string_view s) {
  while (!s.empty() && (s.front() == ' ' || s.front() == '\t')) s.remove_prefix(1);
  while (!s.empty() && (s.back() == ' ' || s.back() == '\t' || s.back() == '\r')) s.remove_suffix(1);
  return s;
}

bool equalsNoCase(std::string_view a, const char* b) {
  size_t n = strlen(b);
  if (a.size() != n) return false;
  for (size_t i = 0; i < n; i++) {
    char x = a[i], y = b[i];
    if (x >= 'A' && x <= 'Z') x += 'a' - 'A';
    if (x != y) return false;
  }
  return true;
}

// The value written in the file for a setting, or false if it isn't one.
bool readValue(const SettingInfo& info, std::string_view text, int* out) {
  if (info.kind == SettingInfo::Toggle) {
    for (const char* on : {"on", "true", "yes", "1"})
      if (equalsNoCase(text, on)) return *out = 1, true;
    for (const char* off : {"off", "false", "no", "0"})
      if (equalsNoCase(text, off)) return *out = 0, true;
    return false;
  }
  if (info.kind == SettingInfo::Choice) {
    for (int i = 0; i < info.count; i++)
      if (equalsNoCase(text, info.values[i])) return *out = i, true;
    return false;
  }
  std::string s(text);
  char* end;
  long v = strtol(s.c_str(), &end, 10);
  if (end == s.c_str() || *end != 0) return false;
  *out = (int)std::max(-1000000L, std::min(1000000L, v));
  return true;
}

int clampSetting(const SettingInfo& info, int v) {
  v = std::max(info.min, std::min(info.max, v));
  if (info.steps) {  // the nearest allowed value
    int best = info.steps[0];
    for (int i = 0; i < info.stepCount; i++)
      if (abs(info.steps[i] - v) < abs(best - v)) best = info.steps[i];
    v = best;
  }
  return v;
}

}  // namespace

const SettingInfo* settingsTable(size_t* count) {
  *count = table().size();
  return table().data();
}

const SettingInfo* findSetting(const char* section, const char* key) {
  for (const SettingInfo& s : table())
    if (!strcmp(s.section, section) && !strcmp(s.key, key)) return &s;
  return nullptr;
}

int stepSetting(const SettingInfo& info, int value, int dir) {
  if (info.kind == SettingInfo::Toggle) return value ? 0 : 1;
  if (info.steps) {
    int i = 0;
    while (i + 1 < info.stepCount && info.steps[i] < value) i++;
    i = std::max(0, std::min(info.stepCount - 1, i + (dir > 0 ? 1 : dir < 0 ? -1 : 0)));
    return info.steps[i];
  }
  return clampSetting(info, value + (dir > 0 ? info.step : dir < 0 ? -info.step : 0));
}

std::string formatSetting(const SettingInfo& info, int value) {
  if (info.kind == SettingInfo::Toggle) return value ? "On" : "Off";
  if (info.kind == SettingInfo::Choice) return value >= 0 && value < info.count ? info.labels[value] : "?";
  char buf[32];
  if (info.divisor > 1) {
    snprintf(buf, sizeof buf, "%d.%d", value / info.divisor, value % info.divisor * 10 / info.divisor);
  } else if (value == 0 && !strcmp(info.unit, "min")) {
    snprintf(buf, sizeof buf, "Never");
  } else {
    snprintf(buf, sizeof buf, info.unit[0] ? "%d %s" : "%d", value, info.unit);
  }
  return buf;
}

void Settings::fix() {
  for (const SettingInfo& info : table()) this->*info.field = clampSetting(info, this->*info.field);
  startVolume = std::min(startVolume, volumeLimit);
}

void Settings::parse(std::string_view ini, std::vector<std::string>* problems) {
  std::string section;
  size_t lineNo = 0;
  auto problem = [&](const std::string& what) {
    if (problems) problems->push_back("line " + std::to_string(lineNo) + ": " + what);
  };
  while (!ini.empty()) {
    size_t nl = ini.find('\n');
    std::string_view line = trim(ini.substr(0, nl));
    ini = nl == std::string_view::npos ? std::string_view() : ini.substr(nl + 1);
    lineNo++;
    if (line.empty() || line[0] == '#' || line[0] == ';') continue;
    if (line.front() == '[' && line.back() == ']') {
      section = std::string(trim(line.substr(1, line.size() - 2)));
      for (char& c : section) c = (c >= 'A' && c <= 'Z') ? (char)(c + 'a' - 'A') : c;
      continue;
    }
    size_t eq = line.find('=');
    if (eq == std::string_view::npos) {
      problem("not 'key = value'");
      continue;
    }
    std::string key(trim(line.substr(0, eq)));
    for (char& c : key) c = (c >= 'A' && c <= 'Z') ? (char)(c + 'a' - 'A') : c;
    std::string_view value = line.substr(eq + 1);
    for (size_t k = 1; k < value.size(); k++) {  // "key = value  ; comment"
      if ((value[k] == ';' || value[k] == '#') && (value[k - 1] == ' ' || value[k - 1] == '\t')) {
        value = value.substr(0, k);
        break;
      }
    }
    value = trim(value);
    const SettingInfo* info = findSetting(section.c_str(), key.c_str());
    int v;
    if (!info) {
      problem("unknown setting [" + section + "] " + key);
    } else if (!readValue(*info, value, &v)) {
      problem("bad value for " + key + ": " + std::string(value));
    } else {
      this->*info->field = v;
    }
  }
  fix();
}

std::string Settings::serialize() const {
  std::string out = "# E-ink DAP settings. You can edit this on a computer; the player rewrites it.\n";
  const char* section = "";
  for (const SettingInfo& info : table()) {
    if (strcmp(section, info.section)) {
      section = info.section;
      out += std::string("\n[") + section + "]\n";
    }
    int v = this->*info.field;
    out += std::string(info.key) + " = ";
    if (info.kind == SettingInfo::Toggle) out += v ? "on" : "off";
    else if (info.kind == SettingInfo::Choice) out += v >= 0 && v < info.count ? info.values[v] : info.values[0];
    else out += std::to_string(v);
    out += '\n';
  }
  return out;
}

int Settings::marginPx() const {
  static const int kPx[] = {6, 14, 22};
  return kPx[std::max(0, std::min(2, margins))];
}

int Settings::indentEms(bool cjkBook) const {
  if (indent == kIndentOn) return 2;
  if (indent == kIndentOff) return 0;
  return cjkBook ? 2 : 1;
}

int Settings::headingSize() const {
  for (int s : kFontSizes)
    if (s > fontSize) return s;
  return fontSize;
}
