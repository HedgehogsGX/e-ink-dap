#!/bin/sh
# Generates the decoder benchmark clips into bench_audio.nosync/ (5 s of stereo pink
# noise: close to worst case for FLAC, so real music decodes at least this fast).
# Then: pio run -e decode_bench -t uploadfs
set -e
cd "$(dirname "$0")/.."
out=bench_audio.nosync
secs=5
mkdir -p "$out"
rm -f "$out"/*

noise() {  # rate, then ffmpeg output args
  rate=$1
  shift
  ffmpeg -v error -y \
    -f lavfi -i "anoisesrc=color=pink:amplitude=0.25:sample_rate=$rate:seed=1:duration=$secs" \
    -f lavfi -i "anoisesrc=color=pink:amplitude=0.25:sample_rate=$rate:seed=2:duration=$secs" \
    -filter_complex amerge=inputs=2 -map_metadata -1 -fflags +bitexact "$@"
}

for spec in "44100 16" "48000 24" "96000 24" "192000 24"; do
  set -- $spec
  noise "$1" -c:a "pcm_s$2le" "$out/tmp.wav"
  flac -8 -s -f -o "$out/flac_$1_$2.flac" "$out/tmp.wav"
done
rm -f "$out/tmp.wav"
noise 44100 -c:a libmp3lame -b:a 320k "$out/mp3_44100_320k.mp3"

ls -l "$out"
