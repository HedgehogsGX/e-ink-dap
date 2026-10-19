// Host tests for lib/library_index: pio test -e native
//
// sample_library.idx is real output of the PC tool, so these tests also check that the
// Python writer and the C++ reader agree. To remake it:
//   tools/make_sample_library.sh
//   SOURCE_DATE_EPOCH=1792108800 uv run tools/build_index.py sample_music.nosync \
//       --out test/test_library/sample_library.idx
#include <unity.h>

#include <cstdio>
#include <string>
#include <vector>

#include "library_index.h"

using Codec = LibraryIndex::Codec;
using Error = LibraryIndex::Error;

static std::vector<uint8_t> fixture;

static std::vector<uint8_t> readFixture() {
  std::string path = __FILE__;
  path = path.substr(0, path.find_last_of("/\\") + 1) + "sample_library.idx";
  std::vector<uint8_t> data;
  if (FILE* f = fopen(path.c_str(), "rb")) {
    int c;
    while ((c = fgetc(f)) != EOF) data.push_back((uint8_t)c);
    fclose(f);
  }
  return data;
}

static std::string s(std::string_view v) { return std::string(v); }

static void put32(std::vector<uint8_t>& d, size_t at, uint32_t v) {
  for (int i = 0; i < 4; i++) d[at + i] = (uint8_t)(v >> (8 * i));
}

static LibraryIndex openFixture() {
  LibraryIndex lib;
  TEST_ASSERT_EQUAL(Error::None, lib.open(fixture.data(), fixture.size()));
  return lib;
}

void setUp() {}
void tearDown() {}

static void test_fixture_present() {
  TEST_ASSERT_TRUE_MESSAGE(fixture.size() > 64, "test/test_library/sample_library.idx missing");
}

static void test_crc32_matches_zlib() {
  const uint8_t text[] = "123456789";
  TEST_ASSERT_EQUAL_HEX32(0xCBF43926, LibraryIndex::crc32(text, 9));
  TEST_ASSERT_EQUAL_HEX32(0xCBF43926, LibraryIndex::crc32(text + 4, 5, LibraryIndex::crc32(text, 4)));
}

static void test_counts() {
  LibraryIndex lib = openFixture();
  TEST_ASSERT_TRUE(lib.isOpen());
  TEST_ASSERT_EQUAL_UINT32(8, lib.trackCount());
  TEST_ASSERT_EQUAL_UINT32(4, lib.albumCount());
  TEST_ASSERT_EQUAL_UINT32(4, lib.artistCount());
  TEST_ASSERT_EQUAL_UINT32(1792108800, lib.builtUnixTime());
}

static void test_albums_sorted_by_title() {
  LibraryIndex lib = openFixture();
  const char* titles[] = {"Analog Summer", "Loose Tracks", "Paper Weather", "城市夜航"};
  const char* artists[] = {"Various Artists", "", "Mizuiro Tape", "林夕舟"};
  const char* art[] = {"", "", "/.dap/art/00002.g4", "/.dap/art/00003.g4"};
  const uint16_t years[] = {2021, 0, 2024, 2019};
  const uint16_t counts[] = {2, 1, 3, 2};
  uint32_t next = 0;
  for (uint32_t i = 0; i < 4; i++) {
    LibraryIndex::Album a = lib.album(i);
    TEST_ASSERT_EQUAL_STRING(titles[i], s(a.title).c_str());
    TEST_ASSERT_EQUAL_STRING(artists[i], s(a.artist).c_str());
    TEST_ASSERT_EQUAL_STRING(art[i], s(a.art).c_str());
    TEST_ASSERT_EQUAL_UINT16(years[i], a.year);
    TEST_ASSERT_EQUAL_UINT16(counts[i], a.trackCount);
    TEST_ASSERT_EQUAL_UINT32(next, a.firstTrack);  // albums own consecutive track ranges
    for (uint32_t t = a.firstTrack; t < a.firstTrack + a.trackCount; t++) {
      TEST_ASSERT_EQUAL_UINT32(i, lib.track(t).album);
    }
    next += a.trackCount;
  }
  TEST_ASSERT_EQUAL_UINT32(lib.trackCount(), next);
}

