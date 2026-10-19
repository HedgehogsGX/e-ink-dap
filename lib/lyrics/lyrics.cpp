#include "lyrics.h"

#include <algorithm>

namespace {

bool isDigit(char c) { return c >= '0' && c <= '9'; }
bool isAlpha(char c) { return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z'); }

std::string_view trim(std::string_view s) {
  auto space = [](char c) { return c == ' ' || c == '\t' || c == '\r' || c == '\n'; };
  while (!s.empty() && space(s.front())) s.remove_prefix(1);
  while (!s.empty() && space(s.back())) s.remove_suffix(1);
  return s;
}

bool equalsLower(std::string_view s, std::string_view lower) {
  if (s.size() != lower.size()) return false;
  for (size_t i = 0; i < s.size(); i++) {
    char c = s[i];
    if (c >= 'A' && c <= 'Z') c += 'a' - 'A';
    if (c != lower[i]) return false;
  }
  return true;
}

// Reads up to maxLen digits starting at s[*i]. Returns how many were read.
size_t readDigits(std::string_view s, size_t* i, size_t maxLen, uint32_t* value) {
  size_t n = 0;
  uint32_t v = 0;
  while (*i < s.size() && n < maxLen && isDigit(s[*i])) {
    v = v * 10 + (s[*i] - '0');
    ++*i;
    ++n;
  }
  *value = v;
  return n;
}

// "m:ss", "mm:ss.f", "mm:ss.ff", "mm:ss.fff" or "mm:ss:ff" -> ms.
bool parseTime(std::string_view tag, uint32_t* ms) {
  size_t i = 0;
  uint32_t min, sec, frac = 0;
  if (readDigits(tag, &i, 4, &min) == 0 || i >= tag.size() || tag[i++] != ':') return false;
  if (readDigits(tag, &i, 2, &sec) == 0 || sec >= 60) return false;
  if (i < tag.size()) {
    if (tag[i] != '.' && tag[i] != ':') return false;
    i++;
    size_t n = readDigits(tag, &i, 3, &frac);
    if (n == 0) return false;
    while (i < tag.size() && isDigit(tag[i])) i++;  // finer than 1 ms: ignored
    frac *= n == 1 ? 100 : n == 2 ? 10 : 1;
  }
  if (i != tag.size()) return false;
  *ms = (min * 60 + sec) * 1000 + frac;
  return true;
}

// "key:value" with a letters-only key, e.g. "ti:Song" or "offset:+200".
bool splitInfoTag(std::string_view tag, std::string_view* key, std::string_view* value) {
  size_t colon = tag.find(':');
  if (colon == std::string_view::npos || colon == 0) return false;
  if (!std::all_of(tag.begin(), tag.begin() + colon, isAlpha)) return false;
  *key = tag.substr(0, colon);
  *value = trim(tag.substr(colon + 1));
  return true;
}

bool parseInt(std::string_view s, int32_t* out) {
  bool neg = false;
  if (!s.empty() && (s[0] == '+' || s[0] == '-')) {
    neg = s[0] == '-';
    s.remove_prefix(1);
  }
  size_t i = 0;
  uint32_t v;
  if (readDigits(s, &i, 9, &v) == 0 || i != s.size()) return false;
  *out = neg ? -(int32_t)v : (int32_t)v;
  return true;
}

}  // namespace

void Lyrics::clear() {
  buf_.clear();
  lines_.clear();
  title_ = artist_ = album_ = Span{};
  offsetMs_ = 0;
}

Lyrics::Span Lyrics::store(std::string_view s) {
  Span span{(uint32_t)buf_.size(), (uint32_t)s.size()};
  buf_.append(s.data(), s.size());
  return span;
}

bool Lyrics::parse(std::string_view lrc) {
  clear();
  if (lrc.substr(0, 3) == "\xEF\xBB\xBF") lrc.remove_prefix(3);
  buf_.reserve(lrc.size());

  std::vector<uint32_t> times;
  std::string words;
  size_t pos = 0;
  while (pos < lrc.size()) {
    size_t end = lrc.find_first_of("\r\n", pos);
    if (end == std::string_view::npos) end = lrc.size();
    std::string_view rest = trim(lrc.substr(pos, end - pos));
    pos = end + 1;

    // Leading tags: time tags, or (before any time tag) "key:value" info tags.
    times.clear();
    while (!rest.empty() && rest.front() == '[') {
      size_t close = rest.find(']');
      if (close == std::string_view::npos) break;
      std::string_view tag = rest.substr(1, close - 1);
      uint32_t ms;
      std::string_view key, value;
      if (parseTime(tag, &ms)) {
        times.push_back(ms);
      } else if (times.empty() && splitInfoTag(tag, &key, &value)) {
        if (equalsLower(key, "ti")) title_ = store(value);
        else if (equalsLower(key, "ar")) artist_ = store(value);
        else if (equalsLower(key, "al")) album_ = store(value);
        else if (equalsLower(key, "offset")) parseInt(value, &offsetMs_);
      } else {
        break;  // not a tag, e.g. "[Chorus]": the rest is text
      }
      rest.remove_prefix(close + 1);
    }
    if (times.empty()) continue;

    // Drop enhanced-LRC word times: "<00:01.00>Hello <00:01.50>world" -> "Hello world".
    rest = trim(rest);
    if (rest.find('<') != std::string_view::npos) {
      words.clear();
      for (size_t i = 0; i < rest.size();) {
        size_t close = rest[i] == '<' ? rest.find('>', i) : std::string_view::npos;
        uint32_t ms;
        if (close != std::string_view::npos && parseTime(rest.substr(i + 1, close - i - 1), &ms)) {
          i = close + 1;
        } else {
          words += rest[i++];
        }
      }
      rest = trim(words);
    }
    Span text = store(rest);
    for (uint32_t ms : times) lines_.push_back({ms, text});
  }

  for (Line& line : lines_) {
    int64_t t = (int64_t)line.ms - offsetMs_;
    line.ms = t < 0 ? 0 : t > UINT32_MAX ? UINT32_MAX : (uint32_t)t;
  }
  std::stable_sort(lines_.begin(), lines_.end(), [](const Line& a, const Line& b) { return a.ms < b.ms; });
  return !lines_.empty();
}

int Lyrics::indexAt(uint32_t ms) const {
  auto after = std::upper_bound(lines_.begin(), lines_.end(), ms,
                                [](uint32_t t, const Line& line) { return t < line.ms; });
  int i = (int)(after - lines_.begin()) - 1;
  while (i > 0 && lines_[i - 1].ms == lines_[i].ms) i--;
  return i;
}

size_t Lyrics::groupEnd(size_t i) const {
  size_t j = i + 1;
  while (j < lines_.size() && lines_[j].ms == lines_[i].ms) j++;
  return j;
}
