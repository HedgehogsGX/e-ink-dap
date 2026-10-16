# E-ink DAP (DIY ESP32-S3 Music Player) — Project Handoff

Context file for Claude Code. Compiled from several earlier claude.ai chats.
Items marked **⚠ OPEN** were left unresolved or contradicted each other across chats — settle these first.

---

## 1. What we're building

A pocket-sized portable music player (DAP) with an e-paper screen, inspired by a video of a clear-case e-ink player with synced lyrics and physical buttons.

**Design goals**
- Drive the **Moondrop Dark Saber** IEM well (22 Ω, 128 dB/Vrms — very sensitive, so *low noise/hiss* matters more than power)
- Lossless playback from microSD (≥64 GB; 128 GB card chosen)
- Outputs: **3.5 mm single-ended + 4.4 mm balanced**, plus **USB-C** (charging, data, digital audio out)
- Battery life target **20–40 h**, 4000 mAh LiPo
- Size target: **~2/3 the length of an iPhone 15 (~98 mm)**
- Touch e-paper for browsing; physical buttons for play/volume
- Budget ~¥1,300 total. Parts from Taobao / Tmall / JD; PCB + SMT from JLCPCB (嘉立创)
- Owner is a beginner in electronics, lives in Japan, buys from mainland China via 集运 (consolidated shipping)

**Two-phase plan**
1. **Phase 1 – Breadboard prototype**: dev board + modules, prove firmware (screen, SD, audio, buttons/touch).
2. **Phase 2 – Custom 4-layer PCB**: real audio chain (dual CS43131), power management, USB features, enclosure.

---

## 2. Phase 1 hardware (prototype)