static void test_flac_hires_track_with_lyrics() {
  LibraryIndex lib = openFixture();
  LibraryIndex::Track t = lib.track(lib.album(2).firstTrack);
  TEST_ASSERT_EQUAL_STRING("/Mizuiro Tape/Paper Weather/01 群青の午後.flac", s(t.path).c_str());
  TEST_ASSERT_EQUAL_STRING("群青の午後", s(t.title).c_str());
  TEST_ASSERT_EQUAL_STRING("Mizuiro Tape", s(t.artist).c_str());
  TEST_ASSERT_EQUAL(Codec::Flac, t.codec);
  TEST_ASSERT_EQUAL_UINT32(96000, t.sampleRate);
  TEST_ASSERT_EQUAL_UINT8(24, t.bitsPerSample);
  TEST_ASSERT_EQUAL_UINT8(2, t.channels);
  TEST_ASSERT_EQUAL_UINT32(3000, t.durationMs);
  TEST_ASSERT_EQUAL_UINT16(1, t.trackNo);
  TEST_ASSERT_TRUE(t.hasLyrics);
  TEST_ASSERT_EQUAL_STRING("Mizuiro Tape feat. Kiko", s(lib.track(lib.album(2).firstTrack + 1).artist).c_str());
  TEST_ASSERT_FALSE(lib.track(lib.album(2).firstTrack + 1).hasLyrics);
}

static void test_mp3_and_untagged_wav() {
  LibraryIndex lib = openFixture();
  LibraryIndex::Track mp3 = lib.track(lib.album(0).firstTrack);
  TEST_ASSERT_EQUAL_STRING("Sunday Dials", s(mp3.title).c_str());
  TEST_ASSERT_EQUAL_STRING("Kiko & The Dials", s(mp3.artist).c_str());
  TEST_ASSERT_EQUAL(Codec::Mp3, mp3.codec);
  TEST_ASSERT_EQUAL_UINT32(44100, mp3.sampleRate);
  TEST_ASSERT_EQUAL_UINT8(0, mp3.bitsPerSample);
  TEST_ASSERT_EQUAL_UINT16(320, mp3.bitrateKbps);

  LibraryIndex::Track wav = lib.track(lib.album(1).firstTrack);
  TEST_ASSERT_EQUAL_STRING("demo take 3", s(wav.title).c_str());  // file name, no tags
  TEST_ASSERT_TRUE(wav.artist.empty());
  TEST_ASSERT_EQUAL(Codec::Wav, wav.codec);
  TEST_ASSERT_EQUAL_UINT32(48000, wav.sampleRate);
  TEST_ASSERT_EQUAL_UINT8(24, wav.bitsPerSample);
  TEST_ASSERT_EQUAL_UINT16(0, wav.trackNo);
  TEST_ASSERT_TRUE(wav.hasLyrics);
}

static void test_two_disc_album_in_disc_order() {
  LibraryIndex lib = openFixture();
  LibraryIndex::Album a = lib.album(3);
  LibraryIndex::Track d1 = lib.track(a.firstTrack), d2 = lib.track(a.firstTrack + 1);
  TEST_ASSERT_EQUAL_STRING("夜航船", s(d1.title).c_str());
  TEST_ASSERT_EQUAL_UINT8(1, d1.discNo);
  TEST_ASSERT_EQUAL_STRING("灯塔", s(d2.title).c_str());
  TEST_ASSERT_EQUAL_UINT8(2, d2.discNo);
  TEST_ASSERT_EQUAL_STRING("/林夕舟/城市夜航/CD2/01 灯塔.flac", s(d2.path).c_str());
}

static void test_artists_unknown_last() {
  LibraryIndex lib = openFixture();
  const char* names[] = {"Mizuiro Tape", "Various Artists", "林夕舟", ""};
  const char* albums[] = {"Paper Weather", "Analog Summer", "城市夜航", "Loose Tracks"};
  const uint16_t tracks[] = {3, 2, 2, 1};
  for (uint32_t i = 0; i < 4; i++) {
    LibraryIndex::Artist ar = lib.artist(i);
    TEST_ASSERT_EQUAL_STRING(names[i], s(ar.name).c_str());
    TEST_ASSERT_EQUAL_UINT16(1, ar.albumCount);
    TEST_ASSERT_EQUAL_UINT16(tracks[i], ar.trackCount);
    TEST_ASSERT_EQUAL_STRING(albums[i], s(lib.album(lib.artistAlbum(ar.firstAlbum)).title).c_str());
  }
}

