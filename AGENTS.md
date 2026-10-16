# E-ink DAP — agent rules

- `PROJECT.md` is the source of truth for goals, hardware, open decisions and bring-up order. When a ⚠ OPEN item is settled, update it there (state the decision and date) instead of leaving the contradiction in place.
- Once `include/pins.h` exists, it is the only authoritative pin map. Firmware never hard-codes GPIO numbers elsewhere.
- Bring up one subsystem at a time (PROJECT.md §6). Record each test result (pass/fail, date, notes) in PROJECT.md §4.4.
- Owner is an electronics beginner: wiring instructions must name every pin on both ends, and any step that can damage hardware or ears (power, first audio test) gets an explicit warning.
