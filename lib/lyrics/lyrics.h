// Synced lyrics (.lrc) parser. Plain C++17, no Arduino dependency (tested on the host
// with `pio test -e native`).
//
// Handles [mm:ss], [mm:ss.x], [mm:ss.xx], [mm:ss.xxx] and [mm:ss:xx] time tags, several
// time tags in front of one line, the [ti:], [ar:], [al:] and [offset:] tags, CR/LF/CRLF
// line ends, a UTF-8 BOM, and enhanced-LRC word times (<mm:ss.xx>), which are removed.
// Text is UTF-8 and kept byte for byte (CJK included). Lines without a time tag are ignored.
//
// Usage: read the whole .lrc file into a buffer, parse(), then call indexAt() with the
// playback position each time the display updates.
#pragma once
#include <cstddef>
#include <cstdint>
#include <string>
#include <string_view>
#include <vector>

class Lyrics {
 public:
  // Replaces any previous content. Returns false if the text has no timed line.
  bool parse(std::string_view lrc);
  void clear();

  size_t size() const { return lines_.size(); }
  bool empty() const { return lines_.empty(); }
  // Line time in ms, already shifted by [offset:]. Lines are sorted by time; lines that
  // share a time (e.g. a translation under the original) keep their order from the file.
  uint32_t timeMs(size_t i) const { return lines_[i].ms; }
  // May be empty: an empty timed line clears the lyrics during an instrumental part.
  std::string_view text(size_t i) const { return view(lines_[i].text); }

  // The line to highlight at playback position `ms`: the first of the lines with the
  // latest time <= ms, or -1 before the first line.
  int indexAt(uint32_t ms) const;
  // One past the last line that shares line i's time (i + 1 if none do).
  size_t groupEnd(size_t i) const;

  std::string_view title() const { return view(title_); }
  std::string_view artist() const { return view(artist_); }
  std::string_view album() const { return view(album_); }
  // [offset:] in ms. Positive means the lyrics appear earlier (times were reduced by it).
  int32_t offsetMs() const { return offsetMs_; }

 private:
  struct Span {
    uint32_t start = 0, len = 0;  // into buf_
  };
  struct Line {
    uint32_t ms;
    Span text;
  };
  Span store(std::string_view s);
  std::string_view view(Span s) const { return std::string_view(buf_).substr(s.start, s.len); }

  std::string buf_;  // all text, so lines don't each allocate
  std::vector<Line> lines_;
  Span title_, artist_, album_;
  int32_t offsetMs_ = 0;
};
