#include "frame.h"

#include <cmath>
#include <vector>

#include "dapfile.h"
#include "text_layout.h"

void Frame::fill(int x0, int y0, int x1, int y1, bool black) {
  if (x0 > x1) std::swap(x0, x1);
  if (y0 > y1) std::swap(y0, y1);
  x0 = std::max(x0, 0);
  y0 = std::max(y0, 0);
  x1 = std::min(x1, kWidth - 1);
  y1 = std::min(y1, kHeight - 1);
  for (int y = y0; y <= y1; y++)
    for (int x = x0; x <= x1; x++) pixel(x, y, black);
}

void Frame::dottedHline(int x0, int x1, int y) {
  for (int x = x0; x < x1; x += 2) pixel(x, y);
}

// How far row y of a box from y0 to y1 with corner radius r is inset at each side.
static int cornerInset(int r, int y, int y0, int y1) {
  int d = std::min(y - y0, y1 - y);
  if (r <= 0 || d >= r) return 0;
  double dy = r - d - 0.5;
  return r - (int)std::lround(std::sqrt(std::max(0.0, (double)r * r - dy * dy)));
}

void Frame::roundRect(int x0, int y0, int x1, int y1, int r, bool filled, bool black) {
  for (int y = y0; y <= y1; y++) {
    int a = cornerInset(r, y, y0, y1);
    if (filled || y == y0 || y == y1) {
      hline(x0 + a, x1 - a, y, black);
      continue;
    }
    int b = std::max(cornerInset(r - 1, y, y0 + 1, y1 - 1) + 1, a + 1);  // the inside starts here
    hline(x0 + a, x0 + b - 1, y, black);
    hline(x1 - b + 1, x1 - a, y, black);
  }
}

void Frame::line(int x0, int y0, int x1, int y1, int width, bool black) {
  int dx = std::abs(x1 - x0), dy = -std::abs(y1 - y0);
  int sx = x0 < x1 ? 1 : -1, sy = y0 < y1 ? 1 : -1, err = dx + dy;
  bool steep = -dy > dx;
  for (;;) {
    for (int k = 0; k < width; k++) pixel(x0 + (steep ? k : 0), y0 + (steep ? 0 : k), black);
    if (x0 == x1 && y0 == y1) break;
    int e2 = 2 * err;
    if (e2 >= dy) err += dy, x0 += sx;
    if (e2 <= dx) err += dx, y0 += sy;
  }
}

void Frame::fillPolygon(const float* xy, int n, bool black) {
  float top = xy[1], bottom = xy[1];
  for (int i = 1; i < n; i++) top = std::min(top, xy[2 * i + 1]), bottom = std::max(bottom, xy[2 * i + 1]);
  std::vector<float> xs;
  for (int y = (int)std::floor(top); y <= (int)std::ceil(bottom); y++) {
    xs.clear();
    for (int i = 0; i < n; i++) {  // vertices are pixel centres, so compare with y itself
      float ax = xy[2 * i], ay = xy[2 * i + 1], bx = xy[2 * ((i + 1) % n)], by = xy[2 * ((i + 1) % n) + 1];
      if ((ay <= y && by > y) || (by <= y && ay > y)) xs.push_back(ax + (y - ay) * (bx - ax) / (by - ay));
    }
    std::sort(xs.begin(), xs.end());
    for (size_t i = 0; i + 1 < xs.size(); i += 2) hline((int)std::ceil(xs[i]), (int)std::floor(xs[i + 1]), y, black);
  }
  for (int i = 0; i < n; i++)  // the edges too, as the mockups draw them
    line((int)std::lround(xy[2 * i]), (int)std::lround(xy[2 * i + 1]), (int)std::lround(xy[2 * ((i + 1) % n)]),
         (int)std::lround(xy[2 * ((i + 1) % n) + 1]), 1, black);
}

void Frame::fillEllipse(int x0, int y0, int x1, int y1, bool black) {
  double cx = (x0 + x1) / 2.0, cy = (y0 + y1) / 2.0, rx = (x1 - x0) / 2.0 + 0.5, ry = (y1 - y0) / 2.0 + 0.5;
  for (int y = y0; y <= y1; y++) {
    double t = (y - cy) / ry;
    if (std::fabs(t) > 1) continue;
    double hw = rx * std::sqrt(1 - t * t);
    hline((int)std::lround(cx - hw + 0.5), (int)std::lround(cx + hw - 0.5), y, black);
  }
}

int Frame::text(const BitmapFont& f, int x, int y, std::string_view s, bool black) {
  int baseline = y + f.ascent();
  size_t i = 0;
  while (i < s.size()) {
    uint32_t c = dap::nextUtf8(s.data(), s.size(), i);
    if (c < 0x20) continue;
    x += f.draw(c, x, baseline, [&](int px, int py) { pixel(px, py, black); });
  }
  return x;
}

void Frame::centered(const BitmapFont& f, int x0, int x1, int y, std::string_view s, bool black) {
  std::string t = fit(f, s, x1 - x0);
  text(f, (x0 + x1 - width(f, t)) / 2, y, t, black);
}

void Frame::rightAligned(const BitmapFont& f, int right, int y, std::string_view s, bool black) {
  text(f, right - width(f, s), y, s, black);
}

int Frame::width(const BitmapFont& f, std::string_view s) {
  int w = 0;
  size_t i = 0;
  while (i < s.size()) {
    uint32_t c = dap::nextUtf8(s.data(), s.size(), i);
    if (c >= 0x20) w += f.advance(c);
  }
  return w;
}

std::string Frame::fit(const BitmapFont& f, std::string_view s, int width) {
  if (Frame::width(f, s) <= width) return std::string(s);
  int room = width - f.advance(0x2026), w = 0;
  size_t i = 0, end = 0;
  while (i < s.size()) {
    uint32_t c = dap::nextUtf8(s.data(), s.size(), i);
    if (c >= 0x20 && (w += f.advance(c)) > room) break;
    end = i;
  }
  while (end > 0 && s[end - 1] == ' ') end--;
  return std::string(s.substr(0, end)) + "…";
}

static std::string_view trimEnd(std::string_view s) {
  while (!s.empty() && s.back() == ' ') s.remove_suffix(1);
  return s;
}

int wrapText(const BitmapFont& f, std::string_view s, int width, int maxLines, std::string* lines) {
  // Tokens: one CJK character, or a Latin word with the spaces after it.
  std::vector<size_t> starts;
  enum { kAfterCjk, kInWord, kAfterSpace } state = kAfterCjk;
  size_t i = 0;
  while (i < s.size()) {
    size_t at = i;
    uint32_t c = dap::nextUtf8(s.data(), s.size(), i);
    if (booktext::isCjk(c)) {
      starts.push_back(at);
      state = kAfterCjk;
    } else if (c == ' ') {
      if (state == kAfterCjk) starts.push_back(at);
      state = kAfterSpace;
    } else {
      if (state != kInWord) starts.push_back(at);
      state = kInWord;
    }
  }
  starts.push_back(s.size());
  int n = 0;
  size_t t = 0;
  while (t + 1 < starts.size() && n < maxLines) {
    size_t start = starts[t];
    if (n == maxLines - 1) {
      lines[n++] = Frame::fit(f, trimEnd(s.substr(start)), width);
      break;
    }
    size_t end = starts[++t];
    while (t + 1 < starts.size() && Frame::width(f, trimEnd(s.substr(start, starts[t + 1] - start))) <= width)
      end = starts[++t];
    lines[n++] = Frame::fit(f, trimEnd(s.substr(start, end - start)), width);
  }
  return n;
}
