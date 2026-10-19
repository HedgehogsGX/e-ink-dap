// Reader for the music library index that tools/build_index.py writes to
// /.dap/library.idx on the card (format: docs/formats.md). Plain C++17, no Arduino
// dependency (tested on the host with `pio test -e native`).
//
// Load the whole file into memory (PSRAM on the board, ps_malloc: roughly 150-200 bytes
// per track), then open() it. Everything is read in place, so the strings are views into
// that buffer: keep it alive while you use the index. Every accessor is bounds-checked;
// out-of-range indexes and damaged offsets give empty records, never a crash.
#pragma once
#include <cstddef>
#include <cstdint>
#include <string_view>

class LibraryIndex {
 public:
  static constexpr uint32_t kNone = 0xFFFFFFFF;

  enum class Codec : uint8_t { Unknown = 0, Flac = 1, Mp3 = 2, Wav = 3 };

  struct Track {
    std::string_view path;    // from the card root, e.g. "/Artist/Album/01 Song.flac"
    std::string_view title;   // the file name (without extension) if untagged
    std::string_view artist;  // empty if untagged
    uint32_t durationMs = 0;
    uint32_t sampleRate = 0;
    uint32_t album = kNone;     // index for album()
    uint16_t trackNo = 0;       // 0 = unknown
    uint8_t discNo = 0;         // 0 = unknown
    uint8_t bitsPerSample = 0;  // 0 for MP3
    uint8_t channels = 0;
    Codec codec = Codec::Unknown;
    uint16_t bitrateKbps = 0;
    bool hasLyrics = false;  // a .lrc with the same name is next to the file
  };

  struct Album {
    std::string_view title;
    std::string_view artist;  // album artist, "Various Artists" for mixed ones, empty if unknown
    std::string_view art;     // path of the .g4 cover, empty if none
    uint32_t firstTrack = 0;  // the album's tracks are track(firstTrack ... firstTrack + trackCount - 1),
    uint16_t trackCount = 0;  // in disc/track order
    uint16_t year = 0;        // 0 = unknown
  };

  struct Artist {
    std::string_view name;    // empty = unknown artist
    uint32_t firstAlbum = 0;  // the artist's albums are artistAlbum(firstAlbum ... + albumCount - 1)
    uint16_t albumCount = 0;
    uint16_t trackCount = 0;
  };

  enum class Error { None, TooSmall, BadMagic, UnsupportedVersion, SizeMismatch, BadLayout, BadChecksum };
  static const char* errorText(Error e);

  // Checks the header and that every section lies inside the file; with verifyChecksum,
  // also the CRC-32 of the whole file (catches a half-copied index).
  Error open(const uint8_t* data, size_t size, bool verifyChecksum = true);
  bool isOpen() const { return data_ != nullptr; }

  uint32_t trackCount() const { return trackCount_; }
  uint32_t albumCount() const { return albumCount_; }
  uint32_t artistCount() const { return artistCount_; }
  uint32_t builtUnixTime() const;

  // Tracks are stored album by album, in album order.
  Track track(uint32_t i) const;
  // Sorted by title.
  Album album(uint32_t i) const;
  // Sorted by name, unknown artist last.
  Artist artist(uint32_t i) const;
  // The n-th track in title order (an index for track()), kNone if n is out of range.
  uint32_t songByTitle(uint32_t n) const;
  // Album index at position n of the artist album list (each artist's albums by year),
  // kNone if n is out of range.
  uint32_t artistAlbum(uint32_t n) const;

  // CRC-32 as used by zip/zlib (Python's zlib.crc32). Pass the previous result to continue.
  static uint32_t crc32(const uint8_t* data, size_t size, uint32_t crc = 0);

 private:
  std::string_view str(uint32_t offset) const;

  const uint8_t* data_ = nullptr;
  size_t size_ = 0;
  uint32_t trackCount_ = 0, albumCount_ = 0, artistCount_ = 0;
  uint32_t tracksAt_ = 0, albumsAt_ = 0, artistsAt_ = 0, artistAlbumsAt_ = 0, songsAt_ = 0;
  uint32_t stringsAt_ = 0, stringsSize_ = 0;
  uint32_t trackSize_ = 0, albumSize_ = 0, artistSize_ = 0;
};
