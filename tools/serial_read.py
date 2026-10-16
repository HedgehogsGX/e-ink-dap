# Reads the board over serial without resetting it (for scripted test runs; use
# `pio device monitor` by hand). Run with ~/.platformio/penv/bin/python.
# Usage: serial_read.py PORT SECONDS [TEXT_TO_SEND ...]
# Opens the ESP32-S3 USB-Serial-JTAG port leaving DTR/RTS asserted, which does not reset it.
# (To reboot into the firmware, use esptool's --after watchdog-reset; an RTS pulse here
# lands in download mode.)
# Sends each TEXT (newline-terminated, 1 s apart) and prints all output for SECONDS.
import sys, time, serial
args = sys.argv[1:]
port, seconds = args[0], float(args[1])
to_send = args[2:]

def open_port():
    for _ in range(80):
        try:
            return serial.Serial(port, 115200, timeout=0.1)
        except Exception:
            time.sleep(0.25)
    sys.exit("could not open " + port)

s = open_port()
end = time.time() + seconds
next_send = time.time() + 1.5
while time.time() < end:
    try:
        if to_send and time.time() >= next_send:
            s.write((to_send.pop(0) + "\n").encode()); next_send = time.time() + 1.0
        data = s.read(4096)
    except Exception:
        try: s.close()
        except Exception: pass
        time.sleep(0.3); s = open_port(); continue
    if data:
        sys.stdout.write(data.decode(errors="replace")); sys.stdout.flush()
