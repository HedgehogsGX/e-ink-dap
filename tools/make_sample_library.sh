#!/bin/sh
# Makes a small fake music library in sample_music.nosync/ to try the PC tools on
# (build_index.py, cover_art.py) without a real card. Needs ffmpeg and flac, like
# make_bench_clips.sh. Every artist, album and lyric in it is made up.
#
# It covers the cases the index builder has to get right: FLAC 96/24 and 44.1/16, MP3,
# untagged WAV, CJK tags and file names, a sort tag, a two-disc album in CD1/CD2
# folders, a compilation without an album artist, cover.jpg vs embedded art, a UTF-8
# and a GBK .lrc, and files to skip (macOS "._" files, .Trashes, m4a, txt).
set -e
cd "$(dirname "$0")/.."
out=sample_music.nosync
rm -rf "$out"
mkdir -p "$out"
tmp="$out/tmp"

tone() {  # rate, then ffmpeg output args. 3 s of a quiet 440 Hz tone.
  rate=$1
  shift
  ffmpeg -v error -y -f lavfi -i "sine=frequency=440:sample_rate=$rate:duration=3" \
    -af volume=0.1 -ac 2 -map_metadata -1 -fflags +bitexact "$@"
}

flac_track() {  # file, rate, bits, then metaflac options. Adds $album, $albumartist, $date.
  file=$1 rate=$2 bits=$3
  shift 3
  mkdir -p "$(dirname "$file")"
  tone "$rate" -c:a "pcm_s${bits}le" "$tmp.wav"
  flac -s -f -o "$file" "$tmp.wav"
  # --no-utf8-convert: the tags are UTF-8 already; without it metaflac goes through the locale.
  metaflac --no-utf8-convert --remove-all-tags "--set-tag=ALBUM=$album" "--set-tag=ALBUMARTIST=$albumartist" \
    "--set-tag=DATE=$date" "$@" "$file"
}

mp3_track() {  # file, then ffmpeg -metadata options
  file=$1
  shift
  mkdir -p "$(dirname "$file")"
  tone 44100 -c:a libmp3lame -b:a 320k "$@" "$file"
}

# 1. Album with cover.jpg in the folder, FLAC 96 kHz / 24-bit, a CJK title with a sort tag.
a="$out/Mizuiro Tape/Paper Weather"
album="Paper Weather" albumartist="Mizuiro Tape" date=2024
flac_track "$a/01 群青の午後.flac" 96000 24 \
  "--set-tag=TITLE=群青の午後" "--set-tag=TITLESORT=ぐんじょうのごご" "--set-tag=ARTIST=Mizuiro Tape" \
  --set-tag=TRACKNUMBER=1
flac_track "$a/02 Low Tide Radio.flac" 96000 24 \
  "--set-tag=TITLE=Low Tide Radio" "--set-tag=ARTIST=Mizuiro Tape feat. Kiko" --set-tag=TRACKNUMBER=2/3
flac_track "$a/03 Umbrella Song.flac" 96000 24 \
  "--set-tag=TITLE=Umbrella Song" "--set-tag=ARTIST=Mizuiro Tape" --set-tag=TRACKNUMBER=3/3
ffmpeg -v error -y -f lavfi -i "mandelbrot=size=600x600" -frames:v 1 "$a/cover.jpg"
cat > "$a/01 群青の午後.lrc" <<'EOF'
[ti:群青の午後]
[ar:Mizuiro Tape]
[al:Paper Weather]
[00:00.40]窓の外は まだ雨のまま
[00:00.40]窗外依旧下着雨
[00:01.20]紙の空に 青を塗った
[00:01.20]在纸做的天空涂上蓝色
[00:02.60]
EOF

# 2. Two-disc album in CD1/CD2 folders, FLAC 44.1 kHz / 16-bit, cover embedded in the files.
a="$out/林夕舟/城市夜航"
ffmpeg -v error -y -f lavfi -i "gradients=size=500x500:seed=7" -frames:v 1 "$tmp.jpg"
album="城市夜航" albumartist="林夕舟" date=2019-03-01
flac_track "$a/CD1/01 夜航船.flac" 44100 16 "--set-tag=TITLE=夜航船" "--set-tag=ARTIST=林夕舟" \
  --set-tag=TRACKNUMBER=1 --set-tag=DISCNUMBER=1/2 "--import-picture-from=3|image/jpeg|Front cover||$tmp.jpg"
flac_track "$a/CD2/01 灯塔.flac" 44100 16 "--set-tag=TITLE=灯塔" "--set-tag=ARTIST=林夕舟" \
  --set-tag=TRACKNUMBER=1 --set-tag=DISCNUMBER=2/2 "--import-picture-from=3|image/jpeg|Front cover||$tmp.jpg"

# 3. Compilation: MP3 320k, different artists, no album artist, no cover.
a="$out/Various/Analog Summer"
mp3_track "$a/01 Sunday Dials.mp3" -metadata "title=Sunday Dials" -metadata "artist=Kiko & The Dials" \
  -metadata "album=Analog Summer" -metadata track=1/2 -metadata date=2021
mp3_track "$a/02 Night Bus.mp3" -metadata "title=Night Bus" -metadata "artist=The Quiet Hours" \
  -metadata "album=Analog Summer" -metadata track=2/2 -metadata date=2021

# 4. Untagged WAV 48 kHz / 24-bit with a GBK-encoded .lrc (the builder warns about it).
a="$out/Loose Tracks"
mkdir -p "$a"
tone 48000 -c:a pcm_s24le "$a/demo take 3.wav"
printf '[00:00.50]这是一个测试\n' | iconv -f UTF-8 -t GBK > "$a/demo take 3.lrc"

# 5. Things the builder must skip.
head -c 4096 /dev/zero > "$a/._demo take 3.wav"  # macOS metadata file on FAT32
mkdir -p "$out/.Trashes"
cp "$out/Various/Analog Summer/02 Night Bus.mp3" "$out/.Trashes/deleted.mp3"
tone 44100 -c:a aac "$a/voice memo.m4a"
echo "not music" > "$out/notes.txt"

rm -f "$tmp.wav" "$tmp.jpg"
find "$out" -type f | sort
