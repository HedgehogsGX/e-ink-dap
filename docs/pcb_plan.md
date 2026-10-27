# Player board (Phase 2) — plan

Stage 1 of the board design: what is on the board, how power flows, which ESP32 pin does
what, and which parts JLCPCB can assemble. Drafted and approved 2026-10-26. Stock and prices
are from JLCPCB's parts library on 2026-10-25.

**Stage 2, the schematic, is drawn (2026-10-26):** see [Schematic](#schematic-stage-2) at the
end. It follows this plan with the changes listed there.

**Stage 3 under way (2026-10-27): every part is placed and every net routed except 28
connections, mostly around the two DACs; DRC clean.** See
[Placement draft](#placement-draft-stage-3) and [Routing](#routing-stage-3) at the end.
Stage 4 files exist as a **draft, not ready to order**: see
[JLCPCB files](#jlcpcb-files-stage-4-draft).

One board, 4 layers, assembled by JLCPCB on **one side** (the side facing the screen), so it
stays in their cheaper "Economic" assembly. Its outline comes from the case model
(`tools/make_case.py`): about 60.8 × 105.8 mm, with notches for the jacks, USB-C and the two
screw bosses.

## What changed from PROJECT.md §3

- **Charger BQ24075 → BQ24073.** Same chip family and footprint, but the BQ24073 holds its
  output at 4.4 V when USB is plugged in. The BQ24075 lets it rise to 5.5 V, above the
  CS43131's 5.25 V limit on VP. The BQ24073 has no SYSOFF pin, so "off" is a deep sleep of
  the ESP32 with the audio and other rails switched off (roughly 0.1–0.2 mA; the battery's
  own self-discharge matters more).
- **The CS43131s make the audio clocks, not the ESP32.** The 24.576 / 22.5792 MHz
  oscillators feed both DACs directly; the left DAC is the I2S clock master and the ESP32
  receives its bit and word clocks (I2S slave). The ESP32's MCLK pin is no longer used.
  The firmware's I2S code changes to slave mode.
- **Two keys move pins:** Power must be on a pin that can wake the ESP32 from deep sleep
  (GPIO 0–21), and the ESP32 has no free pins otherwise. See the pin map.

## Block diagram

```mermaid
flowchart LR
  USB["USB-C"] -- CC --> TUSB["TUSB320L<br/>USB-C role"]
  USB -- "D+ / D−" --> USW["FSUSB42<br/>USB switch"]
  USW --> ESP["ESP32-S3-WROOM-1<br/>N16R8"]
  USW --> GL["GL823K<br/>card reader"]
  GL --> SDSW["TS3A27518E<br/>SD switch"]
  ESP -- "SD, 4-bit" --> SDSW
  SDSW --> SD["microSD"]
  ESP -- SPI --> EPD["3.7&quot; e-paper<br/>24-pin FPC + booster"]
  ESP -- "I2C 3.3 V" --> TP["touch FT6336U<br/>6-pin FPC"]
  ESP -- "I2C 3.3 V" --> TUSB
  ESP -- "I2C" --> I2CLS["PCA9306<br/>3.3 ↔ 1.8 V"]
  I2CLS -- "I2C 1.8 V" --> DACL["CS43131 L<br/>clock master"]
  I2CLS -- "I2C 1.8 V" --> DACR["CS43131 R"]
  ESP <-->|I2S| LS["SN74AVC4T774<br/>3.3 ↔ 1.8 V"]
  LS <--> DACL
  LS --> DACR
  OSC["24.576 + 22.5792 MHz<br/>oscillators"] -- MCLK --> DACL
  OSC -- MCLK --> DACR
  DACL -- "L+ / L−" --> J44["4.4 mm balanced"]
  DACR -- "R+ / R−" --> J44
  DACL -- "L" --> J35["3.5 mm"]
  DACR -- "R" --> J35
  KEYS["4 side keys"] --> ESP
```

- **Audio:** the two CS43131s run in mono (differential) mode, Cirrus's documented way to
  make a balanced stereo output from two chips (datasheet §4.2.3). The left chip drives L+
  and L−, the right chip R+ and R−. The 4.4 mm jack takes all four (Pentaconn order: tip L+,
  ring 1 L−, ring 2 R+, ring 3 R−, sleeve ground). The 3.5 mm jack takes only L+ and R+, so
  single-ended output is 6 dB lower, which suits the sensitive Dark Sabers anyway. Each
  jack's detect contact goes to one CS43131's HP_DETECT pin, read over I2C.
- **Clocks:** one oscillator runs at a time (24.576 MHz for 48/96/192 kHz music,
  22.5792 MHz for 44.1/88.2/176.4 kHz), chosen by OSC_SEL. Both outputs share the MCLK net.
- **Level shifting:** the CS43131's digital pins run at 1.8 V and the ESP32's at 3.3 V.
  SN74AVC4T774 (the part on Cirrus's own evaluation board) carries SCLK and LRCK to the
  ESP32 and SDIN and OSC_SEL to the 1.8 V side. PCA9306 joins the two I2C buses. RESET
  and INT sit in the CS43131's VP domain (3.0–4.4 V here), so they take 3.3 V directly.
- **USB:** normally USB goes to the ESP32 (firmware updates, serial log, and later USB
  audio out). In "USB disk" mode, USB_DISK flips both switches: the PC sees the microSD
  through the GL823K at full USB 2.0 speed while the ESP32 lets go of the card.
- **Screen:** the panel connects straight to the board through Good Display's reference
  booster circuit (what the FTS02 does now), with the 0.47 Ω sense resistor for its UC8253.

## Power tree

```mermaid
flowchart TD
  VBUS["USB-C VBUS 5 V"] --> CHG["BQ24073 charger + power path<br/>input ≤ 1.0 A, charge 0.8 A"]
  BAT["606090 battery<br/>3.0–4.2 V, 10 kΩ NTC"] <--> CHG
  CHG --> SYS["SYS 3.0–4.4 V"]
  SYS --> BB["TPS63001 buck-boost<br/>3V3, about 1 A"]
  SYS --> LDOA["LP5907 → 1V8_A<br/>VA ×2"]
  SYS --> LDOC["LP5907 → 1V8_CP<br/>VCP ×2"]
  SYS --> LDOD["LP5907 → 1V8_D<br/>VD, VL ×2, oscillators"]
  SYS --> VP["filter → VP ×2<br/>Class H rail"]
  SYS -.-> BST["TPS61023 boost 5 V<br/>(optional, USB host)"]
  BST -.-> LSW["TPS2553 500 mA limit"] -.-> VBUS
  BB --> L33["ESP32, screen, touch, microSD,<br/>switches, level shifters"]
  VBUS --> GLP["GL823K (own 3.3 V)<br/>powered whenever USB is plugged in"]
```

| Rail | From | Feeds | Switched by |
|---|---|---|---|
| SYS 3.0–4.4 V | BQ24073 OUT (battery, or USB when plugged in) | everything below | — |
| 3V3 | TPS63001 | ESP32, e-paper, touch, microSD card, TUSB320L, FSUSB42, TS3A27518E, 3.3 V side of the level shifters | always on |
| 1V8_A | LP5907 | VA of both CS43131 (the quietest rail) | AUDIO_EN |
| 1V8_CP | LP5907 | VCP (Class H charge pump) of both CS43131: Cirrus asks for VA and VCP on separate clean supplies | AUDIO_EN |
| 1V8_D | LP5907 | VD, VL of both CS43131, oscillators, inverter, 1.8 V side of the level shifters | AUDIO_EN |
| VP | SYS through a ferrite bead | Class H supply of both CS43131 (3.0–5.25 V allowed) | — (DACs held in reset) |
| 5 V out | TPS61023 + TPS2553 | VBUS when the player powers a USB DAC | BOOST_EN |

- **Charger settings:** input limit 1.0 A (R_ILIM = 1610 / 1.0 ≈ 1.6 kΩ), charge current 0.8 A
  (R_ISET = 890 / 0.8 ≈ 1.1 kΩ): a full charge takes about 5–6 hours. It's a linear charger
  in a closed case, so more current means more heat (about 1 W at 0.8 A).
- **When the player powers a USB DAC,** BOOST_EN also puts the charger in standby (EN1 high,
  EN2 tied high), so it doesn't try to charge from its own 5 V. The 5 V boost and its
  switch are optional: leave them unassembled to save cost; the rest works without them.
- **Battery life, rough:** 60–150 mA while playing (ESP32 mostly idle between buffer fills,
  Wi-Fi off) → about 25–60 hours from 4000 mAh. Measured numbers come with the prototype.

## Pin map (ESP32-S3-WROOM-1-N16R8)

Changes from the prototype (`include/pins.h`) are in bold. `pins.h` gets a board variant
when the firmware moves to this board; until then the prototype map stays.

| GPIO | Use | Notes |
|---|---|---|
| 0 | **Play key** | was 39. Boot-strap pin: holding Play while plugging in starts the firmware download mode, handy for recovery. |
| 1 | **Power key** | was 42. Can wake the ESP32 from deep sleep ("off"). |
| 2 | I2S SCLK in | from the left CS43131 via the level shifter |
| 3 | **Battery voltage** | 1 MΩ / 1 MΩ divider from BAT (ADC1) |
| 4 | I2S LRCK in | from the left CS43131 via the level shifter |
| 5 | I2S data out | to both CS43131 SDIN via the level shifter |
| 6 / 7 | I2C SDA / SCL, 3.3 V | touch (0x38), TUSB320L, PCA9306 → both CS43131 (addresses set by ADR resistors) |
| 8 – 13 | e-paper RST, DC, CS, MOSI, SCK, BUSY | same as the prototype |
| 14 – 18, 21 | microSD CLK, CMD, D0–D3 | same as the prototype, now through the SD switch |
| 19 / 20 | USB D− / D+ | through the USB switch |
| 38 | **USB_DISK** | high = microSD and USB go to the card reader |
| 39 | **DAC_RST** | both CS43131 RESET (low = reset, also the default while the ESP32 boots) |
| 40 / 41 | Vol+ / Vol− keys | same as the prototype |
| 42 | **OSC_SEL** | low = 22.5792 MHz, high = 24.576 MHz |
| 43 | debug serial TX | test pad only |
| 44 | **CHG** | charger status, also lights a small charge LED |
| 45 | **BOOST_EN** | 5 V out for a USB DAC. Pulled down: this pin must be low at boot. |
| 46 | **AUDIO_EN** | the two 1.8 V audio rails. Pulled down at boot. |
| 47 / 48 | touch INT / RST | same as the prototype |

All 33 usable pins are taken. The CS43131 and TUSB320L interrupt lines aren't wired: the
firmware polls them over I2C (headphone plugged in, USB attached). The MCLK pin (GPIO 1 on
the prototype) is reused for the Power key.

## Parts list

| Function | Part | JLCPCB no. | Stock | Each | Notes |
|---|---|---|---|---|---|
| MCU + flash + PSRAM + Wi-Fi/BT | ESP32-S3-WROOM-1-N16R8 | C2913202 | 27,240 | $5.35 | |
| DAC + headphone amp ×2 | CS43131-CNZR (QFN-40) | C965907 | 13 | $5.60 | ~8,500 more at LCSC's partner stock, 3–5 days. Order early. |
| 22.5792 MHz oscillator | SX3M22.5792M20F30TNN | C2901572 | 861 | $0.33 | 1.62–3.63 V, 3.2 × 2.5 mm |
| 24.576 MHz oscillator | SX3M24.576M20F30TNN | C2901574 | 1,749 | $0.48 | same series |
| I2S level shifter | SN74AVC4T774PWR | C129363 | 11,891 | $0.77 | |
| I2C level shifter | PCA9306DCUR | C33196 | 7,857 | $0.67 | |
| Charger + power path | BQ24073RGTR | C15220 | 30,204 | $0.88 | |
| 3.3 V buck-boost | TPS63001DRCR | C28060 | 9,131 | $1.61 | |
| 1.8 V low-noise LDO ×3 | LP5907MFX-1.8/NOPB | C92498 | 28,755 | $0.19 | |
| Oscillator select inverter | 74LVC1G04DBVR | C33962550 | 3,329 | $0.06 | runs at 1.8 V |
| USB ESD protection | USBLC6-2SC6 | C7519 | 40,920 | $0.18 | |
| E-paper booster MOSFET | SI1308EDL-T1-GE3 | C469327 | 38,173 | $0.27 | the part Good Display names |
| E-paper booster diodes ×3 | MBR0530 | C77336 | 53,880 | $0.04 | |
| USB-C role controller | TUSB320LIRWBR | C2836598 | 5,673 | $0.79 | |
| USB 2.0 switch | FSUSB42MUX | C11355 | 30,950 | $0.30 | |
| microSD bus switch | TS3A27518EPWR | C443721 | 4,382 | $0.93 | |
| USB card reader | GL823K-HCY04 | C284879 | 115,985 | $0.49 | makes its own clock, no crystal |
| 5 V boost (optional) | TPS61023DRLR | C919459 | 9,169 | $0.24 | |
| 5 V current-limit switch (optional) | TPS2553DBVR | C55266 | 49,565 | $0.54 | |
| microSD socket, push-push | TF-01A (Hroparts) | C91145 | 172,459 | $0.19 | |
| E-paper connector, 24-pin 0.5 mm | AFC07-S24FCA-00 | C262567 | 47,608 | $0.13 | bottom contact; KiCad has its footprint. Contact side to confirm against how the ribbon folds |
| Touch connector, 6-pin 0.5 mm | AFC07-S06FCA-00 | C262553 | 31,892 | $0.11 | same |
| Side keys ×4 | Alps SKRTLAE010, side-push 4.5 × 3.4 × 3.3 mm | C110293 | 43,836 | $0.14 | |
| 3.5 mm jack | PJ-342 (SHOU HAN) | C668606 | 73,200 | $0.18 | 4-pole (TRRS), 4.5 mm tall; detect contact to check in its drawing |
| Battery connector | ~~JST PH 3-pin, right angle (S3B-PH-SM4-TB)~~ → 3 solder pads on the back | — | — | — | Changed in the placement draft: the JST PH is too tall for the 3.3 mm gap under the screen and has no room beside the jacks |
| **4.4 mm jack** | **not in JLCPCB's library** | — | — | — | Buy on Taobao (4.4mm 平衡母座) and hand-solder; I need its drawing for the footprint. |
| **USB-C, 16-pin** | TYPE-C-31-M-12 (top mount) | C165948 | 324,076 | $0.19 | The case assumes a **mid-mount** one, which I couldn't find in stock. A top-mount one works if the hole in the case moves up ~3 mm. |
| E-paper booster | Good Display reference circuit | — | — | — | inductor, N-MOSFET, 3 Schottky diodes, 0.47 Ω, ~10 × 1 µF/25 V; values from the panel's spec in stage 2 |
| Resistors, capacitors, ferrites | ~100, mostly JLCPCB Basic parts | — | — | — | |

About 25 different Extended parts: at JLCPCB's current $1.50–3 loading fee each, that's
roughly $40–75 per order on top of the parts, board and assembly.

## Board layout idea (stage 3)

- **Top edge (audio corner):** jacks, USB-C, both CS43131s, oscillators and the 1.8 V LDOs,
  with short output traces to the jacks. No switching regulator near here.
- **Middle:** ESP32 module, I2C/I2S level shifters. **Lower right:** charger, buck-boost and
  the optional 5 V boost. **Bottom:** the screen and touch connectors (the ribbons fold back
  at the panel's bottom edge), microSD socket, card reader and SD switch.
- **Layers** (changed 2026-10-26, see Routing): 1 parts and signals (facing the screen),
  2 and 3 solid ground, 4 signals and a 3.3 V fill under the battery side. Power runs as
  wide tracks.
- **Height limit:** parts on the board must stay under 3.3 mm, the gap to the screen. The
  ESP32 module (3.1 mm) and the side switches (3.3 mm) are at the limit. The case script
  will check every part with its real height in stage 3.

## Open items

1. **4.4 mm jack:** pick one (Taobao), send me the listing or its drawing.
2. **USB-C:** a top-mount port is fine if the case hole moves; or find a mid-mount one.
3. **Battery plug:** what connector does the 606090 have (a photo is enough)? 3 wires means
   + , − and the NTC. The placement draft solders the wires to pads instead (see
   below); a connector needs one under 3.3 mm tall (JST SH, 2.9 mm) and a wire slot.
4. **Optional 5 V output** (power a USB DAC from the player): keep it on the board, or
   leave it out?
5. **Wi-Fi/Bluetooth range will be poor:** the battery's foil sits right under the module's
   antenna. Fine if wireless is only for occasional use; otherwise use the WROOM-1U module
   with a small stick-on antenna.
6. Settled in stage 2: the e-paper booster values (Good Display's reference circuit), the
   headphone-detect wiring (below) and the GL823K power (straight from VBUS, no switch).
   Still unconfirmed: the CS43131 RESET input threshold (the datasheet gives none; it is
   driven at 3.3 V, inside its VP-domain limit).

## Schematic (stage 2)

Drawn 2026-10-26 in `hardware/` (KiCad 10): open `hardware/dap.kicad_pro`, or read
`hardware/dap_schematic.pdf`. Six pages: the top sheet, then Power, MCU, Display, USB and
storage, Audio. 158 parts, 126 nets.

The sheets are generated by `tools/make_schematic.py` from one table of parts and
connections, so edit that and re-run (`python3 tools/make_schematic.py`) rather than
editing the sheets in KiCad; a re-run overwrites them. Each run also checks itself:

- KiCad's electrical rules check (ERC): 0 errors, 0 warnings.
- KiCad's own netlist is read back and compared with the table: every intended net is
  exactly one KiCad net, none split, none merged. A deliberately broken label is caught,
  which ERC alone misses.

**Changes from the plan above, made while drawing:**
- **Third 1.8 V LDO** for VCP: Cirrus asks for VA and VCP on independent clean supplies.
- **No 12 MHz crystal:** the GL823K makes its own clock. It runs from VBUS whenever USB is
  plugged in (about 45 mA from the PC), so it needs no power switch.
- **Charger EN2 tied to SYS,** not 3.3 V: otherwise a flat battery would start the charger in
  its 100 mA mode, which may not be enough to boot the player.
- **USB ESD protection** (USBLC6-2SC6) on D+/D− and VBUS.

**How the main circuits are wired** (all on the sheets):
- CS43131: every capacitor from Cirrus's typical connection diagram (FILT+ 15 µF to VA,
  FILT− 15 µF to −VA, 2.2 µF flying and filter caps, VP 0.1 + 4.7 µF), mono mode, the left
  chip at I2C address bits 00 (ADR to ground), the right chip at 01 (4.99 kΩ to ground).
  HPREFA/B go to the jack ground net HP_GND, which meets GND through a net tie at the jacks
  so it can be routed on its own.
- Headphone detect: each jack's detect contact goes to one CS43131's HP_DETECT (3.5 mm to the
  left chip, 4.4 mm to the right). The pin reads low when the contact touches a plug's tip,
  as Cirrus describes.
- Touch connector pins from Good Display's TP037-S02 drawing: 1 GND, 2 VDD, 3 RST, 4 INT,
  5 SDA, 6 SCL.
- E-paper: Good Display's reference circuit (10 µH, Si1308EDL, three MBR0530, 0.47 Ω
  sense, 1 µF/50 V on every rail).
- TUSB320L: dual role (PORT open), I2C address 0x47, 887 kΩ to VBUS_DET. It shows a 5.1 kΩ
  pull-down even unpowered, so a USB-C charger still turns on with a flat battery.

**To check in stage 3 (layout), with each part's drawing:**
- Footprints for the two jacks (custom), the microSD socket and 6-pin FPC (stand-ins now),
  and which side the 24-pin FPC contacts face once the panel ribbon is folded.
- The jacks' detect contact: it must touch the tip when a plug is in. The 4.4 mm jack isn't
  chosen yet.
- Oscillator OE polarity (assumed high = running) and that its output goes high-impedance
  when off, since the two outputs share MCLK.
- GL823K VDD and VDDA are tied together as its internal 3.3 V; check against a Genesys
  reference design.
- 15 µF capacitors in 0805: not found under the first part number tried; pick one or use 22 µF.

## Placement draft (stage 3)

Placed 2026-10-26 in `hardware/dap.kicad_pcb`: all 158 parts on a 4-layer, 1.2 mm board
cut to the case's outline (60.8 × 105.8 mm, jack notches, screw-boss corners). Routing is
under way, see the next section. Renders: `hardware/renders/pcb_top.png`, `pcb_angle.png`, `pcb_bottom.png`;
in KiCad, open the board and press Alt+3 (View → 3D Viewer) to turn it around.

Made by `tools/make_pcb.py` from the schematic's netlist, so run it after
`make_schematic.py` (it needs KiCad's own Python, see the script's first lines). Big parts
sit where its PLACE table puts them, following the layout idea above; each group's small
parts are packed as close as they fit to the pins they connect to. It also writes the
stand-in footprints (`hardware/dap.pretty`), simple 3D models for parts KiCad has none
for (`hardware/3d`), and JLCPCB's 4-layer limits as design rules (`hardware/dap.kicad_dru`).
DRC: no clearance, courtyard or edge problems, apart from the connections not routed yet
and KiCad's own footprint for the side keys (its peg sits close to its pads).

**Decisions made while placing (change them if you disagree):**
- **ESP32 antenna at the left edge,** module centre 8 mm below the board's middle. The
  footprint asks for no copper and no parts in a 6 × 48 mm strip beside the antenna; the
  strip ends just under the Vol− key.
- **USB-C top-mount** (the part in the list), at the top edge with no notch. The case's
  USB-C hole has to move up about 3 mm (open item 2).
- **Battery wires solder to three pads** (+, −, NTC) on the back, between the 3.5 mm jack
  and USB-C, right above the battery's end. The JST PH plug didn't fit anywhere (open
  item 3).

**Stand-ins to replace once the parts are chosen:** both jacks (boxes from the case
estimate, mid-mount in their notches), the microSD socket (Hirose DM3D footprint), the
6-pin touch connector (Hirose FH12), and box models for USB-C, side keys and the 24-pin FPC.
The real FPC positions also depend on where the panel's and touch film's ribbons come out.

## Routing (stage 3)

Started 2026-10-26. `tools/make_pcb.py` routes in two steps, both part of the same script, so
everything is redone whenever the schematic or the placement changes (a full run takes
about 50 minutes):

1. **Its own small router** (`tools/pcb_router.py`) for ground, the short local nets (a chip
   and its capacitors, feedback dividers: pins within 8 mm), then USB, audio and power, in
   that order: 45° tracks on the top and bottom layers, through vias 0.5/0.3 mm, clearances
   checked on a 0.025 mm grid. A connection it can't make gets up to three rounds of
   rip-up and reroute (the nets routed within 2 mm of the stuck pins are taken up, the stuck
   one goes first). Strips above and below each CS43131 are reserved channels: only its
   headphone nets above, only its I2S, clock and I2C below.
2. **Freerouting** (2.5.0, the Java version: `tools/freerouting.nosync/freerouting-2.5.0.jar`,
   downloaded from its GitHub release and checked against the published SHA-256, run with
   its usage statistics off; not in git) for everything still unrouted: all tracks so far
   are locked and handed over as fixed wiring, the inner layers as ground planes, and its
   session is read back in. Then a clean-up: its neck-downs below 0.1 mm are widened to
   0.1 mm, and dead-end tracks and vias (KiCad's own connectivity check) are removed. Without
   the jar the script skips this step and leaves those nets unrouted.

- **Ground:** solid planes on layers 2 and 3 under the whole board (none under the ESP32's
  antenna). Every ground pin reaches them: a via beside the pin, vias inside the exposed
  pads (4 under the charger), and the CS43131's ground pins tied into their own centre pad.
- **USB, routed first** (the socket's pins leave no room to spare): D+/D− from the socket
  through the ESD chip to the USB switch as a pair, 0.2 mm tracks 0.2 mm apart (about
  90 Ω; check with JLCPCB's impedance calculator for the chosen stackup), then on to the
  card reader and the ESP32. The socket's two D− pins straddle a D+ pin, so they are
  joined on the bottom layer. CC1/CC2 to the TUSB320L. Pair lengths: 69/74 mm to the switch
  (5 mm apart: more than USB 2.0 guides like, to be matched by hand), 20/18 mm to the card
  reader.
- **Audio:** master clock (kept 0.2 mm from other nets), the four headphone outputs
  (0.3 mm wide where there is room), headphone ground (0.5 mm) to both jacks and the net
  tie, jack detect, I2S on both sides of the level shifter, oscillator select.
- **Power** (after the signals): the switching nodes of the buck-boost, the 5 V boost and
  the e-paper booster first, kept short; then each rail from its source as a tree of wide
  tracks: VBAT, SYS and VBUS 0.4–0.8 mm, 5 V 0.4–0.6 mm, 3.3 V and VP 0.3–0.5 mm, the 1.8 V
  rails 0.25–0.4 mm. Tracks narrow to 0.15 mm only where they leave a fine-pitch pin. On top
  of its tracks, 3.3 V fills the free area of the bottom layer (about 5,100 mm²).
- **Control and data lines** (I2C, keys, enable and reset lines, e-paper, microSD, charger
  settings, battery sense): Freerouting, 0.15 mm tracks.
- **Check (2026-10-27):** KiCad's DRC finds no clearance, width, edge or dangling-track
  problems. **28 connections are still unrouted:** around the DACs the charge-pump
  capacitors (9: DACL/DACR FLYP/FLYC/FLYN_VCP, DACR_VCPF_P), MCLK (2), OUT_LN (1), HP_GND (1),
  OSC_SEL_N (1); control lines I2C_SCL/SDA (3 + 3), BOOST_EN (3), KEY_VOLUP (3), DAC_RST
  (2), CHG_N (1). Freerouting routed VP's last pieces 0.11 mm wide (short, about 0.01 Ω;
  widen when finishing).

**Placement changes made for routing:** the CS43131s are turned 180° so their outputs face
the jacks, strips above and below them are kept free of small parts, the stand-in
jacks have most pins in a row behind the jack (where the DAC tracks arrive), and the
battery pads moved 2 mm towards the top edge to leave room for a ground via. Later the
same day: small parts keep 0.8 mm beyond the outline of every chip with 0.5 mm pitch or
finer (room for the tracks fanning out of its pins), each two-pad part is turned so its
pads face the pins of their own nets, and a strip in front of the e-paper connector's
signal pins (9-14) is kept free.

**Decided 2026-10-26: layer 3 is a second ground plane.** The long USB pair runs on the
bottom layer, and high-speed USB needs ground on the layer next to it; the plan had layer 3
for power. Power runs as wide tracks and the bottom layer's 3.3 V fill instead.

**Next:** finish the 28 connections. The DAC areas are the hard part: each CS43131 needs
14 capacitors and all its pins on two routing layers. Options: give each DAC more room
(move parts apart), finish them by hand in KiCad, or a 6-layer board with two more
routing layers (costs more at JLCPCB). Then match the USB pair's lengths.

## Case with the real board

`tools/make_pcb.py` also writes the board as a 3D model, `case/pcb.glb` (not in git: 27 MB,
rebuilt each run). `tools/make_case.py` puts it into the case in place of the stand-in boxes
(`-- --dummy-board` brings the boxes back), checks it and renders `case/renders/inside.png`
(the board through the clear shell, panel taken out) besides the other views.

- **Height check:** no part of the board reaches into the panel's layer (the 3.3 mm gap).
- **USB-C hole:** the board uses the top-mount USB-C from the parts list, about 3 mm higher
  than the case's hole (made for a mid-mount one), so the top-edge render shows an empty
  hole. Move the hole up in the case script, or find a mid-mount USB-C (open item 2).

## JLCPCB files (stage 4, draft)

`python3 tools/make_jlc.py` writes `hardware/jlcpcb/`: Gerbers and drill files in one zip,
the BOM (`dap-bom.csv`, JLCPCB's columns) and the placement file (`dap-cpl.csv`), plus
`readiness.txt`, which lists what still blocks ordering and the order settings. While
anything blocks it, the zip is named `dap-gerbers-DRAFT.zip`.

- **Order settings:** 4 layers, 1.2 mm, 60.8 × 105.8 mm; **ENIG** finish (flat pads for the
  0.4 mm-pitch QFNs; HASL is too uneven for them); impedance control with a JLCPCB 4-layer
  1.2 mm stackup for the USB pair; tracks/gaps 0.1 mm; vias 0.5/0.3 mm, tented; parts on
  the top side only.
- **Not assembled by JLCPCB:** the 4.4 mm jack (hand-soldered), the battery wires, the
  test pads and the net tie.
- **Blocks ordering (2026-10-27):** the 28 unrouted connections; stand-in footprints for
  J3 (touch FPC: Hirose outline, the part is an AFC07-S06), J5 (microSD: Hirose outline, the
  part is a TF-01A), J6 and J7 (jacks); 120 resistors and capacitors without LCSC part
  numbers; and the datasheet checks listed under Schematic (oscillator enable, GL823K supply
  pins, 15 µF capacitors, jack detect contacts).
- In JLCPCB's placement preview, check each part's rotation: some library parts are drawn
  turned 90° or 180° from KiCad's footprints.