| Part | Notes |
|---|---|
| ESP32-S3-DevKitC-1 **N16R8** | 16 MB flash, 8 MB **OPI** PSRAM |
| E-paper | **GDEY037T03-T02** (3.7" touch, 416×240, UC8253 driver + FT6336U touch) on the **ESP32-FTS02** adapter — confirmed 2026-10-16 from the order. See §4.1. |
| CS4398 + ES9601K I2S DAC board | Header: GND, 3V3_OUT, LRCK, BCK, DATA, **MCK**. Onboard STC MCU configures the CS4398 itself → **no I2C needed**, just send I2S. Powered from its own USB-C. Uses AMS1117 regulators → expect some hiss on Dark Saber; don't judge final sound from it. |
| microSD breakout, pass-through (9P 插针) | No level shifter, so **4-bit SDMMC** works |
| microSD 128 GB | Must be reformatted **FAT32** (ships as exFAT) |
| 606090 4000 mAh LiPo w/ NTC | Not connected during prototyping — USB power only |
| 6×6 mm tactile buttons, 10 kΩ resistors, breadboards, dupont wires | |
| Tools: 维修佬 T12 Pro Max iron, YIHUA 858D hot air, 63/37 leaded solder, 183 °C leaded paste | Multimeter was recommended if not owned |

**Dropped:** QCC5181 Bluetooth LDAC TX module — no UART control in TX mode, no 技適 certification for Japan, expensive. Revisit later.

---

## 3. Phase 2 hardware (final PCB) — planned, not yet designed

- **MCU:** ESP32-S3-WROOM-1-N16R8 module
- **Audio:** 2× **Cirrus CS43131** (DAC + built-in Class-H headphone amp) in balanced config → 4.4 mm; 3.5 mm SE
  - CS43131 needs **I2C register init sequence** before it makes sound (unlike the CS4398 board)
  - Digital I/O runs ~1.8 V vs ESP32's 3.3 V → **level shifting / VL supply must be handled**
  - MCLK from dedicated audio oscillators: **24.576 MHz** (48k family) and **22.5792 MHz** (44.1k family)
  - CS43198 + OPA1622 (like the Moonriver 2 Ti) was considered and rejected for v1: not pin-compatible, needs external amp, more power/space. Only worth it for high-impedance headphones. Possible v2.
- **Power:** BQ24075 charger (power-path), TPS63001 buck-boost 3.3 V, **LP5907** low-noise LDOs for audio, 5 V boost for powering external USB DACs
- **Storage/USB:** GL823K USB card reader (+12 MHz crystal) so the SD shows up as a drive on a PC; TS3A27518 SD bus switch; FSUSB42 USB data switch; TUSB320 USB-C role controller
- **USB audio out:** ESP32-S3 as USB host to an external DAC is limited by Full-Speed USB (~24/96); can't charge and output simultaneously on one port
- **Display:** raw Good Display panel with the reference driver circuit on our PCB (no adapter)
- **PCB:** 4-layer, JLCPCB SMT assembly (QFN CS43131 should be factory-mounted), designed in 嘉立创EDA
- **Case:** 3D printed (clear resin/PETG), M2 heat-set inserts + brass screws; Fusion 360. JLCPCB also prints.

---

## 4. ⚠ OPEN decisions / contradictions to resolve

1. ✅ **RESOLVED 2026-10-16 — 3.7" touch GDEY037T03-T02 + ESP32-FTS02** (confirmed from the Taobao order). The 4.26" is out.
   - Driver IC is **UC8253** (Good Display demo `gooddisplayshare/ESP32epdx`, `examples/2-Colors (BW)/3.7/GDEY037T03`) → set the FTS02 resistor switch to **0.47 Ω** (UC series; 2.2 Ω is for SSD panels). BUSY reads **0 = busy, 1 = idle**.
   - GxEPD2 driver class: `GxEPD2_370_GDEY037T03`. Panel is 240×416 native (portrait).
   - The FTS02 also has its own microSD slot (SPI mode). Not used — the 4-bit SDMMC breakout is faster.
   - FTS02 header silkscreen labels are not published as text (spec/schematic are PDFs behind Good Display's download page). Read them off the board before wiring.

   History: earlier chats confirmed **GDEY0426T82 + DESPI-C02** in the cart (and possibly already received). A later chat switched to **3.7" touch GDEY037T03-T02 + ESP32-FTS02 (~¥187)** to hit the 98 mm size target and get touch, and said to remove the 4.26". Check which one physically arrived.
   - 4.26": sharper, but player ends up ~110 mm+ long
   - 3.7" touch: ~98 × 62 mm player; touch controller **FT6336U** on I2C (+4 pins: SDA, SCL, INT, RST); slightly greyer image
2. **Hi-res support.** Memory/early chats said 24-bit/96 kHz, but checking the **ESP32-audioI2S** source showed it supports **16–48 kHz**. 96 kHz needs a different decoder path (e.g. own FLAC decoding via libFLAC/dr_flac + ESP-IDF I2S) or downsampling. Decide.
   - **Measured 2026-10-16 (`decode_bench`)**: dr_flac on one 240 MHz core, decoding from PSRAM, pink-noise clips (≈ worst case for FLAC, `flac -8`):

     | Format | Bitrate | CPU, one core |
     |---|---|---|
     | FLAC 44.1/16 | 1073 kbps | 6.9 % |
     | FLAC 48/24 | 1936 kbps | 9.3 % |
     | FLAC 96/24 | 3857 kbps | 18.4 % |
     | FLAC 192/24 | 7701 kbps | 36.8 % |
     | MP3 320k (dr_mp3) | 324 kbps | 10.9 % |

     CPU is not the limit for 96k or even 192k. The ESP32-S3 I2S also produces exact 88.2/96 kHz clocks (`i2s_clocks`).
   - ESP32-audioI2S 4.0.0 (current) resamples everything to a fixed 44.1 or 48 kHz output (not bit-perfect) and is **GPL-3.0**. Fine for the DAC bring-up test, a poor fit for the final player.
   - Still to decide: own dr_flac/dr_mp3 engine (public domain / MIT-0) with native sample rates, and the top rate to support.
3. ✅ **RESOLVED 2026-10-16 — pin map frozen in `include/pins.h`** (touch layout, based on Map A). Board is **DevKitC-1 v1.1**: RGB LED on GPIO38, so GPIO48 is touch RST. Original note: two chats gave *different* GPIO maps (see §5). Also the DevKitC-1's onboard RGB LED is on **GPIO38 (v1.1)** or **GPIO48 (v1.0)** — check the board revision.
4. **What has been tested?** Bare-board results, 2026-10-16 (nothing wired):

   | Test (`pio` env) | Result |
   |---|---|
   | `selftest` | PASS. ESP32-S3 rev v0.2, 16 MB flash, 8 MB OPI PSRAM (4 MB pattern test clean). All 25 planned pins free, no faults. LED lit red on GPIO38 → board v1.1 (`DEVKITC_REV 11`). |
   | `i2s_clocks` | PASS. MCK 256 fs / BCK 64 fs / LRCK within a few ppm at 44.1, 48, 88.2, 96 kHz. |
   | `decode_bench` | See §4.2. |
   | `player` | PASS. Two-core skeleton: play/pause, volume, next/prev, auto-advance, 44.1→48→96 kHz switching, 0 underruns with the control core blocked 1.5 s per simulated full refresh. `stall 200` produces underruns, so the counter works. |
   | `bringup_sd`, `bringup_touch` | Fail cleanly with wiring hints when nothing is attached (expected). |
   | `bringup_epd`, `bringup_dac`, `bringup_buttons` | Built, not run (need the parts). |

   Note: the ESP32-S3 has no audio PLL, so MCLK comes from a fractional divider. The average rate is exact, but jitter was not measured — one more reason not to judge final sound on the prototype.

---

## 5. Pin maps (ESP32-S3-DevKitC-1 N16R8)

> **Superseded by `include/pins.h`** (2026-10-16), the only authoritative pin map. The maps below are kept as history.

**Never use:** GPIO 0, 3, 45, 46 (strapping), 19–20 (USB), 26–32 (flash), 33–37 (OPI PSRAM), 43–44 (UART0), plus whichever of 38/48 drives the RGB LED.

### Map A — most recent (English chat), recommended baseline

| Function | GPIO |
|---|---|
| EPD SDI (MOSI) / SCK / CS / DC / RES / BUSY | 11 / 12 / 10 / 9 / 8 / 13 |
| SD CLK / CMD / D0 / D1 / D2 / D3 | 14 / 15 / 16 / 17 / 18 / 21 |
| I2S MCK / BCK / LRCK / DATA | 1 / 2 / 4 / 5 |
| Buttons Play / Prev / Next / Vol+ / Vol− | 38 / 39 / 40 / 41 / 42 |
| (was Bluetooth UART TX/RX — now free) | 6 / 7 |
| Spare | 47, 48 |

SD: 10 kΩ pull-ups to 3.3 V on CMD, D0–D3 (not CLK). Short (10 cm) wires.
Buttons: one leg to GPIO, other to GND, `INPUT_PULLUP`.
DAC board: **GND must be shared** with ESP32; leave 3V3_OUT unconnected.

### Map B — earlier Chinese assembly guide (differs!)
EPD BUSY=7; SD D3=13; I2S MCLK=21, BCLK=4, LRCK=5, DIN=6; buttons 39/40/41/42/47. Avoids GPIO38/48 for the LED.

### If using the touch screen (proposal — verify before wiring)
Touch chat recommended only 4 physical buttons (play/pause, vol+, vol−, lock) with touch for browsing. On top of Map A: touch SDA=6, SCL=7, INT=47, RST=one freed button pin. Confirm the FTS02 adapter's pinout first.

---

## 6. Firmware

**Toolchain (decided 2026-10-16):** PlatformIO with the community **pioarduino** platform `55.03.312-1` (Arduino core 3.3.12 on ESP-IDF 5.5.5); the official PlatformIO platform lags on Arduino 3.x. Board settings live in `platformio.ini` (16 MB flash, OPI PSRAM). Build output goes to `.pio.nosync/` so iCloud doesn't sync it.

**Uploading and serial** — the board is used on its native **USB** port (not "UART"); `Serial` goes over that port.
- `pio run -e <env> -t upload`, then `pio device monitor`. Uploads end with a watchdog reset because an RTS reset on this port drops into download mode (`waiting for download`).
- Boot output is printed before the monitor opens. Each test re-prints on its own or when you type `r`; the player takes `h` for help.
- Envs: `selftest`, `i2s_clocks`, `decode_bench` (first run `tools/make_bench_clips.sh`, then `-t uploadfs`), `player`, and `bringup_epd` / `bringup_sd` / `bringup_dac` / `bringup_buttons` / `bringup_touch`.

Original plan, for reference: Arduino IDE with `ESP32S3 Dev Module`, Flash **16 MB**, PSRAM **OPI PSRAM** (wrong setting → boot loops), upload via the UART USB-C port.

**Libraries**
- **GxEPD2** — e-paper (partial refresh, 4-level grayscale)
- **SD_MMC** with `SD_MMC.setPins()` — 4-bit mode
- **ESP32-audioI2S** — MP3/FLAC/WAV decode → I2S (16–48 kHz; **MCLK output must be enabled** for the CS4398). DAC bring-up only, see §4.2
- **dr_flac / dr_mp3** (dr_libs, public domain) — candidate decoders for the player's own engine, benchmarked in §4.2
- FT6336U touch driver (if touch screen)
- Later: own CS43131 I2C init driver

**Bring-up order (one subsystem at a time, don't move on until it works)**
1. ESP32 alone: blink / serial "hello"
2. Screen: "Hello" via GxEPD2 (check C02 adapter's resistor switch per Good Display docs for this panel)
3. SD: list files from FAT32 card
4. DAC: WAV → MP3 → FLAC. Low volume, IEMs **not in ears** on first test
5. Buttons / touch
6. Merge into one player

**Architecture notes from earlier chats**
- Split cores: **audio decode on one core, UI/e-ink on the other** — a full e-ink refresh can block SPI for hundreds of ms.
- Build a **library index file** on the SD (title/artist/album/path) instead of scanning thousands of files on every boot.
- `.lrc` parser for synced lyrics; pre-convert album art on the PC into small dithered 4-gray bitmaps.
- Use partial refresh for progress bar/lyrics; periodic full refresh to clear ghosting.

---

## 7. Reference projects

- **御坂晓岚** on 立创开源平台 (oshwhub.com) — ESP32 lossless player, CS4398 + MAX97220, classic ESP32 (for BT). **GPL-3.0** — copying code makes this project GPL too.
- **孟子**'s build — Waveshare ESP32-S3 e-paper board + **CrossMux** e-reader firmware (by 搬砖喵); case STL free on MakerWorld. Good reference for case design and e-ink UI/partial refresh; *not* for audio (uses PCM5102A, poor match for 22 Ω IEMs).

---

## 8. Logistics notes (Japan)

- Ask the 集运 service whether it accepts batteries (带电渠道)
- Bluetooth/Wi-Fi modules need **技適** for legal use in Japan (ESP32-S3 dev boards/modules generally carry it; check)
- Soldering stations bought for 220 V — confirm they work on Japan's 100 V
- Owner also has: Moondrop Moonriver 2 Ti dongle (dual CS43198 + OPA1622) — good as a reference / external USB DAC, don't cannibalize it

---

## 9. Suggested first tasks in Claude Code

1. Confirm which screen arrived and the DevKitC-1 revision → freeze the pin map in `include/pins.h`
2. Set up a PlatformIO project with the board/PSRAM settings above
3. Write the 5 bring-up test sketches (§6), one per subsystem
4. Decide the 48 kHz vs 96 kHz question before writing the playback engine