static void test_songs_by_title() {
  LibraryIndex lib = openFixture();
  // Latin first, then kana (群青の午後 has the sort tag ぐんじょうのごご), then hanzi by code point.
  const char* order[] = {"demo take 3", "Low Tide Radio", "Night Bus", "Sunday Dials",
                         "Umbrella Song", "群青の午後", "夜航船", "灯塔"};
  for (uint32_t n = 0; n < 8; n++) {
    TEST_ASSERT_EQUAL_STRING(order[n], s(lib.track(lib.songByTitle(n)).title).c_str());
  }
}

static void test_out_of_range_gives_empty_records() {
  LibraryIndex lib = openFixture();
  TEST_ASSERT_TRUE(lib.track(8).path.empty());
  TEST_ASSERT_EQUAL_UINT32(LibraryIndex::kNone, lib.track(8).album);
  TEST_ASSERT_TRUE(lib.album(LibraryIndex::kNone).title.empty());
  TEST_ASSERT_TRUE(lib.artist(4).name.empty());
  TEST_ASSERT_EQUAL_UINT32(LibraryIndex::kNone, lib.songByTitle(8));
  TEST_ASSERT_EQUAL_UINT32(LibraryIndex::kNone, lib.artistAlbum(4));
  TEST_ASSERT_TRUE(lib.track(lib.songByTitle(8)).title.empty());
}

static void test_rejects_damaged_files() {
  LibraryIndex lib;
  std::vector<uint8_t> d = fixture;
  TEST_ASSERT_EQUAL(Error::TooSmall, lib.open(nullptr, 0));
  TEST_ASSERT_EQUAL(Error::TooSmall, lib.open(d.data(), 63));
  TEST_ASSERT_EQUAL(Error::SizeMismatch, lib.open(d.data(), d.size() - 1));  // cut short
  TEST_ASSERT_FALSE(lib.isOpen());

  d[100] ^= 0x40;  // one flipped bit in the body
  TEST_ASSERT_EQUAL(Error::BadChecksum, lib.open(d.data(), d.size()));
  TEST_ASSERT_EQUAL(Error::None, lib.open(d.data(), d.size(), false));

  d = fixture;
  d[0] = 'X';
  TEST_ASSERT_EQUAL(Error::BadMagic, lib.open(d.data(), d.size()));
  d = fixture;
  d[4] = 2;  // version 2
  TEST_ASSERT_EQUAL(Error::UnsupportedVersion, lib.open(d.data(), d.size()));
}

static void test_rejects_bad_offsets_even_without_checksum() {
  LibraryIndex lib;
  std::vector<uint8_t> d = fixture;
  put32(d, 28, (uint32_t)d.size() - 16);  // track table runs past the end
  TEST_ASSERT_EQUAL(Error::BadLayout, lib.open(d.data(), d.size(), false));

  d = fixture;
  put32(d, 16, 0x10000000);  // absurd track count
  TEST_ASSERT_EQUAL(Error::BadLayout, lib.open(d.data(), d.size(), false));

  d = fixture;
  d.back() = 'x';  // strings come last; the pool must end with a NUL
  TEST_ASSERT_EQUAL(Error::BadLayout, lib.open(d.data(), d.size(), false));
}

static void test_bad_string_offset_reads_empty() {
  LibraryIndex lib;
  std::vector<uint8_t> d = fixture;
  put32(d, 64, 0xFFFFFF00);  // path offset of track 0
  TEST_ASSERT_EQUAL(Error::None, lib.open(d.data(), d.size(), false));
  TEST_ASSERT_TRUE(lib.track(0).path.empty());
  TEST_ASSERT_EQUAL_STRING("Sunday Dials", s(lib.track(0).title).c_str());
}

int main() {
  fixture = readFixture();
  UNITY_BEGIN();
  RUN_TEST(test_fixture_present);
  RUN_TEST(test_crc32_matches_zlib);
  if (fixture.size() > 64) {
    RUN_TEST(test_counts);
    RUN_TEST(test_albums_sorted_by_title);
    RUN_TEST(test_flac_hires_track_with_lyrics);
    RUN_TEST(test_mp3_and_untagged_wav);
    RUN_TEST(test_two_disc_album_in_disc_order);
    RUN_TEST(test_artists_unknown_last);
    RUN_TEST(test_songs_by_title);
    RUN_TEST(test_out_of_range_gives_empty_records);
    RUN_TEST(test_rejects_damaged_files);
    RUN_TEST(test_rejects_bad_offsets_even_without_checksum);
    RUN_TEST(test_bad_string_offset_reads_empty);
  }
  return UNITY_END();
}
