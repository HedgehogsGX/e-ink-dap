// Phase 1 prototype pin map — the only place GPIO numbers are defined.
//
// Board:   ESP32-S3-DevKitC-1 N16R8 (WROOM-1, quad flash + octal PSRAM, 3.3 V I/O)
// Screen:  GDEY037T03-T02 (UC8253 + FT6336U touch) on ESP32-FTS02, switch at 0.47 Ω
// Audio:   CS4398 I2S DAC board (self-configuring, no I2C)
// Storage: pass-through microSD breakout, 4-bit SDMMC
//
// Never used: 0, 3, 45, 46 (strapping), 19-20 (USB), 26-32 (flash),
// 33-37 (octal PSRAM), 43-44 (UART0 / upload port), and the RGB LED pin.
#pragma once

// Which of GPIO38/48 drives the onboard RGB LED depends on the board revision.
// 0  = not confirmed yet: the blink test toggles both so you can see which one lights.
// 10 = v1.0 (LED on 48), 11 = v1.1 (LED on 38).
// This board: v1.1, confirmed 2026-10-16 (selftest LED lit red on GPIO38).
#ifndef DEVKITC_REV
#define DEVKITC_REV 11
#endif

#if DEVKITC_REV == 11
constexpr int PIN_BOARD_LED = 38;
constexpr int PIN_FREE_38_48 = 48;
#elif DEVKITC_REV == 10
constexpr int PIN_BOARD_LED = 48;
constexpr int PIN_FREE_38_48 = 38;
#else
constexpr int PIN_BOARD_LED = -1;
constexpr int PIN_FREE_38_48 = -1;
#endif

// E-paper, SPI (10/11/12 are the FSPI IO_MUX pins). Comments give the pin on the
// FTS02's Raspberry Pi socket (FTS02 schematic 20250819). Power: socket pin 1 = 3V3,
// pin 6 = GND. Socket pins 2/4 (5 V) stay empty: the panel and touch run on 3.3 V.
constexpr int PIN_EPD_CS   = 10;  // socket 24 "CS"
constexpr int PIN_EPD_MOSI = 11;  // socket 19 "SPI_MOSI"
constexpr int PIN_EPD_SCK  = 12;  // socket 23 "SPI_SCK"
constexpr int PIN_EPD_DC   = 9;   // socket 22 "D/C"
constexpr int PIN_EPD_RST  = 8;   // socket 11 "RES"
constexpr int PIN_EPD_BUSY = 13;  // socket 18 "BUSY". UC8253: 0 = busy, 1 = idle

// Touch, FT6336U on I2C (address 0x38), touch cable in the FTS02's TP-FPC2
constexpr int PIN_TOUCH_SDA = 6;   // socket 33 "TP_SDA"
constexpr int PIN_TOUCH_SCL = 7;   // socket 31 "TP_SCL"
constexpr int PIN_TOUCH_INT = 47;  // socket 35 "TP_INT"
constexpr int PIN_TOUCH_RST = PIN_FREE_38_48;  // socket 37 "TP_RST"; set DEVKITC_REV before the touch test

// microSD, 4-bit SDMMC. 10 kΩ pull-ups to 3.3 V on CMD and D0-D3, not on CLK.
constexpr int PIN_SD_CLK = 14;
constexpr int PIN_SD_CMD = 15;
constexpr int PIN_SD_D0  = 16;
constexpr int PIN_SD_D1  = 17;
constexpr int PIN_SD_D2  = 18;
constexpr int PIN_SD_D3  = 21;

// I2S to the CS4398 board. Share GND; leave the board's 3V3_OUT unconnected.
constexpr int PIN_I2S_MCK  = 1;
constexpr int PIN_I2S_BCK  = 2;
constexpr int PIN_I2S_LRCK = 4;
constexpr int PIN_I2S_DATA = 5;

// Buttons: GPIO to one leg, GND to the other, INPUT_PULLUP, pressed = LOW.
constexpr int PIN_BTN_PLAY     = 39;
constexpr int PIN_BTN_VOL_UP   = 40;
constexpr int PIN_BTN_VOL_DOWN = 41;
constexpr int PIN_BTN_POWER    = 42;
