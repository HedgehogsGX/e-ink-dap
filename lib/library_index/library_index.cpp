#include "library_index.h"

#include <cstring>

#include "dapfile.h"

using dap::rd16;
using dap::rd32;

namespace {

// Header layout: docs/formats.md. All numbers are little-endian.
constexpr size_t kHeaderSize = 64;
constexpr uint16_t kVersion = 1;
constexpr uint32_t kTrackSize = 32, kAlbumSize = 20, kArtistSize = 12;

}  // namespace

const char* LibraryIndex::errorText(Error e) {
  switch (e) {
    case Error::None: return "ok";
    case Error::TooSmall: return "file too small";
    case Error::BadMagic: return "not a library index";
    case Error::UnsupportedVersion: return "index version not supported (rebuild it with tools/build_index.py)";
    case Error::SizeMismatch: return "file size differs from the header (cut short while copying?)";
    case Error::BadLayout: return "sections out of bounds (damaged file)";
    case Error::BadChecksum: return "checksum mismatch (damaged file)";
  }
  return "?";
}

LibraryIndex::Error LibraryIndex::open(const uint8_t* data, size_t size, bool verifyChecksum) {
  *this = LibraryIndex();
  if (data == nullptr || size < kHeaderSize) return Error::TooSmall;
  if (memcmp(data, "DAPL", 4) != 0) return Error::BadMagic;
  if (rd16(data + 4) != kVersion) return Error::UnsupportedVersion;
  if (rd32(data + 8) != size) return Error::SizeMismatch;
  size_t headerSize = rd16(data + 6);
  if (headerSize < kHeaderSize || headerSize > size) return Error::BadLayout;

  uint32_t tracks = rd32(data + 16), albums = rd32(data + 20), artists = rd32(data + 24);
  uint32_t trackSize = rd16(data + 56), albumSize = data[58], artistSize = data[59];
  uint32_t stringsAt = rd32(data + 48), stringsSize = rd32(data + 52);
  // True if `count` records of `recSize` bytes at `at` lie between the header and the end.
  auto fits = [&](uint32_t at, uint64_t count, uint64_t recSize) {
    return at >= headerSize && at <= size && count * recSize <= size - at;
  };
  if (trackSize < kTrackSize || albumSize < kAlbumSize || artistSize < kArtistSize ||
      !fits(rd32(data + 28), tracks, trackSize) || !fits(rd32(data + 32), albums, albumSize) ||
      !fits(rd32(data + 36), artists, artistSize) || !fits(rd32(data + 40), albums, 2) ||
      !fits(rd32(data + 44), tracks, 4) || stringsSize == 0 || !fits(stringsAt, stringsSize, 1) ||
      data[stringsAt + stringsSize - 1] != 0) {  // so every string ends inside the pool
    return Error::BadLayout;
  }
  if (verifyChecksum && crc32(data + headerSize, size - headerSize) != rd32(data + 12)) {
    return Error::BadChecksum;
  }

  data_ = data;
  size_ = size;
  trackCount_ = tracks;
  albumCount_ = albums;
  artistCount_ = artists;
  tracksAt_ = rd32(data + 28);
  albumsAt_ = rd32(data + 32);
  artistsAt_ = rd32(data + 36);
  artistAlbumsAt_ = rd32(data + 40);
  songsAt_ = rd32(data + 44);
  stringsAt_ = stringsAt;
  stringsSize_ = stringsSize;
  trackSize_ = trackSize;
  albumSize_ = albumSize;
  artistSize_ = artistSize;
  return Error::None;
}

uint32_t LibraryIndex::builtUnixTime() const { return data_ ? rd32(data_ + 60) : 0; }

std::string_view LibraryIndex::str(uint32_t offset) const {
  if (offset >= stringsSize_) return {};
  return std::string_view(reinterpret_cast<const char*>(data_ + stringsAt_ + offset));
}

LibraryIndex::Track LibraryIndex::track(uint32_t i) const {
  Track t;
  if (i >= trackCount_) return t;
  const uint8_t* p = data_ + tracksAt_ + (size_t)i * trackSize_;
  t.path = str(rd32(p));
  t.title = str(rd32(p + 4));
  t.artist = str(rd32(p + 8));
  t.durationMs = rd32(p + 12);
  t.sampleRate = rd32(p + 16);
  t.album = rd16(p + 20);
  t.trackNo = rd16(p + 22);
  t.discNo = p[24];
  t.bitsPerSample = p[25];
  t.channels = p[26];
  t.codec = p[27] <= (uint8_t)Codec::Wav ? (Codec)p[27] : Codec::Unknown;
  t.bitrateKbps = rd16(p + 28);
  t.hasLyrics = p[30] & 1;
  return t;
}

LibraryIndex::Album LibraryIndex::album(uint32_t i) const {
  Album a;
  if (i >= albumCount_) return a;
  const uint8_t* p = data_ + albumsAt_ + (size_t)i * albumSize_;
  a.title = str(rd32(p));
  a.artist = str(rd32(p + 4));
  a.art = str(rd32(p + 8));
  a.firstTrack = rd32(p + 12);
  a.trackCount = rd16(p + 16);
  a.year = rd16(p + 18);
  return a;
}

LibraryIndex::Artist LibraryIndex::artist(uint32_t i) const {
  Artist a;
  if (i >= artistCount_) return a;
  const uint8_t* p = data_ + artistsAt_ + (size_t)i * artistSize_;
  a.name = str(rd32(p));
  a.firstAlbum = rd32(p + 4);
  a.albumCount = rd16(p + 8);
  a.trackCount = rd16(p + 10);
  return a;
}

uint32_t LibraryIndex::songByTitle(uint32_t n) const {
  return n < trackCount_ ? rd32(data_ + songsAt_ + (size_t)n * 4) : kNone;
}

uint32_t LibraryIndex::artistAlbum(uint32_t n) const {
  return n < albumCount_ ? rd16(data_ + artistAlbumsAt_ + (size_t)n * 2) : kNone;
}

uint32_t LibraryIndex::crc32(const uint8_t* data, size_t size, uint32_t crc) { return dap::crc32(data, size, crc); }
