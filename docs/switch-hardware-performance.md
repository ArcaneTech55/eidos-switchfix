# Switch hardware performance build

This branch targets real Nintendo Switch hardware (Tegra X1 / Horizon).
Use title takeover and copy eidos.nro into sdmc:/switch/eidos/. Keep your
existing extract/ and profile/ there.

## Changes and evidence

* Hardware readbacks use one OpenGL transfer per image. Upstream used a
  Ryubing workaround that issued one call per row, including PBO transfers
  during ordinary GPU 2D composition (192 calls per DS screen).
  For Ryubing only, put EIDOS_SWITCH_READPIXELS_ROWS=1 in env.txt.
* devkitA64 builds with -O3 -DNDEBUG, armv8-a+crc+crypto and Cortex-A57
  tuning. Upstream already used -O2 and the correct architecture; this was
  not an accidental Debug build. Floating point semantics are preserved.
* A failed generated-C compile now fails the build instead of printing
  FAIL and continuing.

* The Switch renderer expands and uploads clip-space vertices once per
  snapshot, reusing the VBO across display-size, DS-size and AA passes.
  Existing polygon ordering, run batching, blending and depth rules stay.
* GPU 2D keeps independent palette textures for both screens and only
  converts/uploads changed palettes on Switch.
* Switch GL buffer maps reuse up to four module staging allocations; error
  paths unmap the native buffer. The required native-to-module copy stays.
* Read-only files under extract/ use 64 KiB read-ahead, lazily allocated
  and capped at 4 MiB total. Saves, settings and writable files bypass it.
  Set EIDOS_SWITCH_READAHEAD=0 in env.txt to compare without caching.
  File descriptor positions, seeks and pread save/restore are preserved.
* Worker threads prefer separate application cores from the frame thread,
  within the core mask Horizon grants the process; affinity failures are
  logged. Worker stacks use 4 MiB instead of 16 MiB (24 MiB saved for the
  default two workers), matching the existing game's native fiber budget.

The module's existing ARM64 guard mapping remains in place. Its fallback
still has weaker out-of-bounds protection, as documented upstream; no
additional safety checks were removed. Audio mixing stays on the game
thread because moving it would race the game's ARM7 sound state. Its queue
fill is already bounded; SDL submits playback asynchronously.

The Actions artifact contains eidos.nro and a Switch installation ZIP.
No ROM or extracted game data is included.

## Hardware verification

No real-console measurements have been made by this change's author.
A successful compile does not establish playable FPS or visual correctness.

For comparable results, use the same save and scene, internal resolution,
docked/handheld mode, and CPU/GPU clocks before and after. Check opening,
field movement, battles, menus and display capture effects. stderr.txt
already reports the OpenGL renderer and software-3D fallback transitions.
To record frame/swap timing, add EIDOS_FPS=1 to env.txt; --profile can be
added as a line in args.txt for the existing CPU timing report.

Unsupported GL features have not been shown to cause Mesa software
rasterization. Check the logged renderer (llvmpipe/softpipe would be software)
and the reported GPU/CPU 3D transitions before drawing that conclusion.
